"""T015: local Octane LOD0 -> four native c0000 model-999 armor parts."""
import sys
sys.dont_write_bytecode=True
import argparse
import shutil
import time
from pathlib import Path
import numpy as np
from common import ROOT,DEFAULT,MATBIN_DEFAULT,TOOL,EXTRACT,output_path,run,ensure_helper
from geometry import PARTS,MODELS,alignment,meshes,read,save,split,winding
from preview import render,posed
from textures import make_textures,material_definition
from contacts import contact_report

if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8',errors='replace')


def write_mesh(out,part,data,eb,flipy):
    folder=out/('fusemesh_flipy' if flipy else 'fusemesh')/part;folder.mkdir(parents=True,exist_ok=True)
    matnames=sorted({m['material'] for m in data}); materials=[material_definition(ROOT,part,n,flipy) for n in matnames]
    bones=sorted({int(i) for m in data for i in m['bone_indices'].ravel()}); lookup={b:i for i,b in enumerate(bones)}
    doc=dict(format='fusemesh',version=1,space='flver_model',bones=[eb[i]['Name'] for i in bones],materials=materials,submeshes=[])
    types=dict(positions='<f4',normals='<f4',tangents='<f4',uv0='<f4',uv1='<f4',bone_indices='u1',bone_weights='<f4',indices='<u4')
    for i,m in enumerate(data):
        sub=dict(name=m['name'],material=matnames.index(m['material']),vertex_count=len(m['positions']),index_count=m['indices'].size,cull_backfaces=True)
        for key,dtype in types.items():
            name=f'mesh{i:03d}.{key}.bin'; array=m[key]
            if key=='bone_indices': array=np.vectorize(lookup.__getitem__)(array)
            np.asarray(array,dtype=dtype).tofile(folder/name);sub[key]=name
        doc['submeshes'].append(sub)
    files={file for material in materials for file in list(material['textures'].values())+list(material['sampler_textures'].values())}
    for file in sorted(files):
        target=folder/file;target.parent.mkdir(exist_ok=True);shutil.copyfile(out/file,target)
    save(folder/'mesh.json',doc)
    return folder


