"""Locate and export the local Octane rifle idle, with RSX state in the output root."""
import argparse
import csv
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gamedirs  # noqa: E402  (tools/gamedirs.py: the games' install folders)
from common import ROOT, ASSETS, OUT, checked_out, read, save, run, source_info

LIST = ASSETS / 'octane/lists/core_named.csv'
MANIFEST = ASSETS / 'octane/raw/animrig/humans/class/medium/pilot_medium_stim.rson'
RSX = ROOT / 'tools/apexassets/rsx_source/bin/Release_NoGui/rsx.exe'
GAME = gamedirs.apex()


def export_idle(out):
    out = checked_out(out)
    with LIST.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    normal = lambda s: s.replace('\\', '/').lower()
    candidates = [r for r in rows if r['type'] == 'aseq' and
                  normal(r['asset_name']).endswith('/pilot_medium_stim/octane_idle_rifle.rseq')]
    if not candidates:
        save(out / 'sequence-source.json', dict(status='待定', candidates=[],
             list_source=str(LIST.relative_to(ROOT)), reason='No Octane rifle idle in local list'))
        return None
    if len(candidates) != 1:
        raise ValueError('Ambiguous local Octane rifle idle')
    row = candidates[0]
    manifest = MANIFEST.read_text(encoding='utf-8-sig')
    if row['asset_name'].lower() not in manifest.lower():
        raise ValueError('Selected sequence is not a dependency of the Octane body rig')
    rig = next(r for r in rows if r['type'] == 'arig' and
               normal(r['asset_name']).endswith('/medium/pilot_medium_stim.rrig'))
    folder = out / 'rsx/cast'
    # Standalone Cast export has a parsed parent rig; raw standalone ASEQ is not used.
    clip = folder / Path(row['asset_name'].replace('\\', '/')).with_suffix('')
    clip = clip.with_name(clip.name + '_0.cast')
    runtime = checked_out(out / 'rsx/runtime')
    listings = out / 'rsx/lists'
    listings.mkdir(parents=True, exist_ok=True)
    packages = [GAME / 'paks/Win64' / name for name in read(ASSETS / 'octane/run_manifest.json')['package_inputs']]
    for path in [RSX, *packages]:
        if not path.is_file():
            raise FileNotFoundError('待定：required local RSX/input: ' + str(path))
    if not clip.exists():
        command = [RSX, '-nogui', '-export', '--loadwhitelist', 'x',
                   '--exportthreads', '4', '--parsethreads', '8',
                   '--exportdir', folder, '-exportfullpaths', '-nocachedb',
                   '--list', listings / 'octane_idle.csv', '--listformat', 'csv',
                   '--exporttypes', 'aseq,arig', '--exportexact',
                   row['asset_name'] + ',' + rig['asset_name'], *packages]
        run(command, runtime, 'export_octane_idle')
    if not clip.is_file() or clip.read_bytes()[:4] != b'cast':
        raise ValueError('RSX did not emit the expected Cast idle: ' + str(clip))
    save(out / 'sequence-source.json', dict(status='FOUND', sequence=row, rig=rig,
         frame=0, cast='$OUTPUT/' + clip.relative_to(out).as_posix(),
         local_dependency_manifest=str(MANIFEST.relative_to(ROOT)),
         sources=source_info([LIST, MANIFEST, RSX, *packages, clip], out),
         export_rule='local RSX only; exact ASEQ plus parent rig; no raw ASEQ export'))
    return clip


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=OUT)
    export_idle(parser.parse_args().out)
