"""Stage colliding MATBINs and merge generated entries into the unmodified snapshot."""
from pathlib import Path
from common import ROOT, run, read, save

PROJECT = Path(__file__).with_name('material_bundle') / 'MaterialBundle.csproj'


def helper(out, *args):
    cache = out/'inputs/material-adapter'
    assembly = cache/'bin/MaterialBundle.dll'
    sources = [PROJECT, PROJECT.with_name('Program.cs')]
    if not assembly.is_file() or any(p.stat().st_mtime > assembly.stat().st_mtime for p in sources):
        run(['dotnet', 'build', PROJECT, '-c', 'Release', '--ignore-failed-sources', '--nologo',
             '--output', cache/'bin', '/p:BaseIntermediateOutputPath='+str(cache/'obj')+'/',
             '/p:MSBuildProjectExtensionsPath='+str(cache/'obj')+'/',
             '/p:UseSharedCompilation=false', '/nodeReuse:false'], out, 'build_material_adapter')
    return run(['dotnet', assembly, *args], out, 'material_' + str(args[0]))


def target_list(out):
    names = [f'P[{part.upper()}_M_0998]_' + m['name']
             for part in ('bd', 'am') for m in read(out/'fusemesh'/part/'mesh.json')['materials']]
    path = out/'inputs/material-targets.json'
    save(path, names)
    return path


def prepare(out, snapshot):
    staged = snapshot.with_name('build-input.matbinbnd.dcx')
    helper(out, 'prepare', snapshot, staged, target_list(out))
    return staged


def merge(out, snapshot):
    target = out/'package/material/allmaterial.matbinbnd.dcx'
    generated = target.with_name('generated.matbinbnd.dcx')
    target.replace(generated)
    helper(out, 'merge', snapshot, generated, out/'inputs/material-targets.json', target, out/'material-bundle-audit.json')
    generated.unlink()


def verify_material(out, snapshot):
    helper(out, 'verify', snapshot, out/'package/material/allmaterial.matbinbnd.dcx',
           out/'inputs/material-targets.json', out/'material-bundle-verification.json')
    return read(out/'material-bundle-verification.json')
