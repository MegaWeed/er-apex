"""T011 paths and read-only imports. All generated data lives in OUT."""
import sys
from pathlib import Path
import numpy as np

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'er-data/s3/fuse_pov'
OCTANE_OUT = ROOT / 'er-data/s3/octane_pov'
for directory in ('fusemesh', 'fuseanim', 'erdata/scripts'):
    sys.path.append(str(ROOT / 'tools' / directory))
from geometry import read, save, unit, trs, world, winding, tangent_basis, PARTS, MODELS
from convert_fuse import run, TOOL, EXTRACT
from cast import Cast, Model

ARMS = ROOT / 'apex-data/assets/cast/mdl/Weapons/arms/pov_pilot_medium_fuse_LOD0.cast'
OCTANE_ARMS = ROOT / 'apex-data/assets/octane/cast/mdl/Weapons/arms/pov_pilot_medium_stim_LOD0.cast'
GUN = ROOT / 'apex-data/pov/cast/mdl/techart/mshop/weapons/class/assault/r301/r301_base_v_LOD0.cast'
GUN_QC = ROOT / 'apex-data/pov/smd/mdl/techart/mshop/weapons/class/assault/r301/r301_base_v.qc'
RIG = ROOT / 'apex-data/pov/cast/animrig/weapons/rspn101/ptpov_rspn101.cast'
RIG_QC = ROOT / 'apex-data/pov/smd/animrig/weapons/rspn101/ptpov_rspn101.qc'
IDLE = RIG.parent / 'anims_ptpov_rspn101/idle_0.cast'
REFERENCE = IDLE.parent / 'ads_in_0.cast'
CARRIERS = ROOT / 'tools/apexpov/carriers.json'
MATBIN = ROOT / 'scratch/mod/package/material/allmaterial.matbinbnd.dcx'
Q = np.diag([.0254, .0254, -.0254, 1.])
Q_INVERSE = np.linalg.inv(Q)
MIRROR = np.diag([1., 1., -1.])
SELECTED = ('body_0_r301_base_main', 'sight_front_1_r301_base_main',
            'r101_magazine_0_r301_base_main')


def legend_config(legend='fuse'):
    if legend not in ('fuse', 'octane'):
        raise ValueError(f'Unknown legend: {legend}')
    octane = legend == 'octane'
    return dict(legend=legend, arms=OCTANE_ARMS if octane else ARMS,
                arms_mesh='body_0_octane_base_v_arms' if octane else 'body_0_fuse_base_v_arms',
                arms_material='octane_base_v_arms' if octane else 'fuse_base_v_arms',
                texture_dir='pov_pilot_medium_stim' if octane else 'pov_pilot_medium_fuse',
                out=OCTANE_OUT if octane else OUT,
                pack=ROOT / ('apex-data/pov/octane/fuse_pov.anim' if octane else 'apex-data/pov/fuse_pov.anim'))


def checked_out(path, legend='fuse'):
    path = Path(path).resolve()
    roots = [OCTANE_OUT] if legend == 'octane' else [OUT, OCTANE_OUT]
    if not any(path.is_relative_to(root.resolve()) for root in roots):
        raise ValueError(f'Output for {legend} must stay inside ' + ', '.join(map(str, roots)))
    path.mkdir(parents=True, exist_ok=True)
    return path


def model(path):
    return Cast.load(str(path)).Roots()[0].ChildrenOfType(Model)[0]


def bone_data(bones):
    return [dict(name=b.Name(), parent_index=b.ParentIndex(),
                 local_position=list(b.LocalPosition()),
                 local_rotation_xyzw=list(b.LocalRotation()),
                 local_scale=list(b.Scale() or [1, 1, 1])) for b in bones]


def bind_world(bones):
    return world(bones, lambda b: trs(b.LocalPosition(), b.LocalRotation(), b.Scale() or [1, 1, 1]),
                 lambda b: b.ParentIndex())


def file_info(path):
    path = Path(path)
    return dict(path=path.resolve().relative_to(ROOT).as_posix(), size=path.stat().st_size)


def check_file_info(info):
    path = ROOT / info['path']
    assert path.is_file() and path.stat().st_size == info['size'], ('source path/size differs', info)
    if path.suffix.lower() == '.cast':
        with path.open('rb') as stream:
            assert stream.read(4) == b'cast', ('invalid Cast signature', path)
    elif path.suffix.lower() == '.png':
        with path.open('rb') as stream:
            assert stream.read(8) == b'\x89PNG\r\n\x1a\n', ('invalid PNG signature', path)
    return path
