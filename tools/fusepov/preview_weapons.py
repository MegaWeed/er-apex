"""T022 specified camera previews using quantized FLVER and serialized FPOV."""
import argparse
import sys
from pathlib import Path
sys.dont_write_bytecode=True
import numpy as np
from PIL import Image
from common import read,save
from mesh_weapons import wc
from verify_pov import stream
import preview_ability as pa
from preview_pov import perspective,surface_distances,pack_frame0
REQUESTED=[('cr_draw_0',-1,5),('cr_holster_0',0,5),('cr_reload_0',None,5),('cr_reload_empty_0',None,5),('cr_ads_in_0',-1,5),('cr_drawfirst_0',None,5),('frag_draw_seq_0',-1,6),('frag_toss_prep_pullout_seq_0',-1,6),('frag_toss_hold_seq_0',0,6),('frag_toss_seq_0',7,6)]


def load_meshes(out,pack):
 carriers={c['name']:i for i,c in enumerate(pack['carrier_records'])};meshes=[];textures={}
 for part in ('am','bd','hd','lg'):
  source=out if part in ('bd','hd') else wc.ac.BASE_MODEL if part=='am' else wc.bc.BASE_MODEL
  infolder=source/f'fusemesh/{part}';inputs=read(infolder/'mesh.json');folder=out/f'readback/export_{part}';doc=read(folder/'mesh.json');wc.require(len(inputs['submeshes'])==len(doc['submeshes']),'Preview mesh inventory')
  for s,t in zip(doc['submeshes'],inputs['submeshes']):
   bi=stream(folder,s,'bone_indices');bw=stream(folder,s,'flver_bone_weights').astype(float);names=np.asarray(doc['bones'])[bi];lookup=np.asarray([[carriers.get(n,-1) for n in row] for row in names]);wc.require(not (lookup[bw>0]<0).any(),'Unknown preview carrier');lookup[bw==0]=0;groups={pack['carrier_records'][i]['group'] for i in lookup[bw>0]};wc.require(len(groups)==1,'Preview mesh group mixed')
   mat=inputs['materials'][t['material']]['name'];textures[mat]=np.asarray(Image.open(infolder/inputs['materials'][t['material']]['textures']['a']).convert('RGBA'))
   meshes.append(dict(name=t['name'],material=mat,part=part,group=next(iter(groups)),positions=stream(folder,s,'positions').astype(float),normals=stream(folder,s,'normals').astype(float),uv0=stream(folder,s,'uv0'),indices=stream(folder,s,'indices').astype(int),bone_indices=lookup,bone_weights=bw,source_vertex_ids=np.fromfile(infolder/t['source_vertex_ids'],'<u4')))
 return meshes,textures


