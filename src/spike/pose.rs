//! Spike S4: pose override. Plays an Apex animation already retargeted to c0000 (baked offline by
//! tools/retarget, file `fuse_er.anim` in the mod folder) on the player's skeleton: the baked
//! local rotations (and the pelvis translation) replace the game's animation for every bone the
//! clip drives (the hips' translation goes to RootPos); the rest keep the game's own animation. Writing follows er-mario's
//! engine_mario.rs (MIT, Copyright (c) 2026 Delta): local and model pose together, re-applied in
//! every task group up to drawing and right after the game's animation job (hook RVAs from er-mario,
//! exe 2.7.1.0).
//!
//! `fuse_er.anim` v1 (little endian): "FERA", u32 version 1, u32 bone count, bone names (u16 length
//! + UTF-8); u32 clip count; per clip: name (u16 + UTF-8), f32 fps, u32 frames, u8 loop, u8 per
//! bone (1 = driven), then per frame: for each driven bone its local rotation (f32 x y z w), then
//! the RootPos position in model space (f32 x y z, metres: the hips, which carry both legs and
//! spine in c0000), whenever the bone table has RootPos. RootPos keeps the game's rotation (at run
//! time it undoes Master's facing, so the model space stays put); only its position is ours.

use std::collections::HashMap;
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::time::Instant;

use eldenring::cs::WorldChrMan;
use fromsoftware_shared::FromStatic;
use glam::{Quat, Vec3};

use crate::{explore, log, paths};

pub struct Clip {
    pub name: String,
    fps: f32,
    frames: usize,
    looping: bool,
    /// indices into the file's bone table
    driven: Vec<usize>,
    /// frames x driven
    rots: Vec<Quat>,
    pelvis: Option<Vec<Vec3>>,
}

pub struct Pack {
    bones: Vec<String>,
    pub clips: Vec<Clip>,
}

fn parse(d: &[u8]) -> Result<Pack, String> {
    let mut p = 0usize;
    let mut take = |n: usize| -> Result<&[u8], String> {
        let s = d.get(p..p + n).ok_or("truncated")?;
        p += n;
        Ok(s)
    };
    macro_rules! u32le { () => { u32::from_le_bytes(take(4)?.try_into().unwrap()) } }
    macro_rules! f32le { () => { f32::from_le_bytes(take(4)?.try_into().unwrap()) } }
    macro_rules! name { () => {{ let n = u16::from_le_bytes(take(2)?.try_into().unwrap()) as usize; String::from_utf8(take(n)?.to_vec()).map_err(|e| e.to_string())? }} }
    if take(4)? != b"FERA" {
        return Err("not a fuse_er.anim".into());
    }
    if u32le!() != 1 {
        return Err("unsupported version".into());
    }
    let nb = u32le!() as usize;
    if nb == 0 || nb > 1024 {
        return Err("bad bone count".into());
    }
    let bones: Vec<String> = (0..nb).map(|_| Ok(name!())).collect::<Result<_, String>>()?;
    let pelvis_index = bones.iter().position(|b| b == "RootPos");
    let nc = u32le!() as usize;
    let mut clips = Vec::new();
    for _ in 0..nc.min(256) {
        let name = name!();
        let fps = f32le!();
        let frames = u32le!() as usize;
        let looping = take(1)?[0] != 0;
        let mask = take(nb)?.to_vec();
        if !(fps > 0.0 && fps < 1000.0) || frames == 0 || frames > 100_000 {
            return Err(format!("clip {name}: bad fps/frames"));
        }
        let driven: Vec<usize> = mask.iter().enumerate().filter(|(_, m)| **m != 0).map(|(i, _)| i).collect();
        let with_pelvis = pelvis_index.is_some();
        let mut rots = Vec::with_capacity(frames * driven.len());
        let mut pelvis = with_pelvis.then(Vec::new);
        for _ in 0..frames {
            for _ in 0..driven.len() {
                let q = Quat::from_xyzw(f32le!(), f32le!(), f32le!(), f32le!());
                if !q.is_finite() || (q.length() - 1.0).abs() > 0.01 {
                    return Err(format!("clip {name}: bad rotation"));
                }
                rots.push(q.normalize());
            }
            if let Some(v) = pelvis.as_mut() {
                let t = Vec3::new(f32le!(), f32le!(), f32le!());
                if !t.is_finite() {
                    return Err(format!("clip {name}: bad pelvis"));
                }
                v.push(t);
            }
        }
        clips.push(Clip { name, fps, frames, looping, driven, rots, pelvis });
    }
    Ok(Pack { bones, clips })
}

