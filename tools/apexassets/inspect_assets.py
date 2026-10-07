"""Cast model/skeleton/animation reader, QC checks, inventory and rest previews.

Uses unmodified dtzxporter/cast cast.py (MIT; LICENSE.cast). Quaternion order
is xyzw. World rest transforms are composed as parent_world @ local_TRS.
Motion tests describe transform curves present in Cast, not Source's separate
movement extraction records. Texture meanings come only from RSX material JSON.
"""
import collections
import csv
import json
import os
from pathlib import Path
import re

import numpy as np
from PIL import Image
from cast import Cast, Model, Animation


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def normal(name):
    return str(name).replace('\\', '/').lower()


def output_files(out):
    """The legacy Fuse inventory must not absorb the nested Octane export."""
    default = Path(__file__).resolve().parents[2] / 'apex-data/assets'
    for directory, folders, files in os.walk(out):
        if Path(directory).resolve() == default.resolve() and 'octane' in folders:
            folders.remove('octane')
        for name in files:
            yield Path(directory) / name


def quat_matrix(q):
    q = np.asarray(q, dtype=float)
    norm = np.linalg.norm(q)
    if norm < 1e-10:
        raise ValueError('Zero rest quaternion')
    x, y, z, w = q / norm
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def quat_multiply(a, b):
    x, y, z, w = a
    u, v, t, s = b
    return np.array([w*u+x*s+y*t-z*v, w*v-x*t+y*s+z*u,
                     w*t+x*v-y*u+z*s, w*s-x*u-y*v-z*t])


def skeleton_data(skeleton):
    bones = skeleton.Bones()
    worlds, rotations = {}, {}
    visiting = set()

    def compose(index):
        if index in worlds:
            return
        if index in visiting:
            raise ValueError('Cyclic bone hierarchy')
        visiting.add(index)
        bone = bones[index]
        p = bone.ParentIndex()
        if p >= len(bones) or p < -1 or p == index:
            raise ValueError(f'Invalid parent: {index} -> {p}')
        position = bone.LocalPosition() or (0, 0, 0)
        rotation = bone.LocalRotation() or (0, 0, 0, 1)
        scale = bone.Scale() or (1, 1, 1)
        local = np.eye(4)
        local[:3, :3] = quat_matrix(rotation) @ np.diag(scale)
        local[:3, 3] = position
        if p >= 0:
            compose(p)
            worlds[index] = worlds[p] @ local
            rotations[index] = quat_multiply(rotations[p], rotation)
        else:
            worlds[index], rotations[index] = local, np.asarray(rotation)
        visiting.remove(index)

    output = []
    for i, bone in enumerate(bones):
        compose(i)
        p = bone.ParentIndex()
        output.append({'index': i, 'name': bone.Name(), 'parent_index': p,
                       'parent_name': bones[p].Name() if p >= 0 else None,
                       'local_position': list(bone.LocalPosition() or (0, 0, 0)),
                       'local_rotation_xyzw': list(bone.LocalRotation() or (0, 0, 0, 1)),
                       'local_scale': list(bone.Scale() or (1, 1, 1)),
                       'world_position': worlds[i][:3, 3].tolist(),
                       'world_rotation_xyzw': rotations[i].tolist(),
                       'world_matrix': worlds[i].tolist(),
                       'stored_world_position': bone.WorldPosition(),
                       'stored_world_rotation_xyzw': bone.WorldRotation()})
    return output


def nodes(path):
    data = Cast.load(str(path))
    return [node for root in data.Roots() for node in root.childNodes]


