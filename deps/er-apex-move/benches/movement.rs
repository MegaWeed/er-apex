#[path = "../examples/support/mod.rs"]
mod support;
use er_apex_move::{Controller, MoveInput, Vec3, World, FIXED_DT};
use std::{hint::black_box, time::Instant};
use support::*;

fn terrain() -> Vec<er_apex_move::Triangle> {
    let mut triangles = Vec::with_capacity(10000);
    // 32-unit cells: character diameter matches a cell, exercises triangle seams.
    for x in -50..50 {
        for z in -25..25 {
            let a = Vec3::new(x as f32 * 32.0, 0.0, z as f32 * 32.0);
            triangles.extend(quad(
                a,
                a + Vec3::x() * 32.0,
                a + (Vec3::x() + Vec3::z()) * 32.0,
                a + Vec3::z() * 32.0,
            ));
        }
    }
    triangles
}

fn measure(label: &str, triangles: &[er_apex_move::Triangle], input: MoveInput, reset_every: usize) {
    let build = Instant::now();
    let world = World::from_triangles(triangles).unwrap();
    let build_time = build.elapsed();
    assert_eq!(world.triangle_count(), 10000);
    let mut c = Controller::new(world, demo_params(), Vec3::new(0.0, 0.02, 0.0)).unwrap();
    for i in 0..2000 {
        if i % reset_every == 0 {
            c.teleport(Vec3::new(0.0, 0.02, 0.0)).unwrap();
        }
        c.step(&input, FIXED_DT).unwrap();
    }
    let mut samples = Vec::with_capacity(20000);
    for i in 0..20000 {
        // Reset outside timing; every measured call executes exactly one tick.
        if i % reset_every == 0 {
            c.teleport(Vec3::new(0.0, 0.02, 0.0)).unwrap();
        }
        let start = Instant::now();
        assert_eq!(c.step(black_box(&input), black_box(FIXED_DT)).unwrap(), 1);
        black_box(c.state);
        samples.push(start.elapsed().as_nanos() as u64);
    }
    let mean = samples.iter().sum::<u64>() as f64 / samples.len() as f64;
    samples.sort_unstable();
    println!("{label}: triangles=10000 samples={} build={:.3}ms mean={:.3}us p50={:.3}us p95={:.3}us p99={:.3}us max={:.3}us",
        samples.len(), build_time.as_secs_f64()*1000.0, mean/1000.0,
        samples[10000] as f64/1000.0, samples[19000] as f64/1000.0,
        samples[19800] as f64/1000.0, samples[19999] as f64/1000.0);
    assert!(mean < 100000.0, "mean step exceeds 0.1ms");
    assert!(samples[19800] < 100000, "p99 step exceeds 0.1ms");
}

fn main() {
    println!("Release timing; scales are explicit TEST PLACEHOLDERS, not Apex constants.");
    let flat = terrain();
    measure(
        "flat sprint",
        &flat,
        MoveInput {
            wish: Vec3::x(),
            sprint: true,
            ..Default::default()
        },
        180,
    );
    let mut corner = flat;
    corner.truncate(9996);
    corner.extend(wall_x(100.0));
    corner.extend(wall_z(100.0));
    measure(
        "wall/corner",
        &corner,
        MoveInput {
            wish: Vec3::new(1.0, 0.0, 1.0),
            ..Default::default()
        },
        180,
    );
}
