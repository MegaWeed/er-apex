"""T005: regenerate the four native-animation armor parts from local Fuse Cast."""
import argparse
import hashlib
import shutil
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
sys.stdout.reconfigure(encoding='utf-8',errors='replace')
from geometry import PARTS,MODELS,alignment,meshes,read,save,split,winding
from preview import render,posed
from textures import make_textures,material_definition

ROOT=Path(__file__).resolve().parents[2]
DEFAULT=ROOT/'er-data/s3/fuse'
TOOL=ROOT/'tools/erdata/ertool/bin/Release/net8.0/ertool.exe'
EXTRACT=ROOT/'tools/erdata/erextract/target/x86_64-pc-windows-msvc/release/erextract.exe'


def run(command,out,label):
    command=list(map(str,command));logs=out/'logs';logs.mkdir(parents=True,exist_ok=True)
    r=subprocess.run(command,capture_output=True,encoding='utf-8',errors='replace')
    (logs/f'{label}.log').write_text('COMMAND '+repr(command)+'\n'+r.stdout+r.stderr,encoding='utf-8')
    if r.returncode:raise RuntimeError(f'{label}: exit {r.returncode}; {logs/f"{label}.log"}\n{r.stderr[-1500:]}')
    if r.stdout.strip():print(r.stdout.strip()[-1200:],flush=True)
    return r.stdout


def write_mesh(root,out,part,data,eb,flipy):
    folder=out/('fusemesh_flipy' if flipy else 'fusemesh')/part;folder.mkdir(parents=True,exist_ok=True)
    matnames=sorted({m['material'] for m in data});materials=[material_definition(root,part,n,flipy) for n in matnames]
    bones=sorted({int(i) for m in data for i in m['bone_indices'].ravel()});lookup={b:i for i,b in enumerate(bones)}
    doc=dict(format='fusemesh',version=1,space='flver_model',bones=[eb[i]['Name'] for i in bones],materials=materials,submeshes=[])
    types=dict(positions='<f4',normals='<f4',tangents='<f4',uv0='<f4',uv1='<f4',bone_indices='u1',bone_weights='<f4',indices='<u4')
    for i,m in enumerate(data):
        s=dict(name=m['name'],material=matnames.index(m['material']),vertex_count=len(m['positions']),index_count=m['indices'].size,
               cull_backfaces=m['material']!='fuse_base_hair')
        for key,dtype in types.items():
            name=f'mesh{i:03d}.{key}.bin';array=m[key]
            if key=='bone_indices':array=np.vectorize(lookup.__getitem__)(array)
            np.asarray(array,dtype=dtype).tofile(folder/name);s[key]=name
        doc['submeshes'].append(s)
    files={file for m in materials for file in list(m['textures'].values())+list(m['sampler_textures'].values())}
    for file in files:
        target=folder/file;target.parent.mkdir(exist_ok=True);shutil.copyfile(out/file,target)
    save(folder/'mesh.json',doc);return folder


