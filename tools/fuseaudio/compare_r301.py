"""Compare a fresh R-301 export with T007 without calculating content hashes."""
import sys

sys.dont_write_bytecode = True

import argparse
import json
from pathlib import Path

from export_audio import OCTANE_OUT, OUT, dump


def without_hash_fields(value):
    if isinstance(value, dict):
        return {key: without_hash_fields(item) for key, item in value.items() if key != 'sha256'}
    if isinstance(value, list):
        return [without_hash_fields(item) for item in value]
    return value


def same_content(left, right):
    """Check sizes and then compare every byte; do not use cached file equality."""
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open('rb') as original, right.open('rb') as fresh:
        while True:
            chunk = original.read(1024 * 1024)
            if chunk != fresh.read(1024 * 1024):
                return False
            if not chunk:
                return True


def compare(original, fresh):
    original, fresh = original.resolve(), fresh.resolve()
    differences = []
    wav_files = 0
    for folder in ('raw', 'r301'):
        before = {p.relative_to(original).as_posix(): p for p in (original / folder).rglob('*.wav')}
        after = {p.relative_to(fresh).as_posix(): p for p in (fresh / folder).rglob('*.wav')}
        if before.keys() != after.keys():
            differences.append({'folder': folder, 'missing': sorted(before.keys() - after.keys()),
                                'extra': sorted(after.keys() - before.keys())})
        for name in sorted(before.keys() & after.keys()):
            if not same_content(before[name], after[name]):
                differences.append({'file': name, 'reason': 'size or direct byte comparison failed'})
            wav_files += 1
    metadata = ('manifest.json', 'event_map.json', 'source_inventory.json', 'verification.json')
    for name in metadata:
        before = json.loads((original / name).read_text(encoding='utf8'))
        after = json.loads((fresh / name).read_text(encoding='utf8'))
        if without_hash_fields(before) != without_hash_fields(after):
            differences.append({'file': name, 'reason': 'JSON differs beyond removed hash fields'})
    if not same_content(original / 'mapping.md', fresh / 'mapping.md'):
        differences.append({'file': 'mapping.md', 'reason': 'direct byte comparison failed'})

    # Logs describe this invocation; directories and elapsed times are not assets.
    before = json.loads((original / 'logs/run.json').read_text(encoding='utf8'))
    after = json.loads((fresh / 'logs/run.json').read_text(encoding='utf8'))
    command = after['command'].copy()
    export_argument = command.index('--exportdir') + 1
    if Path(command[export_argument]).resolve() != fresh / 'raw' or Path(after['cwd']).resolve() != fresh / 'logs/rsx_runtime':
        differences.append({'file': 'logs/run.json', 'reason': 'incorrect actual output/work paths'})
    command[export_argument] = before['command'][export_argument]
    if command != before['command'] or before['exit_code'] != 0 or after['exit_code'] != 0:
        differences.append({'file': 'logs/run.json', 'reason': 'RSX arguments or exit status changed'})
    return {'status': 'passed' if not differences else 'failed', 'baseline': str(original),
            'check_output': str(fresh), 'wav_files_compared_byte_for_byte': wav_files,
            'metadata_equal_except_removed_hash_fields': list(metadata),
            'mapping_equal_byte_for_byte': not any(d.get('file') == 'mapping.md' for d in differences),
            'invocation_logs': {'exit_code': after['exit_code'], 'cwd': after['cwd'],
                                'seconds': after['seconds'],
                                'policy': 'actual output/work paths and timing retained; RSX args and success checked'},
            'differences': differences}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=OUT)
    parser.add_argument('--check-dir', type=Path, default=OCTANE_OUT / 'r301_check')
    parser.add_argument('--report', type=Path, default=OCTANE_OUT / 'r301_comparison.json')
    args = parser.parse_args()
    if not args.report.resolve().is_relative_to(OCTANE_OUT.resolve()):
        raise ValueError('Comparison report must stay inside apex-data/audio/octane/')
    report = compare(args.baseline, args.check_dir)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    dump(args.report, report)
    print(f'{report["status"]}: {report["wav_files_compared_byte_for_byte"]} WAV files compared; '
          f'{len(report["metadata_equal_except_removed_hash_fields"])} JSON files checked without hash fields; '
          f'{len(report["differences"])} differences')
    if report['differences']:
        print(json.dumps(report['differences'], ensure_ascii=False, indent=2))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
