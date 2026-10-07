"""Local paths, bounded output, process logs and the builder's float32 quantization."""
import os
import subprocess
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT/'er-data/s3/octane'
MATBIN_DEFAULT = ROOT/'scratch/mod/package/material/allmaterial.matbinbnd.dcx'
TOOL = ROOT/'tools/erdata/ertool/bin/Release/net8.0/ertool.exe'
EXTRACT = ROOT/'tools/erdata/erextract/target/x86_64-pc-windows-msvc/release/erextract.exe'
TEXCONV = ROOT/'tools/bin/texconv/texconv.exe'


def output_path(path):
    path = Path(path).resolve()
    if not path.is_relative_to(DEFAULT.resolve()):
        raise ValueError('Output must stay inside exclusive er-data/s3/octane')
    return path


def run(command, out, label, quiet=False):
    out = output_path(out); logs = out/'logs'; logs.mkdir(parents=True,exist_ok=True)
    command = list(map(str,command))
    env = os.environ.copy()
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['DOTNET_CLI_HOME'] = str(Path.home()/'.dotnet')
    env['DOTNET_CLI_TELEMETRY_OPTOUT'] = '1'
    result = subprocess.run(command,capture_output=True,encoding='utf-8',errors='replace',env=env,cwd=out)
    (logs/(label+'.log')).write_text('COMMAND '+repr(command)+'\n'+result.stdout+result.stderr,encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'{label}: exit {result.returncode}; {logs/(label+".log")}\n{result.stdout[-1000:]}{result.stderr[-2000:]}')
    if not quiet and result.stdout.strip(): print(result.stdout.strip()[-1200:],flush=True)
    return result.stdout


def quantize(weights):
    weights = np.asarray(weights,dtype=np.float32)
    total = np.zeros(len(weights),dtype=np.float32)
    for k in range(4): total += weights[:,k]
    scaled = (weights/total[:,None])*np.float32(255)
    ints = np.floor(scaled).astype(int)
    rank = np.argsort(-(scaled-ints),axis=1,kind='stable')
    for i,left in enumerate(255-ints.sum(1)):
        if not 0 <= left <= 4: raise ValueError('Invalid weight quantization')
        ints[i,rank[i,:left]] += 1
    return ints


def ensure_helper(out):
    out = output_path(out)
    binary = out/'helper/bin/MaterialBundle.dll'
    project = ROOT/'tools/octanemesh/bundle/MaterialBundle.csproj'
    sources = list(project.parent.glob('*'))
    if not binary.exists() or any(p.stat().st_mtime > binary.stat().st_mtime for p in sources if p.is_file()):
        run(['dotnet','build',project,'-c','Release',
             '-p:BaseIntermediateOutputPath='+str(out/'helper/obj')+os.sep,
             '-p:OutputPath='+str(binary.parent)+os.sep,
             '-p:NuGetAudit=false','--ignore-failed-sources'],out,'build_material_helper')
    return ['dotnet',binary]