def reference_evidence(root):
    folder=root/'er-data/s3/original_mesh';doc=read(folder/'mesh.json');stats=dict(along=0,against=0,degenerate=0,orthogonal=0);tangent_stats=[]
    for sub in doc['submeshes']:
        p=np.fromfile(folder/sub['positions'],'<f4').reshape(-1,3);n=np.fromfile(folder/sub['normals'],'<f4').reshape(-1,3)
        t=np.fromfile(folder/sub['tangents'],'<f4').reshape(-1,4);uv=np.fromfile(folder/sub['uv0'],'<f4').reshape(-1,2);f=np.fromfile(folder/sub['indices'],'<u4').reshape(-1,3)
        for key,value in winding(p,n,f).items():stats[key]+=value
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
    parser.add_argument('--out',type=Path,default=DEFAULT)
    parser.add_argument('--matbin-bnd',type=Path,default=MATBIN_DEFAULT)
    parser.add_argument('--geometry-only',action='store_true');parser.add_argument('--skip-previews',action='store_true')
    args=parser.parse_args();out=output_path(args.out);out.mkdir(parents=True,exist_ok=True);start=time.monotonic()
    print('Aligning Octane: 87 bones, 60 present mapped joints; all source weights',flush=True)
    state=alignment(ROOT);source,summary=meshes(ROOT,state);parts,split_report=split(source,state);eb=state[1];E=state[6]
    summary['parts']=split_report;summary['alignment']=dict(uniform_scale=state[-1]['uniform_scale'],max_joint_error_m=state[-1]['max_joint_position_error_m'])
    summary['original_er']=reference_evidence(ROOT)
    summary['winding']={m['name']:dict(source=m['original_winding'],aligned=m['converted_winding']) for m in source}
    audit,textures=make_textures(ROOT,out,{m['material'] for m in source})
    for part in PARTS:
        for flipy in (False,True):write_mesh(out,part,parts[part],eb,flipy)
        report=split_report[part]
        print(f'{part}: {report["vertices"]} vertices, {report["triangles"]} triangles, {report["bone_count"]} bones, {report["forced_vertices"]} forced vertices',flush=True)
    deformation,F,pose_report=posed(state,parts);summary['deformation']=pose_report
    save(out/'deformation-contacts.json',contact_report(parts,deformation))
    assert pose_report['finite'] and pose_report['opened_duplicate_pairs_gt_1mm']==0, 'Deformation opens split seams'
    if not args.skip_previews:
        dest=out/'preview';dest.mkdir(exist_ok=True)
        for view,yaw in [('front',180),('side',90),('back',0),('oblique',145)]:
            render(dest/f'parts_{view}.png',parts,eb,E,f'Octane parts / {view} / ER reference',yaw)
        for view,yaw in [('front',180),('side',90),('back',0)]:
            render(dest/f'aligned_{view}.png',parts,eb,E,f'Aligned Octane / {view}',yaw,textures)
        render(dest/'deformation.png',deformation,eb,F,'L forearm +90 / head +45 / R thigh +60',145)
        render(dest/'deformation_textured.png',deformation,eb,F,'Octane native 4-weight deformation',145,textures)
    save(out/'align.json',state[-1]);save(out/'owner-map.json',state[-1]['owner_map']);save(out/'geometry-summary.json',summary)
    selections={part:[dict(source=m['name'],template_matbin=m['template_matbin']) for m in read(out/'fusemesh'/part/'mesh.json')['materials']] for part in PARTS}
    texture_report=read(out/'texture-audit.json');texture_report['part_materials']=selections;save(out/'texture-audit.json',texture_report)
    if args.geometry_only:
        print('PASS geometry:',out/'geometry-summary.json',flush=True);return
    for tool in (TOOL,EXTRACT):
        if not tool.is_file():raise FileNotFoundError(f'Existing built tool required (read-only): {tool}')
    material_source=args.matbin_bnd.resolve()
    if not material_source.is_file():raise FileNotFoundError('待定：input material bundle '+str(material_source))
    snapshot=out/'inputs/material/allmaterial.input.matbinbnd.dcx';snapshot.parent.mkdir(parents=True,exist_ok=True)
    if material_source!=snapshot:shutil.copyfile(material_source,snapshot)
    assert snapshot.read_bytes()==material_source.read_bytes(),'Input bundle copy differs'
    targets=[f'P[{part.upper()}_M_0999]_'+m['source'] for part in PARTS for m in selections[part]]
    save(out/'inputs/material/target-matbins.json',targets)
    provenance_paths=[ROOT/'apex-data/assets/octane/cast/mdl/Humans/class/medium/pilot_medium_stim_LOD0.cast',
        ROOT/'apex-data/assets/octane/skeletons/pilot_medium_stim.json',ROOT/'apex-data/assets/octane/materials.json',
        ROOT/'er-data/s2b/mapping-v0.json',ROOT/'er-data/json/c0000_skeleton.json',material_source]
    save(out/'source-manifest.json',dict(source_files=[dict(path=str(p),size_bytes=p.stat().st_size) for p in provenance_paths],
        material_input=str(material_source),material_snapshot=str(snapshot),material_copy_bytes_exact=True,
        provenance_rule='local source paths/sizes/format checks/direct content comparison; no content digest'))
    helper=ensure_helper(out);working=out/'inputs/material/allmaterial.builder.matbinbnd'
    run([*helper,'prepare',snapshot,out/'inputs/material/target-matbins.json',working,out/'material-bundle-preparation.json'],out,'prepare_material_bundle')
    paths=[f'/parts/{part}_m_{MODELS[part]:04d}{lod}.partsbnd.dcx' for part in PARTS for lod in ('','_l')]
    run([EXTRACT,'get',*paths,'--out',out/'inputs'],out,'extract_templates')
    for flipy in (False,True):
        package=out/('package_flipy' if flipy else 'package');meshroot=out/('fusemesh_flipy' if flipy else 'fusemesh')
        command=[TOOL,'build-armor','--model','999','--matbin-bnd',working,'--out',package]
        for part in PARTS:command.extend([f'--{part}-template',out/f'inputs/parts/{part}_m_{MODELS[part]:04d}.partsbnd.dcx',f'--{part}-mesh',meshroot/part])
        run(command,out,'build_'+package.name)
        run([*helper,'finish',snapshot,package/'material/allmaterial.matbinbnd.dcx',out/'inputs/material/target-matbins.json',out/f'material-bundle-{package.name}.json'],out,'finish_'+package.name)
    from verify_octane import verify
    verification=verify(out);verification['elapsed_seconds']=round(time.monotonic()-start,2);save(out/'verification.json',verification)
    print(f'PASS conversion: {sum(len(m["indices"]) for m in source)} triangles, 4 parts, 2 packages; elapsed {verification["elapsed_seconds"]}s',flush=True)


if __name__=='__main__':main()
