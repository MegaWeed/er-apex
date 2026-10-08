//! The two primary weapon slots (U3): 1 the Wingman in the R-301's place (gun.rs; the slot keeps
//! its `R301` name in the code), 2 the Charge Rifle (chargerifle.rs,
//! S3 `mp_weapon_defender`). Keys 1 and 2 are S3's `weaponSelectPrimary0` / `weaponSelectPrimary1`
//! (dev `weapon 1|2`).
//!
//! A switch as S3's weapon settings time it (R5Reloaded `platform/scripts/weapons`): the weapon in
//! hand is put away over its `holster_time`, then the other is drawn over its `deploy_time`, or its
//! `deployfirst_time` the first time it is drawn; it can fire (and aim) from its draw's
//! `AE_WPN_READYTOFIRE` frame on, the rule ability.rs uses for the R-301's pull-out after the pad.
//! The frames are the local retail view models' (D-021): R-301 `ptpov_rspn101.qc` draw 12 of 25
//! (26 frames), drawfirst 38 of 44; Charge Rifle `chargerifle_base_v_animRig.qc` draw 12 of 20,
//! drawfirst 36 of 45 (tools/apexpov/export_defender_pov.py; the Casts' frame counts).
//!
//! | | holster_time | deploy_time | deployfirst_time |
//! |---|---|---|---|
//! | R-301 (`_base_assault_rifle.txt`, `mp_weapon_rspn101.txt`) | 0.55 | 0.6 | 1.1 |
//! | Charge Rifle (`mp_weapon_defender.txt`) | 0.5 | 0.8 | 1.5 |
//!
//! The R-301 is out at the start, drawn before: its first draw never plays. The slot the HUD
//! highlights changes when the new weapon starts coming out (推断: S3 tracks the active weapon).
//! Aiming waits for the drawn weapon too (推断, R5R 对照项). Pressing the slot already in hand does
//! nothing; pressing the other one during a switch starts a new switch from the weapon in hand.
//! The S3 engine's own switch code was not read (待定): the order holster -> deploy and the timings
//! are the settings' names taken at their word.

use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};

use crate::log;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Slot {
    R301 = 0,
    ChargeRifle = 1,
}

impl Slot {
    pub fn index(self) -> usize {
        self as usize
    }

    pub fn name(self) -> &'static str {
        match self {
            Slot::R301 => "Wingman",
            Slot::ChargeRifle => "Charge Rifle",
        }
    }
}

/// A weapon's switch timings (seconds) and its draws' ready-to-fire points (fractions of the draw).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Timing {
    pub holster: f32,
    pub deploy: f32,
    pub deploy_first: f32,
    pub ready: f32,
    pub ready_first: f32,
}

/// The Wingman in the R-301's slot (`mp_weapon_wingman.txt`: `holster_time` 0.36, `deploy_time` 0.4,
/// `deployfirst_time` 1.45; retail `wingman_base_v_animRig.qc`: draw's `AE_WPN_READYTOFIRE` 14 of 20
/// (21 frames), drawfirst's 41 of 48). The R-301's were 0.55 / 0.6 / 1.1, 12 of 25, 38 of 44.
pub const R301_TIMING: Timing = Timing { holster: 0.36, deploy: 0.4, deploy_first: 1.45, ready: 14.0 / 20.0, ready_first: 41.0 / 48.0 };
/// The sustained-discharge Charge Rifle (`mp_weapon_defender_sustained.txt`): `holster_time` 0.5,
/// `deploy_time` 0.8; `deployfirst_time` not set (the engine's 0): every draw the normal one (推断);
/// ready at `draw`'s AE_WPN_READYTOFIRE (retail QC frame 12 of 20).
pub const CHARGE_RIFLE_TIMING: Timing = Timing { holster: 0.5, deploy: 0.8, deploy_first: 0.8, ready: 12.0 / 20.0, ready_first: 12.0 / 20.0 };

pub fn timing(slot: Slot) -> Timing {
    match slot {
        Slot::R301 => R301_TIMING,
        Slot::ChargeRifle => CHARGE_RIFLE_TIMING,
    }
}

