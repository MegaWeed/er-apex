use std::{ffi::c_void, sync::atomic::AtomicU64};

use shared::FromStatic;
use vtable_rs::VPtr;

use crate::{asterids::ASAllocatorVmt, cs::CSServerInterface, dlkr::DLAllocator};

#[vtable_rs::vtable]
pub trait FNAllocatorVmt: ASAllocatorVmt {
    fn wait(&self, timeout: u32);
    fn set_underlying(&self, allocator: *const DLAllocator);
}

#[repr(C)]
/// Source of name: RTTI
pub struct FNAllocator {
    pub vftable: VPtr<dyn FNAllocatorVmt, Self>,
    pub allocation_count: AtomicU64,
    pub destructor_wait_delay: u32,
    pub underlying: &'static DLAllocator,
}

#[derive(Clone)]
pub struct FnAllocatorProxy;

impl fromsoftware_shared_stl::StlAllocator for FnAllocatorProxy {
    unsafe fn allocate_raw(&self, size: usize, align: usize) -> *mut c_void {
        let allocator = &unsafe { CSServerInterface::instance_mut() }
            .expect("FNAllocatorProxy::allocate_raw called without allocator initialized")
            .fn_allocator;
        let allocation = (allocator.vftable.allocate_aligned)(allocator, size, align);
        if allocation.is_null() {
            panic!("FNAllocator returned null pointer")
        }
        allocation as _
    }

    unsafe fn deallocate_raw(&self, ptr: *mut c_void) {
        let allocator = &unsafe { CSServerInterface::instance_mut() }
            .expect("FNAllocatorProxy::deallocate_raw called without allocator initialized")
            .fn_allocator;

        (allocator.vftable.deallocate)(allocator, ptr as _);
    }
}
