//! The shield battery (D-032; plan docs/plan/plan-shield-battery.md), by Season 3's consumable
//! (R5R `mp_ability_consumable.txt` mod `shield_large` and `mp_ability_consumable.nut`; the current
//! game's export `apex-data/export/weapon/mp_ability_consumable.txt` has the same values):
//!
//! - Key 4 (S3 `+scriptCommand4`, the survival slot; dev `battery`). Endless (the user's choice):
//!   no count, the HUD shows ∞.
//! - Not with the shield full (`TryUseConsumable`: DENY_SHIELD_FULL, "#DENY_SHIELD_FULL"; with no
//!   armour DENY_NO_SHIELDS).
//! - The battery comes out over the consumable's `raise_time` 1.0 s, then charges for its
//!   `charge_time` 4.0 s (`OnWeaponChargeBegin_Consumable` plays `chargeSoundName`); the charge's end
//!   fires it (`charge_end_forces_fire`): the shield is filled (`shieldAmount` 999, capped by the
//!   armour's; `UpdateConsumableUse`) and the fire sounds play (`fire_sound_1_player_1p`,
//!   `fire_sound_2_player_1p`).
//! - Meanwhile no sprint (`offhand_blocks_sprint`) and the primary weapon is away
//!   (`offhand_keep_primary_in_hand` 0): no shots.
//! - Cancelled (S3 `AttemptCancelHeal`, cl_survival_loot.nut) by `+attack`, `+speed`,
//!   `weaponSelectPrimary0/1` (keys 1, 2: weapons.rs) and by another offhand (Q, Z: octane.rs); then the charge
//!   sound stops and `cancelSoundName` plays (`OnWeaponDeactivate_Consumable`). Damage does not
//!   cancel it; death does, silently.
//!
//! Timing is wall-clock, like octane.rs (the game does not pause behind its menus).

use std::sync::Mutex;
use std::time::Instant;

use crate::log;
use crate::spike::lethal;

/// S3 `raise_time` (the consumable's base; `shield_large` keeps it) and `charge_time`.
pub const RAISE: f32 = 1.0;
pub const CHARGE: f32 = 4.0;
/// From the key to the shield.
pub const USE_SECONDS: f32 = RAISE + CHARGE;

/// How long a refusal stays on the HUD (ours; S3 shows it as a hint).
const DENY_SECONDS: f32 = 2.0;

/// The battery's sounds (play names of the audio export, lower case): `charge_sound_1p`, the two
/// fire sounds and `cancelSoundName`.
const SOUND_VOLUME: f32 = 0.5;
const CHARGE_SOUND: &str = "shield_battery_charge";
const FIRE_SOUNDS: [&str; 2] = ["shield_battery_primary", "shield_battery_holster"];
const CANCEL_SOUND: &str = "shield_battery_failure";
/// The view model's QC sounds (T021, ptpov_shield_battery_held.qc): `raise` frames 0 and 25 (the
/// raise is played over RAISE: frame 25 of 31 intervals), `charge` frame 10.
const FOLEY: [(&str, f32); 3] = [
    ("shieldbattery_drawfoley_fr02", 0.0),
    ("shieldbattery_drawfoley_fr27", 25.0 / 31.0 * RAISE),
    ("shieldbattery_drawfoley_fr49", RAISE + 10.0 / 30.0),
];

/// The localization keys the HUD shows (S3 `GetCanUseResultString`).
pub const DENY_SHIELD_FULL: &str = "#DENY_SHIELD_FULL";
pub const DENY_NO_SHIELDS: &str = "#DENY_NO_SHIELDS";

/// Where a use is at `t` seconds after the key.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Phase {
    /// the battery coming out
    Raise,
    /// charging, `0..1`
    Charge(f32),
    /// the charge is over: the shield is due
    Fire,
}

pub fn phase(t: f32) -> Phase {
    if t < RAISE {
        Phase::Raise
    } else if t < USE_SECONDS {
        Phase::Charge(((t - RAISE) / CHARGE).clamp(0.0, 1.0))
    } else {
        Phase::Fire
    }
}

/// Why a use is refused, if it is: the shield and its capacity.
pub fn refusal(shield: f32, max: f32) -> Option<&'static str> {
    if max <= 0.0 {
        Some(DENY_NO_SHIELDS)
    } else if shield >= max {
        Some(DENY_SHIELD_FULL)
    } else {
        None
    }
}

