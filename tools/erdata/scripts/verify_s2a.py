"""Integration checks against the player's own extracted fixtures."""
from pathlib import Path
import json, subprocess, math, struct, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import gamedirs  # noqa: E402  (tools/gamedirs.py: the games' install folders)
BASE=Path(__file__).resolve().parents[1]
DATA=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[3]/'er-data'
EXTRACT=BASE/'erextract/target/x86_64-pc-windows-msvc/release/erextract.exe'
ERTOOL=BASE/'ertool/bin/Release/net8.0/ertool.exe'
GAME=Path(sys.argv[2]) if len(sys.argv)>2 else gamedirs.elden_ring()
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def run(args, expected=0):
    if args[0] in (EXTRACT, ERTOOL): args=[*args,'--game-dir',GAME]
    result=subprocess.run([str(a) for a in args],capture_output=True,encoding='utf-8')
    assert result.returncode==expected,(args,result.stdout,result.stderr)
    return result
checks=0
for path in (DATA/'json/parts').glob('*.json'):
    f=load(path)
    assert f['NodeCount']==len(f['Nodes'])
    assert all(b['PaletteSize']==len(b['BoneIndices']) for b in f['Meshes'])
    for m in f['Meshes']:
        assert all(0<=i<len(f['Nodes']) for i in m['BoneIndexRange']['ActiveIndices'])
        counters={'Normal':0,'Tangent':0,'UV':0}
        for buffer in m['VertexBuffers']:
            slots=[]
            for member in buffer['Members']:
                semantic=member['Semantic'];slots.append(counters.get(semantic,0))
                if semantic in counters: counters[semantic]+=2 if semantic=='UV' and member['Type'] in ['Short4','Float4','Half4','UByte4Norm'] else 1
            for raw,v in zip(buffer['RawSamples'],m['VertexSamples']):
                b=bytes.fromhex(raw['BytesHex']);assert len(b)==buffer['Stride']
                for member,slot in zip(buffer['Members'],slots):
                    start=member['Offset'];chunk=b[start:start+member['Size']];semantic=member['Semantic'];typ=member['Type'];index=slot
                    if typ=='UByte4' and semantic=='Normal':
                        assert all(abs((chunk[i]-127)/127-v['Normals'][index][i])<1e-6 for i in range(3));assert chunk[3]==v['NormalWs'][index];checks+=1
                    if typ=='UByte4' and semantic=='Tangent':
                        assert all(abs((chunk[i]-127)/127-v['Tangents'][index][i])<1e-6 for i in range(4));checks+=1
                    if typ=='UByte4' and semantic=='BoneIndices':assert list(chunk)==v['BoneIndices'];checks+=1
                    if typ=='UByte4Norm' and semantic=='BoneWeights':assert all(abs(chunk[i]/255-v['BoneWeights'][i])<1e-6 for i in range(4));checks+=1
                    if typ=='Short4' and semantic=='UV':
                        uv=struct.unpack('<4h',chunk);assert all(abs(uv[i]/2048-v['UVs'][index+i//2][i%2])<1e-6 for i in range(4));checks+=1
s=load(DATA/'json/c0000_skeleton.json');assert s['BoneCount']==150
assert all(-1<=b['ParentIndex']<len(s['Bones']) for b in s['Bones'])
assert all(abs(sum(x*x for x in b['Rotation'])-1)<1e-4 for b in s['Bones'])
# Real CLI stdout must parse as JSON, including UTF-8 material names.
flver=next((DATA/'extract/parts/bd_m_1280.partsbnd').rglob('*.flver'))
parsed=json.loads(run([ERTOOL,'flver',flver,'--json']).stdout);assert parsed['NodeCount']==165
hk=next((DATA/'extract/chr').rglob('Skeleton.hkx'))
assert json.loads(run([ERTOOL,'hkx-skeleton',hk,'--json']).stdout)['BoneCount']==150
verify=DATA/'verification';verify.mkdir(exist_ok=True)
run([EXTRACT,'get','/parts/bd_m_1280.partsbnd.dcx','--out',verify,'--dcx','--unbnd'])
assert next((verify/'parts/bd_m_1280.partsbnd').rglob('*.flver')).read_bytes()==flver.read_bytes()
assert list(verify.rglob('*.tpf'))
run([EXTRACT,'get','/map/mapstudio/m10_00_00_00.msb.dcx','--out',verify,'--dcx'])
a=json.loads(run([ERTOOL,'msb',DATA/'extract/map/mapstudio/m10_00_00_00.msb.dcx','--json']).stdout)
b=json.loads(run([ERTOOL,'msb',verify/'map/mapstudio/m10_00_00_00.msb','--json']).stdout)
a.pop('Source');b.pop('Source');assert a==b
assert all(region['Data']['Shape'].get('Type') for region in a['Regions'])
assert any('Width' in region['Data']['Shape']['Data'] for region in a['Regions'])
run([EXTRACT,'get','/does_not_exist.dcx','--out',verify],expected=1)
run([ERTOOL,'unknown',flver,'--json'],expected=1)
malformed=verify/'truncated.flver';malformed.write_bytes(b'FLVER\0')
run([ERTOOL,'flver',malformed,'--json'],expected=1)
h=run([EXTRACT,'hash',r'PARTS\BD_M_1280.partsbnd.dcx']).stdout.strip()
v=0
for c in b'/parts/bd_m_1280.partsbnd.dcx':v=(v*0x85+c)&((1<<64)-1)
assert h==f'0x{v:016x}'
listing=run([EXTRACT,'list','--filter','/parts/*_m_1280*.partsbnd.dcx']).stdout.strip().splitlines();assert len(listing)==9
for lang in ['engus','zhocn']:
    places=load(DATA/f'json/smoke/{lang}_PlaceName.json');assert len(places['Entries'])==1049
print(f'PASS: {checks} raw member decoding checks across 32 FLVERs; CLI stdout, DCX parity, extraction parity, wildcard list, hash, invalid input and skeleton invariants.')