struct Player {
    pack: Pack,
    clip: usize,
    start: Instant,
    /// file bone index -> skeleton bone index, for the skeleton it was built for
    map: Option<(usize, Vec<Option<usize>>)>,
    /// first person (firstperson.rs): the hands' common ancestor, moved as one piece, and R_Hand
    rig: Option<(usize, usize)>,
    /// first person with Apex's view model (spike/pov.rs): the carrier bones
    /// each carrier's bone on the live skeleton (None: not there; that carrier stays as the game
    /// poses it)
    pov: Option<Vec<Option<usize>>>,
}

static PLAYER: Mutex<Option<Player>> = Mutex::new(None);
static ON: AtomicBool = AtomicBool::new(false);

/// Plays clip `name` (loading the pack if needed); the same clip keeps running.
pub fn play(name: &str) -> Result<(), String> {
    if PLAYER.lock().unwrap_or_else(|e| e.into_inner()).is_none() {
        load()?;
    }
    let mut g = PLAYER.lock().unwrap_or_else(|e| e.into_inner());
    let p = g.as_mut().ok_or("no pack")?;
    let i = p.pack.clips.iter().position(|c| c.name == name).ok_or_else(|| format!("no clip {name}"))?;
    if p.clip != i || !ON.load(Ordering::Relaxed) {
        p.clip = i;
        p.start = Instant::now();
    }
    drop(g);
    ON.store(true, Ordering::Relaxed);
    install_anim_hook();
    Ok(())
}

/// Stops the override: the game animates the skeleton again.
pub fn stop() {
    ON.store(false, Ordering::Relaxed);
}

/// Dev channel `pose <clip>|off|list`.
pub fn command(arg: Option<&str>) -> String {
    match arg {
        None | Some("list") => {
            // (load() takes the lock itself: holding it here deadlocked the game's frame task)
            if PLAYER.lock().unwrap_or_else(|e| e.into_inner()).is_none() {
                if let Err(e) = load() {
                    return e;
                }
            }
            let g = PLAYER.lock().unwrap_or_else(|e| e.into_inner());
            g.as_ref().map_or("no pack".into(), |p| {
                p.pack.clips.iter().map(|c| format!("{} ({} f @ {} fps)", c.name, c.frames, c.fps)).collect::<Vec<_>>().join(", ")
            })
        }
        Some("off") => {
            ON.store(false, Ordering::Relaxed);
            "pose override off".into()
        }
        Some(name) => {
            if PLAYER.lock().unwrap_or_else(|e| e.into_inner()).is_none() {
                if let Err(e) = load() {
                    return e;
                }
            }
            let mut g = PLAYER.lock().unwrap_or_else(|e| e.into_inner());
            let Some(p) = g.as_mut() else { return "no pack".into() };
            let Some(i) = p.pack.clips.iter().position(|c| c.name == name) else { return format!("no clip {name}") };
            p.clip = i;
            p.start = Instant::now();
            ON.store(true, Ordering::Relaxed);
            install_anim_hook();
            format!("playing {name}")
        }
    }
}

fn load() -> Result<usize, String> {
    let path = paths::mod_dir().join("fuse_er.anim");
    let d = std::fs::read(&path).map_err(|e| format!("{}: {e}", path.display()))?;
    let pack = parse(&d)?;
    let n = pack.clips.len();
    log(format!("pose: loaded {} ({} bones, {n} clips)", path.display(), pack.bones.len()));
    *PLAYER.lock().unwrap_or_else(|e| e.into_inner()) = Some(Player { pack, clip: 0, start: Instant::now(), map: None, rig: None, pov: None });
    Ok(n)
}

