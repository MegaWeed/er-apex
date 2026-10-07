//! Octane's jump pad on the ground (plan-octane.md R4): Apex's world pad has 18 bones, 17 of them
//! the hand-held pad's (names, parents, binds relative to `def_c_base`; tools/apexpov/
//! bake_padworld.py checks), so the mod draws it with the hand-held mesh T020 put in model 998's LG
//! part, its carriers (group 3) posed by the world prop's own sequences instead of the toss:
//! `prop_octane_jump_pad_deploy` as it lands, then `_deploy_idle` looping, `_deploy_trans` (the
//! bounce) each time it launches someone. Data: `padworld.json` in the mod folder (inches, the Cast
//! rig's axes; poses t, r, s per bone and frame).

use std::collections::HashMap;
use std::path::Path;

use glam::{Quat, Vec3};
use serde::Deserialize;

use super::pack::Xf;

#[derive(Deserialize)]
struct FileBone {
    name: String,
    parent: i32,
}

#[derive(Deserialize)]
struct FileClip {
    fps: f32,
    frames: usize,
    #[serde(rename = "loop")]
    looping: bool,
    /// frames x bones x [t xyz, r xyzw, s xyz]
    poses: Vec<Vec<[f32; 10]>>,
}

#[derive(Deserialize)]
struct File {
    bones: Vec<FileBone>,
    clips: HashMap<String, FileClip>,
}

struct Clip {
    fps: f32,
    frames: usize,
    looping: bool,
    poses: Vec<Vec<[f32; 10]>>,
}

pub struct Rig {
    pub names: Vec<String>,
    parents: Vec<i32>,
    clips: HashMap<String, Clip>,
}

const DEPLOY: &str = "prop_octane_jump_pad_deploy";
const IDLE: &str = "prop_octane_jump_pad_deploy_idle";
const BOUNCE: &str = "prop_octane_jump_pad_deploy_trans";

pub fn load(path: &Path) -> Result<Rig, String> {
    let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let f: File = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    let n = f.bones.len();
    for (i, b) in f.bones.iter().enumerate() {
        if b.parent >= i as i32 {
            return Err(format!("bone {} after its parent", b.name));
        }
    }
    let mut clips = HashMap::new();
    for (name, c) in f.clips {
        if c.frames == 0 || c.poses.len() != c.frames || c.poses.iter().any(|f| f.len() != n) {
            return Err(format!("{name}: frames x bones differ"));
        }
        clips.insert(name, Clip { fps: c.fps, frames: c.frames, looping: c.looping, poses: c.poses });
    }
    for need in [DEPLOY, IDLE, BOUNCE] {
        if !clips.contains_key(need) {
            return Err(format!("no {need}"));
        }
    }
    Ok(Rig { names: f.bones.iter().map(|b| b.name.clone()).collect(), parents: f.bones.iter().map(|b| b.parent).collect(), clips })
}

/// A bone's world (rig space, inches) and its scale (in its own axes; only leaves scale here).
#[derive(Clone, Copy, Debug)]
pub struct Posed {
    pub xf: Xf,
    pub scale: Vec3,
}

impl Clip {
    /// Seconds from the first frame to the last (Source: the last frame at cycle 1).
    fn length(&self) -> f32 {
        (self.frames.max(2) - 1) as f32 / self.fps
    }

    fn local(&self, b: usize, t: f32) -> ([f32; 10], [f32; 10], f32) {
        let f = if self.looping { (t / self.length()).rem_euclid(1.0) } else { (t / self.length()).clamp(0.0, 1.0) } * (self.frames - 1) as f32;
        let i = (f as usize).min(self.frames - 1);
        let j = (i + 1).min(self.frames - 1);
        (self.poses[i][b], self.poses[j][b], f - i as f32)
    }
}

impl Rig {
    /// Which sequence, and how far in (seconds): the deploy as it lands, the bounce while one
    /// plays, else the idle loop (counted from the deploy's end).
    fn state(&self, age: f32, bounce: Option<f32>) -> (&Clip, f32) {
        let deploy = &self.clips[DEPLOY];
        let trans = &self.clips[BOUNCE];
        if let Some(b) = bounce.filter(|&b| b < trans.length()) {
            return (trans, b);
        }
        if age < deploy.length() {
            return (deploy, age);
        }
        (&self.clips[IDLE], age - deploy.length())
    }

    /// Every bone posed (rig space, from `jx_c_origin`).
    pub fn pose(&self, age: f32, bounce: Option<f32>) -> Vec<Posed> {
        let (clip, t) = self.state(age, bounce);
        let mut out: Vec<Posed> = Vec::with_capacity(self.names.len());
        for b in 0..self.names.len() {
            let (a, c, w) = clip.local(b, t);
            let lt = Vec3::new(a[0], a[1], a[2]).lerp(Vec3::new(c[0], c[1], c[2]), w);
            let lr = Quat::from_xyzw(a[3], a[4], a[5], a[6]).normalize().slerp(Quat::from_xyzw(c[3], c[4], c[5], c[6]).normalize(), w).normalize();
            let ls = Vec3::new(a[7], a[8], a[9]).lerp(Vec3::new(c[7], c[8], c[9]), w);
            out.push(match usize::try_from(self.parents[b]) {
                // a scaled parent would scale its children's offsets too; none of these has
                // scaled children (bake_padworld.py lists the scaled bones: leaves)
                Ok(p) => Posed { xf: out[p].xf.mul(Xf { t: lt * out[p].scale, r: lr }), scale: out[p].scale * ls },
                // the root: the sequences turn `jx_c_origin` +90° about x (the rig's y up to the
                // game world's z up); the caller's frame already has y up, so it stays put
                Err(_) => Posed { xf: Xf::IDENTITY, scale: Vec3::ONE },
            });
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rig() -> Option<Rig> {
        let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("apex-data/pov/octane_padworld/padworld.json");
        path.exists().then(|| load(&path).expect("padworld.json loads"))
    }

    /// The deploy opens the pads from 0.75 to full size; the idle is unscaled; the bounce follows a
    /// launch and is over after its second.
    #[test]
    fn deploy_idle_and_bounce() {
        let Some(r) = rig() else { return };
        let pad = r.names.iter().position(|n| n == "def_c_pad_1").unwrap();
        let start = r.pose(0.0, None)[pad].scale;
        let open = r.pose(0.7, None)[pad].scale;
        assert!((start.x - 0.75).abs() < 0.01 && (open.x - 1.0).abs() < 0.01, "{start} {open}");
        assert!(std::ptr::eq(r.state(5.0, None).0, &r.clips[IDLE]));
        assert!(std::ptr::eq(r.state(5.0, Some(0.2)).0, &r.clips[BOUNCE]));
        assert!(std::ptr::eq(r.state(5.0, Some(1.2)).0, &r.clips[IDLE]));
    }
}
