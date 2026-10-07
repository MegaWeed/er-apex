"""U3: export the Charge Rifle's first-person view model and its animation rig from the local
Apex install, as QC + SMD (bones, attachments, sequences and their events), for the mod's
charge rifle (src/spike/chargerifle.rs: draw / holster / reload event frames and sounds)
and for a later view model (U3 stage 2).

Which assets: S3's weapon settings name the view model `mdl/weapons/defender/ptpov_defender.rmdl`
(R5Reloaded `platform/scripts/weapons/mp_weapon_defender.txt`); the local retail build ships the
Charge Rifle as `chargerifle_base_v.rmdl` (apex-data/export/weapon/mp_weapon_defender.txt:
viewmodel), whose rig `chargerifle_base_v_animRig.rrig` lists the `ptpov_defender` sequences
(apex-data/assets/lists/core_named.adjlist). Animations and event frames are taken from the local
build (D-021: animation data from the local retail files, rules from S3).

Run from the repository root:
  python tools/apexpov/export_defender_pov.py [--rsx <rsx.exe>] [--out <dir>] [--cast]

  --rsx   T001's RSX build (default: tools/apexassets' ensure_tool, which may build it)
  --out   output directory (default apex-data/weapons/defender/pov; not in git)
  --cast  also export the view model mesh and every rig sequence as Cast (stage 2)

Game files are read only. No game launch, no network, no git commands, no hashing.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gamedirs  # noqa: E402  (tools/gamedirs.py: the games' install folders)
import time

REPO = Path(__file__).resolve().parents[2]
GAME = gamedirs.apex()
PAKS = GAME / 'paks/Win64'
PACKAGES = ['common.rpak', 'common_mp.rpak', 'common_early.rpak']
VIEW_MODEL = 'chargerifle_base_v.rmdl'
RIG = 'chargerifle_base_v_animRig.rrig'


def run(exe, out, name, destination, types, filter_text, flags, runs):
    cache = out / 'logs/rsx_runtime'
    cache.mkdir(parents=True, exist_ok=True)
    (out / 'lists').mkdir(exist_ok=True)
    command = [str(exe), '-nogui', '-export', '--loadwhitelist', 'x',
               '--exportthreads', '4', '--parsethreads', '8',
               '--exportdir', str(out / destination), '-exportfullpaths', '-nocachedb',
               '--texturenames', 'stored', '--nmlrecalc', 'none',
               '--list', str(out / f'lists/{name}.csv'), '--listformat', 'csv',
               '--depfilepath', str(out / f'lists/{name}.adjlist'),
               '--exporttypes', types, '--exportfilter', filter_text, *flags,
               *[str(PAKS / n) for n in PACKAGES]]
    print(f'{name}: starting', flush=True)
    started = time.perf_counter()
    with (out / f'logs/{name}.log').open('wb') as log:
        result = subprocess.run(command, cwd=cache, stdout=log, stderr=subprocess.STDOUT)
    runs.append({'name': name, 'command': command, 'seconds': round(time.perf_counter() - started, 3),
                 'exit_code': result.returncode})
    (out / 'run_manifest.json').write_text(json.dumps({'runs': runs}, indent=2), encoding='utf8')
    if result.returncode:
        raise RuntimeError(f'{name}: RSX exited {result.returncode}; see logs/{name}.log')
    print(f'{name}: {runs[-1]["seconds"]:.1f} s', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--rsx', type=Path, help="RSX executable (default: tools/apexassets' ensure_tool)")
    parser.add_argument('--out', type=Path, default=REPO / 'apex-data/weapons/defender/pov')
    parser.add_argument('--cast', action='store_true', help='also export the mesh and the rig sequences as Cast')
    args = parser.parse_args()
    for n in PACKAGES:
        if not (PAKS / n).exists():
            raise FileNotFoundError(PAKS / n)
    if args.rsx is not None:
        exe = args.rsx
    else:
        sys.path.insert(0, str(REPO / 'tools/apexassets'))
        from build_rsx import ensure_tool  # noqa: E402
        exe = ensure_tool()
    if not Path(exe).is_file():
        raise FileNotFoundError(exe)
    out = args.out.resolve()
    (out / 'logs').mkdir(parents=True, exist_ok=True)
    runs = []
    run(exe, out, 'smd_qc', 'smd', 'mdl_,arig', f'{VIEW_MODEL},{RIG}',
        ['--format-mdl_', '3', '--format-arig', '3', '--format-aseq', '3'], runs)
    if args.cast:
        run(exe, out, 'view_model_cast', 'cast', 'mdl_', VIEW_MODEL, ['-matltextures', '--format-matl', '2'], runs)
        run(exe, out, 'rig_cast', 'cast', 'arig', RIG, ['-exportrigsequences'], runs)
    files = [p for p in out.rglob('*') if p.is_file() and 'logs' not in p.parts]
    print(json.dumps({'files': len(files), 'qc': [p.relative_to(out).as_posix() for p in files if p.suffix == '.qc']}, indent=2))


if __name__ == '__main__':
    main()
