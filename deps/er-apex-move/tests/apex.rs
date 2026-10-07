//! Apex Season 3 movement as measured in R5Reloaded (D-020; trials A–F in
//! docs/research/apex-slide-spec.md §22), on flat ground at 60 Hz with Fuse's settings.
#[path = "../examples/support/mod.rs"]
mod support;
use er_apex_move::{Controller, Duck, MoveInput, Pose, Vec3, FIXED_DT};
use support::*;

fn tick(c: &mut Controller, input: MoveInput) {
    assert_eq!(c.step(&input, FIXED_DT).unwrap(), 1);
}
fn speed(c: &Controller) -> f32 {
    Vec3::new(c.state.velocity.x, 0.0, c.state.velocity.z).norm()
}
fn run() -> MoveInput {
    MoveInput {
        wish: Vec3::x(),
        forward: Vec3::x(),
        sprint: true,
        ..Default::default()
    }
}
fn slide() -> MoveInput {
    MoveInput {
        crouch: true,
        ..run()
    }
}
/// One slide tick of Apex's deceleration: linear slideDecel, then ×0.7^dt.
fn slide_tick(v: f32, decel: f32) -> f32 {
    (v - decel * FIXED_DT).max(0.0) * 0.7f32.powf(FIXED_DT)
}
/// Sprinting at 260 on a flat floor.
fn sprinting() -> Controller {
    let mut c = controller(&floor(0.0), Vec3::zeros());
    c.state.velocity.x = 260.0;
    tick(&mut c, run());
    assert!(c.state.sprinting && (speed(&c) - 260.0).abs() < 0.01);
    c
}

#[test]
fn trial_a_acceleration_profile_and_instant_sprint() {
    let mut c = controller(&floor(0.0), Vec3::zeros());
    let mut v = vec![0.0];
    let mut sprint_tick = None;
    for t in 1..=80 {
        tick(&mut c, run());
        v.push(speed(&c));
        if c.state.sprinting && sprint_tick.is_none() {
            sprint_tick = Some(t);
        }
    }
    // the first tick starts from rest (nothing moving forward yet), the second sprints
    assert_eq!(sprint_tick, Some(2));
    let near = |a: f32, b: f32| (a - b).abs() < 0.01;
    // lowAcceleration 2500 up to lowSpeed 120 (R5Reloaded: +41.77 per tick)
    assert!(
        near(v[1], 41.667) && near(v[2], 83.333) && near(v[3], 125.0),
        "{v:?}"
    );
    // acceleration 450 up to the walk speed minus 1 (R5Reloaded: +7.52)
    assert!(near(v[4], 132.5) && near(v[10], 177.5), "{v:?}");
    // sprintAcceleration 100 above it (R5Reloaded: +1.67), up to sprint speed 260
    assert!(near(v[11] - v[10], 100.0 / 60.0), "{v:?}");
    assert!(near(v[80], 260.0), "{v:?}");
}

#[test]
fn trial_a_slide_boost_decay_and_end() {
    let mut c = sprinting();
    tick(&mut c, slide());
    assert!(c.state.sliding && c.state.crouched);
    assert_eq!(c.state.pose, Pose::Sliding);
    // boost to the 400 cap, then the same tick's deceleration (R5Reloaded 395.958)
    let mut expect = slide_tick(400.0, 100.0);
    assert!((speed(&c) - expect).abs() < 0.01, "{}", speed(&c));
    let mut ticks = 1;
    while c.state.sliding {
        tick(&mut c, slide());
        ticks += 1;
        if c.state.sliding {
            expect = slide_tick(expect, 100.0);
            assert!(
                (speed(&c) - expect).abs() < 0.05,
                "tick {ticks}: {} vs {expect}",
                speed(&c)
            );
        }
        assert!(ticks < 200);
    }
    // R5Reloaded: 1.4495 s (87 ticks) from the boost to below slideStopSpeed 125
    assert!((86..=88).contains(&ticks), "{ticks}");
    // the slide ends crouched, not standing (slide_auto_stand 0)
    assert!(c.state.crouched && c.state.duck == Duck::Ducked);
    assert_eq!(c.state.pose, Pose::Crouching);
    for _ in 0..60 {
        tick(&mut c, slide());
    }
    assert!((speed(&c) - 80.0).abs() < 0.01, "crouch walk {}", speed(&c));
}

