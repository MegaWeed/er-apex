"""M0-FP: export Apex's first-person R-301 view model, its ptpov animations and the QC/SMD
metadata of the view model and Fuse's first-person arms (D-017).

Run from the repository root: python tools/apexpov/export_pov.py
Uses T001's RSX adapter (tools/apexassets, built by build_rsx.py). Game files are read only;
outputs go to apex-data/pov/ (not in git).

  cast/   r301_base_v (LOD0..), its skin-0 materials and textures; ptpov_rspn101 rig with every
          sequence the rig lists (Cast)
  smd/    QC + SMD of r301_base_v, pov_pilot_medium_fuse and ptpov_rspn101 (bones, attachments,
          sequences, events)
  lists/  RSX export lists and dependency tables
"""
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gamedirs  # noqa: E402  (tools/gamedirs.py: the games' install folders)
import time

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'tools/apexassets'))
from build_rsx import ensure_tool  # noqa: E402

OUT = REPO / 'apex-data/pov'
GAME = gamedirs.apex()
PAKS = GAME / 'paks/Win64'
PACKAGES = ['common.rpak', 'common_mp.rpak', 'common_early.rpak',
            'root_lgnd_skins_humans_class_medium_pilot_medium_fuse.rpak',
            'root_lgnd_skins_humans_class_medium_pilot_medium_fuse_shdrs.rpak']
# From R-301's weapon settings (apex-data/fuse_data.json: viewmodel) and the asset list
# (apex-data/assets/lists/core_named.adjlist: r301_base_v -> ptpov_rspn101.rrig)
VIEW_MODEL = 'r301_base_v.rmdl'
ARMS_MODEL = 'pov_pilot_medium_fuse.rmdl'
RIG = 'ptpov_rspn101.rrig'
RUNS = []


def run(exe, name, destination, types, filter_text, flags=()):
    cache = OUT / 'logs/rsx_runtime'
    cache.mkdir(parents=True, exist_ok=True)
    (OUT / 'lists').mkdir(exist_ok=True)
    command = [str(exe), '-nogui', '-export', '--loadwhitelist', 'x',
               '--exportthreads', '4', '--parsethreads', '8',
               '--exportdir', str(OUT / destination), '-exportfullpaths', '-nocachedb',
               '--texturenames', 'stored', '--nmlrecalc', 'none',
               '--list', str(OUT / f'lists/{name}.csv'), '--listformat', 'csv',
               '--depfilepath', str(OUT / f'lists/{name}.adjlist'),
               '--exporttypes', types, '--exportfilter', filter_text, *flags,
               *[str(PAKS / n) for n in PACKAGES]]
    print(f'{name}: starting', flush=True)
    started = time.perf_counter()
    with (OUT / f'logs/{name}.log').open('wb') as log:
        result = subprocess.run(command, cwd=cache, stdout=log, stderr=subprocess.STDOUT)
    RUNS.append({'name': name, 'command': command, 'seconds': time.perf_counter() - started,
                 'exit_code': result.returncode})
    (OUT / 'run_manifest.json').write_text(json.dumps({'runs': RUNS}, indent=2), encoding='utf8')
    if result.returncode:
        raise RuntimeError(f'{name}: RSX exited {result.returncode}; see logs/{name}.log')
    print(f'{name}: {RUNS[-1]["seconds"]:.1f} s', flush=True)


def main():
    for n in PACKAGES:
        if not (PAKS / n).exists():
            raise FileNotFoundError(PAKS / n)
    (OUT / 'logs').mkdir(parents=True, exist_ok=True)
    exe = ensure_tool()
    run(exe, 'view_model_cast', 'cast', 'mdl_', VIEW_MODEL, ['-matltextures', '--format-matl', '2'])
    run(exe, 'ptpov_rig_cast', 'cast', 'arig', RIG, ['-exportrigsequences'])
    # The raw RSEQ of the rig's sequences (T012: bake_pov restores the identity additive curves RSX
    # leaves out of the Cast from their metadata; t012_raw_metadata_export.json had this by hand)
    run(exe, 'ptpov_rig_raw', 'raw', 'arig', RIG, ['--format-arig', '2', '--format-aseq', '2', '-exportrigsequences'])
    run(exe, 'smd_qc', 'smd', 'mdl_,arig', f'{VIEW_MODEL},{ARMS_MODEL},{RIG}',
        ['--format-mdl_', '3', '--format-arig', '3', '--format-aseq', '3'])
    files = [p for p in OUT.rglob('*') if p.is_file() and 'logs' not in p.parts]
    print(json.dumps({'files': len(files), 'casts': sum(p.suffix == '.cast' for p in files),
                      'qc': [str(p.relative_to(OUT)) for p in files if p.suffix == '.qc']}, indent=2))


if __name__ == '__main__':
    main()
