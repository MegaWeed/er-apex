use std::path::PathBuf;
use std::time::{Duration, Instant};

use er_apex_audio::Mixer;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let name = args.first().map_or("fire_3p", String::as_str);
    let dir = args.get(1).map_or_else(
        || PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../apex-data/audio"),
        PathBuf::from,
    );
    let volume: f32 = args.get(2).map_or(Ok(0.5), |v| v.parse())?;
    let mut mixer = Mixer::new()?;
    println!("Output: {:?}", mixer.output_info());
    let loaded = mixer.load_manifest(&dir)?;
    println!("Loaded {loaded} names from {}", dir.display());
    if name == "--list" {
        for name in mixer.sound_names() {
            println!("{name}");
        }
        return Ok(());
    }
    std::thread::sleep(Duration::from_millis(50));
    let duration = mixer.sound_duration_seconds(name).unwrap_or(1.0);
    let started = Instant::now();
    let request = mixer.play(name, volume)?;
    println!(
        "play({name}, {volume}): caller returned in {:.3} ms",
        started.elapsed().as_secs_f64() * 1000.0
    );
    loop {
        if let Some(timing) = mixer
            .last_playback_timing()
            .filter(|t| t.request_id == request)
        {
            println!(
                "Queue to callback: {:.3} ms; estimated call to first nonzero output: {:.3} ms; callback {} frames ({:.3} ms)",
                timing.queue_to_callback_us as f64 / 1000.0,
                timing.estimated_call_to_output_us as f64 / 1000.0,
                mixer.callback_frames(),
                mixer.callback_frames() as f64 * 1000.0
                    / f64::from(mixer.output_info().sample_rate)
            );
            println!(
                "Estimate uses CPAL playback timestamp + WAV leading silence; no acoustic loopback measurement."
            );
            break;
        }
        if mixer.backend_failed() || started.elapsed() > Duration::from_secs(2) {
            return Err("no callback acknowledgement (output device error/timeout)".into());
        }
        std::thread::sleep(Duration::from_millis(1));
    }
    std::thread::sleep(Duration::from_secs_f64(duration + 0.2));
    mixer.stop_all();
    println!(
        "Clamped samples: {}; backend failed: {}",
        mixer.clipped_samples(),
        mixer.backend_failed()
    );
    if mixer.backend_failed() {
        return Err("audio backend failed during playback".into());
    }
    Ok(())
}