struct Battery {
    /// when the key started the use (None: not in use)
    started: Option<Instant>,
    /// the charge has begun (its sound is playing)
    charging: bool,
    /// keys last frame: 4, sprint
    last_use: bool,
    last_sprint: bool,
    uses: u32,
    cancels: u32,
    /// a refusal on the HUD and since when
    deny: Option<(&'static str, Instant)>,
    /// the last use's end and whether it filled the shield
    ended: Option<(Instant, bool)>,
}

static BATTERY: Mutex<Battery> = Mutex::new(Battery {
    started: None,
    charging: false,
    last_use: false,
    last_sprint: false,
    uses: 0,
    cancels: 0,
    deny: None,
    ended: None,
});

/// The lock is never held while calling another module (gun.rs and kcc.rs ask `busy` while they
/// hold theirs).
fn battery() -> std::sync::MutexGuard<'static, Battery> {
    BATTERY.lock().unwrap_or_else(|e| e.into_inner())
}

fn sound(name: &'static str) {
    crate::audio::play(name, SOUND_VOLUME);
}

fn alive_in_play() -> bool {
    crate::state::in_world() && crate::fe::in_play_view() && !lethal::fuse_hp().is_some_and(|hp| hp <= 0.0)
}

/// Once a frame (after octane.rs, before the movement controller): the keys, the charge, the fire.
pub fn update() {
    if !crate::state::in_world() || lethal::fuse_hp().is_some_and(|hp| hp <= 0.0) {
        // left the world or died: the use ends without its sound (S3: the weapon is gone)
        let mut b = battery();
        if b.started.take().is_some() {
            b.charging = false;
            drop(b);
            crate::audio::stop(CHARGE_SOUND);
            log("battery: use ended (out of the world or down)");
        }
        return;
    }
    // (keys 1 / 2 cancel through the weapon slots: weapons.rs `select`)
    let keys = crate::input::battery_keys().unwrap_or_default();
    let sprint = crate::input::move_keys().is_some_and(|k| k.sprint)
        || crate::input::move_pad().is_some_and(|p| p.buttons & 0x0040 != 0);
    let (use_pressed, sprint_pressed) = {
        let mut b = battery();
        let edges = (keys.use_key && !b.last_use, sprint && !b.last_sprint);
        (b.last_use, b.last_sprint) = (keys.use_key, sprint);
        edges
    };
    let in_play = crate::fe::in_play_view();
    let t = battery().started.map(|s| s.elapsed().as_secs_f32());
    match t {
        Some(_) if in_play && sprint_pressed => {
            cancel("sprint");
        }
        Some(t) => match phase(t) {
            Phase::Raise => {}
            Phase::Charge(_) => {
                let begin = !std::mem::replace(&mut battery().charging, true);
                if begin {
                    sound(CHARGE_SOUND);
                }
            }
            Phase::Fire => fire(),
        },
        None if in_play && use_pressed => {
            log(format!("battery: {}", use_battery("key 4")));
        }
        None => {}
    }
}

/// Starts a use if it can (the key or the dev channel); what happened.
pub fn use_battery(by: &str) -> String {
    if !alive_in_play() {
        return format!("({by}) needs a living player in play");
    }
    if battery().started.is_some() {
        return format!("({by}) already in use");
    }
    let Some((shield, max)) = lethal::shield() else {
        return format!("({by}) no Apex health (lethal_guard off)");
    };
    if let Some(why) = refusal(shield, max) {
        battery().deny = Some((why, Instant::now()));
        return format!("({by}) refused: {why} (shield {shield:.0}/{max:.0})");
    }
    {
        let mut b = battery();
        b.started = Some(Instant::now());
        b.charging = false;
        b.uses += 1;
        b.deny = None;
    }
    // the primary goes away (a reload stops: S3 switches weapons); a frag grenade not yet thrown is
    // put away; the stim's injector, if the left hand still holds it, goes with its throw's sound
    let nade = super::grenade::cancel("battery");
    if nade.ends_with("put away") {
        log(nade);
    }
    super::gun::interrupt_reload();
    super::octane::drop_injector();
    for (name, at) in FOLEY {
        crate::audio::play_in(name, SOUND_VOLUME, at);
    }
    let vm = super::pov::start_ability(super::pov::AbilityKind::Battery).unwrap_or_else(|| "pov: no view model".into());
    format!("({by}) using: shield {shield:.0}/{max:.0}, full in {USE_SECONDS} s; {vm}")
}

