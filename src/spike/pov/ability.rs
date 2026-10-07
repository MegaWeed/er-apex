//! Octane's abilities in the view model (plan-octane.md A2/A3, T020): what the stim injector's and
//! the hand-held jump pad's first-person clips do over the R-301's graph, which of the R-301's own
//! clips go with them, and which carrier groups show. Pure (no pack, no game), so the timeline is
//! tested offline.
//!
//! From S3's settings and QCs (apex-data/assets/octane, R5R's mp_ability_heal.txt,
//! mp_weapon_jump_pad.txt, the current mp_ability_octane_stim.txt; T020's ability_sequences.json):
//! - The stim is a charge weapon in the alt hand (`offhand_active_slot altHand`): its 6 s charge
//!   (`charge_time`) is the stim, and only the charge's end fires it (`charge_end_forces_fire`,
//!   `charge_require_input` 0). So the left hand pulls the injector out (`draw`), holds it while it
//!   drains (`play_offhand_charging_anim`: the ACT_VM_CHARGE loops `idle` / `sprint` / `crouch`,
//!   6.03 / 6.36 / 6.03 s, with the additive `drain_fluid_layer`), and only when the stim ends goes
//!   to the fire (`*_to_fire`) and throws the injector away (one of six `holster_*`, ACT_VM_
//!   PRIMARYATTACK, by the QC's activity weights 75/1/20/1/75/1, standing or sprinting). Its QC's
//!   `weightlist_1` gives the right arm, the head and the legs the weight 0: those clips go over the
//!   R-301's pose bone by bone (`Mode::Masked`).
//! - Meanwhile the R-301 stays in the right hand, one-handed: it has the whole set (`switch_to_
//!   onehanded`, ACT_VM_ONEHANDED_IDLE / _PRIMARYATTACK / _SPRINT / _ADS_IN ...). Here: the switch
//!   (16 frames, QC fades 0.1 s) over the whole pose, then the additive `idle_onehanded` (fade 0.3 s,
//!   by `ads_blend`) on the graph's two-handed pose, `sprint_onehanded` over it while sprinting; at
//!   the throw's `AE_VM_EVENT_LAYER_ENABLE` frame (the flourishes are `dualwield` sequences)
//!   `switch_to_twohanded`. It fires from the end of the switch; it does not reload while the left
//!   hand holds the injector. One-handed, its shots, jumps and landings play `fire_onehanded`,
//!   `jump_onehanded`, `land_onehanded` (the graph's two-handed ones not), and aiming
//!   `ads_in_onehanded` / `ads_out_onehanded` over the right arm. Between the charge loops the QC's
//!   transitions play (`transition "idle" "sprint"` ...: the loop before, the transition over it by
//!   its fade-in, the next loop from its start by the transition's fade-out). Not done: a run layer.
//! - The jump pad is tossed with both hands (`toss`, no weight list; `AE_WPN_TOSS_RELEASE` at frame
//!   8). The mod releases it 0.3 s after Z (S3's `toss_time`, octane.rs), so the clip starts at
//!   0.3 s - 8/30 and the R-301 drops in 0.1 s before it (the pad's `deploy_time` is 0.15 s); the
//!   held pad hides at the release, the R-301 comes back when the clip ends.
//!
//! Not measured in S3 (R5R): `offhand_holster_primary` is 1 for the stim, yet the R-301's one-handed
//! set and the dual-wield throws say the R-301 stays (the mod keeps it); whether the R-301 can fire
//! during the switch.

/// The clips' frame rate, but for the flourishes (`Flourish::fps`) and the sprint loops.
const FPS: f32 = 30.0;

/// Seconds a clip of `frames` at `fps` lasts (Source: the last frame at cycle 1).
fn length_at(frames: u32, fps: f32) -> f32 {
    (frames.max(2) - 1) as f32 / fps
}

fn length(frames: u32) -> f32 {
    length_at(frames, FPS)
}

/// S3 `charge_time` (mp_ability_heal.txt): the stim, with the injector in the left hand; the same
/// 6 s as octane.rs's `STIM_SECONDS`.
pub const STIM_CHARGE: f32 = 6.0;
/// S3 `deploy_time` (mp_ability_heal.txt): the pull-out before the charge; octane.rs starts the
/// stim after it. The user's R5R video (2026-10-05 16:53): the hand in at 24.43 s, the stim's flash
/// at 24.58 s, the throw at 30.85 s (the charge's end, then `*_to_fire`).
pub const STIM_DEPLOY: f32 = 0.15;

/// The R-301's put-away and pull-out (ptpov_rspn101.qc; frames from T016's Casts), for the pad.
const R301_HOLSTER: (&str, u32) = ("holster", 16);
const R301_DRAW: (&str, u32) = ("draw", 26);
/// S3's R-301 `deploy_time` (_base_assault_rifle.txt): the pull-out is played in it.
const R301_DEPLOY: f32 = 0.6;
/// The pull-out's `AE_WPN_READYTOFIRE` frame: the R-301 can fire from there on.
const R301_READY_FRAME: u32 = 12;
/// The put-away before the pad's toss (its `deploy_time` 0.15 s, with the toss's own start).
const PAD_HOLSTER: f32 = 0.1;

/// The R-301 one-handed and back (T020's ability_sequences.json): 16 frames, QC fades 0.1 s; the
/// additive idle (191 frames, loop, fades 0.3 s) and the sprint loop (21 frames at 36 fps).
const SWITCH_ON: (&str, u32) = ("switch_to_onehanded", 16);
const SWITCH_BACK: (&str, u32) = ("switch_to_twohanded", 16);
const SWITCH_FADE: f32 = 0.1;
const IDLE_ONEHANDED: (&str, u32) = ("idle_onehanded", 191);
const ONEHANDED_FADE: f32 = 0.3;
const SPRINT_ONEHANDED: (&str, u32, f32) = ("sprint_onehanded", 21, 36.0);
/// What the one-handed R-301 plays instead of its two-handed `fire`, `jump`, `land`, `ads_in` and
/// `ads_out` (ACT_VM_ONEHANDED_*; T020's ability_sequences.json, all by `ads_blend`, weightlist_1):
/// the one-shots are additive (fire: 11 frames, QC fade-in 0.05; jump: 31 frames, fade-out 0.35;
/// land: 19 frames, fades 0.05 / 0.35), the aiming ones absolute (16 frames, fade-in 0.1). Where the
/// QC gives no fade, studiomdl's 0.2 (graph.rs `FADE`).
const FIRE_ONEHANDED: (&str, u32, f32, f32) = ("fire_onehanded", 11, 0.05, 0.2);
const JUMP_ONEHANDED: (&str, u32, f32, f32) = ("jump_onehanded", 31, 0.2, 0.35);
const LAND_ONEHANDED: (&str, u32, f32, f32) = ("land_onehanded", 19, 0.05, 0.35);
const ADS_IN_ONEHANDED: &str = "ads_in_onehanded";
const ADS_OUT_ONEHANDED: &str = "ads_out_onehanded";
const ADS_ONEHANDED_FADE: f32 = 0.1;

