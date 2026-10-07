"""Reproducible local Apex assets: Fuse (T001) and default Octane (T014).

Run: python tools/apexassets/export_assets.py
Requires Python 3.13, numpy, Pillow, matplotlib; Visual Studio C++ to rebuild
the additive RSX adapter on a cold tools directory (see build_rsx.py).
All game inputs are read-only. RSX caches and logs follow the output directory.
"""
import argparse
import csv
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gamedirs  # noqa: E402  (tools/gamedirs.py: the games' install folders)
import subprocess
import struct
import time
import numpy as np

from build_rsx import ensure_tool
from audio_inventory import build_audio_inventory

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
DEFAULT_OUT = REPO / 'apex-data/assets'
OUT = DEFAULT_OUT
GAME = gamedirs.apex()
PAKS = GAME / 'paks/Win64'
CACHE = OUT / 'logs/rsx_runtime'
PACKAGES = [
    'common.rpak', 'common_mp.rpak', 'common_early.rpak',
    'root_lgnd_skins_humans_class_medium_pilot_medium_fuse.rpak',
    'root_lgnd_skins_humans_class_medium_pilot_medium_fuse_shdrs.rpak',
]
# Exclusions MUST come first: RSX TextFilter returns on the first match.
MODEL_FILTER = '-pov_,pilot_medium_fuse.rmdl,r301_base_w.rmdl'
ARMS_FILTER = 'pov_pilot_medium_fuse.rmdl'
RIG_FILTER = '-pov_,pilot_medium_fuse.rrig,mp_pilot_medium_core.rrig'
TARGET_FILTER = '-pov_,pilot_medium_fuse.rmdl,r301_base_w.rmdl,pilot_medium_fuse.rrig,mp_pilot_medium_core.rrig'
RUNS = []


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def run(exe, name, destination, types=None, filter_text=None, flags=(), files=None):
    CACHE.mkdir(parents=True, exist_ok=True)
    command = [str(exe), '-nogui', '-export', '--loadwhitelist', 'x',
               '--exportthreads', '4', '--parsethreads', '8',
               '--exportdir', str(OUT / destination), '-exportfullpaths', '-nocachedb',
               '--texturenames', 'stored', '--nmlrecalc', 'none',
               '--list', str(OUT / f'lists/{name}.csv'), '--listformat', 'csv',
               '--depfilepath', str(OUT / f'lists/{name}.adjlist')]
    if types:
        command += ['--exporttypes', types]
    if filter_text:
        command += ['--exportfilter', filter_text]
    command += list(flags)
    command += [str(path) for path in (files or [PAKS / n for n in PACKAGES])]
    print(f'{name}: starting', flush=True)
    started = time.perf_counter()
    # RSX reconnects stdout to its parent console on Windows; the CSV and
    # artifacts, rather than log text alone, are checked downstream.
    with (OUT / f'logs/{name}.log').open('wb') as log:
        result = subprocess.run(command, cwd=CACHE, stdout=log, stderr=subprocess.STDOUT)
    elapsed = time.perf_counter() - started
    RUNS.append({'name': name, 'command': command, 'cwd': str(CACHE),
                 'seconds': elapsed, 'exit_code': result.returncode})
    dump(OUT / 'run_manifest.json', {'runs': RUNS})
    if result.returncode:
        raise RuntimeError(f'{name}: RSX exited {result.returncode}; see logs/{name}.log')
    if not (OUT / f'lists/{name}.csv').exists():
        raise RuntimeError(f'{name}: missing list output')
    print(f'{name}: {elapsed:.2f}s', flush=True)


