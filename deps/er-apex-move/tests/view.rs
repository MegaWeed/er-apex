//! The view outputs and events the viewmodel and camera effects use (docs/research/
//! apex-gun-motion-spec.md §2.2, §2.3, §4.1; plan docs/plan/plan-gun-motion-hud.md 2.2), on flat
//! ground at 60 Hz. The eye offsets are R5Reloaded's own (trials T2, T3: eye height minus the
//! standing view height, `scratch/r5anim/T2.log`, `T3.log`, read with tools/r5/vmparse.py).
#[path = "../examples/support/mod.rs"]
mod support;
use er_apex_move::{Controller, Duck, MoveEvents, MoveInput, Vec3, FIXED_DT};
use support::*;

fn tick(c: &mut Controller, input: MoveInput) -> MoveEvents {
    assert_eq!(c.step(&input, FIXED_DT).unwrap(), 1);
    c.take_events()
}
fn walk() -> MoveInput {
    MoveInput {
        wish: Vec3::x(),
        forward: Vec3::x(),
        ..Default::default()
    }
}
fn run() -> MoveInput {
    MoveInput {
        sprint: true,
        ..walk()
    }
}
fn smooth(r: f32) -> f32 {
    let r = r.clamp(0.0, 1.0);
    (3.0 - 2.0 * r) * r * r
}
/// The sprint's eye offset at a fraction (spec §4.1, sprintViewOffset −6).
fn offset(f: f32) -> f32 {
    -6.0 * (f * std::f32::consts::FRAC_PI_2).sin()
}
/// Walking forward at the walk speed, sprint not pressed.
fn walking() -> Controller {
    let mut c = controller(&floor(0.0), Vec3::zeros());
    c.state.velocity.x = 173.5;
    for _ in 0..10 {
        let e = tick(&mut c, walk());
        assert!(!e.sprint_started && !c.state.sprinting);
    }
    c
}
/// Ticks until `done`, at most `max`; the events of each.
fn until(
    c: &mut Controller,
    input: MoveInput,
    max: usize,
    done: impl Fn(&Controller, &MoveEvents) -> bool,
) -> MoveEvents {
    for _ in 0..max {
        let e = tick(c, input);
        if done(c, &e) {
            return e;
        }
    }
    panic!("not within {max} ticks: {:?}", c.state);
}

#[test]
fn duck_fraction_is_the_eye_height_smoothstep() {
    let mut c = controller(&floor(0.0), Vec3::zeros());
    let crouch = MoveInput {
        crouch: true,
        ..Default::default()
    };
    // the press tick starts the 400 ms, then 16 whole ms a tick (spec §2.3; slide spec §12)
    for n in 0..26 {
        let e = tick(&mut c, crouch);
        assert_eq!(e.duck_started, n == 0);
        let expect = 1.0 - smooth((400 - 16 * n) as f32 / 400.0);
        assert!(
            (c.state.duck_fraction - expect).abs() < 1.0e-6,
            "tick {n}: {} vs {expect}",
            c.state.duck_fraction
        );
        let eye = 60.0 + (32.0 - 60.0) * c.state.duck_fraction;
        assert!((c.state.eye_height - eye).abs() < 1.0e-4);
    }
    assert_eq!(c.state.duck, Duck::Ducked);
    assert_eq!(c.state.duck_fraction, 1.0);
    // standing up: 200 ms
    for n in 0..14 {
        let e = tick(&mut c, MoveInput::default());
        assert_eq!(e.unduck_started, n == 0);
        let expect = smooth((200 - 16 * n) as f32 / 200.0);
        assert!(
            (c.state.duck_fraction - expect).abs() < 1.0e-6,
            "up tick {n}: {} vs {expect}",
            c.state.duck_fraction
        );
    }
    assert_eq!(c.state.duck, Duck::Standing);
    assert_eq!(c.state.duck_fraction, 0.0);
}

