//! Apex's procedural view model bob and sway (spec §3.1), as R5R's client code does it (IDA
//! database scratch/ref/r5, names given 2026-10-05): `vm_sway_think` 0x1406294E0 once a frame calls
//! `vm_sway_update` 0x140A07DD0 with the weapon's sway settings (weapon settings +0x328 hip,
//! +0x4C8 zoomed; parser 0x140FCBBE0), then `vm_sway_build_matrix` 0x140A08E20 turns the result
//! into a matrix in the view model's own space, and `vm_apply_sway_matrix` 0x1406299E0 puts the view
//! model at (eye, angles, hold offset) times that matrix.
//!
//! - Bob: a phase advances at RemapValClamped(view-relative horizontal speed, bob_min_speed,
//!   bob_max_speed, 0, 1) per second while on the ground (the speed reads 0 while sliding:
//!   `vm_sway_update`'s last argument is the player's `m_sliding`, +0x2815) and wraps at
//!   2 bob_cycle_time; the view
//!   model moves up `bob_vert_dist` sin(2π phase / cycle) and left `bob_horz_dist`
//!   sin(π phase / cycle), pitches `bob_pitch` times the first sine and yaws/rolls `bob_yaw` /
//!   `bob_roll` times the second; all four eased by 1 - exp(-bob_gain dt). Standing still, the phase
//!   eases to its nearest rest point (0, cycle, 2 cycle) at the same rate and the sines to 0.
//! - Sway: targets add up the velocity in the view's frame times dt times `sway_move_*` (forward or
//!   back, left or right, up or down: the side moved to) and the turn rate (the last 5 frames'
//!   average, degrees/s) times the tick interval (0.05 s) times `sway_turn_*`; the translation target
//!   is clamped to `sway_min/max_x/y/z`; translation and angles ease to the targets by
//!   1 - exp(-sway_translate_gain dt) and 1 - exp(-sway_rotate_gain dt); the angles are then clamped
//!   to `sway_min/max_pitch/yaw/roll`.
//! - Aiming (any zoom with `sway_enable_zoomed`, on unless a weapon sets it off) switches to the
//!   `_zoomed` set; the angle clamps and bob angles are blended hip -> zoomed by clamp(2.2 ads).
//! - The rotation (sway angles plus bob angles, Source's AngleMatrix) turns about the attachment
//!   `SWAY_ROTATE` (hip) or `SWAY_ROTATE_ZOOMED` (blended in over
//!   `sway_rotate_attach_blend_time_zoomed` once fully zoomed, back at once), then the translation
//!   (sway plus bob) is added.
//!
//! Axes: Source's, in the view model's own space (the eye's: x forward, y left, z up); angles
//! (pitch down, yaw left, roll) in degrees; units Apex's (inches).

use glam::{Mat3, Quat, Vec3};

/// One set of a weapon's bob and sway settings (the hip or the zoomed one).
#[derive(Clone, Copy, Debug)]
pub struct Set {
    pub min_t: Vec3,
    pub max_t: Vec3,
    pub min_a: Vec3,
    pub max_a: Vec3,
    pub translate_gain: f32,
    pub rotate_gain: f32,
    pub bob_cycle: f32,
    pub bob_min_speed: f32,
    pub bob_max_speed: f32,
    pub bob_vert: f32,
    pub bob_horz: f32,
    /// bob_pitch, bob_yaw, bob_roll
    pub bob_angles: Vec3,
    pub bob_gain: f32,
    /// Per direction: translate x, y, z, then rotate pitch, yaw, roll.
    pub move_forward: [f32; 6],
    pub move_back: [f32; 6],
    pub move_left: [f32; 6],
    pub move_right: [f32; 6],
    pub move_up: [f32; 6],
    pub move_down: [f32; 6],
    pub turn_left: [f32; 6],
    pub turn_right: [f32; 6],
    pub turn_up: [f32; 6],
    pub turn_down: [f32; 6],
}