#[test]
fn trial_c2_released_crouch_slides_on_above_350() {
    let mut c = sprinting();
    // one tick of crouch only
    tick(&mut c, slide());
    let mut expect = speed(&c);
    loop {
        let before = speed(&c);
        tick(&mut c, run());
        if !c.state.sliding {
            // stood up the tick after dropping below slideMaxStopSpeed
            assert!(before <= 350.0 && before > 330.0, "{before}");
            assert!(!c.state.crouched);
            break;
        }
        // want-to-stop deceleration 400 (R5Reloaded −8.98 per tick near 390)
        expect = slide_tick(expect, 400.0);
        assert!(
            (speed(&c) - expect).abs() < 0.05,
            "{} vs {expect}",
            speed(&c)
        );
        assert!(before > 350.0);
    }
}

#[test]
fn trial_c_release_below_350_stands_up_and_sprints() {
    let mut c = sprinting();
    tick(&mut c, slide());
    while speed(&c) > 320.0 {
        tick(&mut c, slide());
    }
    tick(&mut c, run());
    assert!(!c.state.sliding && !c.state.crouched && c.state.duck == Duck::Unducking);
    for _ in 0..30 {
        tick(&mut c, run());
    }
    assert!(c.state.sprinting && (speed(&c) - 260.0).abs() < 0.01);
}

#[test]
fn trial_d2_slide_jump_raised_to_350_once() {
    let mut c = sprinting();
    tick(&mut c, slide());
    // R5Reloaded: 0.417 s into the slide at 305.97
    while speed(&c) > 310.0 {
        tick(&mut c, slide());
    }
    assert_eq!(c.state.duck, Duck::Ducked);
    tick(
        &mut c,
        MoveInput {
            jump: true,
            ..slide()
        },
    );
    assert!(!c.state.grounded && !c.state.sliding);
    assert!((speed(&c) - 350.0).abs() < 0.01, "{}", speed(&c));
}

#[test]
fn trial_d_slow_slide_jump_keeps_its_speed() {
    let mut c = sprinting();
    tick(&mut c, slide());
    while speed(&c) > 240.0 {
        tick(&mut c, slide());
    }
    let before = speed(&c);
    tick(
        &mut c,
        MoveInput {
            jump: true,
            ..slide()
        },
    );
    assert!(!c.state.grounded);
    assert!(
        (speed(&c) - before).abs() < 2.0,
        "{before} -> {}",
        speed(&c)
    );
}

#[test]
fn jump_straight_out_of_a_fresh_slide_loses_the_boost() {
    let mut c = sprinting();
    tick(&mut c, slide());
    tick(
        &mut c,
        MoveInput {
            jump: true,
            ..slide()
        },
    );
    // 260 boosted by 140 to 400: the boost is taken back within 0.4 s of a still-ducking slide
    assert!(speed(&c) < 262.0 && speed(&c) > 240.0, "{}", speed(&c));
}

#[test]
fn trial_e_every_slide_restarts_the_cooldown() {
    let mut c = sprinting();
    let mut boosts = Vec::new();
    for gap in [0.0, 1.6, 1.68, 2.1] {
        let ticks = (gap / FIXED_DT) as usize;
        for _ in 0..ticks {
            tick(&mut c, run());
        }
        // back to sprint speed, then crouch
        while speed(&c) < 259.9 || c.state.duck != Duck::Standing {
            tick(&mut c, run());
        }
        let before = speed(&c);
        tick(&mut c, slide());
        assert!(c.state.sliding);
        boosts.push(speed(&c) > before + 100.0);
        // release when slower than 350: stand up and run on
        while speed(&c) > 340.0 {
            tick(&mut c, slide());
        }
        tick(&mut c, run());
    }
    // the third slide is 3.3 s after the first but 1.7 s after the second: no boost
    assert_eq!(boosts, vec![true, false, false, true]);
}