/// The charge's end: the shield filled.
fn fire() {
    let uses = {
        let mut b = battery();
        if b.started.take().is_none() {
            return;
        }
        b.charging = false;
        b.ended = Some((Instant::now(), true));
        b.uses
    };
    for name in FIRE_SOUNDS {
        sound(name);
    }
    super::weapons::redraw_after_offhand("the battery");
    match lethal::fill_shield() {
        Some((before, after)) => log(format!("battery: use {uses}: shield {before:.1} -> {after:.1}")),
        None => log(format!("battery: use {uses}: no shield to fill (guard off or down)")),
    }
}

/// Cancels a use in progress (fire, sprint, keys 1/2, the stim or the pad, the dev channel): the
/// charge sound stops, the failure sound plays, the view model puts the battery away. False when
/// there was none.
pub fn cancel(by: &str) -> bool {
    let (t, cancels) = {
        let mut b = battery();
        let Some(s) = b.started.take() else { return false };
        b.charging = false;
        b.cancels += 1;
        b.ended = Some((Instant::now(), false));
        (s.elapsed().as_secs_f32(), b.cancels)
    };
    crate::audio::stop(CHARGE_SOUND);
    for (name, _) in FOLEY {
        crate::audio::stop(name);
    }
    sound(CANCEL_SOUND);
    super::pov::cancel_battery();
    super::weapons::redraw_after_offhand("the battery");
    log(format!("battery: cancelled by {by} at {t:.2} s (cancel {cancels})"));
    true
}

/// A use is in progress: no shots, no sprint.
pub fn busy() -> bool {
    battery().started.is_some()
}

/// For the HUD.
#[derive(Clone, Copy, Debug, Default)]
pub struct Hud {
    /// seconds into the use in progress
    pub using: Option<f32>,
    /// a refusal (its localization key) and how long ago
    pub deny: Option<(&'static str, f32)>,
}

pub fn hud() -> Hud {
    let b = battery();
    Hud {
        using: b.started.map(|s| s.elapsed().as_secs_f32()),
        deny: b.deny.map(|(k, at)| (k, at.elapsed().as_secs_f32())).filter(|(_, age)| *age < DENY_SECONDS),
    }
}

/// Dev channel `battery [cancel]`.
pub fn dev(args: &[&str]) -> String {
    match args.first().copied() {
        Some("cancel") => format!("battery: {}", if cancel("dev") { "cancelled" } else { "not in use" }),
        Some("status") => status(),
        _ => format!("battery: {}", use_battery("dev")),
    }
}

pub fn status() -> String {
    let b = battery();
    let state = match b.started.map(|s| s.elapsed().as_secs_f32()) {
        Some(t) => format!("in use {t:.2} s ({:?})", phase(t)),
        None => "idle".into(),
    };
    let last = b.ended.map_or("none".into(), |(at, ok)| {
        format!("{} {:.1} s ago", if ok { "filled" } else { "cancelled" }, at.elapsed().as_secs_f32())
    });
    format!("battery {state}, uses {}, cancels {}, last {last}", b.uses, b.cancels)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Out over 1 s, charging over the next 4 s, the shield at 5 s.
    #[test]
    fn raise_then_charge_then_fire() {
        assert_eq!(phase(0.0), Phase::Raise);
        assert_eq!(phase(0.99), Phase::Raise);
        assert_eq!(phase(1.0), Phase::Charge(0.0));
        assert_eq!(phase(3.0), Phase::Charge(0.5));
        assert_eq!(phase(5.0), Phase::Fire);
        assert_eq!(USE_SECONDS, 5.0);
    }

    /// A full shield refuses, no armour refuses, anything less goes.
    #[test]
    fn refused_only_when_full_or_unarmoured() {
        assert_eq!(refusal(100.0, 100.0), Some(DENY_SHIELD_FULL));
        assert_eq!(refusal(0.0, 0.0), Some(DENY_NO_SHIELDS));
        assert_eq!(refusal(99.5, 100.0), None);
        assert_eq!(refusal(0.0, 100.0), None);
    }
}
