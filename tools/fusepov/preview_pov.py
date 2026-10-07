"""Software previews: ER bind/carrier geometry un-mirrored into Apex display space."""
import argparse
import sys
from pathlib import Path
sys.dont_write_bytecode = True
import numpy as np
from PIL import Image, ImageDraw
from common import (ROOT, ARMS, GUN, RIG, RIG_QC, IDLE, REFERENCE, CARRIERS,
                    model, bone_data, bind_world, world, trs, unit, read, save, file_info,
                    Q, Q_INVERSE, MIRROR, legend_config, checked_out)
from mesh_pov import selection, load_parts
from export_anim import decode, rest_pose, pose_at
from preview import render


def animate():
    rig = model(RIG)
    bones = bone_data(rig.Skeleton().Bones())
    animation, frames, tracks, unknown = decode(IDLE, bones)
    if unknown or not all(t['mode'] == 1 for t in tracks):
        raise ValueError(f'Expected local additive idle: {unknown}')
    qc = RIG_QC.read_text(encoding='utf-8-sig')
    if 'ptpov_rspn101_idle_02_dmx__loop_sub_ptpov_rspn101_iron_ads_in_dmx_' not in qc:
        raise ValueError('QC no longer documents idle subtraction reference')
    reference, ref_frames, ref_tracks, unknown = decode(REFERENCE, bones)
    if unknown or not all(t['mode'] == 0 for t in ref_tracks):
        raise ValueError('Expected absolute ads_in reference')
    rest = rest_pose(bones)
    literal = pose_at(rest, tracks, 0)
    base = pose_at(rest, ref_tracks, 0)
    restored = pose_at(base, tracks, 0)
    # ParseAnimDesc_Origin unconditionally rotates even a delta root -90 Z.
    # Apply that exported coordinate change once, using the absolute base root.
    # At the requested frame 0 the physical root delta is identity.
    root_track = next(t for t in tracks if t['bone'] == 0)
    root_delta = trs(root_track['channels'][0][0], root_track['channels'][1][0], [1, 1, 1])
    expected_export_rotation = np.array([[0., 1., 0.], [-1., 0., 0.], [0., 0., 1.]])
    if not np.allclose(root_delta[:3, :3], expected_export_rotation, atol=2e-6) or not np.allclose(root_delta[:3, 3], 0):
        raise ValueError('Nonidentity physical idle root delta requires explicit conversion')
    restored[0] = base[0]
    idx = {b['name']: i for i, b in enumerate(bones)}

    def matrices(pose):
        return world(bones, lambda b: trs(pose[idx[b['name']], :3], pose[idx[b['name']], 3:7],
                                         pose[idx[b['name']], 7:]), lambda b: b['parent_index'])
    nonroot_error = float(np.max(abs(restored[1:] - base[1:])))
    return bones, idx, matrices(literal), matrices(restored), dict(
        idle=str(IDLE.relative_to(ROOT)), idle_source=file_info(IDLE), frame=0, frames=frames, fps=animation.Framerate(),
        idle_mode='additive', reference=str(REFERENCE.relative_to(ROOT)), reference_source=file_info(REFERENCE),
        reference_frame=0, reference_frame_status='inference: first frame of the QC-named subtraction source; validated by grip geometry',
        qc_source=str(RIG_QC.relative_to(ROOT)),
        qc_idle_source='ptpov_rspn101_idle_02_dmx__loop_sub_ptpov_rspn101_iron_ads_in_dmx_8CDE779D.smd',
        root_exporter_source='tools/apexassets/rsx_source/src/core/mdl/animdata.cpp: ParseAnimDesc_Origin',
        nonroot_idle_frame0_delta_error=nonroot_error,
        literal_note='idle_0 alone applied to rig bind is not a holding pose; it is a delta clip',
        restored_note='QC subtraction reference ads_in frame 0 + idle_0 frame 0; no mesh-fitting transforms')


