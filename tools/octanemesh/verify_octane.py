"""Independent FLVER/TPF readback, channel checks and full input-bundle preservation."""
import sys
sys.dont_write_bytecode=True
import argparse
import copy
import json
import shutil
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image
from common import ROOT,DEFAULT,TOOL,EXTRACT,TEXCONV,run,ensure_helper,output_path,quantize
from geometry import PARTS,MODELS,read,save,world,trs
from textures import dds_info,linear

if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')


def array(folder,sub,key):
    width=dict(positions=3,normals=3,tangents=4,uv0=2,uv1=2,bone_indices=4,bone_weights=4,flver_bone_weights=4,indices=3)[key]
    dtype='u1' if key=='bone_indices' else '<u4' if key=='indices' else '<f4'
    return np.fromfile(folder/sub[key],dtype).reshape(-1,width)


def dump(command,out,label):return json.loads(run(command,out,label,quiet=True))


def verify_alignment(out):
    align=read(out/'align.json');owners=read(out/'owner-map.json')
    ab=read(ROOT/'apex-data/assets/octane/skeletons/pilot_medium_stim.json')['bones']
    eb=read(ROOT/'er-data/json/c0000_skeleton.json')['Bones']
    source_map=read(ROOT/'er-data/s2b/mapping-v0.json')
    assert align['format']=='fuse-align' and align['version']==1
    assert align['source_bone_names']==[b['name'] for b in ab] and len(ab)==87
    A=np.array(align['apex_rest_er_space']);P=np.array(align['apex_aligned_world'])
    raw=world(ab,lambda b:trs(b['local_position'],b['local_rotation_xyzw'],b['local_scale']),lambda b:b['parent_index'])
    E=world(eb,lambda b:trs(b['Translation'],b['Rotation'],b['Scale']),lambda b:b['ParentIndex'])
    Q=np.array(align['scaled_axis_unit_matrix'])
    assert np.allclose(A,Q@raw@np.linalg.inv(Q),atol=1e-12,rtol=0)
    known={o['source']:o['target'] for o in source_map['source_owners']};inherited=0
    assert [b['source'] for b in owners['bones']]==[b['name'] for b in ab]
    for i,record in enumerate(owners['bones']):
        j=i;depth=0
        while ab[j]['name'] not in known:j=ab[j]['parent_index'];depth+=1;assert j>=0
        assert record['target']==known[ab[j]['name']] and record['owner_ancestor']==ab[j]['name'] and record['ancestor_distance']==depth
        inherited+=depth>0
    assert inherited==16 and owners['mapped_pairs']==60
    assert align['missing_mapping']==[dict(source='def_c_jawA',target='Jaw')]
    expected={(p['source'],p['target']) for p in source_map['mapping'] if p['source'] in align['source_bone_names']}
    assert {(p['owner_apex_bone'],p['er_bone']) for p in align['mapped_bones']}==expected
    position_error=offset_error=0.;mapped=set()
    for record in align['mapped_bones']:
        i=record['apex_index'];j=record['er_index'];mapped.add(i)
        assert ab[i]['name']==record['owner_apex_bone'] and eb[j]['Name']==record['er_bone']
        assert np.array_equal(P[i],record['P']) and np.allclose(E[j],record['E'],atol=1e-12,rtol=0)
        position_error=max(position_error,float(np.linalg.norm(P[i,:3,3]-E[j,:3,3])))
        offset_error=max(offset_error,float(np.max(abs(P[i]@np.array(record['O_b'])-E[j]))))
    for i,b in enumerate(ab):
        if i not in mapped:
            j=b['parent_index'];assert j>=0
            assert np.allclose(P[i],P[j]@np.linalg.inv(A[j])@A[i],atol=1e-12,rtol=0)
    assert position_error==align['max_joint_position_error_m']==0 and offset_error<1e-12
    return dict(mapped_pairs=len(expected),owners=87,new_owner_ancestors=16,max_joint_error_m=position_error,max_offset_identity_error=offset_error)


