//! Fuse's R-301 Carbine, M0 prototype (D-014): fire / aim / reload from the game's own action
//! inputs (so pad and mouse both work), a hitscan shot from the camera against enemy hit
//! cylinders, and every hit goes through the S6 damage bridge (`combat::shoot`).
//!
//! Weapon numbers from the local Apex export (`apex-data/fuse_data.json`, `mp_weapon_rspn101`):
//! damage_near/far/very_far_value 15, fire_rate 13.5, ammo_clip_size 21, reload_time 2.4,
//! reloadempty_time 3.2, damage_headshot_scale 1.3, damage_leg_scale 0.75,
//! spread_stand_hip 3, spread_stand_ads 0.
//!
//! Spread (HUD v3, user to-do U2 "the crosshair should match Apex"): the R-301's own spread by how
//! Fuse moves (movement controller, spike/kcc.rs) — hip: stand 3, moving 6.6, sprint 8.4, crouch
//! 2.4, air 8.4; aimed: 0, crouch 0, air 6 — reached at spread_moving_increase_rate 3 going up and
//! spread_moving_decay_rate 30 going down, plus a kick per shot (spread_kick_on_fire_*_hip 0.2, up
//! to spread_max_kick_* 2 / 1.5 / 3) that decays at spread_decay_rate 100 after spread_decay_delay
//! 0.25 s. 推断: the rates read as degrees per second; "moving" is above 0.5 m/s; sprinting hides
//! the crosshair (crosshair_tri's isSprinting input; T009 rule).
//!
//! M0 approximations, to be replaced: the projectile (projectile_launch_speed 29000, gravity on)
//! is a hitscan ray; walls stop it through the game's own ray cast (`CSPhysWorld::cast_ray`, the
//! map filter er-mario's ground probes use); head and leg zones
//! are fixed fractions of the target's hit height; the hip spread is read as a cone half-angle in
//! degrees (its unit in Apex is to be confirmed).

use std::sync::Mutex;
use std::sync::atomic::{AtomicU64, Ordering};

use eldenring::cs::{CSCamera, CSHavokMan, ChrIns, FieldInsHandle, WorldChrMan};
use eldenring::position::{HavokPosition, PositionDelta};
use fromsoftware_shared::FromStatic;
use glam::Vec3;

use crate::{log, paths, state};

// The Wingman in the R-301's place (`apex-data/export/weapon/mp_weapon_wingman.txt`): `is_semi_auto`
// 1, damage_near/far/very_far_value 50, fire_rate 2.8, ammo_clip_size 5, reload_time and
// reloadempty_time 2.1, damage_headshot_scale 1.5, damage_leg_scale 0.9. (The R-301's were 15, 13.5,
// 21, 2.4 / 3.2, 1.3, 0.75, automatic.)
const DAMAGE: f32 = 50.0;
const FIRE_RATE: f32 = 2.8;
const CLIP: u32 = 5;
const RELOAD: f32 = 2.1;
const RELOAD_EMPTY: f32 = 2.1;
const HEAD_SCALE: f32 = 1.5;
const LEG_SCALE: f32 = 0.9;
/// spread_*_hip / spread_*_ads: stand, moving (stand_hip_run), sprint, crouch, air.
const SPREAD_HIP: [f32; 5] = [2.4, 3.0, 4.0, 1.5, 6.0];
const SPREAD_ADS: [f32; 5] = [0.0, 0.0, 0.0, 0.0, 2.0];
const SPREAD_UP: f32 = 5.5;
const SPREAD_DOWN: f32 = 12.0;
/// spread_kick_on_fire_*_hip and spread_max_kick_*_hip: stand, crouch, air (the ADS ones are 0).
const KICK_HIP: [f32; 3] = [2.5, 2.0, 3.0];
const KICK_MAX_HIP: [f32; 3] = [5.5, 3.0, 4.5];
const KICK_DELAY: f32 = 0.26;
const KICK_DECAY: f32 = 11.0;
/// The shot's view kick, chargerifle.rs's rule with the Wingman's numbers: (base, random, inner
/// exclude, soft scale, hard scale) for pitch and yaw; roll (base, random min, random max, soft, hard).
const VIEW_KICK_PITCH: [f32; 5] = [-4.4, 0.8, 0.0, 0.65, 0.35];
const VIEW_KICK_YAW: [f32; 5] = [-0.6, 0.5, 0.0, 0.8, 0.4];
const VIEW_KICK_ROLL: [f32; 5] = [0.1, 0.1, 0.15, 0.4, 0.2];
/// The sounds (`--set wingman`): a shot (`fire_sound_2_player_1p` Weapon_Wingman_Fire_1P, every play
/// action), aim in / out, an empty trigger (`sound_dryfire` pistol_dryfire).
const FIRE_SOUNDS: [&str; 4] = ["weapon_wingman_fire_1p", "weapon_wingman_fire_1p_layer1", "weapon_wingman_fire_1p_layer2", "weapon_wingman_fire_1p_layer3"];
const ADS_IN_SOUND: &str = "weapon_wingman_ads_in";
const ADS_OUT_SOUND: &str = "weapon_wingman_ads_out";
const DRY_SOUND: &str = "pistol_dryfire";
/// Above this (m/s) Fuse counts as moving (推断).
const MOVING: f32 = 0.5;
/// Hitscan range (m); Apex's damage_very_far_distance is 5000 units, far beyond any arena here.
const RANGE: f32 = 150.0;
/// Top / bottom share of a target's hit height counted as head / legs.
const HEAD_ZONE: f32 = 0.85;
const LEG_ZONE: f32 = 0.45;
/// er-mario's ray filter for map geometry (lib.rs RAY_FILTER)
const MAP_RAY: u32 = 0x08;

