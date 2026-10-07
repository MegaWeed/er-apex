"""M0-FP: bake Apex's first-person R-301 animations for er-fuse (D-017).

Run from the repository root: python tools/apexpov/bake_pov.py [--out PATH]
Default output: apex-data/pov/fuse_pov.anim (copy it into the mod folder next to fuse_er.anim).
Clip names are Cast stems, <sequence>_<sample index>, including every selected blend sample.
The companion apex-data/pov/fuse_pov_sequences.json records QC options, sample metadata and
blend coordinates. Absent QC values are null. RSX's empty constant delta samples are restored
from local RSEQ metadata with their originals preserved in pov/cast_original_empty/.

The mod plays these on the ptpov_rspn101 skeleton itself (forward kinematics at run time, so it can
blend the hip and aiming poses and layer the additive idle / fire), then writes each carrier bone
(tools/apexpov/carriers.json) as

    eye (x left, y up, z forward) o [inverse(camera) . world(owner) . inverse(mesh bind of owner)]
        (translation inches -> metres) o ER bind of the carrier

so a vertex stored as 0.0254 x its Cast position (T011's convention) lands where Apex draws it
relative to the camera. Evidence (tools/apexpov, journal 2026-10-04): in the absolute clips the
camera bone sits at the rig origin with local axes x left, y up, z forward; at the end of ads_in the
R-301's ADS_CENTER_SIGHT_R301 is on its z axis 27.61 in ahead.

`fuse_pov.anim` v1, little endian:
  "FPOV", u32 1
  u32 bones; per bone: name (u16 len + UTF-8), i16 parent, f32 rest t xyz (in), q xyzw
  u32 camera bone
  u32 carriers; per carrier: c0000 name, u32 owner bone,
      f32 inverse mesh bind of the owner (t xyz in, q xyzw), f32 ER bind (t xyz m, q xyzw)
  u32 clips; per clip: name, f32 fps, u32 frames, u8 loop, u8 additive,
      per bone f32 translation weight, f32 rotation weight (1 for absolute clips),
      then frames x bones x (t xyz, q xyzw): local transforms (absolute) or deltas (additive)
"""
import argparse
import json
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode = True  # shared tools/fuseanim is read-only for this task
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'tools/fuseanim'))
import export_anim as ea  # noqa: E402  (T006: Cast animation decoding, additive rules)
from cast import Skeleton  # noqa: E402
from pov_sequences import (build_sequence_table, read_qc, recover_empty_casts,
                           selected_clips)  # noqa: E402

POV = REPO / 'apex-data/pov'
RIG = POV / 'cast/animrig/weapons/rspn101/ptpov_rspn101.cast'
ANIMS = POV / 'cast/animrig/weapons/rspn101/anims_ptpov_rspn101'
MODELS = [REPO / 'apex-data/assets/cast/mdl/Weapons/arms/pov_pilot_medium_fuse_LOD0.cast',
          POV / 'cast/mdl/techart/mshop/weapons/class/assault/r301/r301_base_v_LOD0.cast']
OCTANE_ARMS = REPO / 'apex-data/assets/octane/cast/mdl/Weapons/arms/pov_pilot_medium_stim_LOD0.cast'
CARRIERS = Path(__file__).with_name('carriers.json')
# All numeric samples of group A; only sample 0 of group B (T012).
CLIPS = ['ads_in_0', 'ads_in_1', 'ads_out_0', 'ads_out_1',
         'idle_0', 'idle_1', 'crouch_0', 'crouch_1',
         'idle_to_crouch_0', 'idle_to_crouch_1', 'crouch_to_idle_0', 'crouch_to_idle_1',
         'fire_0', 'fire_1', 'fire_2', 'fire_3', 'jump_0', 'jump_1', 'jump_2', 'jump_3',
         'land_0', 'land_1', 'land_2', 'land_3', 'sprint_0', 'sprintraise_0', 'sprintslide_0',
         'reload_0', 'reload_1', 'reload_empty_0', 'reload_empty_1',
         'wind_effect_layer_0', 'wind_effect_layer_1',
         'holster_0', 'draw_0', 'drawfirst_0', 'raise_0', 'lower_0', 'inspect_basic_0']