#[test]
fn sprint_from_a_walk_lowers_the_eye_like_r5r_t2() {
    let mut c = walking();
    let e = tick(&mut c, run());
    assert!(e.sprint_started && c.state.sprinting);
    // R5R T2 (936.765): ticks after the sprint started → eye offset; 0 until 0.2 s, full at 1 s
    let r5r = [
        (6, 0.0),
        (12, 0.0),
        (13, -0.195),
        (18, -1.172),
        (30, -3.334),
        (42, -4.988),
        (54, -5.885),
        (60, -6.0),
        (66, -6.0),
    ];
    let mut k = 0;
    for (at, measured) in r5r {
        while k < at {
            let e = tick(&mut c, run());
            assert!(!e.sprint_started && !e.sprint_ended);
            k += 1;
        }
        let f = ((k as f32 / 60.0 - 0.2) / 0.8).clamp(0.0, 1.0);
        assert!((c.state.sprint_fraction - f).abs() < 1.0e-4, "tick {k}");
        assert!((c.state.eye_sprint_offset - offset(f)).abs() < 1.0e-4);
        assert!(
            (c.state.eye_sprint_offset - measured).abs() < 0.01,
            "tick {k}: {} vs R5R {measured}",
            c.state.eye_sprint_offset
        );
    }
    // stopping: the fraction falls linearly over 0.15 s (R5R T2 942.148)
    let e = until(&mut c, MoveInput::default(), 30, |c, _| !c.state.sprinting);
    assert!(e.sprint_ended);
    assert!((c.state.eye_sprint_offset + 6.0).abs() < 1.0e-4);
    for (k, measured) in [(1, -5.908), (2, -5.639), (3, -5.197), (4, -4.598)] {
        tick(&mut c, MoveInput::default());
        let f = 1.0 - k as f32 / 60.0 / 0.15;
        assert!((c.state.sprint_fraction - f).abs() < 1.0e-4, "end tick {k}");
        assert!(
            (c.state.eye_sprint_offset - measured).abs() < 0.01,
            "end tick {k}: {} vs R5R {measured}",
            c.state.eye_sprint_offset
        );
    }
    for _ in 0..6 {
        tick(&mut c, MoveInput::default());
    }
    assert_eq!(c.state.sprint_fraction, 0.0);
    assert_eq!(c.state.eye_sprint_offset, 0.0);
}

#[test]
fn a_jump_ends_the_sprint_and_landing_resumes_it_fast_like_r5r_t3() {
    let mut c = walking();
    for _ in 0..70 {
        tick(&mut c, run());
    }
    assert!(c.state.sprinting && c.state.sprint_fraction == 1.0);
    // R5R T3 (1014.050): the tick after the jump is no longer sprinting
    let e = tick(
        &mut c,
        MoveInput {
            jump: true,
            ..run()
        },
    );
    assert!(e.jumped && !e.sprint_ended && c.state.sprinting && !c.state.grounded);
    let e = tick(&mut c, run());
    assert!(e.sprint_ended && !c.state.sprinting);
    let e = until(&mut c, run(), 120, |_, e| e.landed.is_some());
    assert!(!e.sprint_started && c.state.sprint_fraction == 0.0);
    // sprinting again on the ground: the sticky sprint is old, so the fast rise alone (0.2 s)
    let e = until(&mut c, run(), 2, |_, e| e.sprint_started);
    assert!(c.state.sprinting && c.state.grounded, "{e:?}");
    let mut k = 0;
    for (at, measured) in [(1, -0.785), (6, -4.244), (12, -6.0)] {
        while k < at {
            tick(&mut c, run());
            k += 1;
        }
        assert!(
            (c.state.eye_sprint_offset - measured).abs() < 0.01,
            "tick {k}: {} vs R5R {measured}",
            c.state.eye_sprint_offset
        );
    }
}

