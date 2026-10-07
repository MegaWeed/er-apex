"""T021 battery sources and lossless FPOV v2 extension (group byte is a u8)."""
from __future__ import annotations
import json
from pathlib import Path
import re
import struct
import sys
sys.dont_write_bytecode = True
import numpy as np
import ability_common as ac
from ability_common import bp, require, checked, save, info, model, model_world, world7, metadata
from verify_pov_pack import Reader

ROOT = ac.ROOT
ASSETS = ROOT/'apex-data/assets/battery'
PACK_ROOT = ROOT/'apex-data/pov/octane_battery'
MODEL_ROOT = ROOT/'er-data/s3/octane_pov_battery'
BASE_PACK = ac.PACK_ROOT/'fuse_pov.anim'
BASE_MODEL = ac.MODEL_ROOT
STEM = 'ptpov_shield_battery_held'
CONFIG = dict(model=ASSETS/f'cast/mdl/Weapons/shield_battery/{STEM}_LOD0.cast',
    rig=ASSETS/f'cast/animrig/weapons/shield_battery/{STEM}.cast',
    qc=ASSETS/f'smd/animrig/weapons/shield_battery/{STEM}.qc',
    model_qc=ASSETS/f'smd/mdl/Weapons/shield_battery/{STEM}.qc',
    metadata=ASSETS/f'sequences/{STEM}.json', part='hd', prefix='battery', group=4)
FACE_NAMES = ('Jaw', 'Lips_Lower', 'L_eyeA', 'L_eyeB', 'R_eyeA', 'R_eyeB')
CARRIER_ORDER = ('Xtra_Multipurpose_Bone02_09', 'Xtra_Multipurpose_Bone02_10')+FACE_NAMES


def read_pack(path):
    """Same v2 layout as T020; accepts the battery group and validates complete records."""
    data = Path(path).read_bytes(); r = Reader(data)
    require(r.take(4) == b'FPOV', 'Not FPOV')
    version, nb = r.unpack('<II')
    require(version == 2 and 0 < nb <= 512, 'Expected FPOV v2')
    bones = []
    for i in range(nb):
        start = r.offset
        name, parent, rest = r.name(), r.unpack('<h')[0], r.unpack('<7f')
        require(-1 <= parent < i, f'Invalid parent: {name}')
        bones.append(dict(name=name, parent=parent, rest=rest, raw=data[start:r.offset]))
    camera, nc = r.unpack('<II')
    require(camera < nb and nc <= 256, 'Invalid camera/carrier count')
    carriers = []
    for _ in range(nc):
        start = r.offset
        name, owner = r.name(), r.unpack('<I')[0]
        inverse, er = r.unpack('<7f'), r.unpack('<7f')
        raw = data[start:r.offset]; group = r.unpack('<B')[0]
        require(owner < nb and group <= 4, f'Invalid carrier: {name}')
        carriers.append(dict(name=name, owner=owner, inverse_mesh_bind=inverse, er_bind=er, group=group,
                             raw=raw, raw_v2=data[start:r.offset]))
    clips = {}; count = r.unpack('<I')[0]
    require(0 < count <= 256, 'Invalid clip count')
    for _ in range(count):
        start = r.offset; name = r.name()
        fps, frames, loop, additive = r.unpack('<fIBB'); header = data[start:r.offset]
        require(0 < fps < 1000 and 0 < frames <= 100000 and loop in (0, 1) and additive in (0, 1), 'Invalid clip header')
        weights = np.frombuffer(r.take(nb*8), '<f4').reshape(nb, 2)
        poses = np.frombuffer(r.take(frames*nb*28), '<f4').reshape(frames, nb, 7)
        require(name not in clips and np.isfinite(poses).all() and np.isfinite(weights).all(), 'Invalid clip data')
        require(np.max(abs(np.linalg.norm(poses[..., 3:], axis=-1)-1)) < .01, f'Bad quaternion: {name}')
        require((weights >= 0).all() and (weights <= 1).all(), f'Bad weights: {name}')
        clips[name] = dict(name=name, fps=fps, frames=frames, loop=bool(loop), additive=bool(additive),
                           weights=weights, poses=poses, header=header)
    require(r.offset == len(data), 'Trailing bytes')
    require(len({b['name'] for b in bones}) == nb and len({c['name'] for c in carriers}) == nc, 'Duplicate bones/carriers')
    require(np.isfinite([b['rest'] for b in bones]).all() and np.isfinite([c['inverse_mesh_bind']+c['er_bind'] for c in carriers]).all(), 'Nonfinite binding')
    return dict(path=str(path), data=data, version=version, bones=bones, camera=camera, carrier_records=carriers, clips=clips)


