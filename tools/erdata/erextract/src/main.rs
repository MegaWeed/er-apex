mod archive;
mod bnd4;
mod dcx;
use clap::{Parser, Subcommand};
use std::path::{Path, PathBuf};
#[derive(Parser)]
#[command(about = "Offline Elden Ring archive extractor")]
struct Cli {
    #[arg(
        long,
        global = true,
        env = "ELDEN_RING_DIR",
        default_value = "E:\\SteamLibrary\\steamapps\\common\\ELDEN RING\\Game"
    )]
    game_dir: PathBuf,
    #[arg(long, global = true)]
    dictionary: Option<PathBuf>,
    #[command(subcommand)]
    command: Command,
}
#[derive(Subcommand)]
enum Command {
    Hash {
        path: String,
    },
    List {
        #[arg(long)]
        filter: Option<String>,
    },
    Get {
        #[arg(required = true)]
        paths: Vec<String>,
        #[arg(long)]
        out: PathBuf,
        #[arg(long)]
        dcx: bool,
        #[arg(long)]
        unbnd: bool,
    },
    /// Read a local BND4/DCX, including generated mod packages, without opening game archives.
    Unpack {
        file: PathBuf,
        #[arg(long)]
        out: PathBuf,
        #[arg(long)]
        filter: Option<String>,
    },
}
fn safe_relative(name: &str) -> Result<PathBuf, String> {
    let normalized = name.replace('\\', "/");
    let mut result = PathBuf::new();
    for (i, component) in normalized.split('/').filter(|s| !s.is_empty()).enumerate() {
        if component == "." || component == ".." {
            return Err(format!("unsafe output path: {name}"));
        }
        let component = if i == 0 && component.len() == 2 && component.ends_with(':') {
            &component[..1]
        } else {
            component
        };
        if component.contains(':') || component.ends_with(['.', ' ']) {
            return Err(format!("unsafe output path: {name}"));
        }
        result.push(component);
    }
    if result.as_os_str().is_empty() {
        return Err("empty output path".into());
    }
    Ok(result)
}
fn write(root: &Path, relative: &Path, bytes: &[u8]) -> Result<(), String> {
    let target = root.join(relative);
    let mut check = root.to_path_buf();
    for part in relative.components() {
        check.push(part);
        if let Ok(meta) = std::fs::symlink_metadata(&check) {
            if meta.file_type().is_symlink() {
                return Err(format!("output path is a link: {}", check.display()));
            }
        }
    }
    std::fs::create_dir_all(target.parent().unwrap()).map_err(|e| e.to_string())?;
    std::fs::write(&target, bytes).map_err(|e| e.to_string())?;
    eprintln!("{} ({} bytes)", target.display(), bytes.len());
    Ok(())
}
fn wildcard(pattern: &[u8], text: &[u8]) -> bool {
    let mut row = vec![false; text.len() + 1];
    row[0] = true;
    for &p in pattern {
        let mut next = vec![false; text.len() + 1];
        if p == b'*' {
            next[0] = row[0];
        }
        for j in 1..=text.len() {
            next[j] = if p == b'*' {
                row[j] || next[j - 1]
            } else {
                row[j - 1] && (p == b'?' || p == text[j - 1])
            };
        }
        row = next;
    }
    row[text.len()]
}
fn run(cli: Cli) -> Result<(), String> {
    if let Command::Hash { path } = &cli.command {
        println!("0x{:016x}", archive::path_hash(path));
        return Ok(());
    }
    if let Command::Unpack { file, out, filter } = &cli.command {
        let raw = std::fs::read(file).map_err(|e| format!("{}: {e}", file.display()))?;
        let data = if raw.starts_with(b"DCX\0") {
            dcx::decompress(&raw, &cli.game_dir)?
        } else {
            raw
        };
        let files = bnd4::read(&data)?;
        let mut outputs = Vec::new();
        let mut seen = std::collections::HashSet::new();
        let total = files.len();
        for entry in files {
            if let Some(pattern) = filter {
                if !entry.name.to_lowercase().contains(&pattern.to_lowercase()) {
                    continue;
                }
            }
            let relative = safe_relative(&entry.name)?;
            if !seen.insert(relative.to_string_lossy().to_lowercase()) {
                return Err("duplicate binder output name".into());
            }
            let bytes = if entry.compressed {
                if !entry.data.starts_with(b"DCX\0") {
                    return Err(format!(
                        "unsupported compressed binder entry {} (expected DCX KRAK)",
                        entry.name
                    ));
                }
                dcx::decompress(&entry.data, &cli.game_dir)?
            } else {
                entry.data
            };
            outputs.push((relative, bytes));
        }
        println!(
            "Read {} local BND4 entries; unpacking {}",
            total,
            outputs.len()
        );
        for (relative, bytes) in outputs {
            write(out, &relative, &bytes)?;
        }
        return Ok(());
    }
    let archives = archive::Archives::open(&cli.game_dir)?;
    match cli.command {
        Command::List { filter } => {
            let dict = cli.dictionary.unwrap_or_else(|| {
                PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .join("../../third_party/UXM-Selective-Unpack/UXM/res/EldenRingDictionary.txt")
            });
            let names =
                std::fs::read_to_string(&dict).map_err(|e| format!("{}: {e}", dict.display()))?;
            let filter = filter.map(|s| s.to_lowercase());

            println!("path\tarchive\tsize");
            let mut seen = std::collections::HashSet::new();
            for name in names.lines().map(str::trim).filter(|s| s.starts_with('/')) {
                let lower = name.to_lowercase();
                if !seen.insert(lower.clone()) {
                    continue;
                }
                if let Some(f) = &filter {
                    if !(if f.contains(['*', '?']) {
                        wildcard(f.as_bytes(), lower.as_bytes())
                    } else {
                        lower.contains(f)
                    }) {
                        continue;
                    }
                }
                if let Some((bdt, size)) = archives.info(name) {
                    println!(
                        "{name}\t{}\t{size}",
                        bdt.file_name().unwrap().to_string_lossy()
                    );
                }
            }
        }
        Command::Get {
            paths,
            out,
            dcx: decompress,
            unbnd,
        } => {
            for path in paths {
                let raw = archives.read(&path)?;
                let data = if decompress || unbnd {
                    dcx::decompress(&raw, &cli.game_dir)?
                } else {
                    raw
                };
                let name = if (decompress || unbnd) && path.ends_with(".dcx") {
                    &path[..path.len() - 4]
                } else {
                    &path
                };
                let relative = safe_relative(name)?;
                if unbnd {
                    let files = bnd4::read(&data)?;
                    let mut outputs = Vec::new();
                    let mut seen = std::collections::HashSet::new();
                    for file in files {
                        eprintln!("binder entry {}: {}", file.id, file.name);
                        let rel = relative.join(safe_relative(&file.name)?);
                        if !seen.insert(rel.to_string_lossy().to_lowercase()) {
                            return Err("duplicate binder output name".into());
                        }
                        let bytes = if file.compressed {
                            if !file.data.starts_with(b"DCX\0") {
                                return Err(format!(
                                    "unsupported compressed binder entry {} (expected DCX KRAK)",
                                    file.name
                                ));
                            }
                            dcx::decompress(&file.data, &cli.game_dir)?
                        } else {
                            file.data
                        };
                        outputs.push((rel, bytes));
                    }
                    for (rel, bytes) in outputs {
                        write(&out, &rel, &bytes)?;
                    }
                } else {
                    write(&out, &relative, &data)?;
                }
            }
        }
        Command::Hash { .. } | Command::Unpack { .. } => unreachable!(),
    }
    Ok(())
}
fn main() {
    if let Err(err) = run(Cli::parse()) {
        eprintln!("erextract: {err}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn traversal_and_ads_are_rejected() {
        for path in ["../x", "a/../../x", "a:x", "C:/../x", "x. "] {
            assert!(safe_relative(path).is_err(), "{path}");
        }
        assert_eq!(
            safe_relative("N:\\GR\\parts\\test.flver").unwrap(),
            PathBuf::from("N/GR/parts/test.flver")
        );
    }
    #[test]
    fn wildcard_matching() {
        assert!(wildcard(
            b"/parts/*128?.*",
            b"/parts/bd_m_1280.partsbnd.dcx"
        ));
        assert!(!wildcard(b"/parts/*128?", b"/parts/bd_m_1280.partsbnd.dcx"));
    }
}
