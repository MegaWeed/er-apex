#![allow(dead_code)]
use er_apex_move::{Controller, MoveParams, Triangle, Vec3, World};

/// TEST/DEMO PLACEHOLDERS ONLY — not verified Apex constants.
pub fn demo_params() -> MoveParams {
    MoveParams {
        base_gravity: Some(1000.0),
        speed_multiplier: Some(1.0),
        meters_per_unit: Some(0.025),
        max_slope_radians: Some(45.0_f32.to_radians()),
        ..MoveParams::default()
    }
}
pub fn controller(triangles: &[Triangle], position: Vec3) -> Controller {
    Controller::new(
        World::from_triangles(triangles).unwrap(),
        demo_params(),
        position,
    )
    .unwrap()
}
pub fn quad(a: Vec3, b: Vec3, c: Vec3, d: Vec3) -> Vec<Triangle> {
    vec![[a, b, c], [a, c, d]]
}
pub fn floor(y: f32) -> Vec<Triangle> {
    quad(
        Vec3::new(-10000.0, y, -10000.0),
        Vec3::new(10000.0, y, -10000.0),
        Vec3::new(10000.0, y, 10000.0),
        Vec3::new(-10000.0, y, 10000.0),
    )
}
pub fn wall_x(x: f32) -> Vec<Triangle> {
    quad(
        Vec3::new(x, -100.0, -10000.0),
        Vec3::new(x, 500.0, -10000.0),
        Vec3::new(x, 500.0, 10000.0),
        Vec3::new(x, -100.0, 10000.0),
    )
}
pub fn wall_z(z: f32) -> Vec<Triangle> {
    quad(
        Vec3::new(-10000.0, -100.0, z),
        Vec3::new(10000.0, -100.0, z),
        Vec3::new(10000.0, 500.0, z),
        Vec3::new(-10000.0, 500.0, z),
    )
}
pub fn step(height: f32) -> Vec<Triangle> {
    let mut t = floor(0.0);
    t.extend(quad(
        Vec3::new(100.0, 0.0, -500.0),
        Vec3::new(100.0, height, -500.0),
        Vec3::new(100.0, height, 500.0),
        Vec3::new(100.0, 0.0, 500.0),
    ));
    t.extend(quad(
        Vec3::new(100.0, height, -500.0),
        Vec3::new(1000.0, height, -500.0),
        Vec3::new(1000.0, height, 500.0),
        Vec3::new(100.0, height, 500.0),
    ));
    t
}
pub fn ramp(angle_degrees: f32) -> Vec<Triangle> {
    let slope = angle_degrees.to_radians().tan();
    quad(
        Vec3::new(-1000.0, -1000.0 * slope, -1000.0),
        Vec3::new(1000.0, 1000.0 * slope, -1000.0),
        Vec3::new(1000.0, 1000.0 * slope, 1000.0),
        Vec3::new(-1000.0, -1000.0 * slope, 1000.0),
    )
}
pub fn ramp_feet(angle_degrees: f32, x: f32) -> Vec3 {
    // Capsule tangent support: bottom-center radius above the plane.
    let angle = angle_degrees.to_radians();
    Vec3::new(
        x,
        x * angle.tan() + 16.0 * (1.0 / angle.cos() - 1.0) + 0.1,
        0.0,
    )
}
