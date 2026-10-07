//! First person (ini `first_person = 1`, D-017): Fuse as Apex shows him, from his own eyes.
//!
//! The camera (camera.rs) sits at Apex's stand view height above his feet; he faces where it looks.
//! His arms and gun are a view model, one of two:
//!
//! - Apex's own (`fuse_pov.anim` in the mod folder and armour model 998 installed, T011): the
//!   first-person arms and R-301 with their ptpov animations, posed by spike/pov.rs in the camera's
//!   frame and written onto carrier bones (`view_model`, spike/pose.rs).
//! - Otherwise (v1, `m0-fp`): Apex's third-person ADS idle pose (`fuse_idle_rifle_ADS`, baked by
//!   tools/retarget) is played, then the upper body from the hands' common ancestor up is moved as
//!   one rigid piece so that the R-301's sight sits where it should in the camera's frame: aiming,
//!   the sight centre (`ADS_CENTER_SIGHT_R301`) on the line of sight with the gun level; from the
//!   hip, low and to the right (tuned by eye in game, `fp`). Only the arms piece is worn.
//!
//! Either way the Tarnished's own body stays hidden (spike/armor.rs).
//!
//! Hands off while the game drives him (fog gates, doors, levers, ladders): he keeps the facing the
//! game gives him; with v1 the game's animation plays, Apex's view model stays posed.

use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicU64, Ordering};
use std::time::Instant;

use eldenring::cs::{CSTaskGroupIndex, WorldChrMan};
use eldenring::rotation::Quaternion;
use fromsoftware_shared::FromStatic;
use glam::{Mat3, Quat, Vec3};

use crate::camera::{self, Mode};
use crate::{log, spike, state};

/// The pose for the gun at the eye.
const CLIP: &str = "fuse_idle_rifle_ADS";

/// Apex's stand view height (player settings `viewheight` 60 units); the model scale of T005
/// (0.0254 m per unit x 0.97).
const STAND_VIEW: f32 = 60.0;
const UNIT: f32 = 0.0254 * 0.970_002_1;
/// The movement controller's view height in units while it moves Fuse (crouch and slide ease it,
/// spec section 12), as f32 bits; 0: standing.
static VIEW_HEIGHT: AtomicU32 = AtomicU32::new(0);

/// The R-301 relative to ER's `R_Hand` (T008 grip.json `gun_root_to_R_Hand_er`: rows, metres; it
/// takes gun coordinates already scaled by `UNIT` with Z flipped).
const GRIP: [[f32; 4]; 3] = [
    [0.002_717_885, 0.161_983_29, -0.986_789_2, 0.046_175_09],
    [-0.074_928_16, 0.984_052_96, 0.161_327_7, -0.004_250_647],
    [0.997_185_5, 0.073_499_9, 0.014_811_661, 0.025_982_934],
];
/// The R-301's `ADS_CENTER_SIGHT_R301` attachment (on `def_c_base`, QC, Apex units).
const SIGHT: [f32; 3] = [0.0, 6.063_558, 20.820_164];

/// The gun as drawn sits this far (m) below where `GRIP` puts it, along its own up (measured in
/// game 2026-10-04: the front sight 30 px low at 60 and 70 cm aiming and from the hip; cause not
/// known).
const GRIP_DROP: f32 = 0.015;

/// Where the sight goes in the camera's frame (metres): aiming, straight ahead at `ADS_DIST` (the
/// eye behind the receiver, the front sight in its ears at the centre); from the hip, right, down
/// and ahead, the muzzle turned in (negative `HIP_YAW`, degrees) and rolled by `HIP_ROLL`. Tuned by
/// eye in game with `fp` (2026-10-04) to put the hip sight about 60 % across and down the screen.
const ADS_DIST: f32 = 0.70;
const HIP_RIGHT: f32 = 0.08;
const HIP_DOWN: f32 = 0.05;
const HIP_FWD: f32 = 0.35;
const HIP_YAW: f32 = -6.0;
const HIP_ROLL: f32 = -6.0;

