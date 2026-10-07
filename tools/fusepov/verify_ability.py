"""T020 independent quantized FLVER, source geometry, texture and material readback."""
import argparse
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import numpy as np
from PIL import Image
from common import ROOT, PARTS, MODELS, TOOL, EXTRACT, read, save, run, unit, tangent_basis, winding
from mesh_ability import ac, mapping, sources, texture_sources
from pov_textures import texture_arrays
from verify_pov import stream, source_expected, quantize_weights
from verify_fuse import read_json_command
from verify_armor_bounds import verify as verify_bounds
from s3a_roundtrip import arrays
from material_bundle import verify_material


def verify_preview(out):
    report = read(out/'ability-preview-verification.json')
    ac.require(len(report['previews']) == 11, 'Expected 11 specified previews')
    ac.require(report['max_er_apex_skin_error_m'] < 1e-12, 'ER/Apex skin differs')
    ac.require(report['idle_t016_geometry_equal'], 'idle_0 geometry differs from T016')
    ac.require(report['idle_t016_pixels_equal'], 'idle_0 pixels differ from T016')
    ac.require(report['binary_clip_weights_unchanged'] and len(report['diagnostic_previews']) == 2, 'Preview layer/holding evidence missing')
    for p in report['previews']+report['diagnostic_previews']:
        path = out/'preview'/p['file']
        ac.require(path.is_file() and Image.open(path).size == (1120, 840), f'Preview missing: {path}')
        ac.require(sum(p['rasterized_pixels'].values()) > 0, f'Empty preview: {path}')
    for p in report['previews']+report['diagnostic_previews']:
        if 'finger_distances' in p:
            ac.require(p['finger_distances']['right_rifle']['minimum_m'] < .001, 'Right hand no longer holds the one-handed rifle')
    diagnostic = report['diagnostic_previews'][0]
    ac.require(diagnostic['finger_distances']['left_prop']['minimum_m'] < .001, 'Pad pre-release frame does not establish left grip')
    return dict(count=11, before_release_diagnostics=2, idle_t016_geometry_equal=True, idle_t016_pixels_equal=True,
                max_er_apex_skin_error_m=report['max_er_apex_skin_error_m'],
                visual_limits=report['limitations'])


def ancestors(nodes, i):
    out = []
    while nodes[i]['ParentIndex'] >= 0:
        i = nodes[i]['ParentIndex']
        out.append(i)
    return out


