"""QC/RSEQ metadata and lossless recovery of RSX's omitted constant delta curves.

All inputs are local Apex exports. RSEQ parsing is deliberately limited to the
v18 sequence / v19.1 animation descriptor layout used by this exported rig.
The shared tools/fuseanim decoder and its additive rules remain unchanged.
"""
from __future__ import annotations

import math
from pathlib import Path
import re
import shlex
import shutil
import struct
import sys

# Do not create bytecode in the read-only shared decoder directory.
sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'tools/fuseanim'))
from cast import Animation, Cast  # noqa: E402

POV = REPO / 'apex-data/pov'
ANIMS = POV / 'cast/animrig/weapons/rspn101/anims_ptpov_rspn101'
QC = POV / 'smd/animrig/weapons/rspn101/ptpov_rspn101.qc'
RAW = POV / 'raw/animrig/weapons/rspn101/anims_ptpov_rspn101'
ORIGINAL_EMPTY = POV / 'cast_original_empty'
GROUP_A = ('ads_in', 'ads_out', 'idle', 'crouch', 'idle_to_crouch',
           'crouch_to_idle', 'fire', 'jump', 'land', 'sprint', 'sprintraise',
           'sprintslide', 'reload', 'reload_empty', 'wind_effect_layer')
GROUP_B = ('holster', 'draw', 'drawfirst', 'raise', 'lower', 'inspect_basic')
QC_FIELDS = ('sample_animation_names', 'blendwidth', 'blend', 'activity',
             'activitymodifiers', 'fadein', 'fadeout', 'loop', 'delta',
             'autoplay', 'addlayer', 'node', 'transition', 'events', 'qc_line',
             'raw_qc')
_TOKEN = re.compile(r'//[^\n]*|"(?:\\.|[^"\\])*"|[{}]|[^\s{}"]+')
_BLOCK = re.compile(r'^\$(sequence|animation)\s+"([^"]+)"', re.MULTILINE)


def relative(path):
    return Path(path).relative_to(REPO).as_posix()


def walk(node):
    yield node
    for child in node.childNodes:
        yield from walk(child)


def animation(path):
    animations = [node for root in Cast.load(str(path)).Roots()
                  for node in walk(root) if isinstance(node, Animation)]
    if len(animations) != 1:
        raise ValueError(f'{path}: expected exactly one Animation')
    return animations[0]


def cast_metadata(path):
    a = animation(path)
    curves = a.Curves()
    if not curves:
        raise ValueError(f'{path}: RSX omitted curves; frame count is unavailable in this Cast')
    frames = max(max(c.KeyFrameBuffer()) for c in curves) + 1
    modes = {c.Mode() for c in curves}
    if modes not in ({'absolute'}, {'additive'}) or a.CurveModeOverrides():
        raise ValueError(f'{path}: unsupported Cast modes {modes}')
    return dict(frames=frames, fps=a.Framerate(), loop=bool(a.Looping()),
                additive=modes == {'additive'})


def _blocks(text):
    for match in _BLOCK.finditer(text):
        depth, opened = 0, False
        for token in _TOKEN.finditer(text, match.end()):
            if token.group() == '{':
                depth += 1
                opened = True
            elif token.group() == '}':
                depth -= 1
                if opened and depth == 0:
                    raw = text[match.start():token.end()]
                    tokens = [t.group() for t in _TOKEN.finditer(raw)
                              if not t.group().startswith('//')]
                    yield match.group(1), match.group(2), raw, tokens, text.count('\n', 0, match.start()) + 1
                    break
        else:
            raise ValueError(f'unclosed QC block {match.group(2)}')


def _value(token):
    return shlex.split(token, posix=True)[0] if token.startswith('"') else token


