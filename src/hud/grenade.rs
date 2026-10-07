//! The frag grenade on the HUD (U9, spike/grenade.rs). Until the grenade has a model (phase 2) it
//! is drawn here, all of it an approximation (近似) of S3's 3D effects:
//! - in the air and on the ground: a red dot where it is (its glow, `frag_grenade_glow_fx`, and the
//!   trail `P_wpn_grenade_frag_trail` are red);
//! - aiming with it in hand: its arc (`grenade_arc_indicator_effect` P_arc_red, through one bounce)
//!   and a ring where it ends (`grenade_arc_impact_indicator_effect` P_arc_red_end);
//! - S3's grenade indicator (cl_damage_indicator.gnut GrenadeArrowThink: the arrow model
//!   grenade_indicator_arrow.rmdl 25 units ahead of the camera and 4 down, turned towards the
//!   grenade, the frag's icon model at its back) as an arrow below the crosshair pointing at it,
//!   with the ordnance icon;
//! - the explosion (the particle P_impact_exp_FRAG_*): a flash growing to the inner radius over
//!   0.15 s and fading by 0.5 s, and the screen washed in by how close it was.

use glam::Vec3;
use hudhook::imgui::DrawListMut;

use super::{project, tex, view};
use crate::spike::grenade;

/// The frag's HUD icon (`hud_icon`), as the HUD's ordnance slot draws it.
pub const ICON: &str = "rui/ordnance_icons/grenade_frag";

const RED: [f32; 4] = [1.0, 0.16, 0.1, 0.95];
const EDGE: [f32; 4] = [0.0, 0.0, 0.0, 0.6];

/// A world circle's radius on screen at `at` (px), through the camera's right.
fn screen_radius(at: Vec3, radius: f32, size: [f32; 2]) -> Option<([f32; 2], f32)> {
    let (_, _, right, _) = view()?;
    let c = project(at, size)?;
    let e = project(at + right.normalize_or_zero() * radius, size)?;
    Some((c, ((e[0] - c[0]).powi(2) + (e[1] - c[1]).powi(2)).sqrt()))
}

pub fn draw(dl: &DrawListMut, size: [f32; 2]) {
    let k = (size[0] / 1920.0).min(size[1] / 1080.0);
    // the aim arc and its end
    if let Some((points, end)) = grenade::aim_arc() {
        let pts: Vec<[f32; 2]> = points.iter().filter_map(|p| project(*p, size)).collect();
        if pts.len() >= 2 {
            dl.add_polyline(pts.clone(), [0.0, 0.0, 0.0, 0.35])
                .thickness(4.0 * k)
                .build();
            dl.add_polyline(pts, RED).thickness(2.0 * k).build();
        }
        if let Some((c, r)) = end.and_then(|e| screen_radius(e, 0.25, size)) {
            dl.add_circle(c, r.max(4.0 * k), RED)
                .thickness(2.0 * k)
                .num_segments(24)
                .build();
        }
    }
    // the grenades: a dot for each one not drawn as a model (the newest two are: firstperson.rs)
    let live = grenade::live();
    let models = crate::firstperson::world_grenades_drawn().min(live.len());
    for (at, _, _) in &live[..live.len() - models] {
        if let Some(c) = project(*at, size) {
            dl.add_circle(c, 5.0 * k, EDGE).filled(true).build();
            dl.add_circle(c, 3.5 * k, RED).filled(true).build();
        }
    }
    // S3's grenade indicator: the nearest one that shows
    if let Some((eye, fwd, right, up)) = view() {
        let nearest = live
            .iter()
            .filter(|g| g.2)
            .map(|g| g.0)
            .min_by(|a, b| a.distance(eye).total_cmp(&b.distance(eye)));
        if let Some(at) = nearest {
            indicator(dl, size, k, at - eye, (fwd, right, up));
        }
    }
    // the explosions
    for (at, age) in grenade::bursts() {
        let grow = (age / 0.15).min(1.0);
        let a = 1.0 - ((age - 0.1) / 0.4).clamp(0.0, 1.0);
        if a <= 0.0 {
            continue;
        }
        let inner = grenade::outer_radius() * (grenade::INNER_RADIUS / grenade::OUTER_RADIUS);
        if let Some((c, r)) = screen_radius(at, inner * (0.3 + 0.7 * grow), size) {
            dl.add_circle(c, r, [1.0, 0.62, 0.2, 0.45 * a])
                .filled(true)
                .num_segments(32)
                .build();
            dl.add_circle(c, r * 0.55, [1.0, 0.92, 0.7, 0.6 * a])
                .filled(true)
                .num_segments(32)
                .build();
        }
        // washed by nearness (the share of damage it would deal at the eye)
        if let Some((eye, ..)) = view() {
            let near = grenade::falloff((at - eye).length() * crate::spike::kcc::UNITS_PER_METRE);
            if near > 0.0 {
                dl.add_rect([0.0, 0.0], size, [1.0, 0.85, 0.6, 0.35 * near * a])
                    .filled(true)
                    .build();
            }
        }
    }
}

/// The arrow below the crosshair pointing at a grenade (`to`: from the eye), its icon behind it.
fn indicator(
    dl: &DrawListMut,
    size: [f32; 2],
    k: f32,
    to: Vec3,
    (fwd, right, up): (Vec3, Vec3, Vec3),
) {
    // S3: 25 units ahead and 4 down of the camera, ~9° below the crosshair; ER's field of view
    // makes that about 0.35 of the half height
    let (cx, cy) = (size[0] * 0.5, size[1] * 0.5 + size[1] * 0.5 * 0.35);
    let d = to.normalize_or_zero();
    let (x, y) = (
        d.dot(right.normalize_or_zero()),
        d.dot(up.normalize_or_zero()),
    );
    // straight ahead or behind: point up / down the screen
    let (x, y) = if x * x + y * y < 1e-4 {
        (0.0, if d.dot(fwd) >= 0.0 { 1.0 } else { -1.0 })
    } else {
        (x, y)
    };
    let ang = x.atan2(y);
    let (s, c) = ang.sin_cos();
    let at = |ahead: f32, side: f32| {
        [
            cx + (s * ahead + c * side) * k,
            cy - (c * ahead - s * side) * k,
        ]
    };
    let (tip, base, half) = (34.0, 12.0, 11.0);
    // a dark edge: the same triangle 3 px larger under it
    let edge = vec![
        at(tip + 3.5, 0.0),
        at(base - 2.0, half + 3.0),
        at(base - 2.0, -half - 3.0),
    ];
    dl.add_polyline(edge, [0.0, 0.0, 0.0, 0.55])
        .filled(true)
        .build();
    let tri = vec![at(tip, 0.0), at(base, half), at(base, -half)];
    dl.add_polyline(tri, RED).filled(true).build();
    if let Some((id, [w, h])) = tex::get(ICON) {
        let size_px = 30.0 * k;
        let sc = (size_px / w).min(size_px / h);
        let (iw, ih) = (w * sc, h * sc);
        let c0 = at(-4.0, 0.0);
        dl.add_circle(c0, size_px * 0.62, [0.0, 0.0, 0.0, 0.45])
            .filled(true)
            .build();
        // the icon in its own colours (white body, orange hexes)
        dl.add_image(
            id,
            [c0[0] - iw * 0.5, c0[1] - ih * 0.5],
            [c0[0] + iw * 0.5, c0[1] + ih * 0.5],
        )
        .build();
    } else {
        dl.add_circle(at(-4.0, 0.0), 9.0 * k, RED)
            .filled(true)
            .build();
    }
}
