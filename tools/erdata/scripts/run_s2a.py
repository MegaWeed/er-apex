"""Reproduce T002 from the player's own installation, without launching the game."""
from pathlib import Path
import argparse, ctypes, hashlib, json, subprocess, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import gamedirs  # noqa: E402  (tools/gamedirs.py: the games' install folders)
BASE=Path(__file__).resolve().parents[1]
EXTRACT=BASE/'erextract/target/x86_64-pc-windows-msvc/release/erextract.exe'
ERTOOL=BASE/'ertool/bin/Release/net8.0/ertool.exe'
GAME=gamedirs.elden_ring()
def sha256(p):
    h=hashlib.sha256()
    with p.open('rb') as stream:
        while chunk:=stream.read(1<<20):h.update(chunk)
    return h.hexdigest()
def file_version(path):
    api=ctypes.windll.version; size=api.GetFileVersionInfoSizeW(str(path),None)
    if not size:return None
    buf=ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoW(str(path),0,size,buf):return None
    pointer=ctypes.c_void_p();length=ctypes.c_uint()
    if not api.VerQueryValueW(buf,'\\',ctypes.byref(pointer),ctypes.byref(length)):return None
    v=ctypes.cast(pointer,ctypes.POINTER(ctypes.c_uint32));return '.'.join(str(x) for x in [v[2]>>16,v[2]&65535,v[3]>>16,v[3]&65535])
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--game-dir',type=Path,default=GAME);parser.add_argument('--data-dir',type=Path,default=BASE.parents[1]/'er-data');args=parser.parse_args()
    game=args.game_dir.resolve();data=args.data_dir.resolve()
    if data.is_relative_to(game) or data.is_relative_to(BASE):raise ValueError('Game-derived data output must be outside the game and tool source directories')
    extract=data/'extract';output=data/'json';logs=data/'logs';logs.mkdir(parents=True,exist_ok=True)
    history=[]
    def run(command,name,capture=False):
        command=[str(x) for x in command];print(name,flush=True);history.append(command)
        r=subprocess.run(command,capture_output=True,encoding='utf-8')
        (logs/(name+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
        if r.returncode:raise RuntimeError(f'{name} failed; see {logs/(name+".log")}')
        return r.stdout
    dictionary=BASE.parent/'third_party/UXM-Selective-Unpack/UXM/res/EldenRingDictionary.txt'
    names=set(dictionary.read_text(encoding='utf-8-sig').splitlines());armor=[]
    for model in ['1280','1010','1500','1600']:
        for part in ['hd','bd','am','lg']:
            for lod in ['', '_l']:
                path=f'/parts/{part}_m_{model}{lod}.partsbnd.dcx'
                if path not in names:raise ValueError(f'Missing dictionary entry {path}')
                armor.append(path)
    binders=['/chr/c0000.anibnd.dcx',*armor]
    run([EXTRACT,'--game-dir',game,'get',*binders,'--out',extract,'--dcx','--unbnd'],'extract_s2a')
    # Map identity was verified by matching BonfireWarpParam -> MSB EntityID -> PlaceName.
    mapinputs=['/map/mapstudio/m10_00_00_00.msb.dcx','/event/m10_00_00_00.emevd.dcx']
    messages=['/msg/engus/item.msgbnd.dcx','/msg/zhocn/item.msgbnd.dcx']
    run([EXTRACT,'--game-dir',game,'get',*mapinputs,*messages,'--out',extract],'extract_smoke')
    run([EXTRACT,'--game-dir',game,'get',*messages,'--out',extract,'--dcx','--unbnd'],'extract_fmg')
    run([EXTRACT,'--game-dir',game,'get','/material/allmaterial.matbinbnd.dcx','--out',extract,'--dcx','--unbnd'],'extract_material')
    def dump(command,source,relative,*extra):
        run([ERTOOL,command,source,*extra,'--game-dir',game,'--json','--out',output/relative],command+'_'+Path(relative).stem)
    dump('hkx-skeleton',next((extract/'chr/c0000.anibnd').rglob('Skeleton.hkx')),'c0000_skeleton.json')
    for path in sorted((extract/'parts').rglob('*.flver')):dump('flver',path,'parts/'+path.stem+'.json')
    dump('msb',extract/'map/mapstudio/m10_00_00_00.msb.dcx','smoke/m10_00_00_00.msb.json')
    dump('emevd',extract/'event/m10_00_00_00.emevd.dcx','smoke/m10_00_00_00.emevd.json')
    for table in ['BonfireWarpParam','EquipParamProtector']:dump('param',game/'regulation.bin','smoke/'+table+'.json',table)
    for lang in ['engus','zhocn']:
        dump('fmg',extract/f'msg/{lang}/item.msgbnd.dcx',f'smoke/{lang}_item.json')
        dump('fmg',next((extract/f'msg/{lang}/item.msgbnd').rglob('PlaceName.fmg')),f'smoke/{lang}_PlaceName.json')
    dump('matbin',next((extract/'material').rglob('*.matbin')),'smoke/sample_matbin.json')
    dump('tpf',next((extract/'parts/bd_m_1280.partsbnd').rglob('*.tpf')),'smoke/sample_tpf.json')
    dump('bnd',extract/'msg/engus/item.msgbnd.dcx','smoke/sample_bnd.json')
    dump('dcx',extract/'map/mapstudio/m10_00_00_00.msb.dcx','smoke/sample_dcx.json')
    listing=run([EXTRACT,'--game-dir',game,'list'],'archive_list');entries={}
    for line in listing.splitlines()[1:]:
        path,archive,size=line.split('\t');entries[path]={'archive':archive,'size':int(size)}
    original_files=[game/'eldenring.exe',game/'regulation.bin',*[game/(name+'.bhd') for name in ['Data0','Data1','Data2','Data3','DLC']]]
    source={'GameDir':str(game),'ExeVersion':file_version(game/'eldenring.exe'),'InputFiles':[{'Path':str(p),'Size':p.stat().st_size,'Sha256':sha256(p)} for p in original_files],'Archives':[{ 'Path':str(game/(name+'.bdt')),'Size':(game/(name+'.bdt')).stat().st_size} for name in ['Data0','Data1','Data2','Data3','DLC']],'ExtractedPaths':{p:entries[p] for p in binders+mapinputs+messages+['/material/allmaterial.matbinbnd.dcx']},'Commands':history,'Dependencies':json.loads((BASE/'dependencies.lock.json').read_text(encoding='utf-8'))}
    (data/'provenance.json').write_text(json.dumps(source,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    run([sys.executable,BASE/'scripts/analyze_s2a.py',output],'analysis')
    run([sys.executable,BASE/'scripts/verify_s2a.py',data,game],'verification')
    artifacts=[{'Path':str(p.relative_to(data)),'Size':p.stat().st_size,'Sha256':sha256(p)} for p in sorted(output.rglob('*')) if p.is_file()]
    (data/'artifact_manifest.json').write_text(json.dumps(artifacts,indent=2)+'\n',encoding='utf-8')
    print('Complete:',output/'s2a_summary.md',flush=True)
if __name__=='__main__':main()
