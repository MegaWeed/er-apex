"""Cast -> carrier weights -> AM/BD triangle partition, without rest-pose alignment."""
import re
import shutil
import numpy as np
from common import (ROOT, GUN, GUN_QC, CARRIERS, SELECTED, model, legend_config,
                    read, save, unit, winding, tangent_basis, file_info, Q, MIRROR)
from textures import material_definition

STREAMS = dict(positions=('<f4', 3), normals=('<f4', 3), tangents=('<f4', 4),
               uv0=('<f4', 2), uv1=('<f4', 2), bone_indices=('u1', 4),
               bone_weights=('<f4', 4), indices=('<u4', 3))


def selection(out=None, legend='fuse'):
    config = legend_config(legend)
    models = {'arms': model(config['arms']), 'gun': model(GUN)}
    qc = GUN_QC.read_text(encoding='utf-8-sig')
    groups = {m[1]: m[2] for m in re.finditer(r'\$bodygroup "([^"]+)"\s*\{([^}]+)\}', qc)}
    for group, index in [('sight_front', 1), ('r101_magazine', 0)]:
        options = re.findall(r'\b(studio|blank)\b(?:\s+"([^"]+)")?', groups[group])
        if options[index] != ('studio', f'r301_base_v_{group}_{index}_lod0.smd'):
            raise ValueError(f'QC option differs from task selection: {group}: {options}')
    selected = []
    audit = []
    for kind, mdl in models.items():
        for mesh in mdl.Meshes():
            keep = mesh.Name() == config['arms_mesh'] if kind == 'arms' else mesh.Name() in SELECTED
            entry = dict(model=kind, name=mesh.Name(), keep=keep,
                              vertices=mesh.VertexCount(), triangles=len(mesh.FaceBuffer())//3,
                              material=mesh.Material().Name())
            if legend == 'octane' and kind == 'arms':
                p = np.asarray(mesh.VertexPositionBuffer()).reshape(-1, 3)
                bones = mdl.Skeleton().Bones()
                bi = np.asarray(mesh.VertexWeightBoneBuffer(), dtype=int)
                bw = np.asarray(mesh.VertexWeightValueBuffer())
                entry.update(weighted_bones=sorted({bones[i].Name() for i in bi[bw > 0]}),
                             bounding_box_cast=dict(min=p.min(0).tolist(), max=p.max(0).tolist(), units='Source inches'))
            audit.append(entry)
            if keep:
                selected.append((kind, mdl, mesh))
    if [m.Name() for k, mdl, m in selected if k == 'gun'] != list(SELECTED):
        raise ValueError('Unexpected selected gun Cast meshes')
    if len([m for k, mdl, m in selected if k == 'arms']) != 1:
        raise ValueError('Expected exactly the selected v_arms mesh')
    if out:
        save(out/'bodygroups.json', dict(source=str(GUN_QC.relative_to(ROOT)), meshes=audit,
             choices=dict(body=0, sight_front=1, r101_magazine=0, all_other_groups='blank 0'),
             qc_blocks={k: groups[k] for k in ('sight_front', 'r101_magazine')},
             default_note='QC lists studio 0 first (folded front sight); task explicitly selects raised studio 1.'))
    return selected