def read_qc(path=QC):
    text = Path(path).read_text(encoding='utf8')
    sequences, animations = {}, {}
    for kind, name, raw, tokens, line in _blocks(text):
        if kind == 'animation':
            animations[name] = dict(file=_value(tokens[2]), qc_line=line)
            continue
        if name not in GROUP_A + GROUP_B:
            continue
        seq = dict(sample_animation_names=[], blendwidth=None, blend=[], activity=None,
                   activitymodifiers=[], fadein=None, fadeout=None, loop=False,
                   delta=False, autoplay=False, addlayer=[], node=None, transition=None,
                   events=[], qc_line=line, raw_qc=raw)
        i = 2
        while i < len(tokens):
            token = tokens[i]
            i += 1
            if token in ('{', '}'):
                continue
            if token.startswith('"'):
                seq['sample_animation_names'].append(_value(token))
            elif token in ('loop', 'delta', 'autoplay'):
                seq[token] = True
            elif token in ('blendwidth', 'fadein', 'fadeout'):
                seq[token] = (int if token == 'blendwidth' else float)(tokens[i])
                i += 1
            elif token == 'blend':
                seq['blend'].append(dict(parameter=_value(tokens[i]),
                                         min=float(tokens[i + 1]), max=float(tokens[i + 2])))
                i += 3
            elif token == 'activity':
                seq['activity'] = dict(name=_value(tokens[i]), weight=int(tokens[i + 1]))
                i += 2
            elif token in ('activitymodifier', 'addlayer'):
                seq['activitymodifiers' if token == 'activitymodifier' else token].append(_value(tokens[i]))
                i += 1
            elif token == 'node':
                seq['node'] = _value(tokens[i])
                i += 1
            elif token == 'transition':
                seq['transition'] = [_value(t) for t in tokens[i:i + 2]]
                i += 2
            elif token == 'event':
                event = dict(name=_value(tokens[i]), frame=int(tokens[i + 1]), options=[])
                i += 2
                while i < len(tokens) and tokens[i] != '}':
                    event['options'].append(_value(tokens[i]))
                    i += 1
                seq['events'].append(event)
            else:
                raise ValueError(f'{name} QC line {line}: unsupported option {token}')
        if name in sequences or not seq['sample_animation_names']:
            raise ValueError(f'{name}: duplicate or empty QC sequence')
        sequences[name] = seq
    if set(sequences) != set(GROUP_A + GROUP_B):
        raise ValueError('QC does not contain the complete selected sequence list')
    poses = re.findall(r'^\$poseparameter\s+"([^"]+)"', text, re.MULTILINE)
    return dict(sequences=sequences, animations=animations, poseparameters=poses)


def packed_indices(name, sequence):
    return range(len(sequence['sample_animation_names'])) if name in GROUP_A else range(1)


def selected_clips(qc):
    return [f'{name}_{i}' for name in GROUP_A + GROUP_B
            for i in packed_indices(name, qc['sequences'][name])]


def _fix_offset(value):
    # studio.h:6, FIX_OFFSET (packed short, low bit selects a four-bit shift).
    return (value & 0xFFFE) << (4 * (value & 1))


def read_raw(name, bone_count=102):
    path = RAW / f'{name}.rseq'
    data = path.read_bytes()

    def unpack(fmt, offset):
        if offset < 0 or offset + struct.calcsize(fmt) > len(data):
            raise ValueError(f'{path}: descriptor exceeds file at {offset}')
        return struct.unpack_from(fmt, data, offset)

    def cstring(offset):
        if offset < 0 or offset >= len(data):
            raise ValueError(f'{path}: string exceeds file at {offset}')
        return data[offset:data.index(b'\0', offset)].decode('utf8')

    label = cstring(_fix_offset(unpack('<H', 0)[0]))
    if not label.endswith(f'/ptpov_rspn101/{name}.rseq'):
        raise ValueError(f'{path}: unexpected label {label}')
    count, index_offset = unpack('<HH', 40)
    width, height = unpack('<2B', 84)
    if not count or count != width * height:
        raise ValueError(f'{path}: invalid blend grid {width} x {height}, count {count}')
    weight_index = unpack('<H', 82)[0]
    if weight_index in (1, 3):
        weights = [0.0 if weight_index == 1 else 1.0] * bone_count
    else:
        weights = list(unpack(f'<{bone_count}f', _fix_offset(weight_index)))
    if not all(math.isfinite(w) for w in weights):
        raise ValueError(f'{path}: nonfinite bone weights')
    samples = []
    for i in range(count):
        offset = _fix_offset(unpack('<H', _fix_offset(index_offset) + 2 * i)[0])
        fps, flags, frames, name_offset = unpack('<fIiH', offset)
        if not 0 < fps < 1000 or not 0 < frames <= 100000:
            raise ValueError(f'{path}: invalid animation descriptor at {offset}')
        samples.append(dict(animdesc_offset=offset, animation_name=cstring(offset + _fix_offset(name_offset)),
                            fps=fps, frames=frames, loop=bool(flags & 1), additive=bool(flags & 4),
                            has_data=bool(flags & 0x20000), flags=flags))
    return dict(file=relative(path), label=label, flags=unpack('<I', 4)[0],
                grid=dict(columns=width, rows=height), paramindex=list(unpack('<2h', 44)),
                paramstart=list(unpack('<2f', 48)), paramend=list(unpack('<2f', 56)),
                bone_weights=weights, samples=samples)


