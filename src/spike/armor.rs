//! S3 armor-loading harness. Native equip/give calls and hide accessors adapted
//! from er-mario (MIT, Copyright (c) 2026 Delta). Test save only.

use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};
use eldenring::cs::{GameDataMan, MapItemMan, PlayerIns, EquipParamProtector, SoloParamRepository, WorldChrMan};
use fromsoftware_shared::FromStatic;
use crate::{log, scan, state};

const PROTECTOR: u32 = 0x1000_0000;
const IDS: [u32; 4] = [660000, 660100, 660200, 660300];
const BARE: [u32; 4] = [10000, 10100, 10200, 10300];
type EquipFn = unsafe extern "C" fn(usize, u32, *const u32, u32, u64, u64, u64) -> u64;
type GiveFn = unsafe extern "C" fn(usize, *const u8, *mut u8, u64) -> u64;
struct Funcs { equip: EquipFn, give: GiveFn }
static FUNCS: OnceLock<Option<Funcs>> = OnceLock::new();
static ORIGINAL_HIDE: Mutex<Option<[[u8; 96]; 4]>> = Mutex::new(None);
struct Run { phase: u8, wanted: [u32; 4], saved: Option<[u32; 4]>, since: Option<Instant> }
static RUN: Mutex<Run> = Mutex::new(Run { phase: 0, wanted: IDS, saved: None, since: None });
/// Fists (er-mario's UNARMED) in every weapon slot while Fuse plays: no staff or sword in his
/// hands and no spells on the fire buttons. (saved weapons, when the disarm started)
const UNARMED: u32 = 110000;
const WEAPON_SLOTS: usize = 6;
static DISARM: Mutex<Option<([u32; WEAPON_SLOTS], Instant, bool)>> = Mutex::new(None);

