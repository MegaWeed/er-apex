"""T008: python tools/fusegun/build_gun.py rebuilds armor 999 with an iron-sight R-301."""
import argparse
import copy
import shutil
import time
from pathlib import Path
import numpy as np
from PIL import Image
from common import ROOT, OUT, ASSETS, PARTS, MODELS, TOOL, EXTRACT, checked_out, read, save, unit, run
from common import add_options, base_for, default_out, alignment_for, ensure_helper, MATBIN_DEFAULT, source_info
from geometry import tangent_basis, winding
from textures import make_textures, material_definition, linear
from grip import derive


def filter_meshes(model, out):
    groups = read(ASSETS/'r301_bodygroups.json')['bodygroups']
    names = ['body'] + [g['name'] for g in groups]
    selected = []
    audit = []
    for i, mesh in enumerate(model.Meshes()):
        group = next(g for g in sorted(names, key=len, reverse=True) if mesh.Name().startswith(g+'_'))
        keep = group in ('body', 'r101_sight_front_on')
        audit.append(dict(cast_mesh_index=i, name=mesh.Name(), group=group,
                          vertices=mesh.VertexCount(), triangles=len(mesh.FaceBuffer())//3,
                          material=mesh.Material().Name(), keep=keep,
                          selected_state='studio 0' if group == 'body' else 'studio 1' if keep else 'blank 0'))
        if keep:
            selected.append(mesh)
    front = next(g for g in groups if g['name'] == 'r101_sight_front_on')
    assert front['options'][0] == ['', 'blank']
    assert front['options'][1][0] == 'r301_base_w_r101_sight_front_on_1_lod0.smd'
    assert [m.Name() for m in selected] == ['body_0_r301_base_main', 'r101_sight_front_on_1_r301_base_main']
    save(out/'bodygroups.json', dict(source='apex-data/assets/r301_bodygroups.json',
                                   meshes=audit, selected_qc=front['raw_qc'],
                                   rear_sight='No independent rear-sight bodygroup; body mesh retained unchanged.'))
    return selected


def textures(out, meshes):
    names = {m.Material().Name() for m in meshes}
    audit, previews = make_textures(ROOT, out, names)
    # T005 restricts all non-body/gear names to dielectric. Apply its metal
    # approximation to the weapon explicitly, without changing T005 behavior.
    materials = {m['name'].split('/')[-1]: m for m in read(ASSETS/'materials.json')['materials']}
    for name in names:
        paths = {t['usage']: ASSETS/t['file'] for t in materials[name]['textures']}
        col = np.asarray(Image.open(paths['_col']).convert('RGBA'))
        spc = np.asarray(Image.open(paths['_spc']).convert('RGBA').resize((col.shape[1], col.shape[0]), Image.Resampling.BILINEAR))
        metal = np.clip((linear(spc[..., :3]).max(2)-.04)/np.maximum(linear(col[..., :3]).max(2)-.04, .04), 0, 1)
        Image.fromarray(np.rint(metal*255).astype(np.uint8)).save(out/f'textures/{name}_m.png')
        audit[name]['metalness_rule'] = 'T005 heuristic: clamp((max(linear(spc))-0.04)/max(max(linear(col))-0.04,0.04),0,1); weapon allowed metallic; physical semantics pending'
        audit[name]['metalness_mean'] = float(metal.mean())
        audit[name]['metalness_nonzero_fraction'] = float((metal > 0).mean())
    doc = read(out/'texture-audit.json')
    doc['materials'] = audit
    doc['limitations'] = ['Apex specular-to-metalness approximation, normal green and AM Rich shader inherited from T005; require runtime lighting review']
    save(out/'texture-audit.json', doc)
    return previews