def quat_mat(q):
    x, y, z, w = q / np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def mat_quat(m):
    t = np.trace(m)
    if t > 0:
        s = np.sqrt(t + 1) * 2
        q = [(m[2, 1]-m[1, 2])/s, (m[0, 2]-m[2, 0])/s, (m[1, 0]-m[0, 1])/s, s/4]
    else:
        i = int(np.argmax(np.diag(m)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = np.sqrt(1 + m[i, i] - m[j, j] - m[k, k]) * 2
        q = [0.0] * 4
        q[i] = s / 4
        q[j] = (m[j, i] + m[i, j]) / s
        q[k] = (m[k, i] + m[i, k]) / s
        q[3] = (m[k, j] - m[j, k]) / s
    q = np.array(q)
    return q / np.linalg.norm(q) * (1 if q[3] >= 0 else -1)


def trs(t, q, s=(1, 1, 1)):
    m = np.eye(4)
    m[:3, :3] = quat_mat(np.asarray(q, float)) * np.asarray(s, float)
    m[:3, 3] = t
    return m


def rigid(m, what):
    r = m[:3, :3]
    if not np.allclose(r @ r.T, np.eye(3), atol=2e-3) or np.linalg.det(r) < 0:
        raise ValueError(f'{what} is not a rotation (scale {np.linalg.svd(r)[1]})')
    return np.concatenate([m[:3, 3], mat_quat(r)])


def skeleton(path):
    for n in ea.nodes(path):
        if isinstance(n, Skeleton):
            return [dict(name=b.Name(), parent=b.ParentIndex(), local_position=list(b.LocalPosition()),
                         local_rotation_xyzw=list(b.LocalRotation()), local_scale=list(b.Scale() or (1, 1, 1)))
                    for b in n.Bones()]
    raise ValueError(f'no skeleton in {path}')


def worlds(bones, pose):
    out = []
    for i, b in enumerate(bones):
        local = trs(pose[i, :3], pose[i, 3:7], pose[i, 7:])
        out.append(out[b['parent']] @ local if b['parent'] >= 0 else local)
    return out


def er_binds(templates):
    """c0000 bone -> its world bind matrix in the templates that enable it (T008's E: the template
    node table); a bone enabled in two templates must agree."""
    out = {}
    for part in templates.values():
        nodes = json.loads((REPO / f'er-data/json/parts/{part}.json').read_text(encoding='utf8'))['Nodes']
        world = {}

        def visit(i):
            if i not in world:
                b = nodes[i]
                local = trs(b['Translation'], b['RotationQuaternion'], b['Scale'])
                world[i] = (visit(b['ParentIndex']) if b['ParentIndex'] >= 0 else np.eye(4)) @ local
            return world[i]
        for i, b in enumerate(nodes):
            w = visit(i)
            # only where it can skin (disabled nodes may hold other transforms)
            if 'Bone' not in b['Flags'] or 'Disabled' in b['Flags']:
                continue
            if b['Name'] in out and np.max(abs(out[b['Name']] - w)) > 1e-4:
                raise ValueError(f'{b["Name"]}: templates disagree')
            out.setdefault(b['Name'], w)
    return out


def name(s):
    b = s.encode('utf8')
    return struct.pack('<H', len(b)) + b


def inverse_mesh_binds(legend='fuse'):
    """Use the selected arms first, then R-301; retain exact baseline floats only for absent owners."""
    if legend not in ('fuse', 'octane'):
        raise ValueError(f'Unknown legend: {legend}')
    paths = [OCTANE_ARMS, MODELS[1]] if legend == 'octane' else MODELS
    mesh_bind, provenance = {}, {}
    for path in paths:
        bones = skeleton(path)
        for bone, matrix in zip(bones, worlds(bones, ea.rest_pose(bones))):
            mesh_bind.setdefault(bone['name'], matrix)
            provenance.setdefault(bone['name'], path.relative_to(REPO).as_posix())
    spec = json.loads(CARRIERS.read_text(encoding='utf8'))
    inverse, fallbacks = {}, []
    baseline = None
    for carrier in spec['carriers']:
        owner = carrier['owner']
        if owner in mesh_bind:
            inverse[carrier['carrier']] = rigid(np.linalg.inv(mesh_bind[owner]), f'mesh bind of {owner}')
        else:
            if legend != 'octane':
                raise ValueError(f'No mesh bind for {owner}')
            if baseline is None:
                from verify_pov_pack import read_pack
                baseline = {c['name']: c for c in read_pack(POV/'fuse_pov.anim')['carrier_records']}
            inverse[carrier['carrier']] = np.asarray(baseline[carrier['carrier']]['inverse_mesh_bind'])
            fallbacks.append(dict(carrier=carrier['carrier'], owner=owner, source='apex-data/pov/fuse_pov.anim'))
    # Every positive v_arms weight must have an owner and an actual selected-model bind.
    from cast import Model
    arms = next(n for n in ea.nodes(paths[0]) if isinstance(n, Model))
    mesh_name = 'body_0_octane_base_v_arms' if legend == 'octane' else 'body_0_fuse_base_v_arms'
    meshes = [m for m in arms.Meshes() if m.Name() == mesh_name]
    if len(meshes) != 1:
        raise ValueError(f'Expected one {mesh_name}')
    bones = arms.Skeleton().Bones()
    used = {bones[int(b)].Name() for b, w in zip(meshes[0].VertexWeightBoneBuffer(), meshes[0].VertexWeightValueBuffer()) if w > 0}
    for bone in used:
        owner = spec['owner_of_bone'].get(bone)
        if owner is None or owner not in mesh_bind:
            raise ValueError(f'Positive arms weight on forbidden/fallback bone: {bone}, owner={owner}')
    return inverse, dict(legend=legend, models=[p.relative_to(REPO).as_posix() for p in paths],
                         owner_sources={c['owner']: provenance.get(c['owner'], 'Fuse baseline fallback') for c in spec['carriers']},
                         fallback_carriers=fallbacks, no_selected_vertex_uses_fallback=True)


def bake(legend='fuse', out_path=None, sequences_path=None, audit_path=None):
    directory = POV / 'octane' if legend == 'octane' else POV
    out_path = Path(out_path or directory/'fuse_pov.anim').resolve()
    sequences_path = Path(sequences_path or out_path.with_name('fuse_pov_sequences.json')).resolve()
    if legend == 'octane':
        roots = [POV/'octane', REPO/'er-data/s3/octane_pov']
        if not all(any(p.is_relative_to(root.resolve()) for root in roots) for p in (out_path, sequences_path)):
            raise ValueError('Octane outputs must stay inside apex-data/pov/octane or er-data/s3/octane_pov')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sequences_path.parent.mkdir(parents=True, exist_ok=True)
    rig = skeleton(RIG)
    index = {b['name']: i for i, b in enumerate(rig)}
    rest = ea.rest_pose(rig)
    if np.max(abs(rest[:, 7:] - 1)) > 1e-4:
        raise ValueError('rig rest has scale')
    qc = read_qc()
    if CLIPS != selected_clips(qc):
        raise ValueError('CLIPS does not agree with the selected QC sample list')
    recovered = recover_empty_casts(qc, rig, out_path.parent/'cast_recovery')
    camera = index['jx_c_camera']
    spec = json.loads(CARRIERS.read_text(encoding='utf8'))
    binds = er_binds(spec['templates'])
    inverse, bind_audit = inverse_mesh_binds(legend)
    out = bytearray(b'FPOV' + struct.pack('<I', 1))
    out += struct.pack('<I', len(rig))
    for b, r in zip(rig, rest):
        out += name(b['name']) + struct.pack('<h', b['parent']) + struct.pack('<7f', *r[:7])
    out += struct.pack('<I', camera)
    out += struct.pack('<I', len(spec['carriers']))
    for c in spec['carriers']:
        out += name(c['carrier']) + struct.pack('<I', index[c['owner']])
        out += struct.pack('<7f', *inverse[c['carrier']])
        out += struct.pack('<7f', *rigid(binds[c['carrier']], f'ER bind of {c["carrier"]}'))
    clips = []
    out += struct.pack('<I', len(CLIPS))
    for clip in CLIPS:
        path = recovered.get(clip, ANIMS / f'{clip}.cast')
        a, frames, tracks, unmapped = ea.decode(path, rig)
        if unmapped:
            raise ValueError(f'{clip}: unmapped bones {unmapped}')
        additive = {t['mode'] for t in tracks} == {1}
        weights = np.ones((len(rig), 2))
        if additive:
            for t in tracks:
                weights[t['bone']] = t['weights'][:2]
        # the deltas alone (additive) or the full local pose (absolute), per frame
        zero = np.tile([0, 0, 0, 0, 0, 0, 1, 1, 1, 1], (len(rig), 1)).astype(float)
        poses = []
        for f in range(frames):
            p = (zero if additive else rest).copy()
            for t in tracks:
                for j, (o, wd) in enumerate(((0, 3), (3, 4), (7, 3))):
                    if t['channels'][j] is not None:
                        p[t['bone'], o:o+wd] = t['channels'][j][f]
            if np.max(abs(p[:, 7:] - 1)) > 1e-3:
                raise ValueError(f'{clip} frame {f}: scale channels')
            poses.append(p[:, :7])
        out += name(clip) + struct.pack('<fIBB', a.Framerate(), frames, int(bool(a.Looping())), int(additive))
        out += weights.astype('<f4').tobytes()
        out += np.asarray(poses, dtype='<f4').tobytes()
        clips.append(dict(name=clip, frames=frames, fps=a.Framerate(), loop=bool(a.Looping()), additive=additive))
    sequences = build_sequence_table(qc, recovered)
    out_path.write_bytes(bytes(out))
    sequences_path.write_text(json.dumps(sequences, indent=2) + '\n', encoding='utf8')
    if legend == 'octane':
        from verify_pov_pack import compare_bind_variant, read_pack
        bind_audit.update(compare_bind_variant(read_pack(POV/'fuse_pov.anim'), read_pack(out_path)))
    else:
        baseline = POV/'fuse_pov.anim'
        if out_path != baseline and baseline.is_file():
            if baseline.read_bytes() != out_path.read_bytes():
                raise ValueError('Fuse bake differs from the current complete Fuse pack')
            bind_audit['fuse_baseline_byte_identical'] = True
    audit_path = Path(audit_path or out_path.with_name('pov-bind-audit.json')).resolve()
    if not audit_path.is_relative_to(out_path.parent):
        raise ValueError('Bind audit must stay inside the pack output directory')
    audit_path.write_text(json.dumps(bind_audit, indent=2) + '\n', encoding='utf8')
    print(json.dumps(dict(out=str(out_path), bytes=len(out), bones=len(rig), carriers=len(spec['carriers']),
                         sequences_out=str(sequences_path), recovered_empty_casts=sorted(recovered),
                         clip_count=len(clips), clips=clips), indent=1))
    return bind_audit


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--legend', choices=('fuse', 'octane'), default='fuse')
    ap.add_argument('--out', type=Path)
    ap.add_argument('--sequences-out', type=Path)
    ap.add_argument('--audit-out', type=Path)
    args = ap.parse_args()
    bake(args.legend, args.out, args.sequences_out, args.audit_out)


if __name__ == '__main__':
    main()
