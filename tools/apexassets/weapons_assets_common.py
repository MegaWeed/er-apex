"""T022 reusable local export/analysis; all writes stay in the caller's task root."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import struct
import sys
sys.dont_write_bytecode = True
import numpy as np
import battery_assets as ba
from battery_assets import ea, oa, EXE, nodes, Model, Animation, model_data, skeleton_data, animation_data, qc_sections, rson_arrays, dump, normal
from verify_assets import read_smd


def checked(path, root):
    path = Path(path).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f'Output outside exclusive task root: {root}')
    path.mkdir(parents=True, exist_ok=True)
    return path


def comparison(out, previous):
    rows = []
    for folder in ('cast', 'raw', 'smd', 'dds'):
        for old in sorted((previous/folder).rglob('*')):
            if not old.is_file(): continue
            relative = old.relative_to(previous); new = out/relative
            rows.append(dict(path=relative.as_posix(), old_size=old.stat().st_size,
                new_size=new.stat().st_size if new.is_file() else None,
                status='same_bytes' if new.is_file() and old.read_bytes()==new.read_bytes() else 'different' if new.is_file() else 'not_exported'))
    added = [p.relative_to(out).as_posix() for folder in ('cast','raw','smd','dds') for p in sorted((out/folder).rglob('*'))
             if p.is_file() and not (previous/p.relative_to(out)).is_file()]
    result = dict(previous=str(previous), compared=rows, added_files=added,
        same_bytes=sum(r['status']=='same_bytes' for r in rows), different=[r for r in rows if r['status']=='different'],
        missing=[r for r in rows if r['status']=='not_exported'], note='Direct file content comparison; no hashes.')
    dump(out/'earlier-export-comparison.json',result)
    return result


def verify_inventory(out):
    inv=oa.load_json(out/'inventory.json'); paths=set(); count=0
    for r in [r for a in inv['assets'] for r in a['output_files']]+inv['derived_files']:
        path=(out/r['path']).resolve()
        if not path.is_relative_to(out) or r['path'].lower() in paths or not path.is_file() or path.stat().st_size!=r['size']:
            raise ValueError(f'Inventory path/size/coverage: {r}')
        paths.add(r['path'].lower());count+=1
    for folder in oa.EXPORT_FOLDERS:
        for p in (out/folder).rglob('*'):
            if p.is_file() and oa.relpath(p,out).lower() not in paths: raise ValueError(f'Unlisted export: {p}')
    checks=[]
    for m in oa.load_json(out/'models.json')['models']:
        bones=oa.load_json(out/m['skeleton_file'])['bones'];qc=oa.asset_file(out,'smd',m['asset'],'.qc')
        total=0;error=0.
        for p in sorted(qc.parent.glob(qc.stem+'_*_lod0.smd')):
            b,t,n=read_smd(p);total+=n
            if b!=[(x['index'],x['name'],x['parent_index']) for x in bones]: raise ValueError(f'SMD hierarchy: {p}')
            for x in bones: error=max(error,float(abs(np.asarray(t[x['index']][:3])-x['local_position']).max()))
        if total!=m['triangles'] or error>=1e-4: raise ValueError(f'SMD/Cast geometry: {m["file"]}')
        checks.append(dict(model=m['asset_path'],bones=len(bones),triangles=total,smd_cast_max_position_error=error))
    tables=oa.load_json(out/'ability_sequences.json')['models']
    return dict(status='PASS',verified_files=count,verified_assets=len(inv['assets']),models=len(checks),
        rigs=len(oa.load_json(out/'rigs.json')['rigs']),materials=len(oa.load_json(out/'materials.json')['materials']),
        textures=sum(a['type']=='txtr' for a in inv['assets']),sequences=sum(t['sequence_count'] for t in tables),
        clips=sum(t['clip_count'] for t in tables),mesh_checks=checks,pending=inv['pending'])


def analyze(out, previous):
    by_guid,by_name=oa.indexes(oa.list_rows(out));selection=oa.load_json(out/'export_selection.json');identities={}
    materials=oa.material_data(out,by_guid,by_name,identities)
    for mat in materials.values():
        usages={}
        for tex in sorted(mat['textures'],key=lambda t:t['slot']):
            usage=tex['usage']; k=usages.get(usage,0);usages[usage]=k+1
            suffix=(f'_{k}' if k else '')+usage+'.png'
            for p in (out/'cast/mdl').rglob(Path(mat['name']).name+suffix): identities[oa.relpath(p,out)]=by_guid[tex['guid']]
    models={};rigs={};animations={}
    for p in sorted((out/'cast').rglob('*.cast')):
        for node in nodes(p):
            guid=f'{node.Hash():016x}';row=by_guid[guid];identities[oa.relpath(p,out)]=row
            if isinstance(node,Model):
                bones=skeleton_data(node.Skeleton())
                if row['type']=='arig': rigs[guid]=dict(asset=row,file=oa.relpath(p,out),bone_count=len(bones),bones=bones)
                elif p.name.endswith('_LOD0.cast'): models[guid]=dict(model_data(node),asset=row,file=oa.relpath(p,out),skin=0,bones=bones,material_guids=[f'{m.Hash():016x}' for m in node.Materials()])
            elif isinstance(node,Animation):
                index=int(re.search(r'_(\d+)\.cast$',p.name)[1]);animations.setdefault(guid,{})[index]=dict(animation_data(node),file=oa.relpath(p,out))
                rel=p.relative_to(out/'cast').with_name(re.sub(r'_\d+$','',p.stem))
                for ext in ('.rseq','.rseq_extn','.json'):
                    raw=(out/'raw'/rel).with_suffix(ext)
                    if raw.is_file():identities[oa.relpath(raw,out)]=row
    deps=[]
    for rig in rigs.values():
        p=oa.asset_file(out,'raw',rig['asset'],'.rson');refs=[oa.asset_reference(v,by_guid,by_name) for v in rson_arrays(p).get('seqs',[])]
        if any(r is None for r in refs):raise ValueError('待定: missing local sequence')
        rig['sequence_reference_count']=len(refs);deps.append(dict(rig=rig['asset'],raw_manifest=oa.relpath(p,out),sequence_references=refs))
        dump(out/'skeletons'/('rig_'+Path(normal(rig['asset']['asset_name'])).stem+'.json'),dict(rig,units='Source inches',quaternion_order='xyzw'))
    summaries=[];tables=[];qcs={oa.relpath(p,out):qc_sections(p) for p in sorted((out/'smd').rglob('*.qc'))}
    for target in selection['targets']:
        info=models[target['asset']['guid']];rawp=oa.asset_file(out,'raw',target['asset'],'.rmdl');raw=rawp.read_bytes()
        nb,nm,nl=[struct.unpack_from('<H',raw,o)[0] for o in (0x74,0xac,0xca)]
        lods=sorted(p.name for p in oa.asset_file(out,'cast',target['asset'],'.cast').parent.glob(rawp.stem+'_LOD*.cast'))
        if (nb,nm)!=(info['bone_count'],info['mesh_count']) or lods!=sorted(rawp.stem+f'_LOD{i}.cast' for i in range(nl)):raise ValueError('RMDL/Cast LOD coverage differs')
        info['raw_model_header']=dict(bone_count=nb,mesh_count=nm,lod_count=nl,cast_lods=lods,offsets=dict(bone_count=0x74,mesh_count=0xac,lod_count=0xca))
        stem=Path(normal(target['asset_path'])).stem;skel=f'skeletons/{stem}.json'
        dump(out/skel,dict(asset=info['asset'],source_file=info['file'],bone_count=nb,bones=info.pop('bones'),units='Source inches',quaternion_order='xyzw',world_transform_rule='parent_world @ local_TRS'))
        info.update(role=target['role'],asset_path=target['asset_path'],source_rpak=target['asset']['file_name'],guid=target['asset']['guid'],skeleton_file=skel,rigs=target['rigs'],materials=[materials[g] for g in info['material_guids']]);summaries.append(info)
        refs={r['guid']:r for r in target.get('inline_sequences',[])}
        for rig in target['rigs']:
            refs.update({r['guid']:r for d in deps if d['rig']['guid']==rig['guid'] for r in d['sequence_references']})
        seqs=[];parents=[target['asset']]+target['rigs'];parent_qcs={oa.relpath(oa.asset_file(out,'smd',r,'.qc'),out) for r in parents}
        for guid,row in refs.items():
            p=oa.linked_sequence_file(out,row,parents);meta=oa.rseq_metadata(p);clips=animations[guid]
            if len(clips)!=meta['blend_count']:raise ValueError(f'Blend count: {p}')
            for sample in meta['blends']:
                c=clips[sample['blend_index']]
                if c['framerate']!=sample['framerate'] or c['frame_count'] is not None and c['frame_count']!=sample['frame_count']:raise ValueError(f'RSEQ timing: {p}')
                sample.update(cast_file=c['file'],cast_frame_count=c['frame_count'],cast_curve_count=c['curve_count'])
            blocks=[dict(file=q,raw_qc=block) for q,(_,sects) in qcs.items() if q in parent_qcs for kind,n,block in sects if kind=='sequence' and n.lower()==meta['name'].lower()]
            if not blocks:raise ValueError(f'Missing QC: {p}')
            seqs.append(dict(meta,asset_path=row['asset_name'].replace('\\','/'),guid=guid,source_rpak=row['file_name'],raw_file=oa.relpath(p,out),qc=blocks))
        seqs.sort(key=lambda s:normal(s['asset_path']))
        table=dict(role=target['role'],model=target['asset'],rigs=target['rigs'],sequence_count=len(seqs),clip_count=sum(s['blend_count'] for s in seqs),sequences=seqs)
        tables.append(table);dump(out/f'sequences/{stem}.json',table)
    dump(out/'models.json',dict(models=summaries));dump(out/'rigs.json',dict(rigs=list(rigs.values())))
    dump(out/'materials.json',dict(materials=list(materials.values()),usage_note='Literal local RSX texture types'))
    dump(out/'rig_dependencies.json',dict(models=selection['targets'],rigs=deps));dump(out/'ability_sequences.json',dict(models=tables))
    dump(out/'qc_metadata.json',dict(files=[dict(file=q,raw_qc=t) for q,(t,_) in qcs.items()]))
    comparison(out,previous)
    # The common list also has other model names starting with the projectile
    # stem; identify our SMD/QC descendants from the exact selected model.
    for target in selection['targets']:
        row=target['asset'];stem=Path(normal(row['asset_name'])).stem
        parent=oa.asset_file(out,'smd',row,'.qc').parent
        for p in (out/'smd').rglob('*'):
            if p.is_file() and normal(p.parent)==normal(parent) and p.name.lower().startswith(stem) and p.suffix in ('.smd','.qc'):
                identities[oa.relpath(p,out)]=row
    oa.assign_remaining_files(out,by_guid,by_name,identities);oa.write_inventory(out,identities,selection)
    inv=oa.load_json(out/'inventory.json');default=selection['targets'][0]['asset']
    for asset in inv['assets']:
        for r in asset['output_files']:r.update(source_rpak=asset['source_rpak'],guid=asset['guid'],asset_path=asset['asset_path'],format_check=ba.format_check(out/r['path']))
    for r in inv['derived_files']:
        source=next((m['asset'] for m in summaries if r['path']==m['skeleton_file']),default)
        source=next((g['asset'] for g in rigs.values() if r['path']=='skeletons/rig_'+Path(normal(g['asset']['asset_name'])).stem+'.json'),source)
        r.update(source_rpak=source['file_name'],guid=source['guid'],asset_path=source['asset_name'].replace('\\','/'),format_check=ba.format_check(out/r['path']),provenance='T022 derived record; dependency records list all exact source assets')
    inv.update(task='T022');dump(out/'inventory.json',inv);result=verify_inventory(out);dump(out/'verification.json',result);return result


def export(out, targets, previous, required_rig=None):
    if not EXE.is_file():raise FileNotFoundError(EXE)
    for d in ('lists','logs','skeletons','sequences'):(out/d).mkdir(parents=True,exist_ok=True)
    ea.OUT,ea.CACHE,ea.PACKAGES,ea.RUNS=out,out/'logs/rsx_runtime',['common.rpak'],[]
    os.environ['MPLCONFIGDIR']=str(ea.CACHE/'matplotlib')
    ea.run(EXE,'core_named','cast',flags=['-metadataonly']);by_guid,by_name=oa.indexes(oa.list_rows(out))
    selected=[dict(role=role,asset_path=by_guid[guid]['asset_name'],asset=by_guid[guid]) for role,guid in targets]
    names=[t['asset_path'] for t in selected];exact=['--exportexact',','.join(names)]
    ea.run(EXE,'models_cast','cast','mdl_',flags=exact+['-matltextures','--format-matl','2'])
    ea.run(EXE,'models_raw','raw','mdl_',flags=exact+['--format-mdl_','2'])
    pending=[];selected,rigs,_=oa.model_links(out,selected,by_guid,by_name,pending)
    if pending:raise ValueError(f'待定: {pending}')
    if required_rig and required_rig not in rigs:raise ValueError('Model/rig dependency differs')
    materials=set()
    for t in selected:
        p=oa.asset_file(out,'cast',t['asset'],'.cast');p=p.with_name(p.stem+'_LOD0.cast');mdl=next(n for n in nodes(p) if isinstance(n,Model))
        materials.update(by_guid[f'{m.Hash():016x}']['asset_name'] for m in mdl.Materials())
    mats=','.join(sorted(materials))
    ea.run(EXE,'materials','cast','matl',flags=['--exportexact',mats,'--format-matl','2','-matltextures'])
    ea.run(EXE,'materials_dds','dds','matl',flags=['--exportexact',mats,'--format-matl','2','--format-txtr','2','-matltextures'])
    rnames=[r['asset_name'] for r in rigs.values()]
    if rnames:
        ea.run(EXE,'rigs_cast','cast','arig',flags=['--exportexact',','.join(rnames),'-exportrigsequences'])
        ea.run(EXE,'rigs_raw','raw','arig',flags=['--exportexact',','.join(rnames),'--format-arig','2','--format-aseq','2','-exportrigsequences'])
    ea.run(EXE,'smd_qc','smd','mdl_,arig',flags=['--exportexact',','.join(names+rnames),'--format-mdl_','3','--format-arig','3','--format-aseq','3'])
    dump(out/'export_selection.json',dict(task='T022',targets=selected,rigs=list(rigs.values()),pending=pending))
    return analyze(out,previous)
