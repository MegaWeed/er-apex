"""T020 HD/LG conversion; T011 raw binding, tangent, winding and weight rules."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import numpy as np
from PIL import Image
from common import ROOT, read, save, unit, winding, tangent_basis, file_info, Q, MIRROR
sys.path.insert(1, str(ROOT/'tools/apexpov'))
import ability_common as ac
from mesh_pov import merged_weights, write_part
from pov_textures import texture_arrays


def mapping():
    data = ac.layout()
    carriers = [dict(carrier=c['name'], owner=c['source_bone'], parts=[c['part']]) for c in data['new_carriers']]
    owners = {c['owner']: c['owner'] for c in carriers}
    for f in data['ancestor_fallbacks']:
        owners[f['source_bone']] = f['ancestor']
    return dict(carriers=carriers, owner_of_bone=owners), data


def sources():
    return [(key, mdl, mesh) for key in ac.CONFIGS for mdl, meshes in [ac.selected(key)] for mesh in meshes]


def texture_sources():
    materials = {m['name'].split('/')[-1]: m for m in read(ac.ASSETS/'materials.json')['materials']}
    result = {}
    for name in sorted({mesh.Material().Name() for _, _, mesh in sources()}):
        material = materials[name]
        paths = {t['usage'].lstrip('_'): ac.ASSETS/next(p for p in t['files'] if p.endswith('.png')) for t in material['textures']}
        ac.require(all(k in paths for k in ('col', 'nml', 'gls', 'spc')), f'Missing local prop texture: {name}')
        result[name] = paths
    return result


def make_textures(out):
    folder = out/'textures'; folder.mkdir(parents=True, exist_ok=True)
    report, previews = {}, {}
    for name, paths in texture_sources().items():
        col, normal, metal = texture_arrays(paths)
        for suffix, pixels in [('a', col), ('n', normal), ('m', np.rint(metal*255).astype(np.uint8))]:
            Image.fromarray(pixels).save(folder/f'{name}_{suffix}.png')
        previews[name] = col
        report[name] = dict(sources={k: file_info(p) for k, p in paths.items()},
            albedo='Source col RGB unchanged; opaque alpha 255; no AO multiplication',
            normal='Source nml RG; gls R in B; A=255', metalness='Same T005/T008 specular-to-metal heuristic as T011',
            source_alpha_minmax=[int(v) for v in [np.asarray(Image.open(paths['col']).convert('RGBA'))[..., 3].min(), np.asarray(Image.open(paths['col']).convert('RGBA'))[..., 3].max()]],
            metalness_mean=float(metal.mean()), unused_channels=[k for k in paths if k not in ('col', 'nml', 'gls', 'spc')])
    neutral = int(np.rint((1.055*(1/4.55)**(1/2.4)-.055)*255))
    for suffix, color in [('a', (neutral, neutral, neutral, 255)), ('n', (128, 128, 128, 255)), ('m', (0, 0, 0, 255))]:
        Image.new('RGBA', (8, 8), color).save(folder/f'neutral_{suffix}.png')
    save(out/'ability-texture-audit.json', dict(materials=report, neutral_detail_albedo_srgb=neutral,
        limitations=['Metal template does not reproduce Apex glass transparency/refraction.',
                     'Source msk/emissive channels recorded but not used by the T011 metal template.',
                     'Normal green convention and specular-to-metal conversion require runtime lighting review.']))
    return previews


def convert(out):
    mapped, data = mapping()
    parts = {'hd': [], 'lg': []}
    report = dict(format='octane-ability-mesh-summary', version=1, model=998,
        binding='float32(diag(0.0254,0.0254,-0.0254)*Cast position); no fitting transforms',
        winding='Mirror flip and ER against-normal flip cancel: original source indices',
        tangent='T005 V tangent from original Cast/UV; mirror Z, normalize XYZ, negate W',
        sources=[file_info(p) for c in ac.CONFIGS.values() for p in (c['model'], c['rig'], c['qc'])],
        meshes=[], omitted_meshes=[], parts={}, max_four_weight_loss=0., ancestor_carrier_fallbacks=data['ancestor_fallbacks'])
    for key, config in ac.CONFIGS.items():
        mdl, kept = ac.selected(key)
        for mesh in mdl.Meshes():
            if mesh not in kept:
                report['omitted_meshes'].append(dict(rig=key, name=mesh.Name(), bodygroup='Surge',
                    vertices=mesh.VertexCount(), triangles=len(mesh.FaceBuffer())//3, material=mesh.Material().Name(), reason='S3 task uses Base only'))
    for key, mdl, mesh in sources():
        config = ac.CONFIGS[key]
        p = np.asarray(mesh.VertexPositionBuffer(), float).reshape(-1, 3)
        n = unit(np.asarray(mesh.VertexNormalBuffer(), float).reshape(-1, 3))
        uv = np.asarray(mesh.VertexUVLayerBuffer(0), float).reshape(-1, 2)
        # These local props have one UV layer. ER's required armor layout has
        # two; reuse the source layer for the neutral detail samplers.
        second_uv = mesh.VertexUVLayerBuffer(1)
        uv1 = np.asarray(second_uv, float).reshape(-1, 2) if second_uv is not None else uv.copy()
        f = np.asarray(mesh.FaceBuffer(), int).reshape(-1, 3)
        ac.require(not mesh.VertexTangentBuffer(), 'Unexpected source tangent semantics')
        _, tangent, sign, fallback = tangent_basis(p, n, uv, f)
        bi, bw, loss, raw_error = merged_weights(mdl, mesh, mapped)
        part = config['part']
        ac.require(all(part in mapped['carriers'][int(i)]['parts'] for i in bi[bw > 0]), 'Carrier not enabled in requested part')
        m = dict(name=mesh.Name(), model=key, material=mesh.Material().Name(), positions=p*np.diag(Q)[:3],
                 normals=unit(np.asarray(mesh.VertexNormalBuffer(), float).reshape(-1, 3)*np.diag(MIRROR)),
                 tangents=np.c_[unit(tangent*np.diag(MIRROR)), -sign], uv0=uv, uv1=uv1,
                 bone_indices=bi, bone_weights=bw, indices=f,
                 source_vertex_ids=np.arange(len(p)), source_triangle_ids=np.arange(len(f)))
        parts[part].append(m)
        bones = mdl.Skeleton().Bones()
        used = sorted({bones[int(b)].Name() for b, w in zip(mesh.VertexWeightBoneBuffer(), mesh.VertexWeightValueBuffer()) if w > 0})
        entry = dict(rig=key, name=mesh.Name(), bodygroup='Base' if key == 'epipen' else 'projectile', part=part,
            vertices=len(p), triangles=len(f), material=mesh.Material().Name(), source_weight_sum_max_error=raw_error,
            weighted_bones=[dict(bone=n, owner=data['bones'][next(c['owner'] for c in data['new_carriers'] if c['source_bone'] == mapped['owner_of_bone'][n])]['name'],
                                 carrier=data['maps'][key+'-carriers'][n]) for n in used],
            four_weight_loss_max=float(loss.max()), four_weight_loss_mean=float(loss.mean()), tangent_fallback_vertices=fallback,
            uv1='source second layer' if second_uv is not None else 'ER layout duplicates source UV0; no Apex second layer in local data',
            source_winding=winding(p, n, f), mirrored_before_flips=winding(m['positions'], m['normals'], f),
            mirror_corrected=winding(m['positions'], m['normals'], f[:, [0, 2, 1]]), final_winding=winding(m['positions'], m['normals'], f))
        report['meshes'].append(entry)
        report['max_four_weight_loss'] = max(report['max_four_weight_loss'], float(loss.max()))
    for part, meshes in parts.items():
        write_part(out, part, meshes, mapped)
        doc = read(out/'fusemesh'/part/'mesh.json')
        report['parts'][part] = dict(meshes=len(meshes), vertices=sum(len(m['positions']) for m in meshes),
            triangles=sum(len(m['indices']) for m in meshes), materials=len(doc['materials']), carriers=doc['bones'])
    for part in ('am', 'bd'):
        report['parts'][part] = dict(read(ac.BASE_MODEL/'pov-mesh-summary.json')['parts'][part],
                                    source='Byte-for-byte copy of er-data/s3/octane_pov/package/parts')
    save(out/'ability-mesh-summary.json', report)
    return parts, report