def merged_weights(mdl, mesh, mapping):
    bones = mdl.Skeleton().Bones()
    rows = mapping['carriers']
    by_owner = {c['owner']: i for i, c in enumerate(rows)}
    bw = np.asarray(mesh.VertexWeightValueBuffer(), dtype=float).reshape(mesh.VertexCount(), -1)
    bi = np.asarray(mesh.VertexWeightBoneBuffer(), dtype=int).reshape(bw.shape)
    if not np.isfinite(bw).all() or (bw < 0).any() or (bw.sum(1) <= 0).any():
        raise ValueError('Invalid source weights')
    raw_error = float(np.max(abs(bw.sum(1)-1)))
    bw /= bw.sum(1)[:, None]
    dense = np.zeros((len(bw), len(rows)))
    for k in range(bw.shape[1]):
        active = bw[:, k] > 0
        ids = np.flatnonzero(active)
        destinations = []
        for b in bi[active, k]:
            name = bones[b].Name()
            if name not in mapping['owner_of_bone'] or mapping['owner_of_bone'][name] is None:
                raise ValueError(f'Used Cast bone has no allowed owner: {name}')
            destinations.append(by_owner[mapping['owner_of_bone'][name]])
        dense[ids, destinations] += bw[active, k]
    order = np.argsort(-dense, axis=1, kind='stable')[:, :4]
    weights = np.take_along_axis(dense, order, axis=1)
    loss = 1-weights.sum(1)
    weights /= weights.sum(1)[:, None]
    # Zero slots repeat the first used bone; they must still be valid input indices.
    order[weights == 0] = np.broadcast_to(order[:, :1], order.shape)[weights == 0]
    return order, weights, np.maximum(loss, 0), raw_error


def assignment(faces, bi, bw, mapping):
    allowed = {p: np.array([p in c['parts'] for c in mapping['carriers']]) for p in ('am', 'bd')}
    losses = {p: np.sum(np.where(allowed[p][bi], 0, bw), axis=1) for p in allowed}
    valid = {p: np.all(losses[p][faces] == 0, axis=1) for p in allowed}
    labels = np.where(valid['am'], 'am', 'bd')
    ambiguous = ~(valid['am'] | valid['bd'])
    # Minimize total lost weight over the three vertices; ties prefer AM.
    labels[ambiguous] = np.where(losses['am'][faces[ambiguous]].sum(1) <=
                                  losses['bd'][faces[ambiguous]].sum(1), 'am', 'bd')
    maximum = max((float(losses[p][faces[labels == p]].max())
                   for p in allowed if (labels == p).any()), default=0.)
    return labels, ambiguous, losses, allowed, maximum


