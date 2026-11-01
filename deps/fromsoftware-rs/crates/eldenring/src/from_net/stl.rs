use crate::from_net::FnAllocatorProxy;

use fromsoftware_shared_stl::{BasicString, Vector};

pub type FNVector<T> = Vector<T, FnAllocatorProxy>;
/// [`BasicString`] that uses [`FnAllocatorProxy`] for all of it's operations.
/// Can be either UTF-8 or ShiftJIS, depending on usage in the game.
pub type FNString = BasicString<u8, FnAllocatorProxy>;