def make_previews(out,pack_path=None):
 pack=wc.read_pack(pack_path or out/'inputs/fuse_pov.anim');meshes,textures=load_meshes(out,pack);folder=out/'preview';folder.mkdir(parents=True,exist_ok=True)
 report=dict(format='octane-weapons-preview-verification',version=1,previews=[],grip_measurements=[],max_er_apex_skin_error_m=0.,camera_axes=dict(forward='+Z',up='+Y',right='-X',horizontal_fov_deg=90),source='Quantized 998 FLVER readback and serialized FPOV f32; unmirror ER skin into Apex display space.')
 for name,frame,group in REQUESTED:
  c=pack['clips'][name];f=c['frames']-1 if frame==-1 else c['frames']//2 if frame is None else frame;wc.require(not c['additive'],'Requested preview must be absolute');pose=pa.mix(np.asarray([b['rest'] for b in pack['bones']]),c,f);posed,error,camera=pa.skin(meshes,pack,pose);shown=[m for m in posed if m['group'] in (0,group)];props=[m for m in posed if m['group']==group];grip={s:surface_distances(pa.finger_points(posed,s),props) for s in ('l','r')};file=f'{name}_frame{f}_groups0{group}.png';pixels=perspective(folder/file,shown,textures,f'{name} frame {f} / quantized 998 / groups [0, {group}]')
  report['previews'].append(dict(file=file,clip=name,frame=f,groups=[0,group],rasterized_pixels=pixels,finger_distances=grip,camera_apex=camera.tolist()));report['grip_measurements'].append(dict(clip=name,frame=f,**grip));report['max_er_apex_skin_error_m']=max(report['max_er_apex_skin_error_m'],error)
 # Projectile owners are explicitly at model bind, with a camera 0.3 m in front.
 worlds=wc.world7(pack['bones'],np.asarray([b['rest'] for b in pack['bones']]))
 bind=next(iter(wc.model_world(wc.model(wc.PROJECTILE)).values()))
 for group in (7,8):
  carrier=next(c for c in pack['carrier_records'] if c['group']==group);w=worlds.copy();w[carrier['owner']]=bind
  camera=bind.copy();camera[:3,3]+=bind[:3,:3]@np.asarray([0.,0.,-.3/.0254]);w[pack['camera']]=camera
  posed,error,_=pa.skin(meshes,pack,np.asarray([b['rest'] for b in pack['bones']]),w);shown=[m for m in posed if m['group']==group];file=f'frag_projectile_{"a" if group==7 else "b"}_bind_group{group}.png';pixels=perspective(folder/file,shown,textures,f'Frag projectile {group} / owner model bind / camera 0.3 m in front')
  report['previews'].append(dict(file=file,clip=None,frame=None,groups=[group],rasterized_pixels=pixels,camera_apex=camera.tolist(),camera_distance_m=.3));report['max_er_apex_skin_error_m']=max(report['max_er_apex_skin_error_m'],error)
 name='battery_charge_0';c=pack['clips'][name];f=c['frames']//2;posed,error,camera=pa.skin(meshes,pack,c['poses'][f].astype(float));file=f'{name}_frame{f}_groups04.png';pixels=perspective(folder/file,[m for m in posed if m['group'] in (0,4)],textures,f'{name} frame {f} / quantized 998 / groups [0, 4]')
 report['previews'].append(dict(file=file,clip=name,frame=f,groups=[0,4],rasterized_pixels=pixels,camera_apex=camera.tolist()));report['battery_t021_pixels_equal']=bool(np.array_equal(np.asarray(Image.open(folder/file)),np.asarray(Image.open(wc.BASE_MODEL/'preview'/file))));report['max_er_apex_skin_error_m']=max(report['max_er_apex_skin_error_m'],error)
 posed,error,camera=pa.skin(meshes,pack,pa.idle_pose(pack),pack_frame0(pack));file='idle_0_frame0_groups01.png';pixels=perspective(folder/file,[m for m in posed if m['group'] in (0,1)],textures,'QC reference + idle_0 frame 0 / ER carrier skin un-mirrored for Apex display')
 report['previews'].append(dict(file=file,clip='idle_0',frame=0,groups=[0,1],rasterized_pixels=pixels,camera_apex=camera.tolist()));report['idle_t021_pixels_equal']=bool(np.array_equal(np.asarray(Image.open(folder/file)),np.asarray(Image.open(wc.BASE_MODEL/'preview'/file))));report['max_er_apex_skin_error_m']=max(report['max_er_apex_skin_error_m'],error)
 # the battery preview changes with its blue tint (battery_tint.py, Claude rework 2026-10-06): only the R-301 one must stay
 wc.require(report['idle_t021_pixels_equal'],'T021 regression pixels changed')
 canvas=Image.new('RGB',(1680,2100),(22,25,30))
 for i,row in enumerate(report['previews']):im=Image.open(folder/row['file']).convert('RGB');im.thumbnail((560,420));canvas.paste(im,((i%3)*560,(i//3)*420))
 canvas.save(folder/'weapons-contact-sheet.png');report['limitations']=['Unsigned grip distances do not measure penetration.','Horizontal FOV=90 is a software inspection setting.','Opaque T011 Metal material approximation.','Projectile previews show standalone model bind; flight is runtime controlled.'];save(out/'weapons-preview-verification.json',report)
 print(f'PASS T022 previews: 14; battery pixels={report["battery_t021_pixels_equal"]}; idle pixels={report["idle_t021_pixels_equal"]}; ER/Apex {report["max_er_apex_skin_error_m"]:.3g} m',flush=True);return report


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path);p.add_argument('--pack',type=Path);a=p.parse_args();make_previews(wc.checked(a.out or wc.MODEL_ROOT,wc.MODEL_ROOT),a.pack)