def validate_raw(qc, name, raw):
    seq = qc['sequences'][name]
    if len(seq['sample_animation_names']) != len(raw['samples']):
        raise ValueError(f'{name}: QC/RSEQ sample counts disagree')
    if (seq['blendwidth'] or 1) != raw['grid']['columns']:
        raise ValueError(f'{name}: QC/RSEQ blendwidth disagrees')
    for flag, bit in (('loop', 1), ('delta', 4), ('autoplay', 8)):
        if seq[flag] != bool(raw['flags'] & bit):
            raise ValueError(f'{name}: QC/RSEQ {flag} disagrees')
    active = [axis for axis, index in enumerate(raw['paramindex']) if index != -1]
    if len(active) != len(seq['blend']):
        raise ValueError(f'{name}: QC/RSEQ blend parameter count disagrees')
    for blend, axis in zip(seq['blend'], active):
        index = raw['paramindex'][axis]
        if not 0 <= index < len(qc['poseparameters']):
            raise ValueError(f'{name}: invalid poseparameter index {index}')
        if (blend['parameter'] != qc['poseparameters'][index]
                or blend['min'] != raw['paramstart'][axis]
                or blend['max'] != raw['paramend'][axis]):
            raise ValueError(f'{name}: QC/RSEQ blend parameter disagrees')
    for alias, sample in zip(seq['sample_animation_names'], raw['samples']):
        declared = Path(qc['animations'][alias]['file']).stem
        if declared != sample['animation_name'] or seq['delta'] != sample['additive']:
            raise ValueError(f'{name}: QC/RSEQ sample animation disagrees: {alias}')


def blend_position(sequence, raw, index):
    column, row = index % raw['grid']['columns'], index // raw['grid']['columns']
    active = [axis for axis, param in enumerate(raw['paramindex']) if param != -1]
    position, axes = {}, []
    for blend, axis in zip(sequence['blend'], active):
        size = raw['grid']['columns' if axis == 0 else 'rows']
        coordinate = column if axis == 0 else row
        if size < 2:
            raise ValueError('active blend axis has fewer than two samples')
        position[blend['parameter']] = blend['min'] + (blend['max'] - blend['min']) * coordinate / (size - 1)
        axes.append(dict(**blend, axis='column' if axis == 0 else 'row'))
    return dict(column=column, row=row), position, axes