def model_data(model):
    meshes = []
    bones = model.Skeleton().Bones() if model.Skeleton() else []
    for mesh in model.Meshes():
        count = mesh.VertexCount()
        positions = np.asarray(mesh.VertexPositionBuffer()).reshape(-1, 3)
        faces = np.asarray(mesh.FaceBuffer()).reshape(-1, 3)
        if len(faces) and (faces.min() < 0 or faces.max() >= count):
            raise ValueError('Face references out-of-range vertex')
        influence = mesh.MaximumWeightInfluence()
        weights = np.asarray(mesh.VertexWeightValueBuffer() or [])
        weight_bones = np.asarray(mesh.VertexWeightBoneBuffer() or [])
        observed = 0
        weight_error = None
        if weights.size:
            if weights.size != count * influence or weight_bones.size != weights.size:
                raise ValueError('Weight buffer size mismatch')
            weights = weights.reshape(count, influence)
            ids = weight_bones.reshape(count, influence)
            observed = int((weights > 1e-8).sum(axis=1).max())
            weight_error = float(np.max(np.abs(weights.sum(axis=1) - 1)))
            if np.any(ids[weights > 1e-8] >= len(bones)):
                raise ValueError('Vertex references out-of-range bone')
        material = mesh.Material()
        meshes.append({'name': mesh.Name(), 'vertices': count, 'triangles': mesh.FaceCount(),
                       'weight_buffer_stride': influence, 'max_nonzero_weights': observed,
                       'max_weight_sum_error': weight_error, 'uv_layers': mesh.UVLayerCount(),
                       'material_name': material.Name() if material else None,
                       'material_hash': f'{material.Hash():016x}' if material else None,
                       'bounds_min': positions.min(axis=0).tolist(),
                       'bounds_max': positions.max(axis=0).tolist()})
    return {'mesh_count': len(meshes), 'vertices': sum(x['vertices'] for x in meshes),
            'triangles': sum(x['triangles'] for x in meshes), 'bone_count': len(bones),
            'max_weights': max((m['max_nonzero_weights'] for m in meshes), default=0),
            'uv_layer_counts': sorted({m['uv_layers'] for m in meshes}),
            'materials': [m.Name() for m in model.Materials()], 'meshes': meshes}


def animation_data(anim):
    bones = anim.Skeleton().Bones() if anim.Skeleton() else []
    roots = {b.Name() for b in bones if b.ParentIndex() == -1}
    # jx_c_start is a child of the delta root and may carry locomotion.
    root_candidates = roots | {'jx_c_delta', 'jx_c_start'}
    max_frame, all_bones, varying_bones = -1, set(), set()
    root_motion, pelvis_motion, modes, blend_weights = [], False, set(), []
    for curve in anim.Curves():
        name = curve.properties.get('nn')
        name = name.values[0] if name else curve.NodeName()
        all_bones.add(name)
        frames = curve.KeyFrameBuffer() or ()
        if frames:
            max_frame = max(max_frame, max(frames))
        modes.add(curve.Mode())
        if 'ab' in curve.properties:
            blend_weights.append(curve.AdditiveBlendWeight())
        key = curve.KeyPropertyName()
        values = np.asarray(curve.KeyValueBuffer())
        vector_width = 4 if key == 'rq' else 1
        values = values.reshape(-1, vector_width)
        varying = len(values) > 1 and float(np.max(np.abs(values - values[0]))) > 1e-5
        if varying:
            varying_bones.add(name)
            if name in root_candidates and key in {'px', 'py', 'pz', 'rq'}:
                root_motion.append({'bone': name, 'property': key,
                                    'range': (values.max(axis=0) - values.min(axis=0)).tolist()})
            if name == 'def_c_hip' and key in {'px', 'py', 'pz'}:
                pelvis_motion = True
    return {'framerate': anim.Framerate(), 'frame_count': max_frame + 1 if max_frame >= 0 else None,
            'frame_count_source': 'max Cast keyframe + 1; null when RSX emitted no curves',
            'looping': anim.Looping(), 'bone_count': len(bones), 'curve_count': len(anim.Curves()),
            'bones_with_curves': sorted(all_bones), 'bones_with_varying_curves': sorted(varying_bones),
            'root_motion_in_cast': bool(root_motion), 'root_motion_curves': root_motion,
            'pelvis_translation_varies': pelvis_motion, 'curve_modes': sorted(modes),
            'cast_curve_additive_weight_range': [min(blend_weights), max(blend_weights)] if blend_weights else None,
            'notification_tracks': [{'name': n.Name(), 'frames': n.KeyFrameBuffer()} for n in anim.Notifications()],
            'curve_mode_override_count': len(anim.ChildrenOfType(__import__('cast').CurveModeOverride)),
            'source_sequence_events_or_blendspace_metadata_in_cast': False}


