"""Independent package readback and negative enabled-bone validation."""
import copy
import hashlib
import subprocess
from pathlib import Path
import numpy as np
from geometry import PARTS,read,save,winding


def array(folder,sub,key):
    width=dict(positions=3,normals=3,tangents=4,uv0=2,uv1=2,bone_indices=4,bone_weights=4,flver_bone_weights=4,indices=3)[key]
    dtype='u1' if key=='bone_indices' else '<u4' if key=='indices' else '<f4'
    return np.fromfile(folder/sub[key],dtype).reshape(-1,width)


def quantize(bw):
    scaled=bw.astype(np.float64)*255;ints=np.floor(scaled).astype(int);rank=np.argsort(-(scaled-ints),axis=1,kind='stable')
    for i,left in enumerate(255-ints.sum(1)):ints[i,rank[i,:left]]+=1
    return ints


def verify(out,run,tool,extract):
    results={};readback=out/'readback'
    for variant in ('package','package_flipy'):
        pkg=out/variant;inputroot=out/('fusemesh' if variant=='package' else 'fusemesh_flipy');summary={}
        for path in sorted(pkg.rglob('*.dcx')):
            assert path.read_bytes()[0x28:0x2c]==b'KRAK'
            target=readback/variant/path.stem;command=[extract,'unpack',path,'--out',target]
            if path.parent.name=='material':command+=['--filter','_M_0999']
            run(command,out,'read_'+variant+'_'+path.stem)
        for part in PARTS:
            infolder=inputroot/part;a=read(infolder/'mesh.json');partresults={}
            for lod in ('','_l'):
                folder=readback/variant/f'export_{part}{lod}'
                run([tool,'export-mesh',pkg/f'parts/{part}_m_0999{lod}.partsbnd.dcx','--matbin-bnd',pkg/'material/allmaterial.matbinbnd.dcx','--out',folder],out,f'export_{variant}_{part}{lod}')
                b=read(folder/'mesh.json');assert len(a['submeshes'])==len(b['submeshes']);vertices=0;triangles=0;weight_error=0.;normal_error=0.;uv_error=0.
                for s,t in zip(a['submeshes'],b['submeshes']):
                    assert s['vertex_count']==t['vertex_count'];assert s['index_count']==t['index_count'];vertices+=s['vertex_count'];triangles+=s['index_count']//3
                    for key in ('positions','indices'):assert (infolder/s[key]).read_bytes()==(folder/t[key]).read_bytes(),(part,key)
                    w=array(infolder,s,'bone_weights');new=array(folder,t,'flver_bone_weights');q=quantize(w)
                    assert np.array_equal(q,np.rint(new*255).astype(int)),(part,'weight quantization')
                    names_a=np.asarray(a['bones'])[array(infolder,s,'bone_indices')];names_b=np.asarray(b['bones'])[array(folder,t,'bone_indices')]
                    assert np.array_equal(names_a,names_b),(part,'bone names')
                    weight_error=max(weight_error,float(np.max(abs(w-new))))
                    for key in ('normals','tangents'):
                        err=float(np.max(abs(array(infolder,s,key)-array(folder,t,key))));normal_error=max(normal_error,err);assert err<=1/127+1e-6
                    for key in ('uv0','uv1'):
                        err=float(np.max(abs(array(infolder,s,key)-array(folder,t,key))));uv_error=max(uv_error,err);assert err<=1/2048+1e-6
                    assert len(t['face_sets'])==6
                unpack=readback/variant/f'{part}_m_0999{lod}.partsbnd';flver=next(unpack.rglob('*.flver'))
                dump=read_json_command(run,[tool,'flver',flver,'--samples','0'],out,f'flver_{variant}_{part}{lod}')
                save(folder/'flver.json',dump)
                assert all('Bone' in dump['Nodes'][i]['Flags'] and 'Disabled' not in dump['Nodes'][i]['Flags'] for m in dump['Meshes'] for i in m['BoneIndexRange']['ActiveIndices'])
                from verify_armor_bounds import verify as bounds
                from s3a_roundtrip import arrays
                bounds(dump,b,folder,arrays)
                partresults[lod or 'high']=dict(vertices=vertices,triangles=triangles,positions_bit_exact=True,indices_bit_exact=True,bone_names_exact=True,
                    quantized_weights_exact=True,max_weight_error=weight_error,max_normal_tangent_error=normal_error,max_uv_error=uv_error,bounds='PASS')
            summary[part]=partresults
        matdir=readback/variant/'allmaterial.matbinbnd';matcount=0
        for part in PARTS:
            for material in read(inputroot/part/'mesh.json')['materials']:
                stem=f'P[{part.upper()}_M_0999]_'+material['name']
                path=next(p for p in matdir.rglob('*.matbin') if p.stem==stem)
                data=read_json_command(run,[tool,'matbin',path],out,f'matbin_{variant}_{part}_{material["name"]}')['Data']
                params={p['Name']:p['Value'] for p in data['Params']}
                for key,value in material['float_params'].items():assert params[key]==value
                samplers={s['Type']:s['Path'] for s in data['Samplers']}
                for key in material['sampler_textures']:assert f'{part.upper()}_M_0999_' in samplers[key] and 'AAT' not in samplers[key]
                matcount+=1
        summary['cloned_matbins_verified']=matcount
        summary['dcx_files']=len(list(pkg.rglob('*.dcx')));assert summary['dcx_files']==9;results[variant]=summary
    # The green variant must have identical non-normal assets and geometry.
    variant_checks={}
    for part in PARTS:
        a=read(inputroot.parent/'fusemesh'/part/'mesh.json');b=read(inputroot.parent/'fusemesh_flipy'/part/'mesh.json')
        for sa,sb in zip(a['submeshes'],b['submeshes']):
            for key in ('positions','normals','tangents','uv0','uv1','indices','bone_indices','bone_weights'):
                assert (out/'fusemesh'/part/sa[key]).read_bytes()==(out/'fusemesh_flipy'/part/sb[key]).read_bytes()
        for m in a['materials']:
            name=m['name']
            from PIL import Image
            n=np.array(Image.open(out/f'textures/{name}_n.png'));ny=np.array(Image.open(out/f'textures/{name}_n_flipy.png'))
            assert np.array_equal(n[:,:,[0,2,3]],ny[:,:,[0,2,3]]) and np.array_equal(255-n[:,:,1],ny[:,:,1])
        variant_checks[part]=True
        standard=readback/'package'/f'export_{part}';opposite=readback/'package_flipy'/f'export_{part}'
        for dds in standard.glob('*.dds'):
            if not dds.stem.endswith('_n'):assert dds.read_bytes()==(opposite/dds.name).read_bytes(),dds.name
        one=next((readback/'package'/f'{part}_m_0999.partsbnd').rglob('*.flver'))
        two=next((readback/'package_flipy'/f'{part}_m_0999.partsbnd').rglob('*.flver'))
        assert one.read_bytes()==two.read_bytes()
    # Decode a neutral color swatch to detect accidental second sRGB encoding.
    color_dir=out/'checks/color';color_dir.mkdir(parents=True,exist_ok=True)
    swatch=next((readback/'package/export_hd').glob('*detail*_a.dds'))
    texconv=Path(__file__).resolve().parents[1]/'bin/texconv/texconv.exe'
    run([texconv,'-nologo','-y','-ft','png','-o',color_dir,swatch],out,'color_readback')
    from PIL import Image
    pixel=np.array(Image.open(color_dir/(swatch.stem+'.png')))[0,0,:3]
    assert np.max(abs(pixel.astype(int)-129))<=5,pixel
    # A Head reference exists in the BD table but is Disabled; rejection must precede any DCX write.
    bad=out/'checks/disabled_bone';bad.mkdir(parents=True,exist_ok=True)
    source=out/'fusemesh/bd';doc=read(source/'mesh.json');shutil_copy_tree(source,bad)
    # Rewrite the bone with the first active influence so this exercises actual skin use.
    s=doc['submeshes'][0];index=int(array(source,s,'bone_indices')[0,0]);doc['bones'][index]='Head';save(bad/'mesh.json',doc)
    command=[tool,'build-armor','--template-dir',out/'inputs/parts','--template-model','1280','--mesh',bad,'--model','998','--matbin-bnd',out/'inputs/material/allmaterial.matbinbnd.dcx','--out',out/'checks/rejected_package']
    # --template-dir contains mixed model input; AM is 1500.
    command+=['--am-template',out/'inputs/parts/am_m_1500.partsbnd.dcx']
    r=subprocess.run(list(map(str,command)),capture_output=True,encoding='utf-8');(out/'logs/disabled_bone.log').write_text(r.stdout+r.stderr,encoding='utf-8')
    assert r.returncode==1 and 'not enabled' in r.stderr,r.stderr
    assert not list((out/'checks/rejected_package').rglob('*.dcx'))
    print('PASS readback: both variants, all 8 part FLVERs, exact positions/indices/names/quantized weights; bounds and disabled-bone rejection',flush=True)
    return dict(status='PASS',packages=results,flipy_only_green=variant_checks,disabled_bone_rejected=True,neutral_color_decoded_rgb=pixel.tolist())


def read_json_command(run,command,out,label):
    import json
    # Dumps can be large; preserve the subprocess output in log and parse it without printing.
    r=subprocess.run(list(map(str,command)),capture_output=True,encoding='utf-8')
    (out/'logs'/f'{label}.log').write_text(r.stdout+r.stderr,encoding='utf-8')
    if r.returncode:raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


def shutil_copy_tree(source,target):
    import shutil
    shutil.copytree(source,target,dirs_exist_ok=True)


if __name__=='__main__':
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'erdata/scripts'))
    from convert_fuse import DEFAULT,TOOL,EXTRACT,run
    save(DEFAULT/'readback-verification.json',verify(DEFAULT,run,TOOL,EXTRACT))