def verify_channels(out):
    audit=read(out/'texture-audit.json');results={}
    for name,material in audit['materials'].items():
        paths={k:Path(v) for k,v in material['source_textures'].items()}
        def image(path,size=None):
            with Image.open(path) as im:
                im=im.convert('RGBA')
                if size is not None and im.size!=size:im=im.resize(size,Image.Resampling.BILINEAR)
                return np.array(im)
        col=image(paths['_col']);a=image(out/f'textures/{name}_a.png')
        assert np.array_equal(a[...,:3],col[...,:3]) and np.all(a[...,3]==255),(name,'albedo')
        n=image(out/f'textures/{name}_n.png');normal=image(paths['_nml'])
        assert np.array_equal(n[...,:2],normal[...,:2]) and np.all(n[...,3]==255),(name,'normal')
        gloss=image(paths['_gls'],(n.shape[1],n.shape[0]))[...,0]
        assert np.array_equal(n[...,2],gloss),(name,'gloss')
        opposite=image(out/f'textures/{name}_n_flipy.png')
        assert np.array_equal(n[:,:,[0,2,3]],opposite[:,:,[0,2,3]]) and np.array_equal(255-n[:,:,1],opposite[:,:,1]),(name,'green variant')
        spc=image(paths['_spc'],(a.shape[1],a.shape[0]));f0=linear(spc[...,:3]).max(2);albedo=linear(col[...,:3]).max(2)
        expected=np.clip((f0-.04)/np.maximum(albedo-.04,.04),0,1)
        if name=='octane_base_head':expected[:]=0
        m=np.array(Image.open(out/f'textures/{name}_m.png'))
        assert np.array_equal(m,np.rint(expected*255).astype(np.uint8)),(name,'metalness')
        results[name]=dict(albedo_rgb_exact=True,alpha_opaque=True,normal_rg_exact=True,gloss_exact=True,metalness_exact=True,green_only_variant=True)
    return results


