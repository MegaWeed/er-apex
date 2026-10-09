// Adapted from deltarooo/er-mario; Copyright (c) 2026 Delta, MIT (see LICENSE).
//! Reads vanilla files out of Elden Ring's archives (DataN.bhd/.bdt, DLC): each .bhd index is RSA
//! encrypted with a public key read from the player's executable, each file's sensitive ranges are AES-128
//! ECB encrypted with a key from the index. Paths are hashed (lowercase, "/" separated, x*0x85 + c).

use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

use aes::Aes128;
use aes::cipher::{BlockDecrypt, KeyInit, generic_array::GenericArray};
use base64::Engine;
use num_bigint::BigUint;

const ARCHIVES: [&str; 5] = ["Data0", "Data1", "Data2", "Data3", "DLC"];

struct RsaKey {
    n: BigUint,
    e: BigUint,
}

struct Entry {
    bdt: PathBuf,
    offset: u64,
    padded: usize,
    size: usize,
    aes: Option<([u8; 16], Vec<(i64, i64)>)>,
}

pub struct Archives {
    entries: std::collections::HashMap<u64, Entry>,
}

pub fn path_hash(path: &str) -> u64 {
    let mut p = path.to_lowercase().replace('\\', "/");
    if !p.starts_with('/') {
        p.insert(0, '/');
    }
    p.bytes()
        .fold(0u64, |h, c| h.wrapping_mul(0x85).wrapping_add(c as u64))
}

/// Scan the player's executable on disk; no process access and no embedded keys.
fn find_keys(dir: &Path) -> Result<Vec<RsaKey>, String> {
    const BEGIN: &[u8] = b"-----BEGIN RSA PUBLIC KEY-----";
    const END: &[u8] = b"-----END RSA PUBLIC KEY-----";
    let image = std::fs::read(dir.join("eldenring.exe")).map_err(|e| e.to_string())?;
    let mut keys = Vec::new();
    let mut at = 0;
    while let Some(i) = find(&image[at..], BEGIN) {
        let begin = at + i + BEGIN.len();
        let Some(j) = find(&image[begin..], END) else {
            break;
        };
        if let Some(key) = parse_pem(&String::from_utf8_lossy(&image[begin..begin + j])) {
            keys.push(key);
        }
        at = begin + j + END.len();
    }
    Ok(keys)
}

fn find(hay: &[u8], needle: &[u8]) -> Option<usize> {
    hay.windows(needle.len()).position(|w| w == needle)
}

/// PKCS#1 RSAPublicKey: SEQUENCE { INTEGER n, INTEGER e }.
fn parse_pem(body: &str) -> Option<RsaKey> {
    let b64: String = body.chars().filter(|c| !c.is_whitespace()).collect();
    let der = base64::engine::general_purpose::STANDARD.decode(b64).ok()?;
    let mut p = 0usize;
    let read_len = |der: &[u8], p: &mut usize| -> Option<usize> {
        let first = *der.get(*p)?;
        *p += 1;
        if first < 0x80 {
            return Some(first as usize);
        }
        let n = (first & 0x7F) as usize;
        let mut len = 0usize;
        for _ in 0..n {
            len = len << 8 | *der.get(*p)? as usize;
            *p += 1;
        }
        Some(len)
    };
    (der.get(p) == Some(&0x30)).then_some(())?;
    p += 1;
    read_len(&der, &mut p)?;
    let int = |der: &[u8], p: &mut usize| -> Option<BigUint> {
        (der.get(*p) == Some(&0x02)).then_some(())?;
        *p += 1;
        let len = read_len(der, p)?;
        let v = BigUint::from_bytes_be(der.get(*p..*p + len)?);
        *p += len;
        Some(v)
    };
    let n = int(&der, &mut p)?;
    let e = int(&der, &mut p)?;
    Some(RsaKey { n, e })
}

/// Raw RSA with the public key, block by block (the index was "encrypted" with the private key).
fn rsa_decrypt(key: &RsaKey, data: &[u8], only_first_block: bool) -> Vec<u8> {
    let k = (key.n.bits() as usize).div_ceil(8);
    let mut out = Vec::with_capacity(data.len());
    for block in data.chunks(k) {
        let m = BigUint::from_bytes_be(block)
            .modpow(&key.e, &key.n)
            .to_bytes_be();
        let width = k - 1;
        out.extend(std::iter::repeat_n(0u8, width.saturating_sub(m.len())));
        out.extend_from_slice(&m[m.len().saturating_sub(width)..]);
        if only_first_block {
            break;
        }
    }
    out
}

/// Decrypts in parallel (a few seconds for the big indexes).
fn rsa_decrypt_parallel(key: &RsaKey, data: &[u8]) -> Vec<u8> {
    let k = (key.n.bits() as usize).div_ceil(8);
    let blocks = data.len().div_ceil(k);
    let threads = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4)
        .clamp(1, 16);
    let per = blocks.div_ceil(threads);
    std::thread::scope(|s| {
        let handles: Vec<_> = (0..threads)
            .map(|t| {
                let lo = (t * per * k).min(data.len());
                let hi = ((t + 1) * per * k).min(data.len());
                s.spawn(move || rsa_decrypt(key, &data[lo..hi], false))
            })
            .collect();
        handles
            .into_iter()
            .flat_map(|h| h.join().unwrap_or_default())
            .collect()
    })
}

fn i32_at(d: &[u8], o: usize) -> Option<i32> {
    Some(i32::from_le_bytes(d.get(o..o + 4)?.try_into().ok()?))
}

fn i64_at(d: &[u8], o: usize) -> Option<i64> {
    Some(i64::from_le_bytes(d.get(o..o + 8)?.try_into().ok()?))
}