// ChrActions bits (fromsoftware-rs action_request.rs)
const R1: u64 = 1 << 0;
const R2: u64 = 1 << 1;
const L1: u64 = 1 << 2;
const L2: u64 = 1 << 3;
const USE_ITEM: u64 = 1 << 7;
const MAGIC: u64 = (1 << 19) | (1 << 20) | (1 << 33) | (1 << 34);
const GUARD: u64 = 1 << 24;
const KICKS: u64 = (1 << 26) | (1 << 27);
/// What the gun takes from the Tarnished: attacks, guard, spells, kicks and items (Fuse doesn't
/// drink flasks, D-003); movement, rolls, jumps, interact and lock-on stay the game's.
const TAKEN: u64 = R1 | R2 | L1 | L2 | USE_ITEM | MAGIC | GUARD | KICKS;

/// Buttons held this frame (written by `input_task`, read by `update`): fire, aim, reload press.
static HELD: AtomicU64 = AtomicU64::new(0);

/// Sound volume of the gun (times the mixer's master `volume`).
const GUN_VOLUME: f32 = 0.5;
/// Reload sounds at their frames in the Wingman's view model `reload` / `reload_empty`
/// (`wingman_base_v_animRig.qc` AE_CL_PLAYSOUND events, 30 fps; the animation is 89 frames, the
/// same for both). Frames are stretched to the reload's own length.
const RELOAD_SOUNDS: [(&str, f32, bool); 5] = [
    ("wpn_wingman_reload_open", 6.0, false),
    ("wpn_wingman_reload_eject", 22.0, false),
    ("wpn_wingman_reload_insertmag", 53.0, false),
    ("wpn_wingman_reload_close", 68.0, false),
    ("wpn_wingman_reload_handgrab", 75.0, false),
];
const RELOAD_QC_SECONDS: f32 = 88.0 / 30.0;
/// A trigger pull not yet answered by a shot (semi-auto: one shot a pull; a pull during the
/// cooldown fires when it is over).
static PULL: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
/// Whether the reload going on is the empty one (the HUD's).
static RELOAD_IS_EMPTY: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
/// The aim state last frame (ADS sounds on its changes).
static WAS_AIMING: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
/// The trigger last frame: a new pull cancels the shield battery (S3 `+attack`, D-032).
static WAS_FIRING: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

struct Gun {
    /// Movement spread now (degrees) and the kick on top, seconds since the last shot.
    spread: f32,
    kick: f32,
    since_shot: f32,
    ammo: u32,
    cooldown: f32,
    /// seconds left of a reload
    reloading: Option<f32>,
    /// a reload asked for (the key, an empty trigger pull) while an ability had the hands
    reload_wanted: bool,
    shots: u32,
    hits: u32,
    rng: u32,
}

static GUN: Mutex<Gun> = Mutex::new(Gun { spread: 3.0, kick: 0.0, since_shot: 1.0, ammo: CLIP, cooldown: 0.0, reloading: None, reload_wanted: false, shots: 0, hits: 0, rng: 0x9e37_79b9 });

/// What the HUD shows: magazine, reload progress (0..1), aiming, the last hit (when, headshot).
pub struct HudState {
    pub ammo: u32,
    pub clip: u32,
    pub reload: Option<f32>,
    pub aiming: bool,
    pub spread_deg: f32,
    /// Sprinting: Apex hides the crosshair.
    pub sprinting: bool,
    pub last_hit: Option<(std::time::Instant, bool)>,
    /// Shots fired so far (a change is a new shot) and whether the reload is the empty one.
    pub shots: u32,
    pub reload_empty: bool,
    /// U3: the weapon's slot (0 the R-301, 1 the Charge Rifle: weapons.rs) and its charge (0..1)
    pub slot: u8,
    pub charge: Option<f32>,
}
static LAST_HIT: Mutex<Option<(std::time::Instant, bool)>> = Mutex::new(None);

