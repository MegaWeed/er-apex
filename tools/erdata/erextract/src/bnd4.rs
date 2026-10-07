// Adapted from deltarooo/er-mario; Copyright (c) 2026 Delta, MIT (see LICENSE).
//! BND4 binders (Elden Ring layout: 0x24-byte entries with ids and UTF-16 names, name hash table).

pub struct File {
    pub id: i32,
    pub name: String,
    pub compressed: bool,
    pub data: Vec<u8>,
}

fn i32_at(d: &[u8], o: usize) -> Option<i32> {
    Some(i32::from_le_bytes(d.get(o..o + 4)?.try_into().ok()?))
}

fn i64_at(d: &[u8], o: usize) -> Option<i64> {
    Some(i64::from_le_bytes(d.get(o..o + 8)?.try_into().ok()?))
}

pub fn wstr(d: &[u8], o: usize) -> Option<String> {
    let mut e = o;
    while d.get(e..e + 2)? != [0, 0] {
        e += 2;
    }
    let units: Vec<u16> = d[o..e]
        .chunks_exact(2)
        .map(|c| u16::from_le_bytes([c[0], c[1]]))
        .collect();
    Some(String::from_utf16_lossy(&units))
}

pub fn read(d: &[u8]) -> Result<Vec<File>, String> {
    let bad = || "damaged binder".to_string();
    if !d.starts_with(b"BND4") {
        return Err("not a BND4 binder".into());
    }
    if d.len() < 0x40 {
        return Err(bad());
    }
    if d[9] != 0 {
        return Err("big-endian BND4 is not supported".into());
    }
    let count = usize::try_from(i32_at(d, 0x0C).ok_or_else(bad)?).map_err(|_| bad())?;
    if count > (d.len() - 0x40) / 16 {
        return Err(bad());
    }
    let unicode = d.get(0x30) == Some(&1);
    // Elden Ring stores the format byte bit-reversed
    let reverse_bits = d[0x0a] != 0;
    let raw_fmt = *d.get(0x31).ok_or_else(bad)?;
    let fmt = if reverse_bits {
        raw_fmt.reverse_bits()
    } else {
        raw_fmt
    };
    let (has_ids, has_names) = (fmt & 0x02 != 0, fmt & 0x0C != 0);
    let (long_offsets, compressed) = (fmt & 0x10 != 0, fmt & 0x20 != 0);
    if !unicode && has_names {
        return Err("binder names are not UTF-16".into());
    }
    let mut p = 0x40;
    let mut files = Vec::with_capacity(count);
    for _ in 0..count {
        let raw_flags = *d.get(p).ok_or_else(bad)?;
        let flags = if reverse_bits {
            raw_flags.reverse_bits()
        } else {
            raw_flags
        };
        p += 8;
        let size = usize::try_from(i64_at(d, p).ok_or_else(bad)?).map_err(|_| bad())?;
        p += 8;
        if compressed {
            p += 8;
        }
        let offset = if long_offsets {
            p += 8;
            usize::try_from(i64_at(d, p - 8).ok_or_else(bad)?).map_err(|_| bad())?
        } else {
            p += 4;
            i32_at(d, p - 4).ok_or_else(bad)? as u32 as usize
        };
        let mut id = -1;
        if has_ids {
            id = i32_at(d, p).ok_or_else(bad)?;
            p += 4;
        }
        let mut name = String::new();
        if has_names {
            name = wstr(d, i32_at(d, p).ok_or_else(bad)? as usize).ok_or_else(bad)?;
            p += 4;
        }
        let data = d
            .get(offset..offset.checked_add(size).ok_or_else(bad)?)
            .ok_or_else(bad)?
            .to_vec();
        files.push(File {
            id,
            name,
            compressed: flags & 1 != 0,
            data,
        });
    }
    Ok(files)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn corrupt_binder_count_is_rejected() {
        let mut b = vec![0u8; 64];
        b[..4].copy_from_slice(b"BND4");
        b[12..16].copy_from_slice(&i32::MAX.to_le_bytes());
        assert!(read(&b).is_err());
        assert!(read(b"BND4").is_err());
    }
}
