//! Elden Ring's own effects where an Apex one has nothing to draw it with (U9): the frag grenade's
//! explosion. S3 plays the particles of its `impact_effect_table` exp_frag_grenade
//! (P_impact_exp_FRAG_*); they are in S3's .pcf files inside R5R's VPKs, which no local tool reads
//! (待定). Here a vanilla explosion stands in for them (近似): a game bullet spawned where the grenade
//! goes off, whose own effect is a vanilla explosion's and which does no damage (the grenade's damage
//! is grenade.rs's, by S3's rules).
//!
//! The bullet: BulletParam row 67, an unused dev row as combat.rs's 65/66 (er-mario repurposes
//! 65-70 the same way), rewritten at run time from a donor row: by default "Explosive Stone [Hit]"
//! (10183001, its effect 300602, also the Explosive Bolt's), ini `nade_fx_bullet` names another
//! (e.g. 210030001 "Hefty Fire Pot [Hit]", 10030001 "Fire Pot [Hit]"), read at each explosion. The
//! copy keeps the donor's effect and life and drops its attack (0, as vanilla's chain rows) and its
//! follow-up bullet; nothing is added to the params and regulation.bin is not touched.

use std::sync::Mutex;

use eldenring::cs::{Bullet, CSBulletManager, FieldInsHandle, SoloParamRepository, WorldChrMan};
use fromsoftware_shared::{F32Vector4, FromStatic};
use glam::Vec3;

const BULLET: i32 = 67;
const DONOR: u32 = 10_183_001;

/// Mirror of the game's bullet spawn request (combat.rs's; layout from er-mario's combat.rs, MIT,
/// Copyright (c) 2026 Delta).
#[repr(C)]
struct SpawnRequest {
    owner: FieldInsHandle,
    behavior_id: i32,
    magic_id: i32,
    unk10: u32,
    bullet_id: i32,
    goods_id: i32,
    dummy_poly_id: i32,
    target: [u8; 8],
    unk28: u32,
    unk2c: u32,
    unk30: F32Vector4,
    unk40: u32,
    unk44: u32,
    pad48: [u8; 8],
    acceleration_angle: F32Vector4,
    unk60: F32Vector4,
    angle: F32Vector4,
    position: F32Vector4,
    rest: [u8; 0x80],
}
const _: () = assert!(size_of::<SpawnRequest>() == 0x110);

/// The donor row the dev row was last copied from.
static PATCHED: Mutex<Option<u32>> = Mutex::new(None);

fn donor() -> u32 {
    crate::paths::number::<u32>("nade_fx_bullet").unwrap_or(DONOR)
}

/// Row 67 as a copy of `donor` with no attack and no follow-up; its effect id. None when a row is
/// missing.
fn patch(donor: u32) -> Option<i32> {
    let repo = unsafe { SoloParamRepository::instance_mut() }.ok()?;
    let src = repo.get::<Bullet>(donor)? as *const eldenring::param::BULLET_PARAM_ST;
    let dst = repo.get_mut::<Bullet>(BULLET as u32)? as *mut eldenring::param::BULLET_PARAM_ST;
    // the rows are plain param data of one layout: the whole row copied
    unsafe { std::ptr::copy_nonoverlapping(src, dst, 1) };
    let b = unsafe { &mut *dst };
    b.set_atk_id_bullet(0);
    b.set_hit_bullet_id(-1);
    b.set_init_vellocity(0.0);
    b.set_max_vellocity(0.0);
    b.set_min_vellocity(0.0);
    b.set_accel_in_range(0.0);
    b.set_accel_out_range(0.0);
    b.set_gravity_in_range(0.0);
    b.set_gravity_out_range(0.0);
    b.set_num_shoot(1);
    b.set_is_hit_both_team(false);
    Some(b.sfx_id_bullet())
}

/// The vanilla explosion at `at` (the physics' world, as characters' positions). What it did, for
/// the log.
pub fn explosion(at: Vec3) -> String {
    let want = donor();
    let mut patched = PATCHED.lock().unwrap_or_else(|e| e.into_inner());
    if *patched != Some(want) {
        match patch(want) {
            Some(sfx) => {
                crate::log(format!("fx: bullet {BULLET} now a copy of {want} (effect {sfx}), no attack"));
                *patched = Some(want);
            }
            None => return format!("fx: bullet row {want} or {BULLET} missing: no explosion effect"),
        }
    }
    drop(patched);
    let Some(owner) = (unsafe { WorldChrMan::instance() }).ok().and_then(|w| w.main_player.as_ref()).map(|p| p.chr_ins.field_ins_handle.clone()) else {
        return "fx: no player".into();
    };
    let pos = F32Vector4(at.x, at.y, at.z, 0.0);
    let up = F32Vector4(0.0, 1.0, 0.0, 0.0);
    let request = SpawnRequest {
        owner,
        behavior_id: -1,
        magic_id: -1,
        unk10: 0,
        bullet_id: BULLET,
        goods_id: -1,
        dummy_poly_id: -1,
        target: [0xFF; 8],
        unk28: 0,
        unk2c: 0,
        unk30: pos,
        unk40: 0,
        unk44: 0,
        pad48: [0; 8],
        acceleration_angle: up,
        unk60: F32Vector4(0.0, 0.0, 0.0, 0.0),
        angle: up,
        position: pos,
        rest: [0; 0x80],
    };
    let result = unsafe { CSBulletManager::instance_mut() }
        .map(|m| m.spawn_bullet(unsafe { &*(&request as *const SpawnRequest as *const _) }))
        .map_err(|e| format!("{e:?}"));
    format!("fx: explosion (bullet {BULLET} from {want}) {result:?}")
}

/// Dev channel `fx boom [metres]`: the explosion's effect that far along the camera's line (a test
/// of the look without a grenade; ini `nade_fx_bullet` picks the donor).
pub fn dev(args: &[&str]) -> String {
    match args {
        ["boom", rest @ ..] => {
            let d = rest.first().and_then(|a| a.parse::<f32>().ok()).unwrap_or(6.0);
            let Some((pos, fwd, _, _)) = crate::camera::view() else { return "fx: no camera".into() };
            explosion(pos + fwd.normalize_or_zero() * d)
        }
        _ => "usage: fx boom [metres]".into(),
    }
}
