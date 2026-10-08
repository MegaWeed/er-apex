"""Wingman full 998: T022's package with the pistol appended to BD; AM/HD/LG bytes kept."""
import argparse
import shutil
import sys
import time
from pathlib import Path
sys.dont_write_bytecode=True
from common import PARTS,MODELS,TOOL,EXTRACT,run,read,save
from mesh_wingman import wm,convert,PART
from material_bundle import helper,merge
sys.path.insert(1,str(Path(__file__).resolve().parents[1]/'apexpov'))
from bake_wingman import generate
DEFAULT_MATBIN=wm.BASE_MODEL/'package/material/allmaterial.matbinbnd.dcx'
KEPT=('am','hd','lg')


def build(out=None,matbin_bnd=DEFAULT_MATBIN):
 out=wm.checked(out or wm.MODEL_ROOT,wm.MODEL_ROOT);start=time.monotonic();source=Path(matbin_bnd).resolve()
 for p in (source,TOOL,EXTRACT,wm.BASE_PACK):
  if not p.is_file():raise FileNotFoundError(p)
 canonical=wm.PACK_ROOT/'fuse_pov.anim'
 if not canonical.is_file():raise FileNotFoundError(f'{canonical}: run tools/apexpov/bake_wingman.py first')
 summary=convert(out)
 snapshot=out/'inputs/material/allmaterial.matbinbnd.dcx';snapshot.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,snapshot);wm.require(snapshot.read_bytes()==source.read_bytes(),'Material snapshot changed')
 save(out/'inputs/source-material.json',dict(source=str(source),size=source.stat().st_size))
 names=[f'P[{PART.upper()}_M_0998]_'+m['name'] for m in read(out/f'fusemesh/{PART}/mesh.json')['materials']]
 targets=out/'inputs/material-targets.json';save(targets,names);staged=snapshot.with_name('build-input.matbinbnd.dcx');helper(out,'prepare',snapshot,staged,targets)
 command=[TOOL,'build-armor','--model','998','--matbin-bnd',staged,'--out',out/'package']
 for part in PARTS:
  template=wm.ac.BASE_MODEL/f'inputs/parts/{part}_m_{MODELS[part]:04d}.partsbnd.dcx'
  if part=='hd':template=wm.BASE_MODEL/'inputs/live-templates/hd_m_1280.partsbnd.dcx'
  if part=='lg':template=wm.wc.bc.BASE_MODEL/'inputs/live-templates/lg_m_1280.partsbnd.dcx'
  command += [f'--{part}-template',template]
  if part==PART:command += [f'--{part}-mesh',out/f'fusemesh/{part}']
 run(command,out,'build_wingman_package');merge(out,snapshot)
 # the other parts exactly as T022 built them
 for part in KEPT:
  for lod in ('','_l'):
   name=f'{part}_m_0998{lod}.partsbnd.dcx';shutil.copyfile(wm.BASE_MODEL/'package/parts'/name,out/'package/parts'/name)
 manifest=read(out/'package/build-manifest.json');base=read(wm.BASE_MODEL/'package/build-manifest.json')
 manifest.update(task='wingman',base_package=str(wm.BASE_MODEL/'package'),animation_pack=str(canonical),preserved_parts=[p+l for p in KEPT for l in ('','_l')],parts=[p for p in manifest['parts'] if p['piece']==PART]+[dict(p,copied_byte_identical=True) for p in base['parts'] if p['piece'] in KEPT])
 manifest['meshes']=base['meshes']+len(summary['meshes']);manifest['vertices']=base['vertices']+sum(m['vertices'] for m in summary['meshes'])
 manifest['textures']=[t for t in base['textures'] if not t['name'].startswith(f'{PART.upper()}_M_0998_')]+manifest['textures'];save(out/'package/build-manifest.json',manifest)
 report=verify(out);report['elapsed_seconds']=round(time.monotonic()-start,2);save(out/'wingman-verification.json',report)
 print(f'PASS wingman build: full 998; {PART.upper()} + pistol; {", ".join(p.upper() for p in KEPT)} byte-identical; {report["elapsed_seconds"]}s',flush=True);return report


def verify(out):
 """Read the new BD back: its meshes, the pistol's carriers in its skeleton, its materials in the bundle."""
 from verify_fuse import read_json_command
 rb=out/'readback/export_bd';rb.mkdir(parents=True,exist_ok=True)
 run([EXTRACT,'unpack',out/'package/parts/bd_m_0998.partsbnd.dcx','--out',rb/'unpacked'],out,'wingman_unpack_bd')
 flver=next((rb/'unpacked').rglob('*.flver'));dump=read_json_command(run,[TOOL,'flver',flver,'--samples','0'],out,'wingman_flver_bd');save(rb/'flver.json',dump)
 nodes=[n['Name'] for n in dump['Nodes']];doc=read(out/f'fusemesh/{PART}/mesh.json')
 wm.require(len(dump['Meshes'])==len(doc['submeshes']),f'BD mesh count {len(dump["Meshes"])} != {len(doc["submeshes"])}')
 wm.require(all(c in nodes for c in wm.CARRIERS),'Pistol carrier missing from BD nodes')
 for part in KEPT:
  for lod in ('','_l'):
   name=f'{part}_m_0998{lod}.partsbnd.dcx';wm.require((out/'package/parts'/name).read_bytes()==(wm.BASE_MODEL/'package/parts'/name).read_bytes(),f'{name} changed')
 return dict(status='PASS',bd_meshes=len(dump['Meshes']),bd_nodes=len(nodes),carriers=list(wm.CARRIERS))


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path);p.add_argument('--matbin-bnd',type=Path,default=DEFAULT_MATBIN);a=p.parse_args();build(a.out,a.matbin_bnd)
