"""Wingman: append the pistol's body to T022's BD mesh input; source geometry follows T011 exactly."""
import sys
from pathlib import Path
import shutil
sys.dont_write_bytecode=True
import numpy as np
from common import ROOT, read, save, unit, winding, tangent_basis, file_info, Q, MIRROR
sys.path.insert(1,str(ROOT/'tools/apexpov'))
import wingman_common as wm
from mesh_pov import merged_weights, STREAMS
from mesh_weapons import converted_arrays
from textures import material_definition
PART='bd'


def old_input():
 return wm.BASE_MODEL/'fusemesh'/PART


def mapping(data):
 carriers=[dict(carrier=c['name'],owner=c['owner_name'],parts=[c['part']]) for c in data['new_carriers']]
 by_name={c['carrier']:c['owner'] for c in carriers}
 return dict(carriers=carriers,owner_of_bone={n:by_name[c] for n,c in data['maps'][wm.KEY+'-carriers'].items()})


# A skin: a folder with `Wingman_Default_col` / `_spc` (.png, or .dds converted with texconv into the
# output's inputs/skin/) replacing the base material's albedo and specular (build_wingman.py --skin).
SKIN={'dir':None}
SKIN_MATERIAL='wingman_base_main'


def skin_paths(out):
 folder=SKIN['dir']
 if folder is None:return {}
 folder=Path(folder);dest=out/'inputs/skin';dest.mkdir(parents=True,exist_ok=True);paths={}
 for usage in ('col','spc','nml','gls'):
  png=folder/f'Wingman_Default_{usage}.png';dds=folder/f'Wingman_Default_{usage}.dds'
  if png.is_file():shutil.copyfile(png,dest/png.name);paths[usage]=dest/png.name
  elif dds.is_file():
   import subprocess
   subprocess.run([str(ROOT/'tools/bin/texconv/texconv.exe'),'-nologo','-y','-ft','png','-f','R8G8B8A8_UNORM','-o',str(dest),str(dds)],check=True,capture_output=True)
   paths[usage]=dest/f'Wingman_Default_{usage}.png'
 wm.require('col' in paths,f'No Wingman_Default_col in the skin folder {folder}')
 return paths


def texture_sources(meshes,out=None):
 result={}
 materials=read(wm.CONFIG['assets']/'materials.json')['materials']
 skin=skin_paths(out) if out is not None else {}
 for mesh in meshes:
  mat=next(m for m in materials if m['guid']==f'{mesh.Material().Hash():016x}');paths={}
  for t in sorted(mat['textures'],key=lambda t:t['slot']):paths.setdefault(t['usage'].lstrip('_'),wm.CONFIG['assets']/next(p for p in t['files'] if p.endswith('.png')))
  if mesh.Material().Name()==SKIN_MATERIAL:paths.update(skin)
  wm.require('col' in paths,'Missing local albedo texture');result[mesh.Material().Name()]=paths
 return result


def make_textures(out,meshes):
 from PIL import Image
 folder=out/'textures';folder.mkdir(parents=True,exist_ok=True)
 doc=read(old_input()/'mesh.json')
 for mat in doc['materials']:
  for rel in set(mat['textures'].values())|set(mat['sampler_textures'].values()):
   source=old_input()/rel;target=out/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
 report={}
 for name,paths in texture_sources(meshes,out).items():
  col,normal,metal=converted_arrays(paths)
  for suffix,pixels in [('a',col),('n',normal),('m',np.rint(metal*255).astype(np.uint8))]:Image.fromarray(pixels).save(folder/f'{name}_{suffix}.png')
  report[name]=dict(sources={k:file_info(p) for k,p in paths.items()},albedo='Source RGB; alpha 255',normal='Source nml RG; gls R in B',metal='T011/T005 heuristic',missing_channels=[k for k in ('nml','gls','spc') if k not in paths])
 save(out/'wingman-texture-audit.json',dict(materials=report,limitations=['Opaque Metal approximation; no emissive, transparency or refraction.','Source UV1 absent: duplicate UV0.']))


