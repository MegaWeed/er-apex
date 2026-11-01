#[vtable_rs::vtable]
pub trait ASAllocatorVmt {
    fn destructor(&mut self, flags: u32);

    fn allocate(&self, size: usize) -> *const u8;
    fn allocate_aligned(&self, size: usize, alignment: usize) -> *const u8;
    fn reallocate(&self, allocation: *const u8, size: usize) -> *const u8;
    fn reallocate_aligned(&self, allocation: *const u8, size: usize, alignment: usize)
    -> *const u8;
    fn deallocate(&self, allocation: *const u8);
}