#[test]
fn slides_need_the_input_within_reach_of_the_view() {
    let mut c = sprinting();
    let side = MoveInput {
        wish: Vec3::z(),
        forward: Vec3::x(),
        crouch: true,
        ..Default::default()
    };
    tick(&mut c, side);
    assert!(!c.state.sliding);
}

#[test]
fn landing_crouched_slides_with_the_air_threshold() {
    let mut c = controller(&floor(0.0), Vec3::new(0.0, 100.0, 0.0));
    c.state.velocity.x = 150.0; // below the ground threshold 200, above the air one 90
    let fall = MoveInput {
        wish: Vec3::x(),
        forward: Vec3::x(),
        crouch: true,
        ..Default::default()
    };
    while !c.state.grounded {
        tick(&mut c, fall);
    }
    assert!(c.state.sliding, "{:?}", c.state);
    assert!(speed(&c) > 280.0, "boosted from 150: {}", speed(&c));
}

#[test]
fn a_high_fall_stops_the_player() {
    let mut c = controller(&floor(0.0), Vec3::new(0.0, 900.0, 0.0));
    c.state.velocity.x = 200.0;
    while !c.state.grounded {
        tick(&mut c, MoveInput::default());
    }
    // landSlowdownFrac 0 from above landSlowdownHeightMax 800
    assert!(speed(&c) < 1.0, "{}", speed(&c));
}

#[test]
fn a_low_fall_keeps_speed() {
    let mut c = controller(&floor(0.0), Vec3::new(0.0, 60.0, 0.0));
    c.state.velocity.x = 200.0;
    while !c.state.grounded {
        tick(&mut c, MoveInput::default());
    }
    assert!(speed(&c) > 190.0, "{}", speed(&c));
}

#[test]
fn sliding_off_a_ledge_keeps_the_slide() {
    // a platform ending at x = 100 above a floor 200 below
    let mut terrain = quad(
        Vec3::new(-1000.0, 0.0, -500.0),
        Vec3::new(100.0, 0.0, -500.0),
        Vec3::new(100.0, 0.0, 500.0),
        Vec3::new(-1000.0, 0.0, 500.0),
    );
    terrain.extend(floor(-200.0));
    let mut c = controller(&terrain, Vec3::new(0.0, 0.0, 0.0));
    c.state.velocity.x = 260.0;
    tick(&mut c, run());
    tick(&mut c, slide());
    assert!(c.state.sliding);
    while c.state.grounded {
        tick(&mut c, slide());
    }
    assert!(c.state.sliding, "left the ground: {:?}", c.state);
}

#[test]
fn crouch_takes_400_ms_and_eye_height_eases() {
    let mut c = controller(&floor(0.0), Vec3::zeros());
    assert_eq!(c.state.eye_height, 60.0);
    let crouch = MoveInput {
        crouch: true,
        ..Default::default()
    };
    let mut ticks = 0;
    while !c.state.crouched {
        tick(&mut c, crouch);
        ticks += 1;
        assert!(c.state.eye_height <= 60.0 && c.state.eye_height >= 32.0);
    }
    // whole milliseconds, 16 a tick from the tick after the press: 400 ms take 26 ticks (a
    // slide's 200 ms took 13 ticks after its start in R5Reloaded, trial A)
    assert_eq!(ticks, 26);
    assert_eq!(c.state.eye_height, 32.0);
    let mut up = 0;
    while c.state.duck != Duck::Standing {
        tick(&mut c, MoveInput::default());
        up += 1;
    }
    assert_eq!(up, 14); // the 200 ms unduck: the first tick starts it
    assert_eq!(c.state.eye_height, 60.0);
}
