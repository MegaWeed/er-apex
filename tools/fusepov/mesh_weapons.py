"""T022 append-only BD/HD mesh inputs; source geometry follows T011 exactly."""
import sys
from pathlib import Path
import shutil
sys.dont_write_bytecode=True
import numpy as np
from PIL import Image
from common import ROOT, read, save, unit, winding, tangent_basis, file_info, Q, MIRROR
sys.path.insert(1,str(ROOT/'tools/apexpov'))
import weapons_common as wc
from mesh_pov import merged_weights, STREAMS
from pov_textures import texture_arrays
from verify_pov import stream
from textures import material_definition


def old_input(part):
 return (wc.ac.BASE_MODEL if part=='bd' else wc.BASE_MODEL)/'fusemesh'/part


def sources():
 rows=[(key,m,mesh,mesh.Name()) for key in wc.CONFIGS for m,meshes,_ in [wc.selected(key)] for mesh in meshes]
 projectile=wc.model(wc.PROJECTILE)
 rows += [(key,projectile,mesh,key+':'+mesh.Name()) for key in ('fragproj_a','fragproj_b') for mesh in projectile.Meshes()]
 return rows


def mapping(key,data=None):
 data=data or wc.layout();carriers=[dict(carrier=c['name'],owner=c['owner_name'],parts=[c['part']]) for c in data['new_carriers'] if c['rig']==key]
 by_name={c['carrier']:c['owner'] for c in carriers}
 owners={n:by_name[c] for n,c in data['maps'][key+'-carriers'].items()}
 return dict(carriers=carriers,owner_of_bone=owners)


def texture_sources():
 result={}
 for key,mdl,mesh,_ in sources():
  assets=wc.CONFIGS[key]['assets'] if key in wc.CONFIGS else wc.CONFIGS['frag']['assets']
  mat=next(m for m in read(assets/'materials.json')['materials'] if m['guid']==f'{mesh.Material().Hash():016x}')
  paths={}
  for t in sorted(mat['textures'],key=lambda t:t['slot']):paths.setdefault(t['usage'].lstrip('_'),assets/next(p for p in t['files'] if p.endswith('.png')))
  wc.require('col' in paths,'Missing local albedo texture')
  name=mesh.Material().Name()
  if name in result:
   wc.require(set(result[name])==set(paths) and all(result[name][k].read_bytes()==paths[k].read_bytes() for k in paths),'Conflicting same-name material texture')
  else:result[name]=paths
 return result


def converted_arrays(paths):
 if all(k in paths for k in ('col','nml','gls','spc')):return texture_arrays(paths)
 # T005 already defines these missing-channel defaults. The Charge Rifle's
 # heat material has col and ilm only; do not borrow another material's maps.
 col=np.asarray(Image.open(paths['col']).convert('RGBA')).copy();col[...,3]=255
 normal=np.tile(np.asarray([128,128,64,255],np.uint8),(col.shape[0],col.shape[1],1))
 metal=np.zeros(col.shape[:2],float)
 return col,normal,metal


def make_textures(out):
 folder=out/'textures';folder.mkdir(parents=True,exist_ok=True)
 for part in ('bd','hd'):
  doc=read(old_input(part)/'mesh.json')
  for mat in doc['materials']:
   for rel in set(mat['textures'].values())|set(mat['sampler_textures'].values()):
    source=old_input(part)/rel;target=out/rel;target.parent.mkdir(parents=True,exist_ok=True)
    if target.is_file():wc.require(source.read_bytes()==target.read_bytes(),'Conflicting preserved texture')
    else:shutil.copyfile(source,target)
 report={}
 for name,paths in texture_sources().items():
  col,normal,metal=converted_arrays(paths)
  for suffix,pixels in [('a',col),('n',normal),('m',np.rint(metal*255).astype(np.uint8))]:Image.fromarray(pixels).save(folder/f'{name}_{suffix}.png')
  report[name]=dict(sources={k:file_info(p) for k,p in paths.items()},primary_slots='First usage occurrence by local slot; secondary channels retained in source export',albedo='Source RGB; alpha 255',normal='Source nml RG; gls R in B',metal='T011/T005 heuristic',missing_channels=[k for k in ('nml','gls','spc') if k not in paths],missing_channel_policy='Source values 待定; use existing T005 neutral normal RG=128/gloss B=64, metal=0 defaults; no other Apex source substituted.')
 save(out/'weapons-texture-audit.json',dict(materials=report,limitations=['Opaque Metal approximation; no emissive, transparency or refraction.','Source UV1 absent for new meshes: duplicate UV0.']))