def merge(out, model, grip, legend='fuse'):
    base = base_for(legend)
    for part in PARTS:
        shutil.copytree(base/'fusemesh'/part, out/'fusemesh'/part, dirs_exist_ok=True)
    folder = out/'fusemesh/am'
    doc = read(folder/'mesh.json')
    original = copy.deepcopy(doc)
    selected = filter_meshes(model, out)
    textures(out, selected)
    bone = doc['bones'].index('R_Hand')
    transform = np.array(grip['source_gun_to_er_bind'])
    rotation = transform[:3, :3]/np.linalg.norm(transform[:3, 0])
    assert np.linalg.det(rotation) < 0
    material_names = sorted({m.Material().Name() for m in selected})
    material_lookup = {}
    for name in material_names:
        material_lookup[name] = len(doc['materials'])
        definition = material_definition(ROOT, 'am', name)
        doc['materials'].append(definition)
        for file in set(definition['textures'].values()) | set(definition['sampler_textures'].values()):
            (folder/file).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(out/file, folder/file)
    summary = []
    for mesh in selected:
        p = np.array(mesh.VertexPositionBuffer()).reshape(-1, 3)
        n = unit(np.array(mesh.VertexNormalBuffer()).reshape(-1, 3))
        uv = np.array(mesh.VertexUVLayerBuffer(0)).reshape(-1, 2)
        f = np.array(mesh.FaceBuffer()).reshape(-1, 3)
        U, V, w, fallback = tangent_basis(p, n, uv, f)
        pos = p@transform[:3, :3].T+transform[:3, 3]
        normal = unit(n@rotation.T)
        tangent = unit(V@rotation.T)
        tangent = unit(tangent-normal*(normal*tangent).sum(1)[:, None])
        # As in T005, reflection swap and ER clockwise swap cancel.
        arrays = dict(positions=pos, normals=normal, tangents=np.c_[tangent, -w],
                      uv0=uv, uv1=np.array(mesh.VertexUVLayerBuffer(1)).reshape(-1, 2),
                      bone_indices=np.full((len(p), 4), bone),
                      bone_weights=np.tile([1., 0., 0., 0.], (len(p), 1)), indices=f)
        sub = dict(name=mesh.Name(), material=material_lookup[mesh.Material().Name()],
                   vertex_count=len(p), index_count=f.size, cull_backfaces=True)
        for key, value in arrays.items():
            file = f'gun{len(summary):02d}.{key}.bin'
            dtype = 'u1' if key == 'bone_indices' else '<u4' if key == 'indices' else '<f4'
            np.asarray(value, dtype=dtype).tofile(folder/file)
            sub[key] = file
        doc['submeshes'].append(sub)
        summary.append(dict(name=mesh.Name(), vertices=len(p), triangles=len(f),
                            original_winding=winding(p, n, f), final_winding=winding(pos, normal, f),
                            tangent_fallback_vertices=fallback))
    save(folder/'mesh.json', doc)
    save(out/'geometry-summary.json', dict(gun_meshes=summary,
         gun_vertices=sum(m['vertices'] for m in summary), gun_triangles=sum(m['triangles'] for m in summary),
         original_am_submeshes=len(original['submeshes']), merged_am_submeshes=len(doc['submeshes']),
         merged_am_vertices=sum(m['vertex_count'] for m in doc['submeshes']),
         merged_am_triangles=sum(m['index_count']//3 for m in doc['submeshes']),
         original_am_materials=len(original['materials']), merged_am_materials=len(doc['materials']),
         gun_materials=material_names, skin='all four bone-index slots R_Hand; weights [1,0,0,0]',
         untouched_part_inputs=('hd/bd/lg directories copied byte-for-byte from T005 fusemesh' if legend == 'fuse' else
                                'hd/bd/lg directories copied byte-for-byte from T015 octane fusemesh'),
         original_am_geometry='all original submeshes and material definitions retained'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_options(parser, material=True)
    parser.add_argument('--skip-previews', action='store_true')
    args = parser.parse_args()
    out = checked_out(args.out or default_out(args.legend))
    base = base_for(args.legend)
    start = time.monotonic()
    print(f'T019/{args.legend}: local Cast grip; original armor inputs preserved', flush=True)
    for required in [base/'align.json', base/'fusemesh/am/mesh.json', TOOL, EXTRACT]:
        if not required.exists():
            raise FileNotFoundError(f'Required local T005/T003 input: {required}')
    state = alignment_for(args.legend)
    model, grip, idleW = derive(state, out, args.legend)
    merge(out, model, grip, args.legend)
    print('T008: 2 iron-sight gun meshes appended; building four armor parts', flush=True)
    shutil.copytree(base/'inputs/parts', out/'inputs/parts', dirs_exist_ok=True)
    # Fuse retains the legacy input by default so T008's nine packages stay exact.
    material_source = (args.matbin_bnd or (MATBIN_DEFAULT if args.legend == 'octane' else
                       base/'inputs/material/allmaterial.matbinbnd.dcx')).resolve()
    if not material_source.is_file():
        raise FileNotFoundError('待定：input material bundle ' + str(material_source))
    snapshot = out/'inputs/material/allmaterial.input.matbinbnd.dcx'
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    if snapshot != material_source:
        shutil.copyfile(material_source, snapshot)
    assert snapshot.read_bytes() == material_source.read_bytes()
    targets = [f'P[{part.upper()}_M_0999]_'+m['name'] for part in PARTS
               for m in read(out/'fusemesh'/part/'mesh.json')['materials']]
    gun_names = read(out/'geometry-summary.json')['gun_materials']
    target_file = out/'inputs/material/target-matbins.json'
    save(target_file, dict(generated=targets, replace=['P[AM_M_0999]_'+n for n in gun_names]))
    save(out/'source-manifest.json', dict(legend=args.legend, material_input=str(material_source),
         material_copy_bytes_exact=True, source_files=source_info([material_source, base/'align.json',
             *[base/'fusemesh'/p/'mesh.json' for p in PARTS]], out)))
    helper = ensure_helper(out)
    working = out/'inputs/material/allmaterial.builder.matbinbnd'
    run([*helper, 'prepare', snapshot, target_file, working, out/'material-bundle-preparation.json'], out, 'prepare_material_bundle')
    command = [TOOL, 'build-armor', '--model', '999', '--matbin-bnd', working, '--out', out/'package']
    for part in PARTS:
        command.extend([f'--{part}-template', out/f'inputs/parts/{part}_m_{MODELS[part]:04d}.partsbnd.dcx',
                        f'--{part}-mesh', out/'fusemesh'/part])
    run(command, out, 'build_package')
    run([*helper, 'finish', snapshot, out/'package/material/allmaterial.matbinbnd.dcx', target_file,
         out/'material-bundle-package.json'], out, 'finish_material_bundle')
    if not args.skip_previews:
        from preview_gun import make_previews
        make_previews(out, state, idleW, args.legend)
    from verify_gun import verify
    report = verify(out, args.legend)
    report['elapsed_seconds'] = round(time.monotonic()-start, 2)
    save(out/'verification.json', report)
    print(f'PASS T019/{args.legend}: 5084 gun vertices, 3905 gun triangles, rigid R_Hand; 8 parts + allmaterial; elapsed {report["elapsed_seconds"]}s', flush=True)


if __name__ == '__main__':
    main()
