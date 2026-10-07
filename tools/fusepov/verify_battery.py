"""T021 independent quantized FLVER, source geometry, texture and material readback."""
import argparse
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import numpy as np
from PIL import Image
from common import ROOT, PARTS, MODELS, TOOL, EXTRACT, read, save, run, unit, tangent_basis, winding
from mesh_battery import bc as ac, mapping, sources, texture_sources
sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify_ability import verify_live_nodes
from verify_battery_pack_bridge import verify_pack_input
from pov_textures import texture_arrays
from verify_pov import stream, source_expected, quantize_weights
from verify_fuse import read_json_command
from verify_armor_bounds import verify as verify_bounds
from s3a_roundtrip import arrays
from material_bundle import verify_material


def verify_preview(out):
    report = read(out/'battery-preview-verification.json')
    ac.require(len(report['previews']) == 8, 'Expected eight specified previews')
    ac.require(report['max_er_apex_skin_error_m'] < 1e-12, 'ER/Apex skin differs')
    ac.require(report['stim_t020_pixels_equal'] and report['idle_t020_pixels_equal'], 'T020 previews differ')
    for p in report['previews']:
        path = out/'preview'/p['file']
        ac.require(path.is_file() and Image.open(path).size == (1120,840), 'Preview missing')
        ac.require(sum(p['rasterized_pixels'].values()) > 0, 'Empty preview')
        ac.require(float(np.asarray(Image.open(path))[...,:3].std())>1., 'Constant preview pixels')
    for filename in ('stim_idle_0_frame0_ability.png','idle_0_frame0_groups01.png'):
        ac.require(np.array_equal(np.asarray(Image.open(out/'preview'/filename)),
                   np.asarray(Image.open(ac.BASE_MODEL/'preview'/filename))), 'Actual T020 preview pixels differ')
    for grip in report['grip_measurements']:
        ac.require(all(grip[side]['minimum_m']<.001 for side in ('l','r')), 'Battery hand proximity differs')
    return dict(count=8, stim_t020_pixels_equal=True,idle_t020_pixels_equal=True,
                max_er_apex_skin_error_m=report['max_er_apex_skin_error_m'],grip_measurements=report['grip_measurements'])



def verify_battery_er_binds(dump, pack):
    nodes=dump['Nodes']; index={n['Name']:i for i,n in enumerate(nodes)}; matrices={}
    def visit(i):
        if i not in matrices:
            n=nodes[i];local=ac.bp.trs(n['Translation'],n['RotationQuaternion'],n['Scale'])
            matrices[i]=visit(n['ParentIndex'])@local if n['ParentIndex']>=0 else local
        return matrices[i]
    for c in pack['carrier_records'][69:]:
        ac.require(c['name'] in index, 'Battery carrier absent in HD')
        expected=visit(index[c['name']]);actual=ac.bp.trs(c['er_bind'][:3],c['er_bind'][3:])
        ac.require(float(abs(expected-actual).max())<2e-6,'Battery ER bind differs from HD')


def compare_injector(out, folder, actual, dump, part, lod):
    oldfolder=ac.BASE_MODEL/'readback'/f'export_{part}{lod}'
    old=read(oldfolder/'mesh.json'); olddump=read(oldfolder/'flver.json')
    ac.require(actual['bones'][:len(old['bones'])] == old['bones'],'Old mesh bone list differs')
    for s,t in zip(old['submeshes'],actual['submeshes']):
        for k in ('name','material','vertex_count','index_count','cull_backfaces','source_model'):
            if k in s: ac.require(s[k]==t[k],f'Injector submesh field changed: {k}')
        for key in ('positions','normals','tangents','uv0','uv1','bone_indices','bone_weights','flver_bone_weights','indices'):
            ac.require((oldfolder/s[key]).read_bytes() == (folder/t[key]).read_bytes(), f'Injector FLVER stream changed: {key}')
        for a,b in zip(s['face_sets'],t['face_sets']):
            ac.require((oldfolder/a['indices']).read_bytes() == (folder/b['indices']).read_bytes(),'Injector face set changed')
    ac.require(dump['Materials'][:len(olddump['Materials'])]==olddump['Materials'],'Injector FLVER materials changed')
    for a,b in zip(olddump['Nodes'],dump['Nodes']):
        for k in ('Name','Flags','ParentIndex','FirstChildIndex','NextSiblingIndex','PreviousSiblingIndex','Translation','RotationQuaternion','Scale'):
            ac.require(a[k]==b[k],f'T020 HD node changed: {a["Name"]}/{k}')
    ac.require(dump['Skeletons']==olddump['Skeletons'],'T020 HD skeleton set changed')
    dds=list(oldfolder.glob('*.dds'))
    ac.require(len(dds)==14,'Expected fourteen T020 injector DDS entries')
    for source in dds:
        ac.require(source.read_bytes()==(folder/source.name).read_bytes(),'Injector TPF/DDS texture bytes changed')
    return dict(meshes=2,streams_byte_identical=True,materials_exact=True,nodes_and_skeleton_set_exact=True,dds_textures_byte_identical=14)