def verify_live_nodes(dump, packed, part):
    live = ac.live_skeleton()
    names = [b['name'] for b in live['bones']]
    live_by_name = {b['name']: b for b in live['bones']}
    nodes = dump['Nodes']
    # 2026-10-05 rework: the template's own nodes all stay (vanilla names, live or not; mesh nodes),
    # the 20 Xtra bones come after them; every mesh points at a mesh node; the skeleton set has one
    # entry per node (BaseSkeleton mirrors the nodes, AllSkeletons is a permutation with the Xtra
    # bones under their live parents)
    vanilla = read(ROOT/f'er-data/json/parts/{part.upper()}_M_{MODELS[part]}.json')['Nodes']
    # as in vanilla parts: the enabled bones first (the template's, then the 20 Xtra), then the
    # mesh nodes, then the disabled ones
    bones = next(i for i, n in enumerate(vanilla) if n['Flags'] != 'Bone')
    order = [n['Name'] for n in vanilla[:bones]] + list(ac.XTRA_NAMES) + [n['Name'] for n in vanilla[bones:]]
    ac.require(sorted(order[bones:bones + 20]) == sorted(ac.XTRA_NAMES), f'{part}: Xtra names')
    ac.require([n['Name'] for n in nodes[:bones]] == order[:bones] and sorted(n['Name'] for n in nodes[bones:bones + 20]) == sorted(ac.XTRA_NAMES)
               and [n['Name'] for n in nodes[bones + 20:]] == order[bones + 20:], f'{part}: node order is not template bones, Xtra, rest')
    first_other = next(i for i, n in enumerate(nodes) if n['Flags'] != 'Bone')
    ac.require(first_other == bones + 20 and all(n['Flags'] != 'Bone' for n in nodes[first_other:]), f'{part}: enabled bones are not a prefix')
    ac.require(all(m['NodeIndex'] >= 0 and 'Mesh' in nodes[m['NodeIndex']]['Flags'] for m in dump['Meshes']), f'{part}: mesh without a mesh node')
    skel = dump['Skeletons']
    base, every = skel['BaseSkeleton'], skel['AllSkeletons']
    ac.require(len(base) == len(nodes) and len(every) == len(nodes), f'{part}: skeleton set size differs from the nodes')
    for i, (b, n) in enumerate(zip(base, nodes)):
        ac.require(b['NodeIndex'] == i and b['ParentIndex'] == n['ParentIndex'] and b['FirstChildIndex'] == n['FirstChildIndex']
                   and b['NextSiblingIndex'] == n['NextSiblingIndex'] and b['PreviousSiblingIndex'] == n['PreviousSiblingIndex'], f'{part}: BaseSkeleton differs from node {i}')
    ac.require(sorted(b['NodeIndex'] for b in every) == list(range(len(nodes))), f'{part}: AllSkeletons is not a permutation of the nodes')
    entry_of = {b['NodeIndex']: i for i, b in enumerate(every)}
    for name in ac.XTRA_NAMES:
        e = every[entry_of[[n['Name'] for n in nodes].index(name)]]
        ac.require(every[e['ParentIndex']]['NodeIndex'] == [n['Name'] for n in nodes].index(names[live_by_name[name]['parent']]), f'{part}: AllSkeletons parent of {name} is not its live parent')
    node_index = {n['Name']: i for i, n in enumerate(nodes)}
    worlds = {}
    def visit(i):
        if i not in worlds:
            n = nodes[i]
            local = ac.bp.trs(n['Translation'], n['RotationQuaternion'], n['Scale'])
            worlds[i] = visit(n['ParentIndex'])@local if n['ParentIndex'] >= 0 else local
        return worlds[i]
    live_worlds = []
    for bone in live['bones']:
        ref = bone['ref']
        local = ac.bp.trs(ref['t'], ref['r'], ref['s'])
        live_worlds.append(live_worlds[bone['parent']]@local if bone['parent'] >= 0 else local)
    local_error = world_error = carrier_error = 0.
    for name in ac.XTRA_NAMES:
        ac.require(name in node_index, f'Added Xtra absent: {part}/{name}')
        node = nodes[node_index[name]]; bone = live_by_name[name]; ref = bone['ref']
        ac.require('Bone' in node['Flags'] and 'Disabled' not in node['Flags'], 'Added Xtra disabled')
        # a chain top (live parent Master) is a root with its model-space bind, as vanilla parts'
        # top used bones are; the rest keep their live parent and local reference
        if names[bone['parent']].startswith('Xtra_Multipurpose_Bone'):
            ac.require(nodes[node['ParentIndex']]['Name'] == names[bone['parent']], 'Xtra parent differs from live')
            expected = ac.bp.trs(ref['t'], ref['r'], ref['s'])
        else:
            ac.require(node['ParentIndex'] == -1, 'Xtra chain top is not a root')
            expected = live_worlds[bone['i']]
        ac.require(all('Disabled' not in nodes[j]['Flags'] for j in ancestors(nodes, node_index[name])), 'Xtra under a disabled node')
        actual = ac.bp.trs(node['Translation'], node['RotationQuaternion'], node['Scale'])
        local_error = max(local_error, float(abs(actual-expected).max()))
        world_error = max(world_error, float(abs(visit(node_index[name])-live_worlds[bone['i']]).max()))
    for c in packed['carrier_records'][51:]:
        if c['group'] != (2 if part == 'hd' else 3):
            continue
        expected = ac.bp.rigid(visit(node_index[c['name']]), c['name'])
        actual = ac.bp.trs(c['er_bind'][:3], c['er_bind'][3:])
        carrier_error = max(carrier_error, float(abs(actual-ac.bp.trs(expected[:3], expected[3:])).max()))
    ac.require(local_error < 2e-6 and world_error < 6e-6 and carrier_error < 2e-6, 'Xtra local/world/pack binding differs')
    return dict(template_nodes_kept=True, meshes_on_mesh_nodes=True, skeleton_set_rebuilt=True, enabled_xtra_nodes=20,
                xtra_chain_tops_are_roots=True, no_disabled_xtra_ancestors=True,
                local_reference_matrix_error=local_error, world_reference_matrix_error=world_error,
                packed_er_bind_matrix_error=carrier_error)


