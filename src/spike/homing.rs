//! Homing shots (the Sentinel, the user's 2026-10-09 ask): a shot of a gun with `homing` set
//! (gun.rs `Spec`) turns towards the enemy nearest the crosshair inside a cone, if one is within
//! range; the ray then goes to that enemy's body as any shot does (walls still stop it: gun.rs
//! `fire_ray_ex`).
//!
//! Every number is here, and each can be changed in er_apex.ini without a rebuild (read fresh on
//! every shot):
//!
//! | ini key | default | meaning |
//! |---|---|---|
//! | `homing` | 1 | 0 turns homing off |
//! | `homing_range` | 60 | metres: enemies farther away are not tracked |
//! | `homing_angle` | 20 | degrees from the crosshair: the cone's half angle |
//! | `homing_height` | 0.6 | where on the enemy the shot goes, from its feet (0) to its top (1) |

use glam::Vec3;

use eldenring::cs::{ChrIns, WorldChrMan};
use fromsoftware_shared::FromStatic;

use crate::paths;

pub const RANGE: f32 = 60.0;
pub const ANGLE_DEG: f32 = 20.0;
pub const HEIGHT: f32 = 0.6;

/// The homing settings now (ini over the defaults above).
#[derive(Clone, Copy, Debug)]
pub struct Settings {
    pub on: bool,
    pub range: f32,
    pub angle_deg: f32,
    pub height: f32,
}

pub fn settings() -> Settings {
    let num = |k: &str, d: f32| paths::number::<f32>(k).filter(|v| v.is_finite()).unwrap_or(d);
    Settings {
        on: paths::config("homing").is_none_or(|v| v.trim() != "0"),
        range: num("homing_range", RANGE).max(0.0),
        angle_deg: num("homing_angle", ANGLE_DEG).clamp(0.0, 89.0),
        height: num("homing_height", HEIGHT).clamp(0.0, 1.0),
    }
}

/// The direction from `origin` to the enemy nearest `dir` (by angle) within the cone and range;
/// None: no enemy there (the shot goes where it was aimed).
pub fn steer(origin: Vec3, dir: Vec3) -> Option<Vec3> {
    let s = settings();
    if !s.on || s.range <= 0.0 || s.angle_deg <= 0.0 {
        return None;
    }
    let cos_max = s.angle_deg.to_radians().cos();
    let wcm = unsafe { WorldChrMan::instance() }.ok()?;
    let mut best: Option<(f32, Vec3)> = None;
    for c in wcm.chr_sets.iter().flatten().flat_map(|set| set.characters()) {
        let c: &ChrIns = c;
        if c.modules.data.hp <= 0 || !super::body::is_enemy_team(c.team_type) {
            continue;
        }
        let (h, _) = super::body::cylinder(c);
        let q = c.modules.physics.position;
        let at = Vec3::new(q.0, q.1 + h * s.height, q.2);
        let to = at - origin;
        let dist = to.length();
        if dist < 0.5 || dist > s.range {
            continue;
        }
        let d = to / dist;
        let cos = d.dot(dir);
        if cos >= cos_max && best.is_none_or(|b| cos > b.0) {
            best = Some((cos, d));
        }
    }
    best.map(|b| b.1)
}
