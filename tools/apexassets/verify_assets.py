"""Meaningful acceptance checks across independent Cast/SMD and MBNK/RSX paths."""
import json
from pathlib import Path
import re
import struct
import time

import numpy as np
from export_assets import OUT, read_wave
from inspect_assets import nodes, skeleton_data, quat_matrix
from cast import Model
from rtech_hash import string_to_guid


def read_smd(path):
    lines = path.read_text(encoding='utf8').splitlines()
    begin = lines.index('nodes') + 1
    end = lines.index('end', begin)
    bones = []
    for line in lines[begin:end]:
        match = re.fullmatch(r'\s*(\d+)\s+"([^"]+)"\s+(-?\d+)\s*', line)
        if not match:
            raise ValueError(f'Invalid SMD node: {line}')
        bones.append((int(match[1]), match[2], int(match[3])))
    begin = lines.index('skeleton') + 1
    end = lines.index('end', begin)
    frame = [line.split() for line in lines[begin:end] if line.strip() and not line.lstrip().startswith('time')]
    transforms = {int(parts[0]): [float(v) for v in parts[1:]] for parts in frame}
    triangles = 0
    if 'triangles' in lines:
        begin = lines.index('triangles') + 1
        end = lines.index('end', begin)
        payload = [line for line in lines[begin:end] if line.strip()]
        if len(payload) % 4:
            raise ValueError('SMD triangle section is not material+3 vertices')
        triangles = len(payload) // 4
    return bones, transforms, triangles


def verify(out=OUT):
    OUT = Path(out)
    start = time.perf_counter()
    model_path = OUT / 'cast/mdl/Humans/class/medium/pilot_medium_fuse_LOD0.cast'
    model = next(n for n in nodes(model_path) if isinstance(n, Model))
    skeleton = skeleton_data(model.Skeleton())
    smds = sorted((OUT / 'smd/mdl/Humans/class/medium').glob('pilot_medium_fuse_*_lod0.smd'))
    if not smds:
        raise ValueError('Missing Fuse SMD LOD0 files')
    triangles, position_error = 0, 0.0
    for path in smds:
        bones, transforms, faces = read_smd(path)
        triangles += faces
        assert [(b['index'], b['name'], b['parent_index']) for b in skeleton] == bones
        for bone in skeleton:
            values = transforms[bone['index']]
            position_error = max(position_error, float(np.max(np.abs(np.asarray(values[:3])-bone['local_position']))))
    cast_triangles = sum(m.FaceCount() for m in model.Meshes())
    assert triangles == cast_triangles, (triangles, cast_triangles)
    assert position_error < 1e-4

    sequences = json.loads((OUT / 'fuse_sequences.json').read_text(encoding='utf8'))
    dependencies = json.loads((OUT / 'rig_dependencies.json').read_text(encoding='utf8'))
    references = {row['guid'].lower().zfill(16) for rig in dependencies['rigs'] for row in rig['sequence_references']}
    exported = {seq['guid'] for seq in sequences['sequences']}
    missing = sorted(references-exported)
    extra = sorted(exported-references)
    assert not missing and not extra, {'missing': missing, 'extra': extra}
    assert all(seq['clips'] for seq in sequences['sequences'])
    examples = []
    sample_names = ['fuse_idle_rifle', 'fuse_run_rifle_F', 'fuse_sprint_rifle',
                    'fuse_slide_rifle', 'medium_jump_rifle_F', 'mp_pt_medium_reload_rspn101',
                    'fuse_idle_rifle_fire', 'fuse_idle_rifle_ADS']
    for name in sample_names:
        seq = next(s for s in sequences['sequences'] if s['asset']['asset_name'].replace('\\', '/').rsplit('/', 1)[-1].lower() == name.lower()+'.rseq')
        examples.append({'asset_name': seq['asset']['asset_name'], 'guid': seq['guid'],
                         'clips': [{key: c[key] for key in ['file', 'framerate', 'frame_count', 'bone_count', 'curve_count', 'root_motion_in_cast', 'notification_tracks']}
                                   for c in seq['clips']], 'qc_metadata_count': len(seq.get('qc_metadata', []))})

    materials = json.loads((OUT / 'materials.json').read_text(encoding='utf8'))['materials']
    assert materials and all(t['file'] and (OUT / t['file']).is_file() for m in materials for t in m['textures'])
    audio = json.loads((OUT / 'audio_inventory.json').read_text(encoding='utf8'))
    assert audio['available_source_count'] == audio['available_by_raw_table']
    assert audio['full_bank_source_count'] == 2614241 and audio['event_count'] == 138083
    samples = [read_wave(path, OUT) for path in sorted((OUT / 'samples').rglob('*.wav'))]
    assert len(samples) == 3
    assert (OUT / samples[0]['path']).read_bytes() != (OUT / samples[1]['path']).read_bytes()
    odl = json.loads(next((OUT / 'odl').rglob('*.json')).read_text(encoding='utf8'))
    assert odl['originalAssetGuid'] == f'{model.Hash():016x}'
    assert int(odl['odlGuid'], 16) == string_to_guid('odl_asset/ce427f84.rpak')
    for view in ['front', 'side']:
        from PIL import Image
        image = Image.open(OUT / f'preview/pilot_medium_fuse_{view}.png')
        assert image.width > 500 and image.height > 700
    result = {'status': 'passed', 'seconds': time.perf_counter()-start,
              'fuse_cast_smd_triangle_count': cast_triangles, 'bone_count': len(skeleton),
              'smd_cast_max_local_position_error': position_error,
              'rig_unique_sequence_references': len(references), 'cast_unique_sequences': len(exported),
              'missing_sequences': missing, 'extra_sequences': extra,
              'clip_count': sequences['clip_count'], 'notification_track_count': sequences['notification_track_count'],
              'sample_sequences': examples, 'material_count': len(materials),
              'audio_event_count': audio['event_count'], 'audio_bank_source_count': audio['full_bank_source_count'],
              'audio_available_source_count': audio['available_source_count'], 'audio_samples': samples,
              'odl': odl}
    (OUT / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: v for k, v in result.items() if k not in ['sample_sequences', 'audio_samples', 'odl']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legend', choices=['fuse', 'octane'], default='fuse')
    parser.add_argument('--output-dir', '--output', type=Path)
    args = parser.parse_args()
    out = args.output_dir or (OUT / 'octane' if args.legend == 'octane' else OUT)
    if args.legend == 'octane':
        from octane_assets import verify_inventory
        print(json.dumps(verify_inventory(out), ensure_ascii=False, indent=2))
    else:
        verify(out)
