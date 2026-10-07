//! The frag grenade in the view model (U9, spike/grenade.rs), with T022's grenade (carrier group 6)
//! and its clips (`frag_*`, retail `ptpov_frag_grenade_held.rrig`). G is a weapon switch in S3: the
//! weapon in the hands goes away (its `holster`, 16 frames over its `holster_time`: the R-301's 0.55
//! s, ptpov_rspn101.qc; with the Charge Rifle in the hands pov/mod.rs plays its `cr_holster` for the
//! name, over its 0.5 s), held at its end and hidden; then the grenade:
//! - `draw_seq` (17 frames) over `deploy_time` 0.6 s, `idle_seq` (47, looping) after it, its crouch
//!   (`idle_seq_crouch`) by crouchFraction and `sprinting_seq` (21 at 36 fps) while sprinting;
//! - the pin: `toss_prep_pullout_seq` (13) over `toss_pullout_time` 0.25 s, then `toss_hold_seq` (38,
//!   looping) while the trigger is held (`toss_hold_sprinting_seq` sprinting);
//! - the throw: `toss_seq` (18) over `toss_time` 0.4 s, released at AE_WPN_TOSS_RELEASE (frame 7 of 17),
//!   or overhead `toss_overhead_seq` (24) over `toss_overhead_time` 0.7 s (frame 6 of 23): the
//!   grenade hidden from the release (the thrown one is drawn in the world: groups 7/8);
//! - put away unthrown: `holster_seq` (15 frames) over 14/30 s;
//! then the weapon's `draw` (the R-301's 26 frames, by crouch) over its `deploy_time` (0.6 s; the
//! Charge Rifle's `cr_draw` over 0.8 s), firing from AE_WPN_READYTOFIRE (frame 12 of 25; of 20).
//! The weapon's times come with the view (grenade.rs `HandView`). Each clip over the arms by its weight list (Masked), a new one
//! fading in over its QC `fadein` (0.05 for the tosses, else 0.1: 推断).
//!
//! Without T022's pack (no `frag_*` clips) the grenade's clips find nothing and the arms stay at the
//! weapon's put-away (phase 1).

use super::ability::{Layer, Mode, Out, Params};
use crate::spike::grenade::{HandView, VIEW_DEPLOY, VIEW_HOLSTER, VIEW_PREP, VIEW_RELEASE, VIEW_RELEASE_OVERHEAD, VIEW_TOSS, VIEW_TOSS_OVERHEAD};

const HOLSTER: &str = "holster";
const DRAW: &str = "draw";
/// The put-away's fade in, as the pad's (ability.rs); the grenade clips' fades.
const FADE_IN: f32 = 0.1;
const TOSS_FADE: f32 = 0.05;
/// Loop lengths (s): `idle_seq` 47 frames, `toss_hold_seq` 38, at 30 fps; the sprints 21 at 36.
const IDLE_LOOP: f32 = 46.0 / 30.0;
const HOLD_LOOP: f32 = 37.0 / 30.0;
const SPRINT_LOOP: f32 = 20.0 / 36.0;

fn one(name: &str) -> Vec<(String, f32)> {
    vec![(format!("{name}_0"), 1.0)]
}

fn ramp(t: f32, fade: f32) -> f32 {
    if fade > 0.0 { (t / fade).clamp(0.0, 1.0) } else { 1.0 }
}

/// The grenade's resting loop under a one-shot: idle (by crouch) or its sprint; the pin held: the
/// hold or its sprint.
fn rest(held: bool, t: f32, p: Params, o: &mut Out) {
    let mask = |samples, cycle| Layer { samples, cycle, weight: 1.0, mode: Mode::Masked };
    if p.sprinting {
        let name = if held { "frag_toss_hold_sprinting_seq" } else { "frag_sprinting_seq" };
        o.layers.push(mask(one(name), (t / SPRINT_LOOP).rem_euclid(1.0)));
    } else if held {
        o.layers.push(mask(one("frag_toss_hold_seq"), (t / HOLD_LOOP).rem_euclid(1.0)));
    } else {
        let c = p.crouch.clamp(0.0, 1.0);
        let samples = [("frag_idle_seq_0".to_string(), 1.0 - c), ("frag_idle_seq_crouch_0".to_string(), c)].into_iter().filter(|s| s.1 > 0.0).collect();
        o.layers.push(mask(samples, (t / IDLE_LOOP).rem_euclid(1.0)));
    }
}

