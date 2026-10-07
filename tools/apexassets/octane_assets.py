"""T014: dependency-driven default Octane export and cross-format verification.

Game names come from local player/weapon settings and RSX's postloaded list.
RSEQ metadata uses the compact structures in the pinned RSX studio_r5_v16.h;
label, activity, blend count, FPS and frame count are checked against QC/Cast.
"""
import csv
import filecmp
import json
from pathlib import Path
import re
import struct
import time

import numpy as np

from cast import Animation, Model
from inspect_assets import (animation_data, dump, model_data, nodes, normal,
                            qc_sections, quat_matrix, rson_arrays, skeleton_data)

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
PACKAGES = [
    'common.rpak', 'common_mp.rpak', 'common_early.rpak',
    'root_lgnd_skins_humans_class_medium_pilot_medium_stim.rpak',
    'root_lgnd_skins_humans_class_medium_pilot_medium_stim_shdrs.rpak',
]
EXPORT_FOLDERS = ('cast', 'raw', 'smd', 'dds', 'odl')


def load_json(path):
    return json.loads(path.read_text(encoding='utf8'))


def relpath(path, out):
    return path.relative_to(out).as_posix()


def list_rows(out, name='core_named'):
    with (out / f'lists/{name}.csv').open(encoding='utf8', newline='') as stream:
        return list(csv.DictReader(stream))


def indexes(rows):
    by_guid, by_name = {}, {}
    for row in rows:
        row = dict(row, guid=row['guid'].lower().zfill(16))
        by_guid.setdefault(row['guid'], row)
        by_name.setdefault(normal(row['asset_name']), row)
    return by_guid, by_name


def asset_reference(value, by_guid, by_name):
    return by_name.get(normal(value)) or by_guid.get(value.lower().removeprefix('0x').zfill(16))


def asset_file(out, folder, row, extension):
    return (out / folder / Path(row['asset_name'].replace('\\', '/'))).with_suffix(extension)


def local_targets():
    settings_path = REPO / 'apex-data/export/settings/player/mp/pilot_survival_stim.json'
    # The local settings dumper leaves trailing commas in this .json file.
    # Read the two exact string fields without accepting the file as strict JSON.
    settings_text = settings_path.read_text(encoding='utf8')

    def setting_model(key):
        matches = re.findall(r'"' + re.escape(key) + r'"\s*:\s*("(?:[^"\\]|\\.)*")', settings_text)
        if len(matches) != 1:
            raise ValueError(f'Expected one {key} in {settings_path}')
        return json.loads(matches[0])

    def weapon_model(filename, key):
        path = REPO / 'apex-data/export/weapon' / filename
        matches = re.findall(r'"' + re.escape(key) + r'"\s+"([^"]+)"', path.read_text(encoding='utf8'))
        if len(matches) != 1:
            raise ValueError(f'Expected one {key} in {path}')
        return matches[0], relpath(path, REPO)

    epipen, epipen_source = weapon_model('mp_ability_octane_stim.txt', 'viewmodel')
    held_pad, pad_source = weapon_model('mp_weapon_jump_pad.txt', 'viewmodel')
    prop_pad, _ = weapon_model('mp_weapon_jump_pad.txt', 'projectilemodel')
    result = [
        {'role': 'body', 'asset_path': setting_model('bodyModel'), 'settings_source': relpath(settings_path, REPO)},
        {'role': 'arms', 'asset_path': setting_model('armsModel'), 'settings_source': relpath(settings_path, REPO)},
        {'role': 'stim_viewmodel', 'asset_path': epipen, 'settings_source': epipen_source},
        {'role': 'jump_pad_viewmodel', 'asset_path': held_pad, 'settings_source': pad_source},
        {'role': 'jump_pad_prop', 'asset_path': prop_pad, 'settings_source': pad_source},
    ]
    if any(not target['asset_path'] for target in result):
        raise ValueError('Missing body/arms model in local player settings')
    return result


def resolve_targets(out):
    by_guid, by_name = indexes(list_rows(out))
    targets = local_targets()
    pending = []
    for target in targets:
        row = by_name.get(normal(target['asset_path']))
        if row is None:
            target['status'] = '待定'
            pending.append(dict(target, reason='Model absent from the loaded local RPaks'))
        else:
            target['asset'] = row
    return targets, by_guid, by_name, pending