/// The parser's defaults (0x140FCBBE0) for what a weapon leaves out: bob_min_speed 0.1,
/// bob_max_speed 0.2, the gains 12 (hip) and 24 (zoomed translate/rotate; bob_gain 12), the rest 0.
const ZERO6: [f32; 6] = [0.0; 6];

/// The R-301's (apex-data/export/weapon/mp_weapon_rspn101.txt; the export writes negative integers
/// as unsigned 64-bit numbers: 18446744073709551613 is -3). Not set there, so the parser's
/// defaults: bob_min_speed 0.1, bob_gain 12.
pub const R301_HIP: Set = Set {
    min_t: Vec3::new(-0.5, -0.5, -0.6),
    max_t: Vec3::new(0.5, 0.5, 0.6),
    min_a: Vec3::new(-3.0, -2.5, -4.0),
    max_a: Vec3::new(3.0, 2.5, 4.0),
    translate_gain: 2.5,
    rotate_gain: 7.0,
    bob_cycle: 0.4,
    bob_min_speed: 0.1,
    bob_max_speed: 173.0,
    bob_vert: 0.19,
    bob_horz: 0.1,
    bob_angles: Vec3::new(0.75, -1.7, 1.2),
    bob_gain: 12.0,
    move_forward: [-0.1, 0.0, -0.5, 0.0, 0.0, 0.0],
    move_back: [0.2, 0.0, -0.2, 0.0, 0.0, 0.0],
    move_left: [0.0, -1.0, -0.5, 0.0, 0.0, -4.0],
    move_right: [0.0, 1.0, -0.5, 0.0, 0.0, 4.0],
    move_up: [0.0, 0.0, -1.0, 0.0, 0.0, 0.0],
    move_down: [0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
    turn_left: [0.0, 0.5, 0.0, 0.0, -2.5, 4.0],
    turn_right: [0.0, -0.5, 0.0, 0.0, 2.5, -4.0],
    turn_up: [0.1, 0.0, 0.2, 3.0, 0.0, -0.8],
    turn_down: [-0.1, 0.0, -0.2, -3.0, 0.0, 0.8],
};

/// The R-301's `_zoomed` set; not set there: the translation clamps (0: no translation sway while
/// aiming), bob_pitch 0, bob_min_speed 0.1, the translate gain 24, bob_gain 12.
pub const R301_ZOOMED: Set = Set {
    min_t: Vec3::ZERO,
    max_t: Vec3::ZERO,
    min_a: Vec3::new(-0.0065, -0.0275, -1.0),
    max_a: Vec3::new(0.008, 0.0275, 1.0),
    translate_gain: 24.0,
    rotate_gain: 5.0,
    bob_cycle: 0.4,
    bob_min_speed: 0.1,
    bob_max_speed: 155.0,
    bob_vert: 0.0275,
    bob_horz: 0.065,
    bob_angles: Vec3::new(0.0, -0.01, 0.25),
    bob_gain: 12.0,
    move_forward: ZERO6,
    move_back: ZERO6,
    move_left: [0.0, 0.0, 0.0, 0.0, 0.0, -0.2],
    move_right: [0.0, 0.0, 0.0, 0.0, 0.0, 0.2],
    move_up: ZERO6,
    move_down: ZERO6,
    turn_left: [0.0, 0.0, 0.0, 0.0, -0.085, -1.0],
    turn_right: [0.0, 0.0, 0.0, 0.0, 0.085, 1.0],
    turn_up: [0.0, 0.0, 0.0, 0.07, 0.0, 0.0],
    turn_down: [0.0, 0.0, 0.0, -0.07, 0.0, 0.0],
};

/// `sway_rotate_attach_blend_time_zoomed` (the R-301's 0.2 s); the hip one is not set: 0, at once.
pub const PIVOT_BLEND_ZOOMED: f32 = 0.2;
/// The turn rate is scaled by the tick interval (globals +0x44): R5R's `base_tickinterval_mp` 0.05
/// (platform/cfg/system/autoexec_client_dev.cfg), Apex's 20 Hz.
const TICK_INTERVAL: f32 = 0.05;

/// What the sway reads each frame.
#[derive(Clone, Copy, Debug, Default)]
pub struct SwayIn {
    pub dt: f32,
    /// How far the view turned since the last frame: pitch (down), yaw (left), roll, degrees.
    pub turn: Vec3,
    /// The velocity in the view's frame: forward, left, up (units/s).
    pub velocity: Vec3,
    pub grounded: bool,
    /// The player's `m_sliding` (+0x2815, found by its datamap entry): the bob reads speed 0.
    pub sliding: bool,
    /// The zoom, 0..1.
    pub ads: f32,
}

/// The state Apex keeps per view model (`vm_sway_update`'s first argument and the pivot blend).
#[derive(Clone, Copy, Debug, Default)]
pub struct Sway {
    /// eased sway translation and angles
    pos: Vec3,
    ang: Vec3,
    /// the last 5 frames' turn rates (degrees/s) and the slot written last
    rates: [Vec3; 5],
    slot: usize,
    /// bob phase (seconds of cycle), the eased sines and the eased offsets (up, left)
    phase: f32,
    sin_vert: f32,
    sin_horz: f32,
    bob_up: f32,
    bob_left: f32,
    bob_ang: Vec3,
    /// 0 hip pivot .. 1 zoomed pivot
    pivot: f32,
}

/// Source's RemapValClamped (0x140427190).
fn remap_clamped(v: f32, a: f32, b: f32, c: f32, d: f32) -> f32 {
    if a == b {
        return if v - b >= 0.0 { d } else { c };
    }
    c + (d - c) * ((v - a) / (b - a)).clamp(0.0, 1.0)
}

/// Source's AngleDiff (0x14042FF30): a - b in (-180, 180].
fn angle_diff(a: f32, b: f32) -> f32 {
    let d = (a - b) % 360.0;
    if a > b {
        if d >= 180.0 { d - 360.0 } else { d }
    } else if d <= -180.0 {
        d + 360.0
    } else {
        d
    }
}

/// Source's AngleMatrix: (pitch, yaw, roll) degrees to the rotation whose columns are forward,
/// left, up.
pub fn angle_matrix(a: Vec3) -> Mat3 {
    let (sp, cp) = a.x.to_radians().sin_cos();
    let (sy, cy) = a.y.to_radians().sin_cos();
    let (sr, cr) = a.z.to_radians().sin_cos();
    Mat3::from_cols(
        Vec3::new(cp * cy, cp * sy, -sp),
        Vec3::new(sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, sr * cp),
        Vec3::new(cr * sp * cy + sr * sy, cr * sp * sy - sr * cy, cr * cp),
    )
}

fn add(t: &mut Vec3, a: &mut Vec3, g: &[f32; 6], s: f32) {
    *t += Vec3::new(g[0], g[1], g[2]) * s;
    *a += Vec3::new(g[3], g[4], g[5]) * s;
}

impl Sway {
    /// One frame (`vm_sway_update`, and the pivot blend of `vm_sway_think`).
    pub fn step(&mut self, i: &SwayIn, hip: &Set, zoomed: &Set) {
        let dt = i.dt;
        if dt <= 0.0 {
            return;
        }
        let set = if i.ads > 0.0 { zoomed } else { hip };

        // bob
        let cycle = set.bob_cycle;
        let speed = if i.sliding { 0.0 } else { Vec3::new(i.velocity.x, i.velocity.y, 0.0).length() };
        let rate = if i.grounded && cycle > 0.0 { remap_clamped(speed, set.bob_min_speed, set.bob_max_speed, 0.0, 1.0) } else { 0.0 };
        let keep = (-set.bob_gain * dt).exp();
        let (s_vert, s_horz) = if rate <= 0.0 {
            // to the nearest rest point of the phase
            let rest = if self.phase > 1.5 * cycle {
                2.0 * cycle
            } else if self.phase < 0.5 * cycle {
                0.0
            } else {
                cycle
            };
            self.phase = (1.0 - keep) * rest + keep * self.phase;
            (0.0, 0.0)
        } else {
            self.phase = (rate * dt + self.phase) % (2.0 * cycle);
            let v = (self.phase % cycle) * std::f32::consts::TAU / cycle;
            let h = self.phase * std::f32::consts::TAU / (2.0 * cycle);
            (v.sin(), h.sin())
        };
        let ease = |x: f32, to: f32| (1.0 - keep) * to + keep * x;
        self.sin_vert = ease(self.sin_vert, s_vert);
        self.sin_horz = ease(self.sin_horz, s_horz);
        self.bob_up = ease(self.bob_up, s_vert * set.bob_vert);
        self.bob_left = ease(self.bob_left, s_horz * set.bob_horz);

        // sway targets: moving
        let (mut t, mut a) = (Vec3::ZERO, Vec3::ZERO);
        let v = i.velocity * dt;
        if i.velocity.x < 0.0 {
            add(&mut t, &mut a, &set.move_back, -v.x);
        } else {
            add(&mut t, &mut a, &set.move_forward, v.x);
        }
        if i.velocity.y < 0.0 {
            add(&mut t, &mut a, &set.move_right, -v.y);
        } else {
            add(&mut t, &mut a, &set.move_left, v.y);
        }
        if i.velocity.z < 0.0 {
            add(&mut t, &mut a, &set.move_down, -v.z);
        } else {
            add(&mut t, &mut a, &set.move_up, v.z);
        }
        // turning: the average rate of the last 5 frames times the tick interval
        self.slot = (self.slot + 1) % 5;
        self.rates[self.slot] = i.turn / dt;
        let avg = self.rates.iter().fold(Vec3::ZERO, |s, r| s + *r * 0.2) * TICK_INTERVAL;
        if avg.x < 0.0 {
            add(&mut t, &mut a, &set.turn_up, -avg.x);
        } else {
            add(&mut t, &mut a, &set.turn_down, avg.x);
        }
        if avg.y < 0.0 {
            add(&mut t, &mut a, &set.turn_right, -avg.y);
        } else {
            add(&mut t, &mut a, &set.turn_left, avg.y);
        }

        // ease to them
        let t = t.clamp(set.min_t, set.max_t);
        let kt = 1.0 - (-set.translate_gain * dt).exp();
        self.pos += (t - self.pos) * kt;
        let kr = 1.0 - (-set.rotate_gain * dt).exp();
        for k in 0..3 {
            self.ang[k] += kr * angle_diff(a[k] % 360.0, self.ang[k]);
        }
        // the angle clamps and the bob angles, hip to zoomed by the zoom (sway_enable_zoomed)
        let w = (i.ads * 2.2).clamp(0.0, 1.0);
        self.ang = self.ang.clamp(hip.min_a.lerp(zoomed.min_a, w), hip.max_a.lerp(zoomed.max_a, w));
        let b = hip.bob_angles.lerp(zoomed.bob_angles, w);
        self.bob_ang = Vec3::new(b.x * self.sin_vert, b.y * self.sin_horz, b.z * self.sin_horz);

        // the pivot: zoomed once fully zoomed (blended in), hip otherwise (at once)
        if i.ads >= 1.0 {
            self.pivot = if PIVOT_BLEND_ZOOMED > 0.0 { (self.pivot + dt / PIVOT_BLEND_ZOOMED).min(1.0) } else { 1.0 };
        } else {
            self.pivot = 0.0;
        }
    }

    /// The matrix the view model is put through (`vm_sway_build_matrix`): the rotation turns about
    /// the pivot (hip and zoomed attachments in the view model's space, blended), then the sway and
    /// bob translation is added. Returns (rotation, translation).
    pub fn matrix(&self, hip_pivot: (Vec3, Quat), zoomed_pivot: (Vec3, Quat)) -> (Quat, Vec3) {
        let (p, q) = if self.pivot <= 0.0 {
            hip_pivot
        } else if self.pivot >= 1.0 {
            zoomed_pivot
        } else {
            (hip_pivot.0.lerp(zoomed_pivot.0, self.pivot), hip_pivot.1.slerp(zoomed_pivot.1, self.pivot))
        };
        let r = Quat::from_mat3(&angle_matrix(self.ang + self.bob_ang));
        let rot = (q * r * q.inverse()).normalize();
        let t = p - rot * p + self.pos + Vec3::new(0.0, self.bob_left, self.bob_up);
        (rot, t)
    }

    /// For `fp trace`: the eased sway translation and angles, the bob offsets (up, left) and angles,
    /// the pivot blend.
    pub fn describe(&self) -> String {
        format!(
            "sway t {:.3} {:.3} {:.3} a {:.3} {:.3} {:.3} | bob up {:.3} left {:.3} a {:.3} {:.3} {:.3} | pivot {:.2}",
            self.pos.x, self.pos.y, self.pos.z, self.ang.x, self.ang.y, self.ang.z, self.bob_up, self.bob_left, self.bob_ang.x, self.bob_ang.y, self.bob_ang.z, self.pivot
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const DT: f32 = 1.0 / 60.0;

    fn walk(s: &mut Sway, frames: usize, velocity: Vec3) -> Vec<Sway> {
        (0..frames)
            .map(|_| {
                s.step(&SwayIn { dt: DT, velocity, grounded: true, ..Default::default() }, &R301_HIP, &R301_ZOOMED);
                *s
            })
            .collect()
    }

    #[test]
    fn helpers_like_source() {
        assert_eq!(remap_clamped(86.5, 0.1, 173.0, 0.0, 1.0), (86.5 - 0.1) / (173.0 - 0.1));
        assert_eq!(remap_clamped(500.0, 0.1, 173.0, 0.0, 1.0), 1.0);
        assert!((angle_diff(10.0, 350.0) - 20.0).abs() < 1e-4);
        assert!((angle_diff(350.0, 10.0) + 20.0).abs() < 1e-4);
        // pitch down 90: forward to -z; yaw 90: forward to +y (left)
        let m = angle_matrix(Vec3::new(90.0, 0.0, 0.0));
        assert!((m.x_axis - Vec3::new(0.0, 0.0, -1.0)).length() < 1e-5);
        let m = angle_matrix(Vec3::new(0.0, 90.0, 0.0));
        assert!((m.x_axis - Vec3::Y).length() < 1e-5 && (m.y_axis + Vec3::X).length() < 1e-5);
    }

    /// Walking at Apex's walk speed (173.5, above bob_max_speed 173): the vertical bob repeats every
    /// bob_cycle_time 0.4 s, the horizontal one every 0.8 s; the eased amplitudes are the settings
    /// times the first-order lag at gain 12 (vertical 2.5 Hz: 0.607; horizontal 1.25 Hz: 0.837).
    #[test]
    fn walking_bob_period_and_amplitude() {
        let mut s = Sway::default();
        let f = walk(&mut s, 240, Vec3::new(173.5, 0.0, 0.0));
        let tail = &f[120..];
        let span = |g: &dyn Fn(&Sway) -> f32| {
            let (lo, hi) = tail.iter().map(g).fold((f32::MAX, f32::MIN), |(lo, hi), v| (lo.min(v), hi.max(v)));
            hi - lo
        };
        let lag = |hz: f32| 1.0 / (1.0 + (std::f32::consts::TAU * hz / 12.0).powi(2)).sqrt();
        let up = span(&|s| s.bob_up);
        let left = span(&|s| s.bob_left);
        assert!((up - 2.0 * 0.19 * lag(2.5)).abs() < 0.01, "up p-p {up}");
        assert!((left - 2.0 * 0.1 * lag(1.25)).abs() < 0.01, "left p-p {left}");
        let yaw = span(&|s| s.bob_ang.y);
        let roll = span(&|s| s.bob_ang.z);
        let pitch = span(&|s| s.bob_ang.x);
        // R5R T1 (spec §3 table, view model angles less the animation): yaw 2.84°, roll 2.08°,
        // pitch 1.10° peak to peak; the pitch differs (the measured includes the turn about the
        // pivot and the sway of the walk itself)
        assert!((yaw - 3.4 * lag(1.25)).abs() < 0.05 && (yaw - 2.84).abs() < 0.1, "yaw p-p {yaw}");
        assert!((roll - 2.4 * lag(1.25)).abs() < 0.05 && (roll - 2.08).abs() < 0.1, "roll p-p {roll}");
        assert!((pitch - 1.5 * lag(2.5)).abs() < 0.05, "pitch p-p {pitch}");
        // periods: zero crossings of the eased sines 0.2 s apart (vertical), 0.4 s (horizontal)
        let crossings = |g: &dyn Fn(&Sway) -> f32| -> Vec<usize> { (1..tail.len()).filter(|&k| g(&tail[k - 1]) < 0.0 && g(&tail[k]) >= 0.0).collect() };
        let v = crossings(&|s| s.sin_vert);
        let h = crossings(&|s| s.sin_horz);
        assert!(v.windows(2).all(|w| (w[1] - w[0]) as i32 - 24 <= 1 && 24 - ((w[1] - w[0]) as i32) <= 1), "vertical {v:?}");
        assert!(h.windows(2).all(|w| (w[1] - w[0]) as i32 - 48 <= 1 && 48 - ((w[1] - w[0]) as i32) <= 1), "horizontal {h:?}");
    }

    /// Stopping: the phase settles on a rest point and the bob dies away; standing still nothing
    /// moves.
    #[test]
    fn standing_still_settles() {
        let mut s = Sway::default();
        walk(&mut s, 37, Vec3::new(173.5, 0.0, 0.0));
        let f = walk(&mut s, 120, Vec3::ZERO);
        let last = f.last().unwrap();
        assert!(last.bob_up.abs() < 1e-3 && last.bob_left.abs() < 1e-3 && last.bob_ang.length() < 1e-2, "{last:?}");
        let c = R301_HIP.bob_cycle;
        assert!([0.0, c, 2.0 * c].iter().any(|r| (last.phase - r).abs() < 1e-3), "phase {}", last.phase);
        let mut still = Sway::default();
        let f = walk(&mut still, 60, Vec3::ZERO);
        assert!(f.iter().all(|s| s.pos == Vec3::ZERO && s.ang == Vec3::ZERO && s.bob_up == 0.0), "{:?}", f.last());
    }

    /// Sliding (`m_sliding`): the bob reads speed 0 and settles as when standing, however fast the
    /// slide; the move sway still reads the velocity.
    #[test]
    fn sliding_stops_the_bob() {
        let mut walked = Sway::default();
        walk(&mut walked, 37, Vec3::new(173.5, 0.0, 0.0));
        let (mut slid, mut stood) = (walked, walked);
        for _ in 0..30 {
            slid.step(&SwayIn { dt: DT, velocity: Vec3::new(450.0, 0.0, 0.0), grounded: true, sliding: true, ..Default::default() }, &R301_HIP, &R301_ZOOMED);
            stood.step(&SwayIn { dt: DT, grounded: true, ..Default::default() }, &R301_HIP, &R301_ZOOMED);
            assert_eq!((slid.phase, slid.bob_up, slid.bob_left, slid.bob_ang), (stood.phase, stood.bob_up, stood.bob_left, stood.bob_ang));
        }
        assert!(slid.pos.z < stood.pos.z - 0.1, "move sway {} vs {}", slid.pos.z, stood.pos.z);
    }

    /// Walking forward: the gun sinks to the clamp (forward 173.5 u/s × dt × -0.5 = -1.45, clamped
    /// -0.6) and back a little (-0.29), easing in at gain 2.5.
    #[test]
    fn walking_forward_sways_down_and_back() {
        let mut s = Sway::default();
        let f = walk(&mut s, 600, Vec3::new(173.5, 0.0, 0.0));
        let p = f.last().unwrap().pos;
        assert!((p.z + 0.6).abs() < 1e-3 && (p.x + 173.5 * DT * 0.1).abs() < 1e-3 && p.y.abs() < 1e-6, "{p}");
        // after 1/2.5 s it is 63% there
        let at = f[(60.0 / 2.5) as usize - 1].pos.z;
        assert!((at / -0.6 - (1.0 - (-1.0f32).exp())).abs() < 0.02, "{at}");
    }

    /// Turning left at 90°/s: yaw target -2.5 × 4.5 clamped to -2.5 (the gun turns right, lags), the
    /// gun moves left 0.5 (clamped) and rolls 4 (clamped); turning right the opposite.
    #[test]
    fn turning_lags_and_clamps() {
        let mut s = Sway::default();
        for _ in 0..240 {
            s.step(&SwayIn { dt: DT, turn: Vec3::new(0.0, 90.0 * DT, 0.0), grounded: true, ..Default::default() }, &R301_HIP, &R301_ZOOMED);
        }
        assert!((s.ang.y + 2.5).abs() < 1e-3 && (s.ang.z - 4.0).abs() < 1e-3 && (s.pos.y - 0.5).abs() < 1e-3, "{s:?}");
        let mut s = Sway::default();
        for _ in 0..240 {
            s.step(&SwayIn { dt: DT, turn: Vec3::new(0.0, -90.0 * DT, 0.0), grounded: true, ..Default::default() }, &R301_HIP, &R301_ZOOMED);
        }
        assert!((s.ang.y - 2.5).abs() < 1e-3 && (s.ang.z + 4.0).abs() < 1e-3 && (s.pos.y + 0.5).abs() < 1e-3, "{s:?}");
    }

    /// Aiming: the zoomed set, no translation sway, the yaw sway clamped to ±0.0275°; the pivot
    /// blends in over 0.2 s once fully zoomed and drops back at once.
    #[test]
    fn aiming_uses_the_zoomed_set() {
        let mut s = Sway::default();
        for _ in 0..240 {
            s.step(&SwayIn { dt: DT, turn: Vec3::new(0.0, 90.0 * DT, 0.0), velocity: Vec3::new(150.0, 0.0, 0.0), grounded: true, ads: 1.0, ..Default::default() }, &R301_HIP, &R301_ZOOMED);
        }
        assert!(s.pos.length() < 1e-4 && (s.ang.y + 0.0275).abs() < 1e-4, "{s:?}");
        assert_eq!(s.pivot, 1.0);
        let mut s = Sway::default();
        let ads = SwayIn { dt: DT, ads: 1.0, ..Default::default() };
        for k in 1..=12 {
            s.step(&ads, &R301_HIP, &R301_ZOOMED);
            assert!((s.pivot - (k as f32 * DT / 0.2).min(1.0)).abs() < 1e-5);
        }
        s.step(&SwayIn { dt: DT, ads: 0.9, ..Default::default() }, &R301_HIP, &R301_ZOOMED);
        assert_eq!(s.pivot, 0.0);
    }

    /// The matrix turns about the pivot: the pivot itself only moves by the translation.
    #[test]
    fn matrix_turns_about_the_pivot() {
        let mut s = Sway::default();
        for _ in 0..60 {
            s.step(&SwayIn { dt: DT, turn: Vec3::new(1.0, 1.5, 0.0), grounded: true, ..Default::default() }, &R301_HIP, &R301_ZOOMED);
        }
        let pivot = (Vec3::new(6.5, -2.6, -7.1), Quat::from_rotation_x(std::f32::consts::PI));
        let (r, t) = s.matrix(pivot, pivot);
        let moved = r * pivot.0 + t;
        assert!((moved - (pivot.0 + s.pos + Vec3::new(0.0, s.bob_left, s.bob_up))).length() < 1e-4, "{moved}");
        assert!(r.angle_between(Quat::IDENTITY) > 0.01);
    }
}