static POSED: AtomicBool = AtomicBool::new(false);

/// Dev tuning (`fp` command), f32 bits, NaN = the constants: ADS distance, hip right / down /
/// forward (cm), hip yaw / roll (degrees), an orbit for looking at the rig from outside (pull back,
/// cm; angle, degrees), and the grip drop (cm).
const KEYS: [&str; 9] = ["ads", "right", "down", "fwd", "yaw", "roll", "back", "angle", "drop"];
static TUNE: [AtomicU32; 9] = [const { AtomicU32::new(0x7fc0_0000) }; 9];

fn tuned(i: usize, default: f32) -> f32 {
    let v = f32::from_bits(TUNE[i].load(Ordering::Relaxed));
    if v.is_nan() { default } else { v }
}

fn ads_dist() -> f32 {
    tuned(0, ADS_DIST * 100.0) / 100.0
}

/// The debug orbit (`fp` back and angle): metres behind the eye and degrees around it, if set.
pub fn orbit() -> Option<(f32, f32)> {
    let back = tuned(6, 0.0) / 100.0;
    (back > 0.01).then(|| (back, tuned(7, 0.0)))
}

/// Dev channel `fp [key=value ...|reset]`, keys `ads right down fwd yaw roll back angle drop` (cm,
/// degrees).
pub fn tune(args: &[&str]) -> String {
    for a in args {
        if *a == "reset" {
            for t in &TUNE {
                t.store(0x7fc0_0000, Ordering::Relaxed);
            }
        } else if let Some((k, v)) = a.split_once('=') {
            match (KEYS.iter().position(|n| *n == k), v.parse::<f32>()) {
                (Some(i), Ok(v)) => TUNE[i].store(v.to_bits(), Ordering::Relaxed),
                _ => return format!("bad {a}; keys {KEYS:?}"),
            }
        }
    }
    let (s, f) = last_sight().map_or((String::from("-"), String::from("-")), |(s, f)| (format!("{s:.3}"), format!("{f:.3}")));
    format!(
        "ads {:.0} right {:.0} down {:.0} fwd {:.0} yaw {:.1} roll {:.1} drop {:.1} (cm, deg); orbit {:?}; ads frac {:.2}; sight {s} dir {f}",
        tuned(0, ADS_DIST * 100.0),
        tuned(1, HIP_RIGHT * 100.0),
        tuned(2, HIP_DOWN * 100.0),
        tuned(3, HIP_FWD * 100.0),
        tuned(4, HIP_YAW),
        tuned(5, HIP_ROLL),
        tuned(8, GRIP_DROP * 100.0),
        orbit(),
        camera::ads_frac()
    )
}

pub fn enabled() -> bool {
    camera::mode() == Mode::First
}

/// The eye above the feet (m).
pub fn eye_height() -> f32 {
    match VIEW_HEIGHT.load(Ordering::Relaxed) {
        0 => STAND_VIEW * UNIT,
        bits => f32::from_bits(bits) * UNIT,
    }
}

/// The view height (Apex units) from the movement controller; None when it lets go.
pub fn set_view_height(units: Option<f32>) {
    VIEW_HEIGHT.store(units.filter(|u| *u > 0.0).map_or(0, f32::to_bits), Ordering::Relaxed);
}

/// Events the game drives (er-mario's `game_driven`; as spike/kcc.rs).
fn game_driven(anim: i32) -> bool {
    (60000..70000).contains(&anim) || (28000..29000).contains(&anim) || (51100..51200).contains(&anim)
}

/// Dev `fpdbg`: frames left to log the yaws of the camera, physics and drawn model (turn lag).
static DEBUG_FRAMES: AtomicU32 = AtomicU32::new(0);

