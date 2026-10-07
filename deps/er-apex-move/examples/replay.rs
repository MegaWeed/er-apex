//! Replays a triangle window dumped from Elden Ring (er-fuse dev command `kcc dump`) and times
//! the controller there: standing still, then pushing 2 s in each of 8 directions, walking and
//! sprinting. `cargo run --release --example replay -- <kcc_window.txt>`
use er_apex_move::{Controller, MoveInput, MoveParams, Triangle, Vec3, World, FIXED_DT};
use std::time::Instant;

fn main() {
    let path = std::env::args()
        .nth(1)
        .expect("usage: replay <kcc_window.txt>");
    let text = std::fs::read_to_string(&path).expect("read the dump");
    let mut lines = text.lines();
    let nums = |l: &str| {
        l.split_whitespace()
            .map(|x| x.parse::<f32>().unwrap())
            .collect::<Vec<_>>()
    };
    let head = nums(lines.next().unwrap());
    let state = nums(lines.next().unwrap());
    let mut lines = lines.peekable();
    // optional: the input of a slow step (er-fuse `kcc` slow-step dumps)
    let recorded = lines
        .next_if(|l| l.starts_with("input"))
        .map(|l| nums(&l["input".len()..]));
    let tris: Vec<Triangle> = lines
        .map(nums)
        .filter(|v| v.len() == 9)
        .map(|v| {
            [
                Vec3::new(v[0], v[1], v[2]),
                Vec3::new(v[3], v[4], v[5]),
                Vec3::new(v[6], v[7], v[8]),
            ]
        })
        .collect();
    let (mpu, gravity, slope, mult) = (head[0], head[1], head[2], head[3]);
    let params = MoveParams {
        base_gravity: Some(gravity / mpu),
        speed_multiplier: Some(mult),
        meters_per_unit: Some(mpu),
        max_slope_radians: Some(slope.to_radians()),
        // FUSE_ITER: collision iterations as an integration sets them (default: the library's)
        collision_iterations: std::env::var("FUSE_ITER")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(MoveParams::default().collision_iterations),
        ..MoveParams::default()
    };
    let start = Vec3::new(state[0], state[1], state[2]);
    let t0 = Instant::now();
    let world = World::from_triangles(&tris).unwrap();
    println!(
        "{} triangles, world built in {:.2} ms, start {:?}",
        tris.len(),
        t0.elapsed().as_secs_f64() * 1000.0,
        start
    );
    let mut all = Vec::new();
    let run = |name: &str,
               c: &mut Controller,
               input: MoveInput,
               ticks: usize,
               all: &mut Vec<f64>| {
        let mut v = Vec::new();
        let mut drops = 0;
        for tick in 0..ticks {
            let h = |c: &Controller| Vec3::new(c.state.velocity.x, 0.0, c.state.velocity.z).norm();
            let (before, was, from) = (h(c), c.state.grounded, c.state.position);
            let t = Instant::now();
            c.step(&input, FIXED_DT).unwrap();
            v.push(t.elapsed().as_secs_f64() * 1e6);
            // FUSE_TRACE=<scenario>: every tick of one scenario
            if std::env::var("FUSE_TRACE").is_ok_and(|s| s == name) {
                println!(
                    "    {tick:3} {:6.0} µs at {:.2?} v {:.1?} {:?} grounded {} sprint {}",
                    v[v.len() - 1],
                    c.state.position,
                    c.state.velocity,
                    c.state.pose,
                    c.state.grounded,
                    c.state.sprinting
                );
            }
            // a sudden loss of ground speed (user test 2026-10-04: 6.4 -> 2.5 m/s in one tick)
            if was && c.state.grounded && before > 100.0 && h(c) < before * 0.7 {
                drops += 1;
                // FUSE_DROPS=1: where and how
                if std::env::var("FUSE_DROPS").is_ok() {
                    println!(
                        "    {name} tick {tick}: {before:.1} -> {:.1}, moved {:.2} of {:.2}, at {:.1?} v {:.1?} {:?}",
                        h(c),
                        (c.state.position - from).norm(),
                        before * FIXED_DT,
                        c.state.position,
                        c.state.velocity,
                        c.state.pose
                    );
                }
            }
        }
        if drops > 0 {
            println!("{name:>16}: {drops} ticks lost over 30% of ground speed");
        }
        all.extend(&v);
        let worst = v
            .iter()
            .enumerate()
            .max_by(|a, b| a.1.total_cmp(b.1))
            .map_or(0, |(i, _)| i);
        #[cfg(feature = "profile")]
        {
            let [sw, cand, casts, slide, up, ground, ledge] = er_apex_move::profile::take();
            let t = ticks as f64;
            println!(
                "{:>16}  per tick: {:.1} sweeps, {:.0} candidates, {:.0} casts; µs slide {:.0} step-up {:.0} ground {:.0} ledge {:.0}",
                "",
                sw as f64 / t,
                cand as f64 / t,
                casts as f64 / t,
                slide as f64 / t / 1e3,
                up as f64 / t / 1e3,
                ground as f64 / t / 1e3,
                ledge as f64 / t / 1e3
            );
        }
        v.sort_by(f64::total_cmp);
        let p = |q: f64| v[((v.len() - 1) as f64 * q).round() as usize];
        println!(
            "{name:>16}: mean {:7.1} µs p50 {:7.1} p99 {:7.1} max {:7.1} (tick {worst}) | at {:.1?} {:?} stuck {}",
            v.iter().sum::<f64>() / v.len() as f64,
            p(0.5),
            p(0.99),
            p(1.0),
            c.state.position,
            c.state.pose,
            c.state.stuck
        );
    };
    let mut c = Controller::new(world, params, start).unwrap();
    // the dumped state as it was (velocity included), left alone: does it settle?
    {
        let d = &mut c;
        d.state.velocity = Vec3::new(state[3], state[4], state[5]);
        for t in 0..=60 {
            if t % 10 == 0 {
                println!(
                    "dumped state, tick {t:2}: at {:.2?} velocity {:.1?} {:?} grounded {} stuck {}",
                    d.state.position,
                    d.state.velocity,
                    d.state.pose,
                    d.state.grounded,
                    d.state.stuck
                );
            }
            d.step(&MoveInput::default(), FIXED_DT).unwrap();
        }
        d.teleport(start).unwrap();
    }
    if let Some(r) = recorded {
        // the recorded step: same state and input, timed tick by tick
        c.state.velocity = Vec3::new(state[3], state[4], state[5]);
        let input = MoveInput {
            wish: Vec3::new(r[0], r[1], r[2]),
            sprint: r[3] != 0.0,
            crouch: r[4] != 0.0,
            jump: r[5] != 0.0,
            ..Default::default()
        };
        println!(
            "recorded: {} ticks in {:.0} µs in game; input {:?}",
            r[6], r[7], input
        );
        for _ in 0..(r[6] as usize).max(1) {
            #[cfg(feature = "profile")]
            er_apex_move::profile::take();
            let t = Instant::now();
            c.step(&input, FIXED_DT).unwrap();
            let us = t.elapsed().as_secs_f64() * 1e6;
            #[cfg(feature = "profile")]
            {
                let [sw, cand, casts, slide, up, ground, ledge] = er_apex_move::profile::take();
                println!("  tick {us:.0} µs: {sw} sweeps, {cand} candidates, {casts} casts; µs slide {} step-up {} ground {} ledge {} -> {:?}", slide / 1000, up / 1000, ground / 1000, ledge / 1000, c.state.pose);
            }
            #[cfg(not(feature = "profile"))]
            println!("  tick {us:.0} µs -> {:?}", c.state.pose);
        }
        c.teleport(start).unwrap();
    }
    run("idle", &mut c, MoveInput::default(), 120, &mut all);
    for i in 0..8 {
        let a = i as f32 * std::f32::consts::FRAC_PI_4;
        let wish = Vec3::new(a.sin(), 0.0, a.cos());
        for sprint in [false, true] {
            c.teleport(start).unwrap();
            run(
                &format!("dir {i}{}", if sprint { " sprint" } else { "" }),
                &mut c,
                MoveInput {
                    wish,
                    sprint,
                    ..Default::default()
                },
                120,
                &mut all,
            );
        }
    }
    all.sort_by(f64::total_cmp);
    let n = all.len();
    println!(
        "all {n} ticks: p50 {:.1} p99 {:.1} max {:.1} µs, >1 ms: {}",
        all[n / 2],
        all[(n - 1) * 99 / 100],
        all[n - 1],
        all.iter().filter(|&&x| x > 1000.0).count()
    );
}
