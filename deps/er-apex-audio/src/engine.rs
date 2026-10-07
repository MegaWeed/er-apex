use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::time::Instant;

use crossbeam_queue::ArrayQueue;

use crate::Shared;
use crate::bank::SampleBank;

pub(crate) enum Command {
    Bank(Arc<SampleBank>),
    Play {
        sound: usize,
        clip: usize,
        volume: f32,
        id: u64,
        epoch: u64,
        submitted: Instant,
    },
    /// Silences every voice of this sound (plays queued before it are not affected).
    Stop { sound: usize },
}

#[derive(Clone, Copy, Default)]
struct Voice {
    active: bool,
    sound: usize,
    clip: usize,
    frame: usize,
    volume: f32,
    serial: u64,
}

pub(crate) struct Engine {
    voices: Vec<Voice>,
    bank: Arc<SampleBank>,
    queue: Arc<ArrayQueue<Command>>,
    shared: Arc<Shared>,
    epoch: u64,
    serial: u64,
}

impl Engine {
    pub fn new(
        voices: usize,
        queue: Arc<ArrayQueue<Command>>,
        shared: Arc<Shared>,
        bank: Arc<SampleBank>,
    ) -> Self {
        Self {
            voices: vec![Voice::default(); voices],
            bank,
            queue,
            shared,
            epoch: 0,
            serial: 0,
        }
    }

    fn clear(&mut self) {
        for voice in &mut self.voices {
            voice.active = false;
        }
    }

    fn start_voice(&mut self, sound: usize, clip: usize, volume: f32) {
        let definition = &self.bank.sounds[sound];
        let same_sound = self
            .voices
            .iter()
            .filter(|v| v.active && v.sound == sound)
            .count();
        let same_group = self
            .voices
            .iter()
            .filter(|v| v.active && self.bank.sounds[v.sound].group == definition.group)
            .count();
        // Replace oldest within the limiting sound/group, then oldest globally.
        let slot = if same_sound >= definition.max_instances {
            self.voices
                .iter()
                .enumerate()
                .filter(|(_, v)| v.active && v.sound == sound)
                .min_by_key(|(_, v)| v.serial)
                .map(|(i, _)| i)
        } else if same_group >= definition.group_limit {
            self.voices
                .iter()
                .enumerate()
                .filter(|(_, v)| v.active && self.bank.sounds[v.sound].group == definition.group)
                .min_by_key(|(_, v)| v.serial)
                .map(|(i, _)| i)
        } else {
            self.voices.iter().position(|v| !v.active).or_else(|| {
                self.voices
                    .iter()
                    .enumerate()
                    .min_by_key(|(_, v)| v.serial)
                    .map(|(i, _)| i)
            })
        };
        if let Some(slot) = slot {
            self.serial = self.serial.wrapping_add(1);
            self.voices[slot] = Voice {
                active: true,
                sound,
                clip,
                frame: 0,
                volume,
                serial: self.serial,
            };
        }
    }

    fn commands(&mut self, buffer_to_output_us: u64, rate: u32) {
        let epoch = self.shared.stop_epoch.load(Ordering::Acquire);
        if epoch != self.epoch {
            self.clear();
            self.epoch = epoch;
        }
        // Bounded work even if the control thread keeps filling the queue.
        for _ in 0..self.queue.capacity() {
            let Some(command) = self.queue.pop() else {
                break;
            };
            match command {
                Command::Bank(bank) => {
                    self.clear();
                    self.bank = bank;
                }
                Command::Stop { sound } => {
                    for voice in &mut self.voices {
                        if voice.sound == sound {
                            voice.active = false;
                        }
                    }
                }
                Command::Play {
                    sound,
                    clip,
                    volume,
                    id,
                    epoch,
                    submitted,
                } if epoch == self.epoch => {
                    let elapsed = submitted.elapsed().as_micros() as u64;
                    let silence = self.bank.clips[clip].leading_silence_frames as u64 * 1_000_000
                        / u64::from(rate);
                    self.start_voice(sound, clip, volume);
                    self.shared.last_request.store(0, Ordering::SeqCst);
                    self.shared.queue_us.store(elapsed, Ordering::SeqCst);
                    self.shared.output_us.store(
                        elapsed
                            .saturating_add(buffer_to_output_us)
                            .saturating_add(silence),
                        Ordering::SeqCst,
                    );
                    self.shared.last_request.store(id, Ordering::SeqCst);
                }
                _ => {}
            }
        }
    }

    fn frame(&mut self) -> [f32; 2] {
        let mut mixed = [0.0; 2];
        for voice in &mut self.voices {
            if !voice.active {
                continue;
            }
            let clip = &self.bank.clips[voice.clip];
            let sample = clip.frames[voice.frame];
            mixed[0] += sample[0] * voice.volume;
            mixed[1] += sample[1] * voice.volume;
            voice.frame += 1;
            if voice.frame == clip.frames.len() {
                voice.active = false;
            }
        }
        let mut clipped = 0;
        for sample in &mut mixed {
            if sample.abs() > 1.0 {
                clipped += 1;
            }
            *sample = sample.clamp(-1.0, 1.0);
        }
        if clipped > 0 {
            self.shared
                .clipped_samples
                .fetch_add(clipped, Ordering::Relaxed);
        }
        mixed
    }

    pub fn render<T: cpal::Sample + cpal::FromSample<f32>>(
        &mut self,
        data: &mut [T],
        channels: usize,
        rate: u32,
        info: &cpal::OutputCallbackInfo,
    ) {
        let timestamp = info.timestamp();
        let delay = timestamp
            .playback
            .duration_since(&timestamp.callback)
            .map_or(0, |d| d.as_micros() as u64);
        self.commands(delay, rate);
        self.render_samples(data, channels);
    }

