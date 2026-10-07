use er_apex_anim::{Pack, Trs};
use std::{hint::black_box, time::Instant};
fn main() {
    let path = std::env::var_os("FUSE_ANIM_PACK")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| {
            std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../../apex-data/anim/fuse.anim")
        });
    let pack =
        Pack::parse(&std::fs::read(&path).expect("run python tools/fuseanim/export_anim.py first"))
            .expect("valid pack");
    let mut pose = vec![Trs::default(); pack.bones().len()];
    let n = 30_000;
    println!("231-bone full pose, fractional frame, allocation-free sampling:");
    for name in [
        "fuse_idle_rifle",
        "fuse_run_rifle_F#1",
        "fuse_slide_rifle",
        "medium_jump_rifle_F#1",
        "fuse_idle_rifle_fire",
        "mp_pt_medium_reload_rspn101",
    ] {
        let clip = pack.clip_by_name(name).expect("selected clip");
        let period = pack.clips()[clip].loop_period_s();
        for i in 0..1000 {
            pack.sample(clip, (i as f64 * 0.0173) % period, true, &mut pose)
                .unwrap();
            black_box(&pose);
        }
        let mut results = Vec::new();
        for _ in 0..5 {
            let start = Instant::now();
            for i in 0..n {
                pack.sample(
                    black_box(clip),
                    black_box((i as f64 * 0.0173) % period),
                    true,
                    black_box(&mut pose),
                )
                .unwrap();
                black_box(&pose);
            }
            results.push(start.elapsed().as_secs_f64() * 1e6 / n as f64);
        }
        results.sort_by(f64::total_cmp);
        println!(
            "{name}: median {:.3} us; min {:.3}; max {:.3}",
            results[2], results[0], results[4]
        );
        assert!(results[2] < 20., "sampling target exceeded");
    }
}