#[derive(Clone, Copy, PartialEq)]
struct Layout {
    imp: usize,
    skeleton: usize,
    model: usize,
    local: usize,
    parents: usize,
    count: usize,
}

static LAYOUT: Mutex<Option<(usize, Layout)>> = Mutex::new(None);

fn raw(a: usize) -> usize {
    unsafe { *(a as *const usize) }
}

/// The player's pose buffers (er-mario's pose_layout), validated when a pointer changes.
fn layout(chr: usize) -> Option<Layout> {
    let mut cached = LAYOUT.lock().unwrap_or_else(|e| e.into_inner());
    if let Some((c, l)) = *cached {
        if c == chr && raw(chr + 0x398) == l.imp && raw(l.imp + 0x60) == l.model && raw(l.imp + 0x50) == l.local {
            return Some(l);
        }
    }
    let imp = explore::read_u64(chr + 0x398)? as usize;
    let skeleton = explore::read_u64(imp + 0x48)? as usize;
    let model = explore::read_u64(imp + 0x60)? as usize;
    let count = explore::read_u64(imp + 0x68)? as u32 as usize;
    let local = explore::read_u64(imp + 0x50)? as usize;
    let local_count = explore::read_u64(imp + 0x58)? as u32 as usize;
    let parents = explore::read_u64(skeleton + 0x20)? as usize;
    let parent_count = explore::read_u64(skeleton + 0x28)? as u32 as usize;
    if count == 0 || count > 512 || local_count != count || parent_count != count {
        return None;
    }
    if !explore::readable(model, count * 0x30) || !explore::readable(local, count * 0x30) || !explore::readable(parents & !7, count * 2 + 8) {
        return None;
    }
    let l = Layout { imp, skeleton, model, local, parents, count };
    *cached = Some((chr, l));
    Some(l)
}

/// Bone names of the live hkaSkeleton (+0x30 hkArray<hkaBone>, 0x10 each, name first).
fn bone_names(skeleton: usize, count: usize) -> Option<Vec<String>> {
    let arr = explore::read_u64(skeleton + 0x30)? as usize;
    if !explore::readable(arr, count * 0x10) {
        return None;
    }
    (0..count)
        .map(|i| {
            let p = raw(arr + i * 0x10) & !1;
            if p == 0 || !explore::readable(p & !7, 16) {
                return None;
            }
            let mut s = Vec::new();
            for k in 0..64 {
                let b = unsafe { *((p + k) as *const u8) };
                if b == 0 {
                    break;
                }
                s.push(b);
            }
            String::from_utf8(s).ok()
        })
        .collect()
}

/// The task group applying the pose (u32::MAX: the animation-job hook), for `fpgroup`.
static GROUP: AtomicU32 = AtomicU32::new(u32::MAX);
/// Dev `fpgroup <id>`: in that task group only, the view model is drawn 5 cm higher, to see which
/// group's write the renderer uses (u32::MAX: off). Groups seen are logged once.
static PROBE_GROUP: AtomicU32 = AtomicU32::new(u32::MAX);

pub fn probe(args: &[&str]) -> String {
    let g = args.first().and_then(|a| a.parse().ok()).unwrap_or(u32::MAX);
    PROBE_GROUP.store(g, Ordering::Relaxed);
    format!("view model offset in task group {g}")
}

/// The task group applying the pose now (u32::MAX outside the tasks).
pub fn current_group() -> u32 {
    GROUP.load(Ordering::Relaxed)
}

/// From a task (its group id), see `apply`.
pub fn apply_in_group(group: u32) {
    static SEEN: Mutex<Vec<u32>> = Mutex::new(Vec::new());
    if ON.load(Ordering::Relaxed) {
        let mut seen = SEEN.lock().unwrap_or_else(|e| e.into_inner());
        if !seen.contains(&group) {
            seen.push(group);
            log(format!("pose: applied in task groups {seen:?}"));
        }
    }
    GROUP.store(group, Ordering::Relaxed);
    apply();
    GROUP.store(u32::MAX, Ordering::Relaxed);
}

