use er_apex_anim::{Pack, Trs};
use std::{
    error::Error,
    fs,
    io::{self, Read},
    time::Instant,
};
fn f32_read(r: &mut impl Read) -> io::Result<f32> {
    let mut b = [0; 4];
    r.read_exact(&mut b)?;
    Ok(f32::from_le_bytes(b))
}
fn angle(a: [f32; 4], b: [f32; 4]) -> f64 {
    let normalize = |q: [f32; 4]| {
        let n = q.iter().map(|v| f64::from(*v).powi(2)).sum::<f64>().sqrt();
        q.map(|v| f64::from(v) / n)
    };
    let a = normalize(a);
    let mut b = normalize(b);
    if a.iter().zip(b).map(|(x, y)| x * y).sum::<f64>() < 0. {
        b = b.map(|v| -v);
    }
    let minus = a
        .iter()
        .zip(b)
        .map(|(x, y)| (x - y).powi(2))
        .sum::<f64>()
        .sqrt();
    let plus = a
        .iter()
        .zip(b)
        .map(|(x, y)| (x + y).powi(2))
        .sum::<f64>()
        .sqrt();
    (4. * minus.atan2(plus)).to_degrees()
}
fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 4 {
        return Err("usage: validate PACK VALIDATION OUTPUT_JSON".into());
    }
    let started = Instant::now();
    let pack = Pack::parse(&fs::read(&args[1])?)?;
    let mut input: Box<dyn Read> = if args[2].ends_with(".json") {
        // Exporter fixture grammar consists solely of nested numeric arrays.
        // This scanner is intentionally confined to trusted validation fixtures,
        // not a general JSON parser and never used by Pack::parse.
        let json = fs::read_to_string(&args[2])?;
        let mut tokens = json
            .split(|c: char| c.is_whitespace() || matches!(c, '[' | ']' | ','))
            .filter(|t| !t.is_empty());
        let mut number = || -> Result<f64, Box<dyn Error>> {
            let n: f64 = tokens.next().ok_or("truncated numeric JSON")?.parse()?;
            if !n.is_finite() {
                return Err("nonfinite JSON value".into());
            }
            Ok(n)
        };
        if number()? != 1. {
            return Err("JSON fixture version".into());
        }
        let nb = number()?;
        let count = number()?;
        if nb != pack.bones().len() as f64
            || count < 0.
            || count.fract() != 0.
            || count > 1_000_000.
        {
            return Err("JSON fixture counts".into());
        }
        let mut bytes = b"FAVAL001".to_vec();
        bytes.extend((nb as u32).to_le_bytes());
        bytes.extend((count as u32).to_le_bytes());
        for _ in 0..count as usize {
            let clip = number()?;
            if clip < 0. || clip.fract() != 0. || clip >= pack.clips().len() as f64 {
                return Err("JSON clip index".into());
            }
            bytes.extend((clip as u32).to_le_bytes());
            bytes.extend(number()?.to_le_bytes());
            for _ in 0..nb as usize * 10 + 14 {
                bytes.extend((number()? as f32).to_le_bytes());
            }
        }
        if tokens.next().is_some() {
            return Err("trailing JSON fixture values".into());
        }
        Box::new(io::Cursor::new(bytes))
    } else {
        Box::new(io::BufReader::new(fs::File::open(&args[2])?))
    };
    let mut header = [0; 16];
    input.read_exact(&mut header)?;
    if &header[..8] != b"FAVAL001" {
        return Err("bad validation magic".into());
    }
    let bones = u32::from_le_bytes(header[8..12].try_into()?) as usize;
    let records = u32::from_le_bytes(header[12..16].try_into()?);
    if bones != pack.bones().len() {
        return Err("validation bone count".into());
    }
    let mut pose = vec![Trs::default(); bones];
    let (mut rotation, mut translation, mut scale) = (0_f64, 0_f64, 0_f64);
    let mut worst = String::new();
    let (mut root_rotation, mut root_translation) = (0_f64, 0_f64);
    for _ in 0..records {
        let mut h = [0; 12];
        input.read_exact(&mut h)?;
        let clip = u32::from_le_bytes(h[..4].try_into()?) as usize;
        let t = f64::from_le_bytes(h[4..].try_into()?);
        pack.sample(clip, t, false, &mut pose)?;
        for (i, p) in pose.iter().enumerate() {
            let mut expected = [0_f32; 10];
            for v in &mut expected {
                *v = f32_read(&mut input)?;
            }
            let a = angle(p.rotation, expected[3..7].try_into()?);
            if a > rotation {
                rotation = a;
                worst = format!(
                    "{} bone {} time {t}",
                    pack.clips()[clip].name,
                    pack.bones()[i].name
                );
            }
            translation = translation.max(
                p.translation
                    .iter()
                    .zip(&expected[..3])
                    .map(|(a, b)| (f64::from(*a) - f64::from(*b)).powi(2))
                    .sum::<f64>()
                    .sqrt(),
            );
            scale = scale.max(
                p.scale
                    .iter()
                    .zip(&expected[7..])
                    .map(|(a, b)| (f64::from(*a) - f64::from(*b)).abs())
                    .fold(0., f64::max),
            );
        }
        for looping in [false, true] {
            let mut expected = [0_f32; 7];
            for v in &mut expected {
                *v = f32_read(&mut input)?;
            }
            let end = if looping {
                pack.clips()[clip].loop_period_s() + t
            } else {
                t
            };
            let delta = pack.root_motion_delta(clip, 0., end, looping)?;
            root_rotation = root_rotation.max(angle(delta.rotation, expected[3..].try_into()?));
            root_translation = root_translation.max(
                delta
                    .translation
                    .iter()
                    .zip(&expected[..3])
                    .map(|(a, b)| (f64::from(*a) - f64::from(*b)).powi(2))
                    .sum::<f64>()
                    .sqrt(),
            );
        }
    }
    let mut tail = [0; 1];
    if input.read(&mut tail)? != 0 {
        return Err("trailing validation bytes".into());
    }
    let json = format!(
        "{{\n  \"status\": \"{}\",\n  \"poses\": {records},\n  \"bone_transforms\": {},\n  \"max_rotation_error_deg\": {rotation},\n  \"max_translation_error_inches\": {translation},\n  \"max_scale_error\": {scale},\n  \"elapsed_seconds\": {}\n}}\n",
        if rotation < 0.02
            && translation < 0.0001
            && scale < 0.0001
            && root_rotation < 0.02
            && root_translation < 0.05
        {
            "passed"
        } else {
            "failed"
        },
        u64::from(records) * bones as u64,
        started.elapsed().as_secs_f64()
    );
    let json = json.replace("\n}", &format!(",\n  \"max_root_rotation_error_deg\": {root_rotation},\n  \"max_root_translation_error_inches\": {root_translation}\n}}"));
    fs::write(&args[3], &json)?;
    println!("{json}worst rotation: {worst}");
    if rotation >= 0.02
        || translation >= 0.0001
        || scale >= 0.0001
        || root_rotation >= 0.02
        || root_translation >= 0.05
    {
        return Err("Cast/Rust disagreement".into());
    }
    Ok(())
}
