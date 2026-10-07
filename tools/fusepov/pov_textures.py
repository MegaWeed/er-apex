"""T005 channel packing, using the actual first-person PNGs; no AO multiplication."""
import numpy as np
from PIL import Image
from common import ROOT, GUN, save, file_info, legend_config
from textures import linear


def texture_arrays(paths):
    col = np.asarray(Image.open(paths['col']).convert('RGBA')).copy()
    nml = np.asarray(Image.open(paths['nml']).convert('RGBA'))
    gloss = np.asarray(Image.open(paths['gls']).convert('RGBA').resize(
        (nml.shape[1], nml.shape[0]), Image.Resampling.BILINEAR))[..., 0]
    spec = np.asarray(Image.open(paths['spc']).convert('RGBA').resize(
        (col.shape[1], col.shape[0]), Image.Resampling.BILINEAR))
    normal = np.empty_like(nml)
    normal[..., :2] = nml[..., :2]
    normal[..., 2] = gloss
    normal[..., 3] = 255
    metal = np.clip((linear(spec[..., :3]).max(2)-.04)/
                    np.maximum(linear(col[..., :3]).max(2)-.04, .04), 0, 1)
    col[..., 3] = 255
    return col, normal, metal


def make_textures(out, legend='fuse'):
    config = legend_config(legend)
    dest = out/'textures'
    dest.mkdir(parents=True, exist_ok=True)
    audit = {}
    previews = {}
    for name, base in [(config['arms_material'], config['arms'].parent/config['texture_dir']),
                       ('r301_base_main', GUN.parent/'r301_base_v')]:
        paths = {s: base/f'{name}_{s}.png' for s in ('col', 'nml', 'gls', 'spc')}
        col, normal, metal = texture_arrays(paths)
        for suffix, data in [('a', col), ('n', normal), ('m', np.rint(metal*255).astype(np.uint8))]:
            Image.fromarray(data).save(dest/f'{name}_{suffix}.png')
        previews[name] = col
        audit[name] = dict(source_textures={s: str(p.relative_to(ROOT)) for s, p in paths.items()},
              sources={s: file_info(p) for s, p in paths.items()},
              albedo='_col RGB unchanged, A=255; no AO', normal='_nml RG unchanged; B=_gls R; A=255',
              metalness='T005/T008 heuristic clamp((max(linear(spc))-0.04)/max(max(linear(col))-0.04,0.04),0,1); arms and weapon may contain metal',
              metalness_mean=float(metal.mean()), metalness_nonzero_fraction=float((metal > 0).mean()))
    neutral = int(np.rint((1.055*(1/4.55)**(1/2.4)-.055)*255))
    for suffix, color in [('a', (neutral, neutral, neutral, 255)), ('n', (128, 128, 128, 255)), ('m', (0, 0, 0, 255))]:
        Image.new('RGBA', (8, 8), color).save(dest/f'neutral_{suffix}.png')
    save(out/'texture-audit.json', dict(materials=audit, neutral_detail_albedo_srgb=neutral,
         rules_source='tools/fusemesh/textures.py and tools/fusegun/build_gun.py',
         limitations=['specular to metalness approximation', 'Apex normal green and AM Rich shader pending runtime lighting review']))
    return previews