def verify(out):
    out=output_path(out);helper=ensure_helper(out);readback=out/'readback';results={};encoded={}
    sys.path.insert(0,str(ROOT/'tools/erdata/scripts'))
    from verify_armor_bounds import verify as bounds
    arrays=lambda path:np.fromfile(path,'<f4').tolist()
    channels=verify_channels(out)
    alignment=verify_alignment(out)
    snapshot=out/'inputs/material/allmaterial.input.matbinbnd.dcx';targets=out/'inputs/material/target-matbins.json'
    # Source MATBINs are independently read from the captured input, rather than trusting the old evidence JSON.
    originals={}
    for part in PARTS:
        stem=f'P[{part.upper()}_M_{MODELS[part]}]_Metal';folder=readback/'template_matbins'/part
        run([EXTRACT,'unpack',snapshot,'--filter',stem+'.matbin','--out',folder],out,'template_matbin_'+part,quiet=True)
        files=[p for p in folder.rglob('*.matbin') if p.stem==stem]
        assert len(files)==1,(stem,len(files))
        originals[part]=dump([TOOL,'matbin',files[0]],out,'template_matbin_dump_'+part)['Data']
    for variant in ('package','package_flipy'):
        pkg=out/variant;inputroot=out/('fusemesh' if variant=='package' else 'fusemesh_flipy');summary={}
        manifest=read(pkg/'build-manifest.json')
        assert manifest['model']==999
        for path in sorted(pkg.rglob('*.dcx')):
            with path.open('rb') as stream:header=stream.read(0x2c)
            assert header[:4]==b'DCX\0' and header[0x28:0x2c]==b'KRAK',path
            target=readback/variant/path.stem;command=[EXTRACT,'unpack',path,'--out',target]
            if path.parent.name=='material':command+=['--filter','_M_0999']
            run(command,out,'unpack_'+variant+'_'+path.stem,quiet=True)
        run([*helper,'verify',snapshot,pkg/'material/allmaterial.matbinbnd.dcx',targets,out/f'material-bundle-verification-{variant}.json'],out,'bundle_verify_'+variant)
        bundle_report=read(out/f'material-bundle-verification-{variant}.json')
        for part in PARTS:
            infolder=inputroot/part;a=read(infolder/'mesh.json');partresults={}
            for material in a['materials']:
                for file in set(material['textures'].values())|set(material['sampler_textures'].values()):
                    assert (infolder/file).read_bytes()==(out/file).read_bytes(),(part,file,'PNG input snapshot')
            for lod in ('','_l'):
                folder=readback/variant/f'export_{part}{lod}'
                run([TOOL,'export-mesh',pkg/f'parts/{part}_m_0999{lod}.partsbnd.dcx','--matbin-bnd',pkg/'material/allmaterial.matbinbnd.dcx','--out',folder],out,f'export_{variant}_{part}{lod}',quiet=True)
                b=read(folder/'mesh.json');assert len(a['submeshes'])==len(b['submeshes']);assert len(a['materials'])==len(b['materials'])
                vertices=triangles=0;weight_error=normal_error=uv_error=0.
                for s,t in zip(a['submeshes'],b['submeshes']):
                    assert s['vertex_count']==t['vertex_count'] and s['index_count']==t['index_count']
                    assert s['material']==t['material'];vertices+=s['vertex_count'];triangles+=s['index_count']//3
                    for key in ('positions','indices'):assert (infolder/s[key]).read_bytes()==(folder/t[key]).read_bytes(),(variant,part,lod,key)
                    w=array(infolder,s,'bone_weights');new=array(folder,t,'flver_bone_weights');q=quantize(w)
                    assert np.array_equal(q,np.rint(new*255).astype(int)),(variant,part,lod,'weight quantization')
                    names_a=np.asarray(a['bones'])[array(infolder,s,'bone_indices')];names_b=np.asarray(b['bones'])[array(folder,t,'bone_indices')]
                    assert np.array_equal(names_a,names_b),(part,'bone names')
                    weight_error=max(weight_error,float(np.max(abs(w-new))))
                    for key in ('normals','tangents'):
                        err=float(np.max(abs(array(infolder,s,key)-array(folder,t,key))));normal_error=max(normal_error,err);assert err<=1/127+1e-6
                    for key in ('uv0','uv1'):
                        err=float(np.max(abs(array(infolder,s,key)-array(folder,t,key))));uv_error=max(uv_error,err);assert err<=1/2048+1e-6
                    assert len(t['face_sets'])==6
                    for face in t['face_sets']:
                        assert (folder/face['indices']).read_bytes()==(infolder/s['indices']).read_bytes()
                        assert face['cull_backfaces']==s['cull_backfaces']
                unpack=readback/variant/f'{part}_m_0999{lod}.partsbnd';flver=next(unpack.rglob('*.flver'))
                data=dump([TOOL,'flver',flver,'--samples','0'],out,f'flver_{variant}_{part}{lod}');save(folder/'flver.json',data)
                template=read(ROOT/f'er-data/json/parts/{part.upper()}_M_{MODELS[part]}.json')
                assert len(data['Nodes'])==len(template['Nodes'])
                for node,original in zip(data['Nodes'],template['Nodes']):
                    for key in ('Name','ParentIndex','Flags','Translation','RotationQuaternion','Scale'):assert node[key]==original[key],(part,key)
                assert all('Bone' in data['Nodes'][i]['Flags'] and 'Disabled' not in data['Nodes'][i]['Flags'] for m in data['Meshes'] for i in m['BoneIndexRange']['ActiveIndices'])
                for material,expected in zip(data['Materials'],a['materials']):
                    assert material['Name']==expected['name']
                    assert Path(material['MTD'].replace('\\','/')).stem==f'P[{part.upper()}_M_0999]_'+expected['name']
                bounds(data,b,folder,arrays)
                textures=[item for item in manifest['textures'] if item['name'].startswith(part.upper()+'_M_0999_')]
                actual_dds={p.stem:p for p in folder.glob('*.dds')}
                assert set(actual_dds)=={item['name'] for item in textures},(variant,part,'TPF texture list')
                for item in textures:
                    source=Path(item['source']);key=(source.name,item['dds']['dxgi']);actual=actual_dds[item['name']]
                    if key not in encoded:
                        target=out/'checks/encoded_textures'/f'item_{len(encoded):03d}';target.mkdir(parents=True,exist_ok=True)
                        command=[TEXCONV,'-nologo','-y','-dx10','-f',item['dds']['dxgi'],'-m','0','-o',target,source]
                        if item['dds']['srgb']:command+=['-srgb']
                        run(command,out,f'encode_check_{len(encoded):03d}',quiet=True)
                        encoded[key]=(target/(source.stem+'.dds')).read_bytes()
                    assert actual.read_bytes()==encoded[key],(variant,part,item['name'],'DDS exact re-encoding')
                    info=dds_info(actual);assert info['width']==item['dds']['width'] and info['height']==item['dds']['height']
                    assert info['mipmaps']==1+int(np.floor(np.log2(max(info['width'],info['height']))))
                partresults[lod or 'high']=dict(vertices=vertices,triangles=triangles,positions_bit_exact=True,indices_bit_exact=True,
                    bone_names_exact=True,quantized_weights_exact=True,nodes_match_template=True,materials_exact=True,textures_exact=True,
                    max_weight_error=weight_error,max_normal_tangent_error=normal_error,max_uv_error=uv_error,bounds='PASS',textures=len(textures))
            summary[part]=partresults
        matdir=readback/variant/'allmaterial.matbinbnd';matcount=0
        for part in PARTS:
            for material in read(inputroot/part/'mesh.json')['materials']:
                stem=f'P[{part.upper()}_M_0999]_'+material['name'];path=next(p for p in matdir.rglob('*.matbin') if p.stem==stem)
                data=dump([TOOL,'matbin',path],out,f'matbin_{variant}_{part}_{material["name"]}')['Data']
                expected=copy.deepcopy(originals[part])
                for param in expected['Params']:
                    if param['Name'] in material['float_params']:param['Value']=material['float_params'][param['Name']]
                for index,sampler in enumerate(expected['Samplers']):
                    old=Path(sampler['Path'].replace('\\','/')).stem
                    if sampler['Type'] in material['sampler_textures']:
                        role='a' if sampler['Type'].endswith('AlbedoMap') else 'n' if sampler['Type'].endswith('NormalMap') else 'm'
                        new=f'{part.upper()}_M_0999_{material["name"]}_detail{index}_{role}'
                    elif old.startswith(f'{part.upper()}_M_{MODELS[part]}_'):
                        candidates=[t for t in manifest['textures'] if t['template']==old and Path(t['source'])==(inputroot/part/material['textures'][old.split('_')[-1]])]
                        assert len(candidates)==1,(part,old);new=candidates[0]['name']
                    else:continue
                    sampler['Path']=sampler['Path'].replace(old,new) if old else new+'.tif'
                expected['SourcePath']=expected['SourcePath'].replace(material['template_matbin'],stem)
                assert data==expected,(variant,part,material['name'],'MATBIN clone data')
                matcount+=1
        summary['cloned_matbins_verified']=matcount;summary['bundle_preservation']={k:bundle_report[k] for k in ('input_entries','output_entries','preserved_entries','replaced_entries','added_entries')}
        summary['dcx_files']=len(list(pkg.rglob('*.dcx')));assert summary['dcx_files']==9;results[variant]=summary
    # The packages differ only in primary normal DDS bytes; geometry and other DDSs are identical.
    assert (out/'package/material/allmaterial.matbinbnd.dcx').read_bytes()==(out/'package_flipy/material/allmaterial.matbinbnd.dcx').read_bytes()
    for part in PARTS:
        for lod in ('','_l'):
            one=next((readback/'package'/f'{part}_m_0999{lod}.partsbnd').rglob('*.flver'))
            two=next((readback/'package_flipy'/f'{part}_m_0999{lod}.partsbnd').rglob('*.flver'))
            assert one.read_bytes()==two.read_bytes()
            for dds in (readback/'package'/f'export_{part}{lod}').glob('*.dds'):
                if not dds.stem.endswith('_n'):assert dds.read_bytes()==(readback/'package_flipy'/f'export_{part}{lod}'/dds.name).read_bytes()
    swatch=next((readback/'package/export_hd').glob('*detail*_a.dds'));color=out/'checks/color';color.mkdir(parents=True,exist_ok=True)
    run([TEXCONV,'-nologo','-y','-ft','png','-o',color,swatch],out,'color_readback',quiet=True)
    pixel=np.array(Image.open(color/(swatch.stem+'.png')))[0,0,:3]
    assert np.max(abs(pixel.astype(int)-129))<=5,pixel
    # Negative validation exercises an actually weighted Disabled Head in the BD template.
    bad=out/'checks/disabled_bone';source=out/'fusemesh/bd';shutil.copytree(source,bad,dirs_exist_ok=True);doc=read(source/'mesh.json')
    index=int(array(source,doc['submeshes'][0],'bone_indices')[0,0]);doc['bones'][index]='Head';save(bad/'mesh.json',doc)
    command=[TOOL,'build-armor','--template-dir',out/'inputs/parts','--template-model','1280','--mesh',bad,'--model','998',
             '--matbin-bnd',out/'inputs/material/allmaterial.builder.matbinbnd','--am-template',out/'inputs/parts/am_m_1500.partsbnd.dcx','--out',out/'checks/rejected_package']
    r=subprocess.run(list(map(str,command)),capture_output=True,encoding='utf-8',errors='replace')
    (out/'logs/disabled_bone.log').write_text(r.stdout+r.stderr,encoding='utf-8')
    assert r.returncode==1 and 'not enabled' in r.stderr,r.stderr
    assert not list((out/'checks/rejected_package').rglob('*.dcx'))
    print('PASS readback: both variants, all 16 part FLVERs; exact geometry/quantized weights/nodes/materials/textures/bounds; input bundle bytes preserved',flush=True)
    return dict(status='PASS',packages=results,source_texture_channels=channels,alignment=alignment,independent_dds_encodings=len(encoded),
                flipy_only_green=True,disabled_bone_rejected=True,neutral_color_decoded_rgb=pixel.tolist())


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,default=DEFAULT)
    args=parser.parse_args();out=output_path(args.out);save(out/'readback-verification.json',verify(out))


if __name__=='__main__':main()
