"""T020: extend the Octane pack losslessly to FPOV v2, from local Cast/QC only."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import numpy as np
from ability_common import (ROOT, ASSETS, PACK_ROOT, BASE_PACK, CONFIGS, R301_SEQUENCES,
    bp, checked, save, info, read_pack, write_pack, read_qc, layout, decode_source,
    remap_clip, metadata, require)


def generate():
    base = read_pack(BASE_PACK)
    data = layout(base)
    bones = data['bones']
    count = len(bones)
    rest = np.asarray([b['rest'] for b in bones], '<f4')
    identity = np.tile([0, 0, 0, 0, 0, 0, 1], (count-102, 1)).astype('<f4')
    clips = {}
    records = []
    for name, c in base['clips'].items():
        poses = np.empty((c['frames'], count, 7), '<f4')
        poses[:, :102] = c['poses']
        poses[:, 102:] = identity if c['additive'] else rest[102:]
        clips[name] = dict(c, poses=poses, weights=np.concatenate([c['weights'], np.zeros((count-102, 2), '<f4')]))
    omitted = []
    for key, config in CONFIGS.items():
        qc = read_qc(config['qc'])
        local = json.loads(config['metadata'].read_text(encoding='utf8'))
        wanted = [s for s in local['sequences'] if 'surge' not in s['name']]
        omitted += [dict(rig=key, sequence=s['name']) for s in local['sequences'] if 'surge' in s['name']]
        for seq_record in wanted:
            seqname = seq_record['name']; seq = qc['sequences'][seqname]
            require(len(seq['sample_animation_names']) == seq_record['blend_count'], f'{seqname}: QC/sequence blends differ')
            for sample in seq_record['blends']:
                i = sample['blend_index']
                path = ASSETS/sample['cast_file']
                source = decode_source(path, data['sources'][key], seq, qc)
                require((source['frames'], source['fps']) == (sample['frame_count'], sample['framerate']), f'{path}: RSEQ/Cast frame count/fps differs')
                name = f'{config["prefix"]}_{seqname}_{i}'
                clip = remap_clip(source, data, key)
                clip['name'] = name
                clips[name] = clip
                row = metadata(name, seqname, i, seq, source, path, config['qc'], qc)
                row.update(rig=key, preserved_existing=False,
                           zero_weight_bones=[b['name'] for b, w in zip(bones, clip['weights']) if (w == 0).all()])
                records.append(row)
    qc_path = ROOT/'apex-data/pov/smd/animrig/weapons/rspn101/ptpov_rspn101.qc'
    qc = read_qc(qc_path)
    rig = bp.skeleton(bp.RIG)
    for seqname in R301_SEQUENCES:
        seq = qc['sequences'][seqname]
        for i in range(len(seq['sample_animation_names'])):
            name = f'{seqname}_{i}'; path = bp.ANIMS/(name+'.cast')
            source = decode_source(path, rig, seq, qc)
            if name in base['clips']:
                old = base['clips'][name]
                for field in ('frames', 'fps', 'loop', 'additive'):
                    require(old[field] == source[field], f'{name}: duplicate {field} differs')
                require(old['weights'].tobytes() == source['weights'].astype('<f4').tobytes(), f'{name}: duplicate weights differ')
                require(old['poses'].tobytes() == source['poses'].astype('<f4').tobytes(), f'{name}: duplicate poses differ')
            else:
                poses = np.empty((source['frames'], count, 7), '<f4')
                poses[:, :102] = source['poses']
                poses[:, 102:] = identity if source['additive'] else rest[102:]
                clips[name] = dict(source, name=name, poses=poses,
                    weights=np.concatenate([source['weights'], np.zeros((count-102, 2))]).astype('<f4'))
            row = metadata(name, seqname, i, seq, source, path, qc_path, qc)
            row.update(rig='r301', preserved_existing=name in base['clips'],
                       zero_weight_bones=[b['name'] for b, w in zip(bones, clips[name]['weights']) if (w == 0).all()])
            records.append(row)
    table = dict(format='octane-ability-sequences', version=2, sources=[info(BASE_PACK)],
                 clips=records, omitted_surge_sequences=omitted,
                 absent_qc_values='null means absent from local QC; no inferred defaults')
    audit = dict(format='octane-ability-pack-audit', version=2, source=info(BASE_PACK),
        bones=count, carriers=len(data['carrier_records']), clips=len(clips),
        added_bones=data['added'], parent_differences=data['parent_differences'],
        new_carriers=data['new_carriers'], ancestor_carrier_fallbacks=data['ancestor_fallbacks'],
        current_carriers=[dict(index=i, carrier=c['name'], owner=bones[c['owner']]['name'], group=c['group'])
                          for i, c in enumerate(data['carrier_records'][:51])],
        duplicate_clips_kept=[r['name'] for r in records if r['preserved_existing']],
        prop_branch_rule='Copy weapon-only ancestors through ja_c_propGun, stopping at body branch def_c_spineC. The local ability tracks move ja_c_propGun; sharing it would move the R-301.',
        original_bone_count=102, original_carrier_count=51, original_clip_count=39,
        carrier_correction='Revision 4: carriers are distinct live Xtra bones in authorized HD/LG template copies; no face/body carrier reuse.',
        live_skeleton=info(ROOT/'er-data/skeleton/c0000_live_skeleton.json'), all_carriers_in_live_skeleton=True,
        no_input_repair=True, no_hash_calculations=True)
    return dict(bones=bones, camera=base['camera'], carrier_records=data['carrier_records'], clips=clips), table, audit


def bake(out=None):
    out = checked(out or PACK_ROOT, PACK_ROOT)
    pack, table, audit = generate()
    path = out/'fuse_pov.anim'
    write_pack(path, pack)
    audit['output'] = info(path)
    save(out/'ability_sequences.json', table)
    save(out/'ability-pack-audit.json', audit)
    print(f'PASS T020 bake: FPOV v2; {len(pack["bones"])} bones; {len(pack["carrier_records"])} carriers; '
          f'{len(pack["clips"])} clips; {path.stat().st_size} bytes; duplicates kept {audit["duplicate_clips_kept"]}', flush=True)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, help='Directory inside apex-data/pov/octane_ability')
    bake(parser.parse_args().out)
