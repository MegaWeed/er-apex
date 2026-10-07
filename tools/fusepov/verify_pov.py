"""Independent source/FLVER readback, enabled nodes, local bounds, and 999 preservation."""
import argparse
import sys
from pathlib import Path
import numpy as np
sys.dont_write_bytecode = True
from common import (ROOT, OUT, PARTS, MODELS, TOOL, EXTRACT, CARRIERS, MATBIN,
                    checked_out, read, save, run, check_file_info, winding, tangent_basis, legend_config)
from mesh_pov import selection, STREAMS
from verify_fuse import read_json_command
from verify_armor_bounds import verify as verify_bounds
from s3a_roundtrip import arrays


def stream(folder, sub, key):
    if key == 'flver_bone_weights':
        dtype, width = '<f4', 4
    else:
        dtype, width = STREAMS[key]
    return np.fromfile(folder/sub[key], dtype).reshape(-1, width)


def quantize_weights(weights):
    """ArmorBuilder.QuantizeWeights single-precision arithmetic and stable ties."""
    weights = np.asarray(weights, dtype=np.float32)
    total = np.zeros(len(weights), dtype=np.float32)
    for k in range(4):
        total = total + weights[:, k]
    scaled = (weights/total[:, None])*np.float32(255)
    integers = np.floor(scaled).astype(int)
    rank = np.argsort(-(scaled-integers), axis=1, kind='stable')
    for i, remainder in enumerate(255-integers.sum(1)):
        integers[i, rank[i, :remainder]] += 1
    return integers


def source_expected(mdl, mesh, mapping):
    """Reconstruct every vertex from original Cast, independently of conversion code."""
    count = mesh.VertexCount()
    source_weights = np.array(mesh.VertexWeightValueBuffer()).reshape(count, -1)
    source_bones = np.array(mesh.VertexWeightBoneBuffer()).reshape(source_weights.shape)
    bones = mdl.Skeleton().Bones()
    owners = {c['owner']: i for i, c in enumerate(mapping['carriers'])}
    names = [c['carrier'] for c in mapping['carriers']]
    result_indices = np.zeros((count, 4), dtype=int)
    result_weights = np.zeros((count, 4))
    losses = []
    for v in range(count):
        merged = {}
        total = source_weights[v].sum()
        for bone, weight in zip(source_bones[v], source_weights[v]):
            if weight <= 0:
                continue
            owner = mapping['owner_of_bone'][bones[int(bone)].Name()]
            assert owner is not None, (mesh.Name(), v, bones[int(bone)].Name())
            index = owners[owner]
            merged[index] = merged.get(index, 0.) + weight/total
        ranked = sorted(merged, key=lambda i: (-merged[i], i))[:4]
        retained = sum(merged[i] for i in ranked)
        losses.append(max(0., 1-retained))
        result_indices[v] = ranked+[ranked[0]]*(4-len(ranked))
        result_weights[v, :len(ranked)] = [merged[i]/retained for i in ranked]
    return np.array(names)[result_indices], result_weights, max(losses)


