"""T020 authorized local HD/LG template copies, with live Xtra reference nodes."""
from pathlib import Path
from common import ROOT, run, read, save, TOOL, EXTRACT
from mesh_ability import ac
from verify_fuse import read_json_command

PROJECT = Path(__file__).with_name('ability_templates')/'AbilityTemplates.csproj'


def prepare_templates(out):
    cache = out/'inputs/template-adapter'
    assembly = cache/'bin/AbilityTemplates.dll'
    if not assembly.is_file() or any(p.stat().st_mtime > assembly.stat().st_mtime for p in (PROJECT, PROJECT.with_name('Program.cs'))):
        run(['dotnet', 'build', PROJECT, '-c', 'Release', '--ignore-failed-sources', '--nologo',
             '--output', cache/'bin', '/p:BaseIntermediateOutputPath='+str(cache/'obj')+'/',
             '/p:MSBuildProjectExtensionsPath='+str(cache/'obj')+'/', '/p:UseSharedCompilation=false', '/nodeReuse:false'], out, 'build_template_adapter')
    audit = dict(source_live=ac.info(ac.LIVE_SKELETON), template_copies=[], policy='Remove non-live mesh/face nodes, preserve retained local transforms, append 20 enabled Xtra nodes from live reference; AM/BD never altered')
    for part in ('hd', 'lg'):
        for lod in ('', '_l'):
            name = f'{part}_m_1280{lod}.partsbnd.dcx'
            original = out/'inputs/parts'/name
            staged = out/'inputs/live-templates'/name
            record = out/f'inputs/template-audit/{part}{lod}-changes.json'
            record.parent.mkdir(parents=True, exist_ok=True)
            run(['dotnet', assembly, ac.LIVE_SKELETON, original, staged, record], out, 'stage_template_'+part+lod)
            run([EXTRACT, 'unpack', staged, '--out', out/f'inputs/template-readback/{part}{lod}'], out, 'staged_unpack_'+part+lod)
            flver = next((out/f'inputs/template-readback/{part}{lod}').rglob('*.flver'))
            dump = read_json_command(run, [TOOL, 'flver', flver, '--samples', '0'], out, 'staged_flver_'+part+lod)
            save(out/f'inputs/template-audit/{part}{lod}.json', dump)
            audit['template_copies'].append(read(record))
    save(out/'ability-template-audit.json', audit)
    return audit
