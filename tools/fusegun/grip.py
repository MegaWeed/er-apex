"""Derive the gun-to-wrist relationship from local Cast animation, without fitting."""
import numpy as np
from common import ASSETS, ROOT, read, save, trs, world, unit, base_for, source_info
from cast import Cast, Model
from export_anim import decode, rest_pose, pose_at

GUN_CAST = ASSETS / 'cast/mdl/techart/mshop/weapons/class/assault/r301/r301_base_w_LOD0.cast'
GUN_QC = ASSETS / 'smd/mdl/techart/mshop/weapons/class/assault/r301/r301_base_w.qc'
FUSE_QC = ASSETS / 'smd/mdl/Humans/class/medium/pilot_medium_fuse.qc'
ANIMS = ASSETS / 'cast/animrig/humans/class/medium/anims_pilot_medium_fuse'


def animation_world(bones, tracks, frame, remove_root=False):
    pose = pose_at(rest_pose(bones), tracks, frame)
    # Cast's origin track includes the exporter's global rotation and locomotion.
    # Removing that track restores the model's Y-up space, without changing G.
    if remove_root:
        pose[0] = rest_pose(bones)[0]
    indices = {b['name']: i for i, b in enumerate(bones)}
    return world(bones, lambda b: trs(pose[indices[b['name']], :3],
                                    pose[indices[b['name']], 3:7],
                                    pose[indices[b['name']], 7:]),
                 lambda b: b['parent_index'])


def rotation_difference(a, b):
    relative = a[:, :3, :3] @ b[:3, :3].T
    return np.rad2deg(np.arccos(np.clip((np.trace(relative, axis1=1, axis2=2)-1)/2, -1, 1)))


def attachment_line(path, name):
    matches = [line for line in path.read_text(encoding='utf-8-sig').splitlines()
               if line.startswith(f'$attachment "{name}" ')]
    if len(matches) != 1:
        raise ValueError(f'Expected one attachment {name} in {path}')
    return matches[0]


def skeleton_relation(bones):
    names = {b['name']: i for i, b in enumerate(bones)}
    matrices = world(bones, lambda b: trs(b['local_position'], b['local_rotation_xyzw'], b['local_scale']),
                     lambda b: b['parent_index'])
    return np.linalg.inv(matrices[names['def_r_wrist']]) @ matrices[names['ja_c_propGun']]


def fuse_reference():
    bones = read(ASSETS/'fuse_skeleton.json')['bones']
    lookup = {b['name']: i for i, b in enumerate(bones)}
    _, _, tracks, _ = decode(ANIMS/'fuse_idle_rifle_0.cast', bones)
    W = animation_world(bones, tracks, 0)
    return np.linalg.inv(W[lookup['def_r_wrist']]) @ W[lookup['ja_c_propGun']]


