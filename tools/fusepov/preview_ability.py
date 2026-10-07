"""T020 software views from serialized FPOV v2 and quantized 998 FLVER geometry."""
import argparse
import sys
from pathlib import Path
sys.dont_write_bytecode = True
import numpy as np
from PIL import Image
from common import Q, Q_INVERSE, MIRROR, unit, read, save
from mesh_ability import ac
from verify_pov import stream
from preview_pov import perspective, camera_meshes, surface_distances, pack_frame0

REQUESTED = [('stim_draw_0', -1, [0, 2]), ('stim_idle_0', 0, [0, 2]),
             ('stim_holster_throwAway_0', 20, [0, 2]),
             ('pad_toss_prep_pullout_0', 0, [0, 3]), ('pad_toss_0', 9, [0, 3])]


def mix(base, clip, frame):
    pose = base.copy()
    values, weights = clip['poses'][frame].astype(float), clip['weights'].astype(float)
    if clip['additive']:
        pose[:, :3] += weights[:, :1]*values[:, :3]
        pose[:, 3:] = ac.bp.ea.normalize(ac.bp.ea.mul(pose[:, 3:], ac.bp.ea.slerp(
            np.tile([0., 0., 0., 1.], (len(pose), 1)), values[:, 3:], weights[:, 1:])))
        # RSX adds an export rotation even to a delta root. Remove it only when
        # this requested sample proves a pure export rotation, as in T011/T016.
        root = ac.bp.trs(values[0, :3], values[0, 3:])
        expected = [[0, 1, 0], [-1, 0, 0], [0, 0, 1]]
        ac.require(np.allclose(root[:3, :3], expected, atol=2e-6) and np.allclose(root[:3, 3], 0), 'Preview root needs a physical-delta conversion')
        pose[0] = base[0]
    else:
        pose[:, :3] = base[:, :3]+weights[:, :1]*(values[:, :3]-base[:, :3])
        pose[:, 3:] = ac.bp.ea.slerp(base[:, 3:], values[:, 3:], weights[:, 1:])
    return pose


def idle_pose(pack, onehanded=False):
    base = pack['clips']['ads_in_0']['poses'][0].astype(float)
    pose = mix(base, pack['clips']['idle_0'], 0)
    if onehanded:
        qc = ac.read_qc(ac.ROOT/'apex-data/pov/smd/animrig/weapons/rspn101/ptpov_rspn101.qc')
        alias = qc['sequences']['idle_onehanded']['sample_animation_names'][0]
        source = qc['animations'][alias]['file']
        ac.require('_sub_ptpov_rspn101_onehanded_iron_ads_in_' in source, 'Local one-handed subtraction reference changed')
        pose = mix(pose, pack['clips']['ads_in_onehanded_0'], 0)
        pose = mix(pose, pack['clips']['idle_onehanded_0'], 0)
    return pose


def load_meshes(out, pack):
    carriers = {c['name']: i for i, c in enumerate(pack['carrier_records'])}
    meshes = []
    textures = {}
    for part in ('am', 'bd', 'hd', 'lg'):
        inputfolder = (ac.BASE_MODEL if part in ('am', 'bd') else out)/'fusemesh'/part
        inputs = read(inputfolder/'mesh.json')
        folder = out/'readback'/f'export_{part}'
        doc = read(folder/'mesh.json')
        ac.require(len(inputs['submeshes']) == len(doc['submeshes']), 'Preview source/readback count differs')
        for s, source in zip(doc['submeshes'], inputs['submeshes']):
            bi = stream(folder, s, 'bone_indices')
            bw = stream(folder, s, 'flver_bone_weights').astype(float)
            names = np.asarray(doc['bones'])[bi]
            lookup = np.array([[carriers.get(n, -1) for n in row] for row in names])
            ac.require(not (lookup[bw > 0] < 0).any(), 'Positive non-carrier influence in preview')
            lookup[bw == 0] = 0
            groups = {pack['carrier_records'][int(i)]['group'] for i in lookup[bw > 0]}
            ac.require(len(groups) == 1, 'Mixed mesh groups require splitting')
            material = inputs['materials'][source['material']]['name']
            textures[material] = np.asarray(Image.open(inputfolder/inputs['materials'][source['material']]['textures']['a']).convert('RGBA'))
            meshes.append(dict(name=source['name'], material=material, part=part, group=next(iter(groups)),
                positions=stream(folder, s, 'positions').astype(float), normals=stream(folder, s, 'normals').astype(float),
                uv0=stream(folder, s, 'uv0'), indices=stream(folder, s, 'indices').astype(int),
                bone_indices=lookup, bone_weights=bw, source_vertex_ids=np.fromfile(inputfolder/source['source_vertex_ids'], '<u4')))
    return meshes, textures