    fn render_samples<T: cpal::Sample + cpal::FromSample<f32>>(
        &mut self,
        data: &mut [T],
        channels: usize,
    ) {
        self.shared
            .callback_frames
            .store((data.len() / channels) as u64, Ordering::Relaxed);
        for output in data.chunks_exact_mut(channels) {
            let frame = self.frame();
            if channels == 1 {
                output[0] = T::from_sample((frame[0] + frame[1]) * 0.5);
            } else {
                output[0] = T::from_sample(frame[0]);
                output[1] = T::from_sample(frame[1]);
                // Additional output channels stay silent; do not duplicate surround.
                for sample in &mut output[2..] {
                    *sample = T::from_sample(0.0);
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bank::{Clip, Sound};

    fn engine() -> Engine {
        let bank = Arc::new(SampleBank {
            clips: vec![Clip {
                frames: vec![[0.75, -0.75]; 16],
                leading_silence_frames: 0,
            }],
            sounds: (0..2)
                .map(|_| Sound {
                    group: 0,
                    group_limit: 2,
                    max_instances: 2,
                    variants: vec![0],
                })
                .collect(),
            names: Default::default(),
        });
        Engine::new(
            3,
            Arc::new(ArrayQueue::new(4)),
            Arc::new(Shared::default()),
            bank,
        )
    }

    #[test]
    fn callback_work_neither_allocates_nor_frees() {
        let mut engine = engine();
        // Same lifetime rule as Mixer: the control thread retains every bank.
        let _retained_old = Arc::clone(&engine.bank);
        let retained_new = Arc::new(SampleBank {
            clips: vec![Clip {
                frames: vec![[0.1, -0.1]; 256],
                leading_silence_frames: 0,
            }],
            sounds: vec![Sound {
                group: 0,
                group_limit: 2,
                max_instances: 2,
                variants: vec![0],
            }],
            names: Default::default(),
        });
        assert!(
            engine
                .queue
                .push(Command::Bank(Arc::clone(&retained_new)))
                .is_ok()
        );
        assert!(
            engine
                .queue
                .push(Command::Play {
                    sound: 0,
                    clip: 0,
                    volume: 1.0,
                    id: 1,
                    epoch: 0,
                    submitted: Instant::now(),
                })
                .is_ok()
        );
        let mut output = [0.0_f32; 960];
        let operations = crate::allocation_audit::measure(|| {
            engine.commands(10_000, 48_000);
            engine.render_samples(&mut output, 2);
            engine.shared.stop_epoch.fetch_add(1, Ordering::AcqRel);
            engine.commands(10_000, 48_000);
            engine.render_samples(&mut output, 2);
        });
        assert_eq!(operations, 0, "callback allocated or freed memory");
        assert!(output.iter().all(|&s| s == 0.0));
    }

    #[test]
    fn stop_silences_one_sound_only() {
        let mut engine = engine();
        engine.start_voice(0, 0, 1.0);
        engine.start_voice(1, 0, 1.0);
        assert!(engine.queue.push(Command::Stop { sound: 0 }).is_ok());
        let operations = crate::allocation_audit::measure(|| engine.commands(10_000, 48_000));
        assert_eq!(operations, 0, "stop allocated or freed memory");
        let active: Vec<usize> = engine.voices.iter().filter(|v| v.active).map(|v| v.sound).collect();
        assert_eq!(active, [1]);
    }

    #[test]
    fn mixing_is_limited_and_voices_expire() {
        let mut engine = engine();
        engine.start_voice(0, 0, 1.0);
        engine.start_voice(0, 0, 1.0);
        assert_eq!(engine.frame(), [1.0, -1.0]);
        assert_eq!(engine.shared.clipped_samples.load(Ordering::Relaxed), 2);
        for _ in 1..16 {
            engine.frame();
        }
        assert_eq!(engine.frame(), [0.0, 0.0]);
    }

    #[test]
    fn group_limit_spans_sound_names_and_steals_oldest() {
        let mut engine = engine();
        engine.start_voice(0, 0, 1.0);
        engine.start_voice(1, 0, 1.0);
        engine.start_voice(1, 0, 1.0);
        assert_eq!(engine.voices.iter().filter(|v| v.active).count(), 2);
        assert!(
            engine
                .voices
                .iter()
                .filter(|v| v.active)
                .all(|v| v.sound == 1)
        );
    }

    #[test]
    fn stop_invalidates_queued_plays_even_with_full_queue() {
        let mut engine = engine();
        engine.start_voice(0, 0, 1.0);
        for id in 1..=4 {
            assert!(
                engine
                    .queue
                    .push(Command::Play {
                        sound: 0,
                        clip: 0,
                        volume: 1.0,
                        id,
                        epoch: 0,
                        submitted: Instant::now()
                    })
                    .is_ok()
            );
        }
        engine.shared.stop_epoch.fetch_add(1, Ordering::AcqRel);
        engine.commands(0, 48_000);
        assert_eq!(engine.frame(), [0.0, 0.0]);
        assert!(engine.queue.is_empty());
        assert!(
            engine
                .queue
                .push(Command::Play {
                    sound: 0,
                    clip: 0,
                    volume: 0.5,
                    id: 5,
                    epoch: 1,
                    submitted: Instant::now()
                })
                .is_ok()
        );
        engine.commands(0, 48_000);
        assert_eq!(engine.frame(), [0.375, -0.375]);
    }
}
