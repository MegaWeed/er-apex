"""Octane textures: T005 packing with per-file evidence and explicit pending semantics."""
import struct
import numpy as np
from PIL import Image
from geometry import read, save, MODELS


def linear(rgb):
    value = rgb/255.
    return np.where(value<=.04045,value/12.92,((value+.055)/1.055)**2.4)


def dds_info(path):
    with open(path,'rb') as stream: header=stream.read(148)
    if header[:4]!=b'DDS ' or len(header)<128: raise ValueError('Invalid DDS: '+str(path))
    cc=header[84:88].decode('ascii')
    return dict(path=str(path),size_bytes=path.stat().st_size,fourcc=cc,
        dxgi=struct.unpack_from('<I',header,128)[0] if cc=='DX10' else None,
        width=struct.unpack_from('<I',header,16)[0],height=struct.unpack_from('<I',header,12)[0],
        mipmaps=struct.unpack_from('<I',header,28)[0])


def make_textures(root,out,names):
    assets=root/'apex-data/assets/octane'
    materials={m['name'].split('/')[-1]:m for m in read(assets/'materials.json')['materials']}
    dest=out/'textures'; dest.mkdir(parents=True,exist_ok=True); audit={}; previews={}
    for name in sorted(names):
        src=materials[name]; paths={}; dds={}
        for texture in src['textures']:
            pngs=[assets/f for f in texture['files'] if f.lower().endswith('.png')]
            compressed=[assets/f for f in texture['files'] if f.lower().endswith('.dds')]
            if len(pngs)!=1: raise ValueError('Missing or ambiguous local texture: '+name+texture['usage'])
            paths[texture['usage']]=pngs[0]
            if len(compressed)==1: dds[texture['usage']]=dds_info(compressed[0])
        for usage in ('_col','_nml','_gls','_spc'):
            if usage not in paths: raise ValueError('待定：missing required local texture '+name+usage)
        def load(usage,size=None):
            with Image.open(paths[usage]) as image:
                image=image.convert('RGBA')
                if size is not None and image.size!=size: image=image.resize(size,Image.Resampling.BILINEAR)
                return np.array(image)
        col=load('_col'); original_alpha=col[...,3].copy(); height,width=col.shape[:2]
        normal=load('_nml'); nh,nw=normal.shape[:2]
        n=np.empty((nh,nw,4),np.uint8);n[...,:2]=normal[...,:2];n[...,2]=load('_gls',(nw,nh))[...,0];n[...,3]=255
        f0=linear(load('_spc',(width,height))[...,:3]).max(2); albedo=linear(col[...,:3]).max(2)
        metallic=np.clip((f0-.04)/np.maximum(albedo-.04,.04),0,1)
        metal_rule='待定：T005 specular->metalness heuristic clamp((max(linear(_spc))-0.04)/max(max(linear(_col))-0.04,0.04),0,1)'
        if name=='octane_base_head':
            metallic[:]=0; metal_rule+='; head restricted to dielectric 0 by T005 rule (goggles/mask need game review)'
        source_material=read(assets/src['json_file'])
        states=source_material['blendStates']
        # All six local body materials have the same non-blended states as T005 opaque material.
        if source_material['blendStateMask']!='0x0' or set(states)!={'0xF0000000'}:
            raise ValueError('待定：unexpected transparent source material '+name)
        col[...,3]=255
        for suffix,array in [('a',col),('n',n),('m',np.rint(metallic*255).astype(np.uint8))]:
            Image.fromarray(array).save(dest/f'{name}_{suffix}.png')
        opposite=n.copy();opposite[...,1]=255-opposite[...,1];Image.fromarray(opposite).save(dest/f'{name}_n_flipy.png')
        previews[name]=col
        audit[name]=dict(source=src['name'],source_material=str(assets/src['json_file']),shader_set=src['shader_set'],
            source_textures={k:str(v) for k,v in paths.items()},source_dds=dds,source_blend_states=states,
            source_blend_mask=source_material['blendStateMask'],source_shader_type=src['shader_type'],
            source_alpha_minmax=[int(original_alpha.min()),int(original_alpha.max())],source_zero_alpha_pixels=int((original_alpha==0).sum()),
            alpha_rule='opaque A=255; no locally identified alpha-blended body material; meaning of zero-alpha atlas texels 待定',
            transparent=False,albedo='_col.RGB unchanged; no AO multiplication',
            normal='R/G=_nml.R/G; B=_gls.R resized bilinear if needed; A=255',
            green_status='待定：Apex normal green convention; package_flipy flips only main normal G',
            gloss_status='待定：numeric _gls -> ER gloss response; local RSX labels _gls glossTexture',
            metalness_rule=metal_rule,metalness_mean=float(metallic.mean()),metalness_nonzero_fraction=float((metallic>0).mean()),
            unused_channels=[k for k in paths if k not in ('_col','_nml','_gls','_spc')])
    neutral=int(np.rint((1.055*(1/4.55)**(1/2.4)-.055)*255))
    for suffix,color in [('a',(neutral,neutral,neutral,255)),('n',(128,128,128,255)),('m',(0,0,0,255))]:
        Image.new('RGBA',(8,8),color).save(dest/f'neutral_{suffix}.png')
    save(out/'texture-audit.json',dict(materials=audit,transparent_materials=[],neutral_detail_albedo_srgb=neutral,
        er_evidence=str(root/'tools/erdata/docs/armor-materials.md'),
        apex_evidence=str(root/'tools/apexassets/rsx_source/src/game/rtech/assets/texture.h'),
        limitations=['待定：Apex specular physical F0/scaling and metalness approximation',
                     '待定：Apex normal green sign and gloss numerical response',
                     '待定：AM1500 DetailBlend_Rich runtime sampler bindings',
                     '待定：_ilm emissive, _sctr subsurface, _msk, _cav and _ao semantics are not transferred',
                     '待定：source _col zero-alpha texels are forced opaque; inspect atlas boundaries and goggles in game']))
    return audit,previews


def material_definition(root,part,name,flipy=False):
    template=f'P[{part.upper()}_M_{MODELS[part]}]_Metal'
    source=read(root/'er-data/s3/material_evidence/matbins.json')[template]['data']
    local={s['type'].split('_')[-1]:s['path'] for s in source['samplers'] if f'{part.upper()}_M_{MODELS[part]}_' in s['path']}
    assert all(key in local for key in ('AlbedoMap','NormalMap','MetallicMap'))
    samplers={s['type']:f'textures/neutral_{role}.png' for s in source['samplers'] if 'AAT' in s['path']
              for ending,role in [('AlbedoMap','a'),('NormalMap','n'),('MetallicMap','m')] if s['type'].endswith(ending)}
    params={p['name']:0. for p in source['params'] if p['type']=='Float' and p['name'].endswith(('float_0','float_2','float_10','float_15'))}
    params.update({p['name']:1. for p in source['params'] if p['type']=='Float' and p['name'].endswith('float_19')})
    return dict(name=name,template_matbin=template,
        textures={s:f'textures/{name}_{s}'+('_flipy' if s=='n' and flipy else '')+'.png' for s in ('a','n','m')},
        sampler_textures=samplers,float_params=params)
