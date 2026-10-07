"""T022 independent FLVER/Cast readback, old mesh retention, templates and materials."""
import argparse
import importlib.util
from pathlib import Path
import sys
sys.dont_write_bytecode=True
import numpy as np
from PIL import Image
from common import ROOT,PARTS,MODELS,TOOL,EXTRACT,read,save,run,unit,tangent_basis,winding
from mesh_weapons import wc,mapping,sources,texture_sources,old_input,converted_arrays
from pov_textures import texture_arrays
from verify_pov import stream,source_expected,quantize_weights
from verify_fuse import read_json_command
from verify_armor_bounds import verify as verify_bounds
from s3a_roundtrip import arrays
from material_bundle import verify_material


def verify_preview(out):
 report=read(out/'weapons-preview-verification.json');wc.require(len(report['previews'])==14,'Expected 14 previews');wc.require(report['max_er_apex_skin_error_m']<1e-12,'ER/Apex skin differs')
 wc.require(report['idle_t021_pixels_equal'],'Regression preview differs')
 for row in report['previews']:
  p=out/'preview'/row['file'];wc.require(p.is_file() and Image.open(p).size==(1120,840),'Missing preview');wc.require(sum(row['rasterized_pixels'].values())>0 and float(np.asarray(Image.open(p))[...,:3].std())>1.,'Empty preview')
 for name in ('idle_0_frame0_groups01.png',):wc.require(np.array_equal(np.asarray(Image.open(out/'preview'/name)),np.asarray(Image.open(wc.BASE_MODEL/'preview'/name))),'Actual regression pixels changed')
 return dict(count=14,battery_t021_pixels_equal=bool(report['battery_t021_pixels_equal']),battery_tinted=True,idle_t021_pixels_equal=True,max_er_apex_skin_error_m=report['max_er_apex_skin_error_m'],grip_measurements=report['grip_measurements'])


def verify_layout(dump,part,lod,pack,out):
 source=(wc.ac.BASE_MODEL if part=='bd' else wc.BASE_MODEL)/f'readback/export_{part}{lod}'
 old=read(source/'flver.json');nodes=dump['Nodes'];oldnodes=old['Nodes'];byname={n['Name']:n for n in nodes};oldby={n['Name']:n for n in oldnodes}
 if part=='bd':
  wc.require(len(nodes)==len(oldnodes) and dump['Skeletons']==old['Skeletons'],'BD nodes/skeletons changed')
  for a,b in zip(nodes,oldnodes):
   for k in ('Name','Flags','ParentIndex','FirstChildIndex','NextSiblingIndex','PreviousSiblingIndex','Translation','RotationQuaternion','Scale'):wc.require(a[k]==b[k],f'BD node changed: {k}')
 else:
  expected=[n['Name'] for n in oldnodes[:32]]+list(wc.FACE_NAMES)+[n['Name'] for n in oldnodes[32:]]
  wc.require([n['Name'] for n in nodes]==expected,'HD enabled-template/Xtra/face/rest order differs');wc.require(all(n['Flags']=='Bone' for n in nodes[:38]) and all(n['Flags']!='Bone' for n in nodes[38:]),'HD enabled prefix differs')
  for name,a in oldby.items():
   b=byname[name]
   for k in ('Flags','Translation','RotationQuaternion','Scale'):wc.require(a[k]==b[k],f'Old HD node bind changed: {name}/{k}')
   pa=oldnodes[a['ParentIndex']]['Name'] if a['ParentIndex']>=0 else None;pb=nodes[b['ParentIndex']]['Name'] if b['ParentIndex']>=0 else None;wc.require(pa==pb,'Old HD parent changed')
  live=wc.live_skeleton()['bones'];liveby={b['name']:b for b in live};world=wc.node_world(nodes);oldworld=wc.node_world(oldnodes)
  for name in oldby:wc.require(abs(world[name]-oldworld[name]).max()<2e-6,'Old HD world bind moved')
  for name in wc.FACE_NAMES:
   b=liveby[name];n=byname[name];parent=live[b['parent']]['name'];wc.require(nodes[n['ParentIndex']]['Name']==parent,'Face parent differs from live');ref=b['ref']
   wc.require(abs(wc.bp.trs(n['Translation'],n['RotationQuaternion'],n['Scale'])-wc.bp.trs(ref['t'],ref['r'],ref['s'])).max()<2e-6,'Face reference bind differs')
 for mesh in dump['Meshes']:wc.require(mesh['NodeIndex']>=0 and 'Mesh' in nodes[mesh['NodeIndex']]['Flags'],'Mesh is not on a mesh node')
 sk=dump['Skeletons'];base,allbones=sk['BaseSkeleton'],sk['AllSkeletons'];wc.require(len(base)==len(nodes)==len(allbones),'Skeleton table count')
 for i,(b,n) in enumerate(zip(base,nodes)):
  wc.require(b['NodeIndex']==i and all(b[k]==n[k] for k in ('ParentIndex','FirstChildIndex','NextSiblingIndex','PreviousSiblingIndex')),'BaseSkeleton does not match nodes')
 wc.require(sorted(b['NodeIndex'] for b in allbones)==list(range(len(nodes))),'AllSkeletons is not a permutation')
 if part=='hd':
  names=[n['Name'] for n in nodes];entries={names[b['NodeIndex']]:b for b in allbones}
  for b in wc.live_skeleton()['bones']:
   if b['name'] in (*wc.FACE_NAMES,*wc.ac.XTRA_NAMES):wc.require(names[allbones[entries[b['name']]['ParentIndex']]['NodeIndex']]==wc.live_skeleton()['bones'][b['parent']]['name'],'AllSkeletons live parent differs')
 world=wc.node_world(nodes)
 for c in pack['carrier_records'][71:]:
  if (part=='bd')!=(c['group']==5):continue
  wc.require(c['name'] in world and byname[c['name']]['Flags']=='Bone','Carrier disabled');wc.require(abs(world[c['name']]-wc.bp.trs(c['er_bind'][:3],c['er_bind'][3:])).max()<2e-6,'ER carrier bind differs')
 return dict(nodes=len(nodes),skeleton_tables_correct=True,mesh_nodes_correct=True,old_node_binds_preserved=True,face_nodes_enabled=6 if part=='hd' else 0)


