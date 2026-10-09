//! F5: back to the Tarnished and to Octane again. Off, the mod hands everything back to Elden Ring:
//! the game's own movement (the controller lets go: kcc.rs), camera (camera.rs `mode`), HUD (fe.rs),
//! death (lethal.rs), the Tarnished's own armour and weapons (armor.rs) and buttons (gun.rs); the
//! Apex HUD, the guns, the abilities, the battery and the grenade are off. On again, Octane's set and
//! fists go back on. The key is read like the others (focus, in play: weapons.rs) and hidden from the
//! game (kbd.rs).

use std::sync::atomic::{AtomicBool, Ordering};

use crate::log;

static APEX: AtomicBool = AtomicBool::new(true);
static KEY_WAS: AtomicBool = AtomicBool::new(false);

/// Whether Octane is played (the mod's systems on); false after F5: the Tarnished.
pub fn apex() -> bool {
    APEX.load(Ordering::Relaxed)
}

fn f5_down() -> bool {
    use windows::Win32::System::Threading::GetCurrentProcessId;
    use windows::Win32::UI::Input::KeyboardAndMouse::GetAsyncKeyState;
    use windows::Win32::UI::WindowsAndMessaging::{GetForegroundWindow, GetWindowThreadProcessId};
    let mut pid = 0u32;
    unsafe { GetWindowThreadProcessId(GetForegroundWindow(), Some(&mut pid)) };
    pid == unsafe { GetCurrentProcessId() } && unsafe { GetAsyncKeyState(0x74) } as u16 & 0x8000 != 0
}

/// Once a frame, first: F5 switches (only in the world, in play).
pub fn update() {
    let down = f5_down();
    let pressed = down && !KEY_WAS.swap(down, Ordering::Relaxed);
    if !down {
        KEY_WAS.store(false, Ordering::Relaxed);
    }
    if pressed && crate::state::in_world() && crate::fe::in_play_view() {
        log(set(!apex()));
    }
}

/// Switches (also the dev channel's `mode apex|tarnished`). What happened.
pub fn set(on: bool) -> String {
    if on == apex() {
        return format!("mode: already {}", if on { "Octane" } else { "the Tarnished" });
    }
    if on {
        APEX.store(true, Ordering::Relaxed);
        format!("mode: Octane again ({})", crate::spike::armor::to_octane())
    } else {
        // let go of everything before the switch is seen
        crate::spike::gun::interrupt_reload();
        crate::spike::kcc::hands_off();
        crate::spike::lethal::release();
        crate::audio::stop_all();
        APEX.store(false, Ordering::Relaxed);
        format!("mode: the Tarnished ({})", crate::spike::armor::to_tarnished())
    }
}
