//! The game's own HUD (its "front end", Scaleform) next to ours (M0 HUD, D-015): hidden during
//! play (`hud_hide = 1`), since the Apex-style HUD replaces it, and read for what it knows that
//! the Apex HUD shows (boss names and health).
//!
//! Why hide it: the floating enemy tags and the lock-on dot project with the game's own camera, so
//! with the over-the-shoulder camera they sit above their targets (camera.rs); the HP/FP/stamina
//! bars are the hidden Tarnished's, not Fuse's.
//!
//! Seen in game (2026-10-03): `hud_state = HideAll` hides all of it (bars, equipment, compass,
//! runes, enemy tags, lock-on dot); prompts and messages stay. Hiding single parts through the
//! tag/equipment flags (`is_visible`, `enable_equip_hud`, before and after MenuMan) does nothing:
//! the game rebuilds them inside MenuMan and hands them to Scaleform there.
//!
//! Seen in game (2026-10-04): with HideAll the game leaves the boss bar's name empty (it fills it
//! in MenuMan only while the HUD shows); `hud_state` stays as set (the game changes it only when
//! menus open and close). So while a boss's name is missing, the state goes back to Default just
//! around MenuMan (WorldChrMan_PostPhysics -> GameFlowStep_Post) and the name is kept per boss.

use std::collections::HashMap;
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, AtomicU8, Ordering};

use eldenring::cs::{CSFeManHudState, CSFeManImp, CSMenuManImp, WorldChrMan};
use fromsoftware_shared::FromStatic;

use crate::{log, paths, state};

/// 0 unknown yet, 1 shown, 2 hidden: the ini `hud_hide`, changed by the dev command `fe hide`.
static HIDE: AtomicU8 = AtomicU8::new(0);

fn hidden() -> bool {
    match HIDE.load(Ordering::Relaxed) {
        0 => {
            let h = paths::flag("hud_hide");
            HIDE.store(if h { 2 } else { 1 }, Ordering::Relaxed);
            h
        }
        v => v == 2,
    }
}

/// Boss names seen so far, by the boss's handle (selector, block id).
static NAMES: Mutex<Option<HashMap<(u32, i32), String>>> = Mutex::new(None);
/// The HUD state was set back to Default for this MenuMan, to have it fill a boss's name.
static PEEKING: AtomicBool = AtomicBool::new(false);

fn key(h: &eldenring::cs::FieldInsHandle) -> (u32, i32) {
    (h.selector.0, h.block_id.0)
}

/// Before MenuMan (WorldChrMan_PostPhysics): the game's HUD off during play (menus switch to
/// ShowAll / PopupMenu, left alone); on just for this MenuMan while a boss's name is missing.
pub fn before_menu() {
    if !hidden() || !state::in_world() {
        return;
    }
    let Ok(fe) = (unsafe { CSFeManImp::instance_mut() }) else { return };
    let names = NAMES.lock().unwrap_or_else(|e| e.into_inner());
    let missing = fe.boss_health_displays.iter().any(|d| !d.field_ins_handle.is_empty() && !names.as_ref().is_some_and(|n| n.contains_key(&key(&d.field_ins_handle))));
    if missing && fe.hud_state == CSFeManHudState::HideAll {
        fe.hud_state = CSFeManHudState::Default;
        PEEKING.store(true, Ordering::Relaxed);
    } else if fe.hud_state == CSFeManHudState::Default {
        fe.hud_state = CSFeManHudState::HideAll;
    }
}

/// After MenuMan (GameFlowStep_Post), before Scaleform draws: keep the names it filled, HUD off.
pub fn after_menu() {
    if !hidden() || !state::in_world() {
        return;
    }
    let Ok(fe) = (unsafe { CSFeManImp::instance_mut() }) else { return };
    {
        let mut names = NAMES.lock().unwrap_or_else(|e| e.into_inner());
        let names = names.get_or_insert_with(HashMap::new);
        for (d, t) in fe.boss_health_displays.iter().zip(fe.frontend_values.boss_list_tag_data.iter()) {
            let name = t.chr_name.to_string();
            if !d.field_ins_handle.is_empty() && !name.is_empty() {
                if names.insert(key(&d.field_ins_handle), name.clone()).is_none() {
                    log(format!("fe: boss name \"{name}\" (peeked {})", PEEKING.load(Ordering::Relaxed)));
                }
            }
        }
    }
    PEEKING.store(false, Ordering::Relaxed);
    if fe.hud_state == CSFeManHudState::Default {
        fe.hud_state = CSFeManHudState::HideAll;
    }
}

