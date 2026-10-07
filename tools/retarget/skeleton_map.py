"""M0-S2b: validate a hand-authored humanoid map against local game exports.

Only this conversion recipe is tracked. Bone tables and matrices go to er-data.
Matrices use column vectors: parent_world @ local_TRS, quaternions xyzw.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]

# ER names are keyed to the corresponding Apex joint, not to a fuzzy name match.
CORE = {
    "Master": "jx_c_delta", "RootPos": "jx_c_start", "Pelvis": "def_c_hip",
    "Spine": "def_c_spineA", "Spine1": "def_c_spineB", "Spine2": "def_c_spineC",
    "Neck": "def_c_neckA", "Head": "def_c_head",
}
for side, source in (("L", "l"), ("R", "r")):
    for target, joint in (
        ("Clavicle", "clav"), ("UpperArm", "shoulder"), ("Forearm", "elbow"),
        ("Hand", "wrist"), ("Thigh", "thigh"), ("Calf", "knee"),
        ("Foot", "ankle"), ("Toe0", "ball"),
    ):
        CORE[f"{side}_{target}"] = f"def_{source}_{joint}"
    for digit, source_digit in enumerate(("Thumb", "Index", "Mid", "Ring", "Pinky")):
        for segment, letter in enumerate("ABC"):
            target = f"{side}_Finger{digit}" + (str(segment) if segment else "")
            CORE[target] = f"def_{source}_fin{source_digit}{letter}"

# Extra deforming joints retain explicit conservative owners in the v0 mesh.
EXTRA = {"Jaw": "def_c_jawA"}
for side, source in (("L", "l"), ("R", "r")):
    EXTRA[f"{side}_UpArmTwist"] = f"def_{source}_shoulderTwist"
    EXTRA[f"{side}_ForeArmTwist"] = f"def_{source}_forearm"
    EXTRA[f"{side}_Weapon"] = f"ja_{source}_propHand"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def trs(t, q, s):
    t, q, s = np.asarray(t[:3]), np.asarray(q), np.asarray(s[:3])
    if not all(np.isfinite(v).all() for v in (t, q, s)):
        raise ValueError("non-finite reference transform")
    if abs(np.linalg.norm(q) - 1) > 0.001:
        raise ValueError("non-unit reference quaternion")
    x, y, z, w = q / np.linalg.norm(q)
    r = np.array([
        [1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
        [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
        [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)],
    ])
    m = np.eye(4)
    m[:3, :3] = r @ np.diag(s)
    m[:3, 3] = t
    return m


def world_matrices(bones, name, parent, local):
    names = [b[name] for b in bones]
    if len(set(names)) != len(names):
        raise ValueError("duplicate bone names")
    result, active = {}, set()
    def visit(i):
        if i in result:
            return result[i]
        if i in active or not 0 <= i < len(bones):
            raise ValueError("invalid/cyclic bone hierarchy")
        active.add(i)
        p = bones[i][parent]
        if p < -1 or p >= len(bones):
            raise ValueError("invalid parent index")
        result[i] = (visit(p) if p >= 0 else np.eye(4)) @ local(bones[i])
        active.remove(i)
        return result[i]
    return {b[name]: visit(i) for i, b in enumerate(bones)}


def build(apex_path, er_path, armor_path, runtime_path, out):
    apex, er, armor, runtime = map(read, (apex_path, er_path, armor_path, runtime_path))
    ab, eb, fb = apex["bones"], er["Bones"], armor["Nodes"]
    aw = world_matrices(ab, "name", "parent_index", lambda b: trs(
        b["local_position"], b["local_rotation_xyzw"], b["local_scale"]))
    ew = world_matrices(eb, "Name", "ParentIndex", lambda b: trs(
        b["Translation"], b["Rotation"], b["Scale"]))
    fw = world_matrices(fb, "Name", "ParentIndex", lambda b: trs(
        b["Translation"], b["RotationQuaternion"], b["Scale"]))
    rb = runtime["bones"]
    if len(rb) != len(eb):
        raise ValueError("runtime bone count differs")
    for r, e in zip(rb, eb):
        if (r["name"], r["parent"]) != (e["Name"], e["ParentIndex"]):
            raise ValueError("runtime/offline identity differs")
        for key, field, n in (("t", "Translation", 3), ("r", "Rotation", 4), ("s", "Scale", 3)):
            if not np.allclose(r["ref"][key], e[field][:n], atol=1e-6, rtol=0):
                raise ValueError("runtime/offline reference pose differs")
    for target, source in (CORE | EXTRA).items():
        if source not in aw or target not in ew:
            raise ValueError(f"mapping joint absent: {source} -> {target}")
    missing = set(CORE) - set(fw)
    if missing:
        raise ValueError(f"armor lacks core joints: {sorted(missing)}")
    # Root helpers can share an owner; no source deform joint gets ambiguous owners.
    source_to_target = {source: target for target, source in (CORE | EXTRA).items()}
    owners = []
    for i, bone in enumerate(ab):
        ancestor = i
        while ab[ancestor]["name"] not in source_to_target:
            ancestor = ab[ancestor]["parent_index"]
            if ancestor < 0:
                raise ValueError("unmapped bone without mapped ancestor")
        target = source_to_target[ab[ancestor]["name"]]
        owners.append({"source": bone["name"], "target": target,
                       "rule": "explicit" if ancestor == i else "nearest_mapped_ancestor"})
    mapped = []
    for target, source in (CORE | EXTRA).items():
        mapped.append({"target": target, "source": source, "core": target in CORE,
                       "apex_index": next(i for i,b in enumerate(ab) if b["name"] == source),
                       "er_index": next(i for i,b in enumerate(eb) if b["Name"] == target),
                       "armor_index": next((i for i,b in enumerate(fb) if b["Name"] == target), None),
                       "apex_rest_world": aw[source].tolist(),
                       "er_rest_world": ew[target].tolist(),
                       "armor_rest_world": fw[target].tolist() if target in fw else None})
    out.mkdir(parents=True, exist_ok=True)
    payload = {"format": "fuse-skeleton-map", "version": 0,
               "matrix_convention": "column_vectors_parent_world_at_local_TRS",
               "counts": {"apex": len(ab), "er": len(eb), "armor": len(fb),
                          "core_pairs": len(CORE), "extra_pairs": len(EXTRA),
                          "source_owners": len(owners)},
               "runtime_matches_offline": True, "mapping": mapped, "source_owners": owners,
               "inputs": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                          for p in (apex_path, er_path, armor_path, runtime_path)],
               "limitations": ["v0 auxiliary/facial/robot joints use ancestor ownership",
                               "reference rotations require rest-pose corrections",
                               "mesh unit scale and handedness must be calibrated separately"]}
    (out / "mapping-v0.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"PASS mapping: {len(CORE)}/{len(CORE)} core joints, {len(EXTRA)} extras, "
          f"{len(owners)}/{len(ab)} source owners; ER runtime/offline reference consistent")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apex", type=Path, default=ROOT / "apex-data/assets/fuse_skeleton.json")
    parser.add_argument("--er", type=Path, default=ROOT / "er-data/json/c0000_skeleton.json")
    parser.add_argument("--armor", type=Path, default=ROOT / "er-data/s3/original_flver.json")
    parser.add_argument("--runtime", type=Path, default=ROOT / "er-data/runtime/c0000_runtime.json")
    parser.add_argument("--out", type=Path, default=ROOT / "er-data/s2b")
    args = parser.parse_args()
    build(args.apex, args.er, args.armor, args.runtime, args.out)