/// One bullet that hit: for the HUD's damage numbers and target health bar.
#[derive(Clone)]
pub struct Hit {
    pub at: std::time::Instant,
    /// Where it hit (world, the camera's space).
    pub pos: Vec3,
    /// Apex damage (before the bridge to ER health).
    pub damage: f32,
    pub head: bool,
    pub target: FieldInsHandle,
    /// U3: the slot of the weapon that fired it (the kill feed's icon)
    pub weapon: u8,
}

/// Where a shot hit a target: its top HEAD_ZONE, its bottom LEG_ZONE, or between.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Zone {
    Head,
    Body,
    Legs,
}

impl Zone {
    fn name(self) -> &'static str {
        match self {
            Zone::Head => "head",
            Zone::Body => "body",
            Zone::Legs => "legs",
        }
    }
}

/// Hits of the last few seconds, oldest first.
static HITS: Mutex<std::collections::VecDeque<Hit>> = Mutex::new(std::collections::VecDeque::new());
/// How long hits are kept for the HUD.
const HIT_KEEP_SECONDS: f32 = 4.0;

/// Another weapon's hit (the frag grenade, spike/grenade.rs) for the HUD's damage numbers and the
/// kill credit (stats.rs).
pub fn record_hit(hit: Hit) {
    let mut h = HITS.lock().unwrap_or_else(|e| e.into_inner());
    h.push_back(hit);
    if h.len() > 64 {
        h.pop_front();
    }
}

/// The gun's buttons as `input_task` last saw them: the trigger held, aiming (read-only; the frag
/// grenade's pin and throw, spike/grenade.rs).
pub fn buttons() -> (bool, bool) {
    let held = HELD.load(Ordering::Relaxed);
    (held & 1 != 0, held & 2 != 0)
}

/// Hits younger than HIT_KEEP_SECONDS, oldest first.
pub fn hits() -> Vec<Hit> {
    let mut h = HITS.lock().unwrap_or_else(|e| e.into_inner());
    while h.front().is_some_and(|x| x.at.elapsed().as_secs_f32() > HIT_KEEP_SECONDS) {
        h.pop_front();
    }
    h.iter().cloned().collect()
}
static RELOAD_TOTAL: Mutex<f32> = Mutex::new(RELOAD);

pub fn hud() -> Option<HudState> {
    if !enabled() || !state::in_world() {
        return None;
    }
    let g = GUN.lock().unwrap_or_else(|e| e.into_inner());
    let total = *RELOAD_TOTAL.lock().unwrap_or_else(|e| e.into_inner());
    // (aiming waits for a drawn weapon: weapons.rs)
    let aiming = super::weapons::aiming(aim_held());
    Some(HudState {
        ammo: g.ammo,
        clip: CLIP,
        reload: g.reloading.map(|left| (1.0 - left / total).clamp(0.0, 1.0)),
        aiming,
        spread_deg: g.spread + g.kick,
        sprinting: super::kcc::locomotion().is_some_and(|l| l.sprinting),
        last_hit: last_hit(),
        shots: g.shots,
        reload_empty: g.reloading.is_some() && RELOAD_IS_EMPTY.load(Ordering::Relaxed),
        slot: 0,
        charge: None,
    })
}

/// Whether the aim button is held (either weapon's).
pub fn aim_held() -> bool {
    HELD.load(Ordering::Relaxed) & 2 != 0
}

/// The last hit of either weapon: when, whether on the head (the hit marker).
pub fn last_hit() -> Option<(std::time::Instant, bool)> {
    *LAST_HIT.lock().unwrap_or_else(|e| e.into_inner())
}

/// U3: a switch puts the R-301 away (weapons.rs): a reload going on is off with its queued sounds
/// (`interrupt_reload`); the magazine stays as it is (full if the reload's AE_WPN_FILLAMMO had
/// come).
pub fn holster_check() {
    if !matches!(super::weapons::phase(), super::weapons::Phase::Holstering { slot: super::weapons::Slot::R301, .. }) {
        return;
    }
    interrupt_reload();
}

pub fn enabled() -> bool {
    static ON: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    *ON.get_or_init(|| paths::flag("gun"))
}

