//! Preloaded one-shot mixer. File I/O, decoding and resampling run on the caller.
//! The callback uses a bounded queue, fixed voice slots and immutable sample banks.
//! Keep `Mixer` alive for the lifetime of playback; call `load_manifest` at startup.

#[cfg(test)]
mod allocation_audit;
mod bank;
mod engine;

use std::collections::BTreeMap;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::time::Instant;

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use crossbeam_queue::ArrayQueue;
use thiserror::Error;

pub use bank::{Manifest, SoundDefinition, VariantDefinition};
use bank::{SampleBank, load_bank};
use engine::{Command, Engine};

#[derive(Debug, Error)]
pub enum AudioError {
    #[error("no default audio output device")]
    NoOutputDevice,
    #[error("audio backend: {0}")]
    Backend(String),
    #[error("invalid mixer configuration: {0}")]
    Config(&'static str),
    #[error("manifest: {0}")]
    Manifest(String),
    #[error("WAV: {0}")]
    Wav(String),
    #[error("I/O: {0}")]
    Io(#[from] std::io::Error),
    #[error("unknown sound: {0}")]
    UnknownSound(String),
    #[error("volume must be finite and between 0 and 4")]
    InvalidVolume,
    #[error("audio command queue is full; request was not accepted")]
    QueueFull,
}

pub type Result<T> = std::result::Result<T, AudioError>;

/// Limits apply to the sum of all voices in a group, across sound names.
#[derive(Clone, Debug)]
pub struct MixerConfig {
    pub max_voices: usize,
    pub command_capacity: usize,
    pub group_limits: BTreeMap<String, usize>,
    /// Request a buffer only if the default format advertises a supported range.
    /// Otherwise use the backend default. WASAPI shared mode can override this.
    pub preferred_buffer_frames: u32,
}

impl Default for MixerConfig {
    fn default() -> Self {
        Self {
            max_voices: 32,
            command_capacity: 256,
            group_limits: BTreeMap::from([("weapon".into(), 16), ("reload".into(), 4)]),
            preferred_buffer_frames: 128,
        }
    }
}

#[derive(Clone, Debug)]
pub struct OutputInfo {
    pub device_name: String,
    pub sample_rate: u32,
    pub channels: u16,
    pub sample_format: cpal::SampleFormat,
    pub requested_buffer_frames: Option<u32>,
}

/// Backend timestamps estimate buffer-to-DAC delay, not acoustic measurement.
#[derive(Clone, Copy, Debug)]
pub struct PlaybackTiming {
    pub request_id: u64,
    pub queue_to_callback_us: u64,
    pub estimated_call_to_output_us: u64,
}

#[derive(Default)]
pub(crate) struct Shared {
    stop_epoch: AtomicU64,
    last_request: AtomicU64,
    queue_us: AtomicU64,
    output_us: AtomicU64,
    callback_frames: AtomicU64,
    backend_failed: AtomicBool,
    clipped_samples: AtomicU64,
}

pub struct Mixer {
    // Drop stream before retained banks. Callback never releases the final bank owner.
    _stream: cpal::Stream,
    queue: Arc<ArrayQueue<Command>>,
    shared: Arc<Shared>,
    retained_banks: Vec<Arc<SampleBank>>,
    current: Arc<SampleBank>,
    rotations: Vec<usize>,
    config: MixerConfig,
    output: OutputInfo,
    next_request: u64,
}

impl Mixer {
    pub fn new() -> Result<Self> {
        Self::with_config(MixerConfig::default())
    }

    pub fn with_config(config: MixerConfig) -> Result<Self> {
        if config.max_voices == 0 || config.command_capacity == 0 {
            return Err(AudioError::Config("voice/command limits must be nonzero"));
        }
        if config.group_limits.values().any(|&n| n == 0) {
            return Err(AudioError::Config("group limits must be nonzero"));
        }
        let device = cpal::default_host()
            .default_output_device()
            .ok_or(AudioError::NoOutputDevice)?;
        let supported = device
            .default_output_config()
            .map_err(|e| AudioError::Backend(e.to_string()))?;
        let format = supported.sample_format();
        let mut stream_config: cpal::StreamConfig = supported.clone().into();
        if stream_config.channels == 0 || stream_config.sample_rate.0 == 0 {
            return Err(AudioError::Backend("invalid default output format".into()));
        }
        let requested_buffer_frames = match supported.buffer_size() {
            cpal::SupportedBufferSize::Range { min, max } if config.preferred_buffer_frames > 0 => {
                let frames = config.preferred_buffer_frames.clamp(*min, *max);
                stream_config.buffer_size = cpal::BufferSize::Fixed(frames);
                Some(frames)
            }
            _ => None,
        };
        let output = OutputInfo {
            device_name: device.name().unwrap_or_else(|_| "default output".into()),
            sample_rate: stream_config.sample_rate.0,
            channels: stream_config.channels,
            sample_format: format,
            requested_buffer_frames,
        };
        let queue = Arc::new(ArrayQueue::new(config.command_capacity));
        let shared = Arc::new(Shared::default());
        let bank = Arc::new(SampleBank::default());
        let engine = Engine::new(
            config.max_voices,
            Arc::clone(&queue),
            Arc::clone(&shared),
            Arc::clone(&bank),
        );
        let error_state = Arc::clone(&shared);
        // An error callback records a flag: formatting/logging is left to the caller.
        let on_error = move |_| error_state.backend_failed.store(true, Ordering::Relaxed);
        let channels = usize::from(stream_config.channels);
        let rate = stream_config.sample_rate.0;
        macro_rules! build {
            ($sample:ty) => {{
                let mut engine = engine;
                device.build_output_stream(
                    &stream_config,
                    move |data: &mut [$sample], info| engine.render(data, channels, rate, info),
                    on_error,
                    None,
                )
            }};
        }
        let stream = match format {
            cpal::SampleFormat::F32 => build!(f32),
            cpal::SampleFormat::F64 => build!(f64),
            cpal::SampleFormat::I8 => build!(i8),
            cpal::SampleFormat::I16 => build!(i16),
            cpal::SampleFormat::I32 => build!(i32),
            cpal::SampleFormat::I64 => build!(i64),
            cpal::SampleFormat::U8 => build!(u8),
            cpal::SampleFormat::U16 => build!(u16),
            cpal::SampleFormat::U32 => build!(u32),
            cpal::SampleFormat::U64 => build!(u64),
            other => {
                return Err(AudioError::Backend(format!(
                    "unsupported output sample format {other}"
                )));
            }
        }
        .map_err(|e| AudioError::Backend(e.to_string()))?;
        stream
            .play()
            .map_err(|e| AudioError::Backend(e.to_string()))?;
        Ok(Self {
            _stream: stream,
            queue,
            shared,
            retained_banks: vec![Arc::clone(&bank)],
            current: bank,
            rotations: Vec::new(),
            config,
            output,
            next_request: 0,
        })
    }

    /// Load `dir/manifest.json` transactionally; a failure keeps the current bank.
    /// On success the next callback replaces the bank and clears existing voices.
    /// Old banks stay retained until Mixer is dropped to avoid callback destruction.
    pub fn load_manifest(&mut self, dir: impl AsRef<Path>) -> Result<usize> {
        self.load_manifests(&[dir.as_ref()])
    }

    /// As `load_manifest`, with the sounds of several manifests in one bank (a name may appear in
    /// only one of them).
    pub fn load_manifests(&mut self, dirs: &[&Path]) -> Result<usize> {
        let bank = Arc::new(load_bank(
            dirs,
            self.output.sample_rate,
            self.config.max_voices,
            &self.config.group_limits,
        )?);
        let count = bank.sounds.len();
        let rotations = vec![0; count];
        // Retain BEFORE enqueue so the callback is never the sole owner.
        self.retained_banks.push(Arc::clone(&bank));
        if self.queue.push(Command::Bank(Arc::clone(&bank))).is_err() {
            self.retained_banks.pop();
            return Err(AudioError::QueueFull);
        }
        self.current = bank;
        self.rotations = rotations;
        Ok(count)
    }

    /// Round-robin variants; gain 0..=4. Return a request ID for timing inspection.
    /// Full queues report an error, without advancing the variant rotation.
    pub fn play(&mut self, name: &str, volume: f32) -> Result<u64> {
        if !volume.is_finite() || !(0.0..=4.0).contains(&volume) {
            return Err(AudioError::InvalidVolume);
        }
        let &sound = self
            .current
            .names
            .get(name)
            .ok_or_else(|| AudioError::UnknownSound(name.into()))?;
        let variants = &self.current.sounds[sound].variants;
        let rotation = self.rotations[sound];
        let id = self.next_request.wrapping_add(1).max(1);
        let command = Command::Play {
            sound,
            clip: variants[rotation],
            volume,
            id,
            epoch: self.shared.stop_epoch.load(Ordering::Acquire),
            submitted: Instant::now(),
        };
        self.queue
            .push(command)
            .map_err(|_| AudioError::QueueFull)?;
        self.rotations[sound] = (rotation + 1) % variants.len();
        self.next_request = id;
        Ok(id)
    }

    /// Silences the voices of one sound at the next callback (a charge sound cut short).
    pub fn stop(&mut self, name: &str) -> Result<()> {
        let &sound = self
            .current
            .names
            .get(name)
            .ok_or_else(|| AudioError::UnknownSound(name.into()))?;
        self.queue
            .push(Command::Stop { sound })
            .map_err(|_| AudioError::QueueFull)
    }

    /// Clears voices at the next callback and invalidates all older queued plays.
    /// This succeeds even when the command queue is full.
    pub fn stop_all(&self) {
        self.shared.stop_epoch.fetch_add(1, Ordering::AcqRel);
    }

    pub fn output_info(&self) -> &OutputInfo {
        &self.output
    }

    pub fn callback_frames(&self) -> u64 {
        self.shared.callback_frames.load(Ordering::Relaxed)
    }

    pub fn last_playback_timing(&self) -> Option<PlaybackTiming> {
        // A sequence stamp prevents reading metrics halfway through a publication.
        let id = self.shared.last_request.load(Ordering::SeqCst);
        if id == 0 {
            return None;
        }
        let result = PlaybackTiming {
            request_id: id,
            queue_to_callback_us: self.shared.queue_us.load(Ordering::SeqCst),
            estimated_call_to_output_us: self.shared.output_us.load(Ordering::SeqCst),
        };
        (id == self.shared.last_request.load(Ordering::SeqCst)).then_some(result)
    }

    pub fn backend_failed(&self) -> bool {
        self.shared.backend_failed.load(Ordering::Relaxed)
    }

    pub fn clipped_samples(&self) -> u64 {
        self.shared.clipped_samples.load(Ordering::Relaxed)
    }

    pub fn sound_names(&self) -> impl Iterator<Item = &str> {
        self.current.names.keys().map(String::as_str)
    }

    pub fn sound_duration_seconds(&self, name: &str) -> Option<f64> {
        let &index = self.current.names.get(name)?;
        self.current.sounds[index]
            .variants
            .iter()
            .map(|&clip| {
                self.current.clips[clip].frames.len() as f64 / f64::from(self.output.sample_rate)
            })
            .reduce(f64::max)
    }
}
