"""Export only local Cast/QC data. No game, network, or repository writes outside anim/."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
import zlib

import numpy as np
from PIL import Image, ImageDraw

from cast import Animation, Cast

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'apex-data/assets'
OUT = ROOT / 'apex-data/anim'
NAMES = [
    'fuse_idle_rifle', 'fuse_idle_rifle_ADS', 'fuse_idle_rifle_fire',
    'fuse_idle_rifle_fire_ADS', 'fuse_walk_rifle_F', 'fuse_run_rifle_F',
    'medium_walk_rifle_B', 'medium_run_rifle_B',
    'fuse_sprint_rifle', 'mirage_crouch_rifle', 'medium_crouchWalk_rifle_F',
    'medium_crouchWalk_rifle_B', 'fuse_slide_rifle', 'fuse_slideEnd_rifle_F',
    'fuse_slideEnd_rifle_L', 'fuse_slideEnd_rifle_R', 'fuse_slideEnd_rifle_BL',
    'fuse_slideEnd_rifle_BR', 'medium_jump_rifle_F', 'medium_jump_rifle_B',
    'medium_float_rifle_F', 'medium_float_rifle_B', 'medium_land_rifle',
    'mp_pt_medium_WallMantle_Above', 'mp_pt_medium_WallMantle_Below',
    'mp_pt_medium_WallMantle_Level', 'mp_pt_medium_WallMantle_HighAbove',
    'mp_pt_medium_wallrun_up', 'mp_pt_medium_reload_rspn101',
    'mp_pt_medium_reload_rspn101_crouch',
]


def load_json(name):
    return json.loads((ASSETS / name).read_text(encoding='utf8'))


def text(s):
    value = s.encode('utf8')
    if len(value) > 65535:
        raise ValueError('string exceeds u16')
    return struct.pack('<H', len(value)) + value


def normalize(q):
    return q / np.linalg.norm(q, axis=-1, keepdims=True)


def mul(a, b):
    x, y, z, w = np.moveaxis(a, -1, 0)
    X, Y, Z, W = np.moveaxis(b, -1, 0)
    return np.stack((w*X+x*W+y*Z-z*Y, w*Y-x*Z+y*W+z*X,
                     w*Z+x*Y-y*X+z*W, w*W-x*X-y*Y-z*Z), axis=-1)


def slerp(a, b, t):
    a, b = normalize(a), normalize(b)
    dot = np.sum(a*b, axis=-1, keepdims=True)
    b = np.where(dot < 0, -b, b)
    dot = np.minimum(np.abs(dot), 1.0)
    theta = np.arccos(dot)
    denom = np.maximum(np.sin(theta), 1e-15)
    q = np.where(dot > .9995, (1-t)*a+t*b,
                 np.sin((1-t)*theta)/denom*a + np.sin(t*theta)/denom*b)
    return normalize(q)


def angle_error(a, b):
    a, b = normalize(a), normalize(b)
    b = np.where(np.sum(a*b, axis=-1, keepdims=True) < 0, -b, b)
    # atan2/chord avoids acos cancellation near identical quaternions.
    return np.rad2deg(4*np.arctan2(np.linalg.norm(a-b, axis=-1),
                                 np.linalg.norm(a+b, axis=-1)))


def quantize(q):
    return np.rint(normalize(q)*32767).astype('<i2')


def nodes(path):
    def walk(n):
        yield n
        for c in n.childNodes:
            yield from walk(c)
    for r in Cast.load(str(path)).Roots():
        yield from walk(r)


def decode(path, bones):
    a = next(n for n in nodes(path) if isinstance(n, Animation))
    if a.CurveModeOverrides():
        raise ValueError('v0 export rejects curve mode overrides')
    curves = a.Curves()
    if not curves:
        raise ValueError(f'empty animation: {path}')
    frames = max(max(c.KeyFrameBuffer()) for c in curves) + 1
    lookup = {b['name']: i for i, b in enumerate(bones)}
    grouped, unmapped = {}, set()
    for c in curves:
        if c.NodeName() not in lookup:
            unmapped.add(c.NodeName())
            continue
        group = grouped.setdefault(lookup[c.NodeName()], {})
        if c.KeyPropertyName() in group:
            raise ValueError('duplicate Cast channel')
        group[c.KeyPropertyName()] = c
    tracks = []
    modes = {c.Mode() for c in curves}
    if len(modes) != 1 or not modes <= {'absolute', 'additive'}:
        raise ValueError(f'unsupported/mixed modes: {modes}')
    additive = modes == {'additive'}
    for idx, group in sorted(grouped.items()):
        channels, weights = [], []
        for props, width in [(('tx', 'ty', 'tz'), 3), (('rq',), 4),
                             (('sx', 'sy', 'sz'), 3)]:
            present = [prop in group for prop in props]
            if not any(present):
                channels.append(None)
                weights.append(1.)
                continue
            if not all(present):
                raise ValueError(f'partial channel vector at {path}:{idx}')
            values = []
            for prop in props:
                c = group[prop]
                keys = np.array(c.KeyFrameBuffer())
                v = np.array(c.KeyValueBuffer(), dtype=np.float64)
                if prop == 'rq':
                    v = v.reshape(-1, 4)
                else:
                    v = v[:, None]
                if len(v) != len(keys) or np.any(np.diff(keys) <= 0):
                    raise ValueError('invalid Cast key buffers')
                if prop == 'rq':
                    left = np.clip(np.searchsorted(keys, np.arange(frames), side='right')-1, 0, len(keys)-1)
                    right = np.minimum(left+1, len(keys)-1)
                    t = ((np.arange(frames)-keys[left])/np.maximum(keys[right]-keys[left], 1))[:, None]
                    values.append(slerp(v[left], v[right], np.clip(t, 0, 1)))
                else:
                    values.append(np.interp(np.arange(frames), keys, v[:, 0])[:, None])
            channels.append(np.concatenate(values, axis=1))
            ws = {group[p].AdditiveBlendWeight() for p in props}
            if len(ws) != 1:
                raise ValueError('component weights differ')
            weights.append(ws.pop())
        if not set(group) <= {'tx', 'ty', 'tz', 'rq', 'sx', 'sy', 'sz'}:
            raise ValueError(f'unknown channels: {set(group)}')
        tracks.append({'bone': idx, 'mode': int(additive), 'weights': weights,
                       'channels': channels})
    return a, frames, tracks, sorted(unmapped)


def rest_pose(bones):
    return np.array([b['local_position'] + b['local_rotation_xyzw'] +
                     b['local_scale'] for b in bones], dtype=np.float64)


def pose_at(rest, tracks, frame, root=None):
    pose = rest.copy()
    for tr in tracks:
        idx = tr['bone']
        for j, (offset, width) in enumerate(((0, 3), (3, 4), (7, 3))):
            v = tr['channels'][j]
            if v is None:
                continue
            v = v[frame]
            if not tr['mode']:
                pose[idx, offset:offset+width] = v
            elif j == 0:
                pose[idx, :3] += tr['weights'][j]*v
            elif j == 1:
                pose[idx, 3:7] = normalize(mul(pose[idx, 3:7], slerp(
                    np.array([0., 0., 0., 1.]), v, tr['weights'][j])))
            else:
                pose[idx, 7:] *= 1 + tr['weights'][j]*(v-1)
    if root is not None:
        pose[root['bone'], :3] = root['channels'][0][0]
        pose[root['bone'], 3:7] = root['channels'][1][0]
    return pose


def packed_channel(v, rotation):
    if v is None:
        return struct.pack('<I', 0)
    v = quantize(v) if rotation else np.asarray(v, dtype='<f4')
    if np.all(v == v[0]):
        v = v[:1]
    return struct.pack('<I', len(v)) + v.tobytes()


def rigid_mul(a, b):
    q, v = a[3:], b[:3]
    u = q[:3]
    t = a[:3] + v + 2*np.cross(u, np.cross(u, v)+q[3]*v)
    return np.concatenate((t, normalize(mul(q, b[3:]))))


def rigid_inverse(a):
    q = a[3:]*np.array([-1., -1., -1., 1.])
    u, v = q[:3], -a[:3]
    t = v + 2*np.cross(u, np.cross(u, v)+q[3]*v)
    return np.concatenate((t, q))


def root_reference(root, frame, cycles=0):
    identity = np.array([0., 0., 0., 0., 0., 0., 1.])
    if root is None:
        return identity
    t, q = root['channels'][:2]
    i = int(frame)
    if frame == i:
        current = np.concatenate((t[i], q[i]))
    else:
        current = np.concatenate(((t[i]+t[i+1])*.5, slerp(q[i], q[i+1], .5)))
    first_inverse = rigid_inverse(np.concatenate((t[0], q[0])))
    current = rigid_mul(first_inverse, current)
    cycle = rigid_mul(first_inverse, np.concatenate((t[-1], q[-1])))
    for _ in range(cycles):
        current = rigid_mul(cycle, current)
    return current


def qc_info(seq, qcfiles):
    rig = seq['referenced_by_rigs'][0].replace('\\', '/')
    qcpath = 'smd/' + rig.removesuffix('.rrig') + '.qc'
    qcf = next(q for q in qcfiles if q['file'] == qcpath)
    name = seq['asset']['asset_name'].replace('\\', '/').rsplit('/', 1)[-1][:-5]
    matches = [q for q in qcf['sequences'] if q['name'] == name]
    if len(matches) != 1:
        raise ValueError(f'ambiguous QC: {name}')
    raw = matches[0]['raw_qc']
    axes = [{'name': m[0], 'min': float(m[1]), 'max': float(m[2])}
            for m in re.findall(r'\bblend\s+"([^"]+)"\s+(-?[\d.]+)\s+(-?[\d.]+)', raw)]
    events = []
    for line in matches[0]['event_lines']:
        m = re.search(r'event\s+"([^"]+)"\s+(\d+)(?:\s+"([^"]*)")?', line)
        if not m:
            raise ValueError(f'unrecognized event: {line}')
        events.append({'frame': int(m[2]), 'name': m[1], 'parameter': m[3] or ''})
    before = raw.split('blendwidth')[0].split('blend ')[0]
    tokens = re.findall(r'"([^"]+)"', before)[1:]
    return dict(qc_file=qcpath, raw_qc=raw, axes=axes, sample_tokens=tokens,
                activities=re.findall(r'\bactivity\s+"([^"]+)"\s+(-?\d+)', raw),
                modifiers=re.findall(r'activitymodifier\s+"([^"]+)"', raw),
                layers=re.findall(r'(?:addlayer|autolayer)\s+"([^"]+)"', raw),
                events=sorted(events, key=lambda e: e['frame']), rig=rig)


def world_positions(pose, bones):
    world_t, world_q, world_s = [], [], []
    for trs, b in zip(pose, bones):
        t, q, s = trs[:3], trs[3:7], trs[7:]
        p = b['parent_index']
        if p >= 0:
            v = world_s[p]*t
            u = world_q[p][:3]
            t = world_t[p] + v + 2*np.cross(u, np.cross(u, v)+world_q[p][3]*v)
            q = normalize(mul(world_q[p], q))
            s = world_s[p]*s
        world_t.append(t)
        world_q.append(q)
        world_s.append(s)
    return np.array(world_t)


def preview(name, rest, tracks, root, frames, bones):
    picks = np.linspace(0, frames-1, 6).astype(int)
    image = Image.new('RGB', (1440, 470), '#f5f5f1')
    draw = ImageDraw.Draw(image)
    # Local skeletons are Y-up; exported root rotation puts them in Z-up.
    worlds = []
    for f in picks:
        pose = pose_at(rest, tracks, int(f), root)
        if root is not None:
            pose[root['bone'], :3] = root['channels'][0][f]
            pose[root['bone'], 3:7] = root['channels'][1][f]
        w = world_positions(pose, bones)
        w[:, :2] -= w[0, :2]  # center travel horizontally, keep climb height
        worlds.append(w)
    chains = [('def_c_hip', 'def_c_spineC', 'def_c_neckA', 'def_c_head')]
    for side in ('l', 'r'):
        chains.append(('def_c_spineC', f'def_{side}_clav', f'def_{side}_shoulder',
                       f'def_{side}_elbow', f'def_{side}_wrist'))
        chains.append(('def_c_hip', f'def_{side}_thigh', f'def_{side}_knee',
                       f'def_{side}_ankle', f'def_{side}_ball'))
    lookup = {b['name']: i for i, b in enumerate(bones)}
    visible_indices = [lookup[name] for name in {n for chain in chains for n in chain}]
    points = np.concatenate([w[visible_indices] for w in worlds])
    height = max(float(np.ptp(points[:, 2])), 50.)
    scale = min(5.3, 350/height)
    for column, (f, w) in enumerate(zip(picks, worlds)):
        cx = 120+240*column
        draw.text((column*240+15, 20), f'{name}  frame {f}', fill='#111111')
        draw.line((column*240+10, 420, column*240+230, 420), fill='#bbbbbb')
        def xy(v):
            return (cx+float(v[1])*scale, 410-float(v[2])*scale)
        for chain in chains:
            for previous, current in zip(chain, chain[1:]):
                draw.line((xy(w[lookup[previous]]), xy(w[lookup[current]])), fill='#20272c', width=4)
        head = next(i for i, b in enumerate(bones) if b['name'] == 'def_c_head')
        x, y = xy(w[head])
        draw.ellipse((x-9, y-9, x+9, y+9), fill='#20272c')
    image.save(OUT / f'{name}_frames.png')


def smd_check(rigs, bones):
    results = []
    for rig in rigs:
        path = ASSETS / rig['source_file'].replace('cast/', 'smd/').replace('.cast', '.smd')
        lines = path.read_text(encoding='utf8').splitlines()
        begin = lines.index('skeleton')+2
        end = lines.index('end', begin)
        pose = rest_pose(rig['bones'])
        for line in lines[begin:end]:
            v = line.split()
            i = int(v[0])
            pose[i, :3] = list(map(float, v[1:4]))
            x, y, z = (float(t)/2 for t in v[4:7])
            sx, sy, sz, cx, cy, cz = math.sin(x), math.sin(y), math.sin(z), math.cos(x), math.cos(y), math.cos(z)
            pose[i, 3:7] = [sx*cy*cz-cx*sy*sz, cx*sy*cz+sx*cy*sz,
                             cx*cy*sz-sx*sy*cz, cx*cy*cz+sx*sy*sz]
        w = world_positions(pose, rig['bones'])
        expected = world_positions(rest_pose(rig['bones']), rig['bones'])
        error = float(np.max(np.linalg.norm(w-expected, axis=1)))
        if error > 1e-3:
            raise ValueError(f'SMD rest check failed: {error}')
        results.append({'file': str(path.relative_to(ASSETS)), 'bones': len(w),
                        'max_world_position_error_inches': error})
    references = []
    for qc in (ASSETS / 'smd/animrig/humans/class/medium').glob('*.qc'):
        raw = qc.read_text(encoding='utf8')
        references.extend(qc.parent / m for m in re.findall(r'\$animation\s+"[^"]+"\s+"([^"]+\.smd)"', raw))
    available = [str(p.relative_to(ASSETS)) for p in references if p.exists()]
    if available:
        raise ValueError('animation SMD appeared: add independent animation validation')
    return {'rig_rest_world_checks': results,
            'animation_smd_references_checked': len(references),
            'available_animation_smd': available,
            'animation_smd_status': '待定：QC references animation SMD files, but assets/smd contains no corresponding animation SMD; rest check is not animation validation.'}


def export(skip_rust=False):
    started = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'verification.json').write_text('{"status":"running"}\n', encoding='utf8')
    bones = load_json('fuse_skeleton.json')['bones']
    rigs = load_json('fuse_rigs.json')['rigs']
    sequences = load_json('fuse_sequences.json')['sequences']
    qcfiles = load_json('qc_metadata.json')['files']
    rest = rest_pose(bones)
    data = bytearray()
    for b, trs in zip(bones, rest):
        data += text(b['name']) + struct.pack('<i10f', b['parent_index'], *trs)
    manifest, validation = [], bytearray(b'FAVAL001')
    validation += struct.pack('<II', len(bones), 0)
    record_count, clip_count, rotation_error = 0, 0, 0.
    json_cases = []
    unmapped_all = set()
    for name in NAMES:
        matches = [s for s in sequences if s['asset']['asset_name'].replace('\\', '/').endswith('/'+name+'.rseq')]
        if len(matches) != 1:
            raise ValueError(f'missing/ambiguous selected name {name}')
        seq = matches[0]
        qc = qc_info(seq, qcfiles)
        row = dict(name=name, guid=seq['guid'], original_path=seq['asset']['asset_name'],
                   rig=qc['rig'], blend_sample_count=len(seq['clips']), qc=qc, samples=[])
        rig = next(r for r in rigs if r['asset']['asset_name'].replace('\\', '/') == qc['rig'])
        model_by_name = {b['name']: b for b in bones}
        assert all(b['parent_name'] == model_by_name[b['name']]['parent_name']
                   for b in rig['bones'] if b['name'] in model_by_name)
        for c in seq['clips']:
            a, frames, tracks, unmapped = decode(ASSETS / c['file'], bones)
            unmapped_all.update(unmapped)
            idx = c['blend_index']
            clip_name = name if len(seq['clips']) == 1 else f'{name}#{idx}'
            axes = qc['axes']
            coords = []
            if axes:
                if len(axes) != 1:
                    raise ValueError('selected v0 clips require 1D QC blend')
                coords = [axes[0]['min'] + (axes[0]['max']-axes[0]['min'])*idx/(len(seq['clips'])-1)]
            metadata = dict(sample_index=idx, sample_count=len(seq['clips']),
                            axes=axes, coordinates=coords,
                            qc_sample_token=qc['sample_tokens'][idx],
                            qc_file=qc['qc_file'], activities=qc['activities'],
                            modifiers=qc['modifiers'], layers=qc['layers'],
                            raw_qc=qc['raw_qc'], unmapped_bones=unmapped)
            root = next((t for t in tracks if t['bone'] == 0 and not t['mode']), None)
            if root is not None:
                assert all(v is not None for v in root['channels'][:2])
                if root['channels'][2] is not None and not np.all(root['channels'][2] == 1):
                    raise ValueError('v0 rigid root requires unit scale')
                tracks = [t for t in tracks if t is not root]
            for tr in tracks + ([root] if root else []):
                v = tr['channels'][1]
                if v is not None:
                    rotation_error = max(rotation_error, float(np.max(angle_error(v, quantize(v)/32767))))
            body = bytearray(text(clip_name)+text(name)+text(c['file'])+text(qc['rig']))
            body += struct.pack('<QfIIIII', int(seq['guid'], 16), a.Framerate(), frames,
                                int(a.Looping()) | (2 if any(t['mode'] for t in tracks) else 0),
                                idx, len(seq['clips']), len(tracks))
            body += text(json.dumps(metadata, ensure_ascii=False, separators=(',', ':')))
            body += struct.pack('<i', 0 if root else -1)
            if root:
                body += packed_channel(root['channels'][0], False)
                body += packed_channel(root['channels'][1], True)
            for tr in tracks:
                mask = sum(1 << j for j, v in enumerate(tr['channels']) if v is not None)
                body += struct.pack('<HBB3f', tr['bone'], tr['mode'], mask, *tr['weights'])
                for j, v in enumerate(tr['channels']):
                    body += packed_channel(v, j == 1)
            body += struct.pack('<I', len(qc['events']))
            for e in qc['events']:
                if e['frame'] >= frames:
                    raise ValueError(f'event beyond clip: {clip_name}:{e}')
                body += struct.pack('<I', e['frame'])+text(e['name'])+text(e['parameter'])
            data += struct.pack('<I', len(body))+body
            # Every integer frame AND every midpoint: independent Python Cast poses.
            integer = [pose_at(rest, tracks, f, root) for f in range(frames)]
            for f in range(2*frames-1):
                frame = f/2
                i = f//2
                pose = integer[i].copy()
                if f % 2:
                    # Interpolate source channels BEFORE composing additive weights.
                    half_tracks = []
                    for tr in tracks:
                        channels = [None if v is None else
                                    (slerp(v[i], v[i+1], .5) if j == 1 else (v[i]+v[i+1])*.5)[None, :]
                                    for j, v in enumerate(tr['channels'])]
                        half_tracks.append(dict(tr, channels=channels))
                    pose = pose_at(rest, half_tracks, 0, root)
                validation += struct.pack('<Id', clip_count, frame/a.Framerate())
                validation += pose.astype('<f4').tobytes()
                # Cast root delta at this frame and after one full loop.
                root_nonloop = root_reference(root, frame).astype('<f4')
                root_loop = root_reference(root, frame, 0 if frames == 1 else 1).astype('<f4')
                validation += root_nonloop.tobytes()
                # Last-frame + one period is exactly the next wrap boundary.
                validation += root_loop.tobytes()
                if f in (0, frames-1, 2*frames-2):
                    json_cases.append([clip_count, frame/a.Framerate(), pose.astype('<f4').tolist(),
                                       root_nonloop.tolist(), root_loop.tolist()])
                record_count += 1
            root_span = (float(np.linalg.norm(root['channels'][0][-1]-root['channels'][0][0]))
                         if root else 0.)
            row['samples'].append(dict(clip=clip_name, cast_file=c['file'], frames=frames,
                                       fps=a.Framerate(), looping=a.Looping(), mode=a.Curves()[0].Mode(),
                                       blend=metadata, root_displacement_inches=root_span,
                                       dropped_bones=unmapped))
            if name in ('fuse_run_rifle_F', 'fuse_slide_rifle', 'mp_pt_medium_WallMantle_Level') and idx == len(seq['clips'])//2:
                preview(name, rest, tracks, root, frames, bones)
            clip_count += 1
        manifest.append(row)
    header = struct.pack('<8sIQIII', b'FUSEANIM', 0, 32+len(data), len(bones), clip_count, zlib.crc32(data))
    pack = header+data
    (OUT / 'fuse.anim').write_bytes(pack)
    struct.pack_into('<I', validation, 12, record_count)
    (OUT / 'validation.bin').write_bytes(validation)
    # Numeric-array-only JSON: version, bones, case count, cases. The zero-dep
    # Rust example reads these independently of the full binary fixture.
    (OUT / 'validation.json').write_text(json.dumps([1, len(bones), len(json_cases), json_cases],
                                                   separators=(',', ':')), encoding='utf8')
    (OUT / 'selected_sequences.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
    lines = ['# Selected local sequences', '',
             '| Sequence | GUID | Rig | Samples / frames | Activity | Events |',
             '|---|---|---|---|---|---|']
    for row in manifest:
        qc = row['qc']
        events = '; '.join(f"{e['frame']}:{e['name']}({e['parameter']})" for e in qc['events']) or '(none)'
        lines.append(f"| {row['name']} | {row['guid']} | {row['rig']} | {len(row['samples'])} / {','.join(str(c['frames']) for c in row['samples'])} | {qc['activities']} | {events} |")
    for row in manifest:
        lines += ['', '## '+row['name'], '', '- Original: `'+row['original_path']+'`',
                  '- QC: `'+row['qc']['qc_file']+'`']
        for c in row['samples']:
            lines.append(f"- `{c['clip']}`: `{c['cast_file']}`, {c['frames']} frames @ {c['fps']} fps; {c['mode']}; loop={c['looping']}; blend={c['blend']['coordinates']}; token={c['blend']['qc_sample_token']}; root={c['root_displacement_inches']:.6f} inches")
        lines += ['', '```qc', row['qc']['raw_qc'], '```']
    (OUT / 'selected_sequences.md').write_text('\n'.join(lines)+'\n', encoding='utf8')
    pending = [
        '独立 fuse_run_rifle_B/L/R 与 fuse_walk_rifle_B/L/R：清单中无此序列；已收录共享 medium_run_rifle_B/medium_walk_rifle_B 与 F 的方向混合样本。',
        '暴雷专名蹲伏 rifle 待机：使用 fuse 骨架内 ACT_MP_CROUCH_IDLE 的 mirage_crouch_rifle；完整 AIM 层组合仍由运行时实现。',
        '对应动作 SMD 世界位置交叉验证：本机仅有骨架/模型 SMD，QC 引用的动作 SMD 不存在。',
        'QC 自动瞄准/脸部层与活动选择逻辑：v0 保留元数据，不自动求值。',
    ]
    summary = dict(status='exported_not_validated' if skip_rust else 'passed',
                   sequence_count=len(manifest), clip_count=clip_count, bone_count=len(bones),
                   pack_bytes=len(pack), sha256=hashlib.sha256(pack).hexdigest(),
                   selected_cast_bytes=sum((ASSETS / c['cast_file']).stat().st_size
                                           for row in manifest for c in row['samples']),
                   quantization='xyzw signed i16 / 32767, then normalize',
                   theoretical_max_angle_error_deg=math.degrees(4*math.asin(1/32767)),
                   measured_max_quantization_angle_error_deg=rotation_error,
                   validation_pose_count=record_count, unmapped_animation_bones=sorted(unmapped_all),
                   smd=smd_check(rigs, bones), pending=pending)
    if not skip_rust:
        subprocess.run(['cargo', 'run', '--release', '--offline', '--example', 'validate', '--',
                        str(OUT / 'fuse.anim'), str(OUT / 'validation.bin'), str(OUT / 'rust_validation.json')],
                       cwd=ROOT / 'deps/er-apex-anim', check=True)
        summary['rust_validation'] = json.loads((OUT / 'rust_validation.json').read_text())
        subprocess.run(['cargo', 'run', '--release', '--offline', '--example', 'validate', '--',
                        str(OUT / 'fuse.anim'), str(OUT / 'validation.json'), str(OUT / 'rust_json_validation.json')],
                       cwd=ROOT / 'deps/er-apex-anim', check=True)
        summary['rust_json_validation'] = json.loads((OUT / 'rust_json_validation.json').read_text())
    summary['export_seconds'] = time.perf_counter()-started
    (OUT / 'verification.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-rust', action='store_true', help='export only; acceptance requires default Rust validation')
    try:
        export(parser.parse_args().skip_rust)
    except Exception as exc:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / 'verification.json').write_text(json.dumps({'status': 'failed', 'error': str(exc)},
                                                        ensure_ascii=False, indent=2), encoding='utf8')
        raise