/// The popup menu's top menu job (a private field at 0xb0 of `CSPopupMenu`, fromsoftware-rs
/// layout): 0 in play, set while the map or a menu is open. Seen in game 2026-10-04: 0 in play,
/// set with the map and with the pause menu; the menu manager's `ui_states` did not do (element
/// 19, the first candidate, is the interaction prompt; the map changes no `hud_state`).
fn top_menu_job() -> Option<usize> {
    let m = unsafe { CSMenuManImp::instance() }.ok()?;
    let p = m.popup_menu?.as_ptr() as *const u8;
    Some(unsafe { *(p.add(0xb0) as *const usize) })
}

/// Whether the game shows its play view, not the map or a menu. True when unknown.
pub fn in_play_view() -> bool {
    top_menu_job().is_none_or(|job| job == 0)
}

/// A boss health bar the game is showing (hidden or not): its name in the player's language, its
/// health and the damage it took last.
pub struct Boss {
    /// The character's handle (selector, block): which boss this is from frame to frame.
    pub key: (u32, i32),
    pub name: String,
    pub hp: u32,
    pub hp_max: u32,
    pub damage: i32,
}

/// The bosses whose bars the game shows (Godrick: one).
pub fn bosses() -> Vec<Boss> {
    let Ok(fe) = (unsafe { CSFeManImp::instance() }) else { return Vec::new() };
    let wcm = unsafe { WorldChrMan::instance() }.ok();
    fe.boss_health_displays
        .iter()
        .zip(fe.frontend_values.boss_list_tag_data.iter())
        .filter(|(d, _)| !d.field_ins_handle.is_empty())
        .map(|(d, t)| {
            let chr = wcm.and_then(|w| w.chr_ins_by_handle(&d.field_ins_handle));
            let (hp, hp_max) = chr.map_or((t.hp, t.hp_max_uncapped), |c| (c.modules.data.hp.max(0) as u32, c.modules.data.max_hp.max(0) as u32));
            let name = NAMES.lock().unwrap_or_else(|e| e.into_inner()).as_ref().and_then(|n| n.get(&key(&d.field_ins_handle)).cloned());
            Boss { key: key(&d.field_ins_handle), name: name.unwrap_or_else(|| t.chr_name.to_string()), hp, hp_max, damage: d.damage_taken }
        })
        .collect()
}

/// Dev channel `fe [hide on|off]`: whether the game's HUD is hidden, its enemy tags and bosses.
pub fn command(args: &[&str]) -> String {
    if let ["hide", v] = args {
        let on = matches!(*v, "on" | "1");
        HIDE.store(if on { 2 } else { 1 }, Ordering::Relaxed);
        if !on {
            if let Ok(fe) = unsafe { CSFeManImp::instance_mut() } {
                if fe.hud_state == CSFeManHudState::HideAll {
                    fe.hud_state = CSFeManHudState::Default;
                }
            }
        }
    }
    let Ok(fe) = (unsafe { CSFeManImp::instance() }) else { return "no CSFeMan".into() };
    let tags: Vec<String> = fe
        .enemy_chr_tag_displays
        .iter()
        .filter(|e| !e.field_ins_handle.is_empty())
        .map(|e| format!("[screen {:.0},{:.0} dmg {}]", e.screen_pos.0, e.screen_pos.1, e.damage_taken))
        .collect();
    let bosses: Vec<String> = bosses().iter().map(|b| format!("[{} {}/{} dmg {}]", b.name, b.hp, b.hp_max, b.damage)).collect();
    // which of the menu manager's UI elements are on screen (to tell a menu or the map from play)
    let ui = unsafe { CSMenuManImp::instance() }.map_or("-".into(), |m| {
        let v: Vec<String> = m.ui_states.iter().enumerate().filter(|(_, u)| u.visible()).map(|(i, _)| i.to_string()).collect();
        v.join(",")
    });
    let job = top_menu_job().map_or("-".into(), |j| format!("{j:#x}"));
    let s = format!("game hud hidden {}; hud_state {:?}; ui visible [{ui}]; top menu job {job}; enemy tags {}; bosses {}", hidden(), fe.hud_state, tags.join(" "), bosses.join(" "));
    log(format!("fe: {s}"));
    s
}
