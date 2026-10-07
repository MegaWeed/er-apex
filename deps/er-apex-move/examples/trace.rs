mod support;
use er_apex_move::{Controller, MoveInput, Vec3, FIXED_DT};
use support::*;

fn run(label: &str, mut c: Controller, ticks: usize, input: impl Fn(usize) -> MoveInput) {
    println!("\n# {label}\nframe,time,x,y,z,vx,vy,vz,pose,grounded,ground_ny");
    for frame in 0..ticks {
        c.step(&input(frame), FIXED_DT).unwrap();
        let s = c.state;
        println!(
            "{frame},{:.4},{:.3},{:.3},{:.3},{:.3},{:.3},{:.3},{:?},{},{:.4}",
            (frame + 1) as f32 * FIXED_DT,
            s.position.x,
            s.position.y,
            s.position.z,
            s.velocity.x,
            s.velocity.y,
            s.velocity.z,
            s.pose,
            s.grounded,
            s.ground_normal.map_or(0.0, |n| n.y)
        );
    }
}
fn main() {
    println!("TEST/DEMO ONLY: gravity=1000, speed multiplier=1, meters/unit=0.025, slope=45deg; all unverified placeholders.");
    run(
        "flat sprint",
        controller(&floor(0.0), Vec3::zeros()),
        120,
        |_| MoveInput {
            wish: Vec3::x(),
            sprint: true,
            ..Default::default()
        },
    );
    run(
        "22-unit step",
        controller(&step(22.0), Vec3::new(50.0, 0.0, 0.0)),
        90,
        |_| MoveInput {
            wish: Vec3::x(),
            ..Default::default()
        },
    );
    let mut downhill = controller(&ramp(-30.0), ramp_feet(-30.0, 0.0));
    downhill.state.velocity.x = 260.0;
    run(
        "downhill slide then jump at frame 45",
        downhill,
        120,
        |frame| MoveInput {
            wish: Vec3::x(),
            crouch: frame < 45,
            jump: frame == 44,
            ..Default::default()
        },
    );
}
