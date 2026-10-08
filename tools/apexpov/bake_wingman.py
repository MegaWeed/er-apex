"""Wingman: losslessly extend T022's pack with the pistol (`wm:` branch, carrier group 9, clips `wm_*`)."""
import argparse
from pathlib import Path
import sys
sys.dont_write_bytecode=True
import numpy as np
import wingman_common as wm
from weapons_common import ac


def generate():
 base=wm.read_pack(wm.BASE_PACK);data=wm.layout(base);bones=data['bones'];old=len(base['bones']);count=len(bones)
 rest=np.asarray([b['rest'] for b in bones],'<f4');identity=np.tile([0,0,0,0,0,0,1],(count-old,1)).astype('<f4');clips={}
 for name,c in base['clips'].items():
  poses=np.empty((c['frames'],count,7),'<f4');poses[:,:old]=c['poses'];poses[:,old:]=identity if c['additive'] else rest[old:]
  clips[name]=dict(c,poses=poses,weights=np.concatenate([c['weights'],np.zeros((count-old,2),'<f4')]))
 qc=wm.read_qc(wm.CONFIG['qc']);rows,excluded=wm.sequence_rows(qc);records=[];rig=data['sources'][wm.KEY]
 for unique,seq,local in rows:
  for sample in local['blends']:
   i=sample['blend_index'];path=wm.CONFIG['assets']/sample['cast_file'];rawpath=wm.CONFIG['assets']/local['raw_file']
   source=wm.wc.decode_source(path,rig,seq,qc,sample,rawpath)
   wm.require((source['frames'],source['fps'])==(sample['frame_count'],sample['framerate']),'Cast/RSEQ timing mismatch')
   wm.require(source['additive']==bool(sample['flags']&4) and source['loop']==bool(sample['flags']&1),'RSEQ flags mismatch')
   name=f'{wm.KEY}_{unique}_{i}';clip=wm.remap_clip(source,data);clip['name']=name;wm.require(name not in clips,'Clip collision');clips[name]=clip
   row=wm.metadata(name,seq['sequence'],i,seq,source,path,wm.CONFIG['qc'],qc)
   row.update(rig=wm.KEY,sequence_occurrence=seq['occurrence'],sequence_guid=local['guid'],sequence_asset=local['asset_path'],rseq_source=wm.info(rawpath),snap=seq.get('snap',False))
   records.append(row)
 table=dict(format='octane-wingman-sequences',version=1,rig=wm.KEY,clips=records,excluded_sequences=excluded,absent_qc_values='null means absent from local data; 待定',sound_events=[dict(sequence=r['sequence'],sequence_occurrence=r['sequence_occurrence'],blend_index=r['blend_index'],**e) for r in records for e in r['events'] if 'SOUND' in e['name']])
 modelbind=wm.model_world(wm.model(wm.CONFIG['model']))
 carriers=dict(format='octane-wingman-carriers',version=1,carriers=data['new_carriers'],ancestor_fallbacks=data['ancestor_fallbacks'],units='Model bind poses: inches, Apex axes; ER bind: meters, ER axes; quaternion xyzw',pistol_model_bind={n:dict(matrix=modelbind[n].tolist(),translation_rotation=wm.bp.rigid(modelbind[n],n).tolist()) for n in ('muzzle_flash','shell','def_c_base') if n in modelbind})
 audit=dict(format='octane-wingman-pack-audit',version=1,source=wm.info(wm.BASE_PACK),bones=count,carriers=len(data['carrier_records']),clips=len(clips),original_bones=old,original_carriers=wm.BASE_COUNTS[1],original_clips=wm.BASE_COUNTS[2],added_bones=data['added'],parent_differences=data['parent_differences'],new_carriers=data['new_carriers'],ancestor_fallbacks=data['ancestor_fallbacks'],bodygroups=data['bodygroups'],omitted_meshes=data['omitted_meshes'],weight_totals=data['weight_totals'],all_T022_bytes_preserved=True)
 return dict(bones=bones,camera=base['camera'],carrier_records=data['carrier_records'],clips=clips),table,audit,carriers


def bake(out=None):
 out=wm.checked(out or wm.PACK_ROOT,wm.PACK_ROOT);pack,table,audit,carriers=generate();path=out/'fuse_pov.anim';ac.write_pack(path,pack)
 # read back: every T022 byte of the bone, carrier and clip headers kept, clips readable
 back=wm.read_pack(path);base=wm.read_pack(wm.BASE_PACK)
 wm.require(all(a['raw']==b['raw'] for a,b in zip(back['bones'],base['bones'])) and all(a['raw']==b['raw'] and a['group']==b['group'] for a,b in zip(back['carrier_records'],base['carrier_records'])),'T022 records changed')
 old=len(base['bones'])
 for n,c in base['clips'].items():wm.require(np.array_equal(back['clips'][n]['poses'][:,:old],c['poses']) and np.array_equal(back['clips'][n]['weights'][:old],c['weights']),f'T022 clip changed: {n}')
 audit['output']=wm.info(path);wm.save(out/'wingman-pack-audit.json',audit);wm.save(out/'wingman_carriers.json',carriers);wm.save(out/'wingman_sequences.json',table)
 print(f'PASS wingman bake: {len(pack["bones"])} bones / {len(pack["carrier_records"])} carriers / {len(pack["clips"])} clips; {path.stat().st_size} bytes',flush=True);return path


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path);bake(p.parse_args().out)
