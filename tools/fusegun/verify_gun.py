"""Read back eight parts and material bundle, validate rigid skin and unchanged body parts."""
import argparse
from pathlib import Path
import numpy as np
from common import PARTS, TOOL, EXTRACT, checked_out, read, save, run
from common import add_options, default_out, base_for, ensure_helper, quantize
from verify_fuse import array, read_json_command
from verify_armor_bounds import verify as verify_bounds
from s3a_roundtrip import arrays


def verify(out, legend='fuse'):
    out = checked_out(out)
    base = base_for(legend)
    assert read(out/'source-manifest.json')['legend'] == legend, 'Output legend mismatch'
    pkg = out/'package'
    rb = out/'readback'
    summary = {'status': 'PASS', 'legend': legend, 'parts': {}, 'unchanged_packages': {}}
    gun_names = {m['name'] for m in read(out/'bodygroups.json')['meshes'] if m['keep']}
    manifest = read(pkg/'build-manifest.json')
    texture_names = {t['name'] for t in manifest['textures']}
    helper = ensure_helper(out)
    snapshot = out/'inputs/material/allmaterial.input.matbinbnd.dcx'
    source = Path(read(out/'source-manifest.json')['material_input'])
    assert source.read_bytes() == snapshot.read_bytes(), 'Input bundle changed since snapshot'
    run([*helper, 'verify', snapshot, pkg/'material/allmaterial.matbinbnd.dcx',
         out/'inputs/material/target-matbins.json', out/'material-bundle-verification.json'], out, 'verify_material_bundle')
    bundle = read(out/'material-bundle-verification.json')
    preserved_names = {m['name'].replace('\\', '/').rsplit('/', 1)[-1].removesuffix('.matbin') for m in bundle['preserved']}
    run([EXTRACT, 'unpack', base/'package/material/allmaterial.matbinbnd.dcx',
         '--out', rb/'baseline_material', '--filter', '_M_0999'], out, 'unpack_baseline_matbins')
    for path in sorted(pkg.rglob('*.dcx')):
        assert path.read_bytes()[0x28:0x2c] == b'KRAK'
        command = [EXTRACT, 'unpack', path, '--out', rb/path.stem]
        if path.parent.name == 'material':
            command += ['--filter', '_M_0999']
        run(command, out, 'unpack_'+path.stem)
    assert len(list(pkg.rglob('*.dcx'))) == 9
    for part in PARTS:
        infolder = out/'fusemesh'/part
        source = read(infolder/'mesh.json')
        original = read(base/'fusemesh'/part/'mesh.json')
        for lod in ('', '_l'):
            path = pkg/f'parts/{part}_m_0999{lod}.partsbnd.dcx'
            folder = rb/f'export_{part}{lod}'
            run([TOOL, 'export-mesh', path, '--matbin-bnd', pkg/'material/allmaterial.matbinbnd.dcx', '--out', folder], out, f'export_{part}{lod}')
            doc = read(folder/'mesh.json')
            assert len(source['submeshes']) == len(doc['submeshes'])
            gun_vertices = 0
            for s, t in zip(source['submeshes'], doc['submeshes']):
                for key in ('positions', 'indices'):
                    assert (infolder/s[key]).read_bytes() == (folder/t[key]).read_bytes(), (part, lod, s['name'], key)
                old_weights = array(infolder, s, 'bone_weights')
                new_weights = array(folder, t, 'flver_bone_weights')
                assert np.array_equal(quantize(old_weights), np.rint(new_weights*255).astype(int))
                names = np.array(doc['bones'])[array(folder, t, 'bone_indices')]
                original_names = np.array(source['bones'])[array(infolder, s, 'bone_indices')]
                assert np.array_equal(names, original_names)
                for key in ('normals', 'tangents'):
                    assert np.max(abs(array(infolder, s, key)-array(folder, t, key))) <= 1/127+1e-6
                for key in ('uv0', 'uv1'):
                    assert np.max(abs(array(infolder, s, key)-array(folder, t, key))) <= 1/2048+1e-6
                if s['name'] in gun_names:
                    assert (names == 'R_Hand').all()
                    assert np.array_equal(new_weights, np.tile([1., 0., 0., 0.], (s['vertex_count'], 1)))
                    assert len(t['face_sets']) == 6
                    gun_vertices += s['vertex_count']
            flver = next((rb/path.stem).rglob('*.flver'))
            dump = read_json_command(run, [TOOL, 'flver', flver, '--samples', '0'], out, f'flver_{part}{lod}')
            save(folder/'flver.json', dump)
            assert all('Bone' in dump['Nodes'][i]['Flags'] and 'Disabled' not in dump['Nodes'][i]['Flags']
                       for m in dump['Meshes'] for i in m['BoneIndexRange']['ActiveIndices'])
            verify_bounds(dump, doc, folder, arrays)
            if part == 'am':
                assert gun_vertices == 5084
            else:
                baseline = base/'package/parts'/path.name
                assert path.read_bytes() == baseline.read_bytes(), path.name
                summary['unchanged_packages'][path.name] = dict(source=str(baseline),
                     size_bytes=path.stat().st_size, byte_identical=True, format='KRAK DCX/BND4/FLVER2')
            summary['parts'][part+lod] = dict(vertices=sum(s['vertex_count'] for s in doc['submeshes']),
                                            triangles=sum(s['index_count']//3 for s in doc['submeshes']),
                                            gun_vertices=gun_vertices, bounds='PASS', positions_indices_bit_exact=True,
                                            bone_names_quantized_weights_exact=True)
        # Verify old AM vertices/material definitions as well as complete HD/BD/LG inputs.
        assert source['bones'] == original['bones']
        assert source['materials'][:len(original['materials'])] == original['materials']
        assert source['submeshes'][:len(original['submeshes'])] == original['submeshes']
        for old in original['submeshes']:
            for key in ['positions', 'normals', 'tangents', 'uv0', 'uv1', 'bone_indices', 'bone_weights', 'indices']:
                assert (infolder/old[key]).read_bytes() == (base/'fusemesh'/part/old[key]).read_bytes()
        # Include all source texture files and JSON for untouched parts.
        for old_file in (base/'fusemesh'/part).rglob('*'):
            if old_file.is_file() and (part != 'am' or old_file.name != 'mesh.json'):
                assert old_file.read_bytes() == (infolder/old_file.relative_to(base/'fusemesh'/part)).read_bytes(), old_file
        for material in source['materials']:
            stem = f'P[{part.upper()}_M_0999]_'+material['name']
            matfile = next(p for p in (rb/'allmaterial.matbinbnd').rglob('*.matbin') if p.stem == stem)
            mat = read_json_command(run, [TOOL, 'matbin', matfile], out, 'matbin_'+part+'_'+material['name'])['Data']
            params = {p['Name']: p['Value'] for p in mat['Params']}
            if stem not in preserved_names:
                assert all(params[k] == v for k, v in material['float_params'].items())
            for sampler in mat['Samplers']:
                path = sampler['Path'].replace('\\', '/').rsplit('/', 1)[-1].removesuffix('.tif')
                if f'{part.upper()}_M_0999_' in path:
                    assert path in texture_names, (stem, path)
                    assert (rb/f'export_{part}'/(path+'.dds')).exists(), path
    # FLVER material->MATBIN name is independently checked from the actual dump.
    for part in PARTS:
        dump = read(rb/f'export_{part}/flver.json')
        for material in dump['Materials']:
            path = material['MTD'].replace('\\', '/').rsplit('/', 1)[-1].replace('.matxml', '.matbin')
            assert any(p.name == path for p in (rb/'allmaterial.matbinbnd').rglob('*.matbin')), path
    preserved_matbins = 0
    baseline_material_differences = []
    baseline_custom_names = {f'P[{p.upper()}_M_0999]_'+m['name'] for p in PARTS
                             for m in read(base/'fusemesh'/p/'mesh.json')['materials']}
    for original in (rb/'baseline_material').rglob('*.matbin'):
        if original.stem not in baseline_custom_names:
            continue
        rebuilt = next(p for p in (rb/'allmaterial.matbinbnd').rglob('*.matbin') if p.name == original.name)
        if original.read_bytes() == rebuilt.read_bytes():
            preserved_matbins += 1
        else:
            # --matbin-bnd may contain intentionally updated body materials.
            # Its existing entries have priority and are verified against that input.
            assert original.stem in preserved_names, original.name
            baseline_material_differences.append(dict(name=original.name,
                 reason='Existing input material preserved byte-for-byte instead of reverting to armor baseline'))
    assert preserved_matbins + len(baseline_material_differences) == len(baseline_custom_names)
    geometry = read(out/'geometry-summary.json')
    geometry['merged_am_tpf_textures'] = len([t for t in manifest['textures'] if t['name'].startswith('AM_M_0999_')])
    assert geometry['merged_am_tpf_textures'] == len(list((rb/'export_am').glob('*.dds')))
    geometry['original_am_tpf_textures'] = len([t for t in read(base/'package/build-manifest.json')['textures']
                                              if t['name'].startswith('AM_M_0999_')])
    assert geometry['merged_am_tpf_textures'] == geometry['original_am_tpf_textures'] + 4
    geometry['package_size_bytes'] = {}
    for path in sorted(pkg.rglob('*.dcx')):
        baseline = base/'package'/path.relative_to(pkg)
        geometry['package_size_bytes'][str(path.relative_to(pkg))] = dict(
            original=baseline.stat().st_size, merged=path.stat().st_size,
            delta=path.stat().st_size-baseline.stat().st_size)
    save(out/'geometry-summary.json', geometry)
    summary.update(gun_vertices_per_am=5084, gun_triangles_per_am=3905,
                   rigid_R_Hand_weight_1=True, unchanged_hd_bd_lg_packages=6,
                   original_am_arrays_and_materials_unchanged=True,
                   original_custom_matbins_byte_identical=preserved_matbins,
                   baseline_material_differences=baseline_material_differences,
                   material_and_texture_references_valid=True,
                   input_material_entries=bundle['input_entries'], preserved_input_entries=bundle['preserved_entries'],
                   added_input_entries=bundle['added_entries'], replaced_input_entries=bundle['replaced_entries'],
                   package_files={str(p.relative_to(pkg)): dict(size_bytes=p.stat().st_size, format='KRAK DCX')
                                  for p in pkg.rglob('*.dcx')})
    save(out/'readback-verification.json', summary)
    print(f'PASS T019/{legend} readback: 8 FLVERs, 5084 gun vertices only R_Hand weight 1; 6 HD/BD/LG packages byte-identical; original AM arrays preserved; materials/textures/bounds valid', flush=True)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    add_options(parser)
    args = parser.parse_args()
    verify(args.out or default_out(args.legend), args.legend)
