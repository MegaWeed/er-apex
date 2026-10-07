"""T022 readback: exact T021 ranges, Cast/QC/RSEQ, isolation, FK and bindings."""
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode=True
import numpy as np
import weapons_common as wc
from bake_weapons import generate


def verify(out=None,write_report=True,pack_path=None):
 out=wc.checked(out or wc.PACK_ROOT,wc.PACK_ROOT,create=False) if pack_path is None else Path(out)
 actual=wc.read_pack(pack_path or out/'fuse_pov.anim');base=wc.bc.read_pack(wc.BASE_PACK);old=len(base['bones']);req=wc.require
 req(actual['camera']==base['camera'],'Camera changed');req([b['raw'] for b in actual['bones'][:old]]==[b['raw'] for b in base['bones']],'T021 bone bytes changed')
 req([c['raw_v2'] for c in actual['carrier_records'][:71]]==[c['raw_v2'] for c in base['carrier_records']],'T021 carrier/group bytes changed')
 req(list(actual['clips'])[:129]==list(base['clips']),'T021 clip order changed')
 for name,c in base['clips'].items():
  a=actual['clips'][name];req(a['header']==c['header'] and a['weights'][:old].tobytes()==c['weights'].tobytes() and a['poses'][:,:old].tobytes()==c['poses'].tobytes(),f'T021 clip bytes changed: {name}')
  req(not a['weights'][old:].any(),'Old clips move new bones');default=np.tile([0,0,0,0,0,0,1],(len(actual['bones'])-old,1)) if c['additive'] else [b['rest'] for b in actual['bones'][old:]]
  req(np.array_equal(a['poses'][:,old:],np.broadcast_to(np.asarray(default,'<f4'),a['poses'][:,old:].shape)),'Wrong masked pose')
 expected,tables,audit,carriers=generate();req(len(actual['bones'])==len(expected['bones']) and len(actual['carrier_records'])==wc.CARRIER_TOTAL and list(actual['clips'])==list(expected['clips']),'Wrong inventory')
 for a,b in zip(actual['bones'],expected['bones']):req(a['name']==b['name'] and a['parent']==b['parent'] and np.array_equal(a['rest'],np.asarray(b['rest'],'<f4')),'New bone differs from Cast')
 live={b['name'] for b in wc.live_skeleton()['bones']}
 for a,b in zip(actual['carrier_records'],expected['carrier_records']):
  req((a['name'],a['owner'],a['group'])==(b['name'],b['owner'],b['group']),'Carrier identity differs');req(a['name'] in live,'Missing live carrier')
  for k in ('inverse_mesh_bind','er_bind'):req(np.array_equal(a[k],np.asarray(b[k],'<f4')),'Carrier bind differs')
 req(all(c['owner']>=old for c in actual['carrier_records'][71:]),'New carrier owns old bone')
 for name,a in actual['clips'].items():
  b=expected['clips'][name];req(all(a[k]==b[k] for k in ('fps','frames','loop','additive')),f'Clip header differs: {name}')
  req(a['poses'].tobytes()==b['poses'].astype('<f4').tobytes() and a['weights'].tobytes()==b['weights'].astype('<f4').tobytes(),f'Clip source values differ: {name}')
 for key,filename in (('cr','defender_sequences.json'),('frag','frag_sequences.json')):req(json.loads((out/filename).read_text(encoding='utf8'))==tables[key],'QC/events table changed')
 req(json.loads((out/'weapons_carriers.json').read_text(encoding='utf8'))==carriers,'Carrier metadata changed')
 data=wc.layout();error=0.;source_samples=0
 projectile_indices=[b['index'] for b in data['added'] if b['rig'].startswith('fragproj')]
 oldprops=list(range(102,131));r301props=[i for i,b in enumerate(base['bones']) if b['name'] in ('ja_c_propGun','weapon_bone','def_c_base','def_c_bolt','def_c_magazine','def_dust_cover_l','ja_ads_attachment')]
 for key,table in tables.items():
  rig=data['sources'][key];mapping=data['maps'][key];qc=wc.read_qc(wc.CONFIGS[key]['qc']);rows,_=wc.sequence_rows(key,qc)
  lookup={(seq['sequence'],seq['occurrence']):(seq,s) for _,seq,s in rows};other=[b['index'] for b in data['added'] if b['rig']!=key]
  for row in table['clips']:
   a=actual['clips'][row['name']];req(not a['weights'][oldprops+r301props+other+projectile_indices].any(),'Foreign rig has nonzero weight')
   seq,s=lookup[(row['sequence'],row['sequence_occurrence'])];sample=s['blends'][row['blend_index']];source=wc.decode_source(wc.ROOT/row['source']['path'],rig,seq,qc,sample,wc.ROOT/row['rseq_source']['path']);source_samples+=1
   for i,b in enumerate(rig):
    if b['name'] in mapping: req(np.array_equal(a['weights'][mapping[b['name']]],source['weights'][i].astype('<f4')),'QC weights differ')
   if not a['additive']:
    for f in (0,a['frames']//2,a['frames']-1):
     sw=wc.world7(rig,source['poses'][f]);tw=wc.world7(actual['bones'],a['poses'][f])
     for i,b in enumerate(rig):
      if b['name'] in mapping:error=max(error,float(abs(sw[i]-tw[mapping[b['name']]]).max()))
 req(error<2e-4,'Source/pack hierarchy FK differs')
 for c in actual['clips'].values():req(not c['weights'][projectile_indices].any(),'A clip moves the projectile')
 report=dict(status='PASS',bones=len(actual['bones']),carriers=wc.CARRIER_TOTAL,clips=len(actual['clips']),pack_bytes=len(actual['data']),baseline_byte_identical=dict(bones=131,carriers_including_groups=71,clips=129),source_samples=source_samples,source_values_exact=True,events_frames_times_exact=True,foreign_rig_weights_zero=True,projectile_weights_zero=True,new_owners_only=True,carrier_binds_exact=True,all_carriers_live=True,max_source_fk_error=error,runtime_clip_limit=audit['runtime_reader_limit'])
 if write_report:wc.save(out/'weapons-pack-verification.json',report)
 print(f'PASS T022 pack: T021 131 bones / 71 carriers / 129 clips byte-identical; {source_samples} Cast/QC/RSEQ samples; FK {error:.3g}',flush=True);return report


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path);verify(p.parse_args().out)
