//! Spike S2c: dumps the player's live skeleton (hkaSkeleton: bone names, parents, reference pose)
//! and the current local and model pose from the character's pose importer, to check the offline
//! extraction (S2a) against what the game really uses.
//!
//! Layout (exe 2.7.1.0, from er-mario's engine_mario.rs; the reference pose offset is what this
//! spike verifies):
//!   ChrIns+0x398 CSFD4LocationHkaPoseImporter: +0x48 hkaSkeleton*, +0x50/+0x58 local pose
//!     (hkQsTransform[], 0x30 each) and count, +0x60/+0x68 model pose and count
//!   hkaSkeleton (Havok 2018, hkReferencedObject is 0x18 bytes): +0x18 name (hkStringPtr),
//!     +0x20 parent indices (hkArray<i16>), +0x30 bones (hkArray<hkaBone>, 0x10 each: name,
//!     lockTranslation), +0x40 reference pose (hkArray<hkQsTransform>)

use std::fmt::Write;

use eldenring::cs::WorldChrMan;
use fromsoftware_shared::FromStatic;

use crate::explore::{class_of, read_u64, readable};
use crate::{log, paths};

fn read_u32(addr: usize) -> Option<u32> {
    readable(addr & !7, 16).then(|| unsafe { *(addr as *const u32) })
}

/// A C string (hkStringPtr: the lowest bit is a flag).
fn c_str(p: usize) -> Option<String> {
    let p = p & !1;
    if p == 0 || !readable(p & !7, 16) {
        return None;
    }
    let mut s = Vec::new();
    for k in 0..128 {
        let b = unsafe { *((p + k) as *const u8) };
        if b == 0 {
            break;
        }
        s.push(b);
    }
    String::from_utf8(s).ok()
}

/// hkQsTransform at `base + i * 0x30`: translation, rotation (xyzw), scale.
fn qs(base: usize, i: usize) -> [f32; 12] {
    unsafe { *((base + i * 0x30) as *const [f32; 12]) }
}

fn qs_json(v: &[f32; 12]) -> String {
    format!(
        "{{\"t\":[{},{},{}],\"r\":[{},{},{},{}],\"s\":[{},{},{}]}}",
        v[0], v[1], v[2], v[4], v[5], v[6], v[7], v[8], v[9], v[10]
    )
}

/// Writes dev/<file> and returns a one-line summary.
pub fn dump(file: &str) -> String {
    match dump_inner(file) {
        Ok(s) => s,
        Err(e) => {
            log(format!("skeleton dump failed: {e}"));
            format!("failed: {e}")
        }
    }
}

fn dump_inner(file: &str) -> Result<String, String> {
    let wcm = unsafe { WorldChrMan::instance() }.map_err(|e| format!("no WorldChrMan: {e:?}"))?;
    let player = wcm.main_player.as_ref().ok_or("no player in the world")?;
    let chr = &player.chr_ins as *const _ as usize;
    let ptr = |a: usize| read_u64(a).map(|v| v as usize).ok_or(format!("unreadable {a:#x}"));
    let imp = ptr(chr + 0x398)?;
    let skel = ptr(imp + 0x48)?;
    let (local, local_n) = (ptr(imp + 0x50)?, read_u32(imp + 0x58).unwrap_or(0) as usize);
    let (model, model_n) = (ptr(imp + 0x60)?, read_u32(imp + 0x68).unwrap_or(0) as usize);
    let (parents, parent_n) = (ptr(skel + 0x20)?, read_u32(skel + 0x28).unwrap_or(0) as usize);
    let (bones, bone_n) = (ptr(skel + 0x30)?, read_u32(skel + 0x38).unwrap_or(0) as usize);
    let (refp, ref_n) = (ptr(skel + 0x40)?, read_u32(skel + 0x48).unwrap_or(0) as usize);
    let name = c_str(ptr(skel + 0x18)?).unwrap_or_default();
    let header: Vec<String> = (0..0x90).step_by(8).map(|o| format!("+{o:#04x}={:#x}", read_u64(skel + o).unwrap_or(0))).collect();
    log(format!(
        "skeleton: importer {imp:#x} ({}), skeleton {skel:#x} ({}) {name:?}: {bone_n} bones, {parent_n} parents, {ref_n} reference transforms, local pose {local_n}, model pose {model_n}",
        class_of(imp).unwrap_or_default(),
        class_of(skel).unwrap_or_default()
    ));
    log(format!("skeleton header: {}", header.join(" ")));
    let n = bone_n.min(1024);
    if n == 0 || parent_n != n || !readable(bones, n * 16) || !readable(parents, n * 2) {
        return Err(format!("unexpected layout: {bone_n} bones, {parent_n} parents"));
    }
    let ref_ok = ref_n == n && readable(refp, n * 0x30);
    let local_ok = local_n == n && readable(local, n * 0x30);
    let model_ok = model_n == n && readable(model, n * 0x30);
    // the reference pose is a pose: unit quaternions, scales near 1
    let mut bad_quats = 0;
    let mut json = String::new();
    let _ = write!(
        json,
        "{{\"skeleton\":{name:?},\"bone_count\":{n},\"reference_pose_offset\":\"0x40\",\"reference_pose_valid\":{ref_ok},\"bones\":["
    );
    for i in 0..n {
        let bname = c_str(unsafe { *((bones + i * 16) as *const usize) }).unwrap_or_default();
        let parent = unsafe { *((parents + i * 2) as *const i16) };
        let _ = write!(json, "{}{{\"i\":{i},\"name\":{bname:?},\"parent\":{parent}", if i > 0 { "," } else { "" });
        if ref_ok {
            let r = qs(refp, i);
            let len = (r[4] * r[4] + r[5] * r[5] + r[6] * r[6] + r[7] * r[7]).sqrt();
            if (len - 1.0).abs() > 1e-3 {
                bad_quats += 1;
            }
            let _ = write!(json, ",\"ref\":{}", qs_json(&r));
        }
        if local_ok {
            let _ = write!(json, ",\"local\":{}", qs_json(&qs(local, i)));
        }
        if model_ok {
            let _ = write!(json, ",\"model\":{}", qs_json(&qs(model, i)));
        }
        json.push('}');
    }
    json.push_str("]}");
    let path = paths::file(&format!("dev/{file}"));
    let _ = std::fs::create_dir_all(paths::file("dev"));
    std::fs::write(&path, json).map_err(|e| format!("{}: {e}", path.display()))?;
    Ok(format!(
        "{n} bones of {name:?} to {}; reference pose {} ({bad_quats} non-unit rotations)",
        path.display(),
        if ref_ok { "read" } else { "NOT found at +0x40" }
    ))
}