fn init() -> bool {
    FUNCS.get_or_init(|| {
        let equip = scan::unique_text(&[None,Some(0x8b),Some(0xf1),None,Some(0x8b),Some(0xd8),None,Some(0x63),Some(0xea),None,Some(0x8b),Some(0xf9)])?;
        let give = scan::unique_text(&[Some(0x8b),Some(0x02),Some(0x83),Some(0xf8),Some(0x0a)])?;
        log(format!("armor: equip RVA {:#x}, give RVA {:#x}", equip - 0x17 - scan::base(), give - 0x52 - scan::base()));
        Some(Funcs { equip: unsafe { std::mem::transmute::<usize, EquipFn>(equip - 0x17) },
                     give: unsafe { std::mem::transmute::<usize, GiveFn>(give - 0x52) } })
    }).is_some()
}
fn inventory_index(item: u32) -> Option<u32> {
    let gdm = unsafe { GameDataMan::instance() }.ok()?;
    let pgd = gdm.main_player_game_data.as_ptr() as usize;
    let items = &gdm.main_player_game_data.equipment.equip_inventory_data.items_data;
    let head = items.normal_items_head.as_ptr() as usize;
    let tail = unsafe { *((pgd + 0x408 + 0x1c) as *const u32) };
    (0..items.normal_items_len as usize).find(|i| unsafe { *((head+i*0x18+4) as *const u32) } == item).map(|i| i as u32 + tail)
}
fn give(item: u32) -> bool {
    let (Some(Some(f)), Ok(man)) = (FUNCS.get(), unsafe { MapItemMan::instance_mut() }) else { return false };
    let mut buf = [0u8; 20];
    buf[..4].copy_from_slice(&1u32.to_le_bytes());
    buf[4..8].copy_from_slice(&item.to_le_bytes());
    buf[8..12].copy_from_slice(&1u32.to_le_bytes());
    buf[12..].fill(0xff);
    let mut scratch = [0u8; 128];
    unsafe { (f.give)(man as *mut MapItemMan as usize, buf.as_ptr(), scratch.as_mut_ptr(), 0) };
    true
}
fn equip(slot: usize, item: u32) -> bool {
    if inventory_index(item).is_none() { give(item); }
    let (Some(Some(f)), Ok(gdm), Some(idx)) = (FUNCS.get(), unsafe { GameDataMan::instance() }, inventory_index(item)) else { return false };
    let pgd = gdm.main_player_game_data.as_ptr() as usize;
    let data = [item,0,0,0];
    unsafe { (f.equip)(pgd+0x2b0, slot as u32, data.as_ptr(), idx,1,1,0) };
    true
}
fn equipped(p: &PlayerIns) -> [u32; 4] {
    std::array::from_fn(|k| p.chr_asm.equipment_param_ids[12+k] as u32)
}
fn patch(model: u16, hide: bool) -> bool {
    let Ok(repo) = (unsafe { SoloParamRepository::instance_mut() }) else { return false };
    let mut original = ORIGINAL_HIDE.lock().unwrap_or_else(|e| e.into_inner());
    if original.is_none() {
        let mut flags = [[0;96];4];
        for (k,id) in IDS.into_iter().enumerate() {
            let Some(row) = repo.get::<EquipParamProtector>(id) else { return false };
            flags[k] = get_hide(row);
        }
        *original = Some(flags);
    }
    for (k,id) in IDS.into_iter().enumerate() {
        let Some(row) = repo.get_mut::<EquipParamProtector>(id) else { return false };
        row.set_equip_model_id(model);
        set_hide(row, if hide { [1;96] } else { original.unwrap()[k] });
    }
    log(format!("armor: Vagabond rows now use model {model}, hide all {hide}"));
    true
}
/// Starts a two-phase reload; `None` restores the pre-test armor loadout.
pub fn request(model: Option<u16>, hide: bool) -> String {
    if !state::in_world() { return "not in the world".into(); }
    if !init() { return "equip/give signatures were not unique; no changes made".into(); }
    let Ok(wcm) = (unsafe { WorldChrMan::instance() }) else { return "no WorldChrMan".into() };
    let Some(p) = wcm.main_player.as_ref() else { return "no player".into() };
    let mut run = RUN.lock().unwrap_or_else(|e| e.into_inner());
    if run.saved.is_none() { run.saved = Some(equipped(p)); }
    if !patch(model.unwrap_or(1280), hide && model.is_some()) { return "armor rows unavailable".into(); }
    run.wanted = if model.is_some() { fuse_set() } else { run.saved.unwrap_or(IDS) };
    run.phase = 1;
    run.since = Some(Instant::now());
    format!("armor reload requested: model {model:?}, hide {hide}, previous {:?}", run.saved)
}
/// Fuse's pieces to wear: all four; in first person only the arms (with the R-301), the head,
/// body and legs bare; with Apex's view model (model 998, T011) its body and arms pieces, and its
/// head and legs too when they carry the abilities' props (T020: the injector, the jump pad), unless
/// ini `pov_props = 0`. The worn rows keep every hide flag on, so the Tarnished's own body stays
/// hidden (D-017).
///
/// T020's first head and legs pieces (2026-10-05 15:17–16:45) never showed the props and made the
/// screen flicker (huge polygons near the eye, the world culled, dark blocks): their Xtra bones came
/// after the disabled nodes and their FLVER2 skeleton set no longer matched the nodes. Rebuilt
/// 18:31 the way vanilla parts are laid out (tools/fusepov/ability_templates), the props show in
/// the hands and 104 frames of the abilities were clean, so they are worn by default again.
fn fuse_set() -> [u32; 4] {
    match crate::camera::mode() {
        crate::camera::Mode::First if super::pov::available() && super::pov::model_installed() && super::pov::has_props() && crate::paths::number::<u32>("pov_props").unwrap_or(1) == 1 => IDS,
        crate::camera::Mode::First if super::pov::available() && super::pov::model_installed() => [BARE[0], IDS[1], IDS[2], BARE[3]],
        crate::camera::Mode::First => [BARE[0], BARE[1], IDS[2], BARE[3]],
        _ => IDS,
    }
}

