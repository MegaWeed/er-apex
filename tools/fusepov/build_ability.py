"""T020: one command builds a complete Octane 998 package, with HD/LG ability props."""
import argparse
import shutil
import sys
import time
from pathlib import Path
sys.dont_write_bytecode = True
from common import ROOT, PARTS, MODELS, TOOL, EXTRACT, run, read, save
from mesh_ability import ac, make_textures, convert
from material_bundle import helper, merge

DEFAULT_MATBIN = ROOT/'er-data/s3/octane_gun/package/material/allmaterial.matbinbnd.dcx'


def build(out=None, matbin_bnd=DEFAULT_MATBIN, pack=None):
    out = ac.checked(out or ac.MODEL_ROOT, ac.MODEL_ROOT)
    start = time.monotonic()
    source = Path(matbin_bnd).resolve()
    for path in (source, TOOL, EXTRACT, ac.BASE_PACK):
        if not path.is_file():
            raise FileNotFoundError(f'Required local read-only input: {path}')
    # A stand-alone build reads the same local data, but writes its preview pack
    # only under the ER output directory. It never mutates the canonical pack.
    from bake_ability import generate
    generated, sequences, audit = generate()
    if pack is None:
        pack = out/'inputs/fuse_pov.anim'
        pack.parent.mkdir(parents=True, exist_ok=True)
        ac.write_pack(pack, generated)
        canonical = ac.PACK_ROOT/'fuse_pov.anim'
        if canonical.is_file():
            ac.require(canonical.read_bytes() == pack.read_bytes(), 'Canonical ability pack differs from independent build')
    else:
        source_pack = Path(pack).resolve()
        pack = out/'inputs/fuse_pov.anim'
        pack.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_pack, pack)
    save(out/'inputs/ability_sequences.json', sequences)
    save(out/'inputs/ability-pack-audit.json', audit)
    make_textures(out)
    _, summary = convert(out)
    paths = [f'/parts/{p}_m_{MODELS[p]:04d}{lod}.partsbnd.dcx' for p in PARTS for lod in ('', '_l')]
    run([EXTRACT, 'get', *paths, '--out', out/'inputs'], out, 'extract_templates')
    from template_ability import prepare_templates
    prepare_templates(out)
    snapshot = out/'inputs/material/allmaterial.matbinbnd.dcx'
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, snapshot)
    ac.require(source.read_bytes() == snapshot.read_bytes(), 'Material snapshot differs')
    save(out/'inputs/source-material.json', dict(source=str(source), size=source.stat().st_size, snapshot_size=snapshot.stat().st_size))
    names = [f'P[{part.upper()}_M_0998]_'+m['name'] for part in ('hd', 'lg')
             for m in read(out/'fusemesh'/part/'mesh.json')['materials']]
    targets = out/'inputs/material-targets.json'; save(targets, names)
    staged = snapshot.with_name('build-input.matbinbnd.dcx')
    helper(out, 'prepare', snapshot, staged, targets)
    command = [TOOL, 'build-armor', '--model', '998', '--matbin-bnd', staged, '--out', out/'package']
    for part in PARTS:
        template_dir = 'live-templates' if part in ('hd', 'lg') else 'parts'
        command += [f'--{part}-template', out/f'inputs/{template_dir}/{part}_m_{MODELS[part]:04d}.partsbnd.dcx']
        if part in ('hd', 'lg'):
            command += [f'--{part}-mesh', out/'fusemesh'/part]
    run(command, out, 'build_package')
    merge(out, snapshot)
    for part in ('am', 'bd'):
        for lod in ('', '_l'):
            name = f'{part}_m_0998{lod}.partsbnd.dcx'
            shutil.copyfile(ac.BASE_MODEL/'package/parts'/name, out/'package/parts'/name)
    manifest = read(out/'package/build-manifest.json')
    base_manifest = read(ac.BASE_MODEL/'package/build-manifest.json')
    manifest.update(task='T020', base_package=str(ac.BASE_MODEL/'package'),
                    preserved_parts=['am', 'am_l', 'bd', 'bd_l'], animation_pack=str(pack),
                    original_meshes=base_manifest['meshes'], prop_meshes=manifest['meshes'],
                    original_materials=base_manifest['materials'], prop_materials=manifest['materials'])
    manifest['meshes'] += base_manifest['meshes']
    manifest['materials'] += base_manifest['materials']
    manifest['vertices'] += base_manifest['vertices']
    for piece in manifest['parts']:
        if piece['piece'] in ('am', 'bd'):
            existing = next(p for p in base_manifest['parts'] if p['piece'] == piece['piece'])
            piece.update(existing, copied_byte_identical=True, source_package=str(ac.BASE_MODEL/'package'))
    manifest['textures'] = base_manifest['textures']+manifest['textures']
    save(out/'package/build-manifest.json', manifest)
    from verify_ability import verify
    report = verify(out, check_preview=False)
    from preview_ability import make_previews
    make_previews(out, pack)
    from verify_ability import verify_preview
    report['previews'] = verify_preview(out)
    report['elapsed_seconds'] = round(time.monotonic()-start, 2)
    save(out/'ability-verification.json', report)
    print(f'PASS T020 build: complete 998, AM/BD byte-identical; HD {summary["parts"]["hd"]["vertices"]} vertices / '
          f'{summary["parts"]["hd"]["triangles"]} triangles; LG {summary["parts"]["lg"]["vertices"]} / '
          f'{summary["parts"]["lg"]["triangles"]}; 11 requested + 2 diagnostic previews; {report["elapsed_seconds"]}s', flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, help='Directory inside er-data/s3/octane_pov_ability')
    parser.add_argument('--matbin-bnd', type=Path, default=DEFAULT_MATBIN)
    parser.add_argument('--pack', type=Path, help='Optional FPOV v2 input; copied under this output')
    args = parser.parse_args()
    build(args.out, args.matbin_bnd, args.pack)
