"""T020 direct-content comparison of clean-build package, mesh, texture and preview artifacts."""
import argparse
from pathlib import Path
from common import read, save
from mesh_ability import ac


def compare(repro, out=None):
    out = ac.checked(out or ac.MODEL_ROOT, ac.MODEL_ROOT, create=False)
    repro = ac.checked(repro, ac.MODEL_ROOT, create=False)
    counts = {}
    for folder in ('package', 'fusemesh', 'textures', 'inputs/live-templates'):
        files = sorted(p for p in (out/folder).rglob('*') if p.is_file() and (folder != 'package' or p.suffix == '.dcx'))
        other = sorted(p.relative_to(repro/folder) for p in (repro/folder).rglob('*') if p.is_file() and (folder != 'package' or p.suffix == '.dcx'))
        ac.require([p.relative_to(out/folder) for p in files] == other, f'File inventory differs: {folder}')
        for path in files:
            relative = path.relative_to(out)
            ac.require(path.read_bytes() == (repro/relative).read_bytes(), f'File bytes differ: {relative}')
        counts[folder] = len(files)
    preview = read(out/'ability-preview-verification.json')
    for item in preview['previews']+preview['diagnostic_previews']:
        name = item['file']
        ac.require((out/'preview'/name).read_bytes() == (repro/'preview'/name).read_bytes(), f'Preview differs: {name}')
    counts['preview'] = len(preview['previews'])+len(preview['diagnostic_previews'])
    ac.require((out/'inputs/fuse_pov.anim').read_bytes() == (repro/'inputs/fuse_pov.anim').read_bytes(), 'Preview packs differ')
    def normalized(value):
        if isinstance(value, str):
            return value.replace(str(repro), str(out)).replace(repro.relative_to(ac.ROOT).as_posix(), out.relative_to(ac.ROOT).as_posix())
        if isinstance(value, dict):
            return {k: normalized(v) for k, v in value.items() if k != 'elapsed_seconds'}
        if isinstance(value, list):
            return [normalized(v) for v in value]
        return value
    audits = ['ability-mesh-summary.json', 'ability-texture-audit.json', 'ability-template-audit.json',
              'ability-readback-verification.json', 'ability-preview-verification.json',
              'material-bundle-audit.json', 'material-bundle-verification.json', 'package/build-manifest.json']
    for name in audits:
        ac.require(normalized(read(out/name)) == normalized(read(repro/name)), f'Audit differs beyond output paths: {name}')
    report = dict(status='PASS', reproduction=str(repro), byte_identical=counts, pack_byte_identical=True,
                  audit_count=len(audits), audit_normalization='Only output path prefix and elapsed_seconds')
    save(out/'ability-reproducibility.json', report)
    print(f'PASS T020 clean reproduction: {counts}; FPOV byte-identical; {len(audits)} audits equal except output paths/time', flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--repro', type=Path, required=True)
    args = parser.parse_args()
    compare(args.repro, args.out)
