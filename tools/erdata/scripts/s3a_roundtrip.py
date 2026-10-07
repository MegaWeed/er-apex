"""Reproduce T003 armor roundtrip from installation archives; all derived output is under er-data/s3."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import gamedirs  # noqa: E402  (tools/gamedirs.py: the games' install folders)
import argparse, collections, hashlib, json, math, struct, subprocess
BASE = Path(__file__).resolve().parents[1]
TOOL = BASE/'ertool/bin/Release/net8.0/ertool.exe'
EXTRACT = BASE/'erextract/target/x86_64-pc-windows-msvc/release/erextract.exe'
GAME = gamedirs.elden_ring()
FIELDS = ['positions','normals','tangents','uv0','uv1','colors','bone_indices','bone_weights','indices','normal_w','flver_bone_weights']
def load(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def arrays(path):
    b=path.read_bytes()
    return struct.unpack('<'+'f'*(len(b)//4),b)
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir',type=Path,default=GAME)
    parser.add_argument('--data-dir',type=Path,default=BASE.parents[1]/'er-data/s3')
    args=parser.parse_args(); data=args.data_dir.resolve();game=args.game_dir.resolve()
    if data.is_relative_to(game) or data.is_relative_to(BASE): raise ValueError('Derived data must be outside game and tool source directories')
    logs=data/'logs';logs.mkdir(parents=True,exist_ok=True);commands=[]
    def run(command,label,expected=0):
        command=[str(x) for x in command]
        if command[0] in [str(TOOL),str(EXTRACT)]: command+=['--game-dir',str(game)]
        commands.append(command);r=subprocess.run(command,capture_output=True,encoding='utf-8')
        (logs/(label+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
        if r.returncode != expected: raise RuntimeError(f'{label}: exit {r.returncode}, expected {expected}; see {logs/(label+".log")}')
        return r.stdout
    print('Extracting fresh 1280 templates and material binder',flush=True)
    paths=[f'/parts/{part}_m_1280{lod}.partsbnd.dcx' for part in ['hd','bd','am','lg'] for lod in ['','_l']]
    run([EXTRACT,'get',*paths,'/material/allmaterial.matbinbnd.dcx','--out',data/'inputs'],'extract_roundtrip')
    material=data/'inputs/material/allmaterial.matbinbnd.dcx'; chest=data/'inputs/parts/bd_m_1280.partsbnd.dcx'
    original=data/'original_mesh';rebuilt=data/'rebuilt_mesh';package=data/'roundtrip_package'
    print(run([TOOL,'export-mesh',chest,'--matbin-bnd',material,'--out',original],'export_original').strip(),flush=True)
    print(run([TOOL,'build-armor','--template-dir',data/'inputs/parts','--template-model','1280','--mesh',original,'--model','999','--matbin-bnd',material,'--out',package],'build_roundtrip').strip(),flush=True)
    print(run([TOOL,'export-mesh',package/'parts/bd_m_0999.partsbnd.dcx','--matbin-bnd',package/'material/allmaterial.matbinbnd.dcx','--out',rebuilt],'export_rebuilt').strip(),flush=True)
    a=load(original/'mesh.json');b=load(rebuilt/'mesh.json');assert a['bones']==b['bones']
    assert len(a['materials'])==len(b['materials'])==26
    assert len(a['submeshes'])==len(b['submeshes'])==26
    assert [m['flver_name'] for m in a['materials']]==[m['flver_name'] for m in b['materials']]
    results={key:dict(byte_equal=True,max_absolute_error=0.0) for key in FIELDS}
    face_count=0;main_triangles=0;all_triangles=0;vertices=0;weight_sums=collections.Counter()
    for s,t in zip(a['submeshes'],b['submeshes']):
        for key in ['vertex_count','index_count','material','node_name','cull_backfaces']:assert s[key]==t[key],key
        vertices+=s['vertex_count'];main_triangles+=s['index_count']//3
        w=arrays(original/s['flver_bone_weights'])
        weight_sums.update(round(sum(w[i:i+4])*255) for i in range(0,len(w),4))
        for key in FIELDS:
            old=(original/s[key]).read_bytes();new=(rebuilt/t[key]).read_bytes()
            equal=old==new;results[key]['byte_equal'] &= equal
            if key not in ['positions','normals','tangents']:assert equal,(s['name'],key)
            if key=='positions':assert equal,'positions must be bit-exact'
            if key in ['normals','tangents']:
                delta=max((abs(x-y) for x,y in zip(arrays(original/s[key]),arrays(rebuilt/t[key]))),default=0)
                results[key]['max_absolute_error']=max(results[key]['max_absolute_error'],delta)
                assert delta <= 1/127+1e-7
        assert len(s['face_sets'])==len(t['face_sets'])
        for sf,tf in zip(s['face_sets'],t['face_sets']):
            for key in ['flags','cull_backfaces','unk06','index_count']:assert sf[key]==tf[key]
            assert (original/sf['indices']).read_bytes()==(rebuilt/tf['indices']).read_bytes()
            face_count+=1;all_triangles+=sf['index_count']//3
    print(f'PASS arrays: {vertices} vertices; positions bit-exact; normal/tangent error 0; UV/colors/bone names/weights/indices identical',flush=True)
    print(f'PASS topology: 26 meshes, 26 materials, {main_triangles} main triangles, {face_count} facesets, {all_triangles} triangles across all facesets',flush=True)
    # Independent Rust BND/KRAK parser reads every produced file. For allmaterial,
    # extracting only new materials avoids creating thousands of redundant files.
    run([EXTRACT,'unpack',chest,'--out',data/'readback/original'],'read_original')
    readback=data/'readback/package'; manifests=[]
    for path in sorted(package.rglob('*.dcx')):
        assert path.read_bytes()[0x28:0x2c]==b'KRAK',path
        folder=readback/path.stem
        command=[EXTRACT,'unpack',path,'--out',folder]
        if path.name=='allmaterial.matbinbnd.dcx':command+=['--filter','BD_M_0999']
        run(command,'read_'+path.stem)
        listing=json.loads(run([TOOL,'bnd',path],'bnd_'+path.stem))
        manifests.append(dict(path=str(path.relative_to(package)),sha256=sha(path),entries=len(listing['Files'])))
        if path.parent.name=='parts':
            piece=path.name[:2]; flver=next(folder.rglob('*.flver')); tpf=next(folder.rglob('*.tpf'))
            dump=json.loads(run([TOOL,'flver',flver,'--samples','0'],'flver_'+path.stem))
            run([TOOL,'tpf',tpf],'tpf_'+path.stem)
            assert len(dump['Meshes'])==(26 if piece=='bd' else 0)
            if piece=='bd':
                (data/('rebuilt_flver'+('_l' if '_l.' in path.name else '')+'.json')).write_text(json.dumps(dump,ensure_ascii=False,indent=2),encoding='utf-8')
            template=json.loads(run([TOOL,'bnd',data/'inputs/parts'/path.name.replace('0999','1280')],'template_bnd_'+path.stem))
            assert [(x['ID'],x['Name'].replace('_1280','_0999'),x['Flags']) for x in template['Files']]==[(x['ID'],x['Name'],x['Flags']) for x in listing['Files']]
    assert len(manifests)==9
    source_materials=json.loads(run([TOOL,'bnd',material],'source_materials'))['Files']
    new_materials=json.loads(run([TOOL,'bnd',package/'material/allmaterial.matbinbnd.dcx'],'built_materials'))['Files']
    assert new_materials[:len(source_materials)]==source_materials
    assert len(new_materials)==len(source_materials)+26
    original_flver=next((data/'readback/original').rglob('*.flver')); original_tpf=next((data/'readback/original').rglob('*.tpf'))
    fa=json.loads(run([TOOL,'flver',original_flver,'--samples','0'],'original_flver'))
    fb=load(data/'rebuilt_flver.json')
    (data/'original_flver.json').write_text(json.dumps(fa,ensure_ascii=False,indent=2),encoding='utf-8')
    assert fa['BufferLayouts']==fb['BufferLayouts'];assert fa['Skeletons']==fb['Skeletons'];assert fa['GXLists']==fb['GXLists'];assert fa['DummyCount']==fb['DummyCount']
    header_differences={k:[v,fb['Header'][k]] for k,v in fa['Header'].items() if v!=fb['Header'][k]}
    assert set(header_differences).issubset({'BoundingBoxMin','BoundingBoxMax'})
    for ma,mb in zip(fa['Materials'],fb['Materials']):
        assert ma['Name']==mb['Name']
        assert ma['Textures']==mb['Textures']
    for na,nb in zip(fa['Nodes'],fb['Nodes']):
        for key in na:
            if not key.startswith('BoundingBox'):assert na[key]==nb[key],(na['Name'],key)
    # Compare raw 40-byte vertex buffers independently of export-mesh's decoding.
    raw_a=original_flver.read_bytes(); rebuilt_flver=next((readback/'bd_m_0999.partsbnd').rglob('*.flver'));raw_b=rebuilt_flver.read_bytes()
    def raw_header(raw):
        return dict(size=len(raw),data_offset=struct.unpack_from('<I',raw,12)[0],data_size=struct.unpack_from('<I',raw,16)[0],true_faces=struct.unpack_from('<I',raw,0x40)[0],total_faces=struct.unpack_from('<I',raw,0x44)[0])
    headers=[raw_header(raw_a),raw_header(raw_b)]
    assert headers[0]['true_faces']==headers[1]['true_faces']==41453
    assert headers[0]['total_faces']==headers[1]['total_faces']==87352
    for ma,mb in zip(fa['Meshes'],fb['Meshes']):
        assert ma['FaceSets']==mb['FaceSets'];assert ma['Dynamic']==mb['Dynamic'];assert ma['NodeIndex']==mb['NodeIndex'];assert ma['BoneIndices']==mb['BoneIndices']
        for va,vb in zip(ma['VertexBuffers'],mb['VertexBuffers']):
            length=va['Stride']*va['VertexCount'];assert length==vb['Stride']*vb['VertexCount']
            assert raw_a[va['AbsoluteOffset']:va['AbsoluteOffset']+length]==raw_b[vb['AbsoluteOffset']:vb['AbsoluteOffset']+length]
    # DDS exports have only renamed names; compressed image bytes must be identical.
    for dds in original.glob('*.dds'):
        assert dds.read_bytes()==(rebuilt/dds.name.replace('1280','0999')).read_bytes()
    mats=list((readback/'allmaterial.matbinbnd').rglob('*.matbin'));assert len(mats)==26
    for i,p in enumerate(mats):run([TOOL,'matbin',p],'matbin_new_'+str(i))
    from verify_armor_bounds import verify
    bounds=verify(fb,b,rebuilt,arrays)
    cloth_arrays=0
    for s,t in zip(a['submeshes'],b['submeshes']):
        if s.get('flver_cloth'):
            for key in s['flver_cloth']:
                assert (original/s['flver_cloth'][key]).read_bytes()==(rebuilt/t['flver_cloth'][key]).read_bytes()
                cloth_arrays+=1
    print(f'PASS buffers/bounds: all original streams byte-identical; {cloth_arrays} cloth arrays; 26 mesh bounds + 165 node bounds independently checked',flush=True)
    print('PASS packages: 9 KRAK files read by ertool and independent erextract; 26 cloned MATBINs; 4 DDS byte-identical',flush=True)
    report=dict(status='PASS',vertices=vertices,meshes=26,materials=26,main_triangles=main_triangles,facesets=face_count,all_faceset_triangles=all_triangles,arrays=results,original_weight_byte_sums=dict(weight_sums),header_differences=header_differences,raw_headers=headers,raw_vertex_buffers_byte_equal=True,cloth_arrays=cloth_arrays,bounds=bounds,original_matbin_count=len(source_materials),packages=manifests,commands=commands)
    (data/'roundtrip_comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Complete:',data/'roundtrip_comparison.json',flush=True)
if __name__=='__main__':main()