def derive(state, out, legend='fuse'):
    ab, eb, ai, ei, A, P, E, Q, mapping, enabled, align = state
    model = Cast.load(str(GUN_CAST)).Roots()[0].ChildrenOfType(Model)[0]
    gunbones = model.Skeleton().Bones()
    names = [b.Name() for b in gunbones]
    assert names[0] == 'ja_c_propGun'
    gunW = world(gunbones, lambda b: trs(b.LocalPosition(), b.LocalRotation(), b.Scale() or [1, 1, 1]),
                 lambda b: b.ParentIndex())
    assert np.allclose(gunW[:3], np.eye(4), atol=1e-7)
    wrist, prop = ai['def_r_wrist'], ai['ja_c_propGun']
    files = ['fuse_idle_rifle_0.cast'] + [f'fuse_run_rifle_F_{i}.cast' for i in range(3)]
    paths = [ANIMS/file for file in files]
    qc = FUSE_QC
    rig_base = ASSETS
    rig_name = 'pilot_medium_fuse'
    fallback = False
    if legend == 'octane':
        from octane_sequence import export_idle
        clip = export_idle(out)
        fallback = clip is None
        paths = [clip or ANIMS/'fuse_idle_rifle_0.cast']
        files = [paths[0].name]
        qc = ASSETS/'octane/smd/mdl/Humans/class/medium/pilot_medium_stim.qc'
        rig_base = ASSETS/'octane'
        rig_name = 'pilot_medium_stim'
    rig_evidence = []
    rig_paths = [rig_base/f'cast/animrig/humans/class/medium/{name}.cast'
                 for name in [rig_name, 'mp_pilot_medium_core']]
    for path in rig_paths:
        rig = Cast.load(str(path)).Roots()[0].ChildrenOfType(Model)[0]
        bones = rig.Skeleton().Bones()
        rig_evidence.append(dict(file=str(path.relative_to(ROOT)), bone_count=len(bones),
            attachment_bones=[dict(index=i, name=b.Name(), parent=bones[b.ParentIndex()].Name(),
                                   local_position=list(b.LocalPosition()), local_rotation_xyzw=list(b.LocalRotation()))
                              for i, b in enumerate(bones)
                              if b.Name() in ('ja_c_propGun', 'ja_r_propHand', 'def_r_wrist')]))
    clips = []
    reference = None
    idleW = None
    for path in paths:
        anim, frames, tracks, unmapped = decode(path, ab)
        assert all(t['mode'] == 0 for t in tracks)
        values = []
        for frame in range(frames):
            W = animation_world(ab, tracks, frame)
            values.append(np.linalg.inv(W[wrist]) @ W[prop])
        values = np.stack(values)
        if reference is None:
            reference = values[0].copy()
            idleW = animation_world(ab, tracks, 0, remove_root=True)
        distance = np.linalg.norm(values[:, :3, 3]-reference[:3, 3], axis=1)
        rotation = rotation_difference(values, reference)
        own_distance = np.linalg.norm(values[:, :3, 3]-values[0, :3, 3], axis=1)
        own_rotation = rotation_difference(values, values[0])
        label = ('$OUTPUT/'+path.relative_to(out).as_posix()) if path.is_relative_to(out) else str(path.relative_to(ROOT))
        clips.append(dict(file=label, frames=frames,
                          fps=anim.Framerate(), unmapped_model_bones=unmapped,
                          vs_selected_translation_max_source_units=float(distance.max()),
                          vs_selected_translation_max_m=float(distance.max()*Q[0, 0]),
                          vs_selected_rotation_max_deg=float(rotation.max()),
                          within_clip_translation_max_source_units=float(own_distance.max()),
                          within_clip_rotation_max_deg=float(own_rotation.max()),
                          samples=[dict(frame=f, gun_root_to_wrist_apex=values[f].tolist())
                                   for f in [0, frames//2, frames-1]],
                          all_frames_gun_root_to_wrist_apex=values.tolist()))
    if fallback:
        reference = fuse_reference()
        idleW[prop] = idleW[wrist] @ reference
    # Use the actual AM template, not a numerically close HKX substitute.
    nodes = read(ROOT/'er-data/json/parts/AM_M_1500.json')['Nodes']
    templateW = world(nodes, lambda b: trs(b['Translation'], b['RotationQuaternion'], b['Scale']),
                      lambda b: b['ParentIndex'])
    hand = next(i for i, b in enumerate(nodes) if b['Name'] == 'R_Hand')
    assert 'Bone' in nodes[hand]['Flags'] and 'Disabled' not in nodes[hand]['Flags']
    handE = templateW[hand]
    converted = Q @ reference @ np.linalg.inv(Q)
    local = np.linalg.inv(handE) @ P[wrist] @ converted
    source_to_bind = handE @ local @ Q
    muzzle = gunW[names.index('muzzle_flash')]
    # The source muzzle's +X points along the barrel. Confirm geometrically
    # against the suppressor mount and muzzle, rather than assuming an FX axis.
    mount = gunW[names.index('def_c_suppressor'), :3, 3]
    forward = unit(muzzle[:3, 3]-mount)
    assert np.dot(forward, muzzle[:3, 0]) > .99999
    muzzle_local = (local @ Q @ np.r_[muzzle[:3, 3], 1])[:3]
    forward_local = unit((local @ Q)[:3, :3] @ forward)
    result = dict(format='fuse-gun-grip', version=1,
                  matrix_convention='column vectors; world = parent_world @ local; translation in last column',
                  apex_units='unchanged Source model units; 0.0254 m inference inherited from T005',
                  er_units='meters', selected_clip=files[0], selected_frame=0,
                  attachment=dict(character_bone='ja_c_propGun', character_attachment='PROPGUN',
                                  character_qc=str(qc.relative_to(ROOT)),
                                  character_qc_line=attachment_line(qc, 'PROPGUN'),
                                  weapon_root='ja_c_propGun', weapon_bone='weapon_bone',
                                  weapon_root_bind=gunW[0].tolist(), weapon_qc=str(GUN_QC.relative_to(ROOT)),
                                  method='same-name coincident bone frame; gun root/weapon_bone/def_c_base are identity',
                                  inference='Bone-frame matching is inferred from identical root name and bind frames. '
                                            'PROPGUN QC rotate describes attachment axes; it is not applied again to the Y-up Cast root. '
                                            'No runtime engine parent/bone-merge behavior has been observed.'),
                  source_right_hand='def_r_wrist', target_right_hand='R_Hand',
                  animation_rig_attachment_evidence=rig_evidence,
                  right_hand_choice=('def_r_wrist is T005 R_Hand owner; ja_r_propHand is a separate animation attachment with a nonzero rig bind offset' if legend == 'fuse' else
                                     'def_r_wrist is T015 R_Hand owner; ja_r_propHand is a separate animation attachment with a nonzero rig bind offset'),
                  scaled_axis_unit_matrix=Q.tolist(), uniform_scale=align['uniform_scale'],
                  gun_root_to_right_hand_apex=reference.tolist(),
                  gun_root_to_right_hand_er_converted=converted.tolist(),
                  gun_root_to_R_Hand_er=local.tolist(),
                  er_matrix_input='gun vertices already converted by Q; includes T005 aligned wrist P and AM template E',
                  aligned_wrist_P=P[wrist].tolist(), template_R_Hand_world=handE.tolist(),
                  source_gun_to_er_bind=source_to_bind.tolist(),
                  formula='bind_vertex = E_AM_R_Hand @ H @ Q @ source_vertex; H = inverse(E_AM_R_Hand) @ P_wrist @ Q @ G @ inverse(Q)',
                  muzzle=dict(attachment='muzzle_flash', bone='muzzle_flash',
                              qc_line=attachment_line(GUN_QC, 'muzzle_flash'),
                              source_model_position=muzzle[:3, 3].tolist(),
                              er_R_Hand_local_position=muzzle_local.tolist(),
                              er_R_Hand_local_barrel_direction=forward_local.tolist(),
                              direction_evidence='unit(muzzle_flash.position - def_c_suppressor.position), agrees with muzzle bone +X',
                              er_bind_world_position=(source_to_bind@np.r_[muzzle[:3, 3], 1])[:3].tolist(),
                              er_bind_world_barrel_direction=unit(source_to_bind[:3, :3]@forward).tolist()),
                  clip_comparison=clips,
                  preview_root_rule='replace jx_c_delta TRS with model bind value; removes exporter origin rotation and root motion only',
                  limitations=['rigid whole gun: magazine, bolt, iron sights do not animate',
                               'single idle reference does not reproduce varying run grip',
                               'ER native animation has no left-hand rifle IK or aiming correction',
                               'ER reference hand points diagonally out/down: global forward aim requires a rifle pose'],
                  legend=legend, grip_source='Fuse T008 fallback' if fallback else f'{legend} idle Cast frame 0',
                  provenance_rule='local paths, sizes, parsed Cast/QC/JSON formats and direct byte comparisons; no content digest',
                  source_files=source_info([GUN_CAST, GUN_QC, qc, ASSETS/'r301_bodygroups.json',
                       ASSETS/('fuse_skeleton.json' if legend == 'fuse' else 'octane/skeletons/pilot_medium_stim.json'),
                       base_for(legend)/'align.json', *paths, *rig_paths], out))
    if legend == 'octane':
        fuseG = fuse_reference()
        fuseBind = skeleton_relation(read(ASSETS/'fuse_skeleton.json')['bones'])
        octaneBind = skeleton_relation(ab)
        result['fuse_comparison'] = dict(
            fuse_clip=str((ANIMS/'fuse_idle_rifle_0.cast').relative_to(ROOT)), fuse_frame=0,
            fuse_grip_apex=fuseG.tolist(), octane_minus_fuse_translation_source=(reference[:3, 3]-fuseG[:3, 3]).tolist(),
            translation_distance_source_units=float(np.linalg.norm(reference[:3, 3]-fuseG[:3, 3])),
            translation_distance_m=float(np.linalg.norm(reference[:3, 3]-fuseG[:3, 3])*Q[0, 0]),
            rotation_difference_deg=float(rotation_difference(reference[None], fuseG)[0]),
            fuse_bind_prop_to_wrist=fuseBind.tolist(), octane_bind_prop_to_wrist=octaneBind.tolist(),
            bind_translation_distance_source_units=float(np.linalg.norm(octaneBind[:3, 3]-fuseBind[:3, 3])),
            bind_rotation_difference_deg=float(rotation_difference(octaneBind[None], fuseBind)[0]))
        result['preview_pose_source'] = 'Fuse tracks applied by name; known grip attached rigidly' if fallback else 'Octane idle Cast frame 0'
        result['sequence_layers'] = 'QC addlayer octane_combat_idle_aims is not composed; use exported base clip at frame 0'
        if fallback:
            result['limitations'].append('待定：no Octane rifle idle in local list; Fuse grip and name-mapped Fuse preview used')
    save(out/'grip.json', result)
    return model, result, idleW