/// The view model's layers and groups while the grenade is out.
pub fn out(v: HandView, p: Params) -> Out {
    if p.other_weapon {
        // the Charge Rifle in hand without its own clips (T022 not installed): its put-away is the
        // weapon slots' (no layers here)
        return Out { show_gun: false, gun_away: !matches!(v, HandView::Back(..)), ..Default::default() };
    }
    let mut o = Out { show_gun: false, gun_away: true, ..Default::default() };
    let shot = |name: &str, t: f32, length: f32, fade: f32| Layer { samples: one(name), cycle: (t / length).clamp(0.0, 1.0), weight: ramp(t, fade), mode: Mode::Masked };
    match v {
        HandView::Away(t, holster) => {
            let t = t.max(0.0);
            let cycle = (t / holster.max(1e-3)).min(1.0);
            let weight = if t.is_finite() { ramp(t, FADE_IN) } else { 1.0 };
            o.layers.push(Layer { samples: one(HOLSTER), cycle, weight, mode: Mode::Over });
            o.show_gun = cycle < 1.0;
        }
        HandView::Out(t) => {
            let t = t.max(0.0);
            // the weapon's put-away under it (the arms below the view until the draw lifts them)
            o.layers.push(Layer { samples: one(HOLSTER), cycle: 1.0, weight: 1.0, mode: Mode::Over });
            o.show_frag = true;
            if t < VIEW_DEPLOY {
                o.layers.push(shot("frag_draw_seq", t, VIEW_DEPLOY, 0.0));
            } else {
                rest(false, t - VIEW_DEPLOY, p, &mut o);
            }
        }
        HandView::Prep(t) => {
            let t = t.max(0.0);
            o.show_frag = true;
            rest(false, t, p, &mut o);
            if t < VIEW_PREP {
                o.layers.push(shot("frag_toss_prep_pullout_seq", t, VIEW_PREP, FADE_IN.min(VIEW_PREP)));
            } else {
                rest(true, t - VIEW_PREP, p, &mut o);
            }
        }
        HandView::Toss(t, overhead) => {
            let t = t.max(0.0);
            let (name, length, release) = if overhead { ("frag_toss_overhead_seq", VIEW_TOSS_OVERHEAD, VIEW_RELEASE_OVERHEAD) } else { ("frag_toss_seq", VIEW_TOSS, VIEW_RELEASE) };
            rest(true, 0.0, p, &mut o);
            o.layers.push(shot(name, t, length, TOSS_FADE));
            // in the hand until AE_WPN_TOSS_RELEASE
            o.show_frag = t < length * release;
        }
        HandView::Holster(t) => {
            let t = t.max(0.0);
            o.show_frag = true;
            rest(false, 0.0, p, &mut o);
            o.layers.push(shot("frag_holster_seq", t, VIEW_HOLSTER, FADE_IN));
        }
        HandView::Back(t, deploy, ready) => {
            let cycle = (t.max(0.0) / deploy.max(1e-3)).min(1.0);
            let crouch = p.crouch.clamp(0.0, 1.0);
            let mut samples = vec![(format!("{DRAW}_0"), 1.0 - crouch), (format!("{DRAW}_1"), crouch)];
            samples.retain(|s| s.1 > 0.0);
            o.layers.push(Layer { samples, cycle, weight: 1.0, mode: Mode::Over });
            o.show_gun = true;
            o.gun_away = cycle < ready;
        }
    }
    o
}

#[cfg(test)]
mod tests {
    use super::*;

