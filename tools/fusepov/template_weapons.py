"""T022 stage T021 HD templates with six enabled live face nodes."""
from pathlib import Path
from common import run,save,read,TOOL,EXTRACT
from mesh_weapons import wc
from verify_fuse import read_json_command
PROJECT=Path(__file__).with_name('weapons_templates')/'WeaponsTemplates.csproj'


def prepare_templates(out):
 cache=out/'inputs/template-adapter';dll=cache/'bin/WeaponsTemplates.dll'
 if not dll.is_file() or any(p.stat().st_mtime>dll.stat().st_mtime for p in (PROJECT,PROJECT.with_name('Program.cs'))):
  run(['dotnet','build',PROJECT,'-c','Release','--ignore-failed-sources','--nologo','--output',cache/'bin','/p:BaseIntermediateOutputPath='+str(cache/'obj')+'/', '/p:MSBuildProjectExtensionsPath='+str(cache/'obj')+'/', '/p:UseSharedCompilation=false','/nodeReuse:false'],out,'build_weapons_templates')
 records=[]
 for lod in ('','_l'):
  name=f'hd_m_1280{lod}.partsbnd.dcx';source=wc.BASE_MODEL/'inputs/live-templates'/name;target=out/'inputs/live-templates'/name;audit=out/f'inputs/template-audit/hd{lod}-changes.json';audit.parent.mkdir(parents=True,exist_ok=True)
  run(['dotnet',dll,wc.ac.LIVE_SKELETON,source,target,audit],out,'weapons_template'+lod)
  run([EXTRACT,'unpack',target,'--out',out/f'inputs/template-readback/hd{lod}'],out,'weapons_template_unpack'+lod)
  flver=next((out/f'inputs/template-readback/hd{lod}').rglob('*.flver'));dump=read_json_command(run,[TOOL,'flver',flver,'--samples','0'],out,'weapons_template_flver'+lod);save(out/f'inputs/template-audit/hd{lod}.json',dump);records.append(read(audit))
 save(out/'weapons-template-audit.json',dict(status='PASS',policy='Keep all T021 nodes; enabled T021 prefix, six live face nodes, rest. Rebuild both skeleton tables and remap references.',templates=records));return records