/// ChrIns_PreBehaviorSafe, right after the game turned the pad / mouse into character actions:
/// note what the gun's buttons do and take them away from the Tarnished.
pub fn input_task() {
    if !enabled() || !state::in_world() {
        return;
    }
    let Some(player) = (unsafe { WorldChrMan::instance_mut() }).ok().and_then(|w| w.main_player.as_mut()) else { return };
    let req: &mut eldenring::cs::CSChrActionRequestModule = &mut player.chr_ins.modules.action_request;
    let bits = |a: &mut eldenring::cs::ChrActions| unsafe { &mut *(a as *mut _ as *mut u64) };
    let held = *bits(&mut req.action_requests);
    let pressed = *bits(&mut req.new_action_presses);
    let mut out = 0;
    if held & (R1 | R2) != 0 {
        out |= 1;
    }
    if held & (L1 | L2 | GUARD) != 0 {
        out |= 2;
    }
    if pressed & USE_ITEM != 0 {
        out |= 4;
    }
    // reload presses are edges: keep one until `update` has seen it
    HELD.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |old| Some(out | (old & 4))).ok();
    for a in [&mut req.action_requests, &mut req.new_action_presses, &mut req.queued_action_inputs, &mut req.cancel_ready_actions] {
        *bits(a) &= !TAKEN;
    }
    // (not `disabled_action_inputs`: with those bits set the game stops reporting the buttons in
    // `action_requests` at all, and the trigger went dead; Fuse holds fists instead, armor.rs)
}

/// Dev channel `fire <seconds>`: holds the trigger without a pad (the synthetic pad's RB works
/// too; this one skips the game's input mapping).
pub fn hold_fire(seconds: f32) -> String {
    *DEV_FIRE.lock().unwrap_or_else(|e| e.into_inner()) = Some(std::time::Instant::now() + std::time::Duration::from_secs_f32(seconds));
    format!("trigger held for {seconds} s")
}
static DEV_FIRE: Mutex<Option<std::time::Instant>> = Mutex::new(None);

/// Stops a reload in progress (the shield battery takes the hands: S3 switches weapons, which ends
/// the reload); its sounds go with it, the magazine stays as it was.
pub fn interrupt_reload() {
    let mut g = GUN.lock().unwrap_or_else(|e| e.into_inner());
    if g.reloading.take().is_some() {
        g.reload_wanted = false;
        drop(g);
        for (name, _, _) in RELOAD_SOUNDS {
            crate::audio::stop(name);
        }
        log("gun: reload interrupted");
    }
}

