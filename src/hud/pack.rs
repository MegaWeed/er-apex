//! The Apex HUD pack (T009): `hud_pack.json` and the files next to it, exported from the player's
//! own Apex install by `python tools/apexhud/export_hud.py` (ini `hud_dir`, else the mod
//! folder's `hud\`). Names, colours, translations and images are local Apex data; positions are
//! the pack's recommended layout on a 1920×1080 canvas (marked 推断 in the pack).

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use serde_json::Value;

/// What the HUD needs from the pack.
pub struct Pack {
    /// Element id -> [x, y, w, h] on the 1920×1080 canvas.
    pub bounds: HashMap<String, [f32; 4]>,
    pub crosshair: Crosshair,
    pub hit_marker: HitMarker,
    /// Palette key -> RGBA (0..1), the "default" colour-vision variant.
    pub colors: HashMap<String, [f32; 4]>,
    /// R-301's name in the HUD language.
    pub weapon_name: String,
    /// Texture name -> PNG (the image's pixel area, "payload_image").
    pub images: Vec<(String, PathBuf)>,
    /// Every located image by its Apex path (`rui/...`) -> PNG ("payload_image").
    pub images_by_path: HashMap<String, PathBuf>,
    /// HUD strings beyond the names, by localization key (#FIRE_MODE_AUTO, ...), in the HUD language.
    pub strings: HashMap<String, String>,
    /// The legend's upgrade icons by Apex path, in the pack's order (T017 `legend_upgrades`; empty
    /// in packs from before it).
    pub upgrades: Vec<String>,
    /// The portrait's Apex path (the `health` element's image), for its framing.
    pub portrait: Option<String>,
    pub font: FontFiles,
}

/// The crosshair's geometry (1920×1080 px; measured on the user's R5R video but for the gap).
pub struct Crosshair {
    /// The ticks' directions, counterclockwise from +x with y up (90° is the top tick).
    pub angles_deg: Vec<f32>,
    pub tick_px: f32,
    pub thickness_px: f32,
    /// The dark outline round the ticks and the dot, their ends too.
    pub outline_px: f32,
    /// Half the dot's side (square) or its radius (a disc: packs from before the video).
    pub dot_px: f32,
    pub square_dot: bool,
    pub min_gap_px: f32,
}

/// The hit marker's four legs along the diagonals, from and to these distances off the centre.
pub struct HitMarker {
    pub inner_px: f32,
    pub outer_px: f32,
    pub thickness_px: f32,
    pub outline_px: f32,
}

pub struct FontFiles {
    /// The R8 signed-distance atlas (as PNG) and the code point tables (source.meta.json).
    pub atlas: PathBuf,
    pub meta: PathBuf,
    /// Font indices for text, for numbers and bold.
    pub body: u32,
    pub numeric: u32,
    pub bold: u32,
}

fn read(path: &Path) -> Result<Value, String> {
    let text = std::fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    serde_json::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))
}

fn f(v: &Value) -> Option<f32> {
    v.as_f64().map(|x| x as f32)
}

fn rect(v: &Value) -> Option<[f32; 4]> {
    let a = v.as_array()?;
    Some([f(a.first()?)?, f(a.get(1)?)?, f(a.get(2)?)?, f(a.get(3)?)?])
}