def skin(meshes, pack, pose, world_override=None):
    worlds = ac.world7(pack['bones'], pose) if world_override is None else np.asarray(world_override)
    deforms = np.array([worlds[c['owner']]@ac.bp.trs(c['inverse_mesh_bind'][:3], c['inverse_mesh_bind'][3:]) for c in pack['carrier_records']])
    camera = worlds[pack['camera']]
    output = []
    error = 0.
    for mesh in meshes:
        p, n = mesh['positions'], mesh['normals']
        posed_er, normal_er, direct = np.zeros_like(p), np.zeros_like(n), np.zeros_like(p)
        apex = p@Q_INVERSE[:3, :3].T
        for k in range(4):
            d = deforms[mesh['bone_indices'][:, k]]
            der = Q@d@Q_INVERSE
            w = mesh['bone_weights'][:, k, None]
            posed_er += w*(np.einsum('nij,nj->ni', der[:, :3, :3], p)+der[:, :3, 3])
            normal_er += w*np.einsum('nij,nj->ni', der[:, :3, :3], n)
            direct += w*(np.einsum('nij,nj->ni', d[:, :3, :3], apex)+d[:, :3, 3])
        display = posed_er@Q_INVERSE[:3, :3].T
        error = max(error, float(np.linalg.norm(display-direct, axis=1).max()*.0254))
        output.append(dict(mesh, positions=display, normals=unit(normal_er*np.diag(MIRROR))))
    return camera_meshes(output, camera), error, camera


def finger_points(meshes, side):
    mdl = ac.model(ac.bp.OCTANE_ARMS)
    source = next(m for m in mdl.Meshes() if m.Name() == 'body_0_octane_base_v_arms')
    names = [b.Name() for b in mdl.Skeleton().Bones()]
    bi = np.asarray(source.VertexWeightBoneBuffer(), int).reshape(source.VertexCount(), -1)
    bw = np.asarray(source.VertexWeightValueBuffer(), float).reshape(bi.shape)
    bw /= bw.sum(1)[:, None]
    finger = np.asarray([n.startswith(f'def_{side}_fin') for n in names])[bi]
    selected = (np.where(finger, bw, 0).sum(1) > .25)
    return np.concatenate([m['positions'][selected[m['source_vertex_ids']]] for m in meshes if m['group'] == 0])


def ability_pose(pack, base, clip, frame, key):
    """Step 14's left-arm + current-prop scope; every other bone uses onehanded.

    The binary pack retains the complete local QC weights. The view's layer mask
    restricts their application to the requested subtrees, without mesh fitting.
    """
    left = next(i for i, b in enumerate(pack['bones']) if b['name'] == 'def_l_clav')
    own = {b['index'] for b in ac.layout()['added'] if b['rig'] == key}
    selected = np.zeros(len(pack['bones']), bool)
    for i, bone in enumerate(pack['bones']):
        ancestor = i
        while ancestor >= 0 and ancestor != left:
            ancestor = pack['bones'][ancestor]['parent']
        selected[i] = ancestor == left or i in own
    weights = clip['weights'].copy()
    weights[~selected] = 0
    # All requested ability previews are absolute. Additive source values remain
    # in the pack and are not used as stand-alone holding poses.
    ac.require(not clip['additive'], 'Requested preview requires an absolute ability sample')
    return mix(base, dict(clip, weights=weights), frame)


