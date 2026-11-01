//! Game version check: the mod's game addresses (fromsoftware-rs, byte patterns, hook RVAs) are
//! per game version. On any other version the mod stays out of the way.
//!
//! Adapted from er-mario (MIT, Copyright (c) 2026 Delta).

use eldenring::rva::ERGameVersion;
use fromsoftware_shared::game_version::GameVersion;
use pelite::pe64::PeView;
use windows::Win32::System::LibraryLoader::GetModuleHandleW;

/// exe 2.7.1.0 / 2.7.1.1 (1.17.1) and 2.7.2.0 / 2.7.2.1 (1.17.2): what deps/fromsoftware-rs has
/// addresses for. Only the worldwide versions are tested.
pub fn check() -> Result<ERGameVersion, String> {
    let module = unsafe { GetModuleHandleW(None) }.map_err(|e| e.to_string())?;
    let view = unsafe { PeView::module(module.0 as *const u8) };
    std::panic::catch_unwind(|| ERGameVersion::detect(&view).map_err(|e| e.to_string()))
        .unwrap_or_else(|_| Err("could not read the game's version".into()))
}

/// 1.17.1 (exe 2.7.1.x): the mod's own hook addresses differ from 1.17.2's.
pub fn is_2_7_1() -> bool {
    check().is_ok_and(|v| v.is_2_7_1())
}