def audio_samples(exe):
    rows = list(csv.DictReader((OUT / 'lists/audio_named.csv').open(encoding='utf8')))
    # Use actual bank source names. Both language variants have the same name
    # and GUID; the adapter exports each into a separate language directory.
    voice_names = {r['asset_name'] for r in rows if r['file_name'] == 'general_english.mstr'
                   and r['asset_name'].lower().startswith('diag_mp_fuse')
                   and 'introseq' in r['asset_name'].lower() and '_l2' not in r['asset_name'].lower()}
    mandarin = {r['asset_name'] for r in rows if r['file_name'] == 'general_mandarin.mstr'}
    voice = sorted(voice_names & mandarin)[0]
    # mp_weapon_rspn101's burst_or_looping_fire_sound_start_1p is
    # Weapon_R101_FirstShot_1P; R-301 fire sounds retain R101 names in the bank.
    shots = [r for r in rows if r['file_name'] == 'general_stream.mstr'
             and r['asset_name'].lower() == 'wpn_r101_1p_wpnfire_firstshot_core_6ch_v4_01']
    if not shots:
        raise RuntimeError('No R-301 fire source name found in local bank')
    shot = sorted(shots, key=lambda row: row['asset_name'])[0]['asset_name']
    run(exe, 'audio_samples', 'samples', 'asrc', flags=[
        '--exportexact', f'{voice},{shot}', '--audiostreams',
        'general_english.mstr,general_mandarin.mstr,general_stream.mstr'],
        files=[GAME / 'audio/ship/general.mbnk'])
    samples = []
    for path in (OUT / 'samples').rglob('*.wav'):
        samples.append(read_wave(path))
    dump(OUT / 'audio_samples.json', {'source_names': [voice, shot], 'samples': samples})
    return samples


def read_wave(path, out=None):
    out = OUT if out is None else Path(out)
    data = path.read_bytes()
    if data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise ValueError(f'Invalid WAV: {path}')
    offset, fmt, payload = 12, None, None
    while offset + 8 <= len(data):
        kind, size = struct.unpack_from('<4sI', data, offset)
        start = offset + 8
        if start + size > len(data):
            raise ValueError('WAV chunk exceeds file')
        if kind == b'fmt ':
            fmt = struct.unpack_from('<HHIIHH', data, start)
        elif kind == b'data':
            payload = data[start:start + size]
        offset = start + size + (size & 1)
    if not fmt or payload is None:
        raise ValueError('Missing WAV format/data chunk')
    encoding, channels, rate, byte_rate, block_size, bits = fmt
    if encoding != 3 or bits != 32:
        raise ValueError(f'Expected RSX float32 WAV, got {encoding}/{bits}')
    samples = np.frombuffer(payload, dtype='<f4')
    if not np.isfinite(samples).all() or len(payload) % block_size or not np.any(samples):
        raise ValueError('Invalid, empty or silent decoded audio')
    frames = len(payload) // block_size
    return {'path': str(path.relative_to(out)).replace('\\', '/'), 'channels': channels,
            'sample_rate': rate, 'frames': frames, 'seconds': frames / rate,
            'encoding': 'IEEE float32', 'peak': float(np.abs(samples).max()),
            'size': len(data)}


def export_materials(exe):
    from cast import Cast, Model
    rows = {row['guid'].lower().zfill(16): row for row in csv.DictReader((OUT / 'lists/core_named.csv').open(encoding='utf8'))}
    ids = set()
    for path in (OUT / 'cast/mdl').rglob('*_LOD0.cast'):
        if path.name not in {'pilot_medium_fuse_LOD0.cast', 'r301_base_w_LOD0.cast', 'pov_pilot_medium_fuse_LOD0.cast'}:
            continue
        for root in Cast.load(str(path)).Roots():
            for model in root.ChildrenOfType(Model):
                ids.update(f'{material.Hash():016x}' for material in model.Materials())
    names = [rows[guid]['asset_name'] for guid in sorted(ids)]
    run(exe, 'materials', 'cast', 'matl', flags=[
        '--exportexact', ','.join(names), '--format-matl', '2', '-matltextures'])
    # Retain compressed original pixels as well as convenient PNG previews.
    run(exe, 'materials_dds', 'dds', 'matl', flags=[
        '--exportexact', ','.join(names), '--format-matl', '2',
        '--format-txtr', '2', '-matltextures'])


