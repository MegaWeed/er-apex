"""T012: verify the old 16-clip FPOV v1 pack and the complete blend-sample pack.

Run from any directory: python tools/apexpov/verify_pov_pack.py
Optional --old, --new and --sequences paths support independent acceptance tests.
Checks never repair inputs. Any failed check prints FAIL and returns exit code 1.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode = True
import numpy as np

from pov_sequences import (ANIMS, GROUP_A, GROUP_B, ORIGINAL_EMPTY, POV, QC_FIELDS,
                           animation, blend_position, cast_metadata, read_qc,
                           read_raw, relative, validate_raw)

# Independent task-list expectation: do not derive this from bake_pov.CLIPS or JSON.
REQUIRED_A = {'ads_in': 2, 'ads_out': 2, 'idle': 2, 'crouch': 2,
              'idle_to_crouch': 2, 'crouch_to_idle': 2, 'fire': 4, 'jump': 4,
              'land': 4, 'sprint': 1, 'sprintraise': 1, 'sprintslide': 1,
              'reload': 2, 'reload_empty': 2, 'wind_effect_layer': 2}
REQUIRED_B = ('holster', 'draw', 'drawfirst', 'raise', 'lower', 'inspect_basic')
REQUIRED_OLD = {'holster', 'ads_out', 'ads_in', 'idle', 'fire', 'reload', 'reload_empty',
                'sprint', 'draw', 'drawfirst', 'raise', 'lower', 'jump', 'land', 'crouch',
                'inspect_basic'}
REQUIRED_CLIPS = {f'{name}_{i}' for name, count in REQUIRED_A.items() for i in range(count)} | {
    f'{name}_0' for name in REQUIRED_B}
# Explicit numbers in docs/research/apex-gun-motion-spec.md, table 2.1.
# Fire/reload counts are unspecified there, so they are checked against Cast/RSEQ.
SPEC_FRAMES = {'ads_in': (16, 12), 'ads_out': (16, 16), 'idle': (191, 191),
               'crouch': (191, 191), 'idle_to_crouch': (29, 29),
               'crouch_to_idle': (29, 29), 'jump': (31, 22, 31, 22),
               'land': (19, 19, 19, 19), 'sprint': (21,), 'sprintraise': (10,),
               'sprintslide': (14,), 'wind_effect_layer': (16, 16)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Reader:
    def __init__(self, data):
        self.data = data
        self.offset = 0

    def take(self, size):
        end = self.offset + size
        require(size >= 0 and end <= len(self.data), f'truncated pack at byte {self.offset}')
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def unpack(self, fmt):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))

    def name(self):
        return self.take(self.unpack('<H')[0]).decode('utf8')


def read_pack(path):
    data = Path(path).read_bytes()
    r = Reader(data)
    require(r.take(4) == b'FPOV', f'{path}: wrong magic')
    require(r.unpack('<I')[0] == 1, f'{path}: expected FPOV version 1')
    bone_count = r.unpack('<I')[0]
    require(0 < bone_count <= 1024, f'{path}: invalid bone count {bone_count}')
    bones = []
    for i in range(bone_count):
        name = r.name()
        parent = r.unpack('<h')[0]
        require(-1 <= parent < i, f'{path}: bone {i} has invalid parent {parent}')
        rest = r.unpack('<7f')
        require(all(math.isfinite(v) for v in rest), f'{path}: nonfinite rest pose')
        bones.append(dict(name=name, parent=parent, rest=rest))
    require(len({b['name'] for b in bones}) == bone_count, f'{path}: duplicate bone names')
    camera = r.unpack('<I')[0]
    require(camera < bone_count, f'{path}: camera outside bone table')
    carrier_count = r.unpack('<I')[0]
    require(carrier_count <= 1024, f'{path}: invalid carrier count')
    carriers = []
    carrier_records = []
    for _ in range(carrier_count):
        name = r.name()
        owner = r.unpack('<I')[0]
        require(owner < bone_count, f'{path}: carrier {name} has invalid owner')
        bind_offset = r.offset
        bind = r.unpack('<14f')
        require(all(math.isfinite(v) for v in bind), f'{path}: nonfinite carrier bind')
        carriers.append(name)
        carrier_records.append(dict(name=name, owner=owner, inverse_mesh_bind=bind[:7],
                                    er_bind=bind[7:], inverse_bind_offset=bind_offset))
    require(len(set(carriers)) == carrier_count, f'{path}: duplicate carriers')
    prefix = data[:r.offset]  # exactly the bytes before the u32 clip count
    clip_count = r.unpack('<I')[0]
    require(0 < clip_count <= 1000, f'{path}: invalid clip count {clip_count}')
    clips = {}
    for _ in range(clip_count):
        name = r.name()
        start = r.offset  # excludes both u16 name length and name bytes
        fps, frames, loop, additive = r.unpack('<fIBB')
        require(0 < fps < 1000 and 0 < frames <= 100000, f'{path}: {name}: invalid fps/frames')
        require(loop in (0, 1) and additive in (0, 1), f'{path}: {name}: invalid flags')
        weights = np.frombuffer(r.take(bone_count * 2 * 4), dtype='<f4').reshape(bone_count, 2)
        poses = np.frombuffer(r.take(frames * bone_count * 7 * 4), dtype='<f4').reshape(frames, bone_count, 7)
        require(np.isfinite(weights).all() and np.isfinite(poses).all(), f'{path}: {name}: nonfinite data')
        require(name not in clips, f'{path}: duplicate clip {name}')
        clips[name] = dict(name=name, frames=frames, fps=fps, loop=bool(loop),
                           additive=bool(additive), payload=data[start:r.offset],
                           weights=weights, poses=poses, payload_offset=start)
    require(r.offset == len(data), f'{path}: {len(data) - r.offset} trailing bytes')
    return dict(path=str(path), data=data, prefix=prefix, bones=bones, camera=camera,
                carrier_count=carrier_count, carrier_records=carrier_records, clips=clips)


def compare_bind_variant(reference, candidate):
    """Mask only the 28 bytes of each inverse mesh bind, then compare all remaining bytes."""
    require(len(reference['data']) == len(candidate['data']), 'pack sizes differ')
    require(reference['bones'] == candidate['bones'] and reference['camera'] == candidate['camera'], 'rig/camera changed')
    require(reference['carrier_count'] == candidate['carrier_count'], 'carrier count changed')
    masked = bytearray(candidate['data'])
    changed = []
    from bake_pov import trs
    for old, new in zip(reference['carrier_records'], candidate['carrier_records']):
        for key in ('name', 'owner', 'er_bind', 'inverse_bind_offset'):
            require(old[key] == new[key], f'{old["name"]}: {key} changed')
        offset = old['inverse_bind_offset']
        masked[offset:offset+28] = reference['data'][offset:offset+28]
        if old['inverse_mesh_bind'] != new['inverse_mesh_bind']:
            a, b = np.asarray(old['inverse_mesh_bind']), np.asarray(new['inverse_mesh_bind'])
            r = trs(b[:3], b[3:])[:3, :3] @ trs(a[:3], a[3:])[:3, :3].T
            sine = np.linalg.norm([r[2, 1]-r[1, 2], r[0, 2]-r[2, 0], r[1, 0]-r[0, 1]]) / 2
            angle = float(np.degrees(np.arctan2(sine, np.clip((np.trace(r)-1)/2, -1, 1))))
            owner_a = np.linalg.inv(trs(a[:3], a[3:]))
            owner_b = np.linalg.inv(trs(b[:3], b[3:]))
            changed.append(dict(carrier=new['name'], owner=candidate['bones'][new['owner']]['name'],
                                inverse_translation_delta_inches=(b[:3]-a[:3]).tolist(),
                                inverse_translation_difference_m=float(np.linalg.norm(b[:3]-a[:3])*.0254),
                                owner_bind_translation_delta_inches=(owner_b[:3, 3]-owner_a[:3, 3]).tolist(),
                                owner_bind_translation_difference_m=float(np.linalg.norm(owner_b[:3, 3]-owner_a[:3, 3])*.0254),
                                rotation_difference_degrees=angle))
    require(bytes(masked) == reference['data'], 'bytes outside inverse mesh binds changed')
    return dict(status='PASS', reference=reference['path'], candidate=candidate['path'], size=len(masked),
                only_inverse_mesh_binds_changed=True, changed_carrier_count=len(changed), changed_carriers=changed)


def check_mesh_binds(pack, legend):
    from bake_pov import inverse_mesh_binds
    expected, audit = inverse_mesh_binds(legend)
    spec = json.loads((Path(__file__).with_name('carriers.json')).read_text(encoding='utf8'))
    require(len(spec['carriers']) == len(pack['carrier_records']), 'carrier mapping count differs')
    for row, carrier in zip(spec['carriers'], pack['carrier_records']):
        require(carrier['name'] == row['carrier'] and pack['bones'][carrier['owner']]['name'] == row['owner'], 'carrier owner mapping differs')
        require(struct.pack('<7f', *carrier['inverse_mesh_bind']) == struct.pack('<7f', *expected[carrier['name']]),
                f'{carrier["name"]}: inverse mesh bind differs from {legend}/R-301 local models')
    return audit


def make_bind_variant(legend, destination):
    """Create a preview pack in the mesh output; preserve the complete local Fuse clip payload."""
    from bake_pov import inverse_mesh_binds
    baseline = read_pack(POV/'fuse_pov.anim')
    inverse, audit = inverse_mesh_binds(legend)
    data = bytearray(baseline['data'])
    for carrier in baseline['carrier_records']:
        offset = carrier['inverse_bind_offset']
        data[offset:offset+28] = struct.pack('<7f', *inverse[carrier['name']])
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    check_mesh_binds(read_pack(destination), legend)
    audit.update(compare_bind_variant(baseline, read_pack(destination)))
    return audit


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f'JSON contains duplicate key {key}')
        result[key] = value
    return result


def check_old_clips(old, new):
    require(set(old['clips']) == REQUIRED_OLD, 'old pack is not the specified original 16-clip baseline')
    for name, clip in old['clips'].items():
        other = new['clips'].get(f'{name}_0')
        require(other is not None, f'missing old sample {name}_0')
        require(clip['payload'] == other['payload'], f'{name} -> {name}_0: bytes after name differ')


def check_clip_list(new, qc):
    require(set(new['clips']) == REQUIRED_CLIPS,
            f'clip set differs: missing {sorted(REQUIRED_CLIPS - set(new["clips"]))}; extra {sorted(set(new["clips"]) - REQUIRED_CLIPS)}')
    for name, count in REQUIRED_A.items():
        require(len(qc['sequences'][name]['sample_animation_names']) == count, f'{name}: unexpected QC sample count')
        actual = {p.stem for p in ANIMS.glob(f'{name}_*.cast')
                  if p.stem.removeprefix(f'{name}_').isdigit()}
        require(actual == {f'{name}_{i}' for i in range(count)}, f'{name}: QC and numeric Cast sample inventory differ')


def check_bones(new):
    require(len(new['bones']) == 102, 'expected 102 bones')
    indices = {bone['name']: i for i, bone in enumerate(new['bones'])}
    for name, index, parent in (('jx_c_pov', 2, 0), ('jx_c_camera', 3, 2)):
        require(indices.get(name) == index and new['bones'][index]['parent'] == parent,
                f'{name}: unexpected index or parent')
        print(f'  {name}: index={index}, parent={parent} ({new["bones"][parent]["name"]})')
    require(new['camera'] == indices['jx_c_camera'], 'camera bone changed')


def check_cast_metadata(new):
    for name, clip in new['clips'].items():
        source = cast_metadata(ANIMS / f'{name}.cast')
        for key in ('frames', 'fps', 'loop'):
            require(clip[key] == source[key], f'{name}: packed {key} differs from Cast')


def check_additive(new, qc):
    for name, clip in new['clips'].items():
        sequence = name.rsplit('_', 1)[0]
        require(clip['additive'] == qc['sequences'][sequence]['delta'], f'{name}: additive differs from QC delta')
        require(clip['additive'] == cast_metadata(ANIMS / f'{name}.cast')['additive'], f'{name}: additive differs from Cast mode')


def check_duplicate(new, name):
    require(new['clips'][f'{name}_1']['payload'] == new['clips'][f'{name}_3']['payload'],
            f'{name}_1 and {name}_3: bytes after name differ')


def check_json_mapping(new, table):
    require(table['schema_version'] == 1 and table['pack_format'] == 'FPOV' and table['pack_version'] == 1,
            'unexpected JSON schema or pack version')
    require(set(table['sequences']) == set(GROUP_A + GROUP_B), 'JSON sequence set differs')
    names = [sample['clip'] for seq in table['sequences'].values() for sample in seq['samples']]
    require(all(count == 1 for count in Counter(names).values()), 'duplicate JSON samples')
    require(set(names) == set(new['clips']), 'JSON samples and packed clips are not bijective')
    require(table['clip_count'] == len(names) and table['sequence_count'] == 21, 'JSON counts disagree')
    require(table['group_clip_counts'] == {'A': 33, 'B': 6}, 'JSON group counts disagree')


def check_json_values(new, table, qc):
    for name in GROUP_A + GROUP_B:
        sequence = table['sequences'][name]
        source = qc['sequences'][name]
        for field in QC_FIELDS:
            require(sequence[field] == source[field], f'{name}: JSON QC field {field} differs')
        raw = read_raw(name)
        validate_raw(qc, name, raw)
        require(sequence['grid'] == raw['grid'] and sequence['rseq_file'] == raw['file'], f'{name}: JSON grid/source differs')
        require(sequence['qc_sample_count'] == len(raw['samples']), f'{name}: JSON QC sample count differs')
        indices = list(range(REQUIRED_A[name])) if name in REQUIRED_A else [0]
        require([s['qc_sample_index'] for s in sequence['samples']] == indices, f'{name}: JSON sample order differs')
        require(sequence['blend_axes'] == blend_position(source, raw, 0)[2], f'{name}: JSON blend axes differ')
        for index, sample in zip(indices, sequence['samples']):
            clip_name = f'{name}_{index}'
            require(sample['clip'] == clip_name and sample['cast_file'] == relative(ANIMS / f'{clip_name}.cast'),
                    f'{name}: JSON sample clip/Cast file differs')
            require(sample['animation'] == source['sample_animation_names'][index], f'{clip_name}: JSON QC animation differs')
            require(sample['rseq_animation'] == raw['samples'][index], f'{clip_name}: JSON RSEQ descriptor differs')
            for key in ('frames', 'fps', 'loop', 'additive'):
                require(sample[key] == new['clips'][clip_name][key], f'{clip_name}: JSON {key} differs')
            grid, position, _ = blend_position(source, raw, index)
            require(sample['blend_grid_position'] == grid and sample['blend_position'] == position,
                    f'{clip_name}: JSON blend position differs')


def check_rsx_order(new, qc):
    for name in GROUP_A + GROUP_B:
        raw = read_raw(name)
        validate_raw(qc, name, raw)
        for index, sample in enumerate(raw['samples']):
            clip = new['clips'].get(f'{name}_{index}')
            if name in REQUIRED_B and index != 0:
                continue
            require(clip is not None, f'{name}_{index}: missing RSEQ sample')
            for key in ('frames', 'fps', 'loop', 'additive'):
                require(clip[key] == sample[key], f'{name}_{index}: RSEQ/pack {key} differs')
    for name in ('jump', 'land'):
        raw = read_raw(name)
        require(raw['samples'][1]['animdesc_offset'] == raw['samples'][3]['animdesc_offset'],
                f'{name}: duplicate QC entries do not point to the same RSEQ animation')


def check_recovery(new, table):
    expected = {'idle_1', 'idle_to_crouch_1', 'crouch_to_idle_1', 'wind_effect_layer_0'}
    entries = table['empty_cast_recovery']
    require(len(entries) == len(expected) and {row['clip'] for row in entries} == expected,
            'constant Cast recovery manifest differs')
    identity = np.array([0, 0, 0, 0, 0, 0, 1], dtype='<f4')
    for row in entries:
        name, index = row['clip'].rsplit('_', 1)
        raw = read_raw(name)
        sample = raw['samples'][int(index)]
        require(not sample['has_data'] and sample['additive'], f'{row["clip"]}: RSEQ has data or is absolute')
        original = ORIGINAL_EMPTY / f'{row["clip"]}.cast'
        require(row['original_cast_file'] == relative(original) and row['rseq_file'] == raw['file'],
                f'{row["clip"]}: recovery source differs')
        require(row['frames'] == sample['frames'] and row['animdesc_offset'] == sample['animdesc_offset'],
                f'{row["clip"]}: recovery descriptor differs')
        require(original.stat().st_size == row.get('original_size', original.stat().st_size),
                f'{row["clip"]}: original Cast size differs')
        source = animation(original)
        require(not source.Curves() and not source.CurveModeOverrides(), f'{row["clip"]}: original Cast was not empty')
        require(source.Framerate() == sample['fps'] and bool(source.Looping()) == sample['loop'],
                f'{row["clip"]}: original Cast metadata differs')
        clip = new['clips'][row['clip']]
        require((clip['poses'] == identity).all(), f'{row["clip"]}: constant sample contains nonidentity deltas')
        weights = np.asarray(raw['bone_weights'], dtype='<f4')[:, None]
        require((clip['weights'] == weights).all(), f'{row["clip"]}: constant sample weights differ from RSEQ')


def spec_differences(new):
    differences = []
    for name, frames in SPEC_FRAMES.items():
        fps = 36.0 if name == 'sprint' else 30.0
        for index, expected_frames in enumerate(frames):
            clip = new['clips'][f'{name}_{index}']
            if clip['frames'] != expected_frames or clip['fps'] != fps:
                differences.append(f'{name}_{index}: actual {clip["frames"]}@{clip["fps"]:g}, table {expected_frames}@{fps:g}')
    return differences


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--legend', choices=('fuse', 'octane'), default='fuse')
    parser.add_argument('--old', type=Path, default=POV / 'fuse_pov.16clips.anim')
    parser.add_argument('--new', type=Path)
    parser.add_argument('--sequences', type=Path)
    args = parser.parse_args()
    directory = POV/'octane' if args.legend == 'octane' else POV
    args.new = args.new or directory/'fuse_pov.anim'
    args.sequences = args.sequences or args.new.with_name('fuse_pov_sequences.json')
    failures = []

    def check(label, action):
        try:
            action()
        except (ValueError, KeyError, TypeError, IndexError, OSError, struct.error) as error:
            failures.append(label)
            print(f'FAIL {label}: {error}')
        else:
            print(f'PASS {label}')

    try:
        old, new = read_pack(args.old), read_pack(args.new)
        table = json.loads(args.sequences.read_text(encoding='utf8'), object_pairs_hook=unique_object)
        qc = read_qc()
    except (ValueError, OSError, struct.error) as error:
        print(f'FAIL input parsing: {error}')
        return 1
    print(f'OLD: {len(old["data"]):,} bytes, {len(old["clips"])} clips')
    print(f'NEW: {len(new["data"]):,} bytes, {len(new["clips"])} clips, {len(new["bones"])} bones, {new["carrier_count"]} carriers')
    print('PASS 01 FPOV v1 structure, valid fields, EOF')  # read_pack checked both files above
    if args.legend == 'octane':
        check('02 only inverse mesh binds differ from complete Fuse pack',
              lambda: compare_bind_variant(read_pack(POV/'fuse_pov.anim'), new))
    else:
        check('02 identical bytes before clip count', lambda: require(old['prefix'] == new['prefix'], 'header/bones/camera/carriers changed'))
    check('03 all 16 old clip payloads unchanged as X_0', lambda: check_old_clips(old, new))
    check('04 exact task clip list and Cast inventory (A=33, B=6)', lambda: check_clip_list(new, qc))
    check('05 102 bones, POV/camera indices and parents', lambda: check_bones(new))
    check('06 frames/fps/loop match all 39 Casts', lambda: check_cast_metadata(new))
    check('07 additive matches QC delta and Cast mode', lambda: check_additive(new, qc))
    check('08 jump_1/jump_3 payloads identical', lambda: check_duplicate(new, 'jump'))
    check('09 land_1/land_3 payloads identical', lambda: check_duplicate(new, 'land'))
    check('10 JSON sample/clip bijection and counts', lambda: check_json_mapping(new, table))
    check('11 JSON QC options, sample metadata, blend coordinates', lambda: check_json_values(new, table, qc))
    check('12 RSX QC ordinal rule, original RSEQ metadata/duplicates', lambda: check_rsx_order(new, qc))
    check('13 four constant delta samples and original Cast provenance', lambda: check_recovery(new, table))
    check('14 inverse mesh binds match selected arms/R-301; fallback vertices absent', lambda: check_mesh_binds(new, args.legend))
    if failures:
        print(f'FAIL: {len(failures)} check(s) failed')
        return 1
    # Audit the reference table separately: do not replace the local game values
    # or weaken any acceptance check when the prose table summarizes a sequence.
    for difference in spec_differences(new):
        print(f'SPEC 2.1 DIFFERENCE: {difference}')
    print('COUNT DIFFERENCE: task expected A=34/B=6=40; listed local samples total A=33/B=6=39.')
    print('PASS: all 14 checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