pub fn debug(args: &[&str]) -> String {
    let n = args.first().and_then(|a| a.parse().ok()).unwrap_or(60);
    DEBUG_FRAMES.store(n, Ordering::Relaxed);
    format!("logging {n} frames of yaws")
}

/// Yaw (degrees) of a forward vector, as the HUD's compass (atan2(x, z)).
fn yaw(v: Vec3) -> f32 {
    v.x.atan2(v.z).to_degrees()
}

fn log_yaws(tag: &str) {
    if DEBUG_FRAMES.load(Ordering::Relaxed) == 0 {
        return;
    }
    let Some(p) = (unsafe { WorldChrMan::instance() }).ok().and_then(|w| w.main_player.as_ref()) else { return };
    let q = p.chr_ins.modules.physics.orientation;
    let phys = Quat::from_xyzw(q.0, q.1, q.2, q.3) * Vec3::NEG_Z;
    let m = &p.chr_ins.chr_ctrl.model_matrix;
    let drawn = -Vec3::new(m.2.0, m.2.1, m.2.2);
    let cam = camera::eye_view().map_or(Vec3::NAN, |v| v.1);
    log(format!("fpdbg {tag}: camera {:.2} physics {:.2} model {:.2}", yaw(cam), yaw(phys), yaw(drawn)));
}

/// Once a frame (`dt` seconds), after the movement controller's step.
pub fn update(dt: f32) {
    if DEBUG_FRAMES.load(Ordering::Relaxed) > 0 {
        log_yaws("frame");
        DEBUG_FRAMES.fetch_sub(1, Ordering::Relaxed);
    }
    if !enabled() || !state::in_world() {
        return;
    }
    let Some(player) = (unsafe { WorldChrMan::instance_mut() }).ok().and_then(|w| w.main_player.as_deref_mut()) else { return };
    let anim = state::current_anim(player);
    let hands_off = game_driven(anim) || player.chr_ins.modules.data.hp <= 0 || !crate::fe::in_play_view();
    // Apex's view model stays posed even then: its mesh is bound for the carriers' poses only, so
    // the game's own animation would draw it as a tangle
    let view_model = spike::pov::available() && spike::pov::model_installed();
    if view_model {
        spike::pov::step(dt, &view_model_inputs());
    }
    step_fx(dt);
    if hands_off && !view_model {
        if POSED.swap(false, Ordering::Relaxed) {
            spike::pose::stop();
        }
        return;
    }
    let Some((_, fwd, _, _)) = camera::eye_view() else { return };
    if !POSED.swap(true, Ordering::Relaxed) {
        match spike::pose::play(CLIP) {
            Ok(()) => log(format!("first person: {CLIP} on")),
            Err(e) => {
                log(format!("first person: no {CLIP}: {e}"));
                POSED.store(false, Ordering::Relaxed);
            }
        }
    }
    if hands_off {
        return;
    }
    // facing where the camera looks (model forward is -Z: spike/kcc.rs)
    if let Some(flat) = Vec3::new(fwd.x, 0.0, fwd.z).try_normalize() {
        let q = Quat::from_rotation_y((-flat.x).atan2(-flat.z));
        player.chr_ins.modules.physics.orientation = Quaternion(q.x, q.y, q.z, q.w);
    }
}

/// Rotation taking (Z forward, Y up) to `fwd`, `up` (up made square to forward).
fn frame(fwd: Vec3, up: Vec3) -> Option<Quat> {
    let f = fwd.try_normalize()?;
    let r = up.cross(f).try_normalize()?;
    Some(Quat::from_mat3(&Mat3::from_cols(r, f.cross(r), f)))
}

