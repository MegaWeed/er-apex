"""T021 append default battery meshes to exact T020 injector inputs, using T011 rules."""
import sys
from pathlib import Path
import shutil
sys.dont_write_bytecode = True
import numpy as np
from PIL import Image
from common import ROOT, read, save, unit, winding, tangent_basis, file_info, Q, MIRROR
sys.path.insert(1,str(ROOT/'tools/apexpov'))
import battery_common as bc
import mesh_ability as ma
from mesh_pov import merged_weights, write_part, STREAMS
from pov_textures import texture_arrays
from verify_pov import stream


def mapping():
    data=bc.layout()
    old,_=ma.mapping()
    carriers=[dict(c) for c in old['carriers'] if c['parts'] == ['hd']]
    carriers += [dict(carrier=c['name'],owner=c['source_bone'],parts=['hd']) for c in data['new_carriers']]
    owners={c['owner']:c['owner'] for c in carriers}
    for f in data['ancestor_fallbacks']: owners[f['source_bone']]=f['ancestor']
    return dict(carriers=carriers,owner_of_bone=owners),data


def sources():
    mdl,meshes,_=bc.selected()
    return [('epipen',m,mesh) for key,m,mesh in ma.sources() if key == 'epipen']+[('battery',mdl,mesh) for mesh in meshes]


def texture_sources():
    result={k:v for k,v in ma.texture_sources().items() if k.startswith('octane_injector')}
    materials={Path(m['name']).name:m for m in read(bc.ASSETS/'materials.json')['materials']}
    for _,_,mesh in [s for s in sources() if s[0]=='battery']:
        name=mesh.Material().Name(); material=materials[name]
        # Slot 0/1 are the primary col/nml. Duplicate types are secondary shader inputs.
        paths={}
        for t in sorted(material['textures'],key=lambda t:t['slot']):
            paths.setdefault(t['usage'].lstrip('_'),bc.ASSETS/next(p for p in t['files'] if p.endswith('.png')))
        bc.require(all(k in paths for k in ('col','nml','gls','spc')),'Missing primary texture')
        result[name]=paths
    return result


def make_textures(out):
    folder=out/'textures';folder.mkdir(parents=True,exist_ok=True);report={}
    for name,paths in texture_sources().items():
        col,normal,metal=texture_arrays(paths)
        for suffix,pixels in [('a',col),('n',normal),('m',np.rint(metal*255).astype(np.uint8))]:
            Image.fromarray(pixels).save(folder/f'{name}_{suffix}.png')
        report[name]=dict(sources={k:file_info(p) for k,p in paths.items()},selected_slots='First local texture of each usage; primary col/nml slots 0/1',
                         albedo='Source RGB unchanged; alpha 255',normal='Source nml RG; gls R in B; A=255',metalness='T011/T005 heuristic')
    for p in (bc.BASE_MODEL/'textures').glob('*.png'):
        if p.name.startswith('octane_injector') or p.name.startswith('neutral_'): shutil.copyfile(p,folder/p.name)
    save(out/'battery-texture-audit.json',dict(materials=report,limitations=[
        'Opaque Metal approximation for glass/energy; source emissive, AO, cavity and secondary col/nml slots preserved in export but not sampled.',
        'Missing UV1 is duplicated from UV0 as in T020; neutral details.', 'Normal green and metallic approximation require runtime lighting review.']))