/// Every frame (ChrIns_PostPhysics): fire rate, magazine, reload, and the shots themselves.
pub fn update(dt: f32) {
    if !enabled() || !state::in_world() {
        return;
    }
    let held = HELD.fetch_and(!4, Ordering::Relaxed);
    let dev = DEV_FIRE.lock().unwrap_or_else(|e| e.into_inner()).is_some_and(|t| std::time::Instant::now() < t);
    let (fire, aim, reload) = (held & 1 != 0 || dev, held & 2 != 0, held & 4 != 0);
    // the shield battery (battery.rs): a new trigger pull cancels it (S3 `AttemptCancelHeal` on
    // `+attack`); while it is out the gun neither fires nor reloads
    let was_firing = WAS_FIRING.swap(fire, Ordering::Relaxed);
    let pulled = fire && !was_firing;
    if pulled {
        PULL.store(true, Ordering::Relaxed);
    }
    if pulled && super::battery::busy() {
        super::battery::cancel("fire");
    }
    // U3: the weapon slots (weapons.rs) switch on keys 1 / 2 and run the Charge Rifle while it is
    // out; the R-301 sits out while it is put away, away or coming out
    if super::weapons::update(dt, super::weapons::Trigger { fire, aim, reload }) {
        WAS_AIMING.store(false, Ordering::Relaxed);
        PULL.store(false, Ordering::Relaxed);
        let mut g = GUN.lock().unwrap_or_else(|e| e.into_inner());
        g.cooldown = g.cooldown.max(0.0);
        return;
    }
    if WAS_AIMING.swap(aim, Ordering::Relaxed) != aim {
        crate::audio::play(if aim { ADS_IN_SOUND } else { ADS_OUT_SOUND }, GUN_VOLUME);
    }
    let mut g = GUN.lock().unwrap_or_else(|e| e.into_inner());
    let (target, kick_row) = spread_target(aim);
    let step = if g.spread < target { SPREAD_UP } else { SPREAD_DOWN } * dt;
    g.spread = if g.spread < target { (g.spread + step).min(target) } else { (g.spread - step).max(target) };
    g.since_shot += dt;
    if g.since_shot > KICK_DELAY {
        g.kick = (g.kick - KICK_DECAY * dt).max(0.0);
    }
    g.cooldown = (g.cooldown - dt).max(-1.0 / FIRE_RATE);
    if let Some(left) = g.reloading {
        let left = left - dt;
        let total = *RELOAD_TOTAL.lock().unwrap_or_else(|e| e.into_inner());
        // the magazine is full from the reload's AE_WPN_FILLAMMO on (the HUD's number jumps there,
        // S3: gun-motion spec 6.3); he can't fire before the reload time is up
        if g.ammo < CLIP && 1.0 - left / total >= fill_at(total) {
            g.ammo = CLIP;
            log(format!("gun: magazine filled, {CLIP} rounds"));
        }
        if left <= 0.0 {
            g.reloading = None;
            g.ammo = CLIP;
            log(format!("gun: reloaded, {CLIP} rounds"));
        } else {
            g.reloading = Some(left);
        }
        PULL.store(false, Ordering::Relaxed);
        return;
    }
    if reload && g.ammo < CLIP {
        g.reload_wanted = true;
    }
    // the R-301 is away for an ability (switching to one hand for the stim, the pad's toss:
    // pov/ability.rs); while the left hand holds the injector it fires one-handed but does not
    // reload: a reload asked for then throws the injector now (the stim goes on) and follows it
    // (or for the frag grenade in hand: G to the R-301's pull-out after it, spike/grenade.rs)
    if super::pov::gun_away() || super::battery::busy() || super::grenade::gun_away() {
        g.cooldown = g.cooldown.max(0.0);
        PULL.store(false, Ordering::Relaxed);
        return;
    }
    let left_busy = super::pov::left_busy();
    if g.reload_wanted && g.ammo < CLIP {
        if !left_busy {
            start_reload(&mut g);
            return;
        }
        super::octane::throw_injector();
    }
    // semi-auto: a pull fires once, as soon as the fire rate allows (held, nothing more)
    if g.cooldown > 0.0 || !PULL.load(Ordering::Relaxed) {
        g.cooldown = g.cooldown.max(0.0);
        return;
    }
    PULL.store(false, Ordering::Relaxed);
    g.cooldown = g.cooldown.max(0.0);
    {
        if g.ammo == 0 {
            crate::audio::play(DRY_SOUND, GUN_VOLUME);
            if left_busy {
                // once per trigger pull's worth of shots, until the injector is gone (thrown
                // next frame for the reload)
                g.cooldown += 0.5;
                g.reload_wanted = true;
            } else {
                start_reload(&mut g);
            }
            return;
        }
        g.ammo -= 1;
        FIRE_SOUNDS.iter().for_each(|n| crate::audio::play(n, GUN_VOLUME));
        g.cooldown += 1.0 / FIRE_RATE;
        g.shots += 1;
        let spread = g.spread + g.kick;
        if !aim {
            g.kick = (g.kick + KICK_HIP[kick_row]).min(KICK_MAX_HIP[kick_row]);
        }
        g.since_shot = 0.0;
        let r = (next(&mut g.rng), next(&mut g.rng));
        // the shot goes along the camera with the kick the view does not show, then kicks it
        let out = shoot(spread, r);
        let u = [next(&mut g.rng), next(&mut g.rng), next(&mut g.rng), next(&mut g.rng), next(&mut g.rng), next(&mut g.rng)];
        let (soft, hard) = view_kick(u);
        crate::viewfx::weapon_kick(soft, hard);
        if out.is_some() {
            g.hits += 1;
        }
        if g.shots <= 30 || g.shots % 50 == 0 {
            log(format!(
                "gun: shot {} ({}), ammo {}, {}",
                g.shots,
                if aim { "aimed" } else { "hip" },
                g.ammo,
                out.unwrap_or_else(|| "miss".into())
            ));
        }
    }
}

/// The spread Fuse's movement asks for (degrees) and the kick row (stand, crouch, air).
fn spread_target(aim: bool) -> (f32, usize) {
    let table = if aim { SPREAD_ADS } else { SPREAD_HIP };
    match super::kcc::locomotion() {
        Some(l) if !l.grounded => (table[4], 2),
        Some(l) if l.crouched => (table[3], 1),
        Some(l) if l.sprinting => (table[2], 0),
        Some(l) if l.speed > MOVING => (table[1], 0),
        _ => (table[0], 0),
    }
}

/// How far into a reload the magazine fills: AE_WPN_FILLAMMO in the Wingman's first-person `reload`
/// and `reload_empty` (both frame 62 of 88, `wingman_base_v_animRig.qc`).
fn fill_at(_total: f32) -> f32 {
    62.0 / 88.0
}