/// The armour model Fuse wears: 999 (T005/T008), or Apex's first-person view model 998 (T011).
pub fn fuse_model() -> u16 {
    if crate::camera::mode() == crate::camera::Mode::First && super::pov::available() && super::pov::model_installed() { 998 } else { 999 }
}
/// Puts fists in all six weapon slots (the old weapons are remembered for `rearm`).
pub fn disarm() -> String {
    if !state::in_world() { return "not in the world".into(); }
    if !init() { return "equip/give signatures were not unique; no changes made".into(); }
    let Ok(wcm) = (unsafe { WorldChrMan::instance() }) else { return "no WorldChrMan".into() };
    let Some(p) = wcm.main_player.as_ref() else { return "no player".into() };
    let mut d = DISARM.lock().unwrap_or_else(|e| e.into_inner());
    let saved = d.as_ref().map(|x| x.0).unwrap_or_else(|| weapons(p));
    *d = Some((saved, Instant::now(), true));
    format!("disarming, weapons were {saved:?}")
}
/// Weapons to put back (F5 to the Tarnished: mode.rs), and since when.
static REARM: Mutex<Option<([u32; WEAPON_SLOTS], Instant)>> = Mutex::new(None);
/// Gives the Tarnished back the weapons the disarm took; the next disarm remembers them afresh.
fn rearm() -> String {
    let Some((saved, _, _)) = DISARM.lock().unwrap_or_else(|e| e.into_inner()).take() else { return "nothing to rearm".into() };
    *REARM.lock().unwrap_or_else(|e| e.into_inner()) = Some((saved, Instant::now()));
    format!("rearming {saved:?}")
}
/// F5 (mode.rs): the Tarnished's own armour and weapons.
pub fn to_tarnished() -> String {
    format!("{}; {}", request(None, false), rearm())
}
/// F5 again: Fuse's set and fists.
pub fn to_octane() -> String {
    *REARM.lock().unwrap_or_else(|e| e.into_inner()) = None;
    format!("{}; {}", request(Some(fuse_model()), true), disarm())
}
fn weapons(p: &PlayerIns) -> [u32; WEAPON_SLOTS] {
    std::array::from_fn(|k| p.chr_asm.equipment_param_ids[k] as u32)
}
fn update_weapons(p: &PlayerIns) {
    let mut r = REARM.lock().unwrap_or_else(|e| e.into_inner());
    if let Some((saved, since)) = *r {
        let now = weapons(p);
        if now == saved || since.elapsed() > Duration::from_secs(10) {
            log(format!("armor: rearm {} (weapons now {now:?})", if now == saved { "done" } else { "timed out" }));
            *r = None;
        } else {
            for (k, w) in saved.into_iter().enumerate() {
                if now[k] != w { equip(k, w); }
            }
        }
        return;
    }
    drop(r);
    let mut d = DISARM.lock().unwrap_or_else(|e| e.into_inner());
    let Some((saved, since, pending)) = d.as_mut() else { return };
    if !*pending { return; }
    let now = weapons(p);
    if now.iter().all(|&w| w == UNARMED) {
        *pending = false;
        log(format!("armor: disarmed (weapons were {saved:?})"));
        return;
    }
    if since.elapsed() > Duration::from_secs(10) {
        *pending = false;
        log(format!("armor: disarm timed out, weapons now {now:?}"));
        return;
    }
    for (k, w) in now.into_iter().enumerate() {
        if w != UNARMED { equip(k, UNARMED); }
    }
}

pub fn update() {
    if let Some(p) = state::in_world().then(|| unsafe { WorldChrMan::instance() }.ok()).flatten().and_then(|w| w.main_player.as_ref()) {
        update_weapons(p);
    }
    let mut run = RUN.lock().unwrap_or_else(|e| e.into_inner());
    if run.phase == 0 || !state::in_world() { return; }
    if run.since.is_some_and(|t| t.elapsed() > Duration::from_secs(10)) {
        log("armor: reload timed out; check armorstat; native loadout may be partially applied");
        run.phase = 0;
        return;
    }
    let Ok(wcm) = (unsafe { WorldChrMan::instance() }) else { return };
    let Some(p) = wcm.main_player.as_ref() else { return };
    let now = equipped(p);
    let wanted = if run.phase == 1 { BARE } else { run.wanted };
    if now == wanted {
        if run.phase == 1 { run.phase = 2; log("armor: slots emptied, equipping target set"); }
        else { run.phase = 0; log(format!("armor: reload complete, armor {:?}", now)); }
        return;
    }
    for (k,item) in wanted.into_iter().enumerate() {
        if now[k] != item { equip(12+k, item|PROTECTOR); }
    }
}
/// ini `fuse_model = 1`: once in the world (after the quick boot, if it runs), Fuse's set goes on
/// by itself: the four Vagabond rows on model 999 with every hide flag, so the Tarnished's own
/// body, face and hair are hidden. Once per launch; the equipment then stays through loads.
pub fn auto_update() {
    static DONE: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
    static SINCE: Mutex<Option<Instant>> = Mutex::new(None);
    if DONE.load(std::sync::atomic::Ordering::Relaxed) || !crate::paths::flag("fuse_model") {
        return;
    }
    let mut since = SINCE.lock().unwrap_or_else(|e| e.into_inner());
    if !state::in_world() || (super::quickboot::enabled() && !super::quickboot::settled()) {
        *since = None;
        return;
    }
    // a moment for the loaded world (and the player's equipment) to settle
    if since.get_or_insert_with(Instant::now).elapsed() < Duration::from_secs(1) {
        return;
    }
    DONE.store(true, std::sync::atomic::Ordering::Relaxed);
    log(format!("armor: fuse_model on: {}", request(Some(fuse_model()), true)));
    log(format!("armor: fuse_model on: {}", disarm()));
}

