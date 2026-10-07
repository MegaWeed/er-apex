"""Compare registered HUD artifacts directly, allowing only T017 schema additions."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from legend import HUD_ROOT, LEGENDS, output_path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf8')
ROOT = HUD_ROOT


def file_equal(first, second):
    if first.stat().st_size != second.stat().st_size:
        return False
    with first.open('rb') as a, second.open('rb') as b:
        while True:
            chunk = a.read(1024 * 1024)
            if chunk != b.read(1024 * 1024):
                return False
            if not chunk:
                return True


def registered(root):
    read = lambda name: json.loads((root / name).read_text(encoding='utf8'))
    assets = read('assets.json')['assets']
    fonts = read('fonts/fonts.json')['fonts']
    paths = {'hud_pack.json', 'assets.json', 'palette.json', 'localization.json', 'fonts/fonts.json'}
    for a in assets:
        paths.update(a[k] for k in ['image', 'payload_image', 'metadata'] if a.get(k))
    for f in fonts:
        paths.update([f['atlas_png'], f['atlas_dds'], f['metadata']])
        paths.add(f'fonts/{f["guid"]}/font.json')
        for profile in f['profiles']:
            paths.update(g['image'] for g in profile['glyphs'].values())
    paths.update(p.relative_to(root).as_posix() for p in (root / 'rui').glob('*.json'))
    paths.update(p.relative_to(root).as_posix() for p in (root / 'inputs').rglob('*') if p.is_file())
    paths.update('preview/' + n + '.png' for n in ['hud_hip', 'hud_ads', 'hud_reload', 'hud_sprint', 'hud_transparent', 'states', 'assets', 'fonts'])
    if (root / 'extra_images.json').is_file():
        paths.add('extra_images.json')
        paths.update(a['payload_image'] for a in read('extra_images.json').values())
    if (root / 'extra_localization.json').is_file():
        paths.add('extra_localization.json')
    return paths


def normalized(value):
    if isinstance(value, dict):
        return {k: normalized(v) for k, v in value.items() if k not in ('sha256', 'payload_sha256')}
    if isinstance(value, list):
        return [normalized(v) for v in value]
    return value


def compare(candidate, baseline=ROOT):
    candidate, baseline = candidate.resolve(), baseline.resolve()
    if candidate == baseline or not candidate.is_relative_to(ROOT.resolve()):
        raise ValueError('Candidate must be an independent directory inside apex-data/hud')
    paths = registered(baseline) | registered(candidate)
    missing, changed, permitted = [], [], []
    for name in sorted(paths):
        first, second = baseline / name, candidate / name
        if not first.resolve().is_relative_to(baseline) or not second.resolve().is_relative_to(candidate):
            raise ValueError(f'Registered artifact escapes its pack: {name}')
        if not first.is_file() or not second.is_file():
            missing.append(name)
            continue
        if file_equal(first, second):
            continue
        if second.suffix == '.json':
            a, b = normalized(json.loads(first.read_text(encoding='utf8'))), normalized(json.loads(second.read_text(encoding='utf8')))
            if name == 'hud_pack.json':
                a.pop('legend_upgrades', None)
                b.pop('legend_upgrades', None)
            if a == b:
                permitted.append(name)
                continue
        changed.append(name)
    result = {'result': 'PASS' if not missing and not changed else 'FAIL',
        'baseline': str(baseline), 'candidate': str(candidate), 'compared_files': len(paths),
        'missing': missing, 'changed': changed,
        'permitted_metadata_differences': permitted,
        'allowed_differences': ['removed sha256/payload_sha256 fields', 'hud_pack.json legend_upgrades field'],
        'comparison': 'file sizes + direct byte/content comparison',
        'exclusions': ['run manifests/logs with absolute output paths/timings', 'unregistered exploratory/raw files',
                       'verification/reproduction summaries']}
    # The baseline can be read-only; keep the report beside the candidate.
    (candidate / 'reproduction.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if missing or changed:
        raise SystemExit(1)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legend', choices=LEGENDS, default='fuse')
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--candidate', type=Path)
    args = parser.parse_args()
    baseline = output_path(args.legend, args.baseline)
    candidate = output_path(args.legend, args.candidate or baseline / 'repro_final')
    compare(candidate, baseline)
