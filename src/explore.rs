//! Safe memory access for reading the game's structures: readable-memory checks (with a small
//! cache of readable regions), raw reads and RTTI class names.
//!
//! Copied from er-mario (MIT, Copyright (c) 2026 Delta).

use fromsoftware_shared::UnknownPtr;
use windows::Win32::System::Memory::{MEM_COMMIT, MEMORY_BASIC_INFORMATION, PAGE_GUARD, PAGE_NOACCESS, VirtualQuery};


/// Readable regions VirtualQuery reported recently: (start, end, when). Checks inside them don't
/// ask Windows again for REGION_TTL. VirtualQuery made Mario mode run at ~20 fps on native
/// Windows (the collision and clutter scans check memory hundreds of times a frame); most
/// checks land in a few big heap regions.
static REGIONS: std::sync::Mutex<Vec<(usize, usize, std::time::Instant)>> = std::sync::Mutex::new(Vec::new());
const REGION_TTL: std::time::Duration = std::time::Duration::from_millis(1500);
const MAX_REGIONS: usize = 64;
/// How often the background thread re-checks the known regions (well inside REGION_TTL, so the
/// game's threads only ever query Windows for regions they haven't seen yet: refreshing them on
/// expiry made a hitch every half second on slower PCs).
const REFRESH_EVERY: std::time::Duration = std::time::Duration::from_millis(500);

fn refresher() {
    loop {
        std::thread::sleep(REFRESH_EVERY);
        let known: Vec<(usize, usize)> = REGIONS.lock().unwrap_or_else(|e| e.into_inner()).iter().map(|r| (r.0, r.1)).collect();
        for (start, end) in known {
            let mut info = MEMORY_BASIC_INFORMATION::default();
            let n = unsafe { VirtualQuery(Some(start as *const _), &mut info, size_of::<MEMORY_BASIC_INFORMATION>()) };
            let still = n != 0
                && info.State == MEM_COMMIT
                && info.Protect.0 & (PAGE_NOACCESS.0 | PAGE_GUARD.0) == 0
                && info.BaseAddress as usize == start
                && start + info.RegionSize == end;
            let mut regions = REGIONS.lock().unwrap_or_else(|e| e.into_inner());
            if still {
                let now = std::time::Instant::now();
                for r in regions.iter_mut().filter(|r| r.0 == start) {
                    r.2 = now;
                }
            } else {
                regions.retain(|r| r.0 != start);
            }
        }
    }
}

/// Memory check statistics (perf log): checks, VirtualQuery calls, time in VirtualQuery (ns).
pub static CHECKS: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
pub static QUERIES: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
pub static QUERY_NS: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

/// True if `len` bytes at `addr` are committed, readable memory.
pub fn readable(addr: usize, len: usize) -> bool {
    use std::sync::atomic::Ordering::Relaxed;
    if addr < 0x10000 || addr % 8 != 0 {
        return false;
    }
    CHECKS.fetch_add(1, Relaxed);
    static REFRESHER: std::sync::Once = std::sync::Once::new();
    REFRESHER.call_once(|| {
        std::thread::spawn(refresher);
    });
    let now = std::time::Instant::now();
    let fresh = |r: &(usize, usize, std::time::Instant)| now.duration_since(r.2) < REGION_TTL;
    {
        let regions = REGIONS.lock().unwrap_or_else(|e| e.into_inner());
        if regions.iter().any(|r| fresh(r) && addr >= r.0 && addr.saturating_add(len) <= r.1) {
            return true;
        }
    }
    // (outside the lock: checks run on several threads, some of them the game's own workers,
    // and must never wait behind a slow VirtualQuery)
    let mut info = MEMORY_BASIC_INFORMATION::default();
    let n = unsafe { VirtualQuery(Some(addr as *const _), &mut info, size_of::<MEMORY_BASIC_INFORMATION>()) };
    QUERIES.fetch_add(1, Relaxed);
    QUERY_NS.fetch_add(now.elapsed().as_nanos() as u64, Relaxed);
    if n == 0 || info.State != MEM_COMMIT {
        return false;
    }
    if info.Protect.0 & (PAGE_NOACCESS.0 | PAGE_GUARD.0) != 0 {
        return false;
    }
    let start = info.BaseAddress as usize;
    let end = start + info.RegionSize;
    let mut regions = REGIONS.lock().unwrap_or_else(|e| e.into_inner());
    regions.retain(|r| fresh(r) && r.0 != start);
    if regions.len() >= MAX_REGIONS {
        regions.remove(0);
    }
    regions.push((start, end, now));
    addr + len <= end
}

pub fn read_u64(addr: usize) -> Option<u64> {
    readable(addr, 8).then(|| unsafe { *(addr as *const u64) })
}

/// Class name of the object at `addr` (its first qword must be a vtable with RTTI).
pub fn class_of(addr: usize) -> Option<String> {
    let vt = read_u64(addr)? as usize;
    if !readable(vt.wrapping_sub(8), 16) {
        return None;
    }
    unsafe { UnknownPtr::from(addr) }.rtti_classname()
}
