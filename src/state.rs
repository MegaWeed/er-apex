//! What the game is doing, as far as the mod and its dev tools care: in the world or not, which map
//! block, where the player stands. Logged on every change and written to dev/state.json once a
//! second, which the test harness (tools/dev) polls.

use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};

use eldenring::cs::{PlayerIns, WorldChrMan};
use fromsoftware_shared::FromStatic;

use crate::{log, paths};

static IN_WORLD: AtomicBool = AtomicBool::new(false);

/// A player character exists (in the world, not the title screen or a menu before loading).
pub fn in_world() -> bool {
    IN_WORLD.load(Ordering::Relaxed)
}

static PLAYABLE: AtomicBool = AtomicBool::new(false);

/// In the world and past the loading screen: the player stands in a map block (-1 while loading)
/// and plays an animation (-1 on loading screens, the first one and a warp's alike).
pub fn playable() -> bool {
    PLAYABLE.load(Ordering::Relaxed)
}

/// The block (map) id as the game's file names write it: m10_00_00_00.
pub fn block_name(id: i32) -> String {
    let b = id as u32;
    format!("m{:02}_{:02}_{:02}_{:02}", b >> 24, (b >> 16) & 0xFF, (b >> 8) & 0xFF, b & 0xFF)
}

/// The player's current animation id (-1 on loading screens).
pub fn current_anim(player: &PlayerIns) -> i32 {
    let t = &player.chr_ins.modules.time_act;
    t.anim_queue[(t.read_idx % 10) as usize].anim_id
}

#[derive(Clone, Default)]
pub struct Snapshot {
    pub uptime: f32,
    pub in_world: bool,
    pub block: i32,
    /// block-local position and yaw (how the map files place things)
    pub block_pos: [f32; 4],
    /// Havok (physics) position
    pub havok: [f32; 3],
    pub anim: i32,
    pub hp: i32,
    pub max_hp: i32,
    pub fps: f32,
}

impl Snapshot {
    pub fn json(&self) -> String {
        format!(
            "{{\"uptime\":{:.3},\"in_world\":{},\"block\":\"{}\",\"block_pos\":[{:.3},{:.3},{:.3},{:.4}],\"havok\":[{:.3},{:.3},{:.3}],\"anim\":{},\"hp\":{},\"max_hp\":{},\"fps\":{:.1}}}",
            self.uptime,
            self.in_world,
            block_name(self.block),
            self.block_pos[0],
            self.block_pos[1],
            self.block_pos[2],
            self.block_pos[3],
            self.havok[0],
            self.havok[1],
            self.havok[2],
            self.anim,
            self.hp,
            self.max_hp,
            self.fps
        )
    }
}

pub static LAST: Mutex<Option<Snapshot>> = Mutex::new(None);

/// Reads the current state (call from a game task).
pub fn snapshot(fps: f32) -> Snapshot {
    let mut s = Snapshot { uptime: crate::log::uptime(), fps, block: -1, ..Default::default() };
    let Some(p) = (unsafe { WorldChrMan::instance() }).ok().and_then(|w| w.main_player.as_ref()) else { return s };
    let p: &PlayerIns = p;
    s.in_world = true;
    s.block = p.current_block_id.into();
    let b = p.block_position;
    s.block_pos = [b.x, b.y, b.z, b.yaw];
    let h = p.chr_ins.modules.physics.position;
    s.havok = [h.0, h.1, h.2];
    s.anim = current_anim(p);
    s.hp = p.chr_ins.modules.data.hp;
    s.max_hp = p.chr_ins.modules.data.max_hp;
    s
}

/// Once per frame: logs world entry/exit and block changes, writes dev/state.json every second.
pub fn update(dt: f32) {
    static TIMER: Mutex<(f32, u32, f32)> = Mutex::new((0.0, 0, 0.0));
    let fps = {
        let mut t = TIMER.lock().unwrap_or_else(|e| e.into_inner());
        t.0 += dt;
        t.1 += 1;
        if t.0 >= 1.0 {
            t.2 = t.1 as f32 / t.0;
            *t = (0.0, 0, t.2);
            Some(t.2)
        } else {
            None
        }
    };
    let s = snapshot(TIMER.lock().unwrap_or_else(|e| e.into_inner()).2);
    let was = IN_WORLD.swap(s.in_world, Ordering::Relaxed);
    PLAYABLE.store(s.in_world && s.block != -1 && s.anim != -1, Ordering::Relaxed);
    let mut last = LAST.lock().unwrap_or_else(|e| e.into_inner());
    if was != s.in_world {
        log(if s.in_world {
            format!("state: in the world, {} at {:.2} {:.2} {:.2}", block_name(s.block), s.block_pos[0], s.block_pos[1], s.block_pos[2])
        } else {
            "state: left the world (title screen, menu or load)".to_string()
        });
    } else if s.in_world && last.as_ref().is_some_and(|l| l.block != s.block) {
        log(format!("state: block {} -> {}", block_name(last.as_ref().map_or(-1, |l| l.block)), block_name(s.block)));
    }
    if fps.is_some() {
        let path = paths::file("dev/state.json");
        let _ = std::fs::create_dir_all(paths::file("dev"));
        let tmp = path.with_extension("tmp");
        if std::fs::write(&tmp, s.json()).is_ok() {
            let _ = std::fs::rename(&tmp, &path);
        }
    }
    *last = Some(s);
}