/// The sight centre (as drawn: `GRIP_DROP`), the barrel's direction and the gun's up in `R_Hand`'s
/// frame.
fn gun_in_hand() -> (Vec3, Vec3, Vec3) {
    let m = |v: Vec3, w: f32| Vec3::new(GRIP[0][0] * v.x + GRIP[0][1] * v.y + GRIP[0][2] * v.z + GRIP[0][3] * w, GRIP[1][0] * v.x + GRIP[1][1] * v.y + GRIP[1][2] * v.z + GRIP[1][3] * w, GRIP[2][0] * v.x + GRIP[2][1] * v.y + GRIP[2][2] * v.z + GRIP[2][3] * w);
    let up = m(Vec3::Y, 0.0).normalize();
    let sight = m(Vec3::new(SIGHT[0], SIGHT[1], -SIGHT[2]) * UNIT, 1.0) - up * (tuned(8, GRIP_DROP * 100.0) / 100.0);
    // gun +Z (towards the muzzle) is -Z after the flip
    (sight, m(Vec3::NEG_Z, 0.0).normalize(), up)
}

/// The sight and barrel direction (world) as last placed, for `fp` and the HUD's debug marks.
static LAST: Mutex<Option<(Vec3, Vec3)>> = Mutex::new(None);

pub fn last_sight() -> Option<(Vec3, Vec3)> {
    *LAST.lock().unwrap_or_else(|e| e.into_inner())
}

/// The task group in which the renderer takes the skeleton's pose (`LocationUpdate_PrePhysics`,
/// group id 0x9000_0000 + index: measured in game 2026-10-04 with `fpgroup`, a 5 cm offset written
/// there shows and in any of the 15 later groups doesn't). It runs before this frame's physics and
/// camera.
const DRAWN_GROUP: u32 = 0x9000_0000 + CSTaskGroupIndex::LocationUpdate_PrePhysics as u32;

/// ChrCtrl's model matrix (model -> world: the physics transform after the game's easing, which
/// trails it while he moves and turns) as it was when the renderer took the pose, and when.
static DRAWN: Mutex<Option<(Mat3, Vec3, Instant)>> = Mutex::new(None);

/// The first-person eye in the world where the drawn body puts it: Apex's view height above the
/// drawn model's origin (its feet). The camera sits here, so the view model drawn with that body
/// stays where it was posed even while the easing moves the body under the camera.
pub fn drawn_eye() -> Option<Vec3> {
    let d = DRAWN.lock().unwrap_or_else(|e| e.into_inner());
    let (axes, origin, at) = d.as_ref()?;
    (at.elapsed().as_secs_f32() < 0.2).then(|| *origin + *axes * Vec3::new(0.0, eye_height(), 0.0))
}

/// The view model's frame in model space: the eye's, turned by the punch (viewfx.rs
/// `view_model_turn`) (rotation taking x left, y up, z backward to the model's axes; position:
/// Apex's view height above the feet), and the model -> world matrix as drawn.
fn eye_in_model() -> Option<(Quat, Vec3, Mat3, Vec3)> {
    let (_, fwd, right, up) = camera::eye_view()?;
    let [_, up, fwd] = crate::viewfx::turned(right, up, fwd, crate::viewfx::view_model_turn());
    let p = (unsafe { WorldChrMan::instance() }).ok()?.main_player.as_ref()?;
    let m = &p.chr_ins.chr_ctrl.model_matrix;
    let row = |v: &fromsoftware_shared::F32Vector4| Vec3::new(v.0, v.1, v.2);
    let axes = Mat3::from_cols(row(&m.0), row(&m.1), row(&m.2));
    let origin = row(&m.3);
    if axes.determinant().abs() < 1e-6 || !origin.is_finite() {
        return None;
    }
    if spike::pose::current_group() == DRAWN_GROUP {
        *DRAWN.lock().unwrap_or_else(|e| e.into_inner()) = Some((axes, origin, Instant::now()));
    }
    let inv = axes.inverse();
    // the mirrored camera frame (x left, y up, z backward; spike/pov.rs `mirror`): the model space
    // is left-handed, so `frame`'s first axis (up x forward) is the eye's right; turned half way
    // round the up axis, it is left and the forward axis backward
    let rot = frame(inv * fwd, inv * up)? * Quat::from_rotation_y(std::f32::consts::PI);
    Some((rot, Vec3::new(0.0, eye_height(), 0.0), axes, origin))
}