    /// G: the weapon goes away over 0.55 s and hides at its end, unable to fire throughout; back: its
    /// draw over 0.6 s, firing again from frame 12 of 25, crouched by the crouched sample.
    #[test]
    fn away_and_back() {
        let p = Params::default();
        let o = out(HandView::Away(0.05, 0.55), p);
        assert!(o.show_gun && o.gun_away && !o.show_frag && o.layers[0].samples[0].0 == "holster_0" && (o.layers[0].weight - 0.5).abs() < 1e-5);
        let o = out(HandView::Away(0.275, 0.55), p);
        assert!((o.layers[0].cycle - 0.5).abs() < 1e-5 && o.show_gun);
        let o = out(HandView::Away(0.6, 0.55), p);
        assert!(!o.show_gun && o.gun_away && o.layers[0].cycle == 1.0);
        let o = out(HandView::Back(0.1, 0.6, 12.0 / 25.0), p);
        assert!(o.show_gun && o.gun_away && !o.show_frag && o.layers[0].samples == vec![("draw_0".to_string(), 1.0)]);
        let o = out(HandView::Back(0.6 * 12.0 / 25.0 + 0.01, 0.6, 12.0 / 25.0), p);
        assert!(!o.gun_away);
        let o = out(HandView::Back(0.3, 0.6, 12.0 / 25.0), Params { crouch: 1.0, ..p });
        assert_eq!(o.layers[0].samples, vec![("draw_1".to_string(), 1.0)]);
    }

    fn names(o: &Out) -> Vec<String> {
        o.layers.iter().flat_map(|l| l.samples.iter().map(|s| s.0.clone())).collect()
    }

    /// The grenade: drawn over 0.6 s then idling (its crouch, its sprint); the pin over 0.25 s then
    /// held; the throw shown in the hand until its release frame; the put-away.
    #[test]
    fn the_grenade_in_the_hand() {
        let p = Params::default();
        let o = out(HandView::Out(0.3), p);
        assert!(o.show_frag && !o.show_gun && o.gun_away);
        let draw = o.layers.iter().find(|l| l.samples[0].0 == "frag_draw_seq_0").expect("draw");
        assert!((draw.cycle - 0.5).abs() < 1e-5 && draw.mode == Mode::Masked);
        assert!(names(&out(HandView::Out(1.0), p)).contains(&"frag_idle_seq_0".to_string()));
        assert!(names(&out(HandView::Out(1.0), Params { crouch: 1.0, ..p })).contains(&"frag_idle_seq_crouch_0".to_string()));
        assert!(names(&out(HandView::Out(1.0), Params { sprinting: true, ..p })).contains(&"frag_sprinting_seq_0".to_string()));
        let o = out(HandView::Prep(0.125), p);
        let pull = o.layers.iter().find(|l| l.samples[0].0 == "frag_toss_prep_pullout_seq_0").expect("pin");
        assert!((pull.cycle - 0.5).abs() < 1e-5 && o.show_frag);
        assert!(names(&out(HandView::Prep(0.6), p)).contains(&"frag_toss_hold_seq_0".to_string()));
        // underhand: in the hand until 7/17 of 0.4 s
        assert!(out(HandView::Toss(0.4 * 7.0 / 17.0 - 0.01, false), p).show_frag);
        let o = out(HandView::Toss(0.4 * 7.0 / 17.0 + 0.01, false), p);
        assert!(!o.show_frag && names(&o).contains(&"frag_toss_seq_0".to_string()));
        // overhead: until 6/23 of 0.7 s
        assert!(out(HandView::Toss(0.7 * 6.0 / 23.0 - 0.01, true), p).show_frag);
        assert!(names(&out(HandView::Toss(0.1, true), p)).contains(&"frag_toss_overhead_seq_0".to_string()));
        let o = out(HandView::Holster(0.2), p);
        assert!(o.show_frag && names(&o).contains(&"frag_holster_seq_0".to_string()));
    }
}
