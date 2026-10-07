"""M0-S4: bake Apex clips (T006 fuse.anim) onto the c0000 skeleton for er-fuse's pose spike.

Retarget (rotation only, ER bone lengths), matching the mesh conversion of T005:
  A'(t) = Q A(t) Q^-1          Apex model space -> ER model space (align.json scaled_axis_unit_matrix)
  W_b(t) = A'_s(t) O_b          for each mapped ER bone b with owner Apex bone s (O_b = P_s^-1 E_b)
Unmapped ER bones follow their parent with the reference local transform. Master, the foot IK
targets and RootPos's rotation are left to the game. RootPos carries the hip motion: its
model-space position is the pelvis position W_Pelvis(t), in place (the Apex root jx_c_delta stays
at its model rest transform). Output: fuse_er.anim v1 (format in src/spike/pose.rs).

Matrices: column vectors, parent_world @ local_TRS, quaternions xyzw (as S2b / T005 / T006).
"""
import argparse
import json
import struct
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def quat_to_mat(q):
    x, y, z, w = q / np.linalg.norm(q)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def mat_to_quat(m):
    t = np.trace(m)
    if t > 0:
        s = np.sqrt(t + 1.0) * 2
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]
    q = np.array(q)
    return q / np.linalg.norm(q)


def trs(t, q, s):
    m = np.eye(4)
    m[:3, :3] = quat_to_mat(np.asarray(q, float)) @ np.diag(s)
    m[:3, 3] = t
    return m


def rot_only(m):
    """Orthonormal rotation of a (possibly scaled) 3x3."""
    u, _, vt = np.linalg.svd(m[:3, :3])
    r = u @ vt
    if np.linalg.det(r) < 0:
        raise ValueError("reflection left in a bone matrix")
    return r


class Reader:
    def __init__(self, data):
        self.d, self.p = data, 0

    def take(self, n):
        if self.p + n > len(self.d):
            raise ValueError("truncated fuse.anim")
        s = self.d[self.p:self.p + n]
        self.p += n
        return s

    def u(self, fmt):
        return struct.unpack("<" + fmt, self.take(struct.calcsize("<" + fmt)))

    def s(self):
        (n,) = self.u("H")
        return self.take(n).decode("utf-8")

    def ch3(self):
        (n,) = self.u("I")
        return np.frombuffer(self.take(n * 12), "<f4").reshape(n, 3).astype(float)

    def ch4q(self):
        (n,) = self.u("I")
        q = np.frombuffer(self.take(n * 8), "<i2").reshape(n, 4).astype(float) / 32767.0
        return q / np.linalg.norm(q, axis=1, keepdims=True) if n else q


def read_fuse_anim(path):
    d = Path(path).read_bytes()
    if d[:8] != b"FUSEANIM":
        raise ValueError("not fuse.anim")
    version, total, nb, nc, crc = struct.unpack("<IQIII", d[8:32])
    if version != 0 or total != len(d) or zlib.crc32(d[32:]) & 0xFFFFFFFF != crc:
        raise ValueError("fuse.anim header/CRC mismatch")
    r = Reader(d)
    r.p = 32
    bones = []
    for _ in range(nb):
        name = r.s()
        (parent,) = r.u("i")
        t = np.array(r.u("3f")); q = np.array(r.u("4f")); s = np.array(r.u("3f"))
        bones.append({"name": name, "parent": parent, "t": t, "q": q / np.linalg.norm(q), "s": s})
    clips = []
    for _ in range(nc):
        (blen,) = r.u("I")
        end = r.p + blen
        c = {"name": r.s(), "sequence": r.s(), "cast": r.s(), "rig": r.s()}
        c["guid"], c["fps"], c["frames"], c["flags"] = r.u("QfII")
        c["sample_index"], c["sample_count"], ntracks = r.u("III")
        c["metadata"] = r.s()
        (c["root_bone"],) = r.u("i")
        if c["root_bone"] != -1:
            c["root_t"], c["root_q"] = r.ch3(), r.ch4q()
        c["tracks"] = []
        for _ in range(ntracks):
            bone, mode, mask = r.u("HBB")
            wt, wr, ws = r.u("3f")
            c["tracks"].append({"bone": bone, "mode": mode, "t": r.ch3(), "q": r.ch4q(), "s": r.ch3(), "w": (wt, wr, ws)})
        r.p = end
        clips.append(c)
    return bones, clips


def at(ch, f):
    return ch[0] if len(ch) == 1 else ch[f]


def apex_world(bones, clip, f):
    """Apex model-space world matrices for frame f (absolute tracks; root held at frame 0)."""
    local = [{"t": b["t"].copy(), "q": b["q"].copy(), "s": b["s"].copy()} for b in bones]
    # The root (jx_c_delta) keeps its model rest transform: the clips' root track starts with the
    # exporter's axis adjustment (a 90 degree turn about X in fuse_idle_rifle frame 0, Z up),
    # while the mesh (T005) was converted from the Y-up model rest pose. Root motion is not used
    # here (in place).
    for tr in clip["tracks"]:
        if tr["mode"] != 0:
            raise ValueError(f"{clip['name']}: additive clips are not baked")
        l = local[tr["bone"]]
        if len(tr["t"]):
            l["t"] = at(tr["t"], f)
        if len(tr["q"]):
            l["q"] = at(tr["q"], f)
        if len(tr["s"]):
            l["s"] = at(tr["s"], f)
    world = []
    for i, b in enumerate(bones):
        m = trs(local[i]["t"], local[i]["q"], local[i]["s"])
        world.append(m if b["parent"] < 0 else world[b["parent"]] @ m)
    return world


