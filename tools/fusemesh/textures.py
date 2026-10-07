"""Locally evidenced ER channel packing, with explicit unresolved Apex semantics."""
from pathlib import Path
import struct
import numpy as np
from PIL import Image
from geometry import read,save,PARTS,MODELS


def linear(rgb):
    x=rgb/255.
    return np.where(x<=.04045,x/12.92,((x+.055)/1.055)**2.4)


def make_textures(root,out,names):
    assets=root/'apex-data/assets';materials={m['name'].split('/')[-1]:m for m in read(assets/'materials.json')['materials']}
    dest=out/'textures';dest.mkdir(parents=True,exist_ok=True);audit={};previews={}
    for name in sorted(names):
        src=materials[name];paths={t['usage']:assets/t['file'] for t in src['textures']}
        col=np.asarray(Image.open(paths['_col']).convert('RGBA')).copy();height,width=col.shape[:2]
        def load(usage,default,size=None):
            if usage not in paths:
                sw,sh=size or (width,height)
                return np.full((sh,sw,4),default,dtype=np.uint8)
            im=Image.open(paths[usage]).convert('RGBA')
            if size is not None:im=im.resize(size,Image.Resampling.BILINEAR)
            return np.asarray(im).copy()
        normal=load('_nml',[128,128,0,255]);nh,nw=normal.shape[:2]
        gloss=load('_gls',[64,64,64,255],(nw,nh))[...,0]
        n=np.empty((nh,nw,4),np.uint8);n[...,:2]=normal[...,:2];n[...,2]=gloss;n[...,3]=255
        # A=1 makes w=0 for float19=1, suppressing the second detail layer.
        # Neutral detail samplers additionally suppress the first layer's tint/normal/gloss modulation.
        spc=load('_spc',[10,10,10,255],(width,height));F0=linear(spc[...,:3]).max(2);albedo=linear(col[...,:3]).max(2)
        metallic=np.clip((F0-.04)/np.maximum(albedo-.04,.04),0,1)
        rule='heuristic F0=max(sRGB_to_linear(_spc.RGB)); m=clamp((F0-0.04)/max(max(linear(_col.RGB))-0.04,0.04)); Apex shader not verified'
        if name not in ('fuse_base_body','fuse_base_gear'):
            metallic[:]=0;rule+='; head/hair/eye restricted to dielectric 0 (specular workflow cannot uniquely determine metalness)'
        alpha_rule='opaque 255'
        if name in ('fuse_base_hair','wraith_base_eyeshadow'):
            alpha_rule='_col.A -> BC1 binary alpha; source opacity interpretation pending'
        elif name=='wraith_base_eyecornea':
            # Local source is a black RGB/opaque-A overlay with nonopaque blend states.
            # Alpha test cannot reproduce it: retain all triangles but hide the overlay.
            col[...,3]=0;alpha_rule='transparent fallback A=0; cannot reproduce source alpha-blended corneal overlay with this alpha-test template'
        else:col[...,3]=255
        for suffix,array in [('a',col),('n',n),('m',np.rint(metallic*255).astype(np.uint8))]:Image.fromarray(array).save(dest/f'{name}_{suffix}.png')
        ny=n.copy();ny[...,1]=255-ny[...,1];Image.fromarray(ny).save(dest/f'{name}_n_flipy.png')
        previews[name]=col
        dds_evidence={}
        for t in src['textures']:
            path=assets/'dds/texture'/('0x'+t['guid'].upper()+'.dds')
            if path.exists():
                header=path.read_bytes()[:148];cc=header[84:88].decode('ascii')
                dds_evidence[t['usage']]=dict(path=str(path),fourcc=cc,dxgi=struct.unpack_from('<I',header,128)[0] if cc=='DX10' else None)
        audit[name]=dict(source=src['name'],source_material=str(assets/src['json_file']),shader_set=src['shader_set'],
            source_textures={k:str(v) for k,v in paths.items()},source_dds=dds_evidence,albedo='_col RGB unchanged, no AO multiplication; A per alpha_rule',
            alpha_rule=alpha_rule,normal='raw BC5-exported _nml.R/G; B=_gls.R linear direct; A=255',
            gloss_status='local RSX texture.h labels _gls as glossTexture; numeric gloss remap and AM Rich shader pending game comparison',
            green_status='pending Apex shader convention; package_flipy changes only primary normal G',
            metalness_rule=rule,metalness_mean=float(metallic.mean()),metalness_nonzero_fraction=float((metallic>0).mean()),
            source_alpha_minmax=[int(np.asarray(Image.open(paths['_col']).convert('RGBA'))[...,3].min()),int(np.asarray(Image.open(paths['_col']).convert('RGBA'))[...,3].max())])
    # Neutral linear detail albedo=1/4.55: shader %164..169 multiply base*detail*4.55.
    neutral=np.rint((1.055*(1/4.55)**(1/2.4)-.055)*255).astype(int)
    for suffix,color in [('a',(neutral,neutral,neutral,255)),('n',(128,128,128,255)),('m',(0,0,0,255))]:
        Image.new('RGBA',(8,8),color).save(dest/f'neutral_{suffix}.png')
    save(out/'texture-audit.json',dict(materials=audit,neutral_detail_albedo_srgb=int(neutral),
        er_evidence=str(root/'tools/erdata/docs/armor-materials.md'),apex_evidence=str(root/'tools/apexassets/rsx_source/src/game/rtech/assets/texture.h'),
        limitations=['Apex _spc physical F0 semantics and shader scaling pending; local source _spc DXGI 72 verifies sRGB storage','Apex normal green convention pending',
                     'AM1500 C[DetailBlend_Rich] not covered by existing 13 shader disassembly','cornea alpha blend unavailable; overlay hidden',
                     'hair/eyeshadow alpha test loses smooth transparency']))
    return audit,previews


def material_definition(root,part,name,flipy=False):
    alpha=name in ('fuse_base_hair','wraith_base_eyecornea','wraith_base_eyeshadow')
    template=f'P[{part.upper()}_M_{MODELS[part]}]_'+('Fabric' if part=='hd' and alpha else 'Metal')
    source=read(root/'er-data/s3/material_evidence/matbins.json')[template]['data']
    local={s['type'].split('_')[-1]:s['path'] for s in source['samplers'] if f'{part.upper()}_M_{MODELS[part]}_' in s['path']}
    assert all(k in local for k in ('AlbedoMap','NormalMap','MetallicMap'))
    samplers={s['type']:f'textures/neutral_{role}.png' for s in source['samplers'] if 'AAT' in s['path']
              for ending,role in [('AlbedoMap','a'),('NormalMap','n'),('MetallicMap','m')] if s['type'].endswith(ending)}
    params={p['name']:0. for p in source['params'] if p['type']=='Float' and p['name'].endswith(('float_0','float_2','float_10','float_15'))}
    # Audited 0 and 13: float0=detail gloss offset, float2=base metalness
    # offset, float10=detail normal amplitude, float15=second detail gloss offset.
    params.update({p['name']:1. for p in source['params'] if p['type']=='Float' and p['name'].endswith('float_19')})
    return dict(name=name,template_matbin=template,
        textures={s:f'textures/{name}_{s}'+('_flipy' if s=='n' and flipy else '')+'.png' for s in ('a','n','m')},
        sampler_textures=samplers,float_params=params)
