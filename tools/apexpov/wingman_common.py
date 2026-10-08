"""Wingman (replaces the R-301 in the hands): T022's Charge Rifle recipe for `wingman_base_v`, one more
independent weapon branch `wm:` and carrier group 9 on part BD, appended to T022's pack and 998."""
from __future__ import annotations
import json
from pathlib import Path
import re
import sys
sys.dont_write_bytecode=True
import numpy as np
import weapons_common as wc
from weapons_common import ac, bp, require, checked, save, info, model, model_world, world7, metadata, live_skeleton, read_qc
ROOT=wc.ROOT
PACK_ROOT=ROOT/'apex-data/pov/octane_wingman'
MODEL_ROOT=ROOT/'er-data/s3/octane_pov_wingman'
BASE_PACK=wc.PACK_ROOT/'fuse_pov.anim'
BASE_MODEL=wc.MODEL_ROOT
KEY='wm'
GROUP=9
CONFIG=dict(assets=ROOT/'apex-data/assets/wingman',part='bd',group=GROUP,model_relative='mdl/techart/mshop/weapons/class/pistol/wingman/wingman_base_v',rig_relative='animrig/techart/mshop/weapons/class/pistol/wingman/wingman_base_v_animRig',stem='wingman_base_v')
CONFIG.update(model=CONFIG['assets']/('cast/'+CONFIG['model_relative']+'_LOD0.cast'),rig=CONFIG['assets']/('cast/'+CONFIG['rig_relative']+'.cast'),qc=CONFIG['assets']/('smd/'+CONFIG['rig_relative']+'.qc'),model_qc=CONFIG['assets']/('smd/'+CONFIG['model_relative']+'.qc'),metadata=CONFIG['assets']/('sequences/'+CONFIG['stem']+'.json'))
# The pistol's weighted bones (body_0 only: sights, suppressors, lasers and the boosted magazine are
# attachments) on the only live leaf bones of part BD that are enabled in its template and no earlier
# carrier uses (nobody's parent: see T022's Claude rework on L_Forearm/R_Forearm). Three: the frame,
# the parts that move most (taclight: 2.2 cm in the reloads, its child taclight1 spins 180 deg;
# detailB: 45 deg in the fire). toprail (1.7 cm), detailC (2.2 cm), trigger (still) and the other
# children ride on their ancestors (rigid).
OWNERS=('def_c_base','def_c_taclight','def_c_detailB')
CARRIERS=('R_ThighTwist','R_Hip','L_Hip')
BASE_COUNTS=(170,87,301)
# T022's Charge Rifle exclusions (attachments, optics, wallrun, inspect, sprint extras) plus the TEMP/late ones
EXCLUDED=wc.EXCLUDED_CR


def bodygroups():
 text=CONFIG['model_qc'].read_text(encoding='utf-8-sig');groups=[]
 for m in re.finditer(r'\$bodygroup\s+"([^"]+)"\s*\{([^}]+)\}',text):
  options=[s or 'blank' for s,_ in re.findall(r'\bstudio\s+"([^"]+)"|\b(blank)\b',m[2])]
  groups.append(dict(name=m[1],options=options,selected_index=None,note='attachment: not shown'))
 for name,studio in re.findall(r'\$body\s+"([^"]+)"\s+"([^"]+)"',text):groups.append(dict(name=name,options=[studio],selected_index=0,qc_first_index=0))
 return groups