def convert(out, legend='fuse'):
    config = legend_config(legend)
    mapping = read(CARRIERS)
    parts = {'am': [], 'bd': []}
    summary = dict(format='fuse-pov-mesh-summary', version=1, model=998,
                   revision='2026-10-04 13:47 task correction: mirror Z like T005, without 0.97 scale',
                   binding='v_bind = float32(diag(0.0254, 0.0254, -0.0254) * raw Cast model-space vertex); no rotation/translation/0.97 scale',
                   apex_to_er_matrix=Q.tolist(),
                   tangent='Cast contains no tangent stream; derive ER V tangent with T005 tangent_basis, mirror Z and normalize XYZ, negate W',
                   winding_contract='one flip for Z reflection plus one flip for ER against-normal convention; final indices equal original Cast order',
                   weight_order='normalize source, merge owners/carriers, keep largest 4, normalize, assign triangles, filter unavailable influences only if required',
                   sources=[file_info(p) for p in (config['arms'], GUN, GUN_QC, CARRIERS)],
                   meshes=[], parts={}, incompatible_triangles=0, max_part_weight_loss=0., max_four_weight_loss=0.)
    if legend == 'octane':
        summary['legend'] = legend
    for kind, mdl, mesh in selection(out, legend):
        p = np.asarray(mesh.VertexPositionBuffer(), dtype=float).reshape(-1, 3)
        n = unit(np.asarray(mesh.VertexNormalBuffer(), dtype=float).reshape(-1, 3))
        uv = np.asarray(mesh.VertexUVLayerBuffer(0), dtype=float).reshape(-1, 2)
        uv1 = np.asarray(mesh.VertexUVLayerBuffer(1), dtype=float).reshape(-1, 2)
        faces = np.asarray(mesh.FaceBuffer(), dtype=int).reshape(-1, 3)
        _, v, sign, fallback = tangent_basis(p, n, uv, faces)
        if mesh.VertexTangentBuffer():
            raise ValueError('New Cast tangent stream requires explicit ER U/V interpretation')
        bi, bw, loss, raw_error = merged_weights(mdl, mesh, mapping)
        labels, incompatible, losses, allowed, maximum = assignment(faces, bi, bw, mapping)
        er_positions = p * np.diag(Q)[:3]
        # Reflect directions without changing their lengths, then normalize.
        er_normals = unit(np.asarray(mesh.VertexNormalBuffer(), dtype=float).reshape(-1, 3) * np.diag(MIRROR))
        er_tangents = unit(v * np.diag(MIRROR))
        er_sign = -sign
        entry = dict(model=kind, name=mesh.Name(), material=mesh.Material().Name(),
                     vertices=len(p), triangles=len(faces), carriers=sorted({mapping['carriers'][b]['carrier'] for b in bi[bw > 0]}),
                     source_weight_sum_max_error=raw_error, four_weight_loss_max=float(loss.max()),
                     four_weight_loss_mean=float(loss.mean()), incompatible_triangles=int(incompatible.sum()),
                     part_weight_loss_max=maximum, tangent_fallback_vertices=fallback,
                     source_winding=winding(p, n, faces),
                     mirrored_winding_before_index_flips=winding(er_positions, er_normals, faces),
                     mirror_corrected_winding=winding(er_positions, er_normals, faces[:, [0, 2, 1]]),
                     final_winding=winding(er_positions, er_normals, faces), parts={})
        if legend == 'octane' and kind == 'arms':
            bones = mdl.Skeleton().Bones()
            raw_bi = np.asarray(mesh.VertexWeightBoneBuffer(), dtype=int)
            raw_bw = np.asarray(mesh.VertexWeightValueBuffer())
            used_bones = sorted({bones[b].Name() for b in raw_bi[raw_bw > 0]})
            by_owner = {c['owner']: c['carrier'] for c in mapping['carriers']}
            entry['weighted_bones'] = [dict(bone=b, owner=mapping['owner_of_bone'][b],
                                          carrier=by_owner[mapping['owner_of_bone'][b]]) for b in used_bones]
            entry['forbidden_positive_weight_bones'] = []
        for part in parts:
            tids = np.flatnonzero(labels == part)
            if not len(tids):
                entry['parts'][part] = dict(vertices=0, triangles=0)
                continue
            vids, reverse = np.unique(faces[tids].ravel(), return_inverse=True)
            weights = np.where(allowed[part][bi[vids]], bw[vids], 0)
            if (weights.sum(1) <= 0).any():
                raise ValueError(f'{mesh.Name()}: triangle cannot retain an enabled influence in {part}')
            weights /= weights.sum(1)[:, None]
            indices = bi[vids].copy()
            first = np.argmax(weights > 0, axis=1)
            indices[weights == 0] = np.broadcast_to(indices[np.arange(len(vids)), first, None], indices.shape)[weights == 0]
            data = dict(name=mesh.Name(), model=kind, material=mesh.Material().Name(),
                        positions=er_positions[vids], normals=er_normals[vids],
                        tangents=np.c_[er_tangents[vids], er_sign[vids]],
                        uv0=uv[vids], uv1=uv1[vids], bone_indices=indices, bone_weights=weights,
                        # Reflection swap + ER convention swap cancel, exactly as T005.
                        indices=reverse.reshape(-1, 3),
                        source_vertex_ids=vids, source_triangle_ids=tids)
            parts[part].append(data)
            entry['parts'][part] = dict(vertices=len(vids), triangles=len(tids),
                                         part_weight_loss_max=float(losses[part][vids].max()))
        summary['meshes'].append(entry)
        summary['incompatible_triangles'] += int(incompatible.sum())
        summary['max_part_weight_loss'] = max(summary['max_part_weight_loss'], maximum)
        summary['max_four_weight_loss'] = max(summary['max_four_weight_loss'], float(loss.max()))
    for part, meshes in parts.items():
        write_part(out, part, meshes, mapping)
        doc = read(out/'fusemesh'/part/'mesh.json')
        summary['parts'][part] = dict(meshes=len(meshes), vertices=sum(len(m['positions']) for m in meshes),
              triangles=sum(len(m['indices']) for m in meshes), materials=len(doc['materials']),
              carriers=doc['bones'], texture_inputs=len({f for m in doc['materials'] for f in
                                                        [*m['textures'].values(), *m['sampler_textures'].values()]}))
    summary['boundary_duplicate_vertices'] = sum(s['vertices'] for s in summary['parts'].values()) - sum(m['vertices'] for m in summary['meshes'])
    for part in ('hd', 'lg'):
        summary['parts'][part] = dict(meshes=0, vertices=0, triangles=0, materials=0, note='No mesh argument: build-armor removes template meshes')
    # Retain only the winding proof, not unrelated full-body audits; Fuse's builds (T005, T008) are only a
    # reference here, so an Octane-only workspace without them records nothing
    summary['reference_winding'] = {}
    for name, folder, key in [('T005', 'fuse', 'winding'), ('T008', 'fuse_gun', 'gun_meshes')]:
        reference = ROOT/f'er-data/s3/{folder}/geometry-summary.json'
        if reference.is_file():
            summary['reference_winding'][name] = read(reference)[key]
    save(out/'pov-mesh-summary.json', summary)
    return parts, summary