/// One shot's view kick (chargerifle.rs `view_kick`'s rule, the Wingman's numbers): the soft part
/// (into the spring's velocity) and the hard part (into its angle), pitch / yaw / roll in degrees;
/// `u` uniforms in 0..1 (pitch, its sign, yaw, its sign, roll, the roll's sign).
fn view_kick(u: [f32; 6]) -> (Vec3, Vec3) {
    let sign = |s: f32| if s < 0.5 { 1.0 } else { -1.0 };
    let pick = |k: [f32; 5], r: f32, s: f32| {
        let (half, inner) = (k[1] * 0.5, k[2] * 0.5);
        k[0] + sign(s) * (inner + (half - inner) * r)
    };
    let pitch = pick(VIEW_KICK_PITCH, u[0], u[1]);
    let yaw = pick(VIEW_KICK_YAW, u[2], u[3]);
    let roll = VIEW_KICK_ROLL[0] + sign(u[5]) * (VIEW_KICK_ROLL[1] + (VIEW_KICK_ROLL[2] - VIEW_KICK_ROLL[1]) * u[4]);
    let soft = Vec3::new(pitch * VIEW_KICK_PITCH[3], yaw * VIEW_KICK_YAW[3], roll * VIEW_KICK_ROLL[3]);
    let hard = Vec3::new(pitch * VIEW_KICK_PITCH[4], yaw * VIEW_KICK_YAW[4], roll * VIEW_KICK_ROLL[4]);
    (soft, hard)
}

fn start_reload(g: &mut Gun) {
    let empty = g.ammo == 0;
    RELOAD_IS_EMPTY.store(empty, Ordering::Relaxed);
    let t = if empty { RELOAD_EMPTY } else { RELOAD };
    g.reloading = Some(t);
    g.reload_wanted = false;
    let stretch = t / RELOAD_QC_SECONDS;
    for (name, frame, bolt) in RELOAD_SOUNDS {
        if empty || !bolt {
            crate::audio::play_in(name, GUN_VOLUME, frame / 30.0 * stretch);
        }
    }
    *RELOAD_TOTAL.lock().unwrap_or_else(|e| e.into_inner()) = t;
    log(format!("gun: reloading ({t} s, {} left in the magazine)", g.ammo));
}

/// Uniform 0..1 from a xorshift.
fn next(s: &mut u32) -> f32 {
    *s ^= *s << 13;
    *s ^= *s >> 17;
    *s ^= *s << 5;
    (*s >> 8) as f32 / (1u32 << 24) as f32
}

/// One Wingman shot (50 per round, head x1.5, legs x0.9, ini `gun_damage_mult`), along the camera
/// with the part of the view kick the view does not show (viewfx.rs).
fn shoot(spread_deg: f32, r: (f32, f32)) -> Option<String> {
    fire_ray(spread_deg, r, crate::viewfx::weapon_aim_offset(), 0, |zone, _| {
        let scale = match zone {
            Zone::Head => HEAD_SCALE,
            Zone::Legs => LEG_SCALE,
            Zone::Body => 1.0,
        };
        // ini `gun_damage_mult` (read fresh; the user's 3 on 2026-10-05), on the Wingman's 50 per round
        DAMAGE * (scale * damage_mult())
    })
}

/// ini `gun_damage_mult`, read fresh (both weapons).
pub(super) fn damage_mult() -> f32 {
    paths::number::<f32>("gun_damage_mult").map_or(1.0, |m| m.max(0.0))
}

/// One shot along the camera's forward direction (inside the spread cone); returns what it hit.
/// `offset` turns that direction first (pitch down, yaw left, degrees: the part of a weapon's view
/// kick the view does not show, viewfx.rs); `weapon` the slot it came from; `damage` the Apex damage
/// for the zone hit at the distance (m).
pub(super) fn fire_ray(spread_deg: f32, r: (f32, f32), offset: Vec3, weapon: u8, damage: impl Fn(Zone, f32) -> f32) -> Option<String> {
    fire_ray_ex(spread_deg, r, offset, weapon, RANGE, true, damage).and_then(|o| o.line)
}

/// What a ray along the camera ended on.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum RayEnd {
    /// a character (hurt when the ray deals damage)
    Target,
    /// the map, or a character's hit behind the map
    Map,
    /// nothing within the range
    Nothing,
}

/// A ray along the camera: the hit's log line (None: no character hit, or not dealing), where it
/// ends (world), and what it ended on.
pub(super) struct RayOut {
    pub line: Option<String>,
    pub end: Vec3,
    pub on: RayEnd,
}