def verify(out=None, check_preview=True):
    out = ac.checked(out or ac.MODEL_ROOT, ac.MODEL_ROOT, create=False)
    pkg, rb = out/'package', out/'readback'
    report = dict(status='PASS', parts={}, base_parts_byte_identical=[], source_textures_exact=True)
    ac.require(len(list(pkg.rglob('*.dcx'))) == 9, 'Expected 8 parts and one material bundle')
    for part in ('am', 'bd'):
        for lod in ('', '_l'):
            name = f'{part}_m_0998{lod}.partsbnd.dcx'
            ac.require((pkg/'parts'/name).read_bytes() == (ac.BASE_MODEL/'package/parts'/name).read_bytes(), f'Original part changed: {name}')
            report['base_parts_byte_identical'].append(name)
    for name, paths in texture_sources().items():
        col, normal, metal = texture_arrays(paths)
        for suffix, expected in [('a', col), ('n', normal), ('m', np.rint(metal*255).astype(np.uint8))]:
            ac.require(np.array_equal(np.asarray(Image.open(out/'textures'/f'{name}_{suffix}.png')), expected), f'Texture pixels differ: {name}/{suffix}')
    neutral = int(np.rint((1.055*(1/4.55)**(1/2.4)-.055)*255))
    for suffix, color in [('a', [neutral, neutral, neutral, 255]), ('n', [128, 128, 128, 255]), ('m', [0, 0, 0, 255])]:
        ac.require(np.array_equal(np.asarray(Image.open(out/'textures'/f'neutral_{suffix}.png')), np.tile(color, (8, 8, 1)).astype(np.uint8)), 'Neutral texture changed')
    snapshot = out/'inputs/material/allmaterial.matbinbnd.dcx'
    input_audit = read(out/'inputs/source-material.json')
    ac.require(snapshot.read_bytes() == Path(input_audit['source']).read_bytes(), 'Input material snapshot differs')
    bundle = verify_material(out, snapshot)
    report['material_bundle'] = {k: bundle[k] for k in ('original_entries', 'output_entries', 'replaced_entries', 'added_entries', 'header_unchanged', 'original_entry_order_ids_names_flags_unchanged')}
    report['preserved_material_entries'] = len(bundle['preserved_entries'])
    run([EXTRACT, 'unpack', pkg/'material/allmaterial.matbinbnd.dcx', '--out', rb/'material_0998', '--filter', '_M_0998'], out, 'ability_materials')
    materials = {p.stem: p for p in (rb/'material_0998').rglob('*.matbin')}
    mapped, layout_data = mapping()
    packed = ac.read_pack(out/'inputs/fuse_pov.anim')
    live_names = {b['name'] for b in ac.live_skeleton()['bones']}
    ac.require(all(c['name'] in live_names for c in packed['carrier_records']), 'Pack carrier missing from live skeleton')
    ac.require(all(c['name'] in ac.XTRA_NAMES and not ac.forbidden_prop_carrier(c['name']) for c in packed['carrier_records'][51:]), 'Forbidden main-body prop carrier')
    expected_pack, expected_sequences, expected_audit = __import__('bake_ability').generate()
    ac.require(packed['version'] == 2 and len(packed['bones']) == len(expected_pack['bones']), 'Preview pack format differs')
    ac.require(len(packed['carrier_records']) == len(expected_pack['carrier_records']), 'Preview carrier count differs')
    for c, expected in zip(packed['carrier_records'], expected_pack['carrier_records']):
        ac.require(c['name'] == expected['name'] and c['owner'] == expected['owner'] and c['group'] == expected['group'], 'Preview pack carrier differs')
        for field in ('inverse_mesh_bind', 'er_bind'):
            ac.require(np.array_equal(c[field], np.asarray(expected[field], '<f4')), f'Preview carrier {field} differs')
    for a, b in zip(packed['bones'], expected_pack['bones']):
        ac.require(a['name'] == b['name'] and a['parent'] == b['parent'] and np.array_equal(a['rest'], np.asarray(b['rest'], '<f4')), 'Preview bone differs')
    ac.require(list(packed['clips']) == list(expected_pack['clips']), 'Preview clip inventory differs')
    for name, a in packed['clips'].items():
        b = expected_pack['clips'][name]
        ac.require(all(a[k] == b[k] for k in ('fps', 'frames', 'loop', 'additive')), f'Preview clip metadata differs: {name}')
        ac.require(a['weights'].tobytes() == b['weights'].astype('<f4').tobytes() and a['poses'].tobytes() == b['poses'].astype('<f4').tobytes(), f'Preview Cast/QC values differ: {name}')
    sequence_path = out/'inputs/ability_sequences.json'
    if sequence_path.is_file():
        ac.require(read(sequence_path) == expected_sequences, 'Preview sequence/QC events differ')
    local_sources = {m.Name(): (key, mdl, m) for key, mdl, m in sources()}
    carriers = {c['carrier']: c for c in mapped['carriers']}
    targets = read(out/'inputs/material-targets.json')
    ac.require(set(targets).issubset(materials), 'Prop MATBIN missing')
    for part in PARTS:
        if part in ('am', 'bd'):
            # The exact existing packages are exported again for previews.
            run([TOOL, 'export-mesh', pkg/f'parts/{part}_m_0998.partsbnd.dcx', '--matbin-bnd', pkg/'material/allmaterial.matbinbnd.dcx', '--out', rb/f'export_{part}'], out, 'ability_export_'+part)
            continue
        infolder = out/'fusemesh'/part
        doc = read(infolder/'mesh.json')
        for material in doc['materials']:
            ac.require(material == __import__('textures').material_definition(ROOT, part, material['name']), 'Material definition differs from T011')
        for lod in ('', '_l'):
            path = pkg/f'parts/{part}_m_0998{lod}.partsbnd.dcx'
            ac.require(path.read_bytes()[0x28:0x2c] == b'KRAK', 'Wrong output DCX encoding')
            run([EXTRACT, 'unpack', path, '--out', rb/path.stem], out, 'ability_unpack_'+part+lod)
            flver = next((rb/path.stem).rglob('*.flver'))
            dump = read_json_command(run, [TOOL, 'flver', flver, '--samples', '0'], out, 'ability_flver_'+part+lod)
            folder = rb/f'export_{part}{lod}'
            save(folder/'flver.json', dump)
            run([TOOL, 'export-mesh', path, '--matbin-bnd', pkg/'material/allmaterial.matbinbnd.dcx', '--out', folder], out, 'ability_export_'+part+lod)
            actual = read(folder/'mesh.json')
            ac.require(len(doc['submeshes']) == len(actual['submeshes']), 'Prop mesh count differs')
            template_path = out/f'inputs/template-audit/{part}{lod}.json'
            template = read(template_path) if template_path.is_file() else read(ROOT/f'er-data/json/parts/{part.upper()}_M_{MODELS[part]}{lod.upper()}.json')
            ac.require(len(template['Nodes']) == len(dump['Nodes']), 'Template node count differs')
            for old, node in zip(template['Nodes'], dump['Nodes']):
                for field in ('Name', 'ParentIndex', 'Flags', 'Translation', 'RotationQuaternion', 'Scale'):
                    ac.require(old[field] == node[field], f'Template node changed: {part}/{node["Name"]}/{field}')
            total_vertices, total_faces = 0, 0
            stats = dict(along=0, against=0, degenerate=0, orthogonal=0)
            maximum_error = 0.
            for source_sub, actual_sub in zip(doc['submeshes'], actual['submeshes']):
                key, mdl, mesh = local_sources[source_sub['name']]
                ac.require(ac.CONFIGS[key]['part'] == part, 'Prop in wrong part')
                count = mesh.VertexCount()
                vids = np.fromfile(infolder/source_sub['source_vertex_ids'], '<u4')
                tids = np.fromfile(infolder/source_sub['source_triangle_ids'], '<u4')
                ac.require(np.array_equal(vids, np.arange(count)) and np.array_equal(tids, np.arange(len(mesh.FaceBuffer())//3)), 'Source coverage differs')
                p = np.asarray(mesh.VertexPositionBuffer(), float).reshape(-1, 3)
                n = unit(np.asarray(mesh.VertexNormalBuffer(), float).reshape(-1, 3))
                uv = np.asarray(mesh.VertexUVLayerBuffer(0), float).reshape(-1, 2)
                second_uv = mesh.VertexUVLayerBuffer(1)
                uv1 = np.asarray(second_uv, float).reshape(-1, 2) if second_uv is not None else uv.copy()
                faces = np.asarray(mesh.FaceBuffer()).reshape(-1, 3)
                _, tangent, sign, _ = tangent_basis(p, n, uv, faces)
                expected_streams = dict(positions=(p*[.0254, .0254, -.0254]).astype('<f4'),
                    normals=unit(np.asarray(mesh.VertexNormalBuffer(), float).reshape(-1, 3)*[1, 1, -1]).astype('<f4'),
                    tangents=np.c_[unit(tangent*[1, 1, -1]), -sign].astype('<f4'), uv0=uv.astype('<f4'), uv1=uv1.astype('<f4'), indices=faces.astype('<u4'))
                for name, value in expected_streams.items():
                    ac.require(np.array_equal(stream(infolder, source_sub, name), value), f'Source stream differs: {mesh.Name()}/{name}')
                    actual_values = stream(folder, actual_sub, name)
                    if name in ('positions', 'indices'):
                        ac.require(np.array_equal(actual_values, value), f'FLVER exact stream differs: {mesh.Name()}/{name}')
                    else:
                        tolerance = 1/127 if name in ('normals', 'tangents') else 1/2048
                        ac.require(np.max(abs(actual_values-value)) <= tolerance+1e-6, f'FLVER encoded stream differs: {mesh.Name()}/{name}')
                expected_names, weights, loss = source_expected(mdl, mesh, mapped)
                stored_names = np.asarray(doc['bones'])[stream(infolder, source_sub, 'bone_indices')]
                actual_names = np.asarray(actual['bones'])[stream(folder, actual_sub, 'bone_indices')]
                ac.require(np.array_equal(expected_names, stored_names) and np.array_equal(expected_names, actual_names), 'Carrier bone names differ')
                weight32 = weights.astype('<f4')
                ac.require(np.array_equal(stream(infolder, source_sub, 'bone_weights'), weight32), 'Merged source weights differ')
                actual_weights = stream(folder, actual_sub, 'flver_bone_weights')
                ac.require(np.array_equal(np.rint(actual_weights*255).astype(int), quantize_weights(weight32)), 'Quantized weights differ')
                maximum_error = max(maximum_error, float(abs(actual_weights-weight32).max()))
                for name in actual_names[actual_weights > 0]:
                    node = next(n for n in dump['Nodes'] if n['Name'] == name)
                    ac.require('Bone' in node['Flags'] and 'Disabled' not in node['Flags'] and part in carriers[name]['parts'], 'Weighted node disabled')
                ac.require(len(actual_sub['face_sets']) == 6, 'Expected six face sets')
                for face in actual_sub['face_sets']:
                    ac.require((folder/face['indices']).read_bytes() == (infolder/source_sub['indices']).read_bytes(), 'Face-set index order changed')
                for name, value in winding(expected_streams['positions'], stream(folder, actual_sub, 'normals'), faces).items():
                    stats[name] += value
                total_vertices += count; total_faces += len(faces)
            verify_bounds(dump, actual, folder, arrays)
            live_check = verify_live_nodes(dump, packed, part)
            report['parts'][part+lod] = dict(meshes=len(doc['submeshes']), vertices=total_vertices, triangles=total_faces,
                source_positions_exact=True, normals_tangents_and_uv_encoding_checked=True, indices_source_order=True,
                weights_quantization_exact=True, template_nodes_exact=True, weighted_nodes_enabled=True,
                bounds='PASS independent T003 node-local reconstruction', max_weight_quantization_error=maximum_error, winding=stats,
                live_skeleton=live_check)
        dds_files = {p.stem for p in (rb/f'export_{part}').glob('*.dds')}
        for material in doc['materials']:
            name = f'P[{part.upper()}_M_0998]_'+material['name']
            matbin = read_json_command(run, [TOOL, 'matbin', materials[name]], out, 'ability_matbin_'+material['name'])['Data']
            params = {p['Name']: p['Value'] for p in matbin['Params']}
            ac.require(all(params[k] == v for k, v in material['float_params'].items()), 'Material parameter differs')
            for sampler in matbin['Samplers']:
                tex = sampler['Path'].replace('\\', '/').split('/')[-1].removesuffix('.tif')
                if '_M_0998_' in tex:
                    ac.require(tex in dds_files, f'MATBIN/TPF texture missing: {tex}')
            for typ in material['sampler_textures']:
                path = next(s['Path'] for s in matbin['Samplers'] if s['Type'] == typ)
                ac.require('_M_0998_' in path and 'AAT' not in path, 'Detail sampler not overridden')
        for material in read(rb/f'export_{part}/flver.json')['Materials']:
            name = material['MTD'].replace('\\', '/').split('/')[-1].removesuffix('.matxml')
            ac.require(name in materials, f'FLVER MATBIN missing: {name}')
    report.update(prop_owners_all_new=all(c['owner'] >= 102 for c in layout_data['new_carriers']),
                  no_main_body_prop_carriers=True, material_references_present=True, all_69_pack_carriers_in_live_skeleton=True)
    if check_preview:
        report['previews'] = verify_preview(out)
    save(out/'ability-readback-verification.json', report)
    print(f'PASS T020 readback: AM/BD 4 files byte-identical; HD/LG 4 FLVERs source geometry/weights/bounds/materials/textures; '
          f'{bundle["original_entries"]} input material entries checked', flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    verify(parser.parse_args().out)