/// Where a switch is.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Phase {
    /// in hand and ready to fire (also between the ready frame and the draw's end: `Drawing`'s
    /// `ready` is true then)
    Ready(Slot),
    /// being put away: the cycle of its holster (0..1)
    Holstering { slot: Slot, cycle: f32 },
    /// coming out: the cycle of its draw (0..1), whether it is the first draw, whether it can fire
    Drawing { slot: Slot, cycle: f32, first: bool, ready: bool },
}

#[derive(Clone, Copy, Debug)]
struct Switch {
    from: Slot,
    to: Slot,
    /// seconds since it started; the holster of `from` then the draw of `to`
    t: f32,
    holster: f32,
    first: bool,
}

/// The slots and the switch between them (pure: offline tests).
#[derive(Clone, Copy, Debug)]
pub struct Loadout {
    /// the weapon in hand or coming out (the one being put away until its holster ends)
    active: Slot,
    switch: Option<Switch>,
    /// whether each slot's weapon has been drawn before (`deployfirst_time` only the first time)
    drawn: [bool; 2],
}

impl Default for Loadout {
    fn default() -> Self {
        Loadout { active: Slot::R301, switch: None, drawn: [true, false] }
    }
}

impl Loadout {
    pub fn active(&self) -> Slot {
        self.active
    }

    /// The slot the switch goes to (the active one when there is none).
    pub fn target(&self) -> Slot {
        self.switch.map_or(self.active, |s| s.to)
    }

    /// Asks for a slot (a key, the dev channel). Whether a switch started.
    pub fn request(&mut self, slot: Slot) -> bool {
        if slot == self.target() {
            return false;
        }
        // the weapon in hand: the one being put away while its holster lasts, else the active one
        let from = match self.switch {
            Some(s) if s.t < s.holster => s.from,
            _ => self.active,
        };
        if from == slot {
            // changed his mind during the put-away: it comes out again (a draw, not a first one)
            self.active = slot;
            self.switch = Some(Switch { from: slot, to: slot, t: 0.0, holster: 0.0, first: false });
            return true;
        }
        self.active = from;
        self.switch = Some(Switch { from, to: slot, t: 0.0, holster: timing(from).holster, first: !self.drawn[slot.index()] });
        true
    }

    pub fn step(&mut self, dt: f32) {
        let Some(mut s) = self.switch else { return };
        s.t += dt.max(0.0);
        if s.t >= s.holster {
            self.active = s.to;
            self.drawn[s.to.index()] = true;
        }
        let t = timing(s.to);
        let deploy = if s.first { t.deploy_first } else { t.deploy };
        self.switch = (s.t < s.holster + deploy).then_some(s);
    }

    pub fn phase(&self) -> Phase {
        let Some(s) = self.switch else { return Phase::Ready(self.active) };
        if s.t < s.holster {
            return Phase::Holstering { slot: s.from, cycle: (s.t / s.holster.max(1e-6)).clamp(0.0, 1.0) };
        }
        let t = timing(s.to);
        let (deploy, ready) = if s.first { (t.deploy_first, t.ready_first) } else { (t.deploy, t.ready) };
        let cycle = ((s.t - s.holster) / deploy.max(1e-6)).clamp(0.0, 1.0);
        Phase::Drawing { slot: s.to, cycle, first: s.first, ready: cycle >= ready }
    }

    /// Whether the active weapon can fire (and aim).
    pub fn ready(&self) -> bool {
        match self.phase() {
            Phase::Ready(_) => true,
            Phase::Drawing { ready, .. } => ready,
            Phase::Holstering { .. } => false,
        }
    }

    /// The weapon in hand comes out again (after an offhand that put it away: the shield battery),
    /// over its draw (not a first one).
    pub fn redraw(&mut self) {
        let slot = self.target();
        self.active = slot;
        self.switch = Some(Switch { from: slot, to: slot, t: 0.0, holster: 0.0, first: false });
    }

    pub fn describe(&self) -> String {
        match self.phase() {
            Phase::Ready(s) => format!("{} ready", s.name()),
            Phase::Holstering { slot, cycle } => format!("{} holstering {:.0} %, then {}", slot.name(), cycle * 100.0, self.target().name()),
            Phase::Drawing { slot, cycle, first, ready } => {
                format!("{} {} {:.0} %{}", slot.name(), if first { "first draw" } else { "draw" }, cycle * 100.0, if ready { ", ready" } else { "" })
            }
        }
    }
}