def convert(out):
 data=wm.layout();mdl,meshes,_=wm.selected();report=dict(format='octane-wingman-mesh-summary',version=1,binding='float32(diag(.0254,.0254,-.0254)*raw Cast); no fitting',omitted_meshes=data['omitted_meshes'],meshes=[])
 folder=out/'fusemesh'/PART;folder.mkdir(parents=True,exist_ok=True);source=old_input()
 for p in source.rglob('*'):
  if p.is_file():dst=folder/p.relative_to(source);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dst)
 doc=read(folder/'mesh.json');doc['bones'] += [c['name'] for c in data['new_carriers']];mp=mapping(data)
 make_textures(out,meshes)
 baseline=read(wm.BASE_MODEL/f'readback/export_{PART}/flver.json') if (wm.BASE_MODEL/f'readback/export_{PART}/flver.json').is_file() else read(wm.ac.BASE_MODEL/f'readback/export_{PART}/flver.json')
 node=baseline['Meshes'][0]['NodeIndex']
 for mesh in meshes:
  p=np.asarray(mesh.VertexPositionBuffer(),float).reshape(-1,3);n=unit(np.asarray(mesh.VertexNormalBuffer(),float).reshape(-1,3));uv=np.asarray(mesh.VertexUVLayerBuffer(0),float).reshape(-1,2);second=mesh.VertexUVLayerBuffer(1);uv1=np.asarray(second,float).reshape(-1,2) if second is not None else uv.copy();faces=np.asarray(mesh.FaceBuffer(),int).reshape(-1,3)
  wm.require(not mesh.VertexTangentBuffer(),'Unexpected source tangents');_,tangent,sign,tan_fallback=tangent_basis(p,n,uv,faces);bi,bw,loss,rawerror=merged_weights(mdl,mesh,mp)
  if bi.shape[1]<4:
   width=4-bi.shape[1];bi=np.concatenate([bi,np.repeat(bi[:,:1],width,axis=1)],axis=1);bw=np.concatenate([bw,np.zeros((len(bw),width))],axis=1)
  bi=np.asarray([doc['bones'].index(c['carrier']) for c in mp['carriers']])[bi]
  streams=dict(positions=p*np.diag(Q)[:3],normals=unit(n*np.diag(MIRROR)),tangents=np.c_[unit(tangent*np.diag(MIRROR)),-sign],uv0=uv,uv1=uv1,bone_indices=bi,bone_weights=bw,indices=faces)
  name=mesh.Material().Name();mi=next((i for i,m in enumerate(doc['materials']) if m['name']==name),None)
  if mi is None:mi=len(doc['materials']);doc['materials'].append(material_definition(ROOT,PART,name))
  i=len(doc['submeshes']);sub=dict(name=mesh.Name(),source_model=wm.KEY,material=mi,vertex_count=len(p),index_count=faces.size,cull_backfaces=True,node_name=baseline['Nodes'][node]['Name'])
  for k,(dtype,_) in STREAMS.items():sub[k]=f'mesh{i:03d}.{k}.bin';np.asarray(streams[k],dtype).tofile(folder/sub[k])
  for k,value in [('source_vertex_ids',np.arange(len(p))),('source_triangle_ids',np.arange(len(faces)))]:sub[k]=f'mesh{i:03d}.{k}.bin';np.asarray(value,'<u4').tofile(folder/sub[k])
  doc['submeshes'].append(sub);used=sorted({mdl.Skeleton().Bones()[b].Name() for b,w in zip(mesh.VertexWeightBoneBuffer(),mesh.VertexWeightValueBuffer()) if w>0})
  report['meshes'].append(dict(rig=wm.KEY,name=mesh.Name(),part=PART,group=wm.GROUP,vertices=len(p),triangles=len(faces),material=name,weighted_bones=used,carriers=[data['maps'][wm.KEY+'-carriers'][n] for n in used],four_weight_loss_max=float(loss.max()),source_weight_sum_max_error=rawerror,tangent_fallback_vertices=tan_fallback,final_winding=winding(streams['positions'],streams['normals'],faces)))
 for mat in doc['materials']:
  for rel in set(mat['textures'].values())|set(mat['sampler_textures'].values()):dst=folder/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(out/rel,dst)
 save(folder/'mesh.json',doc);old=read(old_input()/'mesh.json')
 wm.require(doc['submeshes'][:len(old['submeshes'])]==old['submeshes'] and doc['materials'][:len(old['materials'])]==old['materials'],'Old input metadata changed')
 report['part']=dict(meshes=len(doc['submeshes']),vertices=sum(s['vertex_count'] for s in doc['submeshes']),materials=len(doc['materials']),carriers=doc['bones'])
 save(out/'wingman-mesh-summary.json',report);return report