def rson_arrays(path):
    text = path.read_text(encoding='utf8')
    return {name: [line.strip().strip(',').strip('"') for line in body.splitlines() if line.strip()] for name, body in
            re.findall(r'(\w+)\s*:\s*\[(.*?)\]', text, flags=re.S)}


def qc_sections(path):
    """Keep each sequence/bodygroup verbatim, including brace-free sequences."""
    text = path.read_text(encoding='utf8')
    sections = []
    for match in re.finditer(r'^\$(sequence|bodygroup)\s+"([^"]+)"', text, re.M):
        start = match.start()
        opening = text.find('{', match.end())
        next_command = re.search(r'^\$', text[match.end():], re.M)
        if opening < 0 or (next_command and opening > match.end() + next_command.start()):
            end = match.end() + next_command.start() if next_command else len(text)
            sections.append((match.group(1), match.group(2), text[start:end].rstrip()))
            continue
        depth, pos, quoted = 1, opening + 1, False
        while depth and pos < len(text):
            ch = text[pos]
            if ch == '"' and text[pos-1] != '\\':
                quoted = not quoted
            if not quoted:
                depth += (ch == '{') - (ch == '}')
            pos += 1
        if depth:
            raise ValueError(f'Unbalanced QC: {path}')
        sections.append((match.group(1), match.group(2), text[start:pos]))
    return text, sections