def make_previews(out=None, pack_path=None):
    out = ac.checked(out or ac.MODEL_ROOT, ac.MODEL_ROOT)
    pack = ac.read_pack(pack_path or out/'inputs/fuse_pov.anim')
    ac.require(pack['version'] == 2, 'Preview requires FPOV v2')
    meshes, textures = load_meshes(out, pack)
    folder = out/'preview'; folder.mkdir(parents=True, exist_ok=True)
    report = dict(format='octane-ability-preview-verification', version=1,
        source='Serialized quantized 998 FLVER readback and FPOV v2 f32 clips/weights/inverse binds',
        camera_axes=dict(forward='+Z', up='+Y', right='-X', horizontal_fov_deg=90),
        display_space='ER geometry un-mirrored into Apex space for display',
        base='QC-named ads_in_onehanded_0 frame 0 + idle_onehanded_0 frame 0, export root applied once',
        base_reference_frame_status='Inference: QC subtraction name has no explicit frame argument; same T011/T016 rule.',
        previews=[], diagnostic_previews=[], max_er_apex_skin_error_m=0., limitations=[],
        ability_layer_scope='Step 14: apply source weights only on the def_l_clav subtree and current prop subtree; all other bones retain idle_onehanded frame 0',
        binary_clip_weights_unchanged=True)
    base = idle_pose(pack, True)
    for name, frame, groups in REQUESTED:
        clip = pack['clips'][name]
        f = clip['frames']-1 if frame == -1 else frame
        ac.require(f < clip['frames'], 'Preview frame outside clip')
        key = 'epipen' if name.startswith('stim_') else 'jumppad'
        pose = ability_pose(pack, base, clip, f, key)
        posed, error, camera = skin(meshes, pack, pose)
        report['max_er_apex_skin_error_m'] = max(report['max_er_apex_skin_error_m'], error)
        propgroup = groups[1]
        contacts = dict(left_prop=surface_distances(finger_points(posed, 'l'), [m for m in posed if m['group'] == propgroup]),
                        right_rifle=surface_distances(finger_points(posed, 'r'), [m for m in posed if m['group'] == 1]))
        for show in (groups, [0, 1, 2, 3]):
            suffix = 'ability' if show == groups else 'all_groups'
            filename = f'{name}_frame{f}_{suffix}.png'
            shown = [m for m in posed if m['group'] in show]
            pixels = perspective(folder/filename, shown, textures, f'{name} frame {f} / quantized 998 / groups {show}')
            report['previews'].append(dict(file=filename, clip=name, frame=f, groups=show,
                rasterized_pixels=pixels, finger_distances=contacts, camera_apex=camera.tolist()))
    # The required pad frame 9 is already after the local QC release at frame 8.
    # Add a source frame before release to make the actual left-hand grip reviewable.
    pose = ability_pose(pack, base, pack['clips']['pad_toss_0'], 5, 'jumppad')
    posed, error, camera = skin(meshes, pack, pose)
    contacts = dict(left_prop=surface_distances(finger_points(posed, 'l'), [m for m in posed if m['group'] == 3]),
                    right_rifle=surface_distances(finger_points(posed, 'r'), [m for m in posed if m['group'] == 1]))
    for groups, suffix in [([0, 3], 'ability'), ([0, 1, 2, 3], 'all_groups')]:
        filename = f'pad_toss_0_frame5_{suffix}.png'
        pixels = perspective(folder/filename, [m for m in posed if m['group'] in groups], textures,
                             f'pad_toss_0 frame 5 BEFORE QC release at frame 8 / groups {groups}')
        report['diagnostic_previews'].append(dict(file=filename, clip='pad_toss_0', frame=5, groups=groups,
            rasterized_pixels=pixels, finger_distances=contacts, camera_apex=camera.tolist()))
    report['max_er_apex_skin_error_m'] = max(report['max_er_apex_skin_error_m'], error)
    pose = idle_pose(pack)
    posed, error, camera = skin(meshes, pack, pose, pack_frame0(pack))
    shown = [m for m in posed if m['group'] in (0, 1)]
    filename = 'idle_0_frame0_groups01.png'
    # Same meshes, camera and renderer as the accepted T016 quantized image.
    pixels = perspective(folder/filename, shown, textures, 'QC reference + idle_0 frame 0 / ER carrier skin un-mirrored for Apex display')
    report['previews'].append(dict(file=filename, clip='idle_0', frame=0, groups=[0, 1], rasterized_pixels=pixels, camera_apex=camera.tolist()))
    old = ac.read_pack(ac.BASE_PACK)
    oldworld = np.asarray(pack_frame0(old))
    newworld = np.asarray(pack_frame0(pack))[:102]
    report['idle_t016_geometry_equal'] = bool(np.array_equal(oldworld, newworld))
    previous = ac.BASE_MODEL/'preview/idle_frame0_carriers_camera.png'
    report['idle_t016_pixels_equal'] = bool(previous.is_file() and np.array_equal(np.asarray(Image.open(previous)), np.asarray(Image.open(folder/filename))))
    report['max_er_apex_skin_error_m'] = max(report['max_er_apex_skin_error_m'], error)
    report['limitations'] = [
        'Unsigned finger-to-surface distances measure proximity, not penetration.',
        'The local default pad weight list controls both arms; onehanded pad alternatives mask the left arm. Step 14 preview applies the original weights only inside its requested left-arm/current-prop subtrees; the binary weights remain exact.',
        'stim_holster_throwAway frame 20 and pad_toss frame 9 are after prop release; pad_toss_prep_pullout frame 0 is a preparation pose, not a closed grip. The additional pad_toss frame 5 demonstrates holding.',
        'Groups 0..3 also show the other, inactive prop at its weight-zero bind pose.',
        'Opaque Metal template approximates injector glass; final shader lighting needs the project lead game test.',
        'FOV=90 is a software inspection setting, not an inferred gameplay parameter.']
    save(out/'ability-preview-verification.json', report)
    print(f'PASS T020 previews: 11 requested + 2 before-release images; idle T016 geometry={report["idle_t016_geometry_equal"]}, pixels={report["idle_t016_pixels_equal"]}; '
          f'ER/Apex skin error {report["max_er_apex_skin_error_m"]:.3g} m', flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--pack', type=Path)
    args = parser.parse_args()
    make_previews(args.out, args.pack)