def compare_preserved(folder,actual,dump,part,lod):
 oldfolder=(wc.ac.BASE_MODEL if part=='bd' else wc.BASE_MODEL)/f'readback/export_{part}{lod}';old=read(oldfolder/'mesh.json');olddump=read(oldfolder/'flver.json')
 for s,t in zip(old['submeshes'],actual['submeshes']):
  for k in ('name','material','vertex_count','index_count','cull_backfaces','source_model'):
   if k in s:wc.require(s[k]==t[k],f'T021 old mesh field changed: {k}')
  for k in ('positions','normals','tangents','uv0','uv1','bone_indices','bone_weights','flver_bone_weights','indices'):wc.require((oldfolder/s[k]).read_bytes()==(folder/t[k]).read_bytes(),f'T021 stream changed: {part}/{k}')
  for a,b in zip(s['face_sets'],t['face_sets']):wc.require((oldfolder/a['indices']).read_bytes()==(folder/b['indices']).read_bytes(),'T021 face set changed')
 wc.require(dump['Materials'][:len(olddump['Materials'])]==olddump['Materials'],'T021 materials changed')
 for i,m in enumerate(olddump['Meshes']):
  a=dump['Meshes'][i];wc.require(dump['Nodes'][a['NodeIndex']]['Name']==olddump['Nodes'][m['NodeIndex']]['Name'],'Old mesh node changed')
 from battery_tint import TINTED
 dds=[p for p in oldfolder.glob('*.dds') if not p.stem.endswith(TINTED)]
 for p in dds:wc.require(p.read_bytes()==(folder/p.name).read_bytes(),'T021 DDS bytes changed')
 # the two battery albedos tinted blue (Claude rework 2026-10-06): present, and changed
 tinted=[p for p in oldfolder.glob('*.dds') if p.stem.endswith(TINTED)]
 for p in tinted:wc.require((folder/p.name).is_file() and p.read_bytes()!=(folder/p.name).read_bytes(),'Battery tint missing')
 return dict(meshes=len(old['submeshes']),streams_byte_identical=True,materials_exact=True,dds_byte_identical=len(dds),battery_tinted=len(tinted))