/// The stim's clips (ptpov_octane_epipen_held.qc): the pull-out, the charge loops (standing,
/// sprinting, crouched), the transitions to the fire, the fluid draining over the charge.
const STIM_DRAW: (&str, u32) = ("stim_draw", 7);
const STIM_LOOPS: [(&str, u32, f32); 3] = [("stim_idle_0", 181, 30.0), ("stim_sprint_0", 210, 33.0), ("stim_crouch_0", 181, 30.0)];
/// The charge loops' QC nodes (`node "idle"` ...), the order of STIM_LOOPS.
const IDLE: usize = 0;
const SPRINT: usize = 1;
const CROUCH: usize = 2;
/// QC's (studiomdl's) fade where the QC gives none, seconds (as graph.rs).
const QC_FADE: f32 = 0.2;
/// Between the charge loops, [from][to] (QC `transition "idle" "sprint"` ...): the clip, its frames
/// (30 fps), `fadein` (over the loop before) and `fadeout` (into the next loop).
const STIM_TRANSITIONS: [[Option<(&str, u32, f32, f32)>; 3]; 3] = [
    [None, Some(("stim_idle_to_sprint_0", 2, QC_FADE, QC_FADE)), Some(("stim_idle_to_crouch_0", 24, QC_FADE, 0.4))],
    [Some(("stim_sprint_to_idle_0", 7, 0.05, 0.1)), None, Some(("stim_sprint_to_crouch_0", 7, 0.05, 0.1))],
    [Some(("stim_crouch_to_idle_0", 14, QC_FADE, 0.3)), Some(("stim_crouch_to_sprint_0", 2, QC_FADE, QC_FADE)), None],
];
const STIM_TO_FIRE: [(&str, u32); 3] = [("stim_idle_to_fire_0", 9), ("stim_sprint_to_fire_0", 9), ("stim_crouch_to_fire_0", 9)];
const STIM_DRAIN: &str = "stim_drain_fluid_layer_0";

/// A way to throw the injector away: the sequence, its frames and frame rate, the QC's activity
/// weight, the frame of `AE_VM_EVENT_LAYER_ENABLE` (the R-301 two-handed again) and its `fadeout`.
pub struct Flourish {
    pub name: &'static str,
    pub frames: u32,
    pub fps: f32,
    pub weight: u32,
    pub gun_back: u32,
    pub fade_out: f32,
}

pub const FLOURISHES: [Flourish; 6] = [
    Flourish { name: "stim_holster_backToss", frames: 51, fps: 32.0, weight: 75, gun_back: 38, fade_out: 0.0 },
    Flourish { name: "stim_holster_micDrop", frames: 65, fps: 35.0, weight: 1, gun_back: 26, fade_out: 0.1 },
    Flourish { name: "stim_holster_rocker", frames: 65, fps: 36.0, weight: 20, gun_back: 62, fade_out: 0.1 },
    Flourish { name: "stim_holster_spin", frames: 65, fps: 36.0, weight: 1, gun_back: 53, fade_out: 0.1 },
    Flourish { name: "stim_holster_throwAway", frames: 56, fps: 30.0, weight: 75, gun_back: 3, fade_out: 0.0 },
    Flourish { name: "stim_holster_throwAway_fast", frames: 9, fps: 30.0, weight: 1, gun_back: 4, fade_out: 0.0 },
];

/// The shield battery (D-032, battery.rs), with T021's `ptpov_shield_battery_held` clips (30 fps,
/// battery_sequences.json). S3's consumable is a charge weapon in the main hand: `raise`
/// (ACT_VM_RAISE, 32 frames, QC `snap`) over `raise_time` 1.0 s, the `charge` loop (ACT_VM_CHARGE,
/// 271 frames, fade-in 0.1) for `charge_time` 4.0 s, and the charge's end fires it: `fire`
/// (ACT_VM_PRIMARYATTACK, 3 frames, fades 0.05), then `holster_used` (ACT_VM_HOLSTER with
/// `ability_used`, 10 frames); cancelled, `holster` (10 frames). All by `crouchFraction`, over the
/// arms by the clips' weights (the primary is away: `offhand_keep_primary_in_hand` 0; `fast_swap_to`:
/// the R-301 is gone at once). While it is out, its own `jump` and `land` are added on.
pub const BATTERY_RAISE: f32 = 1.0;
pub const BATTERY_USE: f32 = BATTERY_RAISE + 4.0;
const BATTERY_RAISE_CLIP: (&str, u32) = ("battery_raise", 32);
const BATTERY_CHARGE: (&str, u32) = ("battery_charge", 271);
const BATTERY_CHARGE_FADE: f32 = 0.1;
const BATTERY_FIRE: (&str, u32) = ("battery_fire", 3);
const BATTERY_FIRE_FADE: f32 = 0.05;
const BATTERY_HOLSTER_USED: (&str, u32) = ("battery_holster_used", 10);
const BATTERY_HOLSTER: (&str, u32) = ("battery_holster", 10);
/// The additive jump (31 frames, fade-out 0.35) and landing (19 frames, fade-in 0.05); where the QC
/// gives no fade, studiomdl's 0.2 (`QC_FADE`).
const BATTERY_JUMP: (&str, u32, f32, f32) = ("battery_jump", 31, QC_FADE, 0.35);
const BATTERY_LAND: (&str, u32, f32, f32) = ("battery_land", 19, 0.05, QC_FADE);
/// After the fire, before the R-301 comes back: `fire` then `holster_used`; after a cancel,
/// `holster`.
const BATTERY_AFTER_FIRE: f32 = (BATTERY_FIRE.1 - 1 + BATTERY_HOLSTER_USED.1 - 1) as f32 / FPS;
const BATTERY_AFTER_CANCEL: f32 = (BATTERY_HOLSTER.1 - 1) as f32 / FPS;

/// The pad's toss (ptpov_octane_jump_pad_held.qc).
const PAD_TOSS: (&str, u32) = ("pad_toss", 19);
const PAD_RELEASE_FRAME: u32 = 8;
/// When octane.rs releases the pad, from Z (S3's `toss_time`).
pub const PAD_RELEASE: f32 = 0.3;

/// The QC fade-ins of the offhand's sequences (`draw`, `*_to_fire`: 0.05) and the fade the mod
/// gives a clip where the QC has none (the hand back on the rifle; the sprint coming and going).
const FADE_IN: f32 = 0.05;
const FADE_BACK: f32 = 0.15;
const SPRINT_EASE: f32 = 0.2;