def load_parts(out):
    """Read serialized fusemesh inputs without modifying build artifacts."""
    mapping = read(CARRIERS)
    carrier_index = {c['carrier']: i for i, c in enumerate(mapping['carriers'])}
    parts = {}
    for part in ('am', 'bd'):
        folder = out / 'fusemesh' / part
        doc = read(folder / 'mesh.json')
        lookup = np.array([carrier_index[n] for n in doc['bones']])
        parts[part] = []
        for sub in doc['submeshes']:
            data = dict(name=sub['name'], model=sub['source_model'], material=doc['materials'][sub['material']]['name'])
            for key, (dtype, width) in STREAMS.items():
                data[key] = np.fromfile(folder / sub[key], dtype=dtype).reshape(-1, width)
            data['bone_indices'] = lookup[data['bone_indices']]
            for key in ('source_vertex_ids', 'source_triangle_ids'):
                data[key] = np.fromfile(folder / sub[key], dtype='<u4')
            parts[part].append(data)
    return parts


def write_part(out, part, meshes, mapping):
    folder = out/'fusemesh'/part
    folder.mkdir(parents=True, exist_ok=True)
    names = sorted({m['material'] for m in meshes})
    used = sorted({int(b) for m in meshes for b in m['bone_indices'].ravel()})
    lookup = {b: i for i, b in enumerate(used)}
    doc = dict(format='fusemesh', version=1, space='flver_model',
               bones=[mapping['carriers'][b]['carrier'] for b in used],
               materials=[material_definition(ROOT, part, n) for n in names], submeshes=[])
    for i, m in enumerate(meshes):
        sub = dict(name=m['name'], material=names.index(m['material']), vertex_count=len(m['positions']),
                   index_count=m['indices'].size, cull_backfaces=True, source_model=m['model'])
        for key, (dtype, _) in STREAMS.items():
            value = m[key]
            if key == 'bone_indices':
                value = np.vectorize(lookup.__getitem__)(value)
            sub[key] = f'mesh{i:03d}.{key}.bin'
            np.asarray(value, dtype=dtype).tofile(folder/sub[key])
        for key in ('source_vertex_ids', 'source_triangle_ids'):
            sub[key] = f'mesh{i:03d}.{key}.bin'
            np.asarray(m[key], dtype='<u4').tofile(folder/sub[key])
        doc['submeshes'].append(sub)
    for material in doc['materials']:
        for file in set(material['textures'].values()) | set(material['sampler_textures'].values()):
            (folder/file).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(out/file, folder/file)
    save(folder/'mesh.json', doc)