pub fn load(dir: &Path, language: &str) -> Result<Pack, String> {
    let pack = read(&dir.join("hud_pack.json"))?;
    let file = |key: &str| pack[key].as_str().map(|s| dir.join(s)).ok_or_else(|| format!("hud_pack.json: no {key}"));

    let mut bounds = HashMap::new();
    let mut images = Vec::new();
    let mut portrait = None;
    let mut crosshair = Crosshair {
        angles_deg: vec![90.0, 210.0, 330.0],
        tick_px: 22.0,
        thickness_px: 2.4,
        outline_px: 1.2,
        dot_px: 1.2,
        square_dot: true,
        min_gap_px: 5.0,
    };
    let mut hit_marker = HitMarker { inner_px: 24.0, outer_px: 40.0, thickness_px: 2.4, outline_px: 1.2 };
    for e in pack["elements"].as_array().into_iter().flatten() {
        let Some(id) = e["id"].as_str() else { continue };
        if let Some(b) = rect(&e["layout"]["bounds_px"]) {
            bounds.insert(id.to_string(), b);
        }
        for r in e["rendering"].as_array().into_iter().flatten() {
            if let Some(img) = r["payload_image"].as_str() {
                images.push((id.to_string(), dir.join(img)));
                if id == "health" {
                    portrait = r["asset"].as_str().map(str::to_string);
                }
            }
        }
        if id == "crosshair" {
            let g = &e["geometry"];
            if let Some(a) = g["tick_angles_degrees"].as_array() {
                crosshair.angles_deg = a.iter().filter_map(f).collect();
            }
            crosshair.tick_px = f(&g["tick_length_px"]).unwrap_or(crosshair.tick_px);
            crosshair.thickness_px = f(&g["thickness_px"]).unwrap_or(crosshair.thickness_px);
            crosshair.outline_px = f(&g["outline_px"]).unwrap_or(crosshair.outline_px);
            crosshair.dot_px = f(&g["center_dot_radius_px"]).unwrap_or(crosshair.dot_px);
            crosshair.square_dot = g["center_dot_shape"].as_str() == Some("square");
            crosshair.min_gap_px = f(&g["minimum_gap_px"]).unwrap_or(crosshair.min_gap_px);
        }
        if id == "hit_marker" {
            let g = &e["geometry"];
            hit_marker.inner_px = f(&g["inner_radius_px"]).unwrap_or(hit_marker.inner_px);
            hit_marker.outer_px = f(&g["outer_radius_px"]).unwrap_or(hit_marker.outer_px);
            hit_marker.thickness_px = f(&g["thickness_px"]).unwrap_or(hit_marker.thickness_px);
            hit_marker.outline_px = f(&g["outline_px"]).unwrap_or(hit_marker.outline_px);
        }
    }
    // the legend's ability icons (`tactical`, `ultimate`, `passive`), by their element names
    for e in pack["optional_elements"].as_array().into_iter().flatten() {
        let (Some(id), Some(img)) = (e["id"].as_str(), e["image"]["payload_image"].as_str()) else {
            continue;
        };
        images.push((id.to_string(), dir.join(img)));
    }

    let upgrades = pack["legend_upgrades"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|u| u["asset"].as_str().map(str::to_string))
        .collect();

    let palette = read(&file("palette")?)?;
    let mut colors = HashMap::new();
    for (key, row) in palette["colors"].as_object().into_iter().flatten() {
        if let Some(c) = row["variants"]["default"].as_array() {
            let c: Vec<f32> = c.iter().filter_map(f).collect();
            if c.len() >= 3 {
                colors.insert(key.clone(), [c[0] / 255.0, c[1] / 255.0, c[2] / 255.0, 1.0]);
            }
        }
    }

    let loc = read(&file("localization")?)?;
    let text = |key: &str, fallback: &str| {
        let v = &loc[key]["values"];
        v[language].as_str().or_else(|| v["english"].as_str()).unwrap_or(fallback).to_string()
    };
    let weapon_key = pack["elements"].as_array().into_iter().flatten().find(|e| e["id"] == "weapon_slot").and_then(|e| e["localization_key"].as_str()).unwrap_or("#WPN_RSPN101");
    let weapon_name = text(weapon_key, "R-301");
    let mut strings: HashMap<String, String> = loc.as_object().into_iter().flatten().map(|(key, _)| (key.clone(), text(key, ""))).collect();
    // strings beyond the T009/T017 pack (tools/apexhud/export_extra.py: the reload hint, the
    // knock-down message); optional
    if let Ok(extra) = read(&dir.join("extra_localization.json")) {
        for (key, row) in extra.as_object().into_iter().flatten() {
            let v = &row["values"];
            if let Some(s) = v[language].as_str().or_else(|| v["english"].as_str()) {
                strings.insert(key.clone(), s.to_string());
            }
        }
    }
    let mut images_by_path: HashMap<String, PathBuf> = pack["images"]
        .as_object()
        .into_iter()
        .flatten()
        .filter_map(|(name, img)| img["payload_image"].as_str().map(|p| (name.clone(), dir.join(p))))
        .collect();
    // HUD v3: images named by R5Reloaded's scripts, exported from the local ui.rpak
    // (tools/apexhud/export_extra.py); optional
    if let Ok(extra) = read(&dir.join("extra_images.json")) {
        for (name, img) in extra.as_object().into_iter().flatten() {
            if let Some(p) = img["payload_image"].as_str() {
                images_by_path.insert(name.clone(), dir.join(p));
            }
        }
    }

    let choice = &pack["font_choice"];
    let guid = choice["guid"].as_str().ok_or("hud_pack.json: no font_choice.guid")?;
    let catalog = read(&file("font_catalog")?)?;
    let font = catalog["fonts"].as_array().into_iter().flatten().find(|x| x["guid"] == guid).ok_or_else(|| format!("font {guid} not in the catalog"))?;
    let font = FontFiles {
        atlas: dir.join(font["atlas_png"].as_str().ok_or("font: no atlas_png")?),
        meta: dir.join(font["metadata"].as_str().ok_or("font: no metadata")?),
        body: choice["font_index"].as_u64().unwrap_or(11) as u32,
        numeric: choice["numeric_font_index"].as_u64().unwrap_or(22) as u32,
        bold: choice["bold_font_index"].as_u64().unwrap_or(19) as u32,
    };
    Ok(Pack { bounds, crosshair, hit_marker, colors, weapon_name, images, images_by_path, strings, upgrades, portrait, font })
}

/// The pack folder: ini `hud_dir`, else `<mod>\hud`.
pub fn dir() -> PathBuf {
    crate::paths::config("hud_dir").filter(|d| !d.is_empty()).map(PathBuf::from).unwrap_or_else(|| crate::paths::file("hud"))
}