def reference_evidence(root):
    folder=root/'er-data/s3/original_mesh';doc=read(folder/'mesh.json');stats=dict(along=0,against=0,degenerate=0,orthogonal=0);tangent_stats=[]
    for s in doc['submeshes']:
        p=np.fromfile(folder/s['positions'],'<f4').reshape(-1,3);n=np.fromfile(folder/s['normals'],'<f4').reshape(-1,3)
        t=np.fromfile(folder/s['tangents'],'<f4').reshape(-1,4);uv=np.fromfile(folder/s['uv0'],'<f4').reshape(-1,2);f=np.fromfile(folder/s['indices'],'<u4').reshape(-1,3)
        for k,v in winding(p,n,f).items():stats[k]+=v
        dp=p[f[:,1:]]-p[f[:,0,None]];du=uv[f[:,1:]]-uv[f[:,0,None]];det=du[:,0,0]*du[:,1,1]-du[:,0,1]*du[:,1,0];good=abs(det)>1e-6
        u=(dp[:,0]*du[:,1,1,None]-dp[:,1]*du[:,0,1,None])[good]/det[good,None]
        v=(-dp[:,0]*du[:,1,0,None]+dp[:,1]*du[:,0,0,None])[good]/det[good,None]
        tang=t[f[good],:3].mean(1);bit=(np.cross(n,t[:,:3])*t[:,3,None])[f[good]].mean(1)
        norm=lambda x:x/np.maximum(np.linalg.norm(x,axis=1,keepdims=True),1e-12)
        tangent_stats.extend(np.stack([(norm(u)*norm(tang)).sum(1),(norm(v)*norm(tang)).sum(1),(norm(u)*norm(bit)).sum(1)],axis=1))
    return dict(source=str(folder),winding=stats,tangent_uv_dot_quantiles=np.quantile(tangent_stats,[.1,.5,.9],axis=0).tolist(),
                tangent_uv_dot_columns=['T dot dP/du','T dot dP/dv','cross(N,T)*W dot dP/du'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=DEFAULT);parser.add_argument('--geometry-only',action='store_true')
    parser.add_argument('--skip-previews',action='store_true');args=parser.parse_args();out=args.out.resolve()
    if not out.is_relative_to(DEFAULT.resolve()):raise ValueError('Output must stay inside exclusive er-data/s3/fuse')
    out.mkdir(parents=True,exist_ok=True);start=time.monotonic()
    print('Aligning 231 Apex bones to local HKX reference',flush=True)
    state=alignment(ROOT);source,summary=meshes(ROOT,state);parts,split_report=split(source,state);eb=state[1];E=state[6]
    summary['parts']=split_report;summary['alignment']=dict(uniform_scale=state[-1]['uniform_scale'],max_joint_error_m=state[-1]['max_joint_position_error_m'])
    summary['original_er']=reference_evidence(ROOT)
    summary['winding']={m['name']:dict(source=m['original_winding'],aligned=m['converted_winding']) for m in source}
    audit,textures=make_textures(ROOT,out,{m['material'] for m in source})
    for part in PARTS:
        for flipy in (False,True):write_mesh(ROOT,out,part,parts[part],eb,flipy)
        print(f'{part}: {split_report[part]["vertices"]} vertices, {split_report[part]["triangles"]} triangles, {split_report[part]["bone_count"]} bones, {split_report[part]["forced_vertices"]} forced vertices',flush=True)
    deformation,F,pose_report=posed(state,parts);summary['deformation']=pose_report
    if not args.skip_previews:
        dest=out/'preview';dest.mkdir(exist_ok=True)
        for view,yaw in [('front',180),('side',90),('back',0),('oblique',145)]:
            render(dest/f'parts_{view}.png',parts,eb,E,f'Fuse parts / {view} / ER reference',yaw)
        for view,yaw in [('front',180),('side',90),('back',0)]:
            render(dest/f'aligned_{view}.png',parts,eb,E,f'Aligned Fuse / {view}',yaw,textures)
        render(dest/'deformation.png',deformation,eb,F,'L forearm +90 / head +45 / R thigh +60',145)
        render(dest/'deformation_textured.png',deformation,eb,F,'Native 4-weight deformation',145,textures)
    save(out/'align.json',state[-1]);save(out/'geometry-summary.json',summary)
    if args.geometry_only:
        print('Geometry complete:',out/'geometry-summary.json',flush=True);return
    run(['dotnet','build',ROOT/'tools/erdata/ertool/ertool.csproj','-c','Release','/p:WarningLevel=0'],out,'build_ertool')
    paths=[f'/parts/{part}_m_{MODELS[part]:04d}{lod}.partsbnd.dcx' for part in PARTS for lod in ('','_l')]
    run([EXTRACT,'get',*paths,'/material/allmaterial.matbinbnd.dcx','--out',out/'inputs'],out,'extract_templates')
    for flipy in (False,True):
        package=out/('package_flipy' if flipy else 'package');meshroot=out/('fusemesh_flipy' if flipy else 'fusemesh')
        command=[TOOL,'build-armor','--model','999','--matbin-bnd',out/'inputs/material/allmaterial.matbinbnd.dcx','--out',package]
        for part in PARTS:command.extend([f'--{part}-template',out/f'inputs/parts/{part}_m_{MODELS[part]:04d}.partsbnd.dcx',f'--{part}-mesh',meshroot/part])
        run(command,out,'build_'+package.name)
    from verify_fuse import verify
    sys.path.insert(0,str(ROOT/'tools/erdata/scripts'))
    verification=verify(out,run,TOOL,EXTRACT)
    verification['elapsed_seconds']=round(time.monotonic()-start,2)
    verification['source_sha256']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'apex-data/assets/fuse_skeleton.json',ROOT/'er-data/s2b/mapping-v0.json',ROOT/'apex-data/assets/cast/mdl/Humans/class/medium/pilot_medium_fuse_LOD0.cast']}
    save(out/'verification.json',verification)
    print(f'PASS conversion: {sum(len(m["indices"]) for m in source)} triangles, 4 parts, 2 packages; elapsed {verification["elapsed_seconds"]}s',flush=True)


if __name__=='__main__':main()