/// When the injector is thrown (its flourish starts; the QC's release sound), from the key: the
/// pull-out, the charge's end, then its `*_to_fire`.
pub fn stim_throw_at() -> f32 {
    STIM_DEPLOY + STIM_CHARGE + length(STIM_TO_FIRE[0].1)
}

/// Which flourish a draw in 0..1 picks, by the QC's activity weights.
pub fn pick_flourish(r: f32) -> usize {
    let total: u32 = FLOURISHES.iter().map(|f| f.weight).sum();
    let mut x = r.clamp(0.0, 0.999_999) * total as f32;
    for (i, f) in FLOURISHES.iter().enumerate() {
        if x < f.weight as f32 {
            return i;
        }
        x -= f.weight as f32;
    }
    FLOURISHES.len() - 1
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Kind {
    /// the injector, with the flourish (index into FLOURISHES)
    Stim(usize),
    Pad,
    /// the shield battery
    Battery,
}

/// How a layer goes over the pose under it.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Mode {
    /// over every bone by the layer's weight (the R-301's own put-away, pull-out, switches)
    Over,
    /// over each bone by its weight in the clip (the QC weight list) times the layer's
    Masked,
    /// added on, each bone by its weight in the clip times the layer's
    Add,
}

/// A clip to pose: its samples (clip names, by weight), the cycle, how far it goes over what is
/// under it and how.
#[derive(Clone, Debug, PartialEq)]
pub struct Layer {
    pub samples: Vec<(String, f32)>,
    pub cycle: f32,
    pub weight: f32,
    pub mode: Mode,
}

/// What the abilities do to the view model this frame.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Out {
    /// over the R-301's graph, in this order
    pub layers: Vec<Layer>,
    /// carrier groups 1 (the R-301; the Charge Rifle's 5 when it is the weapon in the hands), 2 (the
    /// injector), 3 (the pad), 4 (the battery) and 6 (the frag grenade in the hand, T022)
    pub show_gun: bool,
    pub show_stim: bool,
    pub show_pad: bool,
    pub show_battery: bool,
    pub show_frag: bool,
    /// the R-301 cannot fire (away, switching hands, or not past its pull-out's
    /// `AE_WPN_READYTOFIRE`)
    pub gun_away: bool,
    /// the left hand holds the injector: no reload
    pub left_busy: bool,
    /// how far the R-301 is one-handed (0..1): over 0.5 its own graph does not play `fire`, `jump`
    /// and `land` (the ability plays the one-handed ones)
    pub onehanded: f32,
}

/// What the clips blend by (QC `crouchFraction`, `sprintfrac`, `ads_blend`).
#[derive(Clone, Copy, Debug, Default)]
pub struct Params {
    pub crouch: f32,
    pub sprinting: bool,
    pub ads: f32,
    /// this frame: a shot, a jump, a landing (the graph's signals)
    pub shot: bool,
    pub jumped: bool,
    pub landed: bool,
    /// the Charge Rifle is the weapon in hand (weapons.rs): no R-301 to pull out after the battery
    /// (the arms stay at the R-301's put-away, pov/mod.rs `with_swap`)
    pub other_weapon: bool,
}

#[derive(Clone, Copy, Debug)]
pub struct Ability {
    pub kind: Kind,
    /// seconds since it started
    pub t: f32,
    /// sprinting, eased over `SPRINT_EASE` (the charge loops, the one-handed sprint)
    pub sprint: f32,
    /// the one-handed R-301's one-shots: when each started (`t`; NEG_INFINITY: none), the newest
    /// shots first
    fire: [f32; 3],
    jump: f32,
    land: f32,
    /// the zoom last frame and whether it last went up (aiming in, else out)
    ads: f32,
    zoom_in: bool,
    /// the stim's charge loop now (IDLE, SPRINT, CROUCH) and when it starts (`t`: after the
    /// transition into it), the loop before and when that started, and when the transition between
    /// them started (NEG_INFINITY: none yet)
    node: usize,
    node_start: f32,
    prev: usize,
    prev_start: f32,
    trans_start: f32,
    /// the stim: when the charge loop gives way to `*_to_fire` and the throw (`t`; the charge's end,
    /// or earlier when a reload asks for the left hand: `throw_now`)
    fire_at: f32,
    /// the battery: when its use ends (`t`): the fire at BATTERY_USE, or a cancel before it
    battery_end: f32,
}

/// `name_0` and `name_1` by `a` (0: the first).
fn two(name: &str, a: f32) -> Vec<(String, f32)> {
    let a = a.clamp(0.0, 1.0);
    let mut v = vec![(format!("{name}_0"), 1.0 - a), (format!("{name}_1"), a)];
    v.retain(|s| s.1 > 0.0);
    v
}

fn one(name: &str) -> Vec<(String, f32)> {
    vec![(format!("{name}_0"), 1.0)]
}

/// A one-shot clip `frames` long starting at `start`, played in `seconds` (its own length if None):
/// the cycle at `t`, or None before it starts.
fn cycle_at(t: f32, start: f32, frames: u32, seconds: Option<f32>) -> Option<f32> {
    let d = seconds.unwrap_or_else(|| length(frames));
    (t >= start).then(|| ((t - start) / d).min(1.0))
}

/// 0 to 1 over `fade` from `start`.
fn ramp(t: f32, start: f32, fade: f32) -> f32 {
    ((t - start) / fade.max(1e-6)).clamp(0.0, 1.0)
}

impl Ability {
    pub fn new(kind: Kind) -> Ability {
        let never = f32::NEG_INFINITY;
        let draw_end = length(STIM_DRAW.1);
        Ability {
            kind,
            t: 0.0,
            sprint: 0.0,
            fire: [never; 3],
            jump: never,
            land: never,
            ads: 0.0,
            zoom_in: false,
            node: IDLE,
            node_start: draw_end,
            prev: IDLE,
            prev_start: draw_end,
            trans_start: never,
            fire_at: STIM_DEPLOY + STIM_CHARGE,
            battery_end: BATTERY_USE,
        }
    }

    /// The battery's use cancelled now (battery.rs): it is put away and the R-301 comes back.
    pub fn cancel_battery(&mut self) {
        if self.kind == Kind::Battery && self.t < self.battery_end {
            self.battery_end = self.t;
        }
    }

    /// The stim: throw the injector now rather than at the charge's end, freeing the left hand for a
    /// reload (the user's choice, 2026-10-05: an empty magazine waited up to 8 s for the throw). The
    /// stim itself goes on (octane.rs). Not before the switch to one hand is over. The seconds from
    /// now to the throw's start (its release sound), or None when it is not a held stim any more.
    pub fn throw_now(&mut self) -> Option<f32> {
        if !matches!(self.kind, Kind::Stim(_)) || self.t >= self.fire_at {
            return None;
        }
        self.fire_at = self.t.max(length(SWITCH_ON.1));
        Some(self.flourish_start() - self.t)
    }

