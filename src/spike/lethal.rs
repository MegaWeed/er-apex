//! Spike S8: the Tarnished only dies when Fuse's own HP runs out (audit #8: refilling HP after a
//! hit can't undo a hit that already killed; the death has to be prevented before it happens).
//!
//! While Fuse lives, the player's "no death" debug flag is held every frame: the game still
//! applies every hit (stagger, effects, the numbers) but keeps the Tarnished at 1 HP or more. Each
//! drop of the Tarnished's HP becomes Fuse damage (the same share of Fuse's HP as the hit took of
//! the Tarnished's max HP, times `fuse_damage_scale`), then the Tarnished is refilled. At 0 Fuse HP
//! the flag is dropped and the Tarnished's HP set to 0: the game's own death and respawn follow.
//!
//! Shields (D-032): the hit's Apex damage goes to the shield first and only what it cannot take to
//! health (S3: no damage passes a shield that holds). The shield is the armour's, tier
//! `shield_tier` (default 3, a purple body shield: 100); it is full at the start and after a respawn
//! (ours: S3 starts without armour). The shield battery fills it (battery.rs).
//!
//! The flag: CSChrDataModule+0x19B, bit 0 = no death, bit 1 = no damage (TGA table "NoDead" /
//! "NoDamage": WorldChrMan -> main player -> modules+0x190 -> data module -> +0x19B; fromsoftware-rs
//! documents the byte as the data module's debug flags).

use std::sync::Mutex;
use std::time::Instant;

use eldenring::cs::WorldChrMan;
use fromsoftware_shared::FromStatic;

use crate::{log, paths, state};

const DEBUG_FLAGS: usize = 0x19B;
const NO_DEAD: u8 = 1 << 0;

/// Fuse's health (Apex units, 100 like `health` in the player settings).
pub const FUSE_MAX_HP: f32 = 100.0;

/// S3 `SURVIVAL_GetArmorShieldCapacity` (sh_survival_loot.gnut): the shield of armour tiers 0-4.
const SHIELD_BY_TIER: [f32; 5] = [0.0, 50.0, 75.0, 100.0, 100.0];
/// The user's choice (D-032): a purple body shield.
const SHIELD_TIER: usize = 3;

struct Guard {
    fuse_hp: f32,
    /// the shield (Apex units); negative until the first frame fills it
    shield: f32,
    /// the Tarnished's HP after our last refill
    last_hp: i32,
    dead: bool,
    hits: u32,
    /// the last hit (or HP Octane's stim cost), for the passive's delay
    last_damage: Option<Instant>,
    /// the last hit that reached health (the HUD's red)
    last_health_damage: Option<Instant>,
}

static GUARD: Mutex<Guard> = Mutex::new(Guard {
    fuse_hp: FUSE_MAX_HP,
    shield: -1.0,
    last_hp: -1,
    dead: false,
    hits: 0,
    last_damage: None,
    last_health_damage: None,
});

/// The shield's capacity: the armour tier's (ini `shield_tier` 0-4, default 3).
pub fn shield_max() -> f32 {
    SHIELD_BY_TIER[paths::number::<usize>("shield_tier").unwrap_or(SHIELD_TIER).min(4)]
}

/// A hit of `dmg` (Apex units) on `shield`: what the shield takes, what health takes.
fn split(shield: f32, dmg: f32) -> (f32, f32) {
    let to_shield = dmg.min(shield.max(0.0));
    (to_shield, dmg - to_shield)
}

pub fn enabled() -> bool {
    paths::flag("lethal_guard")
}

fn scale() -> f32 {
    paths::number::<f32>("fuse_damage_scale").unwrap_or(1.0)
}

/// The data module's debug flag byte.
fn flags_ptr(data: &mut eldenring::cs::CSChrDataModule) -> *mut u8 {
    (data as *mut _ as usize + DEBUG_FLAGS) as *mut u8
}