def preview(model, skel, material_json, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection, LineCollection
    positions = np.asarray([bone['world_position'] for bone in skel])
    # Exported Fuse vertices and rest bones are Y-up; do not rotate either.
    for view, horizontal, depth_axis, depth_sign in [('front', 0, 2, 1), ('side', 2, 0, 1)]:
        triangles, colors, depths = [], [], []
        for mesh in model.Meshes():
            vertices = np.asarray(mesh.VertexPositionBuffer()).reshape(-1, 3)
            faces = np.asarray(mesh.FaceBuffer()).reshape(-1, 3)
            coords = vertices[faces]
            tri = coords[:, :, [horizontal, 1]]
            shade = np.full((len(faces), 3), (0.64, 0.68, 0.74))
            material = mesh.Material()
            info = material_json.get(normal(material.Name())) if material else None
            if info:
                col = next((entry['file'] for entry in info['textures']
                            if entry['usage'].lower() in {'colortexture', 'albedo', 'color', 'albedotexture', '_col'} and entry['file']), None)
                if col:
                    texture = np.asarray(Image.open(out / col).convert('RGB')) / 255
                    uv = np.asarray(mesh.VertexUVLayerBuffer(0)).reshape(-1, 2)[faces].mean(axis=1)
                    # Source UV V points downward; nearest centroid is enough for rest previews.
                    x = ((uv[:, 0] % 1) * (texture.shape[1] - 1)).astype(int)
                    y = ((uv[:, 1] % 1) * (texture.shape[0] - 1)).astype(int)
                    shade = texture[y, x]
            cross = np.cross(coords[:, 1]-coords[:, 0], coords[:, 2]-coords[:, 0])
            normals = cross / np.maximum(np.linalg.norm(cross, axis=1, keepdims=True), 1e-9)
            light = 0.60 + 0.40 * np.abs(normals[:, depth_axis])
            triangles.append(tri)
            colors.append(np.clip(shade * light[:, None], 0, 1))
            depths.append(coords[:, :, depth_axis].mean(axis=1) * depth_sign)
        triangles, colors, depths = np.concatenate(triangles), np.concatenate(colors), np.concatenate(depths)
        order = np.argsort(depths)
        fig, ax = plt.subplots(figsize=(7, 9), dpi=160)
        fig.patch.set_facecolor('#f0f2f5')
        ax.set_facecolor('#f0f2f5')
        ax.add_collection(PolyCollection(triangles[order], facecolors=colors[order],
                                         edgecolors='none', rasterized=True))
        lines = []
        for bone in skel:
            if bone['parent_index'] >= 0 and (bone['name'].startswith('def_') or bone['name'] == 'jx_c_start'):
                lines.append(positions[[bone['parent_index'], bone['index']]][:, [horizontal, 1]])
        ax.add_collection(LineCollection(lines, colors='#28aee1', linewidths=0.5, alpha=0.58))
        core = [b['index'] for b in skel if b['name'] in {'def_c_hip', 'def_c_head', 'def_l_wrist', 'def_r_wrist', 'def_l_ankle', 'def_r_ankle'}]
        ax.scatter(positions[core, horizontal], positions[core, 1], s=8, color='#0b7cba', zorder=5)
        ax.autoscale()
        ax.margins(0.08)
        ax.set_aspect('equal')
        ax.axis('off')
        ax.set_title(f'pilot_medium_fuse — LOD0 rest pose — {view}', fontsize=11)
        fig.text(0.5, 0.025, 'Orthographic mesh + rest skeleton; exported Cast coordinates, Y up', ha='center', fontsize=8)
        fig.savefig(out / f'preview/pilot_medium_fuse_{view}.png', facecolor=fig.get_facecolor(), bbox_inches='tight')
        plt.close(fig)


def analyze(out):
    rows = list(csv.DictReader((out / 'lists/core_named.csv').open(encoding='utf8')))
    by_guid, by_name = {}, {}
    # RSX FindAssetByGUID uses the first loaded matching asset, including when
    # the same material/texture appears in common and the skin root package.
    for row in rows:
        by_guid.setdefault(row['guid'].lower().zfill(16), row)
        by_name.setdefault(normal(row['asset_name']), row)
    by_basename = collections.defaultdict(list)
    for row in rows:
        by_basename[normal(row['asset_name']).rsplit('/', 1)[-1]].append(row)
    file_identity, models, skeletons, sequences, materials = {}, [], [], {}, []
    texture_uses = collections.defaultdict(list)

    # Model-local material JSON keeps the correct skin 0 bindings and shader slots.
    for path in sorted((out / 'cast').rglob('*.json')):
        data = json.loads(path.read_text(encoding='utf8'))
        if '$textures' not in data:
            continue
        asset = by_name.get(normal(path.relative_to(out / 'cast').with_suffix('.rpak')))
        if not asset:
            asset = by_name.get(normal('material/' + data['name'] + '.rpak'))
        if not asset:
            asset = by_name.get(normal(data['name']))
        textures = []
        for slot, name in data['$textures'].items():
            usage = data['$textureTypes'].get(slot, 'unavailable')
            value = None
            guid = None
            if name.startswith('0x'):
                guid = name[2:].lower().zfill(16)
                candidates = list(path.parent.glob('0x' + name[2:] + '.png'))
            else:
                filename = normal(name).rsplit('/', 1)[-1].replace('.rpak', '.png')
                global_path = out / 'cast' / Path(name.replace('\\', '/')).with_suffix('.png')
                candidates = [global_path] if global_path.exists() else [p for p in path.parent.glob('*.png') if p.name.lower() == filename]
                tx = by_name.get(normal(name))
                if not tx:
                    tx = next((r for r in by_basename[filename.replace('.png', '.rpak')] if r['type'] == 'txtr'), None)
                guid = tx['guid'].lower().zfill(16) if tx else None
                guid_match = re.search(r'0x([0-9a-f]+)', name, re.I)
                if guid_match:
                    guid = guid_match.group(1).lower().zfill(16)
            if candidates:
                value = str(candidates[0].relative_to(out)).replace('\\', '/')
            entry = {'slot': int(slot), 'usage': usage, 'asset_name': name, 'guid': guid, 'file': value}
            textures.append(entry)
            if value:
                texture_uses[value].append({'material': data['name'], 'slot': int(slot), 'usage': usage})
                if guid and guid in by_guid:
                    file_identity[value] = by_guid[guid]
        item = {'name': data['name'], 'json_file': str(path.relative_to(out)).replace('\\', '/'),
                'guid': asset['guid'] if asset else None, 'textures': textures,
                'shader_type': data.get('shaderType'), 'shader_set': data.get('shaderSet')}
        materials.append(item)
        if asset:
            file_identity[item['json_file']] = asset
        # RSX model exports use material semantic names; explicit material
        # exports use GUID names. Link both aliases using the exported slot type.
        material_stem = data['name'].rsplit('/', 1)[-1]
        for entry in textures:
            alias = material_stem + entry['usage'] + '.png'
            for local in (out / 'cast/mdl').rglob(alias):
                rel = str(local.relative_to(out)).replace('\\', '/')
                texture_uses[rel].append({'material': data['name'], 'slot': entry['slot'], 'usage': entry['usage'],
                                           'provenance': item['json_file']})
                if entry['guid'] in by_guid:
                    file_identity[rel] = by_guid[entry['guid']]
            if entry['guid']:
                for dds in (out / 'dds').rglob('*.dds'):
                    if re.fullmatch(r'0x0*' + entry['guid'].lstrip('0') + r'\.dds', dds.name, re.I):
                        rel = str(dds.relative_to(out)).replace('\\', '/')
                        texture_uses[rel].append({'material': data['name'], 'slot': entry['slot'], 'usage': entry['usage']})
                        if entry['guid'] in by_guid:
                            file_identity[rel] = by_guid[entry['guid']]
    dump(out / 'materials.json', {'materials': materials,
                                 'channel_note': 'Uses are literal RSX shader resource names. Unavailable remains unknown; no suffix guessing.'})

    for path in sorted((out / 'cast').rglob('*.cast')):
        rel = str(path.relative_to(out)).replace('\\', '/')
        for node in nodes(path):
            guid = f'{node.Hash():016x}'
            asset = by_guid.get(guid)
            if asset:
                file_identity[rel] = asset
            if isinstance(node, Model):
                info = model_data(node)
                info.update({'file': rel, 'guid': guid, 'asset': asset})
                models.append(info)
                skel = skeleton_data(node.Skeleton()) if node.Skeleton() else []
                if path.name == 'pilot_medium_fuse_LOD0.cast':
                    dump(out / 'fuse_skeleton.json', {'source_file': rel, 'guid': guid,
                                                     'quaternion_order': 'xyzw', 'units': 'unchanged Source model units',
                                                     'world_transform_rule': 'parent_world @ local_TRS',
                                                     'bone_count': len(skel), 'bones': skel})
                    preview(node, skel, {normal(m['name'].rsplit('/', 1)[-1].removesuffix('_sknp')): m for m in materials}, out)
                elif path.parent.name == 'medium' and not node.Meshes():
                    skeletons.append({'source_file': rel, 'guid': guid, 'asset': asset,
                                      'bone_count': len(skel), 'bones': skel})
            elif isinstance(node, Animation):
                clip = animation_data(node)
                clip.update({'file': rel, 'blend_index': int(re.search(r'_(\d+)\.cast$', path.name).group(1))})
                sequence = sequences.setdefault(guid, {'guid': guid, 'asset': asset, 'clips': []})
                # Canonical collision-safe exports supersede preliminary aliases.
                previous = next((c for c in sequence['clips'] if c['blend_index'] == clip['blend_index']), None)
                if previous:
                    if '/animseq/' in rel:
                        sequence['clips'].remove(previous)
                        sequence['clips'].append(clip)
                else:
                    sequence['clips'].append(clip)
    dump(out / 'models.json', {'models': models})
    dump(out / 'fuse_rigs.json', {'rigs': skeletons})

    rigs, model_dependencies = [], []
    for path in sorted((out / 'raw').rglob('*.rson')):
        is_rig = 'animrig' in path.parts
        rig_or_model = by_name.get(normal(str(path.relative_to(out / 'raw').with_suffix('.rrig' if is_rig else '.rmdl'))))
        arrays = rson_arrays(path)
        if rig_or_model and not is_rig:
            model_dependencies.append({'model': rig_or_model, 'manifest': str(path.relative_to(out)).replace('\\', '/'), 'references': arrays})
        if rig_or_model and rig_or_model['type'] == 'arig':
            refs = []
            for name in arrays.get('seqs', []):
                asset = by_name.get(normal(name))
                if not asset:
                    asset = by_guid.get(name.lower().removeprefix('0x').zfill(16))
                refs.append(asset or {'asset_name': name, 'missing': True})
            rigs.append({'rig': rig_or_model, 'manifest': str(path.relative_to(out)).replace('\\', '/'),
                         'sequence_references': refs})
            for asset in refs:
                guid = asset.get('guid', '').lower().zfill(16)
                if guid in sequences:
                    sequences[guid].setdefault('referenced_by_rigs', []).append(rig_or_model['asset_name'])
    dump(out / 'rig_dependencies.json', {'rigs': rigs, 'models': model_dependencies})

    qc = []
    bodygroups = []
    for path in sorted((out / 'smd').rglob('*.qc')):
        text, sections = qc_sections(path)
        record = {'file': str(path.relative_to(out)).replace('\\', '/'), 'sequences': [],
                  'include_models': re.findall(r'\$includemodel\s+"([^"]+)"', text),
                  'pose_parameters': re.findall(r'^\$poseparameter.*$', text, re.M)}
        for kind, name, block in sections:
            if kind == 'bodygroup':
                groups = {'name': name, 'options': re.findall(r'^\s*(?:studio\s+"([^"]+)"|(blank))', block, re.M),
                          'raw_qc': block}
                if 'r301_base_w' in path.name:
                    bodygroups.append(groups)
                continue
            events = re.findall(r'^.*\bevent\s+.*$', block, re.M)
            record['sequences'].append({'name': name, 'event_lines': events, 'raw_qc': block})
            for seq in sequences.values():
                if seq['asset'] and normal(seq['asset']['asset_name']).rsplit('/', 1)[-1].removesuffix('.rseq') == name.lower():
                    seq.setdefault('qc_metadata', []).append({'file': record['file'], 'sequence_name': name,
                                                               'event_lines': events,
                                                               'has_blend_options': 'blend ' in block or 'blendwidth' in block,
                                                               'has_layers': 'addlayer' in block or 'blendlayer' in block,
                                                               'raw_qc': block})
        qc.append(record)
    dump(out / 'qc_metadata.json', {'files': qc, 'note': 'Literal RSX QC; not an ER event mapping.'})
    dump(out / 'r301_bodygroups.json', {'source': [x['file'] for x in qc if 'r301_base_w' in x['file']], 'bodygroups': bodygroups})

    clips = [clip for seq in sequences.values() for clip in seq['clips']]
    seq_summary = {'sequence_count': len(sequences), 'clip_count': len(clips),
                   'clips_without_curves': sum(c['curve_count'] == 0 for c in clips),
                   'notification_track_count': sum(len(c['notification_tracks']) for c in clips),
                   'clips_with_root_motion_in_cast': sum(c['root_motion_in_cast'] for c in clips),
                   'sequences_with_qc_events': sum(any(m['event_lines'] for m in s.get('qc_metadata', [])) for s in sequences.values()),
                   'root_motion_scope': 'Only varying Cast root transform curves; Source movement records remain in raw/QC.',
                   'sequences': sorted(sequences.values(), key=lambda s: normal(s['asset']['asset_name']) if s['asset'] else s['guid'])}
    reference_guids = {ref['guid'].lower().zfill(16) for rig in rigs for ref in rig['sequence_references'] if ref.get('guid')}
    seq_summary['rig_unique_sequence_reference_count'] = len(reference_guids)
    seq_summary['missing_sequence_guids'] = sorted(reference_guids - sequences.keys())
    dump(out / 'fuse_sequences.json', seq_summary)

    # Associate files by embedded Cast GUID or exact game path/manifest, not invented asset names.
    identity_extensions = {'.rmdl', '.rrig', '.rseq', '.qc', '.smd', '.vg', '.vg_static', '.json', '.cpu', '.rson', '.rseq_extn'}
    identity_extensions.update({'.uber_struct', '.phy'})
    sequence_stems = {normal(s['asset']['asset_name']).rsplit('/', 1)[-1].removesuffix('.rseq'): s['asset'] for s in sequences.values() if s['asset']}
    sequence_aliases = {}
    for rel, identity in file_identity.items():
        if identity['type'] == 'aseq' and rel.endswith('.cast'):
            alias_path = Path(rel)
            alias_stem = re.sub(r'_\d+$', '', alias_path.stem).lower()
            sequence_aliases[(alias_path.parent.name, alias_stem)] = identity
    for path in output_files(out):
        if not path.is_file():
            continue
        rel = str(path.relative_to(out)).replace('\\', '/')
        if rel in file_identity:
            continue
        if path.suffix in identity_extensions and rel.split('/')[0] in {'cast', 'smd', 'raw', 'odl'}:
            stem = re.sub(r'_LOD\d+$', '', path.stem, flags=re.I)
            explicit = None
            relative = path.relative_to(out / rel.split('/')[0])
            for extension in ['.rseq', '.rmdl', '.rrig', '.rpak']:
                explicit = by_name.get(normal(relative.with_suffix(extension)))
                if explicit:
                    break
            alias = sequence_aliases.get((path.parent.name, stem.lower()))
            if explicit:
                file_identity[rel] = explicit
            elif alias:
                file_identity[rel] = alias
            elif stem.lower() in sequence_stems:
                file_identity[rel] = sequence_stems[stem.lower()]
            else:
                candidates = [r for r in rows if r['type'] in {'arig', 'mdl_', 'matl', 'odla'} and
                              normal(r['asset_name']).rsplit('/', 1)[-1].rsplit('.', 1)[0] == stem.lower()]
                if len(candidates) == 1:
                    file_identity[rel] = candidates[0]
                else:
                    parents = normal(relative.parent)
                    candidates = [r for r in rows if r['type'] in {'mdl_', 'arig'}
                                  and normal(r['asset_name']).rsplit('/', 1)[0] == parents
                                  and stem.lower().startswith(normal(r['asset_name']).rsplit('/', 1)[-1].rsplit('.', 1)[0] + '_')]
                    if len(candidates) == 1:
                        file_identity[rel] = candidates[0]
        if rel.startswith('dds/') and path.suffix in {'.json', '.uber_struct'}:
            explicit = by_name.get(normal(path.relative_to(out / 'dds').with_suffix('.rpak')))
            if not explicit:
                match = re.fullmatch(r'0x([0-9a-f]+)', path.stem, re.I)
                explicit = by_guid.get(match[1].lower().zfill(16)) if match else None
            if explicit:
                file_identity[rel] = explicit
        if path.suffix == '.wav':
            stream = path.parent.name + '.mstr'
            with (out / 'lists/audio_named.csv').open(encoding='utf8') as file:
                row = next((r for r in csv.DictReader(file) if r['asset_name'] == path.stem and r['file_name'] == stream), None)
            if row:
                file_identity[rel] = row
        if rel.startswith('odl/') and path.suffix == '.json':
            data = json.loads(path.read_text(encoding='utf8'))
            identity = by_guid.get(data['odlGuid'].lower().zfill(16))
            if identity:
                file_identity[rel] = identity
    inventory = []
    for path in sorted(output_files(out)):
        if not path.is_file() or path.name in {'inventory.json', 'inventory.md'}:
            continue
        rel = str(path.relative_to(out)).replace('\\', '/')
        identity = file_identity.get(rel)
        record = {'export_file': rel, 'size': path.stat().st_size,
                  'asset_path': identity['asset_name'] if identity else None,
                  'guid': identity['guid'] if identity else None,
                  'type': identity['type'] if identity else 'derived_or_log',
                  'source_package': identity['file_name'] if identity else None}
        if path.suffix == '.png' and rel in texture_uses:
            image = Image.open(path)
            record.update({'texture_uses': texture_uses[rel], 'image_mode': image.mode,
                           'image_size': list(image.size), 'export_format': 'PNG'})
        if path.suffix == '.dds' and rel in texture_uses:
            import struct
            data = path.read_bytes()[:148]
            if data[:4] != b'DDS ':
                raise ValueError('Invalid DDS header')
            fourcc = data[84:88].decode('ascii', errors='replace')
            record.update({'texture_uses': texture_uses[rel], 'export_format': 'DDS',
                           'image_size': [struct.unpack_from('<I', data, 16)[0], struct.unpack_from('<I', data, 12)[0]],
                           'fourcc': fourcc, 'dxgi_format': struct.unpack_from('<I', data, 128)[0] if fourcc == 'DX10' else None})
        inventory.append(record)
    return write_inventory(out, inventory)


def write_inventory(out, inventory):
    seq_summary = json.loads((out / 'fuse_sequences.json').read_text(encoding='utf8'))
    totals = {'files': len(inventory), 'bytes': sum(r['size'] for r in inventory),
              'sequence_count': seq_summary['sequence_count'], 'clip_count': seq_summary['clip_count'],
              'notification_track_count': seq_summary['notification_track_count'],
              'clips_without_curves': seq_summary['clips_without_curves']}
    totals['superseded_cast_aliases'] = sum(r.get('export_status') == 'superseded_trial_alias' for r in inventory)
    dump(out / 'inventory.json', {'totals_excluding_inventory_itself': totals, 'assets': inventory})
    lines = ['# T001 资产清单', '', '游戏名称、GUID、来源包取自本机 RSX 完整清单；用途逐字取自材质 JSON 的 `$textureTypes`。',
             '派生汇总与日志没有独立游戏 GUID，标为 derived_or_log。', '',
             f'文件 {totals["files"]}；合计 {totals["bytes"]:,} 字节（不含清单自身）。',
             f'3P 序列 {totals["sequence_count"]}；Cast 混合样本 {totals["clip_count"]}；通知轨道 {seq_summary["notification_track_count"]}。', '',
             '| 导出文件 | 游戏资产路径 | GUID | 类型 | 来源包 | 字节 | 贴图用途 |',
             '|---|---|---|---|---|---:|---|']
    for row in inventory:
        usage = ', '.join(sorted({u['usage'] for u in row.get('texture_uses', [])}))
        lines.append(f'| {row["export_file"]} | {row["asset_path"] or "—"} | {row["guid"] or "—"} | {row["type"]} | {row["source_package"] or "—"} | {row["size"]} | {usage} |')
    (out / 'inventory.md').write_text('\n'.join(lines) + '\n', encoding='utf8')
    return totals


def refresh_inventory(out):
    """Refresh sizes after timing/verification sidecars are written; no Cast reparse."""
    current = json.loads((out / 'inventory.json').read_text(encoding='utf8'))
    records = {row['export_file']: row for row in current['assets']}
    sequences = json.loads((out / 'fuse_sequences.json').read_text(encoding='utf8'))['sequences']
    active_clips = {clip['file'] for sequence in sequences for clip in sequence['clips']}
    source = {row['guid'].lower().zfill(16): row for row in
              csv.DictReader((out / 'lists/core_named.csv').open(encoding='utf8'))}
    inventory = []
    for path in sorted(output_files(out)):
        if not path.is_file() or path.name in {'inventory.json', 'inventory.md'}:
            continue
        rel = str(path.relative_to(out)).replace('\\', '/')
        record = records.get(rel, {'export_file': rel, 'asset_path': None, 'guid': None,
                                    'type': 'derived_or_log', 'source_package': None})
        record['size'] = path.stat().st_size
        if record['type'] == 'aseq' and rel.endswith('.cast'):
            record['export_status'] = 'active_clip' if rel in active_clips else 'superseded_trial_alias'
        if rel.startswith('odl/') and path.suffix == '.json':
            data = json.loads(path.read_text(encoding='utf8'))
            identity = source[data['odlGuid'].lower().zfill(16)]
            record.update({'asset_path': identity['asset_name'], 'guid': identity['guid'],
                           'type': identity['type'], 'source_package': identity['file_name']})
        inventory.append(record)
    return write_inventory(out, inventory)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('path', nargs='?', type=Path, default=Path(__file__).resolve().parents[2] / 'apex-data/assets')
    args = parser.parse_args()
    if args.path.suffix == '.cast':
        print(json.dumps([model_data(n) if isinstance(n, Model) else animation_data(n) for n in nodes(args.path)
                          if isinstance(n, (Model, Animation))], ensure_ascii=False, indent=2))
    else:
        print(json.dumps(analyze(args.path), ensure_ascii=False, indent=2))
