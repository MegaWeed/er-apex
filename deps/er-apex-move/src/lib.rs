//! Y-up movement in **raw Apex units**, with positions at the capsule's feet.
//! Unknown physical scales must be supplied explicitly; see [`MoveParams`].
pub use parry3d::na::Vector3;
pub type Vec3 = Vector3<f32>;
mod controller;
mod params;
#[cfg(feature = "profile")]
pub mod profile;
mod world;
pub use controller::{
    Controller, Duck, Landing, Ledge, LedgeKind, MoveEvents, MoveInput, MoveState, Pose, FIXED_DT,
};
pub use params::{MoveParams, ParamsError, PoseParams};
pub use world::{ChunkId, Triangle, World, WorldError};
