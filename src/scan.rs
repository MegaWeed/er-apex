//! Byte-pattern search in the game's code (the first .text section of eldenring.exe in memory).
//! Patterns are `Option<u8>` per byte, `None` matching anything.

use windows::Win32::System::LibraryLoader::GetModuleHandleW;

/// The game executable's base address.
pub fn base() -> usize {
    unsafe { GetModuleHandleW(None) }.map(|m| m.0 as usize).unwrap_or(0)
}

/// (start, length) of the first section named `name`.
fn section(name: &[u8]) -> Option<(usize, usize)> {
    let base = base();
    if base == 0 {
        return None;
    }
    let u16_at = |a: usize| unsafe { (a as *const u16).read_unaligned() } as usize;
    let u32_at = |a: usize| unsafe { (a as *const u32).read_unaligned() } as usize;
    let nt = base + u32_at(base + 0x3C);
    let count = u16_at(nt + 6);
    let first = nt + 0x18 + u16_at(nt + 0x14);
    (0..count).map(|i| first + i * 40).find_map(|s| {
        let raw = unsafe { std::slice::from_raw_parts(s as *const u8, 8) };
        let n = raw.split(|&b| b == 0).next().unwrap_or(raw);
        (n == name).then(|| (base + u32_at(s + 12), u32_at(s + 8)))
    })
}

/// The first match of `pat` in the game's .text, if any.
pub fn text(pat: &[Option<u8>]) -> Option<usize> {
    let (start, len) = section(b".text")?;
    let code = unsafe { std::slice::from_raw_parts(start as *const u8, len) };
    find(code, pat).map(|i| start + i)
}

/// Fail closed for native function calls if a signature is absent or ambiguous.
pub fn unique_text(pat: &[Option<u8>]) -> Option<usize> {
    let (start, len) = section(b".text")?;
    let code = unsafe { std::slice::from_raw_parts(start as *const u8, len) };
    let first = find(code, pat)?;
    if find(&code[first + 1..], pat).is_some() { return None; }
    Some(start + first)
}

fn find(hay: &[u8], pat: &[Option<u8>]) -> Option<usize> {
    let first = pat.iter().position(Option::is_some)?;
    let anchor = pat[first]?;
    let last = hay.len().checked_sub(pat.len())?;
    let mut i = 0;
    while i <= last {
        // jump to the next occurrence of the first fixed byte
        let Some(k) = hay[i + first..=last + first].iter().position(|&b| b == anchor) else { return None };
        i += k;
        if pat.iter().enumerate().all(|(j, p)| p.is_none_or(|b| hay[i + j] == b)) {
            return Some(i);
        }
        i += 1;
    }
    None
}

#[cfg(test)]
mod tests {
    use super::find;

    #[test]
    fn wildcards() {
        let hay = [0u8, 0xC3, 1, 2, 0x57, 0xC3, 9, 9, 0x57];
        assert_eq!(find(&hay, &[Some(0xC3), None, None, Some(0x57)]), Some(1));
        assert_eq!(find(&hay, &[Some(0xC3), Some(9), None, Some(0x57)]), Some(5));
        assert_eq!(find(&hay, &[Some(0xC3), Some(7)]), None);
    }
}
