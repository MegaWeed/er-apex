"""R4: the deployed jump pad's animation for the mod, from local data only.

Apex's world jump pad (`mdl/props/octane_jump_pad`, rig `animrig/props/octane_jump_pad`) has 18
bones; 17 of them (all but `jx_c_origin`) have the names, parents and relative binds of the
hand-held pad's bones that T020 put in model 998's LG part. So the mod draws the pad on the
ground with the hand-held mesh, posed by the world prop's own sequences (its QC):
`prop_octane_jump_pad_deploy` (opening), `_deploy_idle` (loop), `_deploy_trans` (the bounce when
it launches someone), `_shutdown`, `_shutdown_idle`.

Writes apex-data/pov/octane_padworld/padworld.json: the rig (names, parents, local binds; inches,
the Cast's axes) and each sequence's local poses per frame (translation xyz, rotation xyzw, scale
xyz), with fps, frame count and loop as the local QC/Cast give them. Run from the repository root:
    python tools/apexpov/bake_padworld.py
No game launch, no network, no git, no hashes.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import numpy as np
import re
from ability_common import ROOT, ASSETS, bp, info, require

RIG = ASSETS / 'cast/animrig/props/octane_jump_pad/octane_jump_pad.cast'
QC = ASSETS / 'smd/animrig/props/octane_jump_pad/octane_jump_pad.qc'
SEQUENCES_JSON = ASSETS / 'sequences/octane_jump_pad.json'
HELD = ASSETS / 'skeletons/ptpov_octane_jump_pad_held.json'
OUT = ROOT / 'apex-data/pov/octane_padworld'
WANTED = ('prop_octane_jump_pad_deploy', 'prop_octane_jump_pad_deploy_idle', 'prop_octane_jump_pad_deploy_trans',
          'prop_octane_jump_pad_shutdown', 'prop_octane_jump_pad_shutdown_idle')


def read_prop_qc(path):
    """The parts of the world pad's QC these sequences use (T020's `read_qc` does not take its
    one-line `$sequence` entries): `$defaultweightlist`, each `$animation`'s loop flag, each
    `$sequence`'s animation, loop flag, fades and weight list. Shaped like `read_qc`'s result."""
    text = path.read_text(encoding='utf8')
    weights = dict((m[1], float(m[2])) for m in re.finditer(r'"([^"]+)"\s+([-\d.]+)', re.search(r'\$defaultweightlist\s*\{([^}]*)\}', text)[1]))
    animations = {m[1]: dict(loop=bool(m[2])) for m in re.finditer(r'^\$animation\s+"([^"]+)"\s+"[^"]+"\s*(loop)?', text, re.M)}
    sequences = {}
    for m in re.finditer(r'^\$sequence\s+"([^"]+)"\s+"([^"]+)"\s*(loop)?\s*(\{(?:[^{}]|\{[^{}]*\})*\})?', text, re.M):
        body = m[4] or ''
        fade = lambda key: (float(f[1]) if (f := re.search(key + r'\s+([-\d.]+)', body)) else None)
        wl = re.search(r'weightlist\s+"([^"]+)"', body)
        sequences[m[1]] = dict(sample_animation_names=[m[2]], loop=bool(m[3]) or 'loop' in re.findall(r'^\s*(loop)\s*$', body, re.M),
                               delta=bool(re.search(r'^\s*delta\s*$', body, re.M)), weightlist=wl[1] if wl else 'defaultweightlist',
                               fadein=fade('fadein'), fadeout=fade('fadeout'))
    return dict(weightlists={'defaultweightlist': weights}, animations=animations, sequences=sequences)


def bake():
    rig = bp.skeleton(RIG)
    names = [b['name'] for b in rig]
    require(len(rig) == 18 and names[0] == 'jx_c_origin' and rig[0]['parent'] < 0, 'World pad rig differs from 18 bones under jx_c_origin')
    # the hand-held pad's rig: the same names, parents and binds relative to def_c_base below it
    held = {b['name']: b for b in json.loads(HELD.read_text(encoding='utf8'))['bones']}
    world_rig = {b['name']: b for b in json.loads((ASSETS/'skeletons/octane_jump_pad.json').read_text(encoding='utf8'))['bones']}
    base_h = np.asarray(held['def_c_base']['world_position'])
    for b in rig[1:]:
        if b['name'] == 'jx_c_start':
            continue
        h = held.get(b['name'])
        require(h is not None, f'{b["name"]} not in the hand-held pad')
        parent = names[b['parent']]
        if b['name'] != 'def_c_base':
            require(h['parent_name'] == parent, f'{b["name"]}: parent {parent} vs held {h["parent_name"]}')
        offset_w = np.asarray(world_rig[b['name']]['world_position']) - np.asarray(world_rig['def_c_base']['world_position'])
        offset_h = np.asarray(h['world_position']) - base_h
        # within 0.05 in (1.3 mm): def_magazine sits 0.02 in lower in the world rig
        require(np.allclose(offset_w, offset_h, atol=0.05), f'{b["name"]}: bind relative to def_c_base differs: {offset_w} vs {offset_h}')
    qc = read_prop_qc(QC)
    table = {s['name']: s for s in json.loads(SEQUENCES_JSON.read_text(encoding='utf8'))['sequences']}
    clips = {}
    for name in WANTED:
        seq = qc['sequences'][name]
        record = table[name]
        require(record['blend_count'] == 1 and len(record['blends']) == 1, f'{name}: not one sample')
        sample = record['blends'][0]
        require(seq['sample_animation_names'][0] in qc['animations'], f'{name}: animation not in the QC')
        path = ASSETS / sample['cast_file']
        # T020's decode_source without its unit-scale rule: these clips scale six bones (the three
        # pads 0.75 -> 1 while it opens, the bottom bladders up to 1.9 in the bounce)
        a, frames, tracks, unknown = bp.ea.decode(path, rig)
        require(not unknown, f'{path}: unmapped bones {unknown}')
        require({t['mode'] for t in tracks} == {0}, f'{name}: not absolute')
        require(not seq['delta'], f'{name}: QC delta')
        loop = seq['loop'] or any(qc['animations'][n]['loop'] for n in seq['sample_animation_names'])
        require(bool(a.Looping()) == loop, f'{name}: QC loop / Cast differ')
        require(all(qc['weightlists'][seq['weightlist']][b['name']] == 1.0 for b in rig), f'{name}: weights not all 1')
        require((frames, a.Framerate()) == (sample['frame_count'], sample['framerate']), f'{name}: Cast/sequence table frames or fps differ')
        poses = np.tile(bp.ea.rest_pose(rig)[None], (frames, 1, 1)).astype(float)
        for t in tracks:
            for channel, (offset, width) in zip(t['channels'], ((0, 3), (3, 4), (7, 3))):
                if channel is not None:
                    poses[:, t['bone'], offset:offset+width] = channel
        q = poses[..., 3:7]
        require(np.allclose(np.linalg.norm(q, axis=-1), 1, atol=1e-3), f'{name}: rotations not unit')
        require(poses[..., 7:].min() > 0, f'{name}: nonpositive scale')
        scaled = sorted({rig[b]['name'] for b in range(len(rig)) if abs(poses[:, b, 7:] - 1).max() > 1e-3})
        clips[name] = dict(fps=float(a.Framerate()), frames=int(frames), loop=bool(loop),
                           fadein=seq['fadein'], fadeout=seq['fadeout'], scaled_bones=scaled, source=info(path),
                           poses=[[[round(float(v), 6) for v in poses[f, b]] for b in range(len(rig))] for f in range(frames)])
    rest = bp.ea.rest_pose(rig)
    data = dict(format='er-apex-padworld', version=1, units='inches, the Cast rig axes (Y up); poses are t xyz, r xyzw, s xyz',
                rig_source=info(RIG), qc_source=info(QC),
                bones=[dict(name=b['name'], parent=b['parent'], rest=[round(float(v), 6) for v in rest[i, :10]]) for i, b in enumerate(rig)],
                clips=clips,
                note='17 bones (all but jx_c_origin) match the hand-held pad by name, parent and bind relative to def_c_base (checked); def_c_base is relative to jx_c_origin here.')
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'padworld.json'
    path.write_text(json.dumps(data, ensure_ascii=False) + '\n', encoding='utf8')
    print(f'PASS padworld: {len(rig)} bones, ' + ', '.join(f'{n} {c["frames"]}@{c["fps"]:g}{" loop" if c["loop"] else ""}' for n, c in clips.items())
          + f'; {path} {path.stat().st_size} bytes')


if __name__ == '__main__':
    bake()
