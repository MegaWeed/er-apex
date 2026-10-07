"""T021 jx_c_camera previews from quantized 998 geometry and serialized FPOV v2."""
import sys
from pathlib import Path
sys.dont_write_bytecode = True
import numpy as np
from PIL import Image
from common import read,save
from mesh_battery import bc
from verify_pov import stream
import preview_ability as pa
from preview_pov import perspective,surface_distances,pack_frame0

REQUESTED=[('battery_raise_0',0),('battery_raise_0',-1),('battery_charge_0',0),('battery_charge_0',None),
           ('battery_fire_0',None),('battery_holster_used_0',0)]


def load_meshes(out,pack):
    carriers={c['name']:i for i,c in enumerate(pack['carrier_records'])};meshes=[];textures={}
    for part in ('am','bd','hd','lg'):
        source=out if part=='hd' else bc.BASE_MODEL if part=='lg' else bc.ac.BASE_MODEL
        infolder=source/'fusemesh'/part;docin=read(infolder/'mesh.json')
        folder=out/'readback'/f'export_{part}';doc=read(folder/'mesh.json')
        bc.require(len(doc['submeshes'])==len(docin['submeshes']),'Mesh input/readback inventory differs')
        for s,t in zip(doc['submeshes'],docin['submeshes']):
            bi=stream(folder,s,'bone_indices');bw=stream(folder,s,'flver_bone_weights').astype(float)
            names=np.asarray(doc['bones'])[bi];lookup=np.array([[carriers.get(n,-1) for n in row] for row in names])
            bc.require(not (lookup[bw>0]<0).any(),'Missing carrier for preview');lookup[bw==0]=0
            groups={pack['carrier_records'][int(i)]['group'] for i in lookup[bw>0]}
            bc.require(len(groups)==1,'Mesh mixes groups')
            material=docin['materials'][t['material']]['name']
            textures[material]=np.asarray(Image.open(infolder/docin['materials'][t['material']]['textures']['a']).convert('RGBA'))
            meshes.append(dict(name=t['name'],material=material,part=part,group=next(iter(groups)),
                positions=stream(folder,s,'positions').astype(float),normals=stream(folder,s,'normals').astype(float),
                uv0=stream(folder,s,'uv0'),indices=stream(folder,s,'indices').astype(int),bone_indices=lookup,bone_weights=bw,
                source_vertex_ids=np.fromfile(infolder/t['source_vertex_ids'],'<u4')))
    return meshes,textures


def make_previews(out,pack_path=None):
    pack=bc.read_pack(pack_path or out/'inputs/fuse_pov.anim');meshes,textures=load_meshes(out,pack)
    folder=out/'preview';folder.mkdir(parents=True,exist_ok=True)
    report=dict(format='octane-battery-preview-verification',version=1,previews=[],grip_measurements=[],max_er_apex_skin_error_m=0.,
        source='Readback quantized FLVER + serialized FPOV f32; battery absolute clips pose both arms and battery.',
        camera_axes=dict(forward='+Z',up='+Y',right='-X',horizontal_fov_deg=90),display='ER skin first, unmirror into Apex for display',
        limitations=['Unsigned finger distances do not measure penetration.', 'FOV=90 is a software inspection setting.',
                    'Opaque Metal approximation; battery energy/emissive and glass refraction not reproduced.'])
    for name,frame in REQUESTED:
        c=pack['clips'][name];f=c['frames']-1 if frame==-1 else c['frames']//2 if frame is None else frame
        bc.require(not c['additive'],'Requested battery preview must be absolute')
        posed,error,camera=pa.skin(meshes,pack,c['poses'][f].astype(float))
        shown=[m for m in posed if m['group'] in (0,4)];props=[m for m in posed if m['group']==4]
        grip={side:surface_distances(pa.finger_points(posed,side),props) for side in ('l','r')}
        namefile=f'{name}_frame{f}_groups04.png'
        pixels=perspective(folder/namefile,shown,textures,f'{name} frame {f} / quantized 998 / groups [0, 4]')
        report['previews'].append(dict(file=namefile,clip=name,frame=f,groups=[0,4],rasterized_pixels=pixels,finger_distances=grip,camera_apex=camera.tolist()))
        report['grip_measurements'].append(dict(clip=name,frame=f,**grip))
        report['max_er_apex_skin_error_m']=max(report['max_er_apex_skin_error_m'],error)
    # Exactly reproduce T020's scoped left-arm/prop layer, title, renderer and selected groups.
    name='stim_idle_0';pose=pa.ability_pose(pack,pa.idle_pose(pack,True),pack['clips'][name],0,'epipen')
    posed,error,camera=pa.skin(meshes,pack,pose);shown=[m for m in posed if m['group'] in (0,2)]
    filename='stim_idle_0_frame0_ability.png'
    pixels=perspective(folder/filename,shown,textures,'stim_idle_0 frame 0 / quantized 998 / groups [0, 2]')
    report['previews'].append(dict(file=filename,clip=name,frame=0,groups=[0,2],rasterized_pixels=pixels,camera_apex=camera.tolist()))
    previous=bc.BASE_MODEL/'preview'/filename
    report['stim_t020_pixels_equal']=bool(np.array_equal(np.asarray(Image.open(previous)),np.asarray(Image.open(folder/filename))))
    report['max_er_apex_skin_error_m']=max(report['max_er_apex_skin_error_m'],error)
    posed,error,camera=pa.skin(meshes,pack,pa.idle_pose(pack),world_override=pack_frame0(pack))
    shown=[m for m in posed if m['group'] in (0,1)];filename='idle_0_frame0_groups01.png'
    pixels=perspective(folder/filename,shown,textures,'QC reference + idle_0 frame 0 / ER carrier skin un-mirrored for Apex display')
    report['previews'].append(dict(file=filename,clip='idle_0',frame=0,groups=[0,1],rasterized_pixels=pixels,camera_apex=camera.tolist()))
    previous=bc.BASE_MODEL/'preview'/filename
    report['idle_t020_pixels_equal']=bool(np.array_equal(np.asarray(Image.open(previous)),np.asarray(Image.open(folder/filename))))
    report['max_er_apex_skin_error_m']=max(report['max_er_apex_skin_error_m'],error)
    bc.require(report['stim_t020_pixels_equal'] and report['idle_t020_pixels_equal'],'T020 preview pixels differ')
    canvas=Image.new('RGB',(1680,1260),(22,25,30))
    for i,row in enumerate(report['previews']):
        im=Image.open(folder/row['file']).convert('RGB');im.thumbnail((560,420));canvas.paste(im,((i%3)*560,(i//3)*420))
    canvas.save(folder/'battery-contact-sheet.png')
    report['limitations'].append('raise frame 0 is the source starting pose below the camera; only the top of the battery is visible. No mesh/camera alignment was applied.')
    save(out/'battery-preview-verification.json',report)
    print(f'PASS T021 previews: six battery + two T020; stim pixels={report["stim_t020_pixels_equal"]}; idle pixels={report["idle_t020_pixels_equal"]}; ER/Apex {report["max_er_apex_skin_error_m"]:.3g} m',flush=True)
    return report
