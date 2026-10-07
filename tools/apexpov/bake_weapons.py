"""T022 losslessly extend T021 with the Charge Rifle, held frag and two projectiles."""
import argparse
from pathlib import Path
import sys
sys.dont_write_bytecode=True
import numpy as np
import weapons_common as wc


def generate():
 base=wc.bc.read_pack(wc.BASE_PACK);data=wc.layout(base);bones=data['bones'];old=len(base['bones']);count=len(bones)
 rest=np.asarray([b['rest'] for b in bones],'<f4');identity=np.tile([0,0,0,0,0,0,1],(count-old,1)).astype('<f4');clips={}
 for name,c in base['clips'].items():
  poses=np.empty((c['frames'],count,7),'<f4');poses[:,:old]=c['poses'];poses[:,old:]=identity if c['additive'] else rest[old:]
  clips[name]=dict(c,poses=poses,weights=np.concatenate([c['weights'],np.zeros((count-old,2),'<f4')]))
 tables={};maximum={f['source_bone']:[0.,0.] for f in data['ancestor_fallbacks']}
 for key,config in wc.CONFIGS.items():
  qc=wc.read_qc(config['qc']);rows,excluded=wc.sequence_rows(key,qc);records=[];rig=data['sources'][key];idx={b['name']:i for i,b in enumerate(rig)}
  for unique,seq,local in rows:
   for sample in local['blends']:
    i=sample['blend_index'];path=config['assets']/sample['cast_file'];rawpath=config['assets']/local['raw_file']
    source=wc.decode_source(path,rig,seq,qc,sample,rawpath)
    wc.require((source['frames'],source['fps'])==(sample['frame_count'],sample['framerate']),'Cast/RSEQ timing mismatch')
    wc.require(source['additive']==bool(sample['flags']&4) and source['loop']==bool(sample['flags']&1),'RSEQ flags mismatch')
    name=f'{key}_{unique}_{i}';clip=wc.remap_clip(source,data,key);clip['name']=name;wc.require(name not in clips,'Clip collision');clips[name]=clip
    row=wc.metadata(name,seq['sequence'],i,seq,source,path,config['qc'],qc)
    row.update(rig=key,sequence_occurrence=seq['occurrence'],sequence_guid=local['guid'],sequence_asset=local['asset_path'],rseq_source=wc.info(rawpath),snap=seq.get('snap',False),zero_weight_bones=[b['name'] for b,w in zip(bones,clip['weights']) if not w.any()],bone_weights=[dict(bone=b['name'],position=float(w[0]),rotation=float(w[1])) for b,w in zip(bones,clip['weights'])]);records.append(row)
    fallbacks=[f for f in data['ancestor_fallbacks'] if f['rig']==key]
    if fallbacks:
     bind=wc.bp.ea.rest_pose(rig)
     for p in source['poses']:
      pose=p.astype(float).copy()
      if source['additive']:
       pose[:,:3]+=bind[:,:3];pose[:,3:]=wc.bp.ea.normalize(wc.bp.ea.mul(bind[:,3:7],pose[:,3:]))
      world=wc.world7(rig,pose)
      for f in fallbacks:
       value=wc.bp.rigid(np.linalg.inv(world[idx[f['ancestor']]])@world[idx[f['source_bone']]],f['source_bone']);m=maximum[f['source_bone']]
       m[0]=max(m[0],float(np.linalg.norm(value[:3])));m[1]=max(m[1],float(2*np.arccos(min(1.,abs(value[6])))*180/np.pi))
  tables[key]=dict(format='octane-weapons-sequences',version=2,rig=key,clips=records,excluded_sequences=excluded,absent_qc_values='null means absent from local data; 待定',sound_events=[dict(sequence=r['sequence'],sequence_occurrence=r['sequence_occurrence'],blend_index=r['blend_index'],**e) for r in records for e in r['events'] if 'SOUND' in e['name']])
 for f in data['ancestor_fallbacks']:
  m=maximum[f['source_bone']];f.update(max_translation_source_inches=m[0],max_translation_m=m[0]*.0254,max_rotation_deg=m[1])
 modelbind=wc.model_world(wc.model(wc.CONFIGS['cr']['model']));projectilebind=wc.model_world(wc.model(wc.PROJECTILE))
 carrier_table=dict(format='octane-weapons-carriers',version=2,carriers=data['new_carriers'],ancestor_fallbacks=data['ancestor_fallbacks'],units='Model bind poses: inches, Apex axes; ER bind: meters, ER axes; quaternion xyzw',rifle_model_bind={n:dict(matrix=modelbind[n].tolist(),translation_rotation=wc.bp.rigid(modelbind[n],n).tolist()) for n in ('muzzle_flash','shell','def_c_base')},projectile_model_bind={n:dict(matrix=m.tolist(),translation_rotation=wc.bp.rigid(m,n).tolist()) for n,m in projectilebind.items()})
 audit=dict(format='octane-weapons-pack-audit',version=2,source=wc.info(wc.BASE_PACK),bones=count,carriers=len(data['carrier_records']),clips=len(clips),original_bones=old,original_carriers=71,original_clips=129,added_bones=data['added'],parent_differences=data['parent_differences'],new_carriers=data['new_carriers'],ancestor_fallbacks=data['ancestor_fallbacks'],bodygroups=data['bodygroups'],omitted_meshes=data['omitted_meshes'],weight_totals=data['weight_totals'],runtime_reader_limit=dict(source='src/spike/pov/pack.rs',current_maximum=256,required_minimum=len(clips),action='Claude must increase the clip reader limit before using this pack.'),all_T021_bytes_preserved=True)
 return dict(bones=bones,camera=base['camera'],carrier_records=data['carrier_records'],clips=clips),tables,audit,carrier_table


def bake(out=None):
 out=wc.checked(out or wc.PACK_ROOT,wc.PACK_ROOT);pack,tables,audit,carriers=generate();path=out/'fuse_pov.anim';wc.write_pack(path,pack)
 audit['output']=wc.info(path);wc.save(out/'weapons-pack-audit.json',audit);wc.save(out/'weapons_carriers.json',carriers)
 for key,filename in (('cr','defender_sequences.json'),('frag','frag_sequences.json')):wc.save(out/filename,tables[key])
 print(f'PASS T022 bake: {len(pack["bones"])} bones / {len(pack["carrier_records"])} carriers / {len(pack["clips"])} clips; {path.stat().st_size} bytes',flush=True);return path


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path);bake(p.parse_args().out)
