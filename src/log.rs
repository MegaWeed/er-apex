//! logs\er_apex.log in the mod folder, started fresh every launch; the previous session's stays
//! as logs\er_apex.prev.log. Every line carries the seconds since the DLL loaded, so test runs
//! can be lined up with screenshots and the dev state file.
//!
//! Adapted from er-mario (MIT, Copyright (c) 2026 Delta).

use std::fs::OpenOptions;
use std::io::Write;
use std::sync::mpsc::{Sender, channel};
use std::sync::{Mutex, OnceLock};
use std::time::Instant;

use crate::paths;

fn start() -> Instant {
    static START: OnceLock<Instant> = OnceLock::new();
    *START.get_or_init(Instant::now)
}

/// Seconds since the DLL loaded.
pub fn uptime() -> f32 {
    start().elapsed().as_secs_f32()
}

/// Lines go to a writer thread that keeps the file open: opening, appending and closing the file
/// for every line took milliseconds on the game's threads (KCC frames over 1 ms, 2026-10-04).
fn writer() -> &'static Mutex<Sender<String>> {
    static TX: OnceLock<Mutex<Sender<String>>> = OnceLock::new();
    TX.get_or_init(|| {
        start();
        let path = paths::file("logs/er_apex.log");
        let _ = std::fs::create_dir_all(paths::file("logs"));
        let _ = std::fs::rename(&path, paths::file("logs/er_apex.prev.log"));
        let (tx, rx) = channel::<String>();
        std::thread::spawn(move || {
            let Ok(f) = OpenOptions::new().create(true).write(true).truncate(true).open(&path) else { return };
            let mut f = std::io::BufWriter::new(f);
            while let Ok(line) = rx.recv() {
                let _ = writeln!(f, "{line}");
                // whatever else is queued, then out to the file (the dev harness reads it back)
                while let Ok(line) = rx.try_recv() {
                    let _ = writeln!(f, "{line}");
                }
                let _ = f.flush();
            }
        });
        Mutex::new(tx)
    })
}

pub fn log(msg: impl AsRef<str>) {
    let line = format!("[{:9.3}] {}", uptime(), msg.as_ref());
    let _ = writer().lock().unwrap_or_else(|e| e.into_inner()).send(line);
}

/// `debug = 1` in er_apex.ini: detailed logging.
pub fn debug() -> bool {
    static DEBUG: OnceLock<bool> = OnceLock::new();
    *DEBUG.get_or_init(|| paths::flag("debug"))
}

/// A diagnostic line, only with `debug = 1`.
pub fn dlog(msg: impl AsRef<str>) {
    if debug() {
        log(msg);
    }
}
