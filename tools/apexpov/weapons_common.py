"""T022 local sources, independent weapon branches, groups 5..8 and exact FPOV IO."""
from __future__ import annotations
import json
from pathlib import Path
import re
import struct
import sys
sys.dont_write_bytecode=True
import numpy as np
import battery_common as bc
import ability_common as ac
from ability_common import bp, ps, require, checked, save, info, model, model_world, world7, metadata, live_skeleton
from verify_pov_pack import Reader
ROOT=ac.ROOT
PACK_ROOT=ROOT/'apex-data/pov/octane_weapons'
MODEL_ROOT=ROOT/'er-data/s3/octane_pov_weapons'
BASE_PACK=bc.PACK_ROOT/'fuse_pov.anim'
BASE_MODEL=bc.MODEL_ROOT
CONFIGS={
 'cr':dict(assets=ROOT/'apex-data/assets/defender',part='bd',group=5,model_relative='mdl/techart/mshop/weapons/class/sniper/chargerifle/chargerifle_base_v',rig_relative='animrig/techart/mshop/weapons/class/sniper/chargerifle/chargerifle_base_v_animRig',stem='chargerifle_base_v'),
 'frag':dict(assets=ROOT/'apex-data/assets/frag',part='hd',group=6,model_relative='mdl/weapons/grenades/ptpov_frag_grenade_held',rig_relative='animrig/weapons/grenades/ptpov_frag_grenade_held',stem='ptpov_frag_grenade_held')}
for c in CONFIGS.values():
 c.update(model=c['assets']/('cast/'+c['model_relative']+'_LOD0.cast'),rig=c['assets']/('cast/'+c['rig_relative']+'.cast'),qc=c['assets']/('smd/'+c['rig_relative']+'.qc'),model_qc=c['assets']/('smd/'+c['model_relative']+'.qc'),metadata=c['assets']/('sequences/'+c['stem']+'.json'))
PROJECTILE=ROOT/'apex-data/assets/frag/cast/mdl/Weapons/grenades/m20_f_grenade_projectile_LOD0.cast'
FACE_NAMES=bc.FACE_NAMES
# Claude rework 2026-10-06: L_Forearm and R_Forearm are the parents of the hand, finger and forearm-twist
# carriers (group 0); hidden (the rifle away), their model scale 1e-4 reached those children in some
# frames (the game recomputes them from their parents' model pose) and the arms stretched (battery test
# 01:22). The rifle keeps the ten carriers that are nobody's parents; detailC/D go on def_c_base.
RIFLE_CARRIERS=('L_ForeArmTwist1','R_ForeArmTwist1','L_ShoulderArmor','Spine2_Mantle','SpineArmor1','SpineArmor2','Spine_Mantle','L_Thigh_Skirt','R_Thigh_Skirt','Pelvis_Mantle')
RIFLE_OWNERS=('def_c_base','def_c_reload_rotate','def_c_reload_front','def_c_reload_back','def_c_detailA','def_c_detailB','def_l_battery_01','def_l_battery_02','def_l_battery_03','def_l_battery_04')
FRAG_OWNERS=('def_c_base','def_c_handle','def_c_pin','def_c_twist')
# T021's 71, the rifle's, the held grenade's and the two thrown ones
CARRIER_TOTAL=71+len(RIFLE_CARRIERS)+len(FRAG_OWNERS)+2
EXCLUDED_CR=set('inspect_basic mod_switch_off mod_switch_on mod_add mod_remove optic_add optic_remove fire_select_off fire_select_on overheat_ballistic meleeraise run_wall_layer ads_out_wallrun_onehanded idle_check sprint_heavy sprintholster sprintjump draw_sprint doublejump doublejump_onehanded fire_regrip fire_optic fire_optic_onehanded'.split())
write_pack=ac.write_pack


def bodygroups(key):
 c=CONFIGS[key];text=c['model_qc'].read_text(encoding='utf-8-sig');groups=[]
 choices={'MAINBODY':0,'sight_front':1,'reloader':1,'heat_charge':0} if key=='cr' else {}
 for m in re.finditer(r'\$bodygroup\s+"([^"]+)"\s*\{([^}]+)\}',text):
  options=[s or 'blank' for s,_ in re.findall(r'\bstudio\s+"([^"]+)"|\b(blank)\b',m[2])]
  selected=choices.get(m[1],0);require(selected<len(options),'Bodygroup choice out of range')
  if key=='cr' and m[1] not in choices:require(options[selected]=='blank','Attachment default is not blank')
  groups.append(dict(name=m[1],options=options,selected_index=selected,qc_first_index=0,qc_first=options[0],raw_qc=m[0]))
 for name,studio in re.findall(r'\$body\s+"([^"]+)"\s+"([^"]+)"',text):groups.append(dict(name=name,options=[studio],selected_index=0,qc_first_index=0))
 require(bool(groups),'No local bodygroups');return groups