/// Writes the clip's pose for now into the player's skeleton (every task group up to drawing).
pub fn apply() {
    if !ON.load(Ordering::Relaxed) {
        return;
    }
    let Some(chr) = (unsafe { WorldChrMan::instance() }).ok().and_then(|w| w.main_player.as_ref()).map(|p| &p.chr_ins as *const _ as usize) else { return };
    let Some(l) = layout(chr) else { return };
    let mut g = PLAYER.lock().unwrap_or_else(|e| e.into_inner());
    let Some(p) = g.as_mut() else { return };
    if p.map.as_ref().is_none_or(|m| m.0 != l.skeleton) {
        let Some(names) = bone_names(l.skeleton, l.count) else { return };
        let index: HashMap<&str, usize> = names.iter().enumerate().map(|(i, n)| (n.as_str(), i)).collect();
        let m: Vec<Option<usize>> = p.pack.bones.iter().map(|b| index.get(b.as_str()).copied()).collect();
        let missing: Vec<&String> = p.pack.bones.iter().zip(&m).filter(|(_, i)| i.is_none()).map(|(b, _)| b).collect();
        log(format!("pose: skeleton {:#x} ({} bones); pack bones missing there: {missing:?}", l.skeleton, l.count));
        p.map = Some((l.skeleton, m));
        p.rig = rig_bones(&names, l.parents);
        log(format!("pose: first-person rig bones {:?}", p.rig));
        let names = super::pov::carrier_names();
        p.pov = names.as_ref().map(|c| c.iter().map(|n| index.get(n.as_str()).copied()).collect());
        let missing: Vec<&String> = names.iter().flatten().filter(|n| !index.contains_key(n.as_str())).collect();
        log(format!(
            "pose: view-model carriers {:?}{}",
            p.pov.as_ref().map(|v| v.len()),
            if missing.is_empty() { String::new() } else { format!("; not on this skeleton (left to the game): {missing:?}") }
        ));
    }
    let clip = &p.pack.clips[p.clip];
    let map = &p.map.as_ref().unwrap().1;
    let t = p.start.elapsed().as_secs_f32() * clip.fps;
    let (f0, f1, a) = if clip.looping {
        let t = t % clip.frames as f32;
        (t as usize % clip.frames, (t as usize + 1) % clip.frames, t.fract())
    } else {
        let t = t.min((clip.frames - 1) as f32);
        (t as usize, (t as usize + 1).min(clip.frames - 1), t.fract())
    };
    let n = l.count.min(512);
    let mut want: [Option<Quat>; 512] = [None; 512];
    let k = clip.driven.len();
    for (j, &fb) in clip.driven.iter().enumerate() {
        if let Some(b) = map[fb].filter(|&b| b < n) {
            want[b] = Some(clip.rots[f0 * k + j].slerp(clip.rots[f1 * k + j], a));
        }
    }
    let pelvis = clip.pelvis.as_ref().map(|v| v[f0].lerp(v[f1], a));
    let pelvis_bone = p.pack.bones.iter().position(|b| b == "RootPos").and_then(|i| map[i]);
    type Qs = (Vec3, Quat);
    let read = |base: usize, b: usize| -> ([f32; 12], Qs) {
        let v = unsafe { *((base + b * 0x30) as *const [f32; 12]) };
        (v, (Vec3::new(v[0], v[1], v[2]), Quat::from_xyzw(v[4], v[5], v[6], v[7]).normalize()))
    };
    let parent_of = |b: usize| unsafe { *((l.parents + b * 2) as *const i16) };
    let mut world: Vec<Qs> = Vec::with_capacity(n);
    let mut locals: Vec<([f32; 12], bool)> = Vec::with_capacity(n);
    for b in 0..n {
        let (mut v, (mut lt, mut lr)) = read(l.local, b);
        let pi = parent_of(b);
        let parent: Qs = if pi >= 0 && (pi as usize) < b { world[pi as usize] } else { (Vec3::ZERO, Quat::IDENTITY) };
        let hips = (Some(b) == pelvis_bone).then_some(pelvis).flatten();
        let dirty = want[b].is_some() || hips.is_some();
        if dirty {
            if let Some(q) = want[b] {
                lr = q;
            }
            if let Some(pt) = hips {
                lt = parent.1.inverse() * (pt - parent.0);
            }
            v[0..3].copy_from_slice(&lt.to_array());
            v[4..8].copy_from_slice(&lr.to_array());
        }
        world.push((parent.0 + parent.1 * lt, (parent.1 * lr).normalize()));
        locals.push((v, dirty));
    }
    // first person with Apex's view model: the carriers where it puts them, the rest following; a
    // carrier that does not show (the R-301 away, a prop not out) is shrunk to nothing
    let view_model = p.pov.as_ref().filter(|c| c.iter().flatten().all(|&b| b < n)).and_then(|c| crate::firstperson::view_model().map(|x| (c, x)));
    let mut hidden = vec![false; n];
    // a shown carrier's own scale (the jump pad on the ground opens and bounces), model pose only
    let mut scales = vec![Vec3::ONE; n];
    if let Some((carriers, xs)) = view_model {
        let mut set = vec![false; n];
        let probe = GROUP.load(Ordering::Relaxed) == PROBE_GROUP.load(Ordering::Relaxed) && GROUP.load(Ordering::Relaxed) != u32::MAX;
        for (&b, &(t, r, shown, scale)) in carriers.iter().zip(&xs) {
            let Some(b) = b else { continue };
            world[b] = (if probe { t + Vec3::Y * 0.05 } else { t }, r);
            set[b] = true;
            hidden[b] = !shown;
            scales[b] = scale;
        }
        for b in 0..n {
            let pi = parent_of(b);
            let parent: Qs = if pi >= 0 && (pi as usize) < b { world[pi as usize] } else { (Vec3::ZERO, Quat::IDENTITY) };
            let v = &mut locals[b];
            if set[b] {
                let lt = parent.1.inverse() * (world[b].0 - parent.0);
                let lr = (parent.1.inverse() * world[b].1).normalize();
                v.0[0..3].copy_from_slice(&lt.to_array());
                v.0[4..8].copy_from_slice(&lr.to_array());
                v.1 = true;
            } else {
                let (lt, lr) = (Vec3::new(v.0[0], v.0[1], v.0[2]), Quat::from_xyzw(v.0[4], v.0[5], v.0[6], v.0[7]).normalize());
                world[b] = (parent.0 + parent.1 * lt, (parent.1 * lr).normalize());
            }
        }
    }
    // first person: the upper body moved as one piece so the gun sits in the camera's frame
    else if let Some((root, hand)) = p.rig.filter(|r| r.0 < n && r.1 < n) {
        if let Some((t, r)) = crate::firstperson::correction(world[hand]) {
            let pi = parent_of(root);
            let parent: Qs = if pi >= 0 && (pi as usize) < root { world[pi as usize] } else { (Vec3::ZERO, Quat::IDENTITY) };
            let mut moved = vec![false; n];
            for b in root..n {
                let pb = parent_of(b);
                if b == root || (pb >= 0 && (pb as usize) >= root && moved[pb as usize]) {
                    moved[b] = true;
                    world[b] = (t + r * world[b].0, (r * world[b].1).normalize());
                }
            }
            let lt = parent.1.inverse() * (world[root].0 - parent.0);
            let lr = (parent.1.inverse() * world[root].1).normalize();
            let v = &mut locals[root];
            v.0[0..3].copy_from_slice(&lt.to_array());
            v.0[4..8].copy_from_slice(&lr.to_array());
            v.1 = true;
        }
    }
    for b in 0..n {
        let (v, dirty) = locals[b];
        if dirty {
            unsafe { *((l.local + b * 0x30) as *mut [f32; 12]) = v };
        }
        let mut mv = v;
        if hidden[b] {
            // hkQsTransform: translation, rotation, then the scale (x y z w); only the model pose,
            // which the renderer skins with: a hidden carrier can be a parent of shown ones (the
            // pad's carriers include Spine and Pelvis), so its local scale stays
            mv[8..11].copy_from_slice(&[HIDDEN_SCALE; 3]);
        } else if scales[b] != Vec3::ONE && scales[b].is_finite() {
            mv[8..11].copy_from_slice(&scales[b].to_array());
        }
        mv[0..3].copy_from_slice(&world[b].0.to_array());
        mv[3] = 0.0;
        mv[4..8].copy_from_slice(&world[b].1.to_array());
        unsafe { *((l.model + b * 0x30) as *mut [f32; 12]) = mv };
    }
}

