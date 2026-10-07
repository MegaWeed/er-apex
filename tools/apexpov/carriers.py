"""M0-FP: which c0000 bone carries which Apex first-person bone (D-017).

Run from the repository root: python tools/apexpov/carriers.py  ->  tools/apexpov/carriers.json

In first person Fuse's body is hidden, so c0000 bones can carry the view model: every frame the
mod writes each carrier's model-space transform from Apex's ptpov animation (no retargeting).
A carrier can only skin vertices in an armour piece whose template enables it (`Bone` and not
`Disabled`): AM_M_1500 enables the upper arms, forearms, hands and fingers (20 a side), BD_M_1280
the clavicles, shoulders, arm twists, elbows, spine, collar and pectorals. So:

- every Apex bone the meshes weight is owned by an animated bone of `ptpov_rspn101` (its nearest
  animated ancestor, e.g. Fuse's right-arm pistons go to `def_r_elbow`);
- some animated bones are merged into a neighbour to fit (helpers into their finger, cuffs into
  the forearm, the outer wrist and ring carpal into the wrist, the backpack jiggle into spineC):
  their vertices follow the neighbour rigidly from the bind pose;
- the R-301's three skinned bones use the BD-only collar and pectorals.

Inputs (not in git): apex-data/pov/smd QC files from tools/apexpov/export_pov.py,
er-data/json/parts/{AM_M_1500,BD_M_1280}.json (T002).
"""
import json
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[2]
SMD = REPO / 'apex-data/pov/smd'
RIG_QC = SMD / 'animrig/weapons/rspn101/ptpov_rspn101.qc'
ARMS_QC = SMD / 'mdl/Weapons/arms/pov_pilot_medium_fuse.qc'
GUN_QC = SMD / 'mdl/techart/mshop/weapons/class/assault/r301/r301_base_v.qc'
PARTS = {'am': 'AM_M_1500', 'bd': 'BD_M_1280'}

# Apex animated bone (per side, without the def_l_/def_r_ prefix) -> c0000 bone (without L_/R_)
SIDE = {
    'clav': 'Clavicle', 'shoulder': 'Shoulder', 'shoulderTwist': 'UpArmTwist',
    'shoulderMid': 'UpArmTwist1', 'elbowB': 'Elbow', 'elbow': 'UpperArm',
    'forearm': 'ForeArmTwist', 'wrist': 'Hand',
    'finThumbA': 'Finger0', 'finThumbB': 'Finger01', 'finThumbC': 'Finger02',
    'finIndexA': 'Finger1', 'finIndexB': 'Finger11', 'finIndexC': 'Finger12',
    'finMidA': 'Finger2', 'finMidB': 'Finger21', 'finMidC': 'Finger22',
    'finRingA': 'Finger3', 'finRingB': 'Finger31', 'finRingC': 'Finger32',
    'finPinkyA': 'Finger4', 'finPinkyB': 'Finger41', 'finPinkyC': 'Finger42',
}
# animated bones without a carrier of their own -> the animated bone they follow
SIDE_MERGE = {
    'finThumbmiddle_helper': 'finThumbA', 'finThumbB_helper': 'finThumbB',
    'finThumbC_helper': 'finThumbC', 'finIndexA_helper': 'finIndexA', 'finMidA_helper': 'finMidA',
    'finRingA_helper': 'finRingA', 'cuff_1': 'forearm', 'cuff_2': 'forearm', 'cuff_3': 'forearm',
    'cuff_4': 'forearm', 'outterwrist': 'wrist', 'finRingCarpal': 'wrist',
    'forearm_shield': 'elbow',
}
CENTER = {'def_c_spineC': 'Spine2', 'def_c_neckB': 'Neck',
          'def_c_base': 'L_Pectoral', 'def_c_bolt': 'R_Pectoral', 'def_c_magazine': 'Collar'}
CENTER_MERGE = {'def_c_backPack_jiggle': 'def_c_spineC'}


def bones(qc):
    text = qc.read_text(encoding='utf8')
    return {m[1]: m[2] for m in re.finditer(r'\$definebone "([^"]+)" "([^"]*)"', text)}


def enabled(part):
    nodes = json.loads((REPO / f'er-data/json/parts/{part}.json').read_text(encoding='utf8'))['Nodes']
    return {n['Name'] for n in nodes if 'Bone' in n['Flags'] and 'Disabled' not in n['Flags']}


def main():
    rig = bones(RIG_QC)
    model_parents = {**bones(ARMS_QC), **bones(GUN_QC)}
    carrier_of = dict(CENTER)
    merge = dict(CENTER_MERGE)
    for side, er in (('l', 'L'), ('r', 'R')):
        for apex, c in SIDE.items():
            carrier_of[f'def_{side}_{apex}'] = f'{er}_{c}'
        for apex, into in SIDE_MERGE.items():
            merge[f'def_{side}_{apex}'] = f'def_{side}_{into}'
    for owner in carrier_of:
        if owner not in rig:
            raise ValueError(f'{owner} is not animated by ptpov_rspn101')

    def owner(bone):
        """The animated bone with a carrier that `bone`'s vertices follow (None: no mesh used in
        first person may weight it, e.g. the legs, the hip, optics)."""
        while bone not in carrier_of:
            if bone in merge:
                bone = merge[bone]
            elif bone in model_parents and model_parents[bone]:
                bone = model_parents[bone]
            else:
                return None
        return bone

    on = {k: enabled(v) for k, v in PARTS.items()}
    carriers = []
    for o, c in carrier_of.items():
        parts = [k for k in PARTS if c in on[k]]
        if not parts:
            raise ValueError(f'{c} is enabled in no part')
        carriers.append({'carrier': c, 'owner': o, 'parts': parts})
    if len({c['carrier'] for c in carriers}) != len(carriers):
        raise ValueError('a c0000 bone carries two Apex bones')
    # every bone of either model that some mesh might weight
    owners = {b: owner(b) for b in sorted(model_parents) if b.startswith('def_')}
    out = {
        'format': 'fuse-pov-carriers', 'version': 1,
        'rig': 'animrig/weapons/rspn101/ptpov_rspn101.rrig',
        'models': ['mdl/Weapons/arms/pov_pilot_medium_fuse.rmdl',
                   'mdl/techart/mshop/weapons/class/assault/r301/r301_base_v.rmdl'],
        'templates': PARTS,
        'carriers': carriers,
        'owner_of_bone': owners,
    }
    path = Path(__file__).with_name('carriers.json')
    path.write_text(json.dumps(out, indent=1) + '\n', encoding='utf8')
    print(f'{len(carriers)} carriers, {len(owners)} model bones -> {path}')


if __name__ == '__main__':
    main()