static LOADOUT: Mutex<Loadout> = Mutex::new(Loadout { active: Slot::R301, switch: None, drawn: [true, false] });

fn loadout() -> std::sync::MutexGuard<'static, Loadout> {
    LOADOUT.lock().unwrap_or_else(|e| e.into_inner())
}

pub fn active() -> Slot {
    loadout().active()
}

pub fn phase() -> Phase {
    loadout().phase()
}

/// Whether the active weapon can fire and aim (not mid-switch).
pub fn ready() -> bool {
    loadout().ready()
}

/// A slot asked for: by a key or the dev channel. What happened.
pub fn select(slot: Slot, by: &str) -> String {
    // the shield battery's use ends (D-032): S3's `AttemptCancelHeal` takes weaponSelectPrimary0/1
    super::battery::cancel(by);
    let started = loadout().request(slot);
    if !started {
        return format!("weapon ({by}): {} already {}", slot.name(), describe());
    }
    log(format!("weapons ({by}): switching to {}: {}", slot.name(), describe()));
    // the R-301 put away: its reload is off (the rifle's own update does the same for it)
    super::gun::holster_check();
    format!("weapon ({by}): {}", describe())
}

pub fn describe() -> String {
    loadout().describe()
}

/// The shield battery or the grenade is over (battery.rs, grenade.rs; `by` names it for the log):
/// the Charge Rifle, if it is the weapon in hand, comes out again (its draw: no shots before its
/// ready frame). The R-301's pull-out is their own (pov/ability.rs, pov/ordnance.rs).
pub fn redraw_after_offhand(by: &str) {
    let mut l = loadout();
    if l.target() == Slot::ChargeRifle {
        l.redraw();
        drop(l);
        log(format!("weapons: Charge Rifle out again after {by}: {}", describe()));
    }
}

/// Keys 1 and 2 last frame (their presses are edges).
static KEYS_WERE: Mutex<[bool; 3]> = Mutex::new([false; 3]);
/// The sounds of the phase changes already played (`Phase` index of the last frame).
static LAST_PHASE: Mutex<Option<Phase>> = Mutex::new(None);
static ANNOUNCED: AtomicBool = AtomicBool::new(false);

/// Keys 1 and 2 (Apex's PC defaults: `weaponSelectPrimary0/1`), only while the game window has the
/// focus (as input.rs `ability_keys`), and 5, the inspect. kbd.rs hides them from the game.
fn number_keys() -> Option<[bool; 3]> {
    use windows::Win32::System::Threading::GetCurrentProcessId;
    use windows::Win32::UI::Input::KeyboardAndMouse::GetAsyncKeyState;
    use windows::Win32::UI::WindowsAndMessaging::{GetForegroundWindow, GetWindowThreadProcessId};
    let mut pid = 0u32;
    unsafe { GetWindowThreadProcessId(GetForegroundWindow(), Some(&mut pid)) };
    if pid != unsafe { GetCurrentProcessId() } {
        return None;
    }
    let down = |vk: u8| unsafe { GetAsyncKeyState(vk as i32) } as u16 & 0x8000 != 0;
    Some([down(b'1'), down(b'2'), down(b'5')])
}

/// What the gun does this frame (gun.rs `update` reads it and calls `update`).
#[derive(Clone, Copy, Debug, Default)]
pub struct Trigger {
    pub fire: bool,
    pub aim: bool,
    /// the reload key, pressed (an edge)
    pub reload: bool,
}