pub fn status() -> String {
    let run = RUN.lock().unwrap_or_else(|e| e.into_inner());
    let now = (unsafe { WorldChrMan::instance() }).ok().and_then(|w| w.main_player.as_ref().map(|p| equipped(p)));
    let models = (unsafe { SoloParamRepository::instance() }).ok().map(|repo| IDS.map(|id| repo.get::<EquipParamProtector>(id).map(|r| r.equip_model_id())));
    format!("armor phase {}, slots {now:?}, models {models:?}", run.phase)
}

fn get_hide(row: &eldenring::param::EQUIP_PARAM_PROTECTOR_ST) -> [u8; 96] {
    [
        row.invisible_flag_sex_ver00(),
        row.invisible_flag_sex_ver01(),
        row.invisible_flag_sex_ver02(),
        row.invisible_flag_sex_ver03(),
        row.invisible_flag_sex_ver04(),
        row.invisible_flag_sex_ver05(),
        row.invisible_flag_sex_ver06(),
        row.invisible_flag_sex_ver07(),
        row.invisible_flag_sex_ver08(),
        row.invisible_flag_sex_ver09(),
        row.invisible_flag_sex_ver10(),
        row.invisible_flag_sex_ver11(),
        row.invisible_flag_sex_ver12(),
        row.invisible_flag_sex_ver13(),
        row.invisible_flag_sex_ver14(),
        row.invisible_flag_sex_ver15(),
        row.invisible_flag_sex_ver16(),
        row.invisible_flag_sex_ver17(),
        row.invisible_flag_sex_ver18(),
        row.invisible_flag_sex_ver19(),
        row.invisible_flag_sex_ver20(),
        row.invisible_flag_sex_ver21(),
        row.invisible_flag_sex_ver22(),
        row.invisible_flag_sex_ver23(),
        row.invisible_flag_sex_ver24(),
        row.invisible_flag_sex_ver25(),
        row.invisible_flag_sex_ver26(),
        row.invisible_flag_sex_ver27(),
        row.invisible_flag_sex_ver28(),
        row.invisible_flag_sex_ver29(),
        row.invisible_flag_sex_ver30(),
        row.invisible_flag_sex_ver31(),
        row.invisible_flag_sex_ver32(),
        row.invisible_flag_sex_ver33(),
        row.invisible_flag_sex_ver34(),
        row.invisible_flag_sex_ver35(),
        row.invisible_flag_sex_ver36(),
        row.invisible_flag_sex_ver37(),
        row.invisible_flag_sex_ver38(),
        row.invisible_flag_sex_ver39(),
        row.invisible_flag_sex_ver40(),
        row.invisible_flag_sex_ver41(),
        row.invisible_flag_sex_ver42(),
        row.invisible_flag_sex_ver43(),
        row.invisible_flag_sex_ver44(),
        row.invisible_flag_sex_ver45(),
        row.invisible_flag_sex_ver46(),
        row.invisible_flag_sex_ver47(),
        row.invisible_flag_sex_ver48(),
        row.invisible_flag_sex_ver49(),
        row.invisible_flag_sex_ver50(),
        row.invisible_flag_sex_ver51(),
        row.invisible_flag_sex_ver52(),
        row.invisible_flag_sex_ver53(),
        row.invisible_flag_sex_ver54(),
        row.invisible_flag_sex_ver55(),
        row.invisible_flag_sex_ver56(),
        row.invisible_flag_sex_ver57(),
        row.invisible_flag_sex_ver58(),
        row.invisible_flag_sex_ver59(),
        row.invisible_flag_sex_ver60(),
        row.invisible_flag_sex_ver61(),
        row.invisible_flag_sex_ver62(),
        row.invisible_flag_sex_ver63(),
        row.invisible_flag_sex_ver64(),
        row.invisible_flag_sex_ver65(),
        row.invisible_flag_sex_ver66(),
        row.invisible_flag_sex_ver67(),
        row.invisible_flag_sex_ver68(),
        row.invisible_flag_sex_ver69(),
        row.invisible_flag_sex_ver70(),
        row.invisible_flag_sex_ver71(),
        row.invisible_flag_sex_ver72(),
        row.invisible_flag_sex_ver73(),
        row.invisible_flag_sex_ver74(),
        row.invisible_flag_sex_ver75(),
        row.invisible_flag_sex_ver76(),
        row.invisible_flag_sex_ver77(),
        row.invisible_flag_sex_ver78(),
        row.invisible_flag_sex_ver79(),
        row.invisible_flag_sex_ver80(),
        row.invisible_flag_sex_ver81(),
        row.invisible_flag_sex_ver82(),
        row.invisible_flag_sex_ver83(),
        row.invisible_flag_sex_ver84(),
        row.invisible_flag_sex_ver85(),
        row.invisible_flag_sex_ver86(),
        row.invisible_flag_sex_ver87(),
        row.invisible_flag_sex_ver88(),
        row.invisible_flag_sex_ver89(),
        row.invisible_flag_sex_ver90(),
        row.invisible_flag_sex_ver91(),
        row.invisible_flag_sex_ver92(),
        row.invisible_flag_sex_ver93(),
        row.invisible_flag_sex_ver94(),
        row.invisible_flag_sex_ver95(),
    ]
}