def skin_cast(mdl, mesh, W, anim_index):
    bones = mdl.Skeleton().Bones()
    bind = bind_world(bones)
    deform = []
    followers = {}
    raw_weights = np.asarray(mesh.VertexWeightValueBuffer())
    raw_bones = np.asarray(mesh.VertexWeightBoneBuffer(), dtype=int)
    used = set(raw_bones[raw_weights > 0])
    for i, b in enumerate(bones):
        parent = i
        while parent >= 0 and bones[parent].Name() not in anim_index:
            parent = bones[parent].ParentIndex()
        if parent < 0:
            if i in used:
                raise ValueError(f'No named animation ancestor: {b.Name()}')
            deform.append(np.eye(4))
            continue
        name = bones[parent].Name()
        deform.append(W[anim_index[name]] @ np.linalg.inv(bind[parent]))
        if parent != i:
            followers[b.Name()] = name
    deform = np.stack(deform)
    p = np.asarray(mesh.VertexPositionBuffer()).reshape(-1, 3)
    n = unit(np.asarray(mesh.VertexNormalBuffer()).reshape(-1, 3))
    bi = np.asarray(mesh.VertexWeightBoneBuffer(), dtype=int).reshape(len(p), -1)
    bw = np.asarray(mesh.VertexWeightValueBuffer()).reshape(bi.shape)
    bw /= bw.sum(1)[:, None]
    pos = np.zeros_like(p)
    normal = np.zeros_like(n)
    for k in range(bi.shape[1]):
        D = deform[bi[:, k]]
        pos += bw[:, k, None]*(np.einsum('nij,nj->ni', D[:, :3, :3], p)+D[:, :3, 3])
        normal += bw[:, k, None]*np.einsum('nij,nj->ni', D[:, :3, :3], n)
    return dict(name=mesh.Name(), material=mesh.Material().Name(), positions=pos, normals=unit(normal),
                uv0=np.asarray(mesh.VertexUVLayerBuffer(0)).reshape(-1, 2),
                indices=np.asarray(mesh.FaceBuffer()).reshape(-1, 3)), followers


def camera_meshes(meshes, camera):
    inverse = np.linalg.inv(camera)
    result = []
    for m in meshes:
        sub = m.copy()
        sub['positions'] = m['positions']@inverse[:3, :3].T+inverse[:3, 3]
        sub['normals'] = unit(m['normals']@inverse[:3, :3].T)
        result.append(sub)
    return result