/// What drives Apex's view model: the zoom, the gun and how Fuse moves (spike/kcc.rs; speed in Apex
/// units/s).
fn view_model_inputs() -> spike::pov::Inputs {
    let g = spike::gun::hud();
    let cr = spike::chargerifle::hud();
    let (cr_charge, cr_discharge) = spike::chargerifle::view();
    spike::pov::Inputs {
        cr_shots: cr.as_ref().map_or(0, |c| c.shots),
        cr_reload: cr.as_ref().and_then(|c| c.reload.map(|r| (r, c.reload_empty))),
        cr_discharge,
        cr_charge,
        ads: camera::ads_frac(),
        shots: g.as_ref().map_or(0, |g| g.shots),
        reload: g.as_ref().and_then(|g| g.reload.map(|r| (r, g.reload_empty))),
        moving: spike::kcc::locomotion().map(|l| {
            let m = spike::pov::Moving {
                sprinting: l.sprinting,
                sliding: l.sliding,
                crouched: l.crouched,
                duck_frac: l.duck_frac,
                speed: l.speed / UNIT,
                jumped: l.events.jumped,
                landed: l.events.landed.is_some(),
                duck_started: l.events.duck_started,
                unduck_started: l.events.unduck_started,
            };
            (m, l.frame)
        }),
        // the eye's frame (the view before the camera effects) for the bob and sway
        eye: camera::eye_view().map(|(_, f, r, u)| (f, -r, u)),
        velocity: spike::kcc::locomotion().map(|l| (l.velocity / UNIT, l.grounded)),
    }
}

/// The movement controller's frame whose events the camera effects took last.
static FX_FRAME: AtomicU64 = AtomicU64::new(u64::MAX);

/// Apex's camera effects (viewfx.rs) from how Fuse moves and the view model's camera bone.
fn step_fx(dt: f32) {
    let Some((_, fwd, right, _)) = camera::eye_view() else { return };
    let flat = |v: Vec3| Vec3::new(v.x, 0.0, v.z).normalize_or_zero();
    let loco = spike::kcc::locomotion();
    // the controller's events stay up until its next step: act on them once
    let fresh = loco.is_some_and(|l| FX_FRAME.swap(l.frame, Ordering::Relaxed) != l.frame);
    let i = crate::viewfx::Inputs {
        velocity: loco.map_or(Vec3::ZERO, |l| l.velocity / UNIT),
        forward: flat(fwd),
        right: flat(right),
        grounded: loco.is_some_and(|l| l.grounded),
        crouched: loco.is_some_and(|l| l.crouched),
        sliding: loco.is_some_and(|l| l.sliding),
        slide_long_jump: loco.is_some_and(|l| l.slide_long_jump),
        jumped: fresh && loco.is_some_and(|l| l.events.jumped),
        landed: loco.filter(|_| fresh).and_then(|l| l.events.landed).map(|d| (d.speed, d.crouched)),
        bone: spike::pov::drawn_camera_turn(),
        ads: camera::ads_frac(),
    };
    crate::viewfx::step(dt, &i);
    if spike::pov::tracing() {
        log(format!(
            "fp fx: eye {:.3} m | flat view heading {:.2}° | velocity along / right of the view {:.0} {:.0} | {}",
            eye_height(),
            i.forward.x.atan2(i.forward.z).to_degrees(),
            i.velocity.dot(i.forward),
            i.velocity.dot(i.right),
            crate::viewfx::describe(fwd)
        ));
    }
}