/// Once per frame, after the game's damage for the frame is applied (ChrIns_PostPhysics).
pub fn update() {
    if !enabled() {
        return;
    }
    let Some(p) = (unsafe { WorldChrMan::instance_mut() }).ok().and_then(|w| w.main_player.as_mut()) else {
        return;
    };
    // who hit the Tarnished last (for the HUD's damage indicator)
    let by = p.chr_ins.last_hit_by.clone();
    let data = &mut p.chr_ins.modules.data;
    let mut g = GUARD.lock().unwrap_or_else(|e| e.into_inner());
    let flags = flags_ptr(data);
    if g.dead {
        // back after the respawn: the game refilled the Tarnished, Fuse starts over
        if state::in_world() && data.hp > 0 && data.hp == data.max_hp {
            let shield = shield_max();
            log(format!("lethal: respawned with {} HP; Fuse back to {FUSE_MAX_HP}, shield {shield}", data.hp));
            *g = Guard {
                fuse_hp: FUSE_MAX_HP,
                shield,
                last_hp: data.hp,
                dead: false,
                hits: 0,
                last_damage: None,
                last_health_damage: None,
            };
        }
        return;
    }
    if g.shield < 0.0 {
        g.shield = shield_max();
    }
    unsafe { *flags |= NO_DEAD };
    if g.last_hp < 0 || data.max_hp <= 0 {
        g.last_hp = data.hp;
        return;
    }
    let lost = g.last_hp - data.hp;
    if lost > 0 {
        let share = lost as f32 / data.max_hp as f32;
        let dmg = share * FUSE_MAX_HP * scale();
        let (to_shield, to_health) = split(g.shield, dmg);
        let shield_before = g.shield;
        g.shield -= to_shield;
        g.fuse_hp -= to_health;
        g.hits += 1;
        let now = Instant::now();
        g.last_damage = Some(now);
        if to_health > 0.0 {
            g.last_health_damage = Some(now);
        }
        super::stats::took(dmg, by);
        log(format!(
            "lethal: hit {}: Tarnished -{lost} of {} max (hp {} -> {}), Apex -{dmg:.1}: shield {shield_before:.1} -> {:.1}{}, Fuse -{to_health:.1} -> {:.1}",
            g.hits,
            data.max_hp,
            g.last_hp,
            data.hp,
            g.shield,
            if to_shield > 0.0 && g.shield <= 0.0 { " (broken)" } else { "" },
            g.fuse_hp.max(0.0)
        ));
        if g.fuse_hp <= 0.0 {
            // Fuse is down: the Tarnished goes with the game's own death
            unsafe { *flags &= !NO_DEAD };
            data.hp = 0;
            g.dead = true;
            g.last_hp = 0;
            log("lethal: Fuse is out of health: no-death flag off, Tarnished HP 0");
            return;
        }
        data.hp = data.max_hp;
    }
    g.last_hp = data.hp;
}

/// Dev channel status line.
pub fn status() -> String {
    let g = GUARD.lock().unwrap_or_else(|e| e.into_inner());
    let flag = (unsafe { WorldChrMan::instance_mut() })
        .ok()
        .and_then(|w| w.main_player.as_mut())
        .map(|p| unsafe { *flags_ptr(&mut p.chr_ins.modules.data) });
    format!(
        "fuse hp {:.1}/{FUSE_MAX_HP}, shield {:.1}/{}, hits {}, dead {}, debug flags {:?}",
        g.fuse_hp.max(0.0),
        g.shield.max(0.0),
        shield_max(),
        g.hits,
        g.dead,
        flag
    )
}

/// The shield and its capacity for the HUD (None when the guard is off).
pub fn shield() -> Option<(f32, f32)> {
    enabled().then(|| {
        let g = GUARD.lock().unwrap_or_else(|e| e.into_inner());
        let max = shield_max();
        (if g.shield < 0.0 { max } else { g.shield.min(max) }, max)
    })
}

/// Sets the shield (dev channel), within its capacity.
pub fn set_shield(v: f32) {
    GUARD.lock().unwrap_or_else(|e| e.into_inner()).shield = v.clamp(0.0, shield_max());
}