def verify(out=None, legend='fuse', check_preview=True):
    out = checked_out(out or legend_config(legend)['out'], legend)
    (out/'logs').mkdir(exist_ok=True)
    pkg, rb = out/'package', out/'readback'
    mapping = read(CARRIERS)
    geometry = read(out/'pov-mesh-summary.json')
    for info in geometry['sources']:
        check_file_info(info)
    from pov_textures import texture_arrays
    from PIL import Image
    for material in read(out/'texture-audit.json')['materials'].values():
        paths = {usage: check_file_info(info) for usage, info in material['sources'].items()}
        col, normal, metal = texture_arrays(paths)
        name = paths['col'].name.removesuffix('_col.png')
        for suffix, expected_pixels in [('a', col), ('n', normal), ('m', np.rint(metal*255).astype(np.uint8))]:
            assert np.array_equal(np.asarray(Image.open(out/'textures'/f'{name}_{suffix}.png')), expected_pixels), ('texture content differs', name, suffix)
    carriers = {c['carrier']: c for c in mapping['carriers']}
    sources = {mesh.Name(): (mdl, mesh) for kind, mdl, mesh in selection(legend=legend)}
    expected = {name: source_expected(mdl, mesh, mapping) for name, (mdl, mesh) in sources.items()}
    expected_parts = {}
    for name, (_, mesh) in sources.items():
        names, weights, _ = expected[name]
        faces = np.asarray(mesh.FaceBuffer()).reshape(-1, 3)
        loss = {part: np.array([sum(w for n, w in zip(row, wr) if part not in carriers[n]['parts'])
                                for row, wr in zip(names, weights)]) for part in ('am', 'bd')}
        am_valid = (loss['am'][faces] == 0).all(1)
        bd_valid = (loss['bd'][faces] == 0).all(1)
        labels = np.where(am_valid, 'am', 'bd')
        incompatible = ~(am_valid | bd_valid)
        labels[incompatible] = np.where(loss['am'][faces[incompatible]].sum(1) <=
                                           loss['bd'][faces[incompatible]].sum(1), 'am', 'bd')
        expected_parts[name] = labels
    seen_triangles = {name: [] for name in sources}
    summary = dict(status='PASS', parts={}, source_cast_checked=True)
    # Compare the snapshot with the exact read-only installed input used by the build.
    snapshot = out/'inputs/material/allmaterial.matbinbnd.dcx'
    source_audit = read(out/'inputs/source-material.json')
    assert snapshot.stat().st_size == source_audit['snapshot_size'] == source_audit['size']
    assert Path(source_audit['source']).read_bytes() == snapshot.read_bytes(), 'input material bundle changed since snapshot'
    summary['material_source'] = dict(source=source_audit['source'], size=source_audit['size'])
    summary['installed_source_still_matches_snapshot'] = True
    from material_bundle import verify_material
    material_audit = verify_material(out, snapshot)
    summary['material_bundle'] = {key: material_audit[key] for key in
                                 ('original_entries', 'output_entries', 'replaced_entries', 'added_entries', 'header_unchanged', 'original_entry_order_ids_names_flags_unchanged')}
    summary['preserved_input_entry_count'] = len(material_audit['preserved_entries'])
    run([EXTRACT, 'unpack', snapshot, '--out', rb/'original_999', '--filter', '_M_0999'], out, 'read_original_999')
    for number in ('0999', '0998'):
        run([EXTRACT, 'unpack', pkg/'material/allmaterial.matbinbnd.dcx', '--out', rb/('material_'+number),
             '--filter', '_M_'+number], out, 'read_material_'+number)
    original_files = {p.relative_to(rb/'original_999'): p for p in (rb/'original_999').rglob('*.matbin')}
    new_files = {p.relative_to(rb/'material_0999'): p for p in (rb/'material_0999').rglob('*.matbin')}
    assert original_files and original_files.keys() == new_files.keys()
    summary['preserved_999_matbins'] = {str(k): p.stat().st_size for k, p in original_files.items()}
    for relative, path in original_files.items():
        assert path.read_bytes() == new_files[relative].read_bytes(), relative
    original_bnd = read_json_command(run, [TOOL, 'bnd', snapshot], out, 'bnd_original_material')
    rebuilt_bnd = read_json_command(run, [TOOL, 'bnd', pkg/'material/allmaterial.matbinbnd.dcx'], out, 'bnd_rebuilt_material')
    old_entries = {f['Name']: f for f in original_bnd['Files'] if '_M_0999' in f['Name']}
    new_entries = {f['Name']: f for f in rebuilt_bnd['Files'] if '_M_0999' in f['Name']}
    assert old_entries == new_entries and len(old_entries) == len(original_files)
    summary['all_999_entry_ids_names_flags_sizes_unchanged'] = True
    manifest = read(pkg/'build-manifest.json')
    assert manifest['model'] == 998
    textures = {t['name'] for t in manifest['textures']}
    for part in PARTS:
        infolder = out/'fusemesh'/part
        a = read(infolder/'mesh.json') if part in ('bd', 'am') else None
        for lod in ('', '_l'):
            path = pkg/f'parts/{part}_m_0998{lod}.partsbnd.dcx'
            assert path.read_bytes()[0x28:0x2c] == b'KRAK'
            run([EXTRACT, 'unpack', path, '--out', rb/path.stem], out, 'unpack_'+path.stem)
            flver = next((rb/path.stem).rglob('*.flver'))
            dump = read_json_command(run, [TOOL, 'flver', flver, '--samples', '0'], out, 'flver_'+part+lod)
            folder = rb/f'export_{part}{lod}'
            save(folder/'flver.json', dump)
            if a is None:
                assert not dump['Meshes'], (part, lod, 'must be empty')
                assert np.array_equal(list(dump['Header']['BoundingBoxMin'].values()), [0, 0, 0])
                assert np.array_equal(list(dump['Header']['BoundingBoxMax'].values()), [0, 0, 0])
                summary['parts'][part+lod] = dict(meshes=0, vertices=0, triangles=0, empty_verified=True)
                continue
            run([TOOL, 'export-mesh', path, '--matbin-bnd', pkg/'material/allmaterial.matbinbnd.dcx', '--out', folder],
                out, 'export_'+part+lod)
            b = read(folder/'mesh.json')
            assert len(a['submeshes']) == len(b['submeshes'])
            template = read(ROOT/f'er-data/json/parts/{part.upper()}_M_{MODELS[part]}.json')
            assert len(template['Nodes']) == len(dump['Nodes'])
            for old, node in zip(template['Nodes'], dump['Nodes']):
                for key in ('Name', 'ParentIndex', 'Flags', 'Translation', 'RotationQuaternion', 'Scale'):
                    assert old[key] == node[key], (part, 'template node changed', key)
            vertices, triangles, max_error = 0, 0, 0.
            actual_winding = dict(along=0, against=0, degenerate=0, orthogonal=0)
            for s, t in zip(a['submeshes'], b['submeshes']):
                mesh = sources[s['name']][1]
                vids = np.fromfile(infolder/s['source_vertex_ids'], '<u4')
                tids = np.fromfile(infolder/s['source_triangle_ids'], '<u4')
                assert len(vids) == s['vertex_count'] and len(tids)*3 == s['index_count']
                assert (np.diff(vids.astype(int)) > 0).all() and (np.diff(tids.astype(int)) > 0).all()
                assert np.array_equal(tids, np.flatnonzero(expected_parts[s['name']] == part)), (part, s['name'], 'AM-first partition')
                source_positions = np.asarray(mesh.VertexPositionBuffer()).reshape(-1, 3)
                target_positions = np.asarray(source_positions[vids]*[.0254, .0254, -.0254], dtype='<f4')
                assert np.array_equal(stream(infolder, s, 'positions'), target_positions)
                assert np.array_equal(stream(folder, t, 'positions'), target_positions), (part, s['name'], 'Cast positions')
                source_normals = np.asarray(mesh.VertexNormalBuffer()).reshape(-1, 3)
                source_normals /= np.maximum(np.linalg.norm(source_normals, axis=1, keepdims=True), 1e-12)
                source_faces = np.asarray(mesh.FaceBuffer()).reshape(-1, 3)
                source_uv = np.asarray(mesh.VertexUVLayerBuffer(0)).reshape(-1, 2)
                _, tangent, sign, _ = tangent_basis(source_positions, source_normals, source_uv, source_faces)
                expected_normals = source_normals[vids]*[1., 1., -1.]
                tangent = tangent[vids]*[1., 1., -1.]
                tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-12)
                expected_tangents = np.c_[tangent, -sign[vids]].astype('<f4')
                assert np.array_equal(stream(infolder, s, 'normals'), expected_normals.astype('<f4'))
                assert np.array_equal(stream(infolder, s, 'tangents'), expected_tangents), (part, s['name'], 'mirrored tangent XYZ and negated W')
                global_faces = vids[stream(folder, t, 'indices')]
                assert np.array_equal(global_faces, source_faces[tids]), (part, s['name'], 'source index order after two flips')
                for key in ('positions', 'indices'):
                    assert (infolder/s[key]).read_bytes() == (folder/t[key]).read_bytes()
                target_names, weights, _ = expected[s['name']]
                target_names, weights = target_names[vids].copy(), weights[vids].copy()
                allowed = np.array([[part in carriers[n]['parts'] for n in row] for row in target_names])
                weights *= allowed
                assert (weights.sum(1) > 0).all()
                weights /= weights.sum(1)[:, None]
                first = np.argmax(weights > 0, axis=1)
                target_names[weights == 0] = np.broadcast_to(target_names[np.arange(len(vids)), first, None], target_names.shape)[weights == 0]
                stored_names = np.array(a['bones'])[stream(infolder, s, 'bone_indices')]
                read_names = np.array(b['bones'])[stream(folder, t, 'bone_indices')]
                assert np.array_equal(target_names, stored_names) and np.array_equal(target_names, read_names)
                weight32 = weights.astype('<f4')
                assert np.array_equal(stream(infolder, s, 'bone_weights'), weight32), (part, s['name'], 'owner merge')
                actual_weights = stream(folder, t, 'flver_bone_weights')
                assert np.array_equal(np.rint(actual_weights*255).astype(int), quantize_weights(weight32)), (part, s['name'], 'quantization')
                max_error = max(max_error, float(abs(actual_weights-weight32).max()))
                for name in read_names[actual_weights > 0]:
                    node = next(n for n in dump['Nodes'] if n['Name'] == name)
                    assert 'Bone' in node['Flags'] and 'Disabled' not in node['Flags']
                    assert part in carriers[name]['parts']
                for key in ('normals', 'tangents', 'uv0', 'uv1'):
                    tolerance = 1/127 if key in ('normals', 'tangents') else 1/2048
                    assert abs(stream(infolder, s, key)-stream(folder, t, key)).max() <= tolerance+1e-6
                assert len(t['face_sets']) == 6
                # Every serialized LOD/MotionBlur face set must use the same indices.
                for face in t['face_sets']:
                    assert (folder/face['indices']).read_bytes() == (infolder/s['indices']).read_bytes()
                stats = winding(target_positions, stream(folder, t, 'normals'), stream(folder, t, 'indices'))
                for key in actual_winding:
                    actual_winding[key] += stats[key]
                vertices += s['vertex_count']
                triangles += len(tids)
                if not lod:
                    seen_triangles[s['name']].extend(tids.tolist())
            # Independent T003 checker derives bone world/inverse and actual quantized active influences.
            verify_bounds(dump, b, folder, arrays)
            summary['parts'][part+lod] = dict(meshes=len(a['submeshes']), vertices=vertices, triangles=triangles,
                positions_equal_diag_k_k_minus_k_times_cast=True, indices_equal_source_after_two_flips=True,
                normals_tangents_z_mirrored=True, tangent_w_negated=True,
                bone_names_and_quantized_weights_exact=True, every_weighted_node_enabled=True,
                template_node_transforms_unchanged=True, bounds='PASS independent node-local/minmax reconstruction',
                max_weight_quantization_error=max_error, serialized_winding=actual_winding)
        if a is not None:
            assert len(list((rb/f'export_{part}').glob('*.dds'))) == len([t for t in textures if t.startswith(part.upper()+'_M_0998_')])
            for material in a['materials']:
                stem = f'P[{part.upper()}_M_0998]_'+material['name']
                file = next(p for p in (rb/'material_0998').rglob('*.matbin') if p.stem == stem)
                data = read_json_command(run, [TOOL, 'matbin', file], out, 'matbin_'+part+'_'+material['name'])['Data']
                params = {p['Name']: p['Value'] for p in data['Params']}
                assert all(params[k] == value for k, value in material['float_params'].items())
                for sampler in data['Samplers']:
                    name = sampler['Path'].replace('\\', '/').split('/')[-1].removesuffix('.tif')
                    if '_M_0998_' in name:
                        assert name in textures and (rb/f'export_{part}'/(name+'.dds')).is_file()
                for typ in material['sampler_textures']:
                    path = next(s['Path'] for s in data['Samplers'] if s['Type'] == typ)
                    assert '_M_0998_' in path and 'AAT' not in path
            for material in read(rb/f'export_{part}/flver.json')['Materials']:
                name = material['MTD'].replace('\\', '/').split('/')[-1].replace('.matxml', '.matbin')
                assert any(p.name == name for p in (rb/'material_0998').rglob('*.matbin'))
    for name, (_, mesh) in sources.items():
        assert sorted(seen_triangles[name]) == list(range(len(mesh.FaceBuffer())//3)), (name, 'triangle coverage')
    assert len(list(pkg.rglob('*.dcx'))) == 9
    new_materials = list((rb/'material_0998').rglob('*.matbin'))
    target_names = set(read(out/'inputs/material-targets.json'))
    selected_materials = [p for p in new_materials if p.stem in target_names]
    assert len(selected_materials) == manifest['materials'] == len(target_names)
    summary.update(preserved_999_entry_count=len(original_files), all_999_payloads_byte_identical=True,
                   new_998_material_count=len(selected_materials), all_998_material_count=len(new_materials), new_998_texture_count=len(textures),
                   maximum_four_weight_loss=max(v[2] for v in expected.values()),
                   triangle_coverage_exact=True,
                   package_files={str(p.relative_to(pkg)): p.stat().st_size for p in sorted(pkg.rglob('*.dcx'))},
                   source_texture_content_checked=True)
    if check_preview:
        verify_preview(out, summary, legend)
    save(out/'readback-verification.json', summary)
    for part in ('am', 'bd'):
        geometry['parts'][part]['tpf_textures'] = sum(t.startswith(part.upper()+'_M_0998_') for t in textures)
    save(out/'pov-mesh-summary.json', geometry)
    print(f'PASS T011 readback: 8 FLVERs; Z-mirrored Cast positions/normals/tangents, negated tangent W, source-order indices; carrier names/quantized weights; '
          f'enabled nodes/local bounds; {len(original_files)} original 999 MATBINs byte-identical; '
          f'{len(selected_materials)} selected 998 MATBINs; all input entries preserved except recorded replacements', flush=True)
    return summary


def verify_preview(out, summary, legend='fuse'):
    preview = read(out/'preview-verification.json')
    assert preview['display_space'] == 'ER geometry un-mirrored into Apex space for display'
    assert preview['max_er_unmirror_skin_error_m'] < 1e-12
    assert preview['gun_forward_camera'][2] > .9
    assert all(v > 0 for v in preview['renders']['idle_frame0']['rasterized_pixels'].values())
    if legend == 'octane':
        assert preview['carrier_mesh_source'] == 'serialized 998 FLVER readback'
        assert preview['carrier_pack']['legend'] == legend
        assert preview['carrier_pack']['only_inverse_mesh_binds_changed']
    summary['preview_reference'] = preview['restored_note']
    summary['preview_idle_mode'] = preview['idle_mode']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legend', choices=('fuse', 'octane'), default='fuse')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    verify(args.out, args.legend)