def verify(out=None,check_preview=True):
 out=wc.checked(out or wc.MODEL_ROOT,wc.MODEL_ROOT,create=False);pkg=out/'package';rb=out/'readback';req=wc.require;report=dict(status='PASS',parts={},base_parts_byte_identical=[])
 req(len(list(pkg.rglob('*.dcx')))==9,'Expected eight parts and allmaterial')
 for part in ('am','lg'):
  for lod in ('','_l'):
   name=f'{part}_m_0998{lod}.partsbnd.dcx';req((pkg/'parts'/name).read_bytes()==(wc.BASE_MODEL/'package/parts'/name).read_bytes(),'AM/LG changed');report['base_parts_byte_identical'].append(name)
 for name,paths in texture_sources().items():
  col,normal,metal=converted_arrays(paths)
  for suffix,expected in [('a',col),('n',normal),('m',np.rint(metal*255).astype(np.uint8))]:req(np.array_equal(np.asarray(Image.open(out/'textures'/f'{name}_{suffix}.png')),expected),'Converted texture pixels changed')
 snapshot=out/'inputs/material/allmaterial.matbinbnd.dcx';req(snapshot.read_bytes()==Path(read(out/'inputs/source-material.json')['source']).read_bytes(),'Material snapshot differs');bundle=verify_material(out,snapshot)
 report['material_bundle']={k:bundle[k] for k in ('original_entries','output_entries','replaced_entries','added_entries','header_unchanged','original_entry_order_ids_names_flags_unchanged')}
 run([EXTRACT,'unpack',pkg/'material/allmaterial.matbinbnd.dcx','--out',rb/'material_0998','--filter','_M_0998'],out,'weapons_materials');materials={p.stem:p for p in (rb/'material_0998').rglob('*.matbin')}
 # A supplied bundle may already contain different payloads for our target
 # names: recorded replacement is permitted. Independently keep the seven
 # actual T021 BD/HD material payloads exact, rather than forbidding changes
 # to a caller's colliding new-mesh entries.
 run([EXTRACT,'unpack',wc.BASE_MODEL/'package/material/allmaterial.matbinbnd.dcx','--out',rb/'material_T021','--filter','_M_0998'],out,'weapons_baseline_materials');baseline_materials={p.stem:p for p in (rb/'material_T021').rglob('*.matbin')}
 preserved_materials=[]
 for part in ('bd','hd'):
  for mat in read(old_input(part)/'mesh.json')['materials']:
   name=f'P[{part.upper()}_M_0998]_'+mat['name'];req(materials[name].read_bytes()==baseline_materials[name].read_bytes(),'Actual T021 MATBIN payload changed');preserved_materials.append(name)
 report['T021_BD_HD_matbins_byte_identical']=preserved_materials
 spec=importlib.util.spec_from_file_location('weapons_pack_verifier',ROOT/'tools/apexpov/verify_weapons.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);report['pack']=module.verify(out/'inputs',write_report=False,pack_path=out/'inputs/fuse_pov.anim')
 pack=wc.read_pack(out/'inputs/fuse_pov.anim');data=wc.layout();local={name:(key,mdl,mesh) for key,mdl,mesh,name in sources()};groupby={c['name']:c['group'] for c in pack['carrier_records']}
 for part in PARTS:
  if part in ('am','lg'):
   run([TOOL,'export-mesh',pkg/f'parts/{part}_m_0998.partsbnd.dcx','--matbin-bnd',pkg/'material/allmaterial.matbinbnd.dcx','--out',rb/f'export_{part}'],out,'weapons_export_'+part);continue
  infolder=out/f'fusemesh/{part}';doc=read(infolder/'mesh.json');old=read(old_input(part)/'mesh.json');newcount=len(doc['submeshes'])-len(old['submeshes'])
  for lod in ('','_l'):
   path=pkg/f'parts/{part}_m_0998{lod}.partsbnd.dcx';req(path.read_bytes()[0x28:0x2c]==b'KRAK','DCX encoding')
   run([EXTRACT,'unpack',path,'--out',rb/path.stem],out,'weapons_unpack_'+part+lod);flver=next((rb/path.stem).rglob('*.flver'));dump=read_json_command(run,[TOOL,'flver',flver,'--samples','0'],out,'weapons_flver_'+part+lod)
   folder=rb/f'export_{part}{lod}';save(folder/'flver.json',dump);run([TOOL,'export-mesh',path,'--matbin-bnd',pkg/'material/allmaterial.matbinbnd.dcx','--out',folder],out,'weapons_export_'+part+lod);actual=read(folder/'mesh.json');req(len(actual['submeshes'])==len(doc['submeshes']),'Mesh count changed')
   stats=dict(along=0,against=0,degenerate=0,orthogonal=0);maxerror=0.
   for s,t in zip(doc['submeshes'],actual['submeshes']):
    names=np.asarray(actual['bones'])[stream(folder,t,'bone_indices')];weights=stream(folder,t,'flver_bone_weights');faces=stream(folder,t,'indices');groups=np.asarray([[groupby.get(n,-1) for n in row] for row in names]);req((groups[weights>0]>=0).all(),'Mesh uses non-carrier')
    for triangle in faces:req(len(set(groups[triangle][weights[triangle]>0]))==1,'Triangle mixes carrier groups')
    if s['name'] not in local:continue
    key,mdl,mesh=local[s['name']];mp=mapping(key,data);req((key=='cr')==(part=='bd'),'Mesh in wrong part')
    p=np.asarray(mesh.VertexPositionBuffer(),float).reshape(-1,3);n=unit(np.asarray(mesh.VertexNormalBuffer(),float).reshape(-1,3));uv=np.asarray(mesh.VertexUVLayerBuffer(0),float).reshape(-1,2);second=mesh.VertexUVLayerBuffer(1);uv1=np.asarray(second,float).reshape(-1,2) if second is not None else uv.copy();f=np.asarray(mesh.FaceBuffer()).reshape(-1,3);_,tangent,sign,_=tangent_basis(p,n,uv,f)
    streams=dict(positions=(p*[.0254,.0254,-.0254]).astype('<f4'),normals=unit(n*[1,1,-1]).astype('<f4'),tangents=np.c_[unit(tangent*[1,1,-1]),-sign].astype('<f4'),uv0=uv.astype('<f4'),uv1=uv1.astype('<f4'),indices=f.astype('<u4'))
    for k,value in streams.items():
     req(np.array_equal(stream(infolder,s,k),value),f'Source geometry changed: {key}/{k}');a=stream(folder,t,k)
     req(np.array_equal(a,value) if k in ('positions','indices') else abs(a-value).max()<=(1/127 if k in ('normals','tangents') else 1/2048)+1e-6,f'Quantized FLVER differs: {key}/{k}')
    expected,w,loss=source_expected(mdl,mesh,mp);req(np.array_equal(expected,names),'Carrier mapping changed');w=w.astype('<f4');req(np.array_equal(stream(infolder,s,'bone_weights'),w),'Source merged weights differ');req(np.array_equal(np.rint(weights*255).astype(int),quantize_weights(w)),'Weight quantization changed');maxerror=max(maxerror,float(abs(weights-w).max()))
    req(np.array_equal(np.fromfile(infolder/s['source_vertex_ids'],'<u4'),np.arange(len(p))) and np.array_equal(np.fromfile(infolder/s['source_triangle_ids'],'<u4'),np.arange(len(f))),'Source coverage differs')
    req(len(t['face_sets'])==6,'Face set count');
    for fs in t['face_sets']:req((folder/fs['indices']).read_bytes()==(infolder/s['indices']).read_bytes(),'Face set winding changed')
    for name,value in winding(streams['positions'],stream(folder,t,'normals'),f).items():stats[name]+=value
   verify_bounds(dump,actual,folder,arrays);layout=verify_layout(dump,part,lod,pack,out);preserved=compare_preserved(folder,actual,dump,part,lod)
   report['parts'][part+lod]=dict(meshes=len(actual['submeshes']),new_meshes=newcount,vertices=sum(s['vertex_count'] for s in actual['submeshes']),triangles=sum(s['index_count']//3 for s in actual['submeshes']),source_positions_exact=True,normals_tangents_uv_encoded=True,carrier_groups_correct=True,weights_quantization_exact=True,max_weight_quantization_error=maxerror,winding=stats,bounds='PASS independent T003 local-space bounds',node_layout=layout,T021=preserved)
  dds={p.stem for p in (rb/f'export_{part}').glob('*.dds')}
  for mat in doc['materials']:
   req(mat==__import__('textures').material_definition(ROOT,part,mat['name']),'T011 material definition changed');name=f'P[{part.upper()}_M_0998]_'+mat['name'];req(name in materials,'MATBIN missing');m=read_json_command(run,[TOOL,'matbin',materials[name]],out,'weapons_matbin_'+part+'_'+mat['name'])['Data'];params={p['Name']:p['Value'] for p in m['Params']};req(all(params[k]==v for k,v in mat['float_params'].items()),'Material params differ')
   for s in m['Samplers']:
    tex=s['Path'].replace('\\','/').split('/')[-1].removesuffix('.tif')
    if '_M_0998_' in tex:req(tex in dds,'MATBIN/TPF texture missing')
   for typ in mat['sampler_textures']:req('_M_0998_' in next(s['Path'] for s in m['Samplers'] if s['Type']==typ),'Detail sampler not overridden')
  for mat in read(rb/f'export_{part}/flver.json')['Materials']:req(mat['MTD'].replace('\\','/').split('/')[-1].removesuffix('.matxml') in materials,'FLVER MATBIN reference missing')
 # Full dummy contents and binding references are compared by SoulsFormats in the template adapter.
 dll=out/'inputs/template-adapter/bin/WeaponsTemplates.dll'
 for part in ('bd','hd'):
  for lod in ('','_l'):run(['dotnet',dll,'verify-preserved',wc.BASE_MODEL/f'package/parts/{part}_m_0998{lod}.partsbnd.dcx',pkg/f'parts/{part}_m_0998{lod}.partsbnd.dcx',out/f'readback/{part}{lod}-dummy-verification.json'],out,'weapons_dummy_'+part+lod)
 report['dummy_contents_and_bind_references_preserved']=True
 if check_preview:report['previews']=verify_preview(out)
 save(out/'weapons-readback-verification.json',report);print(f'PASS T022 readback: AM/LG four files byte-identical; BD/HD four FLVERs checked; T021 meshes/materials/DDS retained; {bundle["original_entries"]} material entries checked',flush=True);return report


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path);verify(p.parse_args().out)