def perspective(path, meshes, textures, title):
    # Camera space is right=-X, up=+Y, forward=+Z. Hand labels are preserved.
    width, height = 1120, 840
    focal = width/(2*np.tan(np.deg2rad(90)/2))
    near = .79  # source units, approximately 2 cm
    rgb = np.full((height, width, 3), (21, 27, 35), np.uint8)
    depth = np.full((height, width), np.inf)
    coverage = {}
    for m in meshes:
        p = m['positions']
        tex = textures[m['material']]
        count = 0
        for face in m['indices']:
            polygon = [np.r_[p[i], m['uv0'][i]] for i in face]
            clipped = []
            for a, b in zip(polygon, polygon[1:]+polygon[:1]):
                if a[2] >= near:
                    clipped.append(a)
                if (a[2] >= near) != (b[2] >= near):
                    t = (near-a[2])/(b[2]-a[2])
                    clipped.append(a+t*(b-a))
            for j in range(1, len(clipped)-1):
                v = np.array([clipped[0], clipped[j], clipped[j+1]])
                z = v[:, 2]
                xy = np.c_[-v[:, 0]/z*focal+width/2, -v[:, 1]/z*focal+height/2]
                low = np.maximum(np.floor(xy.min(0)).astype(int), [0, 42])
                high = np.minimum(np.ceil(xy.max(0)).astype(int), [width-1, height-1])
                if (high < low).any():
                    continue
                x, y = np.meshgrid(np.arange(low[0], high[0]+1)+.5, np.arange(low[1], high[1]+1)+.5)
                a, b, c = xy
                den = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
                if abs(den) < 1e-9:
                    continue
                w0 = ((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/den
                w1 = ((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/den
                bary = np.stack([w0, w1, 1-w0-w1], axis=-1)
                invz = (bary/z).sum(-1)
                dz = 1/np.maximum(invz, 1e-12)
                d = depth[low[1]:high[1]+1, low[0]:high[0]+1]
                mask = (bary.min(-1) >= 0)&(dz < d)
                if not mask.any():
                    continue
                uv = np.einsum('...k,kj->...j', bary/z, v[:, 3:])/invz[..., None]
                tx = np.clip(((uv[..., 0]%1)*tex.shape[1]).astype(int), 0, tex.shape[1]-1)
                ty = np.clip(((uv[..., 1]%1)*tex.shape[0]).astype(int), 0, tex.shape[0]-1)
                brightness = .38+.62*max(0, float(np.dot(unit(m['normals'][face].mean(0)), unit([-.3, .7, -1.]))))
                color = np.clip(tex[ty, tx, :3]*brightness, 0, 255).astype(np.uint8)
                region = rgb[low[1]:high[1]+1, low[0]:high[0]+1]
                region[mask] = color[mask]
                d[mask] = dz[mask]
                count += int(mask.sum())
        coverage[m['name']] = count
    image = Image.fromarray(rgb)
    draw = ImageDraw.Draw(image)
    draw.text((20, 14), title, fill='white')
    draw.text((20, 30), 'Apex display (ER Z mirror undone): camera forward +Z / up +Y / right -X; horizontal FOV 90 deg', fill=(175, 187, 202))
    image.save(path)
    return coverage


def pack_frame0(pack):
    """Compose the same documented reference from the actual FPOV f32 samples and weights."""
    bones = [dict(name=b['name'], parent_index=b['parent']) for b in pack['bones']]
    base = np.c_[pack['clips']['ads_in_0']['poses'][0].astype(float), np.ones((len(bones), 3))]
    idle = pack['clips']['idle_0']
    if not idle['additive'] or pack['clips']['ads_in_0']['additive']:
        raise ValueError('Preview pack has unexpected reference/idle modes')
    tracks = [dict(bone=i, mode=1, weights=[*idle['weights'][i], 1.],
                   channels=[idle['poses'][0, i, :3][None, :], idle['poses'][0, i, 3:7][None, :], None])
              for i in range(len(bones))]
    pose = pose_at(base, tracks, 0)
    delta = trs(idle['poses'][0, 0, :3], idle['poses'][0, 0, 3:7], [1, 1, 1])
    if not np.allclose(delta[:3, :3], [[0, 1, 0], [-1, 0, 0], [0, 0, 1]], atol=2e-6) or not np.allclose(delta[:3, 3], 0):
        raise ValueError('Pack root delta is not the documented pure export rotation')
    pose[0] = base[0]
    index = {b['name']: i for i, b in enumerate(bones)}
    return world(bones, lambda b: trs(pose[index[b['name']], :3], pose[index[b['name']], 3:7], [1, 1, 1]),
                 lambda b: b['parent_index'])


def surface_distances(points, meshes):
    """Exact nearest distance from each selected finger vertex to all posed gun triangles."""
    triangles = np.concatenate([m['positions'][m['indices']] for m in meshes])
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    ab, ac = b-a, c-a
    d00, d01, d11 = (ab*ab).sum(1), (ab*ac).sum(1), (ac*ac).sum(1)
    denominator = d00*d11-d01*d01
    normal = np.cross(ab, ac)
    nn = (normal*normal).sum(1)
    distances = []
    for start in range(0, len(points), 24):
        p = points[start:start+24, None, :]
        pa = p-a
        d20, d21 = (pa*ab).sum(2), (pa*ac).sum(2)
        u = (d11*d20-d01*d21)/np.maximum(denominator, 1e-20)
        v = (d00*d21-d01*d20)/np.maximum(denominator, 1e-20)
        inside = (u >= 0)&(v >= 0)&(u+v <= 1)&(denominator > 1e-20)
        best = np.where(inside, (pa*normal).sum(2)**2/np.maximum(nn, 1e-20), np.inf)
        for begin, end in ((a, b), (b, c), (c, a)):
            edge = end-begin
            t = np.clip(((p-begin)*edge).sum(2)/np.maximum((edge*edge).sum(1), 1e-20), 0, 1)
            distance = ((p-begin-t[..., None]*edge)**2).sum(2)
            best = np.minimum(best, distance)
        distances.extend(np.sqrt(best.min(1)))
    values = np.asarray(distances)*.0254
    return dict(vertices=len(values), minimum_m=float(values.min()), p05_m=float(np.quantile(values, .05)),
                median_m=float(np.median(values)), within_1mm_vertices=int((values <= .001).sum()))


def finger_contacts(legend, native, carriers):
    arms = next((mdl, mesh) for kind, mdl, mesh in selection(legend=legend) if kind == 'arms')
    mdl, mesh = arms
    bones = mdl.Skeleton().Bones()
    bi = np.asarray(mesh.VertexWeightBoneBuffer(), dtype=int).reshape(mesh.VertexCount(), -1)
    bw = np.asarray(mesh.VertexWeightValueBuffer()).reshape(bi.shape)
    bw = bw/bw.sum(1)[:, None]
    native_arms = next(m for m in native if m['name'] == mesh.Name())
    native_gun = [m for m in native if m['name'] != mesh.Name()]
    carrier_arms = [m for m in carriers if m['name'] == mesh.Name()]
    carrier_gun = [m for m in carriers if m['name'] != mesh.Name()]
    report = dict(method='unsigned vertex-to-triangle distance to all selected gun surfaces; finger vertices require normalized summed fin* weight > 0.25; no manual fitting')
    for side in ('l', 'r'):
        finger_bones = np.array([b.Name().startswith(f'def_{side}_fin') for b in bones])
        selected = (np.where(finger_bones[bi], bw, 0).sum(1) > .25)
        native_points = native_arms['positions'][selected]
        carrier_points = np.concatenate([m['positions'][selected[m['source_vertex_ids']]] for m in carrier_arms])
        report[side] = dict(native=surface_distances(native_points, native_gun),
                            quantized_carriers=surface_distances(carrier_points, carrier_gun))
    report['limitation'] = 'Unsigned distances establish proximity, not penetration depth; grip/handguard identification requires the accompanying views.'
    return report


def make_previews(out, parts=None, textures=None, legend='fuse', pack_path=None):
    config = legend_config(legend)
    arms_path = config['arms']
    parts = parts or load_parts(out)
    textures = textures or {m: np.asarray(Image.open(out/'textures'/f'{m}_a.png').convert('RGBA'))
                            for m in (config['arms_material'], 'r301_base_main')}
    dest = out/'preview'
    dest.mkdir(parents=True, exist_ok=True)
    for kind, path in [('arms', arms_path), ('gun', GUN)]:
        meshes = []
        for part_meshes in parts.values():
            for mesh in part_meshes:
                if mesh['model'] != kind:
                    continue
                meshes.append(dict(positions=np.asarray(mesh['positions'], dtype='<f4') * np.diag(MIRROR),
                                   normals=unit(mesh['normals'] * np.diag(MIRROR)),
                                   uv0=mesh['uv0'], indices=mesh['indices'], material=mesh['material']))
        for view, yaw in [('front', 180), ('side', 90)]:
            render(dest/f'{kind}_bind_{view}.png', {'am' if kind == 'arms' else 'bd': meshes}, [],
                   np.zeros((0, 4, 4)), f'{kind} / ER bind un-mirrored for Apex display / {view}', yaw, textures)
    bones, idx, literal, restored, report = animate()
    report['renders'] = {}
    report['display_space'] = 'ER geometry un-mirrored into Apex space for display'
    report['apex_to_er_matrix'] = Q.tolist()
    report['er_to_apex_matrix'] = Q_INVERSE.tolist()
    report['binding_display'] = 'actual converted ER positions in meters with Z reflection undone; no camera fitting transforms'
    report['native_animation_display'] = 'original Apex-space animation bone world * model bind inverse * Cast vertex; matches un-mirrored ER geometry'
    report['carrier_pose_space'] = 'ER: D_er = Q * W_anim_owner * inverse(B_model_owner) * inverse(Q); applied to serialized mirrored bind positions'
    restored_cam = None
    for name, W in [('idle_frame0_literal', literal), ('idle_frame0', restored)]:
        posed = []
        followers = {}
        for kind, mdl, mesh in selection(legend=legend):
            m, f = skin_cast(mdl, mesh, W, idx)
            posed.append(m)
            followers[kind] = f
        camera = W[idx['jx_c_camera']]
        cam = camera_meshes(posed, camera)
        report['renders'][name] = dict(camera_world_apex=camera.tolist(), camera_world_er=(Q @ camera @ Q_INVERSE).tolist(), nonanimated_followers=followers,
            rasterized_pixels=perspective(dest/f'{name}_camera.png', cam, textures,
              'idle_0 frame 0 / '+('additive on rig bind (diagnostic)' if W is literal else 'QC reference restored / native Apex skin')))
        if name == 'idle_frame0':
            restored_cam = cam
            # Orthographic inspection preserves camera local axes and exposes grip contacts.
            normalized = [{**m, 'positions': m['positions']*.0254} for m in cam]
            for view, yaw in [('side', 90), ('oblique', 140)]:
                render(dest/f'idle_frame0_{view}.png', {'am': [normalized[0]], 'bd': normalized[1:]},
                       [], np.zeros((0, 4, 4)), f'QC reference + idle_0 frame 0 / un-mirrored Apex camera space / {view}', yaw, textures)
    # Also render the actual carrier mesh with its four weights, for runtime approximation review.
    mapping = read(CARRIERS)
    packed = None
    carrier_world = restored
    if legend == 'octane':
        sys.path.insert(0, str(ROOT/'tools/apexpov'))
        from verify_pov_pack import read_pack, make_bind_variant, check_mesh_binds, compare_bind_variant
        preview_pack = out/'inputs/preview-fuse_pov.anim'
        if pack_path is None:
            audit = make_bind_variant(legend, preview_pack)
        else:
            import shutil
            packed_source = read_pack(pack_path)
            audit = check_mesh_binds(packed_source, legend)
            audit.update(compare_bind_variant(read_pack(ROOT/'apex-data/pov/fuse_pov.anim'), packed_source))
            shutil.copyfile(pack_path, preview_pack)
        packed = read_pack(preview_pack)
        carrier_world = pack_frame0(packed)
        report['carrier_pack'] = audit
        report['carrier_mesh_source'] = 'serialized 998 FLVER readback'
        report['carrier_animation_source'] = 'FPOV f32 ads_in_0 frame 0 + idle_0 frame 0, using packed weights and the documented export-root correction'
        report['pack_cast_world_matrix_max_error'] = float(np.max(abs(np.asarray(carrier_world)-np.asarray(restored))))
        if config['pack'].is_file():
            if config['pack'].read_bytes() != preview_pack.read_bytes():
                raise ValueError('Preview pack differs from the baked Octane pack')
            report['preview_pack_byte_identical_to_baked_octane'] = True
        save(out/'preview-pack-bind-audit.json', audit)
    posed_carriers = []
    native_by_name = {m['name']: m for m in restored_cam}
    errors = {}
    max_skin_equivalence = 0.
    for part, meshes in parts.items():
        for mesh_number, m in enumerate(meshes):
            bind = bind_world(model(arms_path if m['model'] == 'arms' else GUN).Skeleton().Bones())
            source_bones = model(arms_path if m['model'] == 'arms' else GUN).Skeleton().Bones()
            source_idx = {b.Name(): i for i, b in enumerate(source_bones)}
            # Keep a dictionary because models do not contain every carrier owner.
            transform = {i: restored[idx[c['owner']]] @ np.linalg.inv(bind[source_idx[c['owner']]])
                         for i, c in enumerate(mapping['carriers']) if c['owner'] in source_idx}
            bind_positions = np.asarray(m['positions'], dtype='<f4').astype(float)
            bind_normals = np.asarray(m['normals'], dtype='<f4').astype(float)
            apex_bind_positions = bind_positions @ Q_INVERSE[:3, :3].T
            pos_er = np.zeros_like(bind_positions)
            normal_er = np.zeros_like(bind_normals)
            direct_apex = np.zeros_like(bind_positions)
            from verify_pov import quantize_weights
            bw = quantize_weights(np.asarray(m['bone_weights'], dtype='<f4'))/255.
            indices = m['bone_indices']
            if packed is not None:
                from bake_pov import trs as pack_trs
                transform = {i: carrier_world[record['owner']] @ pack_trs(record['inverse_mesh_bind'][:3], record['inverse_mesh_bind'][3:])
                             for i, record in enumerate(packed['carrier_records'])}
                from verify_pov import stream
                folder = out/'readback'/f'export_{part}'
                doc = read(folder/'mesh.json')
                submesh = doc['submeshes'][mesh_number]
                if submesh['vertex_count'] != len(m['positions']) or submesh['index_count'] != m['indices'].size:
                    raise ValueError('Readback/preview mesh dimensions differ')
                bind_positions = stream(folder, submesh, 'positions').astype(float)
                bind_normals = stream(folder, submesh, 'normals').astype(float)
                apex_bind_positions = bind_positions @ Q_INVERSE[:3, :3].T
                bw = stream(folder, submesh, 'flver_bone_weights').astype(float)
                lookup = {c['carrier']: i for i, c in enumerate(mapping['carriers'])}
                indices = np.array([lookup.get(n, -1) for n in doc['bones']])[stream(folder, submesh, 'bone_indices')]
                if (indices < 0).any():
                    raise ValueError('Serialized preview mesh uses a non-carrier bone')
            for k in range(4):
                ds = np.stack([transform[int(i)] for i in indices[:, k]])
                ds_er = Q @ ds @ Q_INVERSE
                pos_er += bw[:, k, None]*(np.einsum('nij,nj->ni', ds_er[:, :3, :3], bind_positions)+ds_er[:, :3, 3])
                normal_er += bw[:, k, None]*np.einsum('nij,nj->ni', ds_er[:, :3, :3], bind_normals)
                direct_apex += bw[:, k, None]*(np.einsum('nij,nj->ni', ds[:, :3, :3], apex_bind_positions)+ds[:, :3, 3])
            # Un-mirror only for display; the skin above really used corrected ER bind geometry.
            pos = pos_er @ Q_INVERSE[:3, :3].T
            normal = normal_er * np.diag(MIRROR)
            equivalence = float(np.linalg.norm(pos-direct_apex, axis=1).max()*.0254)
            max_skin_equivalence = max(max_skin_equivalence, equivalence)
            if equivalence >= 1e-12:
                raise ValueError(f'ER skin / un-mirrored Apex skin disagreement: {equivalence} m')
            sub = {**m, 'positions': pos, 'normals': unit(normal)}
            if packed is not None:
                sub['uv0'] = stream(folder, submesh, 'uv0')
                sub['indices'] = stream(folder, submesh, 'indices')
            sub = camera_meshes([sub], carrier_world[idx['jx_c_camera']])[0]
            posed_carriers.append(sub)
            distance = np.linalg.norm(sub['positions']-native_by_name[m['name']]['positions'][m['source_vertex_ids']], axis=1)*.0254
            errors[part+'/'+m['name']] = dict(max_m=float(distance.max()), p99_m=float(np.quantile(distance, .99)))
    report['carrier_native_difference'] = errors
    if legend == 'octane':
        report['finger_contacts'] = finger_contacts(legend, restored_cam, posed_carriers)
    report['max_er_unmirror_skin_error_m'] = max_skin_equivalence
    report['carrier_camera_pixels'] = perspective(dest/'idle_frame0_carriers_camera.png', posed_carriers, textures,
                                                 'QC reference + idle_0 frame 0 / ER carrier skin un-mirrored for Apex display')
    report['camera_axes'] = dict(space='un-mirrored Apex display', forward='+Z', up='+Y', right='-X', horizontal_fov_deg=90,
        fov_status='software inspection choice, not an Apex gameplay parameter',
        axis_evidence='raw Cast gun muzzle is beyond suppressor along +Z; use proper-handed view right=cross(forward,up)')
    report['er_camera_axes'] = dict(forward='-Z', up='+Y', right='-X',
                                    conversion='Q maps Apex local axes into ER; camera world transform is Q * camera_apex * inverse(Q)')
    gunmdl = model(GUN)
    gbind = bind_world(gunmdl.Skeleton().Bones())
    gi = {b.Name(): i for i, b in enumerate(gunmdl.Skeleton().Bones())}
    baseD = restored[idx['def_c_base']] @ np.linalg.inv(gbind[gi['def_c_base']])
    muzzle = (baseD @ np.r_[gbind[gi['muzzle_flash'], :3, 3], 1])[:3]
    mount = (baseD @ np.r_[gbind[gi['def_c_suppressor'], :3, 3], 1])[:3]
    camera = restored[idx['jx_c_camera']]
    forward = unit(np.linalg.solve(camera[:3, :3], muzzle-mount))
    report['gun_forward_camera'] = forward.tolist()
    if forward[2] <= .9:
        raise ValueError(f'Gun does not face camera forward: {forward}')
    report['status'] = 'PASS geometry and camera; additive reference documented; visual grip review required'
    save(out/'preview-verification.json', report)
    print(f'PASS previews: corrected ER bind/skin un-mirrored for Apex display; idle_0 diagnostic and QC reference restored; '
          f'barrel Apex camera {forward}; ER/Apex skin error {max_skin_equivalence:.3g} m', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legend', choices=('fuse', 'octane'), default='fuse')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--pack', type=Path, help='Explicit baked FPOV for the Octane carrier preview')
    args = parser.parse_args()
    make_previews(checked_out(args.out or legend_config(args.legend)['out'], args.legend),
                  legend=args.legend, pack_path=args.pack)
