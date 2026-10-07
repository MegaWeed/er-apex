"""One command: python tools/fusepov/build_pov.py; writes only er-data/s3/fuse_pov."""
import argparse
import shutil
import sys
import time
from pathlib import Path
sys.dont_write_bytecode = True
from common import ROOT, PARTS, MODELS, TOOL, EXTRACT, MATBIN, checked_out, run, save, file_info, legend_config
from mesh_pov import convert
from pov_textures import make_textures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legend', choices=('fuse', 'octane'), default='fuse')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--matbin-bnd', type=Path, default=MATBIN)
    args = parser.parse_args()
    out = checked_out(args.out or legend_config(args.legend)['out'], args.legend)
    material_source = args.matbin_bnd.resolve()
    start = time.monotonic()
    for required in (TOOL, EXTRACT, material_source):
        if not required.is_file():
            raise FileNotFoundError(f'Required read-only local input: {required}')
    print('T011: raw Cast positions * diag(0.0254,0.0254,-0.0254), owner/carrier weights, AM/BD partition', flush=True)
    previews = make_textures(out, args.legend)
    parts, summary = convert(out, args.legend)
    paths = [f'/parts/{p}_m_{MODELS[p]:04d}{lod}.partsbnd.dcx' for p in PARTS for lod in ('', '_l')]
    run([EXTRACT, 'get', *paths, '--out', out/'inputs'], out, 'extract_templates')
    destination = out/'inputs/material/allmaterial.matbinbnd.dcx'
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(material_source, destination)
    assert material_source.read_bytes() == destination.read_bytes()
    save(out/'inputs/source-material.json', dict(source=str(material_source), size=material_source.stat().st_size,
         snapshot_size=destination.stat().st_size, snapshot_byte_identical=True,
         note='Read-only input bundle copied before staging target replacements; every other entry preserved'))
    from material_bundle import prepare, merge
    staged = prepare(out, destination)
    command = [TOOL, 'build-armor', '--model', '998', '--matbin-bnd', staged, '--out', out/'package']
    for part in PARTS:
        command += [f'--{part}-template', out/f'inputs/parts/{part}_m_{MODELS[part]:04d}.partsbnd.dcx']
        if part in ('am', 'bd'):
            command += [f'--{part}-mesh', out/'fusemesh'/part]
    run(command, out, 'build_package')
    merge(out, destination)
    # Read the actual quantized FLVER before rendering its carrier view.
    from verify_pov import verify, verify_preview
    verification = verify(out, args.legend, check_preview=False)
    from preview_pov import make_previews
    make_previews(out, parts, previews, args.legend)
    verify_preview(out, verification, args.legend)
    save(out/'readback-verification.json', verification)
    verification['elapsed_seconds'] = round(time.monotonic()-start, 2)
    save(out/'verification.json', verification)
    print(f'PASS T011 package/readback: {sum(m["vertices"] for m in summary["parts"].values())} vertices; '
          f'{sum(m["triangles"] for m in summary["parts"].values())} triangles; 8 parts + allmaterial; '
          f'elapsed {verification["elapsed_seconds"]}s', flush=True)


if __name__ == '__main__':
    main()
