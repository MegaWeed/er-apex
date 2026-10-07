"""T005 software renderer, ER bind and actual Cast idle world pose transported by O."""
import argparse
import numpy as np
from PIL import Image, ImageDraw
from common import ROOT, PARTS, read, save, unit
from common import add_options, default_out, checked_out, alignment_for
from verify_fuse import array
from preview import render


def load_parts(out, eb):
    lookup = {b['Name']: i for i, b in enumerate(eb)}
    parts, textures = {}, {}
    for part in PARTS:
        folder = out/'fusemesh'/part
        doc = read(folder/'mesh.json')
        palette = np.array([lookup[n] for n in doc['bones']])
        parts[part] = []
        for s in doc['submeshes']:
            m = {key: array(folder, s, key) for key in
                 ['positions', 'normals', 'tangents', 'uv0', 'uv1', 'bone_indices', 'bone_weights', 'indices']}
            m['bone_indices'] = palette[m['bone_indices']]
            m['material'] = doc['materials'][s['material']]['name']
            m['name'] = s['name']
            parts[part].append(m)
        for m in doc['materials']:
            textures[m['name']] = np.asarray(Image.open(folder/m['textures']['a']).convert('RGBA'))
    return parts, textures


def pose_parts(parts, matrices, reference):
    D = matrices@np.linalg.inv(reference)
    result = {}
    for part, meshes in parts.items():
        result[part] = []
        for mesh in meshes:
            m = mesh.copy()
            position = np.zeros_like(mesh['positions'])
            normal = np.zeros_like(position)
            for k in range(4):
                ids = mesh['bone_indices'][:, k]
                weight = mesh['bone_weights'][:, k, None]
                position += weight*(np.einsum('nij,nj->ni', D[ids, :3, :3], mesh['positions'])+D[ids, :3, 3])
                normal += weight*np.einsum('nij,nj->ni', D[ids, :3, :3], mesh['normals'])
            m['positions'], m['normals'] = position, unit(normal)
            result[part].append(m)
    return result


def annotate(path, parts, hand_world, grip, yaw):
    # Repeat the renderer's projection exactly for the grip and barrel markers.
    width, height = 720, 920
    theta = np.deg2rad(yaw)
    right = np.array([np.cos(theta), 0, np.sin(theta)])
    basis = np.stack([right, [0, 1, 0], np.cross(right, [0, 1, 0])], axis=1)
    allp = np.concatenate([m['positions'] for meshes in parts.values() for m in meshes])@basis
    lo, hi = allp[:, :2].min(0), allp[:, :2].max(0)
    scale = min((width-80)/max(hi[0]-lo[0], .1), (height-150)/max(hi[1]-lo[1], .1))
    center = (lo+hi)/2
    def point(p):
        v = p@basis
        return ((v[0]-center[0])*scale+width/2, -(v[1]-center[1])*scale+height/2+20)
    hand = hand_world[:3, 3]
    muzzle = (hand_world@np.r_[grip['muzzle']['er_R_Hand_local_position'], 1])[:3]
    direction = unit(hand_world[:3, :3]@np.array(grip['muzzle']['er_R_Hand_local_barrel_direction']))
    im = Image.open(path).convert('RGB')
    draw = ImageDraw.Draw(im)
    x, y = point(hand)
    draw.ellipse((x-5, y-5, x+5, y+5), outline=(80, 240, 230), width=2)
    draw.text((x+8, y-16), 'R_Hand', fill=(80, 240, 230))
    start, end = point(muzzle), point(muzzle+direction*.16)
    draw.line([start, end], fill=(255, 192, 75), width=3)
    draw.ellipse((start[0]-4, start[1]-4, start[0]+4, start[1]+4), fill=(255, 192, 75))
    draw.text((end[0]+6, end[1]), 'barrel', fill=(255, 192, 75))
    draw.text((24, 44), 'cyan: right-hand joint / orange: muzzle and barrel direction', fill=(215, 225, 232))
    im.save(path)
    return dict(hand_world_m=hand.tolist(), muzzle_world_m=muzzle.tolist(), barrel_world=direction.tolist())


def make_previews(out, state, idleW, legend='fuse'):
    out = checked_out(out)
    ab, eb, ai, ei, A, P, E, Q, mapping, enabled, align = state
    grip = read(out/'grip.json')
    parts, textures = load_parts(out, eb)
    # Use exact AM template hand reference for the gun, as in the builder.
    E = E.copy()
    E[ei['R_Hand']] = np.array(grip['template_R_Hand_world'])
    B = Q@idleW@np.linalg.inv(Q)
    F = E.copy()
    for record in align['mapped_bones']:
        F[record['er_index']] = B[record['apex_index']]@np.array(record['O_b'])
    # Remove the 6e-6 template/HKX numerical difference at the hand.
    F[ei['R_Hand']] = B[ai['def_r_wrist']]@np.linalg.inv(P[ai['def_r_wrist']])@E[ei['R_Hand']]
    posed = pose_parts(parts, F, E)
    preview = out/'preview'
    preview.mkdir(exist_ok=True)
    stats = {}
    for name, meshes, matrices in [('er_bind', parts, E), ('idle_frame000', posed, F)]:
        for view, yaw in [('front', 180), ('side', 90)]:
            path = preview/f'{name}_{view}.png'
            render(path, meshes, eb, matrices, f'{legend.title()} + R-301 / {name} / {view}', yaw, textures)
            stats[f'{name}_{view}'] = annotate(path, meshes, matrices[ei['R_Hand']], grip, yaw)
        # Detail views make grip contact visible without changing the mesh.
        detail = {part: [m for m in meshes[part] if part == 'am'] for part in PARTS}
        render(preview/f'{name}_hands_oblique.png', detail, eb, matrices,
               f'Hands + iron-sight R-301 / {name}', 140, textures)
    stats['pose_method'] = 'B=Q@Cast_world_without_origin_track@inverse(Q); ER_pose=B@O; O=inverse(P)@E from T005'
    stats['pose_scope'] = 'Actual Apex idle world positions transported to ER node axes; offline preview only, not an implemented native-ER animation retargeter'
    stats['bind_scope'] = 'ER relaxed reference hand makes barrel point diagonally outward/downward; no world-forward rotation was invented'
    assert stats['idle_frame000_side']['barrel_world'][2] < -.99
    # A rigid gun posed with the selected G must reproduce its directly evaluated Apex placement.
    gun_to_idle = Q@idleW[ai['ja_c_propGun']]
    gun_to_posed = F[ei['R_Hand']]@np.array(grip['gun_root_to_R_Hand_er'])@Q
    error = float(np.max(abs(gun_to_idle-gun_to_posed)))
    assert error < 1e-10
    stats['direct_cast_gun_transform_max_error'] = error
    save(out/'preview-verification.json', stats)
    print('PASS previews: ER bind and Cast idle frame 0, front/side; idle barrel -Z; direct Cast transform agrees', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    add_options(parser)
    args = parser.parse_args()
    out = checked_out(args.out or default_out(args.legend))
    assert read(out/'source-manifest.json')['legend'] == args.legend, 'Output legend mismatch'
    state = alignment_for(args.legend)
    from grip import derive
    _, _, idleW = derive(state, out, args.legend)
    make_previews(out, state, idleW, args.legend)
