//! Owned validated fuse.anim v0 reader; no game or third-party dependencies.
//! Parent-local TRS, xyzw quaternions and inches.
use std::fmt;
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Trs {
    pub translation: [f32; 3],
    pub rotation: [f32; 4],
    pub scale: [f32; 3],
}
impl Default for Trs {
    fn default() -> Self {
        Self {
            translation: [0.; 3],
            rotation: [0., 0., 0., 1.],
            scale: [1.; 3],
        }
    }
}
#[derive(Clone, Debug)]
pub struct Bone {
    pub name: String,
    pub parent: Option<usize>,
    pub rest: Trs,
}
#[derive(Clone, Debug, PartialEq)]
pub struct Event {
    pub frame: u32,
    pub name: String,
    pub parameter: String,
}
#[derive(Clone, Copy, Debug)]
pub struct EventOccurrence<'a> {
    pub event: &'a Event,
    pub time_s: f64,
}
#[derive(Clone, Debug)]
pub struct Clip {
    pub name: String,
    pub sequence: String,
    pub source_path: String,
    pub rig: String,
    pub guid: u64,
    pub fps: f32,
    pub frame_count: u32,
    pub looping: bool,
    pub additive: bool,
    pub sample_index: u32,
    pub sample_count: u32,
    /// QC axes/coordinates, activity, modifiers, layers, source token and raw QC.
    pub metadata_json: String,
    events: Vec<Event>,
    tracks: Vec<Track>,
    root: Option<RootTrack>,
}
impl Clip {
    /// Frame endpoint convention: (N-1)/fps seconds.
    pub fn duration_s(&self) -> f64 {
        f64::from(self.frame_count - 1) / f64::from(self.fps)
    }
    /// Single-frame clips have a one-frame event repeat period.
    pub fn loop_period_s(&self) -> f64 {
        self.duration_s().max(1. / f64::from(self.fps))
    }
    pub fn events(&self) -> &[Event] {
        &self.events
    }
}
#[derive(Clone, Debug)]
struct Track {
    bone: usize,
    additive: bool,
    weights: [f32; 3],
    translations: Vec<[f32; 3]>,
    rotations: Vec<[f32; 4]>,
    scales: Vec<[f32; 3]>,
}
#[derive(Clone, Debug)]
struct RootTrack {
    bone: usize,
    translations: Vec<[f32; 3]>,
    rotations: Vec<[f32; 4]>,
}
/// Relative rigid transform in root axes at interval start.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct RootDelta {
    pub translation: [f32; 3],
    pub rotation: [f32; 4],
}
impl Default for RootDelta {
    fn default() -> Self {
        Self {
            translation: [0.; 3],
            rotation: [0., 0., 0., 1.],
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Truncated,
    BadMagic,
    UnsupportedVersion,
    LengthMismatch,
    ChecksumMismatch,
    InvalidData(&'static str),
    InvalidClip,
    OutputTooSmall,
    InvalidTime,
    TooManyEvents,
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for Error {}
#[derive(Clone, Debug)]
pub struct Pack {
    bones: Vec<Bone>,
    clips: Vec<Clip>,
    rest: Vec<Trs>,
}
impl Pack {
    /// Validates CRC, all lengths, parents, indices, channels and floats.
    /// Parsing allocates, sampling does not. Bad bytes return an error.
    pub fn parse(bytes: &[u8]) -> Result<Self, Error> {
        let mut r = Reader::new(bytes);
        if r.take(8)? != b"FUSEANIM" {
            return Err(Error::BadMagic);
        }
        if r.u32()? != 0 {
            return Err(Error::UnsupportedVersion);
        }
        if r.u64()? != bytes.len() as u64 {
            return Err(Error::LengthMismatch);
        }
        let nb = r.u32()? as usize;
        let nc = r.u32()? as usize;
        let crc = r.u32()?;
        if crc32(r.bytes) != crc {
            return Err(Error::ChecksumMismatch);
        }
        if nb == 0 || nb > 65535 || nb > r.bytes.len() / 46 {
            return Err(Error::InvalidData("bone count"));
        }
        let mut bones = Vec::new();
        let mut names = std::collections::HashSet::new();
        for i in 0..nb {
            let name = r.string()?;
            if name.is_empty() || !names.insert(name.clone()) {
                return Err(Error::InvalidData("bone name"));
            }
            let p = r.i32()?;
            if p < -1 || p >= i as i32 {
                return Err(Error::InvalidData("bone parent"));
            }
            let rest = Trs {
                translation: r.vector()?,
                rotation: r.unit_quat()?,
                scale: r.vector()?,
            };
            bones.push(Bone {
                name,
                parent: (p >= 0).then_some(p as usize),
                rest,
            });
        }
        if nc > r.bytes.len() / 4 {
            return Err(Error::InvalidData("clip count"));
        }
        let mut clips = Vec::new();
        let mut names = std::collections::HashSet::new();
        for _ in 0..nc {
            let len = r.u32()? as usize;
            let mut c = Reader::new(r.take(len)?);
            let name = c.string()?;
            if name.is_empty() || !names.insert(name.clone()) {
                return Err(Error::InvalidData("clip name"));
            }
            let sequence = c.string()?;
            let source_path = c.string()?;
            let rig = c.string()?;
            let guid = c.u64()?;
            let fps = c.float()?;
            let frame_count = c.u32()?;
            let flags = c.u32()?;
            let sample_index = c.u32()?;
            let sample_count = c.u32()?;
            let nt = c.u32()? as usize;
            if fps <= 0.
                || frame_count == 0
                || frame_count > 1_000_000
                || flags & !3 != 0
                || sample_count == 0
                || sample_index >= sample_count
                || nt > nb
            {
                return Err(Error::InvalidData("clip header"));
            }
            let metadata_json = c.string()?;
            let rb = c.i32()?;
            let root = if rb == -1 {
                None
            } else {
                if rb < 0 || rb as usize >= nb || bones[rb as usize].parent.is_some() {
                    return Err(Error::InvalidData("root bone"));
                }
                let translations = c.vectors(frame_count)?;
                let rotations = c.quaternions(frame_count)?;
                if translations.is_empty() || rotations.is_empty() {
                    return Err(Error::InvalidData("empty root"));
                }
                Some(RootTrack {
                    bone: rb as usize,
                    translations,
                    rotations,
                })
            };
            let mut tracks = Vec::new();
            let mut used = vec![false; nb];
            if let Some(root) = &root {
                used[root.bone] = true;
            }
            for _ in 0..nt {
                let bone = c.u16()? as usize;
                let mode = c.u8()?;
                let mask = c.u8()?;
                if bone >= nb || used[bone] || mode > 1 || mask == 0 || mask & !7 != 0 {
                    return Err(Error::InvalidData("track header"));
                }
                used[bone] = true;
                let weights: [f32; 3] = c.vector()?;
                if weights.iter().any(|v| !(0. ..=1.).contains(v)) {
                    return Err(Error::InvalidData("weight"));
                }
                let translations = c.vectors(frame_count)?;
                let rotations = c.quaternions(frame_count)?;
                let scales = c.vectors(frame_count)?;
                let actual = u8::from(!translations.is_empty())
                    | (u8::from(!rotations.is_empty()) << 1)
                    | (u8::from(!scales.is_empty()) << 2);
                if actual != mask {
                    return Err(Error::InvalidData("channel mask"));
                }
                tracks.push(Track {
                    bone,
                    additive: mode == 1,
                    weights,
                    translations,
                    rotations,
                    scales,
                });
            }
            if tracks.iter().any(|t| t.additive) != (flags & 2 != 0) {
                return Err(Error::InvalidData("additive flag"));
            }
            let ne = c.u32()? as usize;
            if ne > c.bytes.len() / 8 {
                return Err(Error::InvalidData("event count"));
            }
            let mut events = Vec::new();
            let mut prev = 0;
            for _ in 0..ne {
                let frame = c.u32()?;
                let name = c.string()?;
                let parameter = c.string()?;
                if frame >= frame_count || frame < prev || name.is_empty() {
                    return Err(Error::InvalidData("event"));
                }
                prev = frame;
                events.push(Event {
                    frame,
                    name,
                    parameter,
                });
            }
            if !c.bytes.is_empty() {
                return Err(Error::LengthMismatch);
            }
            clips.push(Clip {
                name,
                sequence,
                source_path,
                rig,
                guid,
                fps,
                frame_count,
                looping: flags & 1 != 0,
                additive: flags & 2 != 0,
                sample_index,
                sample_count,
                metadata_json,
                events,
                tracks,
                root,
            });
        }
        if !r.bytes.is_empty() {
            return Err(Error::LengthMismatch);
        }
        let rest = bones.iter().map(|b| b.rest).collect();
        Ok(Self { bones, clips, rest })
    }
    pub fn bones(&self) -> &[Bone] {
        &self.bones
    }
    pub fn clips(&self) -> &[Clip] {
        &self.clips
    }
    /// Multi-sample clips have sequence#0, sequence#1 names.
    pub fn clip_by_name(&self, name: &str) -> Option<usize> {
        self.clips.iter().position(|c| c.name == name)
    }
    /// Initialize ALL bones from model rest, apply channels, hold root at frame
    /// zero. Additive clips compose onto rest. looping overrides stored flag.
    pub fn sample(
        &self,
        clip: usize,
        time_s: f64,
        looping: bool,
        out: &mut [Trs],
    ) -> Result<(), Error> {
        let c = self.clips.get(clip).ok_or(Error::InvalidClip)?;
        let f = frame_at(c, time_s, looping)?;
        if out.len() < self.bones.len() {
            return Err(Error::OutputTooSmall);
        }
        out[..self.bones.len()].copy_from_slice(&self.rest);
        apply_tracks(c, f, out);
        Ok(())
    }
    /// Layer on an existing pose: absolute replaces, additive uses Cast weights,
    /// missing channels retain input. Use for fire over sampled idle/run.
    pub fn apply(
        &self,
        clip: usize,
        time_s: f64,
        looping: bool,
        out: &mut [Trs],
    ) -> Result<(), Error> {
        let c = self.clips.get(clip).ok_or(Error::InvalidClip)?;
        let f = frame_at(c, time_s, looping)?;
        if out.len() < self.bones.len() {
            return Err(Error::OutputTooSmall);
        }
        apply_tracks(c, f, out);
        Ok(())
    }
    /// G(start)^-1 G(end), with cumulative SE(3) loop motion including turns.
    /// Negative times/intervals allowed; absent root returns identity.
    pub fn root_motion_delta(
        &self,
        clip: usize,
        start_s: f64,
        end_s: f64,
        looping: bool,
    ) -> Result<RootDelta, Error> {
        let c = self.clips.get(clip).ok_or(Error::InvalidClip)?;
        check_time(c, start_s)?;
        check_time(c, end_s)?;
        match &c.root {
            None => Ok(RootDelta::default()),
            Some(root) => {
                let start = root_at(c, root, start_s, looping)?;
                let mut end = root_at(c, root, end_s, looping)?;
                if looping {
                    let first = RootDelta {
                        translation: root.translations[0],
                        rotation: root.rotations[0],
                    };
                    let last = relative(
                        first,
                        RootDelta {
                            translation: *root
                                .translations
                                .last()
                                .ok_or(Error::InvalidData("root"))?,
                            rotation: *root.rotations.last().ok_or(Error::InvalidData("root"))?,
                        },
                    );
                    let cycles = (end_s / c.loop_period_s()).floor() as i64
                        - (start_s / c.loop_period_s()).floor() as i64;
                    // Cancel completed cycles algebraically before multiplying,
                    // avoiding subtraction of huge accumulated f32 positions.
                    end = compose(power(last, cycles), end);
                }
                Ok(relative(start, end))
            }
        }
    }
    /// Events in (start,end], sorted by absolute time across multiple wraps.
    /// Query from a negative epsilon to include initial frame zero. Reversed or
    /// nonfinite intervals and >1,000,000 occurrences return errors.
    pub fn events_between(
        &self,
        clip: usize,
        start_s: f64,
        end_s: f64,
        looping: bool,
    ) -> Result<Vec<EventOccurrence<'_>>, Error> {
        let c = self.clips.get(clip).ok_or(Error::InvalidClip)?;
        check_time(c, start_s)?;
        check_time(c, end_s)?;
        if end_s < start_s {
            return Err(Error::InvalidTime);
        }
        let mut out = Vec::new();
        for event in &c.events {
            let offset = f64::from(event.frame) / f64::from(c.fps);
            if looping {
                let period = c.loop_period_s();
                let mut first = ((start_s - offset) / period).floor() as i64 + 1;
                let mut last = ((end_s - offset) / period).floor() as i64;
                let occurrence = |cycle: i64| cycle as f64 * period + offset;
                // Correct division rounding at exact fractional-fps boundaries.
                while occurrence(first - 1) > start_s {
                    first -= 1;
                }
                while occurrence(first) <= start_s {
                    first += 1;
                }
                while occurrence(last + 1) <= end_s {
                    last += 1;
                }
                while occurrence(last) > end_s {
                    last -= 1;
                }
                if last >= first && (last - first + 1) as usize > 1_000_000 - out.len() {
                    return Err(Error::TooManyEvents);
                }
                for cycle in first..=last {
                    let time_s = cycle as f64 * period + offset;
                    if time_s > start_s && time_s <= end_s {
                        out.push(EventOccurrence { event, time_s });
                    }
                }
            } else if offset > start_s && offset <= end_s {
                out.push(EventOccurrence {
                    event,
                    time_s: offset,
                });
            }
        }
        out.sort_by(|a, b| a.time_s.total_cmp(&b.time_s));
        Ok(out)
    }
}
fn check_time(c: &Clip, t: f64) -> Result<(), Error> {
    if !t.is_finite() || (t / c.loop_period_s()).abs() > 1_000_000_000. {
        Err(Error::InvalidTime)
    } else {
        Ok(())
    }
}
#[derive(Clone, Copy)]
struct Frame {
    a: usize,
    b: usize,
    alpha: f32,
}
fn frame_at(c: &Clip, time: f64, looping: bool) -> Result<Frame, Error> {
    check_time(c, time)?;
    let t = if looping {
        time.rem_euclid(c.loop_period_s())
    } else {
        time.clamp(0., c.duration_s())
    };
    let f = (t * f64::from(c.fps)).clamp(0., f64::from(c.frame_count - 1));
    let a = f.floor() as usize;
    Ok(Frame {
        a,
        b: (a + 1).min(c.frame_count as usize - 1),
        alpha: (f - a as f64) as f32,
    })
}
fn vec_at(v: &[[f32; 3]], f: Frame) -> [f32; 3] {
    if v.len() == 1 {
        v[0]
    } else {
        lerp(v[f.a], v[f.b], f.alpha)
    }
}
fn quat_at(v: &[[f32; 4]], f: Frame) -> [f32; 4] {
    if v.len() == 1 || f.alpha == 0. {
        v[if v.len() == 1 { 0 } else { f.a }]
    } else {
        slerp(v[f.a], v[f.b], f.alpha)
    }
}
fn apply_tracks(c: &Clip, f: Frame, out: &mut [Trs]) {
    for t in &c.tracks {
        let target = &mut out[t.bone];
        if !t.translations.is_empty() {
            let v = vec_at(&t.translations, f);
            target.translation = if t.additive {
                std::array::from_fn(|i| target.translation[i] + v[i] * t.weights[0])
            } else {
                v
            };
        }
        if !t.rotations.is_empty() {
            let q = quat_at(&t.rotations, f);
            target.rotation = if t.additive {
                normalize(mul(
                    target.rotation,
                    slerp([0., 0., 0., 1.], q, t.weights[1]),
                ))
            } else {
                q
            };
        }
        if !t.scales.is_empty() {
            let v = vec_at(&t.scales, f);
            target.scale = if t.additive {
                std::array::from_fn(|i| target.scale[i] * (1. + t.weights[2] * (v[i] - 1.)))
            } else {
                v
            };
        }
    }
    if let Some(root) = &c.root {
        out[root.bone].translation = root.translations[0];
        out[root.bone].rotation = root.rotations[0];
    }
}
fn lerp<const N: usize>(a: [f32; N], b: [f32; N], t: f32) -> [f32; N] {
    std::array::from_fn(|i| a[i] * (1. - t) + b[i] * t)
}
fn dot(a: [f32; 4], b: [f32; 4]) -> f32 {
    a.iter().zip(b).map(|(a, b)| a * b).sum()
}
fn normalize(q: [f32; 4]) -> [f32; 4] {
    let n = dot(q, q).sqrt();
    q.map(|v| v / n)
}
fn slerp(a: [f32; 4], mut b: [f32; 4], t: f32) -> [f32; 4] {
    let mut d = dot(a, b);
    if d < 0. {
        b = b.map(|v| -v);
        d = -d;
    }
    if d > 0.9995 {
        return normalize(lerp(a, b, t));
    }
    let theta = d.clamp(-1., 1.).acos();
    let denom = theta.sin();
    let u = ((1. - t) * theta).sin() / denom;
    let v = (t * theta).sin() / denom;
    normalize(std::array::from_fn(|i| a[i] * u + b[i] * v))
}
fn mul(a: [f32; 4], b: [f32; 4]) -> [f32; 4] {
    let [x, y, z, w] = a;
    let [xx, yy, zz, ww] = b;
    [
        w * xx + x * ww + y * zz - z * yy,
        w * yy - x * zz + y * ww + z * xx,
        w * zz + x * yy - y * xx + z * ww,
        w * ww - x * xx - y * yy - z * zz,
    ]
}
fn rotate(q: [f32; 4], v: [f32; 3]) -> [f32; 3] {
    let r = mul(mul(q, [v[0], v[1], v[2], 0.]), [-q[0], -q[1], -q[2], q[3]]);
    [r[0], r[1], r[2]]
}
fn compose(a: RootDelta, b: RootDelta) -> RootDelta {
    let t = rotate(a.rotation, b.translation);
    RootDelta {
        translation: std::array::from_fn(|i| a.translation[i] + t[i]),
        rotation: normalize(mul(a.rotation, b.rotation)),
    }
}
fn inverse(a: RootDelta) -> RootDelta {
    let rotation = [
        -a.rotation[0],
        -a.rotation[1],
        -a.rotation[2],
        a.rotation[3],
    ];
    RootDelta {
        translation: rotate(rotation, a.translation.map(|v| -v)),
        rotation,
    }
}
fn relative(a: RootDelta, b: RootDelta) -> RootDelta {
    compose(inverse(a), b)
}
fn power(mut a: RootDelta, count: i64) -> RootDelta {
    if count < 0 {
        a = inverse(a);
    }
    let mut n = count.unsigned_abs();
    let mut r = RootDelta::default();
    while n > 0 {
        if n & 1 != 0 {
            r = compose(r, a);
        }
        a = compose(a, a);
        n >>= 1;
    }
    r
}
fn root_at(c: &Clip, root: &RootTrack, time: f64, looping: bool) -> Result<RootDelta, Error> {
    let first = RootDelta {
        translation: root.translations[0],
        rotation: root.rotations[0],
    };
    let f = frame_at(c, time, looping)?;
    let current = relative(
        first,
        RootDelta {
            translation: vec_at(&root.translations, f),
            rotation: quat_at(&root.rotations, f),
        },
    );
    Ok(current)
}
struct Reader<'a> {
    bytes: &'a [u8],
}
impl<'a> Reader<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { bytes }
    }
    fn take(&mut self, n: usize) -> Result<&'a [u8], Error> {
        if n > self.bytes.len() {
            return Err(Error::Truncated);
        }
        let (a, b) = self.bytes.split_at(n);
        self.bytes = b;
        Ok(a)
    }
    fn array<const N: usize>(&mut self) -> Result<[u8; N], Error> {
        self.take(N)?.try_into().map_err(|_| Error::Truncated)
    }
    fn u8(&mut self) -> Result<u8, Error> {
        Ok(self.array::<1>()?[0])
    }
    fn u16(&mut self) -> Result<u16, Error> {
        Ok(u16::from_le_bytes(self.array()?))
    }
    fn i16(&mut self) -> Result<i16, Error> {
        Ok(i16::from_le_bytes(self.array()?))
    }
    fn u32(&mut self) -> Result<u32, Error> {
        Ok(u32::from_le_bytes(self.array()?))
    }
    fn i32(&mut self) -> Result<i32, Error> {
        Ok(i32::from_le_bytes(self.array()?))
    }
    fn u64(&mut self) -> Result<u64, Error> {
        Ok(u64::from_le_bytes(self.array()?))
    }
    fn float(&mut self) -> Result<f32, Error> {
        let v = f32::from_le_bytes(self.array()?);
        if v.is_finite() {
            Ok(v)
        } else {
            Err(Error::InvalidData("nonfinite float"))
        }
    }
    fn vector<const N: usize>(&mut self) -> Result<[f32; N], Error> {
        let mut v = [0.; N];
        for f in &mut v {
            *f = self.float()?;
        }
        Ok(v)
    }
    fn unit_quat(&mut self) -> Result<[f32; 4], Error> {
        let q = self.vector()?;
        if (dot(q, q) - 1.).abs() > 0.001 {
            return Err(Error::InvalidData("quaternion norm"));
        }
        Ok(normalize(q))
    }
    fn string(&mut self) -> Result<String, Error> {
        let n = self.u16()? as usize;
        Ok(std::str::from_utf8(self.take(n)?)
            .map_err(|_| Error::InvalidData("UTF-8"))?
            .to_owned())
    }
    fn count(&mut self, frames: u32, width: usize) -> Result<usize, Error> {
        let n = self.u32()?;
        if n != 0 && n != 1 && n != frames {
            return Err(Error::InvalidData("channel count"));
        }
        if n as usize > self.bytes.len() / width {
            return Err(Error::Truncated);
        }
        Ok(n as usize)
    }
    fn vectors(&mut self, frames: u32) -> Result<Vec<[f32; 3]>, Error> {
        let n = self.count(frames, 12)?;
        (0..n).map(|_| self.vector()).collect()
    }
    fn quaternions(&mut self, frames: u32) -> Result<Vec<[f32; 4]>, Error> {
        let n = self.count(frames, 8)?;
        (0..n)
            .map(|_| {
                let mut q = [0.; 4];
                for v in &mut q {
                    let i = self.i16()?;
                    if i == i16::MIN {
                        return Err(Error::InvalidData("quantized quaternion"));
                    }
                    *v = f32::from(i) / 32767.;
                }
                if (dot(q, q) - 1.).abs() > 0.001 {
                    return Err(Error::InvalidData("quantized quaternion norm"));
                }
                Ok(normalize(q))
            })
            .collect()
    }
}
fn crc32(bytes: &[u8]) -> u32 {
    let mut c = !0_u32;
    for b in bytes {
        c ^= u32::from(*b);
        for _ in 0..8 {
            c = (c >> 1) ^ (0xedb8_8320 & 0_u32.wrapping_sub(c & 1));
        }
    }
    !c
}
#[cfg(test)]
mod tests;