impl Archives {
    pub fn open(dir: &Path) -> Result<Self, String> {
        let keys = find_keys(dir)?;
        if keys.is_empty() {
            return Err("archive keys not found in eldenring.exe".into());
        }
        let mut entries = std::collections::HashMap::new();
        for name in ARCHIVES {
            let bhd = dir.join(format!("{name}.bhd"));
            // the DLC archive is only there when Shadow of the Erdtree is installed
            if name == "DLC" && !bhd.exists() {
                continue;
            }
            let data = std::fs::read(&bhd).map_err(|e| format!("{}: {e}", bhd.display()))?;
            let Some(key) = keys
                .iter()
                .find(|k| rsa_decrypt(k, &data, true).starts_with(b"BHD5"))
            else {
                return Err(format!("no key opens {name}.bhd"));
            };
            let index = rsa_decrypt_parallel(key, &data);
            Self::parse(&index, &dir.join(format!("{name}.bdt")), &mut entries)
                .ok_or(format!("{name}.bhd is damaged"))?;
        }
        eprintln!("{} archive entries", entries.len());
        if entries.is_empty() {
            return Err("no archives found in game directory".into());
        }
        Ok(Self { entries })
    }

    pub fn info(&self, path: &str) -> Option<(&Path, usize)> {
        self.entries
            .get(&path_hash(path))
            .map(|e| (e.bdt.as_path(), if e.size == 0 { e.padded } else { e.size }))
    }

    fn parse(
        d: &[u8],
        bdt: &Path,
        entries: &mut std::collections::HashMap<u64, Entry>,
    ) -> Option<()> {
        let (bucket_count, buckets) = (
            usize::try_from(i32_at(d, 16)?).ok()?,
            usize::try_from(i32_at(d, 20)?).ok()?,
        );
        d.get(buckets..buckets.checked_add(bucket_count.checked_mul(8)?)?)?;
        for b in 0..bucket_count {
            let (n, off) = (
                usize::try_from(i32_at(d, buckets + b * 8)?).ok()?,
                usize::try_from(i32_at(d, buckets + b * 8 + 4)?).ok()?,
            );
            d.get(off..off.checked_add(n.checked_mul(40)?)?)?;
            for i in 0..n {
                let e = off + i * 40;
                let hash = i64_at(d, e)? as u64;
                let (padded, size) = (
                    usize::try_from(i32_at(d, e + 8)?).ok()?,
                    usize::try_from(i32_at(d, e + 12)?).ok()?,
                );
                let (offset, aes_off) = (
                    u64::try_from(i64_at(d, e + 16)?).ok()?,
                    usize::try_from(i64_at(d, e + 32)?).ok()?,
                );
                if size > padded {
                    return None;
                }
                let aes = if aes_off != 0 {
                    let key: [u8; 16] = d.get(aes_off..aes_off + 16)?.try_into().ok()?;
                    let count = usize::try_from(i32_at(d, aes_off + 16)?).ok()?;
                    d.get(aes_off + 20..(aes_off + 20).checked_add(count.checked_mul(16)?)?)?;
                    let ranges = (0..count)
                        .map(|k| {
                            Some((
                                i64_at(d, aes_off + 20 + k * 16)?,
                                i64_at(d, aes_off + 28 + k * 16)?,
                            ))
                        })
                        .collect::<Option<Vec<_>>>()?;
                    Some((key, ranges))
                } else {
                    None
                };
                entries.insert(
                    hash,
                    Entry {
                        bdt: bdt.to_path_buf(),
                        offset,
                        padded,
                        size,
                        aes,
                    },
                );
            }
        }
        Some(())
    }

    /// The raw (usually DCX compressed) bytes of a game file, e.g. "/parts/bd_m_1280.partsbnd.dcx".
    pub fn read(&self, path: &str) -> Result<Vec<u8>, String> {
        let e = self
            .entries
            .get(&path_hash(path))
            .ok_or(format!("{path} not in the game archives"))?;
        let mut f =
            std::fs::File::open(&e.bdt).map_err(|err| format!("{}: {err}", e.bdt.display()))?;
        let length = f.metadata().map_err(|err| err.to_string())?.len();
        if e.offset
            .checked_add(e.padded as u64)
            .is_none_or(|end| end > length)
        {
            return Err("archive entry exceeds BDT length".into());
        }
        let mut data = vec![0u8; e.padded];
        f.seek(SeekFrom::Start(e.offset))
            .and_then(|_| f.read_exact(&mut data))
            .map_err(|err| format!("{path}: {err}"))?;
        if let Some((key, ranges)) = &e.aes {
            let cipher = Aes128::new(GenericArray::from_slice(key));
            for &(start, end) in ranges {
                if start < 0 || end <= start {
                    continue;
                }
                let (start, end) = (start as usize, end as usize);
                if end > data.len() || start > end || (end - start) % 16 != 0 {
                    return Err("invalid AES range".into());
                }
                for block in data[start..end].chunks_exact_mut(16) {
                    cipher.decrypt_block(GenericArray::from_mut_slice(block));
                }
            }
        }
        if e.size != 0 {
            data.truncate(e.size);
        }
        Ok(data)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn hash_normalization() {
        assert_eq!(
            path_hash("PARTS\\BD_M_1280.partsbnd.dcx"),
            path_hash("/parts/bd_m_1280.partsbnd.dcx")
        );
        assert_eq!(path_hash("a"), 47 * 133 + 97);
    }
    #[test]
    fn malformed_bucket_count_is_rejected() {
        let mut index = vec![0u8; 24];
        index[16..20].copy_from_slice(&(-1i32).to_le_bytes());
        assert!(
            Archives::parse(
                &index,
                Path::new("unused.bdt"),
                &mut std::collections::HashMap::new()
            )
            .is_none()
        );
    }
}