/// Apex's view model (spike/pov): the carrier bones' model-space transforms this frame, in the
/// order of `pov::carrier_names`, placed at the eye, whether each shows (FPOV v2's groups: the
/// R-301 away, a prop out) and its scale (1 but for the pad on the ground). The jump pad standing
/// on the ground (R4) takes the pad's carriers when the hand-held one is not out: they are placed
/// in the world, not at the eye. None without a first-person camera or the pack.
pub fn view_model() -> Option<Vec<(Vec3, Quat, bool, Vec3)>> {
    if !enabled() {
        return None;
    }
    let (rot, eye, axes, origin) = eye_in_model()?;
    *FRAME.lock().unwrap_or_else(|e| e.into_inner()) = Some((rot, eye, axes, origin));
    log_yaws("pose");
    let bones = spike::pov::pose()?;
    // for `fp` and the HUD's debug marks: the line of sight
    *LAST.lock().unwrap_or_else(|e| e.into_inner()) = Some((origin + axes * (eye - rot * Vec3::Z * 0.70), (axes * (rot * Vec3::NEG_Z)).normalize_or_zero()));
    *BONES.lock().unwrap_or_else(|e| e.into_inner()) = bones.iter().map(|b| origin + axes * (eye + rot * b.2)).collect();
    let mut out: Vec<(Vec3, Quat, bool, Vec3)> = bones.into_iter().map(|(t, r, _, shown)| (eye + rot * t, (rot * r).normalize(), shown, Vec3::ONE)).collect();
    let mut drawn = false;
    if let Some(w) = spike::octane::pad_world()
        && let Some(frame) = pad_frame(&w, axes, origin)
        && let Some(cs) = spike::pov::world_pad(frame, w.age, w.bounce)
        && !cs.iter().any(|(i, ..)| out.get(*i).is_some_and(|o| o.2))
    {
        for (i, t, r, s) in cs {
            if let Some(o) = out.get_mut(i) {
                *o = (t, r, true, s);
            }
        }
        drawn = true;
    }
    WORLD_PAD.store(drawn, std::sync::atomic::Ordering::Relaxed);
    // the thrown grenades (U9, T022 groups 7/8): the newest two where they fly or lie
    let mut thrown = 0;
    for (k, (at, spin)) in spike::grenade::props().into_iter().enumerate() {
        let Some(&group) = spike::pov::THROWN.get(k) else { break };
        let inv = axes.inverse();
        let r = Quat::from_mat3(&(inv * Mat3::from_quat(spin))).normalize();
        let t = inv * (at - origin);
        if !(t.is_finite() && r.is_finite()) {
            continue;
        }
        if let Some(cs) = spike::pov::world_rigid(group, spike::pov::PovXf { t, r }) {
            for (i, t, r, s) in cs {
                if let Some(o) = out.get_mut(i) {
                    *o = (t, r, true, s);
                }
            }
            thrown += 1;
        }
    }
    WORLD_GRENADES.store(thrown, std::sync::atomic::Ordering::Relaxed);
    Some(out)
}

/// How many thrown grenades were drawn as models this frame (the HUD's red dots stand in for the
/// others).
static WORLD_GRENADES: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

pub fn world_grenades_drawn() -> usize {
    WORLD_GRENADES.load(std::sync::atomic::Ordering::Relaxed)
}

/// The view model's frame as last placed (the eye's rotation and position in model space, model to
/// world): `muzzle_world`.
static FRAME: Mutex<Option<(Quat, Vec3, Mat3, Vec3)>> = Mutex::new(None);

/// The shown weapon's muzzle in the world as the view model was last placed (the Charge Rifle's
/// beam starts there: hud/beam.rs). None without the view model.
pub fn muzzle_world() -> Option<Vec3> {
    let m = spike::pov::muzzle_view()?;
    let (rot, eye, axes, origin) = (*FRAME.lock().unwrap_or_else(|e| e.into_inner()))?;
    Some(origin + axes * (eye + rot * m))
}

/// Whether the jump pad on the ground was drawn as a model this frame (else the HUD rings it).
static WORLD_PAD: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

pub fn world_pad_drawn() -> bool {
    WORLD_PAD.load(std::sync::atomic::Ordering::Relaxed)
}