/// `fire_ray` with its end (the Charge Rifle's beam, U3): out to `range` metres; `deal` false only
/// finds the end (the beam drawn between pulses).
pub(super) fn fire_ray_ex(spread_deg: f32, r: (f32, f32), offset: Vec3, weapon: u8, range: f32, deal: bool, damage: impl Fn(Zone, f32) -> f32) -> Option<RayOut> {
    // the camera the player sees: ours over the shoulder when it's on, else the game's
    let (origin, fwd, right, up) = match crate::camera::view() {
        Some(v) => v,
        None => {
            let cam = unsafe { CSCamera::instance() }.ok()?;
            let m = &cam.pers_cam_1.matrix;
            (Vec3::new(m.3.0, m.3.1, m.3.2), Vec3::new(m.2.0, m.2.1, m.2.2), Vec3::new(m.0.0, m.0.1, m.0.2), Vec3::new(m.1.0, m.1.1, m.1.2))
        }
    };
    let (fwd, right, up) = if offset == Vec3::ZERO {
        (fwd, right, up)
    } else {
        let [r, u, f] = crate::viewfx::turned(right, up, fwd, offset);
        (f, r, u)
    };
    let fwd = fwd.normalize_or_zero();
    if fwd == Vec3::ZERO {
        return None;
    }
    // uniform in the cone's disc: angle a around the axis, radius sqrt(r) of the half-angle
    let (a, rad) = (r.0 * std::f32::consts::TAU, r.1.sqrt() * spread_deg.to_radians().tan());
    let dir = (fwd + right * (rad * a.cos()) + up * (rad * a.sin())).normalize();
    // `fp trace`: the shot goes along the render camera (the crosshair), the view punch included
    // (D-023), not along the eye's line
    if crate::spike::pov::tracing() {
        if let Some((_, eye, _, _)) = crate::camera::eye_view() {
            log(format!("gun: shot {:.3}° from the crosshair (spread {spread_deg:.2}°), {:.3}° from the eye's line", dir.angle_between(fwd).to_degrees(), dir.angle_between(eye.normalize_or_zero()).to_degrees()));
        }
    }
    let wcm = unsafe { WorldChrMan::instance() }.ok()?;
    let me = wcm.main_player.as_ref()?;
    let p = me.chr_ins.modules.physics.position;
    let me_pos = Vec3::new(p.0, p.1, p.2);
    // nothing between the camera and Fuse counts (the over-the-shoulder camera sits behind him)
    let near = (me_pos - origin).dot(dir).max(0.0);
    let mut best: Option<(f32, FieldInsHandle, f32, u32)> = None;
    for c in wcm.chr_sets.iter().flatten().flat_map(|s| s.characters()) {
        let c: &ChrIns = c;
        if c.modules.data.hp <= 0 {
            continue;
        }
        if !crate::spike::body::is_enemy_team(c.team_type) {
            // which characters the shots pass because of their team (the user, 2026-10-08: "some
            // monsters take no damage"): once per character kind
            if deal && c.team_type != 1 {
                let (h, rad) = super::body::cylinder(c);
                let q = c.modules.physics.position;
                if ray_cylinder(origin, dir, Vec3::new(q.0, q.1, q.2), h, rad).is_some_and(|t| t < range) {
                    note_skipped(c.npc_param_id as u32, c.team_type);
                }
            }
            continue;
        }
        let (h, rad) = super::body::cylinder(c);
        let q = c.modules.physics.position;
        let base = Vec3::new(q.0, q.1, q.2);
        if let Some(t) = ray_cylinder(origin, dir, base, h, rad) {
            if t > near && t < range && best.as_ref().is_none_or(|b| t < b.0) {
                let y = ((origin.y + dir.y * t) - base.y) / h;
                best = Some((t, c.field_ins_handle.clone(), y, c.npc_param_id as u32));
            }
        }
    }
    // a wall between Fuse and the target stops the shot (the ray starts at Fuse, not the camera,
    // so a wall behind him that the camera is pushed against doesn't count)
    let start = origin + dir * near;
    let reach = best.as_ref().map_or(range, |b| b.0) - near;
    let wall = unsafe { CSHavokMan::instance() }.ok().and_then(|h| {
        h.phys_world.cast_ray(MAP_RAY, &HavokPosition(start.x, start.y, start.z, 0.0), PositionDelta(dir.x * reach, dir.y * reach, dir.z * reach), me)
    });
    let wall = wall.map(|w| Vec3::new(w.0, w.1, w.2)).filter(|w| (*w - start).length() < reach - if best.is_some() { 0.3 } else { 0.0 });
    let Some((t, handle, y, npc)) = best else {
        return Some(match wall {
            Some(w) => RayOut { line: None, end: w, on: RayEnd::Map },
            None => RayOut { line: None, end: origin + dir * range, on: RayEnd::Nothing },
        });
    };
    if let Some(w) = wall {
        if deal {
            log(format!("gun: shot blocked by the map {:.1} m out (target npc {npc} at {t:.1} m)", (w - start).length()));
        }
        return Some(RayOut { line: None, end: w, on: RayEnd::Map });
    }
    let end = origin + dir * t;
    if !deal {
        return Some(RayOut { line: None, end, on: RayEnd::Target });
    }
    let zone = if y >= HEAD_ZONE { Zone::Head } else if y < LEG_ZONE { Zone::Legs } else { Zone::Body };
    let amount = damage(zone, t);
    let res = super::combat::shoot(handle.clone(), amount);
    super::stats::dealt(amount);
    let now = std::time::Instant::now();
    *LAST_HIT.lock().unwrap_or_else(|e| e.into_inner()) = Some((now, zone == Zone::Head));
    {
        let mut h = HITS.lock().unwrap_or_else(|e| e.into_inner());
        h.push_back(Hit { at: now, pos: end, damage: amount, head: zone == Zone::Head, target: handle, weapon });
        if h.len() > 64 {
            h.pop_front();
        }
    }
    Some(RayOut { line: Some(format!("hit npc {npc} {} at {t:.1} m for {amount:.1}: {res}", zone.name())), end, on: RayEnd::Target })
}