def recover_empty_casts(qc, rig, recovery_dir=None):
    """Materialize only proven no-data additive samples, preserving original Casts.

    RSX modeldata.cpp:1698-1702 omits all curves if ANIM_VALID is clear.
    animdata.cpp:1050-1058 initializes ANIM_DELTA to t=0, q=identity, s=1.
    Frames/flags/weights below come from the original RSEQ, never from a sibling.
    """
    recovered = {}
    for name in GROUP_A + GROUP_B:
        raw = read_raw(name, len(rig))
        validate_raw(qc, name, raw)
        for i in packed_indices(name, qc['sequences'][name]):
            path = ANIMS / f'{name}_{i}.cast'
            cast = Cast.load(str(path))
            a = next(node for root in cast.Roots() for node in walk(root) if isinstance(node, Animation))
            if a.Curves():
                continue
            sample = raw['samples'][i]
            if sample['has_data'] or not sample['additive'] or a.CurveModeOverrides():
                raise ValueError(f'{path}: empty Cast is not a proven constant additive sample')
            if sample['fps'] != a.Framerate() or sample['loop'] != bool(a.Looping()):
                raise ValueError(f'{path}: empty Cast/RSEQ fps or loop disagrees')
            skeleton = a.Skeleton()
            if skeleton is None or [(b.Name(), b.ParentIndex()) for b in skeleton.Bones()] != [(b['name'], b['parent']) for b in rig]:
                raise ValueError(f'{path}: empty Cast skeleton disagrees with the rig')
            original = ORIGINAL_EMPTY / path.name
            if original.exists():
                if original.read_bytes() != path.read_bytes():
                    raise ValueError(f'{path}: preserved original differs; refusing to overwrite')
            else:
                original = path
            if recovery_dir is None:
                raise ValueError(f'{path}: constant sample needs an explicit writable recovery directory')
            recovery_dir = Path(recovery_dir)
            preserved = recovery_dir / 'original' / path.name
            preserved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, preserved)
            frames = list(range(sample['frames']))
            for bone, weight in zip(rig, raw['bone_weights']):
                for channel in ('tx', 'ty', 'tz', 'rq'):
                    curve = a.CreateCurve()
                    curve.SetNodeName(bone['name'])
                    curve.SetKeyPropertyName(channel)
                    curve.SetKeyFrameBuffer(frames)
                    curve.SetMode('additive')
                    curve.SetAdditiveBlendWeight(weight)
                    if channel == 'rq':
                        curve.SetVec4KeyValueBuffer([(0.0, 0.0, 0.0, 1.0)] * sample['frames'])
                    else:
                        curve.SetFloatKeyValueBuffer([0.0] * sample['frames'])
            destination = recovery_dir / path.name
            cast.save(str(destination))
            recovered[path.stem] = destination
    return recovered


def build_sequence_table(qc, cast_overrides=None):
    cast_overrides = cast_overrides or {}
    sequences, recovery = {}, []
    for name in GROUP_A + GROUP_B:
        source = qc['sequences'][name]
        raw = read_raw(name)
        validate_raw(qc, name, raw)
        seq = dict(source, group='A' if name in GROUP_A else 'B',
                   qc_sample_count=len(raw['samples']), grid=raw['grid'],
                   rseq_file=raw['file'], samples=[])
        seq['blend_axes'] = blend_position(source, raw, 0)[2]
        for i in packed_indices(name, source):
            path = ANIMS / f'{name}_{i}.cast'
            metadata = cast_metadata(cast_overrides.get(path.stem, path))
            sample = raw['samples'][i]
            if any(metadata[key] != sample[key] for key in ('frames', 'fps', 'loop', 'additive')):
                raise ValueError(f'{path}: Cast/RSEQ metadata disagrees')
            grid, position, _ = blend_position(source, raw, i)
            row = dict(clip=path.stem, cast_file=relative(path), qc_sample_index=i,
                       animation=source['sample_animation_names'][i], **metadata,
                       blend_grid_position=grid, blend_position=position,
                       rseq_animation=sample)
            seq['samples'].append(row)
            original = ORIGINAL_EMPTY / path.name
            if original.exists():
                recovery.append(dict(clip=path.stem, original_cast_file=relative(original),
                                     original_size=original.stat().st_size,
                                     rseq_file=raw['file'], animdesc_offset=sample['animdesc_offset'],
                                     frames=sample['frames'], reason='ANIM_VALID clear; identity additive curves omitted by RSX'))
        sequences[name] = seq
    return dict(schema_version=1, pack_format='FPOV', pack_version=1, qc_file=relative(QC),
                rig_file=relative(ANIMS.parent / 'ptpov_rspn101.cast'),
                sequence_count=len(sequences), clip_count=len(selected_clips(qc)),
                group_clip_counts={group: sum(len(s['samples']) for s in sequences.values() if s['group'] == group)
                                   for group in ('A', 'B')},
                sample_index_rule=dict(
                    description='Cast index is the zero-based QC sample ordinal, including duplicates; column = index % blendwidth, row = index // blendwidth. QC skips absent blend axes: a single blend in a width-1 grid varies along rows.',
                    sources=[dict(file='tools/apexassets/rsx_source/src/core/mdl/modeldata.cpp', lines=[1660, 1662, 1664]),
                             dict(file='tools/apexassets/rsx_source/src/core/mdl/modeldata_qc.cpp', lines=[1146, 1148, 1168, 1228]),
                             dict(file='tools/apexassets/rsx_source/src/core/mdl/qc.cpp', lines=[2930, 2957, 2959, 2970])]),
                empty_cast_recovery=recovery, sequences=sequences)
