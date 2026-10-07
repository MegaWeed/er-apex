"""T021 full 998: unchanged AM/BD/LG, unchanged injector, added HD battery."""
import argparse
import shutil
import sys
import time
from pathlib import Path
sys.dont_write_bytecode = True
from common import ROOT,PARTS,MODELS,TOOL,EXTRACT,run,read,save
from mesh_battery import bc,make_textures,convert
from material_bundle import helper,merge
from bake_battery import generate

DEFAULT_MATBIN = bc.BASE_MODEL/'package/material/allmaterial.matbinbnd.dcx'


def build(out=None,matbin_bnd=DEFAULT_MATBIN,pack=None):
    out=bc.checked(out or bc.MODEL_ROOT,bc.MODEL_ROOT);start=time.monotonic();source=Path(matbin_bnd).resolve()
    for path in (source,TOOL,EXTRACT,bc.BASE_PACK):
        if not path.is_file():raise FileNotFoundError(path)
    generated,sequences,audit=generate();inputpack=out/'inputs/fuse_pov.anim';inputpack.parent.mkdir(parents=True,exist_ok=True)
    bc.write_pack(inputpack,generated)
    if pack is not None: bc.require(inputpack.read_bytes()==Path(pack).read_bytes(),'Explicit pack differs from local sources')
    canonical=bc.PACK_ROOT/'fuse_pov.anim'
    if canonical.is_file():bc.require(inputpack.read_bytes()==canonical.read_bytes(),'Canonical battery pack differs')
    save(out/'inputs/battery_sequences.json',sequences);save(out/'inputs/battery-pack-audit.json',audit)
    make_textures(out);_,summary=convert(out)
    # The two free Xtra nodes are already enabled in the corrected T020 templates.
    # Copy these templates verbatim; no face/node modifications are necessary.
    for lod in ('','_l'):
        name=f'hd_m_1280{lod}.partsbnd.dcx'
        src=bc.BASE_MODEL/'inputs/live-templates'/name;dst=out/'inputs/live-templates'/name
        dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
        for suffix in ('.json','-changes.json'):
            src=bc.BASE_MODEL/f'inputs/template-audit/hd{lod}{suffix}';dst=out/f'inputs/template-audit/hd{lod}{suffix}'
            dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
    save(out/'battery-template-audit.json',dict(status='PASS',template_source=str(bc.BASE_MODEL/'inputs/live-templates'),
         hd_template_copies_byte_identical=True,face_node_changes=[],policy='T020 enabled template bones, 20 enabled Xtra, rest; unchanged node layout and skeleton tables.'))
    snapshot=out/'inputs/material/allmaterial.matbinbnd.dcx';snapshot.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,snapshot)
    bc.require(source.read_bytes()==snapshot.read_bytes(),'Material snapshot differs')
    save(out/'inputs/source-material.json',dict(source=str(source),size=source.stat().st_size,snapshot_size=snapshot.stat().st_size))
    names=[f'P[HD_M_0998]_'+m['name'] for m in read(out/'fusemesh/hd/mesh.json')['materials']]
    targets=out/'inputs/material-targets.json';save(targets,names);staged=snapshot.with_name('build-input.matbinbnd.dcx')
    helper(out,'prepare',snapshot,staged,targets)
    command=[TOOL,'build-armor','--model','998','--matbin-bnd',staged,'--out',out/'package']
    for part in PARTS:
        template=out/'inputs/live-templates/hd_m_1280.partsbnd.dcx' if part=='hd' else bc.BASE_MODEL/f'inputs/parts/{part}_m_{MODELS[part]:04d}.partsbnd.dcx'
        command += [f'--{part}-template',template]
        if part=='hd':command += ['--hd-mesh',out/'fusemesh/hd']
    run(command,out,'build_battery_package');merge(out,snapshot)
    for part in ('am','bd','lg'):
        for lod in ('','_l'):
            name=f'{part}_m_0998{lod}.partsbnd.dcx';shutil.copyfile(bc.BASE_MODEL/'package/parts'/name,out/'package/parts'/name)
    manifest=read(out/'package/build-manifest.json');base=read(bc.BASE_MODEL/'package/build-manifest.json')
    preserved=[p for p in base['parts'] if p['piece'] in ('am','bd','lg')]
    hd=next(p for p in manifest['parts'] if p['piece']=='hd')
    manifest.update(task='T021',base_package=str(bc.BASE_MODEL/'package'),preserved_parts=['am','am_l','bd','bd_l','lg','lg_l'],
        animation_pack=str(inputpack),parts=[hd]+[dict(p,copied_byte_identical=True) for p in preserved])
    manifest['meshes']=sum(p['meshes'] for p in manifest['parts']) if all(isinstance(p.get('meshes'),int) for p in manifest['parts']) else base['meshes']+3
    manifest['materials']=base['materials']+3;manifest['vertices']=base['vertices']+sum(m['vertices'] for m in summary['meshes'])
    manifest['textures']=[t for t in base['textures'] if not t['name'].startswith('HD_M_0998_')]+manifest['textures']
    save(out/'package/build-manifest.json',manifest)
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from verify_battery import verify,verify_preview
    report=verify(out,check_preview=False)
    from preview_battery import make_previews
    make_previews(out,inputpack);report['previews']=verify_preview(out);report['elapsed_seconds']=round(time.monotonic()-start,2)
    save(out/'battery-verification.json',report)
    print(f'PASS T021 build: full 998; six AM/BD/LG files byte-identical; HD {summary["parts"]["hd"]["vertices"]} vertices / {summary["parts"]["hd"]["triangles"]} triangles; 8 previews; {report["elapsed_seconds"]}s',flush=True)
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path);parser.add_argument('--matbin-bnd',type=Path,default=DEFAULT_MATBIN)
    parser.add_argument('--pack',type=Path);args=parser.parse_args();build(args.out,args.matbin_bnd,args.pack)