/// Logs a character the shots passed through because its team is not an enemy one (once per npc
/// and team).
fn note_skipped(npc: u32, team: u8) {
    static SEEN: Mutex<Vec<(u32, u8)>> = Mutex::new(Vec::new());
    let mut seen = SEEN.lock().unwrap_or_else(|e| e.into_inner());
    if seen.len() < 256 && !seen.contains(&(npc, team)) {
        seen.push((npc, team));
        log(format!("gun: shot passed npc {npc}: team {team} is not hit (ini friendly_teams / enemy_teams): no damage"));
    }
}

/// The nearest t >= 0 where the ray meets an upright cylinder (base centre, height, radius).
fn ray_cylinder(o: Vec3, d: Vec3, base: Vec3, h: f32, r: f32) -> Option<f32> {
    let (ox, oz) = (o.x - base.x, o.z - base.z);
    let a = d.x * d.x + d.z * d.z;
    let inside = |t: f32| {
        let y = o.y + d.y * t - base.y;
        (0.0..=h).contains(&y)
    };
    let mut hits = Vec::with_capacity(4);
    if a > 1e-8 {
        let b = 2.0 * (ox * d.x + oz * d.z);
        let c = ox * ox + oz * oz - r * r;
        let disc = b * b - 4.0 * a * c;
        if disc >= 0.0 {
            let s = disc.sqrt();
            for t in [(-b - s) / (2.0 * a), (-b + s) / (2.0 * a)] {
                if t >= 0.0 && inside(t) {
                    hits.push(t);
                }
            }
        }
    }
    // the caps (shots from above or below)
    if d.y.abs() > 1e-6 {
        for cap in [base.y, base.y + h] {
            let t = (cap - o.y) / d.y;
            let (x, z) = (ox + d.x * t, oz + d.z * t);
            if t >= 0.0 && x * x + z * z <= r * r {
                hits.push(t);
            }
        }
    }
    hits.into_iter().reduce(f32::min)
}

pub fn status() -> String {
    let g = GUN.lock().unwrap_or_else(|e| e.into_inner());
    format!(
        "gun {}: ammo {}/{CLIP}, reloading {:?}, shots {}, hits {}",
        if enabled() { "on" } else { "off (gun = 1 in the ini)" },
        g.ammo,
        g.reloading,
        g.shots,
        g.hits
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cylinder_side_cap_and_miss() {
        let base = Vec3::new(0.0, 0.0, 10.0);
        // straight at the side, 1 m up: enters at z = 9.5
        let t = ray_cylinder(Vec3::new(0.0, 1.0, 0.0), Vec3::Z, base, 2.0, 0.5).unwrap();
        assert!((t - 9.5).abs() < 1e-4);
        // above it: miss
        assert!(ray_cylinder(Vec3::new(0.0, 3.0, 0.0), Vec3::Z, base, 2.0, 0.5).is_none());
        // from straight above: the top cap
        let t = ray_cylinder(Vec3::new(0.0, 5.0, 10.0), -Vec3::Y, base, 2.0, 0.5).unwrap();
        assert!((t - 3.0).abs() < 1e-4);
        // behind the origin: no hit
        assert!(ray_cylinder(Vec3::new(0.0, 1.0, 20.0), Vec3::Z, base, 2.0, 0.5).is_none());
    }
}