    /// Frozen `t` seconds in (dev `fp hold`).
    pub fn at(kind: Kind, t: f32) -> Ability {
        Ability { t, ..Ability::new(kind) }
    }

    pub fn step(&mut self, dt: f32, p: Params) {
        let dt = dt.clamp(0.0, 0.1);
        self.t += dt;
        let to = if p.sprinting { 1.0 } else { 0.0 };
        self.sprint += (to - self.sprint).clamp(-dt / SPRINT_EASE, dt / SPRINT_EASE);
        if let Kind::Stim(_) = self.kind {
            // the charge loop by stance (sprinting over crouched); the pull-out goes straight into
            // the stance's loop, later changes go through the QC's transition (until the charge ends)
            let target = if p.sprinting {
                SPRINT
            } else if p.crouch > 0.5 {
                CROUCH
            } else {
                IDLE
            };
            if self.t < length(STIM_DRAW.1) {
                self.node = target;
            } else if target != self.node
                && self.t < self.fire_at
                && let Some((_, frames, _, _)) = STIM_TRANSITIONS[self.node][target]
            {
                self.prev = self.node;
                self.prev_start = self.node_start;
                self.trans_start = self.t;
                self.node = target;
                self.node_start = self.t + length(frames);
            }
        }
        if self.kind == Kind::Battery && self.t < self.gun_back() {
            // the battery's own jump and landing (no shots: the R-301 is away)
            if p.jumped {
                self.jump = self.t;
            }
            if p.landed {
                self.land = self.t;
            }
        }
        if self.onehanded() > 0.5 {
            if p.shot {
                self.fire.rotate_right(1);
                self.fire[0] = self.t;
            }
            if p.jumped {
                self.jump = self.t;
            }
            if p.landed {
                self.land = self.t;
            }
        }
        if p.ads > self.ads + 1e-5 {
            self.zoom_in = true;
        } else if p.ads < self.ads - 1e-5 {
            self.zoom_in = false;
        }
        self.ads = p.ads;
    }

    /// How far the R-301 is one-handed now (the stim: in after its switch, out over the switch back).
    fn onehanded(&self) -> f32 {
        match self.kind {
            Kind::Stim(_) => ramp(self.t, length(SWITCH_ON.1), ONEHANDED_FADE) * (1.0 - ramp(self.t, self.gun_back(), length(SWITCH_BACK.1))),
            Kind::Pad | Kind::Battery => 0.0,
        }
    }

    /// The one-handed one-shots playing (newest first), as graph.rs weighs its own: each fades in
    /// over its fade-in, out over the last fade-out seconds, and covers the older ones as it comes in.
    fn one_shots(&self, starts: &[f32], clip: (&str, u32, f32, f32), p: Params, out: &mut Vec<Layer>) {
        let (name, frames, fade_in, fade_out) = clip;
        let len = length(frames);
        let mut left = 1.0;
        for &start in starts {
            let Some(cycle) = cycle_at(self.t, start, frames, None) else { continue };
            if cycle >= 1.0 {
                continue;
            }
            let fade = ramp(self.t, start, fade_in);
            let tail = ((1.0 - cycle) * len / fade_out).clamp(0.0, 1.0);
            let weight = left * fade * tail;
            left *= 1.0 - fade;
            if weight > 0.0 {
                out.push(Layer { samples: two(name, p.ads), cycle, weight, mode: Mode::Add });
            }
        }
    }

    /// The charge loops' transition last started, if any: clip, frames, fade-in, fade-out.
    fn transition(&self) -> Option<(&'static str, u32, f32, f32)> {
        if self.trans_start.is_finite() { STIM_TRANSITIONS[self.prev][self.node] } else { None }
    }

