//! Counters for finding slow ticks (feature `profile`, examples/replay.rs): sweeps, BVH
//! candidates, exact capsule/triangle casts, and nanoseconds per controller phase.
use std::sync::atomic::{AtomicU64, Ordering};

pub static SWEEPS: AtomicU64 = AtomicU64::new(0);
pub static CANDIDATES: AtomicU64 = AtomicU64::new(0);
pub static CASTS: AtomicU64 = AtomicU64::new(0);
pub static SLIDE_NS: AtomicU64 = AtomicU64::new(0);
pub static STEP_UP_NS: AtomicU64 = AtomicU64::new(0);
pub static GROUND_NS: AtomicU64 = AtomicU64::new(0);
pub static LEDGE_NS: AtomicU64 = AtomicU64::new(0);

/// Reads and zeroes all counters: sweeps, candidates, casts, slide/step-up/ground/ledge ns.
pub fn take() -> [u64; 7] {
    [
        &SWEEPS,
        &CANDIDATES,
        &CASTS,
        &SLIDE_NS,
        &STEP_UP_NS,
        &GROUND_NS,
        &LEDGE_NS,
    ]
    .map(|c| c.swap(0, Ordering::Relaxed))
}

pub(crate) fn add(counter: &AtomicU64, since: std::time::Instant) {
    counter.fetch_add(since.elapsed().as_nanos() as u64, Ordering::Relaxed);
}