def convert(out):
    mapped,data=mapping(); oldfolder=bc.BASE_MODEL/'fusemesh/hd';old=read(oldfolder/'mesh.json')
    carrier_index={c['carrier']:i for i,c in enumerate(mapped['carriers'])};meshes=[]
    for s in old['submeshes']:
        m=dict(name=s['name'],model=s['source_model'],material=old['materials'][s['material']]['name'])
        for key in STREAMS: m[key]=stream(oldfolder,s,key)
        m['bone_indices']=np.asarray([carrier_index[n] for n in old['bones']])[m['bone_indices']]
        for key in ('source_vertex_ids','source_triangle_ids'): m[key]=np.fromfile(oldfolder/s[key],'<u4')
        meshes.append(m)
    report=dict(format='octane-battery-mesh-summary',version=1,model=998,bodygroups=data['bodygroups'],omitted_meshes=data['omitted_meshes'],
        binding='float32(diag(0.0254,0.0254,-0.0254)*Cast); no fitting transforms',
        tangent='T005 V tangent from source; Z mirror and W sign flip',winding='Two flips cancel; source indices',meshes=[],parts={},max_four_weight_loss=0.)
    for key,mdl,mesh in sources():
        if key != 'battery':continue
        p=np.asarray(mesh.VertexPositionBuffer(),float).reshape(-1,3);n=unit(np.asarray(mesh.VertexNormalBuffer(),float).reshape(-1,3))
        uv=np.asarray(mesh.VertexUVLayerBuffer(0),float).reshape(-1,2);second=mesh.VertexUVLayerBuffer(1)
        uv1=np.asarray(second,float).reshape(-1,2) if second is not None else uv.copy()
        f=np.asarray(mesh.FaceBuffer(),int).reshape(-1,3)
        bc.require(not mesh.VertexTangentBuffer(),'Unexpected source tangents')
        _,tangent,sign,fallback=tangent_basis(p,n,uv,f)
        bi,bw,loss,raw_error=merged_weights(mdl,mesh,mapped)
        m=dict(name=mesh.Name(),model='battery',material=mesh.Material().Name(),positions=p*np.diag(Q)[:3],
               normals=unit(np.asarray(mesh.VertexNormalBuffer(),float).reshape(-1,3)*np.diag(MIRROR)),
               tangents=np.c_[unit(tangent*np.diag(MIRROR)),-sign],uv0=uv,uv1=uv1,bone_indices=bi,bone_weights=bw,indices=f,
               source_vertex_ids=np.arange(len(p)),source_triangle_ids=np.arange(len(f)))
        meshes.append(m)
        used=sorted({mdl.Skeleton().Bones()[int(i)].Name() for i,w in zip(mesh.VertexWeightBoneBuffer(),mesh.VertexWeightValueBuffer()) if w>0})
        report['meshes'].append(dict(name=mesh.Name(),bodygroup='body',vertices=len(p),triangles=len(f),material=mesh.Material().Name(),weighted_bones=used,
            carriers=[data['maps']['battery-carriers'][n] for n in used],four_weight_loss_max=float(loss.max()),source_weight_sum_max_error=raw_error,
            tangent_fallback_vertices=fallback,uv1='source' if second is not None else 'duplicate UV0',final_winding=winding(m['positions'],m['normals'],f)))
        report['max_four_weight_loss']=max(report['max_four_weight_loss'],float(loss.max()))
    write_part(out,'hd',meshes,mapped)
    doc=read(out/'fusemesh/hd/mesh.json')
    # This is a stronger condition than regenerating geometrically equivalent injector inputs.
    for s,t in zip(old['submeshes'],doc['submeshes']):
        bc.require(s==t,'Injector metadata changed')
        for key in [*STREAMS,'source_vertex_ids','source_triangle_ids']:
            bc.require((oldfolder/s[key]).read_bytes()==(out/'fusemesh/hd'/t[key]).read_bytes(),'Injector input bytes changed')
    bc.require(doc['materials'][:len(old['materials'])]==old['materials'],'Injector material definitions changed')
    report['parts']['hd']=dict(meshes=len(meshes),vertices=sum(len(m['positions']) for m in meshes),triangles=sum(len(m['indices']) for m in meshes),
                               materials=len(doc['materials']),carriers=doc['bones'])
    report['injector_inputs_byte_identical']=True
    save(out/'battery-mesh-summary.json',report)
    return meshes,report