#[test]
fn walking_off_an_edge_keeps_the_sprint_a_quarter_second() {
    // a platform ending at x = 100 above a floor 300 below
    let mut terrain = quad(
        Vec3::new(-1000.0, 0.0, -500.0),
        Vec3::new(100.0, 0.0, -500.0),
        Vec3::new(100.0, 0.0, 500.0),
        Vec3::new(-1000.0, 0.0, 500.0),
    );
    terrain.extend(floor(-300.0));
    let mut c = controller(&terrain, Vec3::new(-50.0, 0.0, 0.0));
    c.state.velocity.x = 260.0;
    tick(&mut c, run());
    assert!(c.state.sprinting);
    until(&mut c, run(), 60, |c, _| !c.state.grounded);
    let mut airborne_sprinting = 1;
    loop {
        let e = tick(&mut c, run());
        assert!(!e.jumped);
        if !c.state.sprinting {
            assert!(e.sprint_ended);
            break;
        }
        airborne_sprinting += 1;
        assert!(!c.state.grounded && airborne_sprinting < 30);
    }
    // 0.25 s of ticks (the 15th falls a float rounding past it)
    assert!(
        (14..=15).contains(&airborne_sprinting),
        "{airborne_sprinting}"
    );
}

#[test]
fn each_event_once() {
    let mut c = walking();
    let e = tick(&mut c, run());
    assert!(e.sprint_started && !e.sprint_ended);
    for _ in 0..30 {
        assert_eq!(tick(&mut c, run()), MoveEvents::default());
    }
    // a slide from the sprint: boosted, the duck starts, the sprint ends
    let slide = MoveInput {
        crouch: true,
        ..run()
    };
    let e = tick(&mut c, slide);
    assert_eq!(e.slide_started, Some(true));
    assert!(e.duck_started && e.sprint_ended && !e.jumped);
    assert!(c.state.sliding && c.state.slide_long_jump);
    // jumping out of it uses the slide jump
    let e = tick(
        &mut c,
        MoveInput {
            jump: true,
            ..slide
        },
    );
    assert!(e.jumped && e.landed.is_none());
    assert!(!c.state.slide_long_jump);
    let e = until(&mut c, slide, 120, |_, e| e.landed.is_some());
    let landed = e.landed.unwrap();
    // the slide jump's launch speed, sqrt(2·g·50), comes back down
    let v0 = (2.0 * c.params().gravity() * 50.0).sqrt();
    assert!(
        (landed.speed - v0).abs() < 0.03 * v0,
        "{} vs {v0}",
        landed.speed
    );
    // ducked in the air: crouched (the landing view kick ×0.2)
    assert!(landed.crouched, "{:?}", c.state);
    // releasing crouch stands up once
    let mut unducks = 0;
    for _ in 0..60 {
        let e = tick(&mut c, MoveInput::default());
        unducks += e.unduck_started as u32;
        assert!(!e.duck_started && e.slide_started.is_none());
    }
    assert_eq!(unducks, 1);
    assert_eq!(c.state.duck, Duck::Standing);
}

#[test]
fn a_second_slide_within_the_cooldown_reports_no_boost_and_keeps_the_flag() {
    let mut c = walking();
    for _ in 0..60 {
        tick(&mut c, run());
    }
    let slide = MoveInput {
        crouch: true,
        ..run()
    };
    assert_eq!(tick(&mut c, slide).slide_started, Some(true));
    // stand up and sprint again, slide again 1 s later
    for _ in 0..4 {
        tick(&mut c, slide);
    }
    until(&mut c, run(), 60, |c, _| c.state.duck == Duck::Standing);
    until(&mut c, run(), 60, |c, _| c.state.sprinting);
    let e = tick(&mut c, slide);
    assert_eq!(e.slide_started, Some(false));
    // R5R T7: the flag from the first slide is still set, so this slide has the FOV too
    assert!(c.state.sliding && c.state.slide_long_jump);
}

#[test]
fn teleport_clears_the_events_and_the_view_state() {
    let mut c = walking();
    for _ in 0..70 {
        tick(&mut c, run());
    }
    tick(
        &mut c,
        MoveInput {
            jump: true,
            ..run()
        },
    );
    c.step(&run(), FIXED_DT).unwrap();
    c.teleport(Vec3::new(0.0, 0.0, 0.0)).unwrap();
    assert_eq!(c.take_events(), MoveEvents::default());
    assert_eq!(c.state.sprint_fraction, 0.0);
    assert_eq!(c.state.eye_sprint_offset, 0.0);
    assert_eq!(c.state.duck_fraction, 0.0);
    assert_eq!(c.state.eye_height, 60.0);
    assert!(!c.state.slide_long_jump);
}
