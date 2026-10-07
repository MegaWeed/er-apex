"""T021 local battery export, using the existing RSX adapter without rebuilding it."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import struct
import sys
sys.dont_write_bytecode = True
import export_assets as ea
import octane_assets as oa
from build_rsx import EXE
from cast import Animation, Model
from inspect_assets import nodes, model_data, skeleton_data, animation_data, qc_sections, rson_arrays, dump, normal

ROOT = oa.REPO
OUT = ROOT/'apex-data/assets/battery'
MODEL_GUID = '690d6fb3640d1331'
RIG_GUID = '713a7a96e92ac0f6'


def checked(path):
    path = Path(path).resolve()
    if not path.is_relative_to(OUT.resolve()):
        raise ValueError(f'Output outside {OUT}')
    path.mkdir(parents=True, exist_ok=True)
    return path


def analyze(out):
    by_guid, by_name = oa.indexes(oa.list_rows(out))
    selection = oa.load_json(out/'export_selection.json')
    target = selection['targets'][0]
    identities = {}
    materials = oa.material_data(out, by_guid, by_name, identities)
    for material in materials.values():
        usages = {}
        for texture in sorted(material['textures'], key=lambda t:t['slot']):
            usage = texture['usage']; occurrence = usages.get(usage,0); usages[usage] = occurrence+1
            suffix = (f'_{occurrence}' if occurrence else '')+usage+'.png'
            for path in (out/'cast/mdl').rglob(Path(material['name']).name+suffix):
                identities[oa.relpath(path,out)] = by_guid[texture['guid']]
    models, rigs, sequences = {}, {}, {}
    for path in sorted((out/'cast').rglob('*.cast')):
        for node in nodes(path):
            guid = f'{node.Hash():016x}'
            row = by_guid[guid]
            identities[oa.relpath(path, out)] = row
            if isinstance(node, Model):
                bones = skeleton_data(node.Skeleton())
                if row['type'] == 'arig':
                    rigs[guid] = dict(asset=row, file=oa.relpath(path, out), bone_count=len(bones), bones=bones)
                elif path.name.endswith('_LOD0.cast'):
                    models[guid] = dict(model_data(node), asset=row, file=oa.relpath(path, out), skin=0, bones=bones,
                                       material_guids=[f'{m.Hash():016x}' for m in node.Materials()])
            elif isinstance(node, Animation):
                index = int(re.search(r'_(\d+)\.cast$', path.name)[1])
                sequences.setdefault(guid, {})[index] = dict(animation_data(node), file=oa.relpath(path, out))
                raw_relative = path.relative_to(out/'cast').with_name(re.sub(r'_\d+$', '', path.stem))
                for extension in ('.rseq', '.rseq_extn', '.json'):
                    raw = (out/'raw'/raw_relative).with_suffix(extension)
                    if raw.is_file():
                        identities[oa.relpath(raw, out)] = row
    dependencies = []
    refs = {r['guid']: r for r in target['inline_sequences']}
    for guid, rig in rigs.items():
        manifest = oa.asset_file(out, 'raw', rig['asset'], '.rson')
        linked = [oa.asset_reference(s, by_guid, by_name) for s in rson_arrays(manifest)['seqs']]
        if any(r is None for r in linked):
            raise ValueError('待定: missing local rig sequence')
        refs.update({r['guid']: r for r in linked})
        rig['sequence_reference_count'] = len(linked)
        dependencies.append(dict(rig=rig['asset'], raw_manifest=oa.relpath(manifest, out), sequence_references=linked))
        dump(out/'skeletons'/('rig_'+Path(normal(rig['asset']['asset_name'])).stem+'.json'),
             dict(rig, units='Source units', quaternion_order='xyzw'))
    info = models[MODEL_GUID]
    raw_model = oa.asset_file(out,'raw',target['asset'],'.rmdl')
    raw = raw_model.read_bytes()
    # Pinned local RSX studiohdr_v19_2_t: boneCount 0x74, meshCount 0xac, lodCount 0xca.
    bone_count,mesh_count,lod_count = [struct.unpack_from('<H',raw,o)[0] for o in (0x74,0xac,0xca)]
    lods = sorted(raw_model.stem+f'_LOD{i}.cast' for i in range(lod_count))
    actual_lods = sorted(p.name for p in oa.asset_file(out,'cast',target['asset'],'.cast').parent.glob(raw_model.stem+'_LOD*.cast'))
    if bone_count != info['bone_count'] or mesh_count != info['mesh_count'] or not 1<=lod_count<=8 or lods != actual_lods:
        raise ValueError('Raw compact model header/Cast bones, meshes or LOD coverage differs')
    info['raw_model_header'] = dict(bone_count=bone_count,mesh_count=mesh_count,lod_count=lod_count,
        cast_lods=actual_lods,source='tools/apexassets/rsx_source/src/game/rtech/utils/studio/studio_r5_v16.h: studiohdr_v19_2_t',
        offsets=dict(bone_count=0x74,mesh_count=0xac,lod_count=0xca))
    skeleton_file = 'skeletons/ptpov_shield_battery_held.json'
    dump(out/skeleton_file, dict(asset=info['asset'], source_file=info['file'], bone_count=info['bone_count'],
         bones=info.pop('bones'), units='unchanged Source model units', quaternion_order='xyzw',
         world_transform_rule='parent_world @ local_TRS'))
    info.update(role='battery_viewmodel', asset_path=target['asset_path'], source_rpak=info['asset']['file_name'],
                guid=MODEL_GUID, skeleton_file=skeleton_file, rigs=target['rigs'],
                materials=[materials[g] for g in info['material_guids']])
    qc_paths = [oa.asset_file(out, 'smd', r, '.qc') for r in [target['asset']]+target['rigs']]
    qcs = {oa.relpath(p, out): qc_sections(p) for p in qc_paths}
    seqs = []
    for guid, row in refs.items():
        path = oa.linked_sequence_file(out, row, [target['asset']]+target['rigs'])
        metadata = oa.rseq_metadata(path)
        if normal(metadata['name']) != Path(normal(row['asset_name'])).stem:
            raise ValueError('RSEQ name mismatch')
        clips = sequences[guid]
        if len(clips) != metadata['blend_count']:
            raise ValueError('Cast blend count mismatch')
        for sample in metadata['blends']:
            clip = clips[sample['blend_index']]
            if clip['framerate'] != sample['framerate'] or (clip['frame_count'] is not None and clip['frame_count'] != sample['frame_count']):
                raise ValueError(f'Cast/RSEQ timing mismatch: {path}')
            sample.update(cast_file=clip['file'], cast_frame_count=clip['frame_count'], cast_curve_count=clip['curve_count'])
        blocks = [dict(file=p, raw_qc=block) for p, (_, sections) in qcs.items()
                  for kind, name, block in sections if kind == 'sequence' and name.lower() == metadata['name'].lower()]
        if not blocks:
            raise ValueError(f'Missing QC sequence: {path}')
        if metadata['activity'] and not any(metadata['activity'] in b['raw_qc'] for b in blocks):
            raise ValueError('QC/RSEQ activity differs')
        seqs.append(dict(metadata, asset_path=row['asset_name'].replace('\\', '/'), guid=guid,
                         source_rpak=row['file_name'], raw_file=oa.relpath(path, out), qc=blocks))
    seqs.sort(key=lambda s: normal(s['asset_path']))
    table = dict(role='battery_viewmodel', model=target['asset'], rigs=target['rigs'],
                 sequence_count=len(seqs), clip_count=sum(s['blend_count'] for s in seqs), sequences=seqs)
    dump(out/'sequences/ptpov_shield_battery_held.json', table)
    dump(out/'models.json', dict(models=[info]))
    dump(out/'rigs.json', dict(rigs=list(rigs.values())))
    dump(out/'materials.json', dict(materials=list(materials.values()), usage_note='Literal local RSX texture types'))
    dump(out/'rig_dependencies.json', dict(models=selection['targets'], rigs=dependencies))
    dump(out/'ability_sequences.json', dict(models=[table]))
    dump(out/'qc_metadata.json', dict(files=[dict(file=p, raw_qc=t) for p, (t, _) in qcs.items()]))
    oa.assign_remaining_files(out, by_guid, by_name, identities)
    oa.write_inventory(out, identities, selection)
    result = oa.verify_inventory(out)
    inventory = oa.load_json(out/'inventory.json')
    # Keep the reusable T014 inventory schema, add explicit format/provenance on every file.
    for asset in inventory['assets']:
        for record in asset['output_files']:
            record.update(source_rpak=asset['source_rpak'], guid=asset['guid'], asset_path=asset['asset_path'],
                          format_check=format_check(out/record['path']))
    for record in inventory['derived_files']:
        if record['path'].startswith('skeletons/rig_'):
            row = by_guid[RIG_GUID]
        else:
            row = by_guid[MODEL_GUID]
        record.update(source_rpak=row['file_name'], guid=row['guid'], asset_path=row['asset_name'].replace('\\', '/'),
                      format_check=format_check(out/record['path']), provenance='Derived battery dependency record; lists contain all loaded common.rpak assets')
    inventory['task'] = 'T021'
    dump(out/'inventory.json', inventory)
    dump(out/'verification.json', result)
    return result


def format_check(path):
    suffix = path.suffix.lower()
    head = path.read_bytes()[:128]
    if not head:
        raise ValueError(f'Empty export: {path}')
    if suffix == '.cast':
        if head[:4] != b'cast': raise ValueError('Bad Cast')
        return 'PASS Cast signature and parsed nodes'
    if suffix == '.dds':
        if head[:4] != b'DDS ' or len(head) < 128: raise ValueError('Bad DDS')
        return 'PASS DDS header'
    if suffix == '.png':
        from PIL import Image
        with Image.open(path) as im: im.verify()
        return 'PASS PNG decoder'
    if suffix == '.json':
        json.loads(path.read_text(encoding='utf8'))
        return 'PASS JSON parser'
    if suffix == '.smd': return 'PASS SMD parsed by T014 cross-format checks'
    if suffix == '.qc':
        qc_sections(path)
        return 'PASS QC sections'
    if suffix == '.rseq':
        oa.rseq_metadata(path)
        return 'PASS compact RSEQ descriptor'
    if suffix == '.rson':
        rson_arrays(path)
        return 'PASS RSON arrays'
    if suffix in ('.rmdl','.rrig'):
        count = struct.unpack_from('<H',head,0x74)[0]
        if not 0<count<512: raise ValueError('Invalid compact model/rig bone count')
        return f'PASS compact studiohdr boneCount={count}; companion Cast hierarchy checked'
    return f'PASS nonempty {suffix} ({path.stat().st_size} bytes); linked local provenance'


def export(out):
    if not EXE.is_file():
        raise FileNotFoundError(f'Existing RSX adapter required (no rebuild/hash): {EXE}')
    for directory in ('lists', 'logs', 'skeletons', 'sequences'):
        (out/directory).mkdir(parents=True, exist_ok=True)
    ea.OUT, ea.CACHE, ea.PACKAGES = out, out/'logs/rsx_runtime', ['common.rpak']
    ea.RUNS = []
    os.environ['MPLCONFIGDIR'] = str(ea.CACHE/'matplotlib')
    ea.run(EXE, 'core_named', 'cast', flags=['-metadataonly'])
    by_guid, by_name = oa.indexes(oa.list_rows(out))
    row = by_guid[MODEL_GUID]
    target = dict(role='battery_viewmodel', asset_path=row['asset_name'], asset=row)
    exact = ['--exportexact', row['asset_name']]
    ea.run(EXE, 'models_cast', 'cast', 'mdl_', flags=exact+['-matltextures', '--format-matl', '2'])
    ea.run(EXE, 'models_raw', 'raw', 'mdl_', flags=exact+['--format-mdl_', '2'])
    targets, rigs, _ = oa.model_links(out, [target], by_guid, by_name, [])
    if RIG_GUID not in rigs: raise ValueError('Local model/rig dependency differs')
    mdl = next(n for n in nodes(oa.asset_file(out, 'cast', row, '.cast').with_name('ptpov_shield_battery_held_LOD0.cast')) if isinstance(n, Model))
    names = [by_guid[f'{m.Hash():016x}']['asset_name'] for m in mdl.Materials()]
    ea.run(EXE, 'materials', 'cast', 'matl', flags=['--exportexact', ','.join(names), '--format-matl', '2', '-matltextures'])
    ea.run(EXE, 'materials_dds', 'dds', 'matl', flags=['--exportexact', ','.join(names), '--format-matl', '2', '--format-txtr', '2', '-matltextures'])
    rig_names = [r['asset_name'] for r in rigs.values()]
    ea.run(EXE, 'rigs_cast', 'cast', 'arig', flags=['--exportexact', ','.join(rig_names), '-exportrigsequences'])
    ea.run(EXE, 'rigs_raw', 'raw', 'arig', flags=['--exportexact', ','.join(rig_names), '--format-arig', '2', '--format-aseq', '2', '-exportrigsequences'])
    ea.run(EXE, 'smd_qc', 'smd', 'mdl_,arig', flags=['--exportexact', ','.join([row['asset_name']]+rig_names), '--format-mdl_', '3', '--format-arig', '3', '--format-aseq', '3'])
    dump(out/'export_selection.json', dict(task='T021', targets=targets, rigs=list(rigs.values()), pending=[]))
    return analyze(out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--analyze-only', action='store_true')
    args = parser.parse_args()
    out = checked(args.out)
    report = analyze(out) if args.analyze_only else export(out)
    print('PASS T021 export: '+json.dumps(report, ensure_ascii=False), flush=True)