# Master (facing) and RootPos (undoes Master's facing at run time) keep the game's rotations;
# RootPos only takes the hips' model-space position. The foot/hand IK targets stay the game's.
DRIVE_SKIP = {"Master", "RootPos"}


def bake(pack, align, er_skel, names, out):
    bones, clips = read_fuse_anim(pack)
    a = json.loads(Path(align).read_text(encoding="utf-8"))
    er = json.loads(Path(er_skel).read_text(encoding="utf-8"))["Bones"]
    Q = np.array(a["scaled_axis_unit_matrix"])
    Qi = np.linalg.inv(Q)
    apex_index = {b["name"]: i for i, b in enumerate(bones)}
    # sanity: our conversion of the rest pose matches T005's apex_rest_er_space
    rest = apex_world(bones, {"root_bone": -1, "tracks": [], "name": "rest"}, 0)
    worst = max(np.abs(Q @ rest[i] @ Qi - np.array(m)).max() for i, m in enumerate(a["apex_rest_er_space"]))
    if worst > 1e-3:
        raise ValueError(f"rest pose conversion differs from align.json by {worst}")
    mapped = {m["er_bone"]: (apex_index[m["owner_apex_bone"]], np.array(m["O_b"])) for m in a["mapped_bones"]}
    er_names = [b["Name"] for b in er]
    er_local = [trs(b["Translation"][:3], b["Rotation"], b["Scale"][:3]) for b in er]
    er_parent = [b["ParentIndex"] for b in er]
    er_ref_world = []
    for i in range(len(er)):
        p = er_parent[i]
        er_ref_world.append(er_local[i] if p < 0 else er_ref_world[p] @ er_local[i])
    driven = [not (n in DRIVE_SKIP or n.endswith("_Target") or "_Target" in n) for n in er_names]
    root_pos = er_names.index("RootPos")

    blobs = []
    for name in names:
        ci = next((k for k, c in enumerate(clips) if c["name"] == name), None)
        if ci is None:
            raise ValueError(f"no clip {name} in {pack}")
        c = clips[ci]
        frames = []
        for f in range(c["frames"]):
            aw = apex_world(bones, c, f)
            world = [None] * len(er)
            rots = []
            for i in range(len(er)):
                p = er_parent[i]
                pw = np.eye(4) if p < 0 else world[p]
                if i == root_pos:
                    # the game's RootPos rotation (model space: the reference one), our hips
                    pel_s, pel_o = mapped["Pelvis"]
                    world[i] = er_ref_world[i].copy()
                    world[i][:3, 3] = (Q @ aw[pel_s] @ Qi @ pel_o)[:3, 3]
                    continue
                if not driven[i]:
                    world[i] = er_ref_world[i]
                    continue
                ref = pw @ er_local[i]
                if er_names[i] in mapped:
                    s, o = mapped[er_names[i]]
                    w = Q @ aw[s] @ Qi @ o
                    m = np.eye(4)
                    m[:3, :3] = rot_only(w)
                    m[:3, 3] = ref[:3, 3]  # ER bone lengths
                    world[i] = m
                else:
                    world[i] = ref
                lr = rot_only(np.linalg.inv(pw) @ world[i])
                rots.append(mat_to_quat(lr))
            frames.append((rots, world[root_pos][:3, 3]))
        looping = bool(c["flags"] & 1)
        blob = bytearray()
        n = name.encode("utf-8")
        blob += struct.pack("<H", len(n)) + n
        blob += struct.pack("<fIB", c["fps"], c["frames"], 1 if looping else 0)
        blob += bytes(1 if d else 0 for d in driven)
        for rots, t in frames:
            for q in rots:
                blob += struct.pack("<4f", *q)
            blob += struct.pack("<3f", *t)
        blobs.append(bytes(blob))
        print(f"baked {name}: {c['frames']} frames @ {c['fps']} fps, loop {looping}, {sum(driven)} driven bones")
    head = bytearray(b"FERA") + struct.pack("<II", 1, len(er))
    for nm in er_names:
        e = nm.encode("utf-8")
        head += struct.pack("<H", len(e)) + e
    head += struct.pack("<I", len(blobs))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(bytes(head) + b"".join(blobs))
    print(f"wrote {out} ({Path(out).stat().st_size} bytes)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pack", default=ROOT / "apex-data/anim/fuse.anim")
    ap.add_argument("--align", default=ROOT / "er-data/s3/fuse/align.json")
    ap.add_argument("--er", default=ROOT / "er-data/json/c0000_skeleton.json")
    ap.add_argument("--out", default=ROOT / "er-data/s4/fuse_er.anim")
    ap.add_argument("clips", nargs="*", default=["fuse_idle_rifle", "fuse_run_rifle_F#1"])
    args = ap.parse_args()
    bake(args.pack, args.align, args.er, args.clips, args.out)
