"""T022 full 998: retain AM/LG bytes, extend BD/HD, materials and previews."""
import argparse
import shutil
import sys
import time
from pathlib import Path
sys.dont_write_bytecode=True
from common import PARTS,MODELS,TOOL,EXTRACT,run,read,save
from mesh_weapons import wc,make_textures,convert
from template_weapons import prepare_templates
from material_bundle import helper,merge
from bake_weapons import generate
DEFAULT_MATBIN=wc.BASE_MODEL/'package/material/allmaterial.matbinbnd.dcx'


def build(out=None,matbin_bnd=DEFAULT_MATBIN,pack=None):
 out=wc.checked(out or wc.MODEL_ROOT,wc.MODEL_ROOT);start=time.monotonic();source=Path(matbin_bnd).resolve()
 for p in (source,TOOL,EXTRACT,wc.BASE_PACK):
  if not p.is_file():raise FileNotFoundError(p)
 generated,tables,audit,carriers=generate();inputpack=out/'inputs/fuse_pov.anim';inputpack.parent.mkdir(parents=True,exist_ok=True);wc.write_pack(inputpack,generated)
 for p in [Path(pack)] if pack is not None else []:wc.require(inputpack.read_bytes()==p.read_bytes(),'Explicit pack differs from sources')
 canonical=wc.PACK_ROOT/'fuse_pov.anim'
 if canonical.is_file():wc.require(inputpack.read_bytes()==canonical.read_bytes(),'Canonical pack differs from sources')
 for key,filename in (('cr','defender_sequences.json'),('frag','frag_sequences.json')):save(out/'inputs'/filename,tables[key])
 save(out/'inputs/weapons-pack-audit.json',audit);save(out/'inputs/weapons_carriers.json',carriers)
 make_textures(out);summary=convert(out)
 # Claude rework 2026-10-06: the battery's energy core and window blue (battery_tint.py)
 from battery_tint import tint;save(out/'battery-tint.json',tint(out/'fusemesh/hd/textures'))
 prepare_templates(out)
 snapshot=out/'inputs/material/allmaterial.matbinbnd.dcx';snapshot.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,snapshot);wc.require(snapshot.read_bytes()==source.read_bytes(),'Material snapshot changed')
 save(out/'inputs/source-material.json',dict(source=str(source),size=source.stat().st_size))
 names=[f'P[{part.upper()}_M_0998]_'+m['name'] for part in ('bd','hd') for m in read(out/f'fusemesh/{part}/mesh.json')['materials']]
 targets=out/'inputs/material-targets.json';save(targets,names);staged=snapshot.with_name('build-input.matbinbnd.dcx');helper(out,'prepare',snapshot,staged,targets)
 command=[TOOL,'build-armor','--model','998','--matbin-bnd',staged,'--out',out/'package']
 for part in PARTS:
  template=out/'inputs/live-templates/hd_m_1280.partsbnd.dcx' if part=='hd' else wc.ac.BASE_MODEL/f'inputs/parts/{part}_m_{MODELS[part]:04d}.partsbnd.dcx'
  # T021 LG used the corrected T020 template; its final bytes are copied below.
  if part=='lg':template=wc.bc.BASE_MODEL/'inputs/live-templates/lg_m_1280.partsbnd.dcx'
  command += [f'--{part}-template',template]
  if part in ('bd','hd'):command += [f'--{part}-mesh',out/f'fusemesh/{part}']
 run(command,out,'build_weapons_package');merge(out,snapshot)
 for part in ('am','lg'):
  for lod in ('','_l'):
   name=f'{part}_m_0998{lod}.partsbnd.dcx';shutil.copyfile(wc.BASE_MODEL/'package/parts'/name,out/'package/parts'/name)
 manifest=read(out/'package/build-manifest.json');base=read(wc.BASE_MODEL/'package/build-manifest.json')
 manifest.update(task='T022',base_package=str(wc.BASE_MODEL/'package'),animation_pack=str(inputpack),preserved_parts=['am','am_l','lg','lg_l'],parts=[p for p in manifest['parts'] if p['piece'] in ('bd','hd')]+[dict(p,copied_byte_identical=True) for p in base['parts'] if p['piece'] in ('am','lg')])
 manifest['meshes']=base['meshes']+len(summary['meshes']);manifest['vertices']=base['vertices']+sum(m['vertices'] for m in summary['meshes']);manifest['materials']=base['materials']+4
 manifest['textures']=[t for t in base['textures'] if not t['name'].startswith(('BD_M_0998_','HD_M_0998_'))]+manifest['textures'];save(out/'package/build-manifest.json',manifest)
 sys.path.insert(0,str(Path(__file__).resolve().parent));from verify_weapons import verify,verify_preview
 report=verify(out,check_preview=False)
 from preview_weapons import make_previews
 make_previews(out,inputpack);report['previews']=verify_preview(out);report['elapsed_seconds']=round(time.monotonic()-start,2);save(out/'weapons-verification.json',report)
 print(f'PASS T022 build: full 998; AM/LG four files byte-identical; 14 previews; {report["elapsed_seconds"]}s',flush=True);return report


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path);p.add_argument('--matbin-bnd',type=Path,default=DEFAULT_MATBIN);p.add_argument('--pack',type=Path);a=p.parse_args();build(a.out,a.matbin_bnd,a.pack)