def convert(out):
 data=wc.layout();docs={};report=dict(format='octane-weapons-mesh-summary',version=1,binding='float32(diag(.0254,.0254,-.0254)*raw Cast); no fitting',bodygroups=data['bodygroups'],omitted_meshes=data['omitted_meshes'],meshes=[],parts={},max_four_weight_loss=0.,old_inputs_byte_identical=True)
 for part in ('bd','hd'):
  folder=out/'fusemesh'/part;folder.mkdir(parents=True,exist_ok=True);source=old_input(part)
  for p in source.rglob('*'):
   if p.is_file():dst=folder/p.relative_to(source);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dst)
  doc=read(folder/'mesh.json');docs[part]=doc
  doc['bones'] += [c['name'] for c in data['new_carriers'] if c['part']==part]
 for key,mdl,mesh,output_name in sources():
  part='bd' if key=='cr' else 'hd';doc=docs[part];folder=out/'fusemesh'/part;mp=mapping(key,data)
  p=np.asarray(mesh.VertexPositionBuffer(),float).reshape(-1,3);n=unit(np.asarray(mesh.VertexNormalBuffer(),float).reshape(-1,3));uv=np.asarray(mesh.VertexUVLayerBuffer(0),float).reshape(-1,2);second=mesh.VertexUVLayerBuffer(1);uv1=np.asarray(second,float).reshape(-1,2) if second is not None else uv.copy();faces=np.asarray(mesh.FaceBuffer(),int).reshape(-1,3)
  wc.require(not mesh.VertexTangentBuffer(),'Unexpected source tangents');_,tangent,sign,tan_fallback=tangent_basis(p,n,uv,faces);bi,bw,loss,rawerror=merged_weights(mdl,mesh,mp)
  if bi.shape[1]<4:
   width=4-bi.shape[1];bi=np.concatenate([bi,np.repeat(bi[:,:1],width,axis=1)],axis=1);bw=np.concatenate([bw,np.zeros((len(bw),width))],axis=1)
  bi=np.asarray([doc['bones'].index(c['carrier']) for c in mp['carriers']])[bi]
  streams=dict(positions=p*np.diag(Q)[:3],normals=unit(n*np.diag(MIRROR)),tangents=np.c_[unit(tangent*np.diag(MIRROR)),-sign],uv0=uv,uv1=uv1,bone_indices=bi,bone_weights=bw,indices=faces)
  name=mesh.Material().Name();mi=next((i for i,m in enumerate(doc['materials']) if m['name']==name),None)
  if mi is None:mi=len(doc['materials']);doc['materials'].append(material_definition(ROOT,part,name))
  i=len(doc['submeshes']);sub=dict(name=output_name,source_model=key,material=mi,vertex_count=len(p),index_count=faces.size,cull_backfaces=True)
  # All new meshes explicitly use the mesh node already used by T021's meshes.
  baseline=read((wc.ac.BASE_MODEL if part=='bd' else wc.BASE_MODEL)/f'readback/export_{part}/flver.json');node=baseline['Meshes'][0]['NodeIndex'];sub['node_name']=baseline['Nodes'][node]['Name']
  for k,(dtype,_) in STREAMS.items():sub[k]=f'mesh{i:03d}.{k}.bin';np.asarray(streams[k],dtype).tofile(folder/sub[k])
  for k,value in [('source_vertex_ids',np.arange(len(p))),('source_triangle_ids',np.arange(len(faces)))]:sub[k]=f'mesh{i:03d}.{k}.bin';np.asarray(value,'<u4').tofile(folder/sub[k])
  doc['submeshes'].append(sub);used=sorted({mdl.Skeleton().Bones()[b].Name() for b,w in zip(mesh.VertexWeightBoneBuffer(),mesh.VertexWeightValueBuffer()) if w>0})
  body=next((g['name'] for g in data['bodygroups'].get(key,[]) if any(s!='blank' and mesh.Name().startswith(__import__('re').sub(r'^'+__import__('re').escape(wc.CONFIGS[key]['stem'])+r'_|_lod\d+$','',Path(s).stem)+'_') for s in g['options'])),'body') if key in wc.CONFIGS else 'body'
  report['meshes'].append(dict(rig=key,name=output_name,source_mesh=mesh.Name(),bodygroup=body,part=part,group=5 if key=='cr' else 6 if key=='frag' else 7 if key=='fragproj_a' else 8,vertices=len(p),triangles=len(faces),material=name,material_guid=f'{mesh.Material().Hash():016x}',weighted_bones=used,carriers=[data['maps'][key+'-carriers'][n] for n in used],four_weight_loss_max=float(loss.max()),source_weight_sum_max_error=rawerror,tangent_fallback_vertices=tan_fallback,uv1='source' if second is not None else 'duplicate UV0',final_winding=winding(streams['positions'],streams['normals'],faces)))
  report['max_four_weight_loss']=max(report['max_four_weight_loss'],float(loss.max()))
 for part,doc in docs.items():
  folder=out/'fusemesh'/part
  for mat in doc['materials']:
   for rel in set(mat['textures'].values())|set(mat['sampler_textures'].values()):dst=folder/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(out/rel,dst)
  save(folder/'mesh.json',doc);old=read(old_input(part)/'mesh.json')
  wc.require(doc['submeshes'][:len(old['submeshes'])]==old['submeshes'] and doc['materials'][:len(old['materials'])]==old['materials'],'Old input metadata changed')
  for sub in old['submeshes']:
   for k in [*STREAMS,'source_vertex_ids','source_triangle_ids']:wc.require((old_input(part)/sub[k]).read_bytes()==(folder/sub[k]).read_bytes(),'Old input stream changed')
  report['parts'][part]=dict(meshes=len(doc['submeshes']),vertices=sum(s['vertex_count'] for s in doc['submeshes']),triangles=sum(s['index_count']//3 for s in doc['submeshes']),materials=len(doc['materials']),carriers=doc['bones'])
 save(out/'weapons-mesh-summary.json',report);return report