/// The scale of a view-model carrier that does not show: small enough to vanish, not 0 (normals).
const HIDDEN_SCALE: f32 = 1e-4;

/// First person's rig on the live skeleton: the lowest common ancestor of the hands, and R_Hand.
fn rig_bones(names: &[String], parents: usize) -> Option<(usize, usize)> {
    let find = |n: &str| names.iter().position(|b| b == n);
    let (left, right) = (find("L_Hand")?, find("R_Hand")?);
    let parent_of = |b: usize| unsafe { *((parents + b * 2) as *const i16) };
    let chain = |mut b: usize| {
        let mut c = vec![b];
        while let Ok(pb) = usize::try_from(parent_of(b)) {
            if pb >= b || c.len() > names.len() {
                break;
            }
            b = pb;
            c.push(b);
        }
        c
    };
    let lc = chain(left);
    let root = chain(right).into_iter().find(|b| lc.contains(b))?;
    Some((root, right))
}

/// er-mario: where the game's animation job has just written a pose (exe 2.7.1.0).
const ANIM_DONE_RVAS: [usize; 2] = [0x41da14, 0x402194];

fn install_anim_hook() {
    static DONE: AtomicBool = AtomicBool::new(false);
    if DONE.swap(true, Ordering::Relaxed) || paths::config("pose_hook").is_some_and(|v| v == "0") {
        return;
    }
    use ilhook::x64::{CallbackOption, HookFlags, hook_closure_jmp_back};
    let Ok(base) = (unsafe { windows::Win32::System::LibraryLoader::GetModuleHandleW(None) }) else { return };
    for rva in ANIM_DONE_RVAS {
        let at = base.0 as usize + rva;
        let bytes = unsafe { *(at as *const [u8; 8]) };
        let hook = |_: *mut ilhook::x64::Registers| {
            let _ = std::panic::catch_unwind(apply);
        };
        match unsafe { hook_closure_jmp_back(at, hook, CallbackOption::None, HookFlags::empty()) } {
            Ok(h) => {
                std::mem::forget(h);
                log(format!("pose: hooked the animation job at +{rva:#x} (bytes {bytes:02x?})"));
            }
            Err(e) => log(format!("pose: animation hook at +{rva:#x} failed: {e:?}")),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pack_bytes() -> Vec<u8> {
        let mut d = b"FERA".to_vec();
        d.extend(1u32.to_le_bytes());
        d.extend(2u32.to_le_bytes());
        for n in ["RootPos", "Spine"] {
            d.extend((n.len() as u16).to_le_bytes());
            d.extend(n.as_bytes());
        }
        d.extend(1u32.to_le_bytes());
        d.extend(4u16.to_le_bytes());
        d.extend(b"idle");
        d.extend(30f32.to_le_bytes());
        d.extend(2u32.to_le_bytes());
        d.push(1);
        d.extend([1u8, 1]);
        for _ in 0..2 {
            for _ in 0..2 {
                for v in [0f32, 0.0, 0.0, 1.0] {
                    d.extend(v.to_le_bytes());
                }
            }
            for v in [0f32, 1.0, 0.0] {
                d.extend(v.to_le_bytes());
            }
        }
        d
    }

    #[test]
    fn parses_and_rejects() {
        let d = pack_bytes();
        let p = parse(&d).unwrap();
        assert_eq!(p.clips[0].driven, vec![0, 1]);
        assert_eq!(p.clips[0].pelvis.as_ref().unwrap().len(), 2);
        assert!(parse(&d[..d.len() - 1]).is_err());
        let mut bad = d.clone();
        bad[0] = b'X';
        assert!(parse(&bad).is_err());
    }
}