fn set_hide(row: &mut eldenring::param::EQUIP_PARAM_PROTECTOR_ST, v: [u8; 96]) {
    row.set_invisible_flag_sex_ver00(v[0]);
    row.set_invisible_flag_sex_ver01(v[1]);
    row.set_invisible_flag_sex_ver02(v[2]);
    row.set_invisible_flag_sex_ver03(v[3]);
    row.set_invisible_flag_sex_ver04(v[4]);
    row.set_invisible_flag_sex_ver05(v[5]);
    row.set_invisible_flag_sex_ver06(v[6]);
    row.set_invisible_flag_sex_ver07(v[7]);
    row.set_invisible_flag_sex_ver08(v[8]);
    row.set_invisible_flag_sex_ver09(v[9]);
    row.set_invisible_flag_sex_ver10(v[10]);
    row.set_invisible_flag_sex_ver11(v[11]);
    row.set_invisible_flag_sex_ver12(v[12]);
    row.set_invisible_flag_sex_ver13(v[13]);
    row.set_invisible_flag_sex_ver14(v[14]);
    row.set_invisible_flag_sex_ver15(v[15]);
    row.set_invisible_flag_sex_ver16(v[16]);
    row.set_invisible_flag_sex_ver17(v[17]);
    row.set_invisible_flag_sex_ver18(v[18]);
    row.set_invisible_flag_sex_ver19(v[19]);
    row.set_invisible_flag_sex_ver20(v[20]);
    row.set_invisible_flag_sex_ver21(v[21]);
    row.set_invisible_flag_sex_ver22(v[22]);
    row.set_invisible_flag_sex_ver23(v[23]);
    row.set_invisible_flag_sex_ver24(v[24]);
    row.set_invisible_flag_sex_ver25(v[25]);
    row.set_invisible_flag_sex_ver26(v[26]);
    row.set_invisible_flag_sex_ver27(v[27]);
    row.set_invisible_flag_sex_ver28(v[28]);
    row.set_invisible_flag_sex_ver29(v[29]);
    row.set_invisible_flag_sex_ver30(v[30]);
    row.set_invisible_flag_sex_ver31(v[31]);
    row.set_invisible_flag_sex_ver32(v[32]);
    row.set_invisible_flag_sex_ver33(v[33]);
    row.set_invisible_flag_sex_ver34(v[34]);
    row.set_invisible_flag_sex_ver35(v[35]);
    row.set_invisible_flag_sex_ver36(v[36]);
    row.set_invisible_flag_sex_ver37(v[37]);
    row.set_invisible_flag_sex_ver38(v[38]);
    row.set_invisible_flag_sex_ver39(v[39]);
    row.set_invisible_flag_sex_ver40(v[40]);
    row.set_invisible_flag_sex_ver41(v[41]);
    row.set_invisible_flag_sex_ver42(v[42]);
    row.set_invisible_flag_sex_ver43(v[43]);
    row.set_invisible_flag_sex_ver44(v[44]);
    row.set_invisible_flag_sex_ver45(v[45]);
    row.set_invisible_flag_sex_ver46(v[46]);
    row.set_invisible_flag_sex_ver47(v[47]);
    row.set_invisible_flag_sex_ver48(v[48]);
    row.set_invisible_flag_sex_ver49(v[49]);
    row.set_invisible_flag_sex_ver50(v[50]);
    row.set_invisible_flag_sex_ver51(v[51]);
    row.set_invisible_flag_sex_ver52(v[52]);
    row.set_invisible_flag_sex_ver53(v[53]);
    row.set_invisible_flag_sex_ver54(v[54]);
    row.set_invisible_flag_sex_ver55(v[55]);
    row.set_invisible_flag_sex_ver56(v[56]);
    row.set_invisible_flag_sex_ver57(v[57]);
    row.set_invisible_flag_sex_ver58(v[58]);
    row.set_invisible_flag_sex_ver59(v[59]);
    row.set_invisible_flag_sex_ver60(v[60]);
    row.set_invisible_flag_sex_ver61(v[61]);
    row.set_invisible_flag_sex_ver62(v[62]);
    row.set_invisible_flag_sex_ver63(v[63]);
    row.set_invisible_flag_sex_ver64(v[64]);
    row.set_invisible_flag_sex_ver65(v[65]);
    row.set_invisible_flag_sex_ver66(v[66]);
    row.set_invisible_flag_sex_ver67(v[67]);
    row.set_invisible_flag_sex_ver68(v[68]);
    row.set_invisible_flag_sex_ver69(v[69]);
    row.set_invisible_flag_sex_ver70(v[70]);
    row.set_invisible_flag_sex_ver71(v[71]);
    row.set_invisible_flag_sex_ver72(v[72]);
    row.set_invisible_flag_sex_ver73(v[73]);
    row.set_invisible_flag_sex_ver74(v[74]);
    row.set_invisible_flag_sex_ver75(v[75]);
    row.set_invisible_flag_sex_ver76(v[76]);
    row.set_invisible_flag_sex_ver77(v[77]);
    row.set_invisible_flag_sex_ver78(v[78]);
    row.set_invisible_flag_sex_ver79(v[79]);
    row.set_invisible_flag_sex_ver80(v[80]);
    row.set_invisible_flag_sex_ver81(v[81]);
    row.set_invisible_flag_sex_ver82(v[82]);
    row.set_invisible_flag_sex_ver83(v[83]);
    row.set_invisible_flag_sex_ver84(v[84]);
    row.set_invisible_flag_sex_ver85(v[85]);
    row.set_invisible_flag_sex_ver86(v[86]);
    row.set_invisible_flag_sex_ver87(v[87]);
    row.set_invisible_flag_sex_ver88(v[88]);
    row.set_invisible_flag_sex_ver89(v[89]);
    row.set_invisible_flag_sex_ver90(v[90]);
    row.set_invisible_flag_sex_ver91(v[91]);
    row.set_invisible_flag_sex_ver92(v[92]);
    row.set_invisible_flag_sex_ver93(v[93]);
    row.set_invisible_flag_sex_ver94(v[94]);
    row.set_invisible_flag_sex_ver95(v[95]);
}
