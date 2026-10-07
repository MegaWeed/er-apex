// Adapted from deltarooo/er-mario; Copyright (c) 2026 Delta, MIT (see LICENSE).
//! DCX containers with Kraken compression, through the game's own oo2core_6_win64.dll.

use std::ffi::c_void;
use std::sync::OnceLock;

use windows::Win32::System::LibraryLoader::{GetProcAddress, LoadLibraryW};
use windows::core::{HSTRING, s};

type Decompress = unsafe extern "C" fn(
    *const u8,
    isize,
    *mut u8,
    isize,
    i32,
    i32,
    i32,
    *mut c_void,
    isize,
    *mut c_void,
    *mut c_void,
    *mut c_void,
    isize,
    i32,
) -> isize;
struct Oodle {
    decompress: Decompress,
}

fn oodle(game_dir: &std::path::Path) -> Result<&'static Oodle, String> {
    static OODLE: OnceLock<Option<Oodle>> = OnceLock::new();
    OODLE
        .get_or_init(|| unsafe {
            let path = game_dir.join("oo2core_6_win64.dll");
            let dll = LoadLibraryW(&HSTRING::from(path.as_os_str())).ok()?;
            Some(Oodle {
                decompress: std::mem::transmute(GetProcAddress(dll, s!("OodleLZ_Decompress"))?),
            })
        })
        .as_ref()
        .ok_or_else(|| "oo2core_6_win64.dll not found next to eldenring.exe".to_string())
}

fn be32(d: &[u8], o: usize) -> usize {
    u32::from_be_bytes(d[o..o + 4].try_into().unwrap()) as usize
}

pub fn decompress(data: &[u8], game_dir: &std::path::Path) -> Result<Vec<u8>, String> {
    if !data.starts_with(b"DCX\0") {
        return Ok(data.to_vec());
    }
    if data.len() < 0x4C || &data[0x28..0x2C] != b"KRAK" {
        return Err("unsupported DCX format".into());
    }
    let (raw, comp) = (be32(data, 0x1C), be32(data, 0x20));
    let body = data.get(0x4C..0x4C + comp).ok_or("truncated DCX")?;
    let o = oodle(game_dir)?;
    let mut out = vec![0u8; raw];
    let n = unsafe {
        (o.decompress)(
            body.as_ptr(),
            body.len() as isize,
            out.as_mut_ptr(),
            raw as isize,
            1,
            0,
            0,
            std::ptr::null_mut(),
            0,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            0,
            3,
        )
    };
    if n != raw as isize {
        return Err(format!("Kraken decompression failed ({n})"));
    }
    Ok(out)
}