def main():
    global OUT, CACHE, PACKAGES
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legend', choices=['fuse', 'octane'], default='fuse')
    parser.add_argument('--output-dir', '--output', type=Path,
                        help='Output root; defaults to assets/ for Fuse, assets/octane/ for Octane')
    parser.add_argument('--analyze-only', action='store_true', help='Re-read existing artifacts without RSX')
    parser.add_argument('--verify', action='store_true', help='Check existing output without exporting')
    args = parser.parse_args()
    OUT = (args.output_dir or (DEFAULT_OUT / 'octane' if args.legend == 'octane' else DEFAULT_OUT)).resolve()
    CACHE = OUT / 'logs/rsx_runtime'
    os.environ['MPLCONFIGDIR'] = str(CACHE / 'matplotlib')
    if args.legend == 'octane':
        if not OUT.is_relative_to((DEFAULT_OUT / 'octane').resolve()):
            parser.error('Octane output must stay inside apex-data/assets/octane/')
        from octane_assets import export_octane, analyze_octane, verify_inventory, PACKAGES as OCTANE_PACKAGES
        PACKAGES = OCTANE_PACKAGES
        if args.verify:
            print(json.dumps(verify_inventory(OUT), ensure_ascii=False, indent=2))
        elif args.analyze_only:
            print(json.dumps(analyze_octane(OUT), ensure_ascii=False, indent=2))
        else:
            export_octane(OUT, PAKS, ensure_tool(), run, RUNS)
        return
    if args.verify:
        from verify_assets import verify
        verify(OUT)
        return
    OUT.mkdir(parents=True, exist_ok=True)
    for directory in ['lists', 'logs', 'preview']:
        (OUT / directory).mkdir(exist_ok=True)
    start = time.perf_counter()
    if not args.analyze_only:
        for name in PACKAGES:
            if not (PAKS / name).exists():
                raise FileNotFoundError(PAKS / name)
        exe = ensure_tool()
        # A separate complete, postloaded list; no asset data is exported here.
        run(exe, 'core_named', 'cast', flags=['-metadataonly'])
        run(exe, 'models_cast', 'cast', 'mdl_', MODEL_FILTER,
            ['-matltextures', '--format-matl', '2'])
        # Fuse's first-person arms: MODEL_FILTER leaves out every pov_ model, but the Octane export
        # (arms comparison), T011's model 998 and the first-person pack read this Cast
        run(exe, 'fuse_arms', 'cast', 'mdl_', ARMS_FILTER,
            ['-matltextures', '--format-matl', '2'])
        export_materials(exe)
        run(exe, 'fuse_rigs', 'cast', 'arig', RIG_FILTER, ['-exportrigsequences'])
        # Raw rig/model manifests prove the rig -> sequence and model -> rig links.
        run(exe, 'raw', 'raw', 'mdl_,arig', TARGET_FILTER,
            ['--format-mdl_', '2', '--format-arig', '2', '--format-aseq', '2', '-exportrigsequences'])
        # Existing SMD exporters generate QC carrying bodygroups, events,
        # pose parameters and layers. Sequence meshes aren't duplicated as SMD.
        run(exe, 'smd_qc', 'smd', 'mdl_,arig', TARGET_FILTER,
            ['--format-mdl_', '3', '--format-arig', '3', '--format-aseq', '3'])
        run(exe, 'odl', 'odl', 'odla', '-pov_,pilot_medium_fuse.rmdl')
        run(exe, 'audio_named', 'samples', flags=['-metadataonly'], files=[GAME / 'audio/ship/general.mbnk'])
        build_audio_inventory(GAME / 'audio/ship/general.mbnk', OUT)
        audio_samples(exe)
    from inspect_assets import analyze, refresh_inventory
    summary = analyze(OUT)
    from verify_assets import verify
    verify(OUT)
    if not args.analyze_only:
        dump(OUT / 'run_manifest.json', {'game': str(GAME), 'package_inputs': PACKAGES,
                                        'adapter': str(exe), 'runs': RUNS,
                                        'total_seconds': time.perf_counter() - start,
                                        'summary': summary})
    summary = refresh_inventory(OUT)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
