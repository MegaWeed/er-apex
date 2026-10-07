"""T021: retain the entire T020 pack and append the local battery rig/clips/carriers."""
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import numpy as np
import battery_common as bc


def generate():
    base = bc.read_pack(bc.BASE_PACK); data = bc.layout(base)
    bones = data['bones']; old = len(base['bones']); count = len(bones)
    rest = np.asarray([b['rest'] for b in bones], '<f4')
    identity = np.tile([0,0,0,0,0,0,1], (count-old,1)).astype('<f4')
    clips = {}
    for name, c in base['clips'].items():
        poses = np.empty((c['frames'], count, 7), '<f4'); poses[:,:old] = c['poses']
        poses[:,old:] = identity if c['additive'] else rest[old:]
        clips[name] = dict(c, poses=poses, weights=np.concatenate([c['weights'], np.zeros((count-old,2),'<f4')]))
    qc = bc.read_qc(bc.CONFIG['qc']); local = json.loads(bc.CONFIG['metadata'].read_text(encoding='utf8'))
    records = []; max_rel = {f['source_bone']:[0.,0.] for f in data['ancestor_fallbacks']}
    rig = data['sources']['battery']; idx = {b['name']:i for i,b in enumerate(rig)}
    for s in local['sequences']:
        seqname = s['name']; seq = qc['sequences'][seqname]
        bc.require(len(seq['sample_animation_names']) == s['blend_count'], 'QC blend count differs')
        for sample in s['blends']:
            i = sample['blend_index']; path = bc.ASSETS/sample['cast_file']
            source = bc.decode_source(path, rig, seq, qc)
            bc.require((source['frames'],source['fps']) == (sample['frame_count'],sample['framerate']), 'RSEQ/Cast timing differs')
            name = f'battery_{seqname}_{i}'; clip = bc.remap_clip(source,data,'battery'); clip['name'] = name
            bc.require(name not in clips, 'Clip collision'); clips[name] = clip
            row = bc.metadata(name,seqname,i,seq,source,path,bc.CONFIG['qc'],qc)
            row.update(rig='battery', snap=seq.get('snap',False), zero_weight_bones=[b['name'] for b,w in zip(bones,clip['weights']) if not w.any()],
                       bone_weights=[dict(bone=b['name'],position=float(w[0]),rotation=float(w[1])) for b,w in zip(bones,clip['weights'])])
            records.append(row)
            if max_rel:
                for pose in source['poses']:
                    p = pose.astype(float).copy()
                    if source['additive']:
                        bind = bc.bp.ea.rest_pose(rig)
                        p[:,:3] += bind[:,:3]; p[:,3:] = bc.bp.ea.normalize(bc.bp.ea.mul(bind[:,3:7],p[:,3:]))
                    world = bc.world7(rig,p)
                    for f in data['ancestor_fallbacks']:
                        rel = np.linalg.inv(world[idx[f['ancestor']]])@world[idx[f['source_bone']]]
                        r = bc.bp.rigid(rel,f['source_bone'])
                        value = max_rel[f['source_bone']]
                        value[0] = max(value[0], float(np.linalg.norm(r[:3])))
                        value[1] = max(value[1], float(2*np.arccos(min(1.,abs(r[6])))*180/np.pi))
    for f in data['ancestor_fallbacks']:
        f.update(max_translation_source_units=max_rel[f['source_bone']][0],max_translation_m=max_rel[f['source_bone']][0]*.0254,
                 max_rotation_deg=max_rel[f['source_bone']][1])
    table = dict(format='octane-battery-sequences',version=2,sources=[bc.info(bc.BASE_PACK)],clips=records,
                 absent_qc_values='null means absent from local QC; 待定',sound_events=[dict(sequence=r['sequence'],blend_index=r['blend_index'],**e)
                 for r in records for e in r['events'] if 'SOUND' in e['name']])
    audit = dict(format='octane-battery-pack-audit',version=2,source=bc.info(bc.BASE_PACK),bones=count,
        carriers=len(data['carrier_records']),clips=len(clips),original_bone_count=old,original_carrier_count=len(base['carrier_records']),
        original_clip_count=len(base['clips']),added_bones=data['added'],parent_differences=data['parent_differences'],
        new_carriers=data['new_carriers'],ancestor_carrier_fallbacks=data['ancestor_fallbacks'],bodygroups=data['bodygroups'],
        omitted_meshes=data['omitted_meshes'],weight_priority=data['weight_priority'],face_nodes_required=[c['name'] for c in data['new_carriers'] if c['name'] in bc.FACE_NAMES],
        prop_branch_rule='T020: copy weapon-only ancestors through ja_c_propGun; stop at the shared body branch.',
        old_pack_bytes_preserved=True,no_hash_calculations=True)
    return dict(bones=bones,camera=base['camera'],carrier_records=data['carrier_records'],clips=clips),table,audit


def bake(out=None):
    out = bc.checked(out or bc.PACK_ROOT,bc.PACK_ROOT)
    pack, table, audit = generate(); path = out/'fuse_pov.anim'
    bc.write_pack(path,pack); audit['output'] = bc.info(path)
    bc.save(out/'battery_sequences.json',table); bc.save(out/'battery-pack-audit.json',audit)
    print(f'PASS T021 bake: {len(pack["bones"])} bones / {len(pack["carrier_records"])} carriers / {len(pack["clips"])} clips; {path.stat().st_size} bytes',flush=True)
    return path


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--out',type=Path)
    bake(parser.parse_args().out)