/// Fills the shield (the battery: S3 `shieldAmount` 999, up to the capacity): before and after;
/// None with the guard off or Fuse down.
pub fn fill_shield() -> Option<(f32, f32)> {
    if !enabled() {
        return None;
    }
    let mut g = GUARD.lock().unwrap_or_else(|e| e.into_inner());
    if g.dead || g.fuse_hp <= 0.0 {
        return None;
    }
    let max = shield_max();
    let before = if g.shield < 0.0 { max } else { g.shield };
    g.shield = max;
    Some((before, max))
}

/// Apex damage that does not come through the Tarnished's HP (the frag grenade on its thrower,
/// grenade.rs): the shield first, then health, as a hit; at 0 health the Tarnished's HP goes to 0 so
/// `update` lets the game's own death follow. What the shield and health took and whether it
/// killed; None with the guard off or Fuse down.
pub fn take(dmg: f32) -> Option<(f32, f32, bool)> {
    if !enabled() {
        return None;
    }
    let mut g = GUARD.lock().unwrap_or_else(|e| e.into_inner());
    if g.dead || g.fuse_hp <= 0.0 {
        return None;
    }
    if g.shield < 0.0 {
        g.shield = shield_max();
    }
    let (to_shield, to_health) = split(g.shield, dmg.max(0.0));
    g.shield -= to_shield;
    g.fuse_hp -= to_health;
    g.hits += 1;
    let now = Instant::now();
    g.last_damage = Some(now);
    if to_health > 0.0 {
        g.last_health_damage = Some(now);
    }
    let died = g.fuse_hp <= 0.0;
    drop(g);
    if died
        && let Some(p) = (unsafe { WorldChrMan::instance_mut() }).ok().and_then(|w| w.main_player.as_mut())
    {
        p.chr_ins.modules.data.hp = 0;
    }
    Some((to_shield, to_health, died))
}

/// Seconds since the last hit that reached health (None: none since the start or the respawn).
pub fn since_health_damage() -> Option<f32> {
    GUARD.lock().unwrap_or_else(|e| e.into_inner()).last_health_damage.map(|t| t.elapsed().as_secs_f32())
}

/// Fuse's HP for the HUD (None when the guard is off).
pub fn fuse_hp() -> Option<f32> {
    enabled().then(|| GUARD.lock().unwrap_or_else(|e| e.into_inner()).fuse_hp.max(0.0))
}

/// Sets Fuse's HP (dev channel).
pub fn set_fuse_hp(hp: f32) {
    GUARD.lock().unwrap_or_else(|e| e.into_inner()).fuse_hp = hp;
}

/// Seconds since the last hit or `mark_damage` (None: none since the start or the last respawn).
pub fn since_damage() -> Option<f32> {
    GUARD.lock().unwrap_or_else(|e| e.into_inner()).last_damage.map(|t| t.elapsed().as_secs_f32())
}

/// Counts as damage now, for the passive's delay (S3's stim sets `lastDamageTime`,
/// mp_ability_heal.nut).
pub fn mark_damage() {
    let mut g = GUARD.lock().unwrap_or_else(|e| e.into_inner());
    let now = Instant::now();
    g.last_damage = Some(now);
    // the stim's cost is health (the HUD's red)
    g.last_health_damage = Some(now);
}

/// Heals Fuse's HP up to `FUSE_MAX_HP` (Octane's passive): the HP before and after; None with the
/// guard off or Fuse down.
pub fn heal(amount: f32) -> Option<(f32, f32)> {
    if !enabled() {
        return None;
    }
    let mut g = GUARD.lock().unwrap_or_else(|e| e.into_inner());
    if g.dead || g.fuse_hp <= 0.0 {
        return None;
    }
    let before = g.fuse_hp;
    g.fuse_hp = (before + amount).min(FUSE_MAX_HP);
    Some((before, g.fuse_hp))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The shield takes the hit first; only the rest reaches health; a broken shield takes nothing.
    #[test]
    fn shield_takes_the_hit_first() {
        assert_eq!(split(100.0, 30.0), (30.0, 0.0));
        assert_eq!(split(20.0, 30.0), (20.0, 10.0));
        assert_eq!(split(0.0, 30.0), (0.0, 30.0));
        assert_eq!(split(-1.0, 5.0), (0.0, 5.0));
        assert_eq!(SHIELD_BY_TIER[SHIELD_TIER], 100.0);
    }
}