/// The pad's `jx_c_origin` in model space (metres): at its landing point, its y along the surface's
/// up, its x along the heading it was tossed along (flattened onto the surface), z = x cross y (a
/// proper rotation in the left-handed model space, as the mirrored view model's frames are).
fn pad_frame(w: &spike::octane::PadWorld, axes: Mat3, origin: Vec3) -> Option<spike::pov::PovXf> {
    let inv = axes.inverse();
    let up = (inv * w.up).normalize_or_zero();
    let heading = inv * Vec3::new(w.yaw.sin(), 0.0, w.yaw.cos());
    let x = (heading - up * heading.dot(up)).normalize_or_zero();
    if up == Vec3::ZERO || x == Vec3::ZERO {
        return None;
    }
    let r = Quat::from_mat3(&Mat3::from_cols(x, up, x.cross(up))).normalize();
    let t = inv * (w.at - origin);
    (t.is_finite() && r.is_finite()).then_some(spike::pov::PovXf { t, r })
}

/// The view model's Apex bones (world) as last posed, for the HUD's debug marks.
static BONES: Mutex<Vec<Vec3>> = Mutex::new(Vec::new());

pub fn view_model_bones() -> Vec<Vec3> {
    BONES.lock().unwrap_or_else(|e| e.into_inner()).clone()
}

/// The rigid move (translation, rotation; model space) for the upper body, given `R_Hand` as posed
/// (model space), that puts the gun's sight where the first-person camera wants it. None when
/// there is no first-person camera this frame.
pub fn correction(hand: (Vec3, Quat)) -> Option<(Vec3, Quat)> {
    if !enabled() {
        return None;
    }
    let (eye, fwd, right, up) = camera::eye_view()?;
    let p = (unsafe { WorldChrMan::instance() }).ok()?.main_player.as_ref()?;
    // model -> world as drawn: ChrCtrl's model matrix (the physics transform after the game's
    // easing, which trails it while he moves and turns); rows: the model's axes, then its origin
    let m = &p.chr_ins.chr_ctrl.model_matrix;
    let row = |v: &fromsoftware_shared::F32Vector4| Vec3::new(v.0, v.1, v.2);
    let axes = Mat3::from_cols(row(&m.0), row(&m.1), row(&m.2));
    let origin = row(&m.3);
    if axes.determinant().abs() < 1e-6 || !origin.is_finite() {
        return None;
    }
    let inv = axes.inverse();
    // the camera in model space
    let (c, f, r, u) = (inv * (eye - origin), inv * fwd, inv * right, inv * up);
    // the gun as posed
    let (s_h, f_h, u_h) = gun_in_hand();
    let s = hand.0 + hand.1 * s_h;
    let now = frame(hand.1 * f_h, hand.1 * u_h)?;
    // where it should be
    let ads = camera::ads_frac();
    let hip = 1.0 - ads;
    let at = c
        + f * (ads_dist() * ads + tuned(3, HIP_FWD * 100.0) / 100.0 * hip)
        + r * (tuned(1, HIP_RIGHT * 100.0) / 100.0 * hip)
        - u * (tuned(2, HIP_DOWN * 100.0) / 100.0 * hip);
    let turn = Quat::from_axis_angle(u.normalize_or(Vec3::Y), (tuned(4, HIP_YAW) * hip).to_radians())
        * Quat::from_axis_angle(f.normalize_or(Vec3::NEG_Z), (tuned(5, HIP_ROLL) * hip).to_radians());
    let want = frame(turn * f, turn * u)?;
    let rot = (want * now.inverse()).normalize();
    let t = at - rot * s;
    if !(t.is_finite() && rot.is_finite()) {
        return None;
    }
    *LAST.lock().unwrap_or_else(|e| e.into_inner()) = Some((origin + axes * at, (axes * (turn * f)).normalize_or_zero()));
    Some((t, rot))
}
