//! The mouse stays free while the game window is not in front: Elden Ring keeps confining the
//! cursor to its window (`ClipCursor`, called again and again) even after it lost the focus, so
//! automated runs locked the user's mouse into the game window (2026-10-04). The hook turns the
//! game's clip into "no clip" whenever another process owns the foreground window. And the game's
//! menus do not follow the user's mouse then (`GetCursorPos` says it is far away).

use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

use windows::Win32::System::LibraryLoader::{GetModuleHandleW, GetProcAddress, LoadLibraryW};
use windows::Win32::System::Threading::GetCurrentProcessId;
use windows::Win32::UI::WindowsAndMessaging::{GetForegroundWindow, GetWindowThreadProcessId};
use windows::core::{s, w};

use crate::log;

/// Whether the game's window is the foreground window (the user has it in front).
pub fn game_in_front() -> bool {
    let mut pid = 0u32;
    unsafe { GetWindowThreadProcessId(GetForegroundWindow(), Some(&mut pid)) };
    pid == unsafe { GetCurrentProcessId() }
}

/// Where `GetCursorPos` says the mouse is while another window is in front (screen pixels): far
/// off the game's window, or the dev `cursor <x> <y>` test point.
const AWAY: (i32, i32) = (-32000, -32000);
static FAKE: std::sync::Mutex<Option<(i32, i32)>> = std::sync::Mutex::new(None);
/// The game's GetCursorPos before our import-table entry (user32's, or the Steam overlay's).
static ORIGINAL: AtomicUsize = AtomicUsize::new(0);

/// Dev `cursor <x> <y>` / `cursor off`: the point the game is told while in the background.
pub fn command(args: &[&str]) -> String {
    let mut fake = FAKE.lock().unwrap_or_else(|e| e.into_inner());
    match args {
        [x, y] => match (x.parse(), y.parse()) {
            (Ok(x), Ok(y)) => {
                *fake = Some((x, y));
                format!("cursor: the game is told ({x}, {y}) while in the background")
            }
            _ => "usage: cursor <x> <y> | off".into(),
        },
        _ => {
            *fake = None;
            format!("cursor: the game is told {AWAY:?} while in the background")
        }
    }
}

/// The game's GetCursorPos(POINT*): with the dev profile's IsEnableControlOnDisactiveWindow its
/// menus follow the mouse wherever it is over the game's screen area, even with other windows on
/// top (the quick boot found the title menu on the DLC store, 2026-10-05 13:28 and 17:51).
unsafe extern "system" fn get_cursor_pos(p: *mut i32) -> i32 {
    let f: unsafe extern "system" fn(*mut i32) -> i32 = unsafe { std::mem::transmute(ORIGINAL.load(Ordering::Relaxed)) };
    let rc = unsafe { f(p) };
    if rc != 0 && !p.is_null() && !game_in_front() {
        static NOTED: AtomicBool = AtomicBool::new(false);
        if !NOTED.swap(true, Ordering::Relaxed) {
            log("cursor: the game asks where the mouse is while in the background; it is told: far away");
        }
        let (x, y) = FAKE.lock().unwrap_or_else(|e| e.into_inner()).unwrap_or(AWAY);
        unsafe {
            *p = x;
            *p.add(1) = y;
        }
    }
    rc
}

pub unsafe fn install() {
    use ilhook::x64::{CallbackOption, HookFlags, hook_closure_retn};
    // the game's own import only: user32's GetCursorPos is too short for an inline hook (a jump
    // patched over it ran into the padding after it and crashed the game, 2026-10-05 20:16)
    match unsafe { crate::input::patch_import("user32", c"GetCursorPos", None, get_cursor_pos as *const () as usize) } {
        Some((_, previous)) => ORIGINAL.store(previous, Ordering::Relaxed),
        None => log("cursor: GetCursorPos not in the game's import table; the menus follow the mouse in the background"),
    }
    let result = (|| -> Result<(), String> {
        let dll = unsafe { GetModuleHandleW(w!("user32.dll")).or_else(|_| LoadLibraryW(w!("user32.dll"))) }.map_err(|e| e.to_string())?;
        let addr = unsafe { GetProcAddress(dll, s!("ClipCursor")) }.ok_or("no ClipCursor")? as usize;
        // ClipCursor(const RECT*): null releases the cursor
        let hook = |reg: *mut ilhook::x64::Registers, original: usize| -> usize {
            let rect = unsafe { (*reg).rcx };
            let f: unsafe extern "system" fn(u64) -> i32 = unsafe { std::mem::transmute(original) };
            let rect = if rect != 0 && !game_in_front() { 0 } else { rect };
            unsafe { f(rect) as u32 as usize }
        };
        let h = unsafe { hook_closure_retn(addr, hook, CallbackOption::None, HookFlags::empty()) }.map_err(|e| format!("{e:?}"))?;
        std::mem::forget(h);
        Ok(())
    })();
    match result {
        Ok(()) => log("cursor: while the game is in the background it neither confines the mouse nor sees where it is"),
        Err(e) => log(format!("cursor: ClipCursor hook failed ({e})")),
    }
}
