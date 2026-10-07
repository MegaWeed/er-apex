"""Compare a complete build in an initially empty output directory."""
import argparse
import sys
from pathlib import Path
sys.dont_write_bytecode = True
from common import OUT, checked_out, read, save, legend_config


def compare(repro=None, out=None, legend='fuse'):
    out = checked_out(out or legend_config(legend)['out'], legend)
    repro = checked_out(repro or out/'repro_final', legend)
    counts = {}
    for directory, pattern in [('package', '*.dcx'), ('fusemesh', '*'), ('textures', '*.png'), ('preview', '*.png')]:
        original = {p.relative_to(out): p for p in (out/directory).rglob(pattern) if p.is_file()}
        rebuilt = {p.relative_to(repro): p for p in (repro/directory).rglob(pattern) if p.is_file()}
        assert original.keys() == rebuilt.keys(), directory
        for key, source in original.items():
            assert source.read_bytes() == rebuilt[key].read_bytes(), key
        counts[directory] = len(original)
    def normalize(value, directory):
        if isinstance(value, str):
            return value.replace(str(directory), '{OUT}').replace(directory.as_posix(), '{OUT}')
        if isinstance(value, dict):
            return {k: normalize(v, directory) for k, v in value.items()}
        if isinstance(value, list):
            return [normalize(v, directory) for v in value]
        return value
    audit_files = ['bodygroups.json', 'pov-mesh-summary.json', 'texture-audit.json',
                   'preview-verification.json', 'readback-verification.json']
    for name in audit_files:
        assert normalize(read(out/name), out) == normalize(read(repro/name), repro), name
    assert normalize(read(out/'package/build-manifest.json'), out) == normalize(read(repro/'package/build-manifest.json'), repro)
    report = dict(status='PASS', reproduction_directory=str(repro), byte_identical_counts=counts,
                  audits_equal_except_output_paths=audit_files, build_manifest_equal_except_output_paths=True)
    save(out/'reproducibility.json', report)
    print(f'PASS clean reproduction: {counts}; 5 audits and manifest equal except output paths', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legend', choices=('fuse', 'octane'), default='fuse')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--repro', type=Path)
    args = parser.parse_args()
    compare(args.repro, args.out, args.legend)
