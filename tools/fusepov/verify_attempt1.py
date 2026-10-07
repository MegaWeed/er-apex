"""Prove the corrected build only changes reflection-related geometry/bounds."""
import argparse
import sys
from pathlib import Path
import numpy as np
sys.dont_write_bytecode = True
from common import OUT, PARTS, read, save, checked_out, legend_config
from verify_pov import stream


def compare(out=None, previous=None, legend='fuse'):
    out = checked_out(out or legend_config(legend)['out'], legend)
    previous = Path(previous or out/'attempt1')
    assert (previous/'verification.json').is_file(), 'Missing archived attempt 1 reproduction'
    counts = dict(submeshes=0, unchanged_streams=0, unchanged_tpf_files=0)
    for part in ('am', 'bd'):
        old_folder, new_folder = previous/'fusemesh'/part, out/'fusemesh'/part
        old_doc, new_doc = read(old_folder/'mesh.json'), read(new_folder/'mesh.json')
        assert (old_folder/'mesh.json').read_bytes() == (new_folder/'mesh.json').read_bytes()
        for old_sub, new_sub in zip(old_doc['submeshes'], new_doc['submeshes']):
            counts['submeshes'] += 1
            for key in ('uv0', 'uv1', 'bone_indices', 'bone_weights', 'source_vertex_ids', 'source_triangle_ids'):
                assert (old_folder/old_sub[key]).read_bytes() == (new_folder/new_sub[key]).read_bytes(), (part, key)
                counts['unchanged_streams'] += 1
            for key in ('positions', 'normals'):
                expected = stream(old_folder, old_sub, key)*[1., 1., -1.]
                assert np.array_equal(stream(new_folder, new_sub, key), expected), (part, old_sub['name'], key)
            tangents = stream(old_folder, old_sub, 'tangents')*[1., 1., -1., -1.]
            assert np.array_equal(stream(new_folder, new_sub, 'tangents'), tangents), (part, old_sub['name'], 'tangents')
            old_faces = stream(old_folder, old_sub, 'indices')
            assert np.array_equal(stream(new_folder, new_sub, 'indices'), old_faces[:, [0, 2, 1]])
    for audit in ('bodygroups.json', 'texture-audit.json'):
        def without_provenance(value):
            if isinstance(value, dict):
                return {k: without_provenance(v) for k, v in value.items() if k not in ('source_sha256', 'sources')}
            if isinstance(value, list):
                return [without_provenance(v) for v in value]
            return value
        assert without_provenance(read(previous/audit)) == without_provenance(read(out/audit)), audit
    old_summary, new_summary = read(previous/'pov-mesh-summary.json'), read(out/'pov-mesh-summary.json')
    for key in ('parts', 'incompatible_triangles', 'max_part_weight_loss', 'max_four_weight_loss', 'boundary_duplicate_vertices'):
        assert old_summary[key] == new_summary[key], key
    old_textures = {p.relative_to(previous/'textures'): p for p in (previous/'textures').glob('*.png')}
    new_textures = {p.relative_to(out/'textures'): p for p in (out/'textures').glob('*.png')}
    assert old_textures.keys() == new_textures.keys()
    for name in old_textures:
        assert old_textures[name].read_bytes() == new_textures[name].read_bytes(), name
    identical_packages = ['material/allmaterial.matbinbnd.dcx']
    identical_packages += [f'parts/{p}_m_0998{lod}.partsbnd.dcx' for p in ('hd', 'lg') for lod in ('', '_l')]
    for relative in identical_packages:
        assert (previous/'package'/relative).read_bytes() == (out/'package'/relative).read_bytes(), relative
    for part in PARTS:
        for lod in ('', '_l'):
            folder = f'{part}_m_0998{lod}.partsbnd'
            old_tpf = {p.relative_to(previous/'readback'/folder): p for p in (previous/'readback'/folder).rglob('*.tpf')}
            new_tpf = {p.relative_to(out/'readback'/folder): p for p in (out/'readback'/folder).rglob('*.tpf')}
            assert old_tpf.keys() == new_tpf.keys()
            for name in old_tpf:
                assert old_tpf[name].read_bytes() == new_tpf[name].read_bytes(), (folder, name)
                counts['unchanged_tpf_files'] += 1
    report = dict(status='PASS', attempt1_archive=str(previous), checks=counts,
                  positions_normals_only_z_negated=True, tangents_only_z_and_w_negated=True,
                  indices_swapped_once_relative_to_attempt1=True,
                  carriers_weights_partition_materials_textures_unchanged=True,
                  unchanged_package_sizes={p: (out/'package'/p).stat().st_size for p in identical_packages})
    save(out/'attempt1-comparison.json', report)
    print(f'PASS attempt 1 comparison: {counts}; positions/normals Z and tangents Z/W negated; '
          'source-order indices; carriers/weights/partition/materials/textures unchanged; '
          'allmaterial and 4 empty-part packages byte-identical', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legend', choices=('fuse', 'octane'), default='fuse')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--previous', type=Path, help='Archived pre-mirror build; Octane has no default historical archive')
    args = parser.parse_args()
    compare(args.out, args.previous, args.legend)