/// Once a frame from gun.rs `update` (in the world, the gun on): the keys, the switch, the Charge
/// Rifle. Whether the R-301 sits this frame out (put away, coming out, or the Charge Rifle out).
pub fn update(dt: f32, t: Trigger) -> bool {
    if !ANNOUNCED.swap(true, Ordering::Relaxed) {
        log("weapons: slot 1 Wingman, slot 2 Charge Rifle (keys 1 / 2, dev `weapon 1|2`)");
    }
    if crate::fe::in_play_view() {
        let keys = number_keys().unwrap_or([false; 3]);
        let pressed = {
            let mut was = KEYS_WERE.lock().unwrap_or_else(|e| e.into_inner());
            let p = [keys[0] && !was[0], keys[1] && !was[1], keys[2] && !was[2]];
            *was = keys;
            p
        };
        if pressed[0] {
            log(select(Slot::R301, "key 1"));
        } else if pressed[1] {
            log(select(Slot::ChargeRifle, "key 2"));
        } else if pressed[2] && ready() {
            log(super::pov::start_inspect());
        }
    }
    let (phase, ready, active) = {
        let mut l = loadout();
        l.step(dt);
        (l.phase(), l.ready(), l.active())
    };
    phase_sounds(phase);
    // the rifle in hand: drawn or coming out (its put-away already ends a charge or a reload, as
    // gun.rs `holster_check` does the R-301's)
    // (nor while the shield battery has the hands: battery.rs; after it the rifle comes out again,
    // `redraw`)
    let rifle_in_hand = active == Slot::ChargeRifle
        && !matches!(phase, Phase::Holstering { .. })
        && !super::battery::busy()
        && !super::grenade::gun_away();
    super::chargerifle::update(dt, t, rifle_in_hand, rifle_in_hand && ready);
    active != Slot::R301 || !ready
}

/// The R-301's put-away and pull-out sounds (`ptpov_rspn101.qc`: `holster` frame 0
/// `Weapon_R101_UnEquip`, `draw` frame 0 `Weapon_R101_Equip`; tools/fuseaudio/export_audio.py
/// `--set defender`), each event's play actions together.
/// The Wingman's in the R-301's slot (`wingman_base_v_animRig.qc`: `holster` frame 0
/// `Weapon_Wingman_UnEquip`, `draw` frame 0 `Weapon_Wingman_Equip`; `--set wingman`).
const R301_UNEQUIP: [&str; 3] = ["weapon_wingman_unequip", "weapon_wingman_unequip_layer1", "weapon_wingman_unequip_layer2"];
const R301_EQUIP: [&str; 3] = ["weapon_wingman_equip", "weapon_wingman_equip_layer1", "weapon_wingman_equip_layer2"];
const R301_VOLUME: f32 = 0.5;

/// The holster and draw sounds as the phases begin (the view models' QCs: `holster` frame 0
/// `*_UnEquip`, `draw` frame 0 `*_Equip`, the Charge Rifle's `drawfirst` frame 1
/// `weapon_chargerifle_firstdraw_1p`).
fn phase_sounds(now: Phase) {
    let mut last = LAST_PHASE.lock().unwrap_or_else(|e| e.into_inner());
    let began = |p: Phase| match (p, *last) {
        (Phase::Holstering { slot, .. }, Some(Phase::Holstering { slot: s, .. })) => slot != s,
        (Phase::Holstering { .. }, _) => true,
        (Phase::Drawing { slot, .. }, Some(Phase::Drawing { slot: s, .. })) => slot != s,
        (Phase::Drawing { .. }, _) => true,
        _ => false,
    };
    if began(now) {
        match now {
            Phase::Holstering { slot: Slot::ChargeRifle, .. } => super::chargerifle::sound_holster(),
            Phase::Drawing { slot: Slot::ChargeRifle, first, .. } => super::chargerifle::sound_draw(first),
            Phase::Holstering { slot: Slot::R301, .. } => R301_UNEQUIP.iter().for_each(|n| crate::audio::play(n, R301_VOLUME)),
            Phase::Drawing { slot: Slot::R301, .. } => R301_EQUIP.iter().for_each(|n| crate::audio::play(n, R301_VOLUME)),
            _ => {}
        }
    }
    *last = Some(now);
}

/// The R-301 in the view model during and after a switch (pov/mod.rs): its put-away (`holster`, 16
/// frames, over the R-301's holster time), then held at its end (the arms lowered out of view) while
/// the Charge Rifle is out, its pull-out (`draw`, 26 frames, by crouch) over its deploy time; and
/// whether the R-301 shows (group 1). None: nothing to add (the R-301 in hand and ready).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct R301View {
    /// the R-301 clip (`holster` or `draw`), its cycle
    pub clip: &'static str,
    pub cycle: f32,
    pub shown: bool,
}

