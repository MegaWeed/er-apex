"""Meaningful builder checks: basic v1 input, PNG conversion, palette remapping and 32-bit index boundary."""
from pathlib import Path
import copy, json, struct, subprocess, zlib
from s3a_roundtrip import BASE,TOOL,EXTRACT,GAME,load,arrays
from verify_armor_bounds import verify
DATA=BASE.parents[1]/'er-data/s3'
def png(path,color):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    rows=b''.join(b'\0'+bytes(color)*8 for _ in range(8))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',8,8,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b''))
def main():
    root=DATA/'builder_checks';root.mkdir(parents=True,exist_ok=True);logs=root/'logs';logs.mkdir(exist_ok=True)
    def run(command,label,expected=0):
        r=subprocess.run([str(x) for x in command],capture_output=True,encoding='utf-8')
        (logs/(label+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
        assert r.returncode==expected,(label,r.stderr)
        return r.stdout
    original=load(DATA/'original_mesh/mesh.json');mesh=root/'minimal_v1';mesh.mkdir(exist_ok=True)
    # Deliberately reorder and shrink bones: palette index 0 must resolve to Spine2,
    # and palette index 1 must resolve to Spine1, not FLVER nodes 0 and 1.
    doc=dict(format='fusemesh',version=1,space='flver_model',bones=['Spine2','Spine1'],materials=[dict(name='red',template_matbin='P[BD_M_1280]_Fabric',textures={'a':'red.png'}),dict(name='blue',template_matbin='P[BD_M_1280]_Metal',textures={'a':'blue.png'})],submeshes=[])
    png(mesh/'red.png',[220,20,20,255]);png(mesh/'blue.png',[20,20,220,255])
    def floats(name,values):(mesh/name).write_bytes(struct.pack('<'+'f'*len(values),*values));return name
    for i,n in enumerate([3,65537]):
        prefix=f'mesh{i}'
        # Last index 65536 specifically exercises the SoulsFormats off-by-one fix.
        positions=[-0.1,1.2,0,0.1,1.2,0,0,1.4,0]+[0,1.3,0]*(n-3)
        s=dict(name=prefix,material=i,vertex_count=n,index_count=3,
            positions=floats(prefix+'.pos.f32',positions),normals=floats(prefix+'.nrm.f32',[0,0,1]*n),tangents=floats(prefix+'.tan.f32',[1,0,0,1]*n),
            uv0=floats(prefix+'.uv0.f32',[0.25,0.75]*n),uv1=floats(prefix+'.uv1.f32',[0.5,0.5]*n),
            bone_indices=prefix+'.bi.u8',bone_weights=floats(prefix+'.bw.f32',[0.5,0.5,0,0]*n),indices=prefix+'.idx.u32')
        (mesh/s['bone_indices']).write_bytes(bytes([0,1,0,0])*n)
        (mesh/s['indices']).write_bytes(struct.pack('<III',0,1,n-1));doc['submeshes'].append(s)
    (mesh/'mesh.json').write_text(json.dumps(doc,indent=2),encoding='utf-8')
    package=root/'package_0998'
    command=[TOOL,'build-armor','--template-dir',DATA/'inputs/parts','--template-model','1280','--mesh',mesh,'--model','998','--matbin-bnd',DATA/'inputs/material/allmaterial.matbinbnd.dcx','--out',package]
    print(run(command,'valid_v1').strip(),flush=True)
    run([EXTRACT,'unpack',package/'parts/bd_m_0998.partsbnd.dcx','--out',root/'readback'],'readback')
    flver=next((root/'readback').rglob('*.flver'));f=json.loads(run([TOOL,'flver',flver,'--samples','1'],'flver'))
    assert f['Meshes'][1]['VertexCount']==65537
    assert all(v['LayoutIndex']==4 and v['Stride']==40 for m in f['Meshes'] for v in m['VertexBuffers'])
    for m in f['Meshes']:
        v=m['VertexSamples'][0];assert [f['Nodes'][i]['Name'] for i in v['BoneIndices']]==['Spine2','Spine1','Spine2','Spine2']
        assert sum(round(w*255) for w in v['BoneWeights'])==255
        assert v['Colors']==[dict(A=1,R=1,G=1,B=1)]
        assert len(m['FaceSets'])==6
    reread=root/'export';run([TOOL,'export-mesh',package/'parts/bd_m_0998.partsbnd.dcx','--out',reread,'--matbin-bnd',package/'material/allmaterial.matbinbnd.dcx'],'export')
    new=load(reread/'mesh.json');assert (reread/new['submeshes'][1]['indices']).read_bytes()==struct.pack('<III',0,1,65536)
    verify(f,new,reread,arrays)
    manifest=load(package/'build-manifest.json');albedos=[t for t in manifest['textures'] if t['template']=='BD_M_1280_a'];assert len(albedos)==2
    assert all(t['dds']['dxgi']=='BC1_UNORM_SRGB' and t['dds']['width']==8 and t['dds']['height']==8 for t in albedos)
    assert {t['name'] for t in albedos}=={'BD_M_0998_a','BD_M_0998_blue_a'}
    failures={
        'version':lambda d:d.update(version=2),
        'missing_bone':lambda d:d['bones'].__setitem__(0,'NoSuchBone'),
        'path_escape':lambda d:d['submeshes'][0].update(positions='../outside.f32'),
        'invalid_material':lambda d:d['submeshes'][0].update(material=99),
        'wrong_array_size':lambda d:d['submeshes'][0].update(vertex_count=4),
        'unknown_texture_slot':lambda d:d['materials'][0]['textures'].update(unsupported='red.png'),
        'cloth_without_streams':lambda d:d['materials'][0].update(template_matbin='P[BD_M_1280]_Fabric_Cloth'),
    }
    # Restore after each negative run; every failure must leave package files absent.
    for label,mutate in failures.items():
        bad=copy.deepcopy(doc);mutate(bad);(mesh/'mesh.json').write_text(json.dumps(bad),encoding='utf-8')
        out=root/('invalid_'+label);badcommand=command[:-1]+[out]
        run(badcommand,label,1);assert not list(out.rglob('*.dcx'))
    for label,field,data in [
        ('zero_weight','bone_weights',struct.pack('<12f',*([0]*12))),
        ('bad_bone_index','bone_indices',bytes([9,1,0,0])*3),
        ('bad_triangle_index','indices',struct.pack('<III',0,1,3)),
        ('nan_position','positions',struct.pack('<9f',math.nan,1,0,*([0]*6))),
    ]:
        bad=copy.deepcopy(doc);path=mesh/doc['submeshes'][0][field];saved=path.read_bytes();path.write_bytes(data)
        (mesh/'mesh.json').write_text(json.dumps(bad),encoding='utf-8');out=root/('invalid_'+label)
        try:run(command[:-1]+[out],label,1);assert not list(out.rglob('*.dcx'))
        finally:path.write_bytes(saved)
    (mesh/'mesh.json').write_text(json.dumps(doc,indent=2),encoding='utf-8')
    summary=dict(status='PASS',basic_v1=True,reordered_bones=True,default_white_colors=True,png_conversion=True,independent_material_textures=True,index_65536_preserved=True,bounds=True,rejected_invalid_inputs=len(failures)+4)
    (root/'results.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print('PASS builder: basic v1, reordered bones, white color default, PNG->template BC/sRGB, per-material textures, index 65536, bounds; 11 invalid inputs rejected',flush=True)
if __name__=='__main__':
    import math
    main()