def verify(out=None, check_preview=True):
    out = ac.checked(out or ac.MODEL_ROOT, ac.MODEL_ROOT, create=False)
    pkg, rb = out/'package', out/'readback'
    report = dict(status='PASS', parts={}, base_parts_byte_identical=[], source_textures_exact=True)
    ac.require(len(list(pkg.rglob('*.dcx'))) == 9, 'Expected 8 parts and one material bundle')
    for lod in ('','_l'):
        name=f'hd_m_1280{lod}.partsbnd.dcx'
        ac.require((out/'inputs/live-templates'/name).read_bytes()==(ac.BASE_MODEL/'inputs/live-templates'/name).read_bytes(),
                   'T020 HD template bytes changed')
    for part in ('am', 'bd', 'lg'):
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
    ac.require(all(not e['payload_changed'] for e in bundle['replaced_entries'] if '_octane_injector' in e['name']),
               'Injector MATBIN payload changed')
    report['material_bundle'] = {k: bundle[k] for k in ('original_entries', 'output_entries', 'replaced_entries', 'added_entries', 'header_unchanged', 'original_entry_order_ids_names_flags_unchanged')}
    report['preserved_material_entries'] = len(bundle['preserved_entries'])
    run([EXTRACT, 'unpack', pkg/'material/allmaterial.matbinbnd.dcx', '--out', rb/'material_0998', '--filter', '_M_0998'], out, 'battery_materials')
    materials = {p.stem: p for p in (rb/'material_0998').rglob('*.matbin')}
    mapped, layout_data = mapping()
    packed = ac.read_pack(out/'inputs/fuse_pov.anim')
    live_names = {b['name'] for b in ac.live_skeleton()['bones']}
    ac.require(all(c['name'] in live_names for c in packed['carrier_records']), 'Pack carrier missing from live skeleton')
    ac.require(all(c['name'] in ac.XTRA_NAMES and not ac.forbidden_prop_carrier(c['name']) for c in packed['carrier_records'][69:]), 'Forbidden main-body prop carrier')
    report['pack'] = verify_pack_input(out)
    local_sources = {m.Name(): (key, mdl, m) for key, mdl, m in sources()}
    carriers = {c['carrier']: c for c in mapped['carriers']}
    targets = read(out/'inputs/material-targets.json')
    ac.require(set(targets).issubset(materials), 'Prop MATBIN missing')
    for part in PARTS:
        if part in ('am', 'bd', 'lg'):
            # The exact existing packages are exported again for previews.
            run([TOOL, 'export-mesh', pkg/f'parts/{part}_m_0998.partsbnd.dcx', '--matbin-bnd', pkg/'material/allmaterial.matbinbnd.dcx', '--out', rb/f'export_{part}'], out, 'battery_export_'+part)
            continue
        infolder = out/'fusemesh'/part
        doc = read(infolder/'mesh.json')
        for material in doc['materials']:
            ac.require(material == __import__('textures').material_definition(ROOT, part, material['name']), 'Material definition differs from T011')
        for lod in ('', '_l'):
            path = pkg/f'parts/{part}_m_0998{lod}.partsbnd.dcx'
            ac.require(path.read_bytes()[0x28:0x2c] == b'KRAK', 'Wrong output DCX encoding')
            run([EXTRACT, 'unpack', path, '--out', rb/path.stem], out, 'battery_unpack_'+part+lod)
            flver = next((rb/path.stem).rglob('*.flver'))
            dump = read_json_command(run, [TOOL, 'flver', flver, '--samples', '0'], out, 'battery_flver_'+part+lod)
            folder = rb/f'export_{part}{lod}'
            save(folder/'flver.json', dump)
            run([TOOL, 'export-mesh', path, '--matbin-bnd', pkg/'material/allmaterial.matbinbnd.dcx', '--out', folder], out, 'battery_export_'+part+lod)
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
            verify_battery_er_binds(dump, packed)
            injector_check = compare_injector(out, folder, actual, dump, part, lod)
            report['parts'][part+lod] = dict(meshes=len(doc['submeshes']), vertices=total_vertices, triangles=total_faces,
                source_positions_exact=True, normals_tangents_and_uv_encoding_checked=True, indices_source_order=True,
                weights_quantization_exact=True, template_nodes_exact=True, weighted_nodes_enabled=True,
                bounds='PASS independent T003 node-local reconstruction', max_weight_quantization_error=maximum_error, winding=stats,
                live_skeleton=live_check,injector=injector_check)
        dds_files = {p.stem for p in (rb/f'export_{part}').glob('*.dds')}
        for material in doc['materials']:
            name = f'P[{part.upper()}_M_0998]_'+material['name']
            matbin = read_json_command(run, [TOOL, 'matbin', materials[name]], out, 'battery_matbin_'+material['name'])['Data']
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
    report.update(prop_owners_all_new=all(c['owner'] >= 126 for c in layout_data['new_carriers']),
                  no_main_body_prop_carriers=True, material_references_present=True, all_71_pack_carriers_in_live_skeleton=True)
    if check_preview:
        report['previews'] = verify_preview(out)
    save(out/'battery-readback-verification.json', report)
    print(f'PASS T021 readback: AM/BD/LG 6 files byte-identical; HD 2 FLVERs source geometry/weights/bounds/materials/textures; '
          f'{bundle["original_entries"]} input material entries checked', flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    verify(parser.parse_args().out)