pub fn r301_view_of(p: Phase) -> Option<R301View> {
    match p {
        Phase::Ready(Slot::R301) => None,
        Phase::Drawing { slot: Slot::R301, cycle, .. } => Some(R301View { clip: "draw", cycle, shown: true }),
        Phase::Holstering { slot: Slot::R301, cycle } => Some(R301View { clip: "holster", cycle, shown: cycle < 1.0 }),
        // the Charge Rifle in hand: no view model of it yet (U3 stage 2), the R-301's arms kept down
        _ => Some(R301View { clip: "holster", cycle: 1.0, shown: false }),
    }
}

/// Zoom times (in, out: seconds) and the part of the zoom over which the field of view changes
/// (`ads_fov_zoomfrac_start` / `_end`) of the weapon in hand: R-301 0.27 / 0.23 (S3
/// `_base_assault_rifle.txt`), 0 .. 1 (S3 defaults); Charge Rifle 0.2 / 0.15, 0.25 .. 0.75
/// (`mp_weapon_defender.txt`). Both `zoom_fov` 55.
pub fn zoom() -> (f32, f32, f32, f32) {
    match active() {
        // the Wingman: `zoom_time_in` / `_out` 0.18 / 0.16, the default fractions
        Slot::R301 => (0.18, 0.16, 0.0, 1.0),
        Slot::ChargeRifle => (super::chargerifle::ZOOM_IN, super::chargerifle::ZOOM_OUT, super::chargerifle::ADS_FOV_FROM, super::chargerifle::ADS_FOV_TO),
    }
}

/// The weapon in hand's `zoom_fov` (4:3 horizontal degrees, camera.rs): the Wingman 60, the Charge
/// Rifle 55.
pub fn zoom_fov() -> f32 {
    match active() {
        Slot::R301 => 60.0,
        Slot::ChargeRifle => 55.0,
    }
}

/// The weapon in hand's view kick spring (`viewkick_spring`, springs.txt: stiffness and damping,
/// pitch / yaw / roll, hip then aimed) and `viewkick_*_weaponFraction` (hip, aimed): the Wingman's
/// `wingman`, 0.4 / 0.3; the Charge Rifle's `titan_arc`, 0.5 / 0.6 (chargerifle.rs).
pub fn kick_spring() -> ([glam::Vec3; 4], (f32, f32)) {
    use glam::Vec3;
    match active() {
        Slot::R301 => ([Vec3::new(120.0, 60.0, 150.0), Vec3::new(30.0, 30.0, 30.0), Vec3::new(100.0, 55.0, 150.0), Vec3::new(25.0, 25.0, 20.0)], (0.4, 0.3)),
        Slot::ChargeRifle => {
            use super::chargerifle::*;
            ([SPRING_K_HIP, SPRING_C_HIP, SPRING_K_ADS, SPRING_C_ADS], (WEAPON_FRACTION_HIP, WEAPON_FRACTION_ADS))
        }
    }
}

/// Whether the aim button counts this frame: held, and the weapon in hand drawn (推断).
pub fn aiming(held: bool) -> bool {
    held && ready()
}

/// What the HUD draws for the weapon in hand (gun.rs / chargerifle.rs state).
pub fn hud() -> Option<super::gun::HudState> {
    match active() {
        Slot::R301 => super::gun::hud(),
        Slot::ChargeRifle => super::chargerifle::hud(),
    }
}