def selected(key):
 c=CONFIGS[key];mdl=model(c['model']);groups=bodygroups(key);keep=[];omitted=[]
 for mesh in mdl.Meshes():
  candidates=[(g,i) for g in groups for i,s in enumerate(g['options']) if s!='blank' and
   (mesh.Name().startswith(Path(s).stem+'_') or mesh.Name().startswith(re.sub(r'^'+re.escape(c['stem'])+r'_|_lod\d+$','',Path(s).stem)+'_'))]
  require(len(candidates)==1,f'QC mesh mapping: {mesh.Name()}');g,i=candidates[0]
  row=dict(name=mesh.Name(),bodygroup=g['name'],studio_index=i,vertices=mesh.VertexCount(),triangles=len(mesh.FaceBuffer())//3,material=mesh.Material().Name())
  if i==g['selected_index']:keep.append(mesh)
  else:omitted.append(dict(row,reason='T022 excludes attachments or another bodygroup option'))
 require(len(keep)==(4 if key=='cr' else 1),'Unexpected selected mesh count');return mdl,keep,omitted


def node_world(nodes):
 result={}
 def visit(i):
  if i not in result:
   n=nodes[i];local=bp.trs(n['Translation'],n['RotationQuaternion'],n['Scale']);result[i]=visit(n['ParentIndex'])@local if n['ParentIndex']>=0 else local
  return result[i]
 return {n['Name']:visit(i) for i,n in enumerate(nodes)}


def carrier_binds(part):
 source=BASE_MODEL if part=='hd' else ac.BASE_MODEL
 nodes=json.loads((source/f'readback/export_{part}/flver.json').read_text(encoding='utf8'))['Nodes'];binds=node_world(nodes)
 if part=='hd':
  live=live_skeleton()['bones']
  for name in FACE_NAMES:
   b=next(b for b in live if b['name']==name);ref=b['ref'];parent=live[b['parent']]['name']
   require(parent in binds,'Missing face parent');binds[name]=binds[parent]@bp.trs(ref['t'],ref['r'],ref['s'])
 return binds


def layout(base=None):
 base=base or bc.read_pack(BASE_PACK);require((len(base['bones']),len(base['carrier_records']),len(base['clips']))==(131,71,129),'Unexpected T021 baseline')
 bones=[dict(b) for b in base['bones']];pack_index={b['name']:i for i,b in enumerate(bones)};added=[];diffs=[];sources={};maps={};new=[];fallback=[];omitted=[];groups={};totals={}
 for key,c in CONFIGS.items():
  rig=bp.skeleton(c['rig']);idx={b['name']:i for i,b in enumerate(rig)};sources[key]=rig
  mdl,meshes,skip=selected(key);omitted+=skip;groups[key]=bodygroups(key);weights={}
  for mesh in meshes:
   for b,w in zip(mesh.VertexWeightBoneBuffer(),mesh.VertexWeightValueBuffer()):
    if w>0:
     name=mdl.Skeleton().Bones()[b].Name();weights[name]=weights.get(name,0.)+w
  totals[key]=weights;prop=set(weights)|{b['name'] for b in rig if b['name'] not in pack_index}
  for n in list(prop):
   require(n in idx,f'Weighted bone missing from rig: {n}');p=rig[idx[n]]['parent']
   while p>=0:
    name=rig[p]['name']
    if name in pack_index and sum(b['parent']==p for b in rig)>1 and name=='def_c_spineC':break
    prop.add(name);p=rig[p]['parent']
  masked_r301={'def_c_bolt','def_c_magazine','def_dust_cover_l','ja_ads_attachment'}
  mapping={n:pack_index[n] for n in idx if n in pack_index and n not in prop and n not in masked_r301};rest=bp.ea.rest_pose(rig)
  for i,b in enumerate(rig):
   n=b['name']
   if n not in prop:continue
   output=key+':'+n;parentname=rig[b['parent']]['name'] if b['parent']>=0 else None;parent=mapping[parentname] if parentname else -1
   mapping[n]=len(bones);bones.append(dict(name=output,parent=parent,rest=tuple(rest[i,:7])))
   added.append(dict(index=mapping[n],name=output,source_bone=n,parent=bones[parent]['name'] if parent>=0 else None,rig=key,copied=n in pack_index,positive_mesh_weight=n in weights))
  for b in base['bones']:
   if b['name'] not in idx:continue
   p=rig[idx[b['name']]]['parent'];sp=rig[p]['name'] if p>=0 else None;pp=base['bones'][b['parent']]['name'] if b['parent']>=0 else None
   if sp!=pp:diffs.append(dict(rig=key,bone=b['name'],pack_parent=pp,source_parent=sp,copied_for_rig=b['name'] in prop))
  maps[key]=mapping;by_source={};binds=carrier_binds(c['part']);meshbind=model_world(mdl)
  owners,names=(RIFLE_OWNERS,RIFLE_CARRIERS) if key=='cr' else (FRAG_OWNERS,FACE_NAMES[:4])
  for owner,name in zip(owners,names):
   require(owner in weights and mapping[owner]>=131,'Invalid carrier owner')
   by_source[owner]=name;new.append(dict(name=name,owner=mapping[owner],owner_name=bones[mapping[owner]]['name'],source_bone=owner,rig=key,part=c['part'],group=c['group'],total_vertex_weight=weights[owner],inverse_mesh_bind=bp.rigid(np.linalg.inv(meshbind[owner]),owner).tolist(),er_bind=bp.rigid(binds[name],name).tolist()))
  for n in weights:
   if n in by_source:continue
   p=rig[idx[n]]['parent']
   while p>=0 and rig[p]['name'] not in by_source:p=rig[p]['parent']
   require(p>=0,'No ancestor carrier');ancestor=rig[p]['name'];by_source[n]=by_source[ancestor]
   fallback.append(dict(rig=key,source_bone=n,ancestor=ancestor,carrier=by_source[n],total_vertex_weight=weights[n]))
  maps[key+'-carriers']=by_source
  for carrier in new:
   if carrier['rig']==key:carrier['mapped_total_vertex_weight']=sum(weights[n] for n,cname in by_source.items() if cname==carrier['name'])
 projectile=model(PROJECTILE);require(len(projectile.Skeleton().Bones())==1,'Projectile must have one bone')
 pb=projectile.Skeleton().Bones()[0];bind=model_world(projectile)[pb.Name()];bind7=bp.rigid(bind,pb.Name());root=pack_index['jx_c_delta'];hd=carrier_binds('hd')
 for key,name,group in (('fragproj_a','R_eyeA',7),('fragproj_b','R_eyeB',8)):
  owner=len(bones);output=key+':'+pb.Name();bones.append(dict(name=output,parent=root,rest=tuple(bind7)))
  added.append(dict(index=owner,name=output,source_bone=pb.Name(),parent='jx_c_delta',rig=key,copied=True,positive_mesh_weight=True))
  new.append(dict(name=name,owner=owner,owner_name=output,source_bone=pb.Name(),rig=key,part='hd',group=group,total_vertex_weight=sum(m.VertexCount() for m in projectile.Meshes()),mapped_total_vertex_weight=sum(m.VertexCount() for m in projectile.Meshes()),inverse_mesh_bind=bp.rigid(np.linalg.inv(bind),pb.Name()).tolist(),er_bind=bp.rigid(hd[name],name).tolist()))
  maps[key+'-carriers']={pb.Name():name}
 require(len({c['name'] for c in base['carrier_records']+new})==CARRIER_TOTAL,'Carrier collision')
 live={b['name'] for b in live_skeleton()['bones']};require(all(c['name'] in live for c in new),'Carrier absent from live')
 return dict(bones=bones,sources=sources,maps=maps,added=added,parent_differences=diffs,new_carriers=new,carrier_records=[dict(c) for c in base['carrier_records']]+new,ancestor_fallbacks=fallback,bodygroups=groups,omitted_meshes=omitted,weight_totals=totals)


def remap_clip(source,data,key):
 active=[d for d in data['parent_differences'] if not d['copied_for_rig']]
 return ac.remap_clip(source,dict(data,parent_differences=active),key)


def decode_source(path,rig,seq,qc,sample,rawpath):
 animation=ps.animation(path)
 if animation.Curves():return ac.decode_source(path,rig,seq,qc)
 raw=Path(rawpath).read_bytes();flags=sample['flags'];require(flags&4 and not flags&0x20000 and seq['delta'] and not animation.CurveModeOverrides(),'Unproved empty weapon Cast')
 wi=struct.unpack_from('<H',raw,82)[0];offset=(wi&0xfffe)<<(4*(wi&1))
 weights=[0. if wi==1 else 1.]*len(rig) if wi in (1,3) else list(struct.unpack_from(f'<{len(rig)}f',raw,offset))
 listed=[qc['weightlists'][seq['weightlist']][b['name']] for b in rig];require(np.allclose(weights,listed,atol=1e-6),'Empty Cast weights differ')
 require(animation.Framerate()==sample['framerate'] and bool(animation.Looping())==bool(flags&1),'Empty Cast timing differs')
 require([(b.Name(),b.ParentIndex()) for b in animation.Skeleton().Bones()]==[(b['name'],b['parent']) for b in rig],'Empty Cast hierarchy differs')
 return dict(fps=sample['framerate'],frames=sample['frame_count'],loop=bool(flags&1),additive=True,weights=np.repeat(np.asarray(listed)[:,None],2,axis=1),poses=np.tile([0.,0.,0.,0.,0.,0.,1.],(sample['frame_count'],len(rig),1)),constant_delta_source=dict(rseq=info(rawpath),animdesc_offset=sample['animdesc_offset'],flags=flags,reason='ANIM_DELTA set and ANIM_VALID clear; identity delta curves omitted by RSX.'))


def sequence_rows(key,qc):
 c=CONFIGS[key];local=json.loads(c['metadata'].read_text(encoding='utf8'))['sequences'];seen={};rows=[];excluded=[]
 for name,seq in qc['sequences'].items():
  sequence=seq['sequence'];occurrence=seq['occurrence']
  omit=(sequence in EXCLUDED_CR or any(t in sequence for t in ('_sniper','_TEMP','_late'))) if key=='cr' else sequence in ('inspect','run_layer_wall') or 'wallrun' in sequence
  if omit:excluded.append(dict(sequence=sequence,occurrence=occurrence));continue
  # Compare the actual animation filenames in the QC, rather than a duplicate sequence name.
  files=[Path(qc['animations'][a]['file']).stem for a in seq['sample_animation_names']]
  candidates=[s for s in local if s['name']==sequence and s['blend_count']==len(files) and [b['name'] for b in s['blends']]==files and
    (not seq['activity'] or (s['activity']==seq['activity']['name'] and s['activity_weight']==seq['activity']['weight']))]
  require(bool(candidates),f'QC has no matching RSEQ: {key}/{name}/{files}')
  candidates.sort(key=lambda s:s['asset_path']);prior=seen.get(sequence,0)
  s=candidates[min(prior,len(candidates)-1)] if len(candidates)>1 else candidates[0];seen[sequence]=prior+1
  rows.append((name,seq,s))
 return rows,excluded


def read_pack(path):
    """Same v2 layout as T020; accepts the battery group and validates complete records."""
    data = Path(path).read_bytes(); r = Reader(data)
    require(r.take(4) == b'FPOV', 'Not FPOV')
    version, nb = r.unpack('<II')
    require(version == 2 and 0 < nb <= 512, 'Expected FPOV v2')
    bones = []
    for i in range(nb):
        start = r.offset
        name, parent, rest = r.name(), r.unpack('<h')[0], r.unpack('<7f')
        require(-1 <= parent < i, f'Invalid parent: {name}')
        bones.append(dict(name=name, parent=parent, rest=rest, raw=data[start:r.offset]))
    camera, nc = r.unpack('<II')
    require(camera < nb and nc <= 256, 'Invalid camera/carrier count')
    carriers = []
    for _ in range(nc):
        start = r.offset
        name, owner = r.name(), r.unpack('<I')[0]
        inverse, er = r.unpack('<7f'), r.unpack('<7f')
        raw = data[start:r.offset]; group = r.unpack('<B')[0]
        require(owner < nb and group <= 8, f'Invalid carrier: {name}')
        carriers.append(dict(name=name, owner=owner, inverse_mesh_bind=inverse, er_bind=er, group=group,
                             raw=raw, raw_v2=data[start:r.offset]))
    clips = {}; count = r.unpack('<I')[0]
    require(0 < count <= 4096, 'Invalid clip count')
    for _ in range(count):
        start = r.offset; name = r.name()
        fps, frames, loop, additive = r.unpack('<fIBB'); header = data[start:r.offset]
        require(0 < fps < 1000 and 0 < frames <= 100000 and loop in (0, 1) and additive in (0, 1), 'Invalid clip header')
        weights = np.frombuffer(r.take(nb*8), '<f4').reshape(nb, 2)
        poses = np.frombuffer(r.take(frames*nb*28), '<f4').reshape(frames, nb, 7)
        require(name not in clips and np.isfinite(poses).all() and np.isfinite(weights).all(), 'Invalid clip data')
        require(np.max(abs(np.linalg.norm(poses[..., 3:], axis=-1)-1)) < .01, f'Bad quaternion: {name}')
        require((weights >= 0).all() and (weights <= 1).all(), f'Bad weights: {name}')
        clips[name] = dict(name=name, fps=fps, frames=frames, loop=bool(loop), additive=bool(additive),
                           weights=weights, poses=poses, header=header)
    require(r.offset == len(data), 'Trailing bytes')
    require(len({b['name'] for b in bones}) == nb and len({c['name'] for c in carriers}) == nc, 'Duplicate bones/carriers')
    require(np.isfinite([b['rest'] for b in bones]).all() and np.isfinite([c['inverse_mesh_bind']+c['er_bind'] for c in carriers]).all(), 'Nonfinite binding')
    return dict(path=str(path), data=data, version=version, bones=bones, camera=camera, carrier_records=carriers, clips=clips)


def read_qc(path):
    """Parse every local sequence, animation and explicit bone weight list."""
    text = Path(path).read_text(encoding='utf-8-sig')
    weights = {}
    for m in re.finditer(r'\$(defaultweightlist|weightlist)(?:\s+"([^"]+)")?\s*\{([^}]+)\}', text):
        weights[m[2] or 'defaultweightlist'] = {b: float(w) for b, w in re.findall(r'"([^"]+)"\s+([-\d.eE+]+)', m[3])}
    sequences, animations = {}, {}
    occurrences = {}
    for kind, name, raw, tokens, line in ps._blocks(text):
        if kind == 'animation':
            animations[name] = dict(file=ps._value(tokens[2]), fps=float(re.search(r'\bfps\s+([\d.]+)', raw)[1]),
                                    loop='loop' in tokens, delta='delta' in tokens)
            continue
        seq = dict(sample_animation_names=[], blendwidth=None, blend=[], activity=None,
                   activitymodifiers=[], fadein=None, fadeout=None, loop=False, delta=False,
                   autoplay=False, addlayer=[], node=None, transition=None, events=[], posecycle=None,
                   weightlist='defaultweightlist', qc_line=line, raw_qc=raw)
        i = 2
        while i < len(tokens):
            token = tokens[i]; i += 1
            if token in ('{', '}'):
                continue
            if token.startswith('"'):
                seq['sample_animation_names'].append(ps._value(token))
            elif token in ('loop', 'delta', 'autoplay', 'snap'):
                seq[token] = True
            elif token in ('blendwidth', 'fadein', 'fadeout'):
                seq[token] = (int if token == 'blendwidth' else float)(tokens[i]); i += 1
            elif token == 'blend':
                seq['blend'].append(dict(parameter=ps._value(tokens[i]), min=float(tokens[i+1]), max=float(tokens[i+2]))); i += 3
            elif token == 'activity':
                seq['activity'] = dict(name=ps._value(tokens[i]), weight=int(tokens[i+1])); i += 2
            elif token in ('weightlist', 'node', 'posecycle'):
                seq[token] = ps._value(tokens[i]); i += 1
            elif token in ('activitymodifier', 'addlayer'):
                seq['activitymodifiers' if token == 'activitymodifier' else token].append(ps._value(tokens[i])); i += 1
            elif token == 'transition':
                seq['transition'] = [ps._value(t) for t in tokens[i:i+2]]; i += 2
            elif token == 'event':
                event = dict(name=ps._value(tokens[i]), frame=int(tokens[i+1]), options=[]); i += 2
                while i < len(tokens) and tokens[i] != '}':
                    event['options'].append(ps._value(tokens[i])); i += 1
                seq['events'].append(event)
            else:
                raise ValueError(f'{path}:{line}: unsupported QC option {token}')
        require(bool(seq['sample_animation_names']), f'No samples: {name}')
        occurrence = occurrences.get(name, 0)
        occurrences[name] = occurrence + 1
        seq.update(sequence=name, occurrence=occurrence)
        unique = name if occurrence == 0 else name + '_b'
        require(unique not in sequences, 'More than two duplicate QC sequences')
        sequences[unique] = seq
    poses = re.findall(r'^\$poseparameter\s+"([^"]+)"', text, re.MULTILINE)
    return dict(sequences=sequences, animations=animations, weightlists=weights, poseparameters=poses)