def selected():
 mdl=model(CONFIG['model']);keep=[];omitted=[]
 for mesh in mdl.Meshes():
  row=dict(name=mesh.Name(),vertices=mesh.VertexCount(),triangles=len(mesh.FaceBuffer())//3,material=mesh.Material().Name())
  if mesh.Name().startswith('body_0_'):keep.append(mesh)
  else:omitted.append(dict(row,reason='Wingman: attachment bodygroup, not shown'))
 require(len(keep)==1,'Unexpected Wingman body mesh count');return mdl,keep,omitted


def read_pack(path):
 """weapons_common.read_pack with group 9 allowed."""
 data=Path(path).read_bytes();r=wc.Reader(data)
 require(r.take(4)==b'FPOV','Not FPOV');version,nb=r.unpack('<II');require(version==2 and 0<nb<=512,'Expected FPOV v2')
 bones=[]
 for i in range(nb):
  start=r.offset;name,parent,rest=r.name(),r.unpack('<h')[0],r.unpack('<7f');require(-1<=parent<i,f'Invalid parent: {name}');bones.append(dict(name=name,parent=parent,rest=rest,raw=data[start:r.offset]))
 camera,nc=r.unpack('<II');require(camera<nb and nc<=256,'Invalid camera/carrier count');carriers=[]
 for _ in range(nc):
  start=r.offset;name,owner=r.name(),r.unpack('<I')[0];inverse,er=r.unpack('<7f'),r.unpack('<7f');raw=data[start:r.offset];group=r.unpack('<B')[0]
  require(owner<nb and group<=GROUP,f'Invalid carrier: {name}');carriers.append(dict(name=name,owner=owner,inverse_mesh_bind=inverse,er_bind=er,group=group,raw=raw))
 clips={};count=r.unpack('<I')[0];require(0<count<=4096,'Invalid clip count')
 for _ in range(count):
  start=r.offset;name=r.name();fps,frames,loop,additive=r.unpack('<fIBB');header=data[start:r.offset]
  weights=np.frombuffer(r.take(nb*8),'<f4').reshape(nb,2);poses=np.frombuffer(r.take(frames*nb*28),'<f4').reshape(frames,nb,7)
  require(name not in clips and np.isfinite(poses).all(),'Invalid clip data');clips[name]=dict(name=name,fps=fps,frames=frames,loop=bool(loop),additive=bool(additive),weights=weights,poses=poses,header=header)
 require(r.offset==len(data),'Trailing bytes')
 return dict(path=str(path),data=data,version=version,bones=bones,camera=camera,carrier_records=carriers,clips=clips)


def layout(base=None):
 base=base or read_pack(BASE_PACK);require((len(base['bones']),len(base['carrier_records']),len(base['clips']))==BASE_COUNTS,'Unexpected T022 baseline')
 bones=[dict(b) for b in base['bones']];pack_index={b['name']:i for i,b in enumerate(bones)};added=[];diffs=[];new=[];fallback=[];old=len(bones)
 rig=bp.skeleton(CONFIG['rig']);idx={b['name']:i for i,b in enumerate(rig)}
 mdl,meshes,omitted=selected();weights={}
 for mesh in meshes:
  for b,w in zip(mesh.VertexWeightBoneBuffer(),mesh.VertexWeightValueBuffer()):
   if w>0:name=mdl.Skeleton().Bones()[b].Name();weights[name]=weights.get(name,0.)+w
 prop=set(weights)|{b['name'] for b in rig if b['name'] not in pack_index}
 for n in list(prop):
  require(n in idx,f'Weighted bone missing from rig: {n}');p=rig[idx[n]]['parent']
  while p>=0:
   name=rig[p]['name']
   if name in pack_index and sum(b['parent']==p for b in rig)>1 and name=='def_c_spineC':break
   prop.add(name);p=rig[p]['parent']
 # the R-301's own bones in the pack: the pistol's same-named ones are copies, never mapped onto the rifle
 masked_r301={'def_c_bolt','def_c_magazine','def_dust_cover_l','ja_ads_attachment','def_c_trigger','def_c_detailB','def_c_detailC','def_c_base','weapon_bone'}
 mapping={n:pack_index[n] for n in idx if n in pack_index and n not in prop and n not in masked_r301};rest=bp.ea.rest_pose(rig)
 for i,b in enumerate(rig):
  n=b['name']
  if n not in prop and n not in masked_r301:continue
  if n in mapping:continue
  output=KEY+':'+n;parentname=rig[b['parent']]['name'] if b['parent']>=0 else None
  require(parentname is None or parentname in mapping,f'Parent not placed before child: {n}')
  parent=mapping[parentname] if parentname else -1
  mapping[n]=len(bones);bones.append(dict(name=output,parent=parent,rest=tuple(rest[i,:7])))
  added.append(dict(index=mapping[n],name=output,source_bone=n,parent=bones[parent]['name'] if parent>=0 else None,rig=KEY,copied=n in pack_index,positive_mesh_weight=n in weights))
 for b in base['bones']:
  if b['name'] not in idx:continue
  p=rig[idx[b['name']]]['parent'];sp=rig[p]['name'] if p>=0 else None;pp=base['bones'][b['parent']]['name'] if b['parent']>=0 else None
  if sp!=pp:diffs.append(dict(rig=KEY,bone=b['name'],pack_parent=pp,source_parent=sp,copied_for_rig=b['name'] in prop or b['name'] in masked_r301))
 by_source={};binds=wc.carrier_binds(CONFIG['part']);meshbind=model_world(mdl)
 for owner,name in zip(OWNERS,CARRIERS):
  require(owner in weights and mapping[owner]>=old,f'Invalid carrier owner: {owner}')
  by_source[owner]=name;new.append(dict(name=name,owner=mapping[owner],owner_name=bones[mapping[owner]]['name'],source_bone=owner,rig=KEY,part=CONFIG['part'],group=GROUP,total_vertex_weight=weights[owner],inverse_mesh_bind=bp.rigid(np.linalg.inv(meshbind[owner]),owner).tolist(),er_bind=bp.rigid(binds[name],name).tolist()))
 for n in weights:
  if n in by_source:continue
  p=rig[idx[n]]['parent']
  while p>=0 and rig[p]['name'] not in by_source:p=rig[p]['parent']
  require(p>=0,'No ancestor carrier');ancestor=rig[p]['name'];by_source[n]=by_source[ancestor]
  fallback.append(dict(rig=KEY,source_bone=n,ancestor=ancestor,carrier=by_source[n],total_vertex_weight=weights[n]))
 for carrier in new:carrier['mapped_total_vertex_weight']=sum(weights[n] for n,cname in by_source.items() if cname==carrier['name'])
 require(len({c['name'] for c in base['carrier_records']+new})==BASE_COUNTS[1]+len(CARRIERS),'Carrier collision')
 live={b['name'] for b in live_skeleton()['bones']};require(all(c['name'] in live for c in new),'Carrier absent from live')
 return dict(bones=bones,sources={KEY:rig},maps={KEY:mapping,KEY+'-carriers':by_source},added=added,parent_differences=diffs,new_carriers=new,carrier_records=[dict(c) for c in base['carrier_records']]+new,ancestor_fallbacks=fallback,bodygroups={KEY:bodygroups()},omitted_meshes=omitted,weight_totals={KEY:weights})


def remap_clip(source,data):
 active=[d for d in data['parent_differences'] if not d['copied_for_rig']]
 return ac.remap_clip(source,dict(data,parent_differences=active),KEY)


def sequence_rows(qc):
 local=json.loads(CONFIG['metadata'].read_text(encoding='utf8'))['sequences'];seen={};rows=[];excluded=[]
 for name,seq in qc['sequences'].items():
  sequence=seq['sequence'];occurrence=seq['occurrence']
  if sequence in EXCLUDED or any(t in sequence for t in ('_sniper','_TEMP','_late')):excluded.append(dict(sequence=sequence,occurrence=occurrence));continue
  files=[Path(qc['animations'][a]['file']).stem for a in seq['sample_animation_names']]
  candidates=[s for s in local if s['name']==sequence and s['blend_count']==len(files) and [b['name'] for b in s['blends']]==files and
    (not seq['activity'] or (s['activity']==seq['activity']['name'] and s['activity_weight']==seq['activity']['weight']))]
  require(bool(candidates),f'QC has no matching RSEQ: {KEY}/{name}/{files}')
  candidates.sort(key=lambda s:s['asset_path']);prior=seen.get(sequence,0)
  s=candidates[min(prior,len(candidates)-1)] if len(candidates)>1 else candidates[0];seen[sequence]=prior+1
  rows.append((name,seq,s))
 return rows,excluded