    fn flourish(&self) -> &'static Flourish {
        let Kind::Stim(i) = self.kind else { return &FLOURISHES[0] };
        &FLOURISHES[i.min(FLOURISHES.len() - 1)]
    }

    fn flourish_start(&self) -> f32 {
        self.fire_at + length(STIM_TO_FIRE[0].1)
    }

    /// When the R-301 comes back (the stim: two-handed again; the pad: its pull-out), from the start.
    pub fn gun_back(&self) -> f32 {
        match self.kind {
            Kind::Stim(_) => {
                let f = self.flourish();
                self.flourish_start() + f.gun_back as f32 / f.fps
            }
            Kind::Pad => self.pad_start() + length(PAD_TOSS.1),
            Kind::Battery if self.battery_end < BATTERY_USE => self.battery_end + BATTERY_AFTER_CANCEL,
            Kind::Battery => BATTERY_USE + BATTERY_AFTER_FIRE,
        }
    }

    fn pad_start(&self) -> f32 {
        PAD_RELEASE - PAD_RELEASE_FRAME as f32 / FPS
    }

    /// When the offhand's clips are over (faded out), from the start.
    fn arms_end(&self) -> f32 {
        match self.kind {
            Kind::Stim(_) => {
                let f = self.flourish();
                self.flourish_start() + length_at(f.frames, f.fps) + f.fade_out.max(FADE_BACK)
            }
            Kind::Pad => self.pad_start() + length(PAD_TOSS.1) + FADE_BACK,
            Kind::Battery => self.gun_back(),
        }
    }

    /// When the R-301's own clips are over, from the start.
    fn gun_end(&self) -> f32 {
        match self.kind {
            Kind::Stim(_) => self.gun_back() + length(SWITCH_BACK.1) + SWITCH_FADE,
            Kind::Pad | Kind::Battery => self.gun_back() + R301_DEPLOY,
        }
    }

    /// Whether it is over: the R-301 back and the offhand gone.
    pub fn done(&self) -> bool {
        self.t >= self.gun_end().max(self.arms_end())
    }

    pub fn out(&self, p: Params) -> Out {
        match self.kind {
            Kind::Stim(_) => self.stim(p),
            Kind::Pad => self.pad(p),
            Kind::Battery => self.battery(p),
        }
    }

    /// The R-301 put away (its `holster` over PAD_HOLSTER), hidden until `back`, pulled out again
    /// (its `draw` over its deploy time; it fires from the draw's ready frame).
    fn r301_away(&self, back: f32, p: Params, o: &mut Out) {
        let t = self.t;
        if t < back {
            let c = (t / PAD_HOLSTER).min(1.0);
            o.layers.push(Layer { samples: one(R301_HOLSTER.0), cycle: c, weight: (t / 0.1).min(1.0), mode: Mode::Over });
            o.show_gun = c < 1.0;
            o.gun_away = true;
        } else if t < back + R301_DEPLOY {
            let cycle = (t - back) / R301_DEPLOY;
            o.layers.push(Layer { samples: two(R301_DRAW.0, p.crouch), cycle, weight: 1.0, mode: Mode::Over });
            o.gun_away = cycle < R301_READY_FRAME as f32 / (R301_DRAW.1 - 1) as f32;
        }
    }

    fn battery(&self, p: Params) -> Out {
        let t = self.t;
        let back = self.gun_back();
        let mut o = Out { show_gun: true, ..Default::default() };
        if t >= back {
            // the R-301 pulled out again (not when the Charge Rifle is the weapon in hand)
            if !p.other_weapon {
                self.r301_away(back, p, &mut o);
            }
            return o;
        }
        o.show_gun = false;
        o.gun_away = true;
        o.left_busy = true;
        o.show_battery = true;
        let c = p.crouch;
        let mut layer = |name: &str, cycle: f32, weight: f32, mode: Mode| {
            if weight > 0.0 {
                o.layers.push(Layer { samples: two(name, c), cycle: cycle.clamp(0.0, 1.0), weight, mode });
            }
        };
        layer(BATTERY_RAISE_CLIP.0, t / BATTERY_RAISE, 1.0, Mode::Masked);
        if t >= BATTERY_RAISE {
            layer(BATTERY_CHARGE.0, (t - BATTERY_RAISE) / length(BATTERY_CHARGE.1), ramp(t, BATTERY_RAISE, BATTERY_CHARGE_FADE), Mode::Masked);
        }
        let end = self.battery_end;
        if end < BATTERY_USE {
            // cancelled: put away
            if t >= end {
                layer(BATTERY_HOLSTER.0, (t - end) / length(BATTERY_HOLSTER.1), ramp(t, end, FADE_IN), Mode::Masked);
            }
        } else if t >= BATTERY_USE {
            layer(BATTERY_FIRE.0, (t - BATTERY_USE) / length(BATTERY_FIRE.1), ramp(t, BATTERY_USE, BATTERY_FIRE_FADE), Mode::Masked);
            let used = BATTERY_USE + length(BATTERY_FIRE.1);
            if t >= used {
                layer(BATTERY_HOLSTER_USED.0, (t - used) / length(BATTERY_HOLSTER_USED.1), ramp(t, used, FADE_IN), Mode::Masked);
            }
        }
        // the jump and the landing, added on
        for (start, (name, frames, fade_in, fade_out)) in [(self.jump, BATTERY_JUMP), (self.land, BATTERY_LAND)] {
            let Some(cycle) = cycle_at(t, start, frames, None) else { continue };
            if cycle >= 1.0 {
                continue;
            }
            let tail = ((1.0 - cycle) * length(frames) / fade_out).clamp(0.0, 1.0);
            layer(name, cycle, ramp(t, start, fade_in) * tail, Mode::Add);
        }
        o
    }

    fn stim(&self, p: Params) -> Out {
        let (t, s) = (self.t, self.sprint);
        let f = self.flourish();
        let switch_end = length(SWITCH_ON.1);
        let back = self.gun_back();
        let mut o = Out { show_gun: true, ..Default::default() };
        // the R-301 one-handed: the additive idle under everything (in after the switch, out over
        // the switch back), the one-handed sprint over the graph, the switches over the whole pose
        let onehanded = self.onehanded();
        o.onehanded = onehanded;
        if onehanded > 0.0 {
            // aiming: `ads_in_onehanded` at the zoom after it last went up, `ads_out_onehanded` at
            // 1 - zoom otherwise, over the right arm and the gun, coming in with the zoom
            if p.ads > 0.0 {
                let (name, cycle) = if self.zoom_in { (ADS_IN_ONEHANDED, p.ads) } else { (ADS_OUT_ONEHANDED, 1.0 - p.ads) };
                let w = onehanded * (p.ads / ADS_ONEHANDED_FADE.max(1e-6)).min(1.0);
                o.layers.push(Layer { samples: one(name), cycle: cycle.clamp(0.0, 1.0), weight: w, mode: Mode::Masked });
            }
            let idle = (t - switch_end) / length(IDLE_ONEHANDED.1);
            o.layers.push(Layer { samples: two(IDLE_ONEHANDED.0, p.ads), cycle: idle, weight: onehanded, mode: Mode::Add });
            if s > 0.0 {
                let cycle = (t - switch_end) / length_at(SPRINT_ONEHANDED.1, SPRINT_ONEHANDED.2);
                o.layers.push(Layer { samples: one(SPRINT_ONEHANDED.0), cycle, weight: s * onehanded, mode: Mode::Masked });
            }
            // the shots, the jump, the landing, added on (in place of the graph's two-handed ones)
            let mut shots = Vec::new();
            self.one_shots(&self.fire, FIRE_ONEHANDED, p, &mut shots);
            self.one_shots(&[self.jump], JUMP_ONEHANDED, p, &mut shots);
            self.one_shots(&[self.land], LAND_ONEHANDED, p, &mut shots);
            for l in &mut shots {
                l.weight *= onehanded;
            }
            o.layers.extend(shots);
        }
        if t < switch_end + ONEHANDED_FADE {
            // in over 0.1 s; at its end it holds while the one-handed idle comes in, then is gone
            let w = ramp(t, 0.0, SWITCH_FADE) * (1.0 - onehanded);
            o.layers.push(Layer { samples: one(SWITCH_ON.0), cycle: (t / switch_end).min(1.0), weight: w, mode: Mode::Over });
        } else if t >= back {
            let d = length(SWITCH_BACK.1);
            let w = ramp(t, back, SWITCH_FADE) * (1.0 - ramp(t, back + d, SWITCH_FADE));
            if w > 0.0 {
                o.layers.push(Layer { samples: two(SWITCH_BACK.0, p.crouch), cycle: ((t - back) / d).min(1.0), weight: w, mode: Mode::Over });
                }
        }
        o.gun_away = t < switch_end;
        o.left_busy = t < back;
        // the left hand: pull the injector out, hold it through the charge, then fire and throw
        let draw_end = length(STIM_DRAW.1);
        let start = self.flourish_start();
        let end = start + length_at(f.frames, f.fps);
        let mut arms = vec![Layer { samples: two(STIM_DRAW.0, p.crouch), cycle: cycle_at(t, 0.0, STIM_DRAW.1, None).unwrap_or(0.0), weight: ramp(t, 0.0, FADE_IN), mode: Mode::Masked }];
        if t >= draw_end {
            let fade = ramp(t, draw_end, FADE_IN);
            let looped = |node: usize, start: f32, weight: f32| Layer {
                samples: vec![(STIM_LOOPS[node].0.to_string(), 1.0)],
                cycle: ((t - start) / length_at(STIM_LOOPS[node].1, STIM_LOOPS[node].2)).max(0.0),
                weight,
                mode: Mode::Masked,
            };
            match self.transition() {
                // the loop before, the transition coming in over it, the next loop at its end
                Some((name, frames, fade_in, fade_out)) if t < self.node_start + fade_out => {
                    arms.push(looped(self.prev, self.prev_start, fade));
                    let c = cycle_at(t, self.trans_start, frames, None).unwrap_or(0.0);
                    arms.push(Layer { samples: vec![(name.to_string(), 1.0)], cycle: c, weight: ramp(t, self.trans_start, fade_in), mode: Mode::Masked });
                    arms.push(looped(self.node, self.node_start, ramp(t, self.node_start, fade_out)));
                }
                _ => arms.push(looped(self.node, self.node_start, fade)),
            }
        }
        let charge_end = self.fire_at;
        if let Some(c) = cycle_at(t, charge_end, STIM_TO_FIRE[0].1, None) {
            let to_fire = vec![(STIM_TO_FIRE[self.node].0.to_string(), 1.0)];
            arms.push(Layer { samples: to_fire, cycle: c, weight: ramp(t, charge_end, FADE_IN), mode: Mode::Masked });
        }
        if let Some(c) = cycle_at(t, start, f.frames, Some(length_at(f.frames, f.fps))) {
            arms.push(Layer { samples: two(f.name, s), cycle: c, weight: 1.0, mode: Mode::Masked });
        }
        let left = 1.0 - ramp(t, end, f.fade_out.max(FADE_BACK));
        for l in &mut arms {
            l.weight *= left;
        }
        arms.retain(|l| l.weight > 0.0);
        o.layers.extend(arms);
        o.show_stim = t < end;
        if o.show_stim {
            // the fluid drains over the charge
            o.layers.push(Layer { samples: vec![(STIM_DRAIN.to_string(), 1.0)], cycle: ((t - STIM_DEPLOY) / STIM_CHARGE).clamp(0.0, 1.0), weight: 1.0, mode: Mode::Add });
        }
        o
    }

    fn pad(&self, p: Params) -> Out {
        let t = self.t;
        let back = self.gun_back();
        let mut o = Out { show_gun: true, ..Default::default() };
        // the R-301: put away, hidden, pulled out again
        self.r301_away(back, p, &mut o);
        let start = self.pad_start();
        let end = start + length(PAD_TOSS.1);
        if let Some(c) = cycle_at(t, start, PAD_TOSS.1, None) {
            let w = ramp(t, start, FADE_IN) * (1.0 - ramp(t, end, FADE_BACK));
            if w > 0.0 {
                o.layers.push(Layer { samples: one(PAD_TOSS.0), cycle: c, weight: w, mode: Mode::Masked });
            }
        }
        o.show_pad = t >= start && t < PAD_RELEASE;
        o.left_busy = t < end;
        o
    }

    /// For `fp vm` / `fp trace`.
    pub fn describe(&self) -> String {
        let kind = match self.kind {
            Kind::Stim(_) => self.flourish().name,
            Kind::Pad => "pad",
            Kind::Battery => "battery",
        };
        format!("{kind} {:.2} s (gun back {:.2} s)", self.t, self.gun_back())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const DT: f32 = 1.0 / 60.0;

    fn run(kind: Kind, p: Params) -> Vec<(f32, Out)> {
        let mut a = Ability::new(kind);
        let mut v = Vec::new();
        while !a.done() && a.t < 12.0 {
            a.step(DT, p);
            v.push((a.t, a.out(p)));
        }
        v
    }

    fn names(o: &Out) -> Vec<&str> {
        o.layers.iter().map(|l| l.samples[0].0.as_str()).collect()
    }

    /// Standing, then sprinting from 2 s: the idle loop, `idle_to_sprint` over it, the sprint loop
    /// from its start at the transition's end; crouching from 4 s: `sprint_to_crouch` (fade-in
    /// 0.05 s), then the crouch loop by its 0.1 s fade-out; the fire at the end is the crouched one.
    #[test]
    fn stim_loop_transitions() {
        let mut a = Ability::new(Kind::Stim(4));
        let stand = Params::default();
        let sprint = Params { sprinting: true, ..Default::default() };
        let crouch = Params { crouch: 1.0, ..Default::default() };
        let layer = |a: &Ability, p: Params, name: &str| a.out(p).layers.into_iter().find(|l| l.samples[0].0 == name);
        while a.t < 2.0 {
            a.step(DT, stand);
        }
        assert!(layer(&a, stand, "stim_idle_0").is_some_and(|l| l.weight == 1.0));
        assert!(layer(&a, stand, "stim_idle_to_sprint_0").is_none());
        a.step(DT, sprint);
        let (start, trans) = (a.t, length(2));
        // the frame after: the transition coming in over the idle loop, the sprint loop not yet
        a.step(DT, sprint);
        assert!(layer(&a, sprint, "stim_idle_to_sprint_0").is_some_and(|l| l.weight > 0.0 && l.weight < 0.2));
        assert!(layer(&a, sprint, "stim_idle_0").is_some_and(|l| l.weight == 1.0));
        assert!(layer(&a, sprint, "stim_sprint_0").is_none());
        while a.t < start + trans + 0.1 {
            a.step(DT, sprint);
        }
        let l = layer(&a, sprint, "stim_sprint_0").unwrap();
        assert!(l.weight > 0.4 && l.weight < 0.7 && l.cycle < 0.03, "{l:?}");
        while a.t < 4.0 {
            a.step(DT, sprint);
        }
        let n = names(&a.out(sprint)).into_iter().map(str::to_string).collect::<Vec<_>>();
        assert!(n.contains(&"stim_sprint_0".to_string()) && !n.iter().any(|n| n.contains("_to_")), "{n:?}");
        a.step(DT, crouch);
        let c0 = a.t;
        while a.t < c0 + 0.06 {
            a.step(DT, crouch);
        }
        assert!(layer(&a, crouch, "stim_sprint_to_crouch_0").is_some_and(|l| l.weight == 1.0));
        while a.t < c0 + length(7) + 0.11 {
            a.step(DT, crouch);
        }
        let n = names(&a.out(crouch)).into_iter().map(str::to_string).collect::<Vec<_>>();
        assert!(n.contains(&"stim_crouch_0".to_string()) && !n.iter().any(|n| n.contains("_to_")), "{n:?}");
        while a.t < STIM_DEPLOY + STIM_CHARGE + 0.05 {
            a.step(DT, crouch);
        }
        assert!(layer(&a, crouch, "stim_crouch_to_fire_0").is_some());
    }

    /// The QC's weights pick throwAway and backToss most of the time, every flourish somewhere.
    #[test]
    fn flourish_by_qc_weights() {
        let picks: Vec<usize> = (0..1730).map(|i| pick_flourish((i as f32 + 0.5) / 1730.0)).collect();
        let count = |k: usize| picks.iter().filter(|&&p| p == k).count();
        assert_eq!((count(0), count(1), count(2), count(3), count(4), count(5)), (750, 10, 200, 10, 750, 10));
        assert_eq!(pick_flourish(0.0), 0);
        assert_eq!(pick_flourish(1.0), 5);
    }

    /// The stim: the injector out at once and held through the 6 s charge (the fluid draining), the
    /// R-301 one-handed and firing meanwhile, the throw only after the charge, the R-301 two-handed
    /// again at the throw's layer frame; then nothing.
    #[test]
    fn stim_timeline() {
        let p = Params::default();
        let v = run(Kind::Stim(4), p);
        let at = |s: f32| &v.iter().find(|(t, _)| *t >= s).unwrap().1;
        // at once: the switch to one hand, the injector pulled out; no shot until the switch is done
        let o = at(DT);
        assert!(o.show_gun && o.show_stim && o.gun_away && o.left_busy, "{o:?}");
        assert_eq!(names(o), ["switch_to_onehanded_0", "stim_draw_0", STIM_DRAIN]);
        // the charge: the injector held, the R-301 one-handed and free to fire, no throw yet
        for s in [1.0, 3.0, 6.05] {
            let o = at(s);
            assert!(o.show_gun && o.show_stim && !o.gun_away && o.left_busy && !names(o).iter().any(|n| n.starts_with("switch")), "{s}: {o:?}");
            assert!(names(o).contains(&"idle_onehanded_0") && names(o).contains(&"stim_idle_0"), "{s}: {:?}", names(o));
            assert!(!names(o).iter().any(|n| n.starts_with("stim_holster")), "{s}: thrown early");
        }
        // the fluid follows the charge, which starts after the pull-out
        let drain = |s: f32| at(s).layers.iter().find(|l| l.samples[0].0 == STIM_DRAIN).unwrap().cycle;
        assert!(drain(0.1) == 0.0 && (drain(3.15) - 0.5).abs() < 0.01 && drain(6.2) == 1.0);
        // the end of the charge: to the fire, then the throw (throwAway: two-handed at its frame 3)
        assert!(names(at(6.2)).contains(&"stim_idle_to_fire_0"));
        let start = STIM_DEPLOY + STIM_CHARGE + 8.0 / 30.0;
        let o = at(start + 0.02);
        assert!(names(o).contains(&"stim_holster_throwAway_0") && o.left_busy);
        let back = start + 3.0 / 30.0;
        let a = Ability::new(Kind::Stim(4));
        assert!((a.gun_back() - back).abs() < 1e-5, "{}", a.gun_back());
        let o = at(back + 0.2);
        assert!(names(o).contains(&"switch_to_twohanded_0") && !o.left_busy && !o.gun_away);
        // the end: everything back
        let (t, o) = v.last().unwrap();
        assert!(o.layers.is_empty() && !o.show_stim && o.show_gun && !o.gun_away && !o.left_busy, "{t} {o:?}");
        assert!(*t > 7.0 && *t < 8.5, "{t}");
    }

    /// A reload at 2 s throws the injector then (to the fire, the flourish), not after the charge:
    /// the left hand is free at the flourish's layer frame; a second call does nothing.
    #[test]
    fn stim_thrown_early_for_reload() {
        let p = Params::default();
        let mut a = Ability::new(Kind::Stim(0));
        while a.t < 2.0 {
            a.step(DT, p);
        }
        let delay = a.throw_now().expect("held");
        assert!((delay - 8.0 / 30.0).abs() < 0.02, "{delay}");
        assert!(a.throw_now().is_none());
        let back = a.t + delay + 38.0 / 32.0;
        assert!((a.gun_back() - back).abs() < 1e-4, "{} {back}", a.gun_back());
        while a.t < back - 0.05 {
            a.step(DT, p);
        }
        assert!(a.out(p).left_busy);
        let o = a.out(p);
        assert!(names(&o).contains(&"stim_holster_backToss_0"), "{:?}", names(&o));
        while a.t < back + 0.05 {
            a.step(DT, p);
        }
        assert!(!a.out(p).left_busy);
        // too early (switching to one hand): the throw waits for the switch's end
        let mut b = Ability::new(Kind::Stim(4));
        b.step(DT, p);
        let d = b.throw_now().unwrap();
        assert!((b.t + d - length(SWITCH_ON.1) - 8.0 / 30.0).abs() < 1e-4);
    }

    /// Sprinting takes the sprint loop, its fire and the throw's sprint sample, and the R-301's
    /// one-handed sprint; backToss is two-handed again at its frame 38.
    #[test]
    fn stim_while_sprinting() {
        let a = Ability::new(Kind::Stim(0));
        assert!((a.gun_back() - (STIM_DEPLOY + STIM_CHARGE + 8.0 / 30.0 + 38.0 / 32.0)).abs() < 1e-5);
        let v = run(Kind::Stim(0), Params { sprinting: true, ..Default::default() });
        let at = |s: f32| &v.iter().find(|(t, _)| *t >= s).unwrap().1;
        let o = at(2.0);
        assert!(o.layers.iter().any(|l| l.samples == vec![("stim_sprint_0".to_string(), 1.0)]), "{:?}", o.layers);
        assert!(names(o).contains(&"sprint_onehanded_0"));
        assert!(at(6.25).layers.iter().any(|l| l.samples == vec![("stim_sprint_to_fire_0".to_string(), 1.0)]));
        assert!(at(6.95).layers.iter().any(|l| l.samples == vec![("stim_holster_backToss_1".to_string(), 1.0)]));
    }

    /// While one-handed the stim plays the R-301's one-handed fire, jump and landing (not before the
    /// switch), aims with `ads_in_onehanded` / `ads_out_onehanded`, and says so for the graph.
    #[test]
    fn onehanded_one_shots_and_aim() {
        let mut a = Ability::new(Kind::Stim(4));
        let names = |a: &Ability, p: Params| a.out(p).layers.iter().map(|l| l.samples[0].0.clone()).collect::<Vec<_>>();
        // a shot during the switch to one hand: not taken
        a.step(DT, Params { shot: true, ..Default::default() });
        assert!(!names(&a, Params::default()).iter().any(|n| n.starts_with("fire_onehanded")));
        assert!(a.out(Params::default()).onehanded < 0.5);
        while a.t < 2.0 {
            a.step(DT, Params::default());
        }
        assert_eq!(a.out(Params::default()).onehanded, 1.0);
        a.step(DT, Params { shot: true, jumped: true, ..Default::default() });
        // in from the next frame (fading in over the QC fade-in, as the graph's one-shots)
        a.step(DT, Params::default());
        let n = names(&a, Params::default());
        assert!(n.contains(&"fire_onehanded_0".to_string()) && n.contains(&"jump_onehanded_0".to_string()), "{n:?}");
        // the shot is over after its 11 frames
        for _ in 0..30 {
            a.step(DT, Params::default());
        }
        assert!(!names(&a, Params::default()).iter().any(|n| n.starts_with("fire_onehanded")));
        // aiming in: ads_in_onehanded at the zoom, by ads_blend's second samples
        let aim = Params { ads: 0.5, ..Default::default() };
        a.step(DT, aim);
        let o = a.out(aim);
        let l = o.layers.iter().find(|l| l.samples[0].0 == "ads_in_onehanded_0").expect("aiming in");
        assert!((l.cycle - 0.5).abs() < 1e-6 && l.mode == Mode::Masked && l.weight == 1.0);
        let out = Params { ads: 0.4, ..Default::default() };
        a.step(DT, out);
        assert!(a.out(out).layers.iter().any(|l| l.samples[0].0 == "ads_out_onehanded_0" && (l.cycle - 0.6).abs() < 1e-6));
        // two-handed again after the throw: no one-handed layers
        while !a.done() {
            a.step(DT, Params::default());
        }
        assert!(a.out(Params::default()).onehanded == 0.0);
    }

    /// Crouched from the start, the charge loop is the crouched one (no transition), alone.
    #[test]
    fn crouched_from_the_start() {
        let v = run(Kind::Stim(4), Params { crouch: 1.0, ..Default::default() });
        let o = &v.iter().find(|(t, _)| *t >= 2.0).unwrap().1;
        let loops: Vec<&Layer> = o.layers.iter().filter(|l| l.samples[0].0.starts_with("stim_") && l.samples[0].0.ends_with("_0") && !l.samples[0].0.contains("draw")).collect();
        assert!(loops.iter().any(|l| l.samples == vec![("stim_crouch_0".to_string(), 1.0)] && l.weight == 1.0), "{loops:?}");
        assert!(!names(o).iter().any(|n| n.contains("_to_") || *n == "stim_idle_0"), "{:?}", names(o));
    }

    /// The battery: out at once over 1 s (`raise`), charging until 5 s, then `fire` and
    /// `holster_used` (0.37 s) and the R-301 pulled out; cancelled at 2 s, `holster` (0.3 s) instead.
    #[test]
    fn battery_timeline() {
        let p = Params::default();
        let v = run(Kind::Battery, p);
        let at = |s: f32| &v.iter().find(|(t, _)| *t >= s).unwrap().1;
        let o = at(0.05);
        assert!(o.gun_away && !o.show_gun && o.show_battery && o.left_busy);
        assert_eq!(names(o), ["battery_raise_0"]);
        assert!(o.layers[0].mode == Mode::Masked && (o.layers[0].cycle - 0.05).abs() < 0.02);
        let o = at(2.0);
        assert_eq!(names(o), ["battery_raise_0", "battery_charge_0"]);
        assert!((o.layers[1].cycle - 1.0 / 9.0).abs() < 0.01 && o.layers[1].weight == 1.0);
        assert!(names(at(5.03)).contains(&"battery_fire_0"));
        let o = at(5.2);
        assert!(names(o).contains(&"battery_holster_used_0") && o.show_battery && !o.show_gun);
        assert!((BATTERY_AFTER_FIRE - 11.0 / 30.0).abs() < 1e-6);
        let o = at(5.45);
        assert!(o.show_gun && !o.show_battery && names(o) == ["draw_0"]);
        let (t, o) = v.last().unwrap();
        assert!(!o.gun_away && o.layers.is_empty() && (*t - (BATTERY_USE + BATTERY_AFTER_FIRE + R301_DEPLOY)).abs() < 0.05, "{t}");
        // crouched: the second samples
        let crouched = Params { crouch: 1.0, ..Default::default() };
        let mut a = Ability::new(Kind::Battery);
        a.step(DT, crouched);
        assert_eq!(a.out(crouched).layers[0].samples, vec![("battery_raise_1".to_string(), 1.0)]);
        // cancelled at 2 s: put away over 0.3 s, then the R-301
        let mut a = Ability::new(Kind::Battery);
        while a.t < 2.0 {
            a.step(DT, p);
        }
        a.cancel_battery();
        assert!((a.gun_back() - (a.t + BATTERY_AFTER_CANCEL)).abs() < 1e-5);
        a.step(DT, p);
        let n = a.out(p).layers.iter().map(|l| l.samples[0].0.clone()).collect::<Vec<_>>();
        assert!(n.contains(&"battery_holster_0".to_string()) && !n.iter().any(|n| n.contains("fire")), "{n:?}");
        while !a.done() {
            a.step(DT, p);
        }
        assert!(a.t < 2.0 + BATTERY_AFTER_CANCEL + R301_DEPLOY + 0.05 && !a.out(p).gun_away);
    }

    /// A jump and a landing while the battery is out add its own jump and land clips.
    #[test]
    fn battery_jump_and_land() {
        let mut a = Ability::new(Kind::Battery);
        while a.t < 2.0 {
            a.step(DT, Params::default());
        }
        a.step(DT, Params { jumped: true, ..Default::default() });
        a.step(DT, Params::default());
        let o = a.out(Params::default());
        assert!(o.layers.iter().any(|l| l.samples[0].0 == "battery_jump_0" && l.mode == Mode::Add && l.weight > 0.0));
        a.step(DT, Params { landed: true, ..Default::default() });
        a.step(DT, Params::default());
        assert!(a.out(Params::default()).layers.iter().any(|l| l.samples[0].0 == "battery_land_0"));
    }

    /// The pad: the toss's release frame lands on the mod's release (0.3 s), the pad hides then, the
    /// R-301 is away until the toss ends.
    #[test]
    fn pad_timeline() {
        let a = Ability::new(Kind::Pad);
        let start = 0.3 - 8.0 / 30.0;
        assert!((a.gun_back() - (start + 18.0 / 30.0)).abs() < 1e-5);
        let v = run(Kind::Pad, Params::default());
        let at = |s: f32| &v.iter().find(|(t, _)| *t >= s).unwrap().1;
        assert!(!at(DT).show_pad && at(DT).gun_away);
        let o = at(0.2);
        let toss = o.layers.iter().find(|l| l.samples[0].0 == "pad_toss_0").unwrap();
        assert!(o.show_pad && !o.show_gun && (toss.cycle - (0.2 - start) / (18.0 / 30.0)).abs() < 0.03);
        // the release: frame 8 of 18 intervals
        let o = at(0.3);
        let toss = o.layers.iter().find(|l| l.samples[0].0 == "pad_toss_0").unwrap();
        assert!(!o.show_pad && (toss.cycle - 8.0 / 18.0).abs() < 0.03, "{}", toss.cycle);
        let (_, o) = v.last().unwrap();
        assert!(!o.gun_away && o.layers.is_empty() && o.show_gun);
    }
}