def model_links(out, targets, by_guid, by_name, pending):
    rigs, ability_rigs = {}, {}
    for target in targets:
        if 'asset' not in target:
            continue
        manifest = asset_file(out, 'raw', target['asset'], '.rson')
        arrays = rson_arrays(manifest)
        target['raw_manifest'] = relpath(manifest, out)
        target['rigs'] = []
        target['inline_sequences'] = []
        for value in arrays.get('rigs', []):
            row = asset_reference(value, by_guid, by_name)
            if not row:
                pending.append({'asset_path': value, 'status': '待定', 'reason': 'Referenced rig absent from local list'})
                continue
            target['rigs'].append(row)
            rigs[row['guid']] = row
            if target['role'] not in {'body', 'arms'}:
                ability_rigs[row['guid']] = row
        for value in arrays.get('seqs', []):
            row = asset_reference(value, by_guid, by_name)
            if row:
                target['inline_sequences'].append(row)
            else:
                pending.append({'asset_path': value, 'status': '待定', 'reason': 'Referenced model sequence absent from local list'})
    return targets, rigs, ability_rigs


def export_octane(out, paks, exe, run, runs):
    started = time.perf_counter()
    for directory in ('lists', 'logs', 'skeletons', 'sequences'):
        (out / directory).mkdir(parents=True, exist_ok=True)
    for package in PACKAGES:
        if not (paks / package).is_file():
            raise FileNotFoundError(paks / package)
    run(exe, 'core_named', 'cast', flags=['-metadataonly'])
    targets, by_guid, by_name, pending = resolve_targets(out)
    model_names = [target['asset']['asset_name'] for target in targets if 'asset' in target]
    if not model_names:
        raise ValueError('None of the requested models is present locally')
    exact_models = ['--exportexact', ','.join(model_names)]
    run(exe, 'models_cast', 'cast', 'mdl_', flags=exact_models + ['-matltextures', '--format-matl', '2'])
    run(exe, 'models_raw', 'raw', 'mdl_', flags=exact_models + ['--format-mdl_', '2'])
    targets, rigs, ability_rigs = model_links(out, targets, by_guid, by_name, pending)
    material_guids = set()
    for target in targets:
        if 'asset' not in target:
            continue
        path = asset_file(out, 'cast', target['asset'], '.cast')
        path = path.with_name(path.stem + '_LOD0.cast')
        model = next(n for n in nodes(path) if isinstance(n, Model))
        material_guids.update(f'{m.Hash():016x}' for m in model.Materials())
    materials = [by_guid[guid]['asset_name'] for guid in sorted(material_guids)]
    run(exe, 'materials', 'cast', 'matl', flags=[
        '--exportexact', ','.join(materials), '--format-matl', '2', '-matltextures'])
    run(exe, 'materials_dds', 'dds', 'matl', flags=[
        '--exportexact', ','.join(materials), '--format-matl', '2', '--format-txtr', '2', '-matltextures'])
    rig_names = [row['asset_name'] for row in rigs.values()]
    ability_names = [row['asset_name'] for row in ability_rigs.values()]
    run(exe, 'rigs_cast', 'cast', 'arig', flags=['--exportexact', ','.join(rig_names)])
    run(exe, 'rigs_raw', 'raw', 'arig', flags=['--exportexact', ','.join(rig_names), '--format-arig', '2'])
    # Export linked sequences through their rig, preserving the rig association.
    # Standalone raw ASEQ export in upstream 2.3.0 dereferences a null parsedData.
    if ability_names:
        run(exe, 'ability_sequences_cast', 'cast', 'arig', flags=[
            '--exportexact', ','.join(ability_names), '-exportrigsequences'])
        run(exe, 'ability_sequences_raw', 'raw', 'arig', flags=[
            '--exportexact', ','.join(ability_names), '--format-arig', '2',
            '--format-aseq', '2', '-exportrigsequences'])
    inline_models = [target['asset']['asset_name'] for target in targets if target.get('inline_sequences')
                     and target['role'] not in {'body', 'arms'}]
    if inline_models:
        for folder, flags in [('cast', []), ('raw', ['--format-mdl_', '2', '--format-aseq', '2'])]:
            run(exe, 'inline_sequences_' + folder, folder, 'mdl_', flags=[
                '--exportexact', ','.join(inline_models), '-exportrigsequences'] + flags)
    run(exe, 'smd_qc', 'smd', 'mdl_,arig', flags=[
        '--exportexact', ','.join(model_names + rig_names), '--format-mdl_', '3',
        '--format-arig', '3', '--format-aseq', '3'])
    odls = [by_name[normal('odl_asset/' + target['asset_path'])]['asset_name']
            for target in targets if normal('odl_asset/' + target['asset_path']) in by_name]
    if odls:
        run(exe, 'odl', 'odl', 'odla', flags=['--exportexact', ','.join(odls)])
    # The task asks for the actual first-person Fuse reference, including its
    # model -> rig manifest. Its existing Cast is read-only comparison input.
    from export_assets import DEFAULT_OUT
    fuse_packages = [paks / name.replace('pilot_medium_stim', 'pilot_medium_fuse') for name in PACKAGES]
    fuse_name = 'mdl/weapons/arms/pov_pilot_medium_fuse.rmdl'
    run(exe, 'fuse_arms_reference', 'comparison/fuse_raw', 'mdl_',
        flags=['--exportexact', fuse_name.replace('/', '\\'), '--format-mdl_', '2'], files=fuse_packages)
    dump(out / 'export_selection.json', {'legend': 'octane', 'skin': 0, 'targets': targets,
                                        'rigs': list(rigs.values()), 'ability_rigs': list(ability_rigs.values()),
                                        'pending': pending, 'fuse_reference_root': str(DEFAULT_OUT)})
    dump(out / 'run_manifest.json', {'legend': 'octane', 'package_inputs': PACKAGES,
                                    'adapter': str(exe), 'runs': runs,
                                    'total_seconds': time.perf_counter() - started})
    result = analyze_octane(out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def compact_offset(value):
    return (value & 0xfffe) << (4 * (value & 1))


def linked_sequence_file(out, row, parents):
    canonical = asset_file(out, 'raw', row, '.rseq')
    if canonical.is_file():
        return canonical
    filename = Path(row['asset_name'].replace('\\', '/')).name
    candidates = []
    for parent in parents:
        parent_path = asset_file(out, 'raw', parent, '.rrig' if parent['type'] == 'arig' else '.rmdl')
        path = parent_path.parent / ('anims_' + parent_path.stem) / filename
        if path.is_file():
            candidates.append(path)
    if not candidates or any(not filecmp.cmp(candidates[0], path, shallow=False) for path in candidates[1:]):
        raise ValueError(f'Missing or ambiguous linked RSEQ: {row}')
    return candidates[0]


def rseq_metadata(path):
    """Read v16/v18 compact seqdesc and v16/v19 animdesc common fields.

    Layout: studio_r5_v16.h mstudioseqdesc_v16_t/v18_t; FIX_OFFSET in studio.h.
    These are descriptor *layout* versions, not the RPak ASEQ asset version.
    Unsupported/malformed descriptors fail instead of inventing frame counts.
    """
    data = path.read_bytes()
    if len(data) < 112:
        raise ValueError(f'Truncated compact RSEQ: {path}')

    def u16(offset):
        return struct.unpack_from('<H', data, offset)[0]

    def string(offset):
        if not 0 <= offset < len(data):
            raise ValueError(f'RSEQ string outside file: {path}')
        end = data.find(b'\0', offset)
        if end < 0:
            raise ValueError(f'Unterminated RSEQ string: {path}')
        return data[offset:end].decode('utf8')

    label = string(compact_offset(u16(0)))
    activity_offset = compact_offset(u16(2))
    activity = string(activity_offset) if activity_offset else ''
    count = u16(40)
    dimensions = list(data[84:86])
    table = compact_offset(u16(42))
    if not count or count != dimensions[0] * dimensions[1] or table + 2 * count > len(data):
        raise ValueError(f'Unsupported RSEQ blend descriptor: {path}')
    blends = []
    for index in range(count):
        offset = compact_offset(u16(table + 2 * index))
        if offset + 14 > len(data):
            raise ValueError(f'RSEQ animation descriptor outside file: {path}')
        fps, flags, frames = struct.unpack_from('<fii', data, offset)
        if not 0 < fps <= 2048 or not 0 < frames <= 0x20000:
            raise ValueError(f'Unsupported RSEQ animation metadata: {path}')
        blends.append({'blend_index': index, 'name': string(offset + compact_offset(u16(offset + 12))),
                       'frame_count': frames, 'framerate': fps, 'flags': flags,
                       'animdesc_offset': offset})
    return {'name': Path(label.replace('\\', '/')).stem, 'raw_label': label,
            'activity': activity or None, 'activity_id': u16(8),
            'activity_weight': u16(10), 'blend_dimensions': dimensions, 'blend_count': count,
            'blends': blends, 'frame_count_source': 'RSEQ animdesc.numframes',
            'layout_source': 'tools/apexassets/rsx_source/src/game/rtech/utils/studio/studio_r5_v16.h'}


def material_data(out, by_guid, by_name, identities):
    materials = {}
    for path in sorted((out / 'cast/material').rglob('*.json')):
        data = load_json(path)
        if '$textures' not in data:
            continue
        row = by_name.get(normal(path.relative_to(out / 'cast').with_suffix('.rpak')))
        if row is None:
            raise ValueError(f'Cannot identify material JSON: {path}')
        identities[relpath(path, out)] = row
        textures = []
        for slot, name in data['$textures'].items():
            texture = asset_reference(name, by_guid, by_name)
            if not texture:
                match = re.search(r'0x([a-f0-9]+)', name, re.I)
                texture = by_guid.get(match[1].lower().zfill(16)) if match else None
            if not texture:
                raise ValueError(f'Cannot identify texture {name} in {path}')
            guid = texture['guid']
            texture_files = []
            for folder, extension in [('cast', '.png'), ('dds', '.dds')]:
                candidates = list((out / folder).rglob('0x*' + extension))
                files = [p for p in candidates if int(p.stem[2:], 16) == int(guid, 16)]
                # Stored names can also be available in newer local builds.
                canonical = asset_file(out, folder, texture, extension)
                if canonical.is_file() and canonical not in files:
                    files.append(canonical)
                if not files:
                    raise ValueError(f'Missing {extension} for material texture {guid}')
                for file in files:
                    relative = relpath(file, out)
                    identities[relative] = texture
                    texture_files.append(relative)
            usage = data.get('$textureTypes', {}).get(slot, 'unavailable')
            textures.append({'slot': int(slot), 'usage': usage,
                             'asset_path': texture['asset_name'].replace('\\', '/'), 'guid': guid,
                             'source_rpak': texture['file_name'], 'files': sorted(texture_files)})
            # Model-local texture aliases use literal material slot meanings.
            for alias in (out / 'cast/mdl').rglob(Path(data['name']).name + usage + '.png'):
                identities[relpath(alias, out)] = texture
        item = {'asset_path': row['asset_name'].replace('\\', '/'), 'guid': row['guid'],
                'source_rpak': row['file_name'], 'name': data['name'],
                'json_file': relpath(path, out), 'textures': textures,
                'shader_type': data.get('shaderType'), 'shader_set': data.get('shaderSet')}
        materials[row['guid']] = item
    return materials


def compare_bones(left, right):
    a, b = {bone['name']: bone for bone in left}, {bone['name']: bone for bone in right}
    differences = []
    for name in sorted(a.keys() & b.keys()):
        one, two = a[name], b[name]
        position = float(np.max(np.abs(np.asarray(one['local_position']) - two['local_position'])))
        rotation = float(np.max(np.abs(quat_matrix(one['local_rotation_xyzw']) - quat_matrix(two['local_rotation_xyzw']))))
        scale = float(np.max(np.abs(np.asarray(one['local_scale']) - two['local_scale'])))
        world = float(np.max(np.abs(np.asarray(one['world_matrix']) - two['world_matrix'])))
        if one['parent_name'] != two['parent_name'] or max(position, rotation, scale, world) > 1e-5:
            differences.append({'name': name, 'octane': one, 'fuse': two,
                                'local_position_max_error': position, 'rotation_matrix_max_error': rotation,
                                'scale_max_error': scale, 'world_matrix_max_error': world})
    only_a, only_b = sorted(a.keys() - b.keys()), sorted(b.keys() - a.keys())
    return {'same_bone_names': not only_a and not only_b,
            'same_bone_order': [bone['name'] for bone in left] == [bone['name'] for bone in right],
            'same_bind_pose_by_name': not differences and not only_a and not only_b,
            'octane_bone_count': len(left), 'fuse_bone_count': len(right),
            'common_bone_count': len(a.keys() & b.keys()), 'only_octane': only_a,
            'only_fuse': only_b, 'different_common_bones': differences, 'tolerance': 1e-5}


def analyze_octane(out):
    out = Path(out).resolve()
    for directory in ('skeletons', 'sequences'):
        (out / directory).mkdir(parents=True, exist_ok=True)
    selection = load_json(out / 'export_selection.json')
    by_guid, by_name = indexes(list_rows(out))
    identities = {}
    materials = material_data(out, by_guid, by_name, identities)
    models, rigs, sequences = {}, {}, {}
    for path in sorted((out / 'cast').rglob('*.cast')):
        for node in nodes(path):
            guid = f'{node.Hash():016x}'
            row = by_guid.get(guid)
            if row is None:
                raise ValueError(f'Cannot identify Cast GUID {guid}: {path}')
            identities[relpath(path, out)] = row
            if isinstance(node, Model):
                bones = skeleton_data(node.Skeleton())
                if row['type'] == 'arig':
                    rigs[guid] = dict(asset=row, file=relpath(path, out), bone_count=len(bones), bones=bones)
                elif path.name.endswith('_LOD0.cast'):
                    info = model_data(node)
                    info.update({'asset': row, 'file': relpath(path, out), 'skin': 0,
                                 'material_count': len(node.Materials()), 'bones': bones,
                                 'material_guids': [f'{m.Hash():016x}' for m in node.Materials()]})
                    models[guid] = info
            elif isinstance(node, Animation):
                index = int(re.search(r'_(\d+)\.cast$', path.name)[1])
                info = animation_data(node)
                info.update({'file': relpath(path, out), 'blend_index': index})
                sequences.setdefault(guid, {'asset': row, 'clips': []})['clips'].append(info)
                raw_relative = path.relative_to(out / 'cast').with_name(re.sub(r'_\d+$', '', path.stem))
                for extension in ('.rseq', '.rseq_extn', '.json'):
                    raw_path = (out / 'raw' / raw_relative).with_suffix(extension)
                    if raw_path.is_file():
                        identities[relpath(raw_path, out)] = row

    qc_records = {}
    for path in sorted((out / 'smd').rglob('*.qc')):
        text, sections = qc_sections(path)
        qc_records[relpath(path, out)] = {'text': text, 'sections': sections}

    dependencies = []
    for guid, rig in rigs.items():
        path = asset_file(out, 'raw', rig['asset'], '.rson')
        refs = [asset_reference(value, by_guid, by_name) for value in rson_arrays(path).get('seqs', [])]
        dependencies.append({'rig': rig['asset'], 'raw_manifest': relpath(path, out),
                             'sequence_references': refs})
        rig['sequence_reference_count'] = len(refs)

    model_summaries, ability_summaries = [], []
    for target in selection['targets']:
        if 'asset' not in target:
            continue
        guid = target['asset']['guid']
        info = models[guid]
        skeleton_file = out / 'skeletons' / (Path(normal(target['asset_path'])).stem + '.json')
        dump(skeleton_file, {'asset': info['asset'], 'source_file': info['file'], 'bone_count': info['bone_count'],
                             'quaternion_order': 'xyzw', 'world_transform_rule': 'parent_world @ local_TRS',
                             'units': 'unchanged Source model units', 'bones': info.pop('bones')})
        info.update({'role': target['role'], 'asset_path': target['asset_path'],
                     'source_rpak': target['asset']['file_name'], 'guid': guid,
                     'skeleton_file': relpath(skeleton_file, out), 'rigs': target['rigs'],
                     'materials': [materials[material] for material in info['material_guids']]})
        model_summaries.append(info)
        if target['role'] in {'body', 'arms'}:
            continue
        refs = {row['guid']: row for row in target.get('inline_sequences', [])}
        for rig in target['rigs']:
            dependency = next(d for d in dependencies if d['rig']['guid'] == rig['guid'])
            for row in dependency['sequence_references']:
                if row:
                    refs[row['guid']] = row
        seq_list = []
        for seq_guid, row in refs.items():
            path = linked_sequence_file(out, row, [target['asset']] + target['rigs'])
            metadata = rseq_metadata(path)
            if metadata['name'].lower() != Path(normal(row['asset_name'])).stem.lower():
                raise ValueError(f'RSEQ label does not match local asset: {path}')
            exported = sequences.get(seq_guid)
            if exported is None:
                raise ValueError(f'Missing Cast sequence: {row}')
            clips = {clip['blend_index']: clip for clip in exported['clips']}
            if len(clips) != metadata['blend_count']:
                raise ValueError(f'Missing Cast blend samples: {row}')
            for blend in metadata['blends']:
                clip = clips[blend['blend_index']]
                if clip['framerate'] != blend['framerate'] or (clip['frame_count'] is not None and clip['frame_count'] != blend['frame_count']):
                    raise ValueError(f'RSEQ/Cast timing mismatch: {row}')
                blend['cast_file'] = clip['file']
                blend['cast_frame_count'] = clip['frame_count']
                blend['cast_curve_count'] = clip['curve_count']
            qc_blocks = []
            parent_qcs = {relpath(asset_file(out, 'smd', parent, '.qc'), out).lower()
                          for parent in [target['asset']] + target['rigs']}
            for qc_path, qc in qc_records.items():
                if qc_path.lower() not in parent_qcs:
                    continue
                for kind, name, block in qc['sections']:
                    if kind == 'sequence' and name.lower() == metadata['name'].lower():
                        qc_blocks.append({'file': qc_path, 'raw_qc': block})
            if not qc_blocks:
                raise ValueError(f'Missing QC sequence metadata: {row}')
            if metadata['activity'] and not any(re.search(r'\bactivity\s+"?' + re.escape(metadata['activity']) + r'"?(?:\s|$)', q['raw_qc']) for q in qc_blocks):
                raise ValueError(f'RSEQ/QC activity mismatch: {row}')
            seq_list.append(dict(metadata, asset_path=row['asset_name'].replace('\\', '/'), guid=seq_guid,
                                 source_rpak=row['file_name'], raw_file=relpath(path, out), qc=qc_blocks))
        seq_list.sort(key=lambda seq: normal(seq['asset_path']))
        summary = {'role': target['role'], 'model': target['asset'], 'rigs': target['rigs'],
                   'sequence_count': len(seq_list), 'clip_count': sum(seq['blend_count'] for seq in seq_list),
                   'sequences': seq_list}
        ability_summaries.append(summary)
        sequence_file = out / 'sequences' / (Path(normal(target['asset_path'])).stem + '.json')
        dump(sequence_file, summary)
        with sequence_file.with_suffix('.csv').open('w', encoding='utf8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['asset_path', 'guid', 'source_rpak', 'name', 'activity', 'blend_index', 'frame_count', 'framerate', 'cast_file', 'raw_file'])
            for seq in seq_list:
                for blend in seq['blends']:
                    writer.writerow([seq['asset_path'], seq['guid'], seq['source_rpak'], seq['name'], seq['activity'], blend['blend_index'], blend['frame_count'], blend['framerate'], blend['cast_file'], seq['raw_file']])
    dump(out / 'models.json', {'models': model_summaries})
    dump(out / 'rigs.json', {'rigs': list(rigs.values())})
    dump(out / 'materials.json', {'materials': list(materials.values()),
                                 'usage_note': 'Literal local RSX $textureTypes; no inferred channel packing'})
    dump(out / 'rig_dependencies.json', {'models': selection['targets'], 'rigs': dependencies})
    dump(out / 'ability_sequences.json', {'models': ability_summaries})
    dump(out / 'qc_metadata.json', {'files': [{'file': key, 'raw_qc': value['text']} for key, value in qc_records.items()]})
    compare_arms(out, selection, model_summaries, rigs)
    assign_remaining_files(out, by_guid, by_name, identities)
    write_inventory(out, identities, selection)
    result = verify_inventory(out)
    dump(out / 'verification.json', result)
    return result


def compare_arms(out, selection, models, rigs):
    arms = next(model for model in models if model['role'] == 'arms')
    reference_root = Path(selection['fuse_reference_root'])
    fuse_cast = reference_root / 'cast/mdl/weapons/arms/pov_pilot_medium_fuse_LOD0.cast'
    fuse_model = next(node for node in nodes(fuse_cast) if isinstance(node, Model))
    fuse_manifest = out / 'comparison/fuse_raw/mdl/weapons/arms/pov_pilot_medium_fuse.rson'
    fuse_links = rson_arrays(fuse_manifest)['rigs']
    octane_links = [row['asset_name'] for row in arms['rigs']]
    comparison = compare_bones(load_json(out / arms['skeleton_file'])['bones'], skeleton_data(fuse_model.Skeleton()))
    comparison.update({'octane_model': arms['asset'], 'fuse_model_cast': str(fuse_cast),
                       'fuse_model_guid': f'{fuse_model.Hash():016x}',
                       'fuse_model_manifest': relpath(fuse_manifest, out), 'fuse_rigs': fuse_links,
                       'octane_rigs': octane_links,
                       'same_referenced_rig_assets': {normal(s) for s in fuse_links} == {normal(s) for s in octane_links},
                       'referenced_rig_details': [{key: rigs[row['guid']][key] for key in ['asset', 'file', 'bone_count']}
                                                  for row in arms['rigs']]})
    dump(out / 'arms_rig_comparison.json', comparison)


def assign_remaining_files(out, by_guid, by_name, identities):
    rows = list(by_guid.values())
    for folder in EXPORT_FOLDERS:
        for path in sorted((out / folder).rglob('*')):
            if not path.is_file() or relpath(path, out) in identities:
                continue
            relative = path.relative_to(out / folder)
            row = None
            if folder == 'odl' and path.suffix == '.json':
                row = by_guid.get(load_json(path)['odlGuid'].lower().zfill(16))
            if re.fullmatch(r'0x[0-9a-f]+', path.stem, re.I):
                row = by_guid.get(path.stem[2:].lower().zfill(16))
            for extension in ('.rmdl', '.rrig', '.rseq', '.rpak'):
                if row is None:
                    row = by_name.get(normal(relative.with_suffix(extension)))
            if row is None:
                stem = re.sub(r'_lod\d+$', '', path.stem.lower())
                candidates = [asset for asset in rows if asset['type'] in {'mdl_', 'arig'}
                              and normal(relative.parent) == normal(Path(asset['asset_name'].replace('\\', '/')).parent)
                              and stem.startswith(Path(normal(asset['asset_name'])).stem + '_')]
                if len(candidates) == 1:
                    row = candidates[0]
            if row is None:
                raise ValueError(f'Exported file has no local provenance: {path}')
            identities[relpath(path, out)] = row


def write_inventory(out, identities, selection):
    assets = {}
    for relative, row in sorted(identities.items()):
        path = out / relative
        guid = row['guid'].lower().zfill(16)
        asset = assets.setdefault(guid, {'asset_path': row['asset_name'].replace('\\', '/'),
                                        'source_rpak': row['file_name'], 'guid': guid,
                                        'type': row['type'], 'output_files': []})
        asset['output_files'].append({'path': relative, 'size': path.stat().st_size})
    derived = []
    for directory in ('skeletons', 'sequences', 'comparison', 'lists'):
        for path in sorted((out / directory).rglob('*')):
            if path.is_file():
                derived.append({'path': relpath(path, out), 'size': path.stat().st_size})
    for path in sorted(out.glob('*.json')):
        if path.name not in {'inventory.json', 'verification.json', 'fuse_comparison.json'}:
            derived.append({'path': path.name, 'size': path.stat().st_size})
    outputs = [file for asset in assets.values() for file in asset['output_files']] + derived
    dump(out / 'inventory.json', {'schema_version': 2, 'legend': 'octane', 'skin': 0,
                                 'path_base': '.', 'verification': 'presence, sizes, provenance, Cast/SMD/QC/RSEQ consistency',
                                 'scope': 'All Cast/raw/SMD/QC/PNG/DDS/ODL exports and derived analysis; runtime logs, caches, Fuse regression and inventory/verification itself are excluded.',
                                 'assets': sorted(assets.values(), key=lambda asset: normal(asset['asset_path'])),
                                 'derived_files': derived, 'pending': selection['pending'],
                                 'totals': {'asset_count': len(assets), 'file_count': len(outputs),
                                            'bytes': sum(file['size'] for file in outputs)}})


def verify_inventory(out):
    """Read-only: validate listed files, sizes, coverage and cross-format content."""
    out = Path(out).resolve()
    inventory = load_json(out / 'inventory.json')
    if inventory.get('legend') != 'octane' or inventory.get('schema_version') != 2:
        raise ValueError('Expected a T014 Octane content-check inventory')
    records = [file for asset in inventory['assets'] for file in asset['output_files']] + inventory['derived_files']
    paths, failures = set(), []
    for record in records:
        relative = record['path']
        path = (out / relative).resolve()
        if not path.is_relative_to(out) or Path(relative).is_absolute():
            failures.append({'path': relative, 'reason': 'Path escapes output directory'})
            continue
        if relative.lower() in paths:
            failures.append({'path': relative, 'reason': 'Duplicate inventory path'})
        paths.add(relative.lower())
        if not path.is_file():
            failures.append({'path': relative, 'reason': 'Missing file'})
        elif path.stat().st_size != record['size']:
            failures.append({'path': relative, 'reason': 'Size mismatch'})
    for folder in EXPORT_FOLDERS:
        for path in (out / folder).rglob('*'):
            if path.is_file() and relpath(path, out).lower() not in paths:
                failures.append({'path': relpath(path, out), 'reason': 'Export not covered by inventory'})
    models = load_json(out / 'models.json')['models']
    ability = load_json(out / 'ability_sequences.json')['models']
    # Cross-format verification catches an
    # exporter silently skipping a mesh or exporting a loading placeholder.
    from verify_assets import read_smd
    mesh_checks = []
    for model in models:
        raw = asset_file(out, 'raw', model['asset'], '.rmdl')
        qc = asset_file(out, 'smd', model['asset'], '.qc')
        if not raw.is_file() or not qc.is_file() or not model['rigs']:
            failures.append({'path': model['asset_path'], 'reason': 'Missing model raw/QC/rig links'})
            continue
        skeleton = load_json(out / model['skeleton_file'])['bones']
        smds = sorted(qc.parent.glob(qc.stem + '_*_lod0.smd'))
        triangles, error = 0, 0.0
        for path in smds:
            bones, transforms, count = read_smd(path)
            triangles += count
            if bones != [(bone['index'], bone['name'], bone['parent_index']) for bone in skeleton]:
                failures.append({'path': relpath(path, out), 'reason': 'SMD/Cast bone hierarchy mismatch'})
            for bone in skeleton:
                error = max(error, float(np.max(np.abs(np.asarray(transforms[bone['index']][:3]) - bone['local_position']))))
        if triangles != model['triangles'] or error >= 1e-4:
            failures.append({'path': model['file'], 'reason': 'SMD/Cast geometry or rest-position mismatch'})
        mesh_checks.append({'model': model['asset_path'], 'bone_count': model['bone_count'],
                            'triangles': triangles, 'smd_cast_max_position_error': error})
    sequence_guids = {seq['guid'] for model in ability for seq in model['sequences']}
    for model in ability:
        for seq in model['sequences']:
            if not seq['blends'] or not seq['qc']:
                failures.append({'path': seq['asset_path'], 'reason': 'Missing sequence blends/QC'})
            for blend in seq['blends']:
                if blend['cast_file'].lower() not in paths or not (out / seq['raw_file']).is_file():
                    failures.append({'path': seq['asset_path'], 'reason': 'Missing sequence Cast/raw'})
    if failures:
        raise ValueError(json.dumps({'status': 'failed', 'failures': failures}, ensure_ascii=False, indent=2))
    return {'status': 'passed', 'verified_files': len(records), 'verified_assets': len(inventory['assets']),
            'model_count': len(models), 'rig_count': len(load_json(out / 'rigs.json')['rigs']),
            'material_count': len(load_json(out / 'materials.json')['materials']),
            'texture_count': sum(asset['type'] == 'txtr' for asset in inventory['assets']),
            'ability_sequence_count': len(sequence_guids),
            'ability_clip_count': sum(model['clip_count'] for model in ability),
            'mesh_checks': mesh_checks, 'pending': inventory['pending']}
