//! Textures for the Apex HUD: PNG files decoded on a thread of their own at start-up, uploaded on
//! the render thread's next frame (hudhook's `RenderContext::load_texture`, as er-mario's hud.rs
//! does), then looked up by name while drawing.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use hudhook::RenderContext;
use hudhook::imgui::TextureId;

use crate::log;

/// How a PNG becomes RGBA: as it is, or as a mask (grey level -> alpha, colour white) that the HUD
/// tints, for font atlases and single-channel icons; `Faint`: a shape kept in a weak alpha (the
/// empty attachment slots: up to about 7 %, RUI scales it), alpha stretched so the strongest
/// pixel is opaque, colour white.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Kind {
    Color,
    Mask,
    Faint,
}

struct Decoded {
    name: String,
    w: u32,
    h: u32,
    rgba: Vec<u8>,
}

/// Decoded, not uploaded yet.
static PENDING: Mutex<Vec<Decoded>> = Mutex::new(Vec::new());
/// Uploaded: name -> texture and size in pixels.
static READY: Mutex<Option<HashMap<String, (TextureId, [f32; 2])>>> = Mutex::new(None);

/// Decodes these files (name, path, kind) on a new thread; failures are logged and skipped.
pub fn load(files: Vec<(String, PathBuf, Kind)>) {
    std::thread::spawn(move || {
        let (mut ok, mut failed) = (0, 0);
        for (name, path, kind) in files {
            match decode(&path, kind) {
                Ok((w, h, rgba)) => {
                    PENDING.lock().unwrap_or_else(|e| e.into_inner()).push(Decoded { name, w, h, rgba });
                    ok += 1;
                }
                Err(e) => {
                    failed += 1;
                    if failed <= 10 {
                        log(format!("hud: {}: {e}", path.display()));
                    }
                }
            }
        }
        log(format!("hud: {ok} images decoded, {failed} failed"));
    });
}

/// PNG -> RGBA8 (any bit depth / colour type).
fn decode(path: &Path, kind: Kind) -> Result<(u32, u32, Vec<u8>), String> {
    let file = std::fs::File::open(path).map_err(|e| e.to_string())?;
    let mut decoder = png::Decoder::new(std::io::BufReader::new(file));
    decoder.set_transformations(png::Transformations::normalize_to_color8());
    let mut reader = decoder.read_info().map_err(|e| e.to_string())?;
    let mut buf = vec![0; reader.output_buffer_size()];
    let info = reader.next_frame(&mut buf).map_err(|e| e.to_string())?;
    let px = &buf[..info.buffer_size()];
    let n = (info.width * info.height) as usize;
    let mut rgba = Vec::with_capacity(n * 4);
    use png::ColorType::*;
    match (info.color_type, kind) {
        (Rgba, Kind::Color) => rgba.extend_from_slice(px),
        (Rgb, Kind::Color) => px.chunks_exact(3).for_each(|c| rgba.extend_from_slice(&[c[0], c[1], c[2], 255])),
        (Grayscale, Kind::Color) => px.iter().for_each(|&g| rgba.extend_from_slice(&[g, g, g, 255])),
        (GrayscaleAlpha, Kind::Color) => px.chunks_exact(2).for_each(|c| rgba.extend_from_slice(&[c[0], c[0], c[0], c[1]])),
        // masks: the grey level (or red channel, or existing alpha times grey) is the coverage
        (Grayscale, Kind::Mask) => px.iter().for_each(|&g| rgba.extend_from_slice(&[255, 255, 255, g])),
        (GrayscaleAlpha, Kind::Mask) => px.chunks_exact(2).for_each(|c| rgba.extend_from_slice(&[255, 255, 255, ((c[0] as u16 * c[1] as u16) / 255) as u8])),
        (Rgb, Kind::Mask) => px.chunks_exact(3).for_each(|c| rgba.extend_from_slice(&[255, 255, 255, c[0]])),
        (Rgba, Kind::Mask) => px.chunks_exact(4).for_each(|c| rgba.extend_from_slice(&[255, 255, 255, ((c[0] as u16 * c[3] as u16) / 255) as u8])),
        (Rgba, Kind::Faint) => {
            let max = px.chunks_exact(4).map(|c| c[3]).max().unwrap_or(0).max(1) as u32;
            px.chunks_exact(4).for_each(|c| rgba.extend_from_slice(&[255, 255, 255, (c[3] as u32 * 255 / max) as u8]));
        }
        (other, _) => return Err(format!("unexpected colour type {other:?}")),
    }
    if rgba.len() != n * 4 {
        return Err(format!("decoded {} bytes for {}x{}", rgba.len(), info.width, info.height));
    }
    Ok((info.width, info.height, rgba))
}

/// A texture made in code (RGBA8, `w` x `h`), uploaded with the next frame as a decoded PNG is.
pub fn generate(name: &str, w: u32, h: u32, rgba: Vec<u8>) {
    PENDING.lock().unwrap_or_else(|e| e.into_inner()).push(Decoded { name: name.into(), w, h, rgba });
}

/// Render thread, before each frame: upload what has been decoded since.
pub fn upload(render_context: &mut dyn RenderContext) {
    let pending: Vec<Decoded> = std::mem::take(&mut *PENDING.lock().unwrap_or_else(|e| e.into_inner()));
    if pending.is_empty() {
        return;
    }
    let mut ready = READY.lock().unwrap_or_else(|e| e.into_inner());
    let map = ready.get_or_insert_with(HashMap::new);
    let mut failed = 0;
    for d in pending {
        match render_context.load_texture(&d.rgba, d.w, d.h) {
            Ok(id) => {
                map.insert(d.name, (id, [d.w as f32, d.h as f32]));
            }
            Err(e) => {
                failed += 1;
                if failed <= 5 {
                    log(format!("hud: upload {} failed: {e:?}", d.name));
                }
            }
        }
    }
    log(format!("hud: {} textures ready ({failed} uploads failed)", map.len()));
}

/// A texture by name and its size in pixels.
pub fn get(name: &str) -> Option<(TextureId, [f32; 2])> {
    READY.lock().unwrap_or_else(|e| e.into_inner()).as_ref()?.get(name).copied()
}