def bodygroups():
    text = CONFIG['model_qc'].read_text(encoding='utf-8-sig')
    groups = []
    for match in re.finditer(r'\$bodygroup\s+"([^"]+)"\s*\{([^}]+)\}', text):
        options = re.findall(r'\bstudio\s+"([^"]+)"|\b(blank)\b', match[2])
        require(bool(options), 'Empty bodygroup')
        groups.append(dict(name=match[1], options=[s or 'blank' for s, _ in options], default_index=0,
                           default=options[0][0] or 'blank', raw_qc=match[0]))
    for name, studio in re.findall(r'\$body\s+"([^"]+)"\s+"([^"]+)"', text):
        groups.append(dict(name=name, options=[studio], default_index=0, default=studio, implicit_single_body=True))
    require(bool(groups), 'No default bodies/bodygroups in local QC')
    return groups


def selected():
    mdl = model(CONFIG['model']); keep = []; excluded = []
    groups = bodygroups()
    for mesh in mdl.Meshes():
        candidates = [(g, i) for g in groups for i, s in enumerate(g['options'])
                      if s != 'blank' and (mesh.Name().startswith(Path(s).stem+'_') or
                         mesh.Name().startswith(re.sub(r'^'+re.escape(STEM)+r'_|_lod\d+$', '', Path(s).stem)+'_'))]
        require(len(candidates) == 1, f'Cannot map QC studio to Cast mesh: {mesh.Name()}')
        g, i = candidates[0]
        if i == 0: keep.append(mesh)
        else: excluded.append(dict(name=mesh.Name(), bodygroup=g['name'], studio_index=i, vertices=mesh.VertexCount(),
                                   triangles=len(mesh.FaceBuffer())//3, material=mesh.Material().Name(), reason='Not the first QC bodygroup option'))
    require(bool(keep), 'No default battery meshes')
    return mdl, keep, excluded


def carrier_binds():
    # Preserve the actual T020 HD hierarchy; only new face nodes use live local reference TRS.
    nodes = json.loads((BASE_MODEL/'inputs/template-audit/hd.json').read_text())['Nodes']
    index = {n['Name']: i for i, n in enumerate(nodes)}
    matrices = {}
    def visit(i):
        if i not in matrices:
            n = nodes[i]; local = bp.trs(n['Translation'], n['RotationQuaternion'], n['Scale'])
            matrices[i] = visit(n['ParentIndex'])@local if n['ParentIndex'] >= 0 else local
        return matrices[i]
    binds = {n: visit(i) for n, i in index.items()}
    live = ac.live_skeleton()['bones']
    for name in FACE_NAMES:
        b = next(b for b in live if b['name'] == name); ref = b['ref']
        parent = live[b['parent']]['name']
        require(parent in binds, f'Face parent unavailable: {parent}')
        binds[name] = binds[parent]@bp.trs(ref['t'], ref['r'], ref['s'])
    return binds


def layout(base=None):
    base = base or read_pack(BASE_PACK)
    require((len(base['bones']), len(base['carrier_records']), len(base['clips'])) == (126, 69, 107), 'Unexpected T020 baseline')
    bones = [dict(b) for b in base['bones']]; pack_index = {b['name']: i for i, b in enumerate(bones)}
    rig = bp.skeleton(CONFIG['rig']); idx = {b['name']: i for i, b in enumerate(rig)}
    mdl, meshes, omitted = selected()
    weights = {}
    for mesh in meshes:
        for b, w in zip(mesh.VertexWeightBoneBuffer(), mesh.VertexWeightValueBuffer()):
            if w > 0:
                n = mdl.Skeleton().Bones()[int(b)].Name()
                weights[n] = weights.get(n, 0.)+w
    prop = set(weights)
    for n in weights:
        require(n in idx, f'Weighted bone absent from rig: {n}')
        parent = rig[idx[n]]['parent']
        while parent >= 0:
            pname = rig[parent]['name']
            if pname in pack_index and sum(b['parent'] == parent for b in rig) > 1: break
            prop.add(pname); parent = rig[parent]['parent']
    mapping = {n: pack_index[n] for n in idx if n in pack_index and n not in prop}
    other_names = {b['name'] for c in ac.CONFIGS.values() for b in bp.skeleton(c['rig'])}
    added = []; rest = bp.ea.rest_pose(rig)
    for i, b in enumerate(rig):
        n = b['name']
        if n not in prop: continue
        output = 'battery:'+n if n in pack_index or n in other_names else n
        require(output not in {b['name'] for b in bones}, 'Battery bone collision')
        parent_name = rig[b['parent']]['name'] if b['parent'] >= 0 else None
        parent = mapping[parent_name] if parent_name else -1
        mapping[n] = len(bones)
        bones.append(dict(name=output, parent=parent, rest=tuple(rest[i, :7])))
        added.append(dict(index=mapping[n], name=output, source_bone=n, parent=bones[parent]['name'] if parent>=0 else None,
                          rig='battery', copied=output != n, positive_mesh_weight=n in weights))
    differences = []
    for b in base['bones']:
        if b['name'] not in idx: continue
        oldparent = base['bones'][b['parent']]['name'] if b['parent']>=0 else None
        p = rig[idx[b['name']]]['parent']; newparent = rig[p]['name'] if p>=0 else None
        if oldparent != newparent:
            differences.append(dict(rig='battery', bone=b['name'], pack_parent=oldparent, source_parent=newparent,
                                    copied_for_battery=b['name'] in prop, pack_bone_weight_zero=b['name'] in prop))
    used = {c['name'] for c in base['carrier_records']}
    available = [n for n in CARRIER_ORDER if n not in used]
    require(len(available) == 8, 'Expected eight free battery carriers')
    binds = carrier_binds(); mesh_bind = model_world(mdl)
    new = []; by_source = {}; fallback = []
    priority = sorted(weights, key=lambda n: (-weights[n], idx[n]))
    for n in priority[:len(available)]:
        carrier = available.pop(0); by_source[n] = carrier
        new.append(dict(name=carrier, owner=mapping[n], owner_name=bones[mapping[n]]['name'], source_bone=n,
                        rig='battery', part='hd', group=4, total_vertex_weight=weights[n],
                        inverse_mesh_bind=bp.rigid(np.linalg.inv(mesh_bind[n]), n).tolist(),
                        er_bind=bp.rigid(binds[carrier], carrier).tolist()))
    for n in priority[len(new):]:
        parent = rig[idx[n]]['parent']
        while parent >= 0 and rig[parent]['name'] not in by_source: parent = rig[parent]['parent']
        require(parent >= 0, f'No carrier ancestor for {n}')
        ancestor = rig[parent]['name']; by_source[n] = by_source[ancestor]
        fallback.append(dict(rig='battery', source_bone=n, ancestor=ancestor, carrier=by_source[n], total_vertex_weight=weights[n]))
    require(all(c['owner'] >= len(base['bones']) for c in new), 'Battery owner uses T020 bone')
    return dict(bones=bones, sources={'battery':rig}, maps={'battery':mapping, 'battery-carriers':by_source},
                added=added, parent_differences=differences, carrier_records=[dict(c) for c in base['carrier_records']]+new,
                new_carriers=new, ancestor_fallbacks=fallback, weight_priority=priority, bodygroups=bodygroups(), omitted_meshes=omitted)


write_pack = ac.write_pack


def remap_clip(source, data, key):
    # A copied prop already has the source hierarchy. Its masked T020 namesake
    # keeps bind/identity; only a reused bone's parent change requires world-to-local conversion.
    active=[d for d in data['parent_differences'] if not d.get('copied_for_battery')]
    return ac.remap_clip(source,dict(data,parent_differences=active),key)


def decode_source(path, rig, seq, qc):
    animation = ac.ps.animation(path)
    if animation.Curves():
        return ac.decode_source(path, rig, seq, qc)
    # T016's proof for omitted identity delta curves, applied to the battery's own RSEQ.
    rawpath = ASSETS/'raw'/Path(path).relative_to(ASSETS/'cast')
    name, blend = rawpath.stem.rsplit('_', 1)
    rawpath = rawpath.with_name(name+'.rseq'); raw = rawpath.read_bytes()
    table = (struct.unpack_from('<H',raw,42)[0] & 0xfffe) << (4*(struct.unpack_from('<H',raw,42)[0] & 1))
    value = struct.unpack_from('<H',raw,table+2*int(blend))[0]
    offset = (value & 0xfffe) << (4*(value & 1))
    fps, flags, frames = struct.unpack_from('<fIi',raw,offset)
    require(flags & 4 and not flags & 0x20000 and seq['delta'] and not animation.CurveModeOverrides(), 'Unproved empty battery Cast')
    wi = struct.unpack_from('<H',raw,82)[0]
    weights = [0. if wi == 1 else 1.]*len(rig) if wi in (1,3) else list(struct.unpack_from(f'<{len(rig)}f',raw,(wi & 0xfffe) << (4*(wi & 1))))
    listed = [qc['weightlists'][seq['weightlist']][b['name']] for b in rig]
    require(weights == listed, 'Empty Cast RSEQ/QC weights differ')
    require(animation.Framerate() == fps and bool(animation.Looping()) == bool(flags & 1), 'Empty Cast header differs')
    require([(b.Name(),b.ParentIndex()) for b in animation.Skeleton().Bones()] == [(b['name'],b['parent']) for b in rig], 'Empty Cast skeleton differs')
    return dict(fps=fps,frames=frames,loop=bool(flags & 1),additive=True,weights=np.repeat(np.asarray(weights)[:,None],2,axis=1),
                poses=np.tile([0.,0.,0.,0.,0.,0.,1.],(frames,len(rig),1)),
                constant_delta_source=dict(rseq=info(rawpath),animdesc_offset=offset,flags=flags,
                reason='Local RSEQ ANIM_DELTA set and ANIM_VALID clear; RSX initializes identity delta and exports no curves.'))


def read_qc(path):
    """Parse every local sequence, animation and explicit bone weight list."""
    text = Path(path).read_text(encoding='utf-8-sig')
    weights = {}
    for m in re.finditer(r'\$(defaultweightlist|weightlist)(?:\s+"([^"]+)")?\s*\{([^}]+)\}', text):
        weights[m[2] or 'defaultweightlist'] = {b: float(w) for b, w in re.findall(r'"([^"]+)"\s+([-\d.eE+]+)', m[3])}
    sequences, animations = {}, {}
    for kind, name, raw, tokens, line in ac.ps._blocks(text):
        if kind == 'animation':
            animations[name] = dict(file=ac.ps._value(tokens[2]), fps=float(re.search(r'\bfps\s+([\d.]+)', raw)[1]),
                                    loop='loop' in tokens, delta='delta' in tokens)
            continue
        seq = dict(sample_animation_names=[], blendwidth=None, blend=[], activity=None,
                   activitymodifiers=[], fadein=None, fadeout=None, loop=False, delta=False,
                   autoplay=False, addlayer=[], node=None, transition=None, events=[], posecycle=None,
                   weightlist='defaultweightlist', qc_line=line, raw_qc=raw)
        i = 2
        while i < len(tokens):
            token = tokens[i]; i += 1
            if token in ('{', '}'):
                continue
            if token.startswith('"'):
                seq['sample_animation_names'].append(ac.ps._value(token))
            elif token in ('loop', 'delta', 'autoplay', 'snap'):
                seq[token] = True
            elif token in ('blendwidth', 'fadein', 'fadeout'):
                seq[token] = (int if token == 'blendwidth' else float)(tokens[i]); i += 1
            elif token == 'blend':
                seq['blend'].append(dict(parameter=ac.ps._value(tokens[i]), min=float(tokens[i+1]), max=float(tokens[i+2]))); i += 3
            elif token == 'activity':
                seq['activity'] = dict(name=ac.ps._value(tokens[i]), weight=int(tokens[i+1])); i += 2
            elif token in ('weightlist', 'node', 'posecycle'):
                seq[token] = ac.ps._value(tokens[i]); i += 1
            elif token in ('activitymodifier', 'addlayer'):
                seq['activitymodifiers' if token == 'activitymodifier' else token].append(ac.ps._value(tokens[i])); i += 1
            elif token == 'transition':
                seq['transition'] = [ac.ps._value(t) for t in tokens[i:i+2]]; i += 2
            elif token == 'event':
                event = dict(name=ac.ps._value(tokens[i]), frame=int(tokens[i+1]), options=[]); i += 2
                while i < len(tokens) and tokens[i] != '}':
                    event['options'].append(ac.ps._value(tokens[i])); i += 1
                seq['events'].append(event)
            else:
                raise ValueError(f'{path}:{line}: unsupported QC option {token}')
        require(bool(seq['sample_animation_names']), f'No samples: {name}')
        sequences[name] = seq
    poses = re.findall(r'^\$poseparameter\s+"([^"]+)"', text, re.MULTILINE)
    return dict(sequences=sequences, animations=animations, weightlists=weights, poseparameters=poses)


CONFIGS = {'epipen': ac.CONFIGS['epipen'], 'battery': CONFIG}
XTRA_NAMES = ac.XTRA_NAMES
live_skeleton = ac.live_skeleton
forbidden_prop_carrier = ac.forbidden_prop_carrier
