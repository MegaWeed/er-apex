//! Test-only allocator probe, scoped to the callback test's thread.
use std::alloc::{GlobalAlloc, Layout, System};
use std::cell::Cell;

thread_local! {
    static ENABLED: Cell<bool> = const { Cell::new(false) };
    static OPERATIONS: Cell<usize> = const { Cell::new(0) };
}

struct AuditAllocator;

fn count() {
    let _ = ENABLED.try_with(|enabled| {
        if enabled.get() {
            let _ = OPERATIONS.try_with(|n| n.set(n.get() + 1));
        }
    });
}

// SAFETY: every operation is forwarded unchanged to the system allocator.
unsafe impl GlobalAlloc for AuditAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        count();
        unsafe { System.alloc(layout) }
    }

    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        count();
        unsafe { System.dealloc(pointer, layout) }
    }

    unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        count();
        unsafe { System.realloc(pointer, layout, size) }
    }
}

#[global_allocator]
static ALLOCATOR: AuditAllocator = AuditAllocator;

pub fn measure(work: impl FnOnce()) -> usize {
    struct Reset;
    impl Drop for Reset {
        fn drop(&mut self) {
            ENABLED.with(|enabled| enabled.set(false));
        }
    }
    OPERATIONS.with(|n| n.set(0));
    ENABLED.with(|enabled| enabled.set(true));
    let reset = Reset;
    work();
    drop(reset);
    OPERATIONS.with(Cell::get)
}