/// Dev channel `weapon [1|2]`.
pub fn dev(args: &[&str]) -> String {
    match args.first().copied() {
        Some("1") => select(Slot::R301, "dev"),
        Some("2") => select(Slot::ChargeRifle, "dev"),
        None => format!("weapon: {} | {}", describe(), super::chargerifle::status()),
        _ => "usage: weapon [1|2]".into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const DT: f32 = 1.0 / 60.0;

    fn run(l: &mut Loadout, seconds: f32) {
        let mut t = 0.0;
        while t < seconds - 1e-6 {
            l.step(DT);
            t += DT;
        }
    }

    /// Wingman -> Charge Rifle: the Wingman put away over 0.36 s (no shots), the rifle's first draw
    /// (no `deployfirst_time` for the sustained rifle: a plain one) over 0.8 s, ready from 12/20 of it.
    #[test]
    fn switch_to_the_charge_rifle_and_back() {
        let mut l = Loadout::default();
        assert_eq!(l.phase(), Phase::Ready(Slot::R301));
        assert!(l.request(Slot::ChargeRifle));
        assert!(!l.request(Slot::ChargeRifle), "same slot again: nothing");
        run(&mut l, 0.3);
        assert!(matches!(l.phase(), Phase::Holstering { slot: Slot::R301, .. }) && !l.ready() && l.active() == Slot::R301);
        run(&mut l, 0.1);
        assert!(matches!(l.phase(), Phase::Drawing { slot: Slot::ChargeRifle, first: true, ready: false, .. }), "{:?}", l.phase());
        assert_eq!(l.active(), Slot::ChargeRifle);
        // ready at 0.36 + 0.8 x 12/20 = 0.84 s
        run(&mut l, 0.84 - 0.4 - 0.05);
        assert!(!l.ready(), "{:?}", l.phase());
        run(&mut l, 0.1);
        assert!(l.ready(), "{:?}", l.phase());
        run(&mut l, 0.5);
        assert_eq!(l.phase(), Phase::Ready(Slot::ChargeRifle));
        // back: the rifle away over 0.5 s, the Wingman drawn (not a first draw) over 0.4 s, ready at 14/20
        assert!(l.request(Slot::R301));
        run(&mut l, 0.45);
        assert!(matches!(l.phase(), Phase::Holstering { slot: Slot::ChargeRifle, .. }));
        run(&mut l, 0.1);
        assert!(matches!(l.phase(), Phase::Drawing { slot: Slot::R301, first: false, .. }));
        run(&mut l, 0.4 * 14.0 / 20.0 - 0.05 - 0.02);
        assert!(!l.ready());
        run(&mut l, 0.05);
        assert!(l.ready());
        // the rifle again: its plain draw now, ready at 0.36 + 0.8 x 12/20 = 0.84 s
        run(&mut l, 1.0);
        assert!(l.request(Slot::ChargeRifle));
        run(&mut l, 0.8);
        assert!(!l.ready() && matches!(l.phase(), Phase::Drawing { first: false, .. }));
        run(&mut l, 0.06);
        assert!(l.ready());
    }

    /// Back to the R-301 during its own put-away: it comes out again at once (a plain draw).
    #[test]
    fn change_of_mind_during_the_holster() {
        let mut l = Loadout::default();
        l.request(Slot::ChargeRifle);
        run(&mut l, 0.2);
        assert!(l.request(Slot::R301));
        assert!(matches!(l.phase(), Phase::Drawing { slot: Slot::R301, first: false, ready: false, .. }), "{:?}", l.phase());
        run(&mut l, 0.6);
        assert_eq!(l.phase(), Phase::Ready(Slot::R301));
        // the rifle was never drawn: its next draw is still the first
        l.request(Slot::ChargeRifle);
        run(&mut l, 0.6);
        assert!(matches!(l.phase(), Phase::Drawing { first: true, .. }));
    }

    /// The view model: the R-301's put-away shown to its end, then hidden with the arms held at it;
    /// its pull-out shown from the start.
    #[test]
    fn r301_view_through_a_switch() {
        assert_eq!(r301_view_of(Phase::Ready(Slot::R301)), None);
        let v = r301_view_of(Phase::Holstering { slot: Slot::R301, cycle: 0.5 }).unwrap();
        assert!(v.shown && v.clip == "holster" && v.cycle == 0.5);
        let v = r301_view_of(Phase::Drawing { slot: Slot::ChargeRifle, cycle: 0.2, first: true, ready: false }).unwrap();
        assert!(!v.shown && v.clip == "holster" && v.cycle == 1.0);
        let v = r301_view_of(Phase::Ready(Slot::ChargeRifle)).unwrap();
        assert!(!v.shown);
        let v = r301_view_of(Phase::Holstering { slot: Slot::ChargeRifle, cycle: 0.5 }).unwrap();
        assert!(!v.shown && v.cycle == 1.0);
        let v = r301_view_of(Phase::Drawing { slot: Slot::R301, cycle: 0.3, first: false, ready: false }).unwrap();
        assert!(v.shown && v.clip == "draw" && v.cycle == 0.3);
    }
}
