"""Reproduce armor MATBIN/TPF evidence and local DetailBlend shader disassembly."""
from pathlib import Path
import argparse, hashlib, json, struct, subprocess, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import gamedirs  # noqa: E402  (tools/gamedirs.py: the games' install folders)
BASE=Path(__file__).resolve().parents[1]
TOOL=BASE/'ertool/bin/Release/net8.0/ertool.exe'
EXTRACT=BASE/'erextract/target/x86_64-pc-windows-msvc/release/erextract.exe'
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=BASE.parents[1]/'er-data/s3')
    parser.add_argument('--game-dir',type=Path,default=gamedirs.elden_ring())
    parser.add_argument('--texconv',type=Path,default=Path(__file__).resolve().parents[2]/'bin/texconv/texconv.exe')
    parser.add_argument('--dxc',type=Path,default=Path('C:/Program Files (x86)/Windows Kits/10/bin/10.0.26100.0/x64/dxc.exe'))
    args=parser.parse_args();data=args.data_dir.resolve();game=args.game_dir.resolve();commands=[]
    if data.is_relative_to(game) or data.is_relative_to(BASE):raise ValueError('Derived data must be outside game and tool source directories')
    logs=data/'logs';logs.mkdir(parents=True,exist_ok=True)
    def run(command,label):
        command=[str(x) for x in command]
        if command[0] in [str(TOOL),str(EXTRACT)]:command+=['--game-dir',str(game)]
        commands.append(command);r=subprocess.run(command,capture_output=True,encoding='utf-8',errors='replace')
        (logs/(label+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
        if r.returncode:raise RuntimeError(f'{label} failed; see {logs/(label+".log")}')
        return r.stdout
    paths=[f'/parts/{piece}_m_{model}.partsbnd.dcx' for model in [1280,1010,1500,1600] for piece in ['hd','bd','am','lg']]
    print('Extracting 16 armor parts, material and shader binders',flush=True)
    run([EXTRACT,'get',*paths,'/material/allmaterial.matbinbnd.dcx','/shader/shaderbdle.shaderbdlebnd.dcx','--out',data/'inputs'],'extract_material_evidence')
    material=data/'inputs/material/allmaterial.matbinbnd.dcx';evidence=data/'material_evidence'
    print(run([TOOL,'armor-evidence','--template-dir',data/'inputs/parts','--models','1280,1010,1500,1600','--matbin-bnd',material,'--out',evidence],'material_evidence').strip(),flush=True)
    shader=data/'inputs/shader/shaderbdle.shaderbdlebnd.dcx'
    run([TOOL,'bnd',shader,'--out',data/'shaderbdle_inventory.json'],'shaderbdle_inventory')
    root=data/'shaders/detailblend'
    run([TOOL,'unpack-bnd',shader,'--filter',r'C[DetailBlend]\C[DetailBlend].shaderbdle','--out',root],'extract_detailblend')
    detail=next(p for p in root.rglob('*.shaderbdle') if p.name=='C[DetailBlend].shaderbdle')
    compiled=data/'shaders/detailblend_compiled'
    run([TOOL,'bnd',detail,'--out',data/'detailblend_inventory.json'],'detailblend_inventory')
    run([TOOL,'unpack-bnd',detail,'--out',compiled],'detailblend_compiled')
    names=['C[DetailBlend]_0_Gbuf.ppo','C[DetailBlend]_6_Gbuf.ppo','C[DetailBlend]_13_Gbuf.ppo','C[DetailBlend]_13_Fwd.ppo','C[DetailBlend]_13_Gbuf_[A].ppo']
    print(run([sys.executable,BASE/'scripts/disassemble_shader.py',*[compiled/n for n in names],'--dxc',args.dxc,'--out',evidence/'shader_asm'],'disassemble_detailblend').strip(),flush=True)
    reference=evidence/'mesh_reference';decoded=evidence/'decoded';decoded.mkdir(exist_ok=True)
    run([TOOL,'export-mesh',data/'inputs/parts/bd_m_1280.partsbnd.dcx','--matbin-bnd',material,'--out',reference],'material_reference_export')
    run([args.texconv,'-nologo','-y','-f','R8G8B8A8_UNORM','-m','1','-o',decoded,reference/'BD_M_1280_m.dds'],'decode_metallic')
    pixels=(decoded/'BD_M_1280_m.dds').read_bytes();offset=148 if pixels[84:88]==b'DX10' else 128
    height,width=struct.unpack_from('<II',pixels,12);raw=pixels[offset:offset+width*height*4]
    channels={c:dict(min=min(raw[i::4]),max=max(raw[i::4]),unique_count=len(set(raw[i::4]))) for i,c in enumerate('RGBA')}
    assert raw[0::4]==raw[1::4]==raw[2::4] and set(raw[3::4])=={255}
    (decoded/'channels.json').write_text(json.dumps(dict(source=str(reference/'BD_M_1280_m.dds'),conversion='texconv -f R8G8B8A8_UNORM -m 1',width=width,height=height,channels=channels,rgb_is_grayscale_copy=True),indent=2)+'\n',encoding='utf-8')
    source=[dict(path=str(p),size=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in [material,shader,detail]]
    (evidence/'provenance.json').write_text(json.dumps(dict(sources=source,commands=commands),indent=2)+'\n',encoding='utf-8')
    print('Complete:',evidence,flush=True)
if __name__=='__main__':main()
