//! A character's size as drawn, for aiming at it: Elden Ring's character capsule (`hit_height`,
//! `chr_hit_height`) is human-sized even for bosses (Godrick's is 2.0 m; he is drawn about 5 m tall
//! and his lock-on point is 2.6 m up, so every shot at him passed over the capsule; journal
//! 2026-10-04). The model pose knows better: its highest bone is the top of the character.

use eldenring::cs::ChrIns;

use crate::explore::{read_u64, readable};

/// The capsule's height and radius (the larger of the physics module's two of each; a human's
/// default if neither is set).
pub fn capsule(chr: &ChrIns) -> (f32, f32) {
    let ph = &chr.modules.physics;
    let h = [ph.hit_height, ph.chr_hit_height].into_iter().filter(|v| v.is_finite() && *v > 0.2).fold(0.0, f32::max);
    let r = [ph.hit_radius, ph.chr_hit_radius].into_iter().filter(|v| v.is_finite() && *v > 0.05).fold(0.0, f32::max);
    (if h > 0.0 { h } else { 1.8 }, if r > 0.0 { r } else { 0.4 })
}

/// The highest bone of the current model pose, metres above the character's feet: the pose
/// importer at ChrIns+0x398, model pose (hkQsTransform, 0x30 each) at +0x60, count at +0x68
/// (layout: spike/skeleton.rs). None if unreadable or implausible.
pub fn top(chr: &ChrIns) -> Option<f32> {
    let imp = read_u64(chr as *const ChrIns as usize + 0x398)? as usize;
    let model = read_u64(imp + 0x60)? as usize;
    let n = (read_u64(imp + 0x68)? & 0xffff_ffff) as usize;
    if n == 0 || n > 1024 || !readable(model, n * 0x30) {
        return None;
    }
    let top = (0..n).map(|i| unsafe { *((model + i * 0x30 + 4) as *const f32) }).filter(|y| y.is_finite()).fold(f32::MIN, f32::max);
    (top > 0.3 && top < 60.0).then_some(top)
}

/// The cylinder to aim at: as tall as the character is drawn (its top bone + 10 %), never less
/// than its capsule; the capsule's radius scaled with the height (at most 3 times).
pub fn cylinder(chr: &ChrIns) -> (f32, f32) {
    let (h, r) = capsule(chr);
    match top(chr) {
        Some(t) if t * 1.1 > h => {
            let tall = t * 1.1;
            (tall, r * (tall / h).min(3.0))
        }
        _ => (h, r),
    }
}
