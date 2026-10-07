"""Read-only T005/T015 inputs; every output is bounded by T019's exclusive root."""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'er-data/s3/octane_gun'
BASE = ROOT / 'er-data/s3/fuse'
FUSE_REFERENCE = ROOT / 'er-data/s3/fuse_gun'
ASSETS = ROOT / 'apex-data/assets'
MATBIN_DEFAULT = ROOT / 'er-data/s3/octane_pov/package/material/allmaterial.matbinbnd.dcx'
sys.path.insert(0, str(ROOT / 'tools/fusemesh'))
sys.path.append(str(ROOT / 'tools/fuseanim'))
sys.path.append(str(ROOT / 'tools/erdata/scripts'))
from geometry import read, save, unit, trs, world, PARTS, MODELS
from convert_fuse import TOOL, EXTRACT


def base_for(legend):
    if legend not in ('fuse', 'octane'):
        raise ValueError('Unknown legend: ' + legend)
    return ROOT / ('er-data/s3/' + legend)


def default_out(legend):
    return OUT if legend == 'octane' else OUT / 'fuse_check'


def add_options(parser, *, material=False):
    parser.add_argument('--legend', choices=('fuse', 'octane'), default='fuse')
    parser.add_argument('--out', type=Path, help='Output inside er-data/s3/octane_gun')
    if material:
        parser.add_argument('--matbin-bnd', type=Path,
                            help='Octane: current 999/998 bundle; Fuse: original T005 input bundle')


def checked_out(path):
    path = Path(path).resolve()
    if not path.is_relative_to(OUT.resolve()):
        raise ValueError('Output must stay inside exclusive er-data/s3/octane_gun')
    path.mkdir(parents=True, exist_ok=True)
    return path


def run(command, out, label):
    out = checked_out(out)
    logs = out / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    command = list(map(str, command))
    env = os.environ.copy()
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['DOTNET_CLI_HOME'] = str(Path.home() / '.dotnet')
    env['DOTNET_CLI_TELEMETRY_OPTOUT'] = '1'
    env['NUGET_PACKAGES'] = str(Path.home() / '.nuget/packages')
    env['NUGET_HTTP_CACHE_PATH'] = str(out / 'helper/nuget_http')
    result = subprocess.run(command, capture_output=True, encoding='utf-8',
                            errors='replace', env=env, cwd=out)
    (logs / (label + '.log')).write_text(
        'COMMAND ' + repr(command) + '\n' + result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'{label}: exit {result.returncode}; {logs / (label + ".log")}\n'
                           + result.stdout[-1000:] + result.stderr[-2000:])
    if result.stdout.strip():
        print(result.stdout.strip()[-1200:], flush=True)
    return result.stdout


def alignment_for(legend):
    if legend == 'fuse':
        from geometry import alignment
    else:
        # Isolate the identically named Octane module without changing T005 imports.
        spec = importlib.util.spec_from_file_location(
            't019_octane_geometry', ROOT / 'tools/octanemesh/geometry.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        alignment = module.alignment
    state = alignment(ROOT)
    import numpy as np
    saved = read(base_for(legend) / 'align.json')
    assert np.array_equal(state[7], saved['scaled_axis_unit_matrix'])
    assert np.array_equal(state[5], saved['apex_aligned_world'])
    return state


def source_info(paths, out):
    result = []
    for path in dict.fromkeys(map(Path, paths)):
        if path.is_relative_to(out):
            name = '$OUTPUT/' + path.relative_to(out).as_posix()
        elif path.is_relative_to(ROOT):
            name = path.relative_to(ROOT).as_posix()
        else:
            name = str(path)
        result.append(dict(path=name, size_bytes=path.stat().st_size,
                           format=path.suffix.lstrip('.')))
    return result


def quantize(weights):
    """Use build-armor's float32 normalization and stable remainder distribution."""
    import numpy as np
    weights = np.asarray(weights, dtype=np.float32)
    total = np.zeros(len(weights), dtype=np.float32)
    for k in range(4):
        total += weights[:, k]
    scaled = (weights / total[:, None]) * np.float32(255)
    ints = np.floor(scaled).astype(int)
    rank = np.argsort(-(scaled - ints), axis=1, kind='stable')
    for i, left in enumerate(255 - ints.sum(1)):
        if not 0 <= left <= 4:
            raise ValueError('Invalid weight quantization')
        ints[i, rank[i, :left]] += 1
    return ints


def ensure_helper(out):
    out = checked_out(out)
    binary = out / 'helper/bin/MaterialBundle.dll'
    project = ROOT / 'tools/fusegun/bundle/MaterialBundle.csproj'
    sources = [p for p in project.parent.iterdir() if p.is_file()]
    if not binary.exists() or any(p.stat().st_mtime > binary.stat().st_mtime for p in sources):
        run(['dotnet', 'build', project, '-c', 'Release',
             '-p:BaseIntermediateOutputPath=' + str(out / 'helper/obj') + os.sep,
             '-p:OutputPath=' + str(binary.parent) + os.sep,
             '-p:UseSharedCompilation=false',
             '-p:NuGetAudit=false', '--ignore-failed-sources'], out, 'build_material_helper')
    return ['dotnet', binary]
