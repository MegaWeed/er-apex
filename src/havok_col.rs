//! Elden Ring's own collision as triangles: reads the live Havok (hknp) world and decodes the
//! static bodies' shapes near a point (compressed meshes, convex shapes, compounds), for the
//! movement controller (spike S5, deps/er-apex-move).
//!
//! Adapted from er-mario's havok_col.rs (MIT, Copyright (c) 2026 Delta): the layout and the
//! decoders are its; this copy drops what only Mario needed (fog-gate thickening, props, debug
//! probes) and takes the query window as a parameter.
//!
//! Layout (er-mario, found with its explorer):
//!   CSHavokMan+0x98 -> CSPhysWorld, +0x8 -> hknpWorld
//!   hknpWorld+0x28 bodies (0xb0 each, count at +0x30)
//!   body +0x30 translation, +0x60 shape, +0x6c collision layer/filter, +0x80 rotation quat (xyzw)
//!   fsnpCustomParamCompressedMeshShape +0x48 -> hknpCompressedMeshShapeData:
//!     +0x30 domain min, +0x40 domain max, +0x60 sections (0x60 each), +0x70 primitives (u8 x4),
//!     +0x80 shared index (u16), +0x90 packed vertices (u32 11/11/10), +0xa0 shared vertices (u64 21/21/22)
//!   section +0x30 offset, +0x3c scale, +0x48 first packed, +0x4c shared start, +0x50 prim start,
//!           +0x58 byte0 = packed count, byte1 = primitive count

use std::collections::HashMap;
use std::sync::Arc;

use eldenring::cs::CSHavokMan;
use fromsoftware_shared::FromStatic;
use glam::{Quat, Vec3};

use crate::explore::{class_of, read_u64, readable};
use crate::log;

const CELL: f32 = 4.0; // metres, per-shape bucket size

/// The part of the world a query returns: a box `radius` wide (horizontally) from `down` below to
/// `up` above the centre, plus a narrow `column` reaching `below` down (the ground under a fall).
#[derive(Clone, Copy, Debug)]
pub struct Window {
    pub radius: f32,
    pub down: f32,
    pub up: f32,
    pub column: f32,
    pub below: f32,
    pub max_tris: usize,
}

pub type Tri = [Vec3; 3];

/// A decoded mesh in shape-local space, bucketed into cells for quick queries.
pub struct Mesh {
    tris: Vec<Tri>,
    cells: HashMap<(i32, i32, i32), Vec<u32>>,
    radius: f32,
}

impl Mesh {
    fn new(tris: Vec<Tri>) -> Self {
        let mut cells: HashMap<(i32, i32, i32), Vec<u32>> = HashMap::new();
        let mut radius: f32 = 0.0;
        for (i, t) in tris.iter().enumerate() {
            if !t.iter().all(|v| v.is_finite() && v.abs().max_element() < 20_000.0) {
                continue;
            }
            let lo = t[0].min(t[1]).min(t[2]);
            let hi = t[0].max(t[1]).max(t[2]);
            radius = radius.max(lo.length()).max(hi.length());
            let c = |v: f32| (v / CELL).floor() as i32;
            let span = (c(hi.x) - c(lo.x) + 1) as i64 * (c(hi.y) - c(lo.y) + 1) as i64 * (c(hi.z) - c(lo.z) + 1) as i64;
            if span > 50_000 {
                continue; // absurdly large triangle: skip rather than flood the grid
            }
            for x in c(lo.x)..=c(hi.x) {
                for y in c(lo.y)..=c(hi.y) {
                    for z in c(lo.z)..=c(hi.z) {
                        cells.entry((x, y, z)).or_default().push(i as u32);
                    }
                }
            }
        }
        Self { tris, cells, radius }
    }
}

#[derive(Default)]
pub struct HavokCollision {
    /// shape address -> (mesh data address, primitive count, decoded mesh)
    meshes: HashMap<usize, (usize, u32, Option<Arc<Mesh>>)>,
    /// convex shapes (boxes, hulls, cylinders): shape address -> (vtable, decoded hull)
    convex: HashMap<usize, (usize, Option<Arc<Mesh>>)>,
    pub layers: Vec<u32>,
    /// bodies left out of queries
    pub exclude: std::collections::HashSet<u32>,
    bodies: usize,
    body_count: usize,
    logged_layers: bool,
    /// shapes collided as a box (custom-piece meshes): the game's rays pass their gaps, so they
    /// can't confirm them
    pub boxed: std::collections::HashSet<usize>,
    /// bodies skipped for not being in the physics world (diagnostics)
    pub not_in_world: u32,
    queries: u32,
    /// compressed meshes being decoded off the game thread: shape -> (mesh data, primitive
    /// count, result)
    decoding: HashMap<usize, (usize, u32, std::sync::mpsc::Receiver<Option<Arc<Mesh>>>)>,
}

fn u32_at(a: usize) -> u32 {
    unsafe { *(a as *const u32) }
}

fn f32_at(a: usize) -> f32 {
    unsafe { *(a as *const f32) }
}

fn vec3_at(a: usize) -> Vec3 {
    Vec3::new(f32_at(a), f32_at(a + 4), f32_at(a + 8))
}

fn u16_at(a: usize) -> u16 {
    unsafe { *(a as *const u16) }
}

/// Decodes a hknp convex shape (hknpBoxShape / hknpConvexPolytopeShape / hknpCylinderShape) into
/// shape-local triangles. Layout: hkRelArray {u16 count, u16 offset from the field} for vertices at
/// +0x3a (vec4, index in w), faces at +0x44 ({u16 first index, u8 count, u8}), u8 indices at +0x48.
fn decode_convex(shape: usize) -> Option<Vec<Tri>> {
    if !readable(shape, 0x50) {
        return None;
    }
    let rel = |field: usize| (shape + field + u16_at(shape + field + 2) as usize, u16_at(shape + field) as usize);
    let (verts, nv) = rel(0x3a);
    let (faces, nf) = rel(0x44);
    let (idx, ni) = rel(0x48);
    if nv == 0 || nv > 1024 || nf == 0 || nf > 1024 || ni > 8192 {
        return None;
    }
    if !readable(verts, nv * 16) || !readable(faces, nf * 4) || !readable(idx, ni) {
        return None;
    }
    let v: Vec<Vec3> = (0..nv).map(|i| vec3_at(verts + i * 16)).collect();
    if !v.iter().all(|p| p.is_finite() && p.abs().max_element() < 1000.0) {
        return None;
    }
    let mut tris = Vec::new();
    for f in 0..nf {
        let first = u16_at(faces + f * 4) as usize;
        let count = unsafe { *((faces + f * 4 + 2) as *const u8) } as usize;
        if count < 3 || first + count > ni {
            continue;
        }
        let at = |k: usize| unsafe { *((idx + first + k) as *const u8) } as usize;
        for k in 1..count - 1 {
            let (a, b, c) = (at(0), at(k), at(k + 1));
            if a < nv && b < nv && c < nv {
                tris.push([v[a], v[b], v[c]]);
            }
        }
    }
    Some(tris)
}

/// A compressed mesh made only of custom (convex piece) primitives, like the portcullis gates:
/// its pieces aren't plain triangles, so it becomes the box of its domain, if that box is thin
/// (gates, grilles, fences). Shape-local triangles; None for anything else.
fn custom_pieces_box(md: usize) -> Option<Vec<Tri>> {
    if !readable(md, 0xb0) {
        return None;
    }
    let prims = read_u64(md + 0x70)? as usize;
    let n = u32_at(md + 0x78) as usize;
    if n == 0 || n > 100_000 || !readable(prims, n * 4) {
        return None;
    }
    // (a primitive whose first two indices match is a custom one)
    let all_custom = (0..n).all(|k| unsafe { *((prims + k * 4) as *const u8) == *((prims + k * 4 + 1) as *const u8) });
    if !all_custom {
        return None;
    }
    let lo = vec3_at(md + 0x30);
    let hi = vec3_at(md + 0x40);
    let size = hi - lo;
    if !(size.min_element() > 0.0 && size.min_element() < 1.0 && size.max_element() < 60.0) {
        return None;
    }
    let c = |i: u32| Vec3::new(if i & 1 == 0 { lo.x } else { hi.x }, if i & 2 == 0 { lo.y } else { hi.y }, if i & 4 == 0 { lo.z } else { hi.z });
    // the 6 faces as 12 triangles (facing is decided later, per triangle)
    let faces = [[0, 1, 3, 2], [4, 5, 7, 6], [0, 1, 5, 4], [2, 3, 7, 6], [0, 2, 6, 4], [1, 3, 7, 5]];
    Some(faces.iter().flat_map(|f| [[c(f[0]), c(f[1]), c(f[2])], [c(f[0]), c(f[2]), c(f[3])]]).collect())
}

/// Decodes a hknpCompressedMeshShapeData into shape-local triangles. None if the layout looks wrong.
fn decode(md: usize) -> Option<Vec<Tri>> {
    copy_raw(md).map(|r| decode_raw(&r))
}

/// A compressed mesh's arrays copied out of the game: the copy is cheap on the game thread; the
/// decoding and the cells (up to 5 ms for one shape, mostly the cells, 2026-10-04) go to a worker.
struct RawMesh {
    dmin: Vec3,
    dmax: Vec3,
    secs: Vec<u8>,
    prims: Vec<u8>,
    sidx: Vec<u8>,
    packed: Vec<u8>,
    shared: Vec<u8>,
}

fn copy_raw(md: usize) -> Option<RawMesh> {
    if !readable(md, 0xb0) {
        return None;
    }
    let arr = |off: usize, elem: usize, max: usize| -> Option<Vec<u8>> {
        let p = read_u64(md + off)? as usize;
        let n = u32_at(md + off + 8) as usize;
        if n > max || (n != 0 && !readable(p, n * elem)) {
            return None;
        }
        Some(if n == 0 { Vec::new() } else { unsafe { std::slice::from_raw_parts(p as *const u8, n * elem) }.to_vec() })
    };
    Some(RawMesh {
        dmin: vec3_at(md + 0x30),
        dmax: vec3_at(md + 0x40),
        secs: arr(0x60, 0x60, 20_000)?,
        prims: arr(0x70, 4, 4_000_000)?,
        sidx: arr(0x80, 2, 4_000_000)?,
        packed: arr(0x90, 4, 4_000_000)?,
        shared: arr(0xa0, 8, 4_000_000)?,
    })
}

fn decode_raw(r: &RawMesh) -> Vec<Tri> {
    let u32s = |b: &[u8], i: usize| u32::from_le_bytes([b[i], b[i + 1], b[i + 2], b[i + 3]]);
    let v3 = |b: &[u8], i: usize| Vec3::new(f32::from_bits(u32s(b, i)), f32::from_bits(u32s(b, i + 4)), f32::from_bits(u32s(b, i + 8)));
    let (nsec, nprims, nsidx, npacked, nshared) = (r.secs.len() / 0x60, r.prims.len() / 4, r.sidx.len() / 2, r.packed.len() / 4, r.shared.len() / 8);
    let span = r.dmax - r.dmin;
    let mut tris = Vec::new();
    for s in 0..nsec {
        let a = s * 0x60;
        let off = v3(&r.secs, a + 0x30);
        let scale = v3(&r.secs, a + 0x3c);
        let first_packed = u32s(&r.secs, a + 0x48) as usize;
        let shared_start = u32s(&r.secs, a + 0x4c) as usize;
        let prim_start = u32s(&r.secs, a + 0x50) as usize;
        let counts = u32s(&r.secs, a + 0x58);
        let (num_packed, num_prims) = ((counts & 0xff) as usize, ((counts >> 8) & 0xff) as usize);
        let vert = |i: usize| -> Option<Vec3> {
            if i < num_packed {
                let k = first_packed + i;
                if k >= npacked {
                    return None;
                }
                let v = u32s(&r.packed, k * 4);
                Some(off + scale * Vec3::new((v & 0x7ff) as f32, ((v >> 11) & 0x7ff) as f32, (v >> 22) as f32))
            } else {
                let k = shared_start + i - num_packed;
                if k >= nsidx {
                    return None;
                }
                let si = u16::from_le_bytes([r.sidx[k * 2], r.sidx[k * 2 + 1]]) as usize;
                if si >= nshared {
                    return None;
                }
                let b = &r.shared[si * 8..si * 8 + 8];
                let v = u64::from_le_bytes([b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7]]);
                let f = Vec3::new(
                    (v & 0x1f_ffff) as f32 / 0x1f_ffff as f32,
                    ((v >> 21) & 0x1f_ffff) as f32 / 0x1f_ffff as f32,
                    (v >> 42) as f32 / 0x3f_ffff as f32,
                );
                Some(r.dmin + span * f)
            }
        };
        for p in prim_start..(prim_start + num_prims).min(nprims) {
            let idx = [r.prims[p * 4], r.prims[p * 4 + 1], r.prims[p * 4 + 2], r.prims[p * 4 + 3]].map(|b| b as usize);
            let (Some(a), Some(b), Some(c)) = (vert(idx[0]), vert(idx[1]), vert(idx[2])) else { continue };
            tris.push([a, b, c]);
            if idx[3] != idx[2] {
                if let Some(d) = vert(idx[3]) {
                    tris.push([a, c, d]);
                }
            }
        }
    }
    tris
}

/// hknpCompoundShape: +0x48 instances (0x80 each), +0x50 count. Instance: +0x00/+0x10/+0x20
/// rotation columns, +0x30 translation, +0x40 scale, +0x50 child shape.
fn decode_compound(shape: usize) -> Option<Vec<Tri>> {
    let inst = read_u64(shape + 0x48)? as usize;
    let n = (u32_at(shape + 0x50) as usize).min(1024);
    if n == 0 || !readable(inst, n * 0x80) {
        return None;
    }
    let mut out = Vec::new();
    for k in 0..n {
        let a = inst + k * 0x80;
        let (c0, c1, c2) = (vec3_at(a), vec3_at(a + 0x10), vec3_at(a + 0x20));
        let t = vec3_at(a + 0x30);
        let scale = vec3_at(a + 0x40);
        let child = read_u64(a + 0x50)? as usize;
        if !class_of(child).is_some_and(|c| c.contains("CompressedMeshShape")) {
            continue;
        }
        let Some(tris) = read_u64(child + 0x48).and_then(|md| decode(md as usize)) else { continue };
        for tri in tris {
            out.push(tri.map(|v| {
                let v = v * scale;
                c0 * v.x + c1 * v.y + c2 * v.z + t
            }));
        }
    }
    Some(out)
}

impl HavokCollision {
    pub fn new(layers: Vec<u32>) -> Self {
        Self { layers, ..Default::default() }
    }

    /// A compressed mesh of custom (convex piece) primitives only, as its box.
    fn custom_box(&mut self, shape: usize, md: usize, body: usize, layer: u32) -> Option<Arc<Mesh>> {
        let b = custom_pieces_box(md)?;
        self.boxed.insert(shape);
        log(format!("collision: body {body} (layer {layer:#x}) is custom pieces only: using its box"));
        Some(Arc::new(Mesh::new(b)))
    }

    /// World-space (Havok) triangles near `center` from all allowed bodies, in one go.
    pub fn query(&mut self, center: Vec3, win: Window) -> Option<Vec<(Tri, u32, u32)>> {
        let mut run = QueryRun::new(center, win);
        loop {
            if let Some(mut done) = self.query_step(&mut run, usize::MAX)? {
                cap(&mut done, center, win.max_tris);
                return Some(done);
            }
        }
    }

    /// The next `budget` bodies of a window query: None if the Havok world is unavailable,
    /// Some(None) while bodies are left, Some(Some(triangles)) when done. The body table is read
    /// afresh each call (streaming can reallocate it between frames; slots keep their index).
    pub fn query_step(&mut self, run: &mut QueryRun, budget: usize) -> Option<Option<Vec<(Tri, u32, u32)>>> {
        self.query_step_until(run, budget, None)
    }

    /// `query_step`, also stopping once `deadline` has passed (checked after each body: a shape
    /// decoded for the first time can still take longer on its own).
    pub fn query_step_until(&mut self, run: &mut QueryRun, budget: usize, deadline: Option<std::time::Instant>) -> Option<Option<Vec<(Tri, u32, u32)>>> {
        let setup_t0 = std::time::Instant::now();
        let havok = unsafe { CSHavokMan::instance() }.ok()?;
        let base = havok as *const CSHavokMan as usize;
        let pw = read_u64(base + 0x98)? as usize;
        let world = read_u64(pw + 0x8)? as usize;
        let bodies = read_u64(world + 0x28)? as usize;
        let count = (u32_at(world + 0x30) as usize).min(262_144);
        if !readable(bodies, count * 0xb0) {
            return None;
        }
        self.bodies = bodies;
        self.body_count = count;
        // a body left half done by the last slice first
        if let Some(mut p) = run.pending.take() {
            if !emit(run, &mut p, deadline) {
                run.pending = Some(p);
                return Some(None);
            }
        }
        let mut end = run.next.saturating_add(budget).min(count);
        run.setup_max_us = run.setup_max_us.max(setup_t0.elapsed().as_secs_f32() * 1e6);
        // (body index, its start, triangles out before it): timed when the next one starts
        let mut timing: Option<(usize, std::time::Instant, usize)> = None;
        for i in run.next..end {
            let now = std::time::Instant::now();
            if let Some((b, t, n)) = timing.replace((i, now, run.out.len())) {
                let us = (now - t).as_secs_f32() * 1e6;
                if us > run.slowest.0 {
                    run.slowest = (us, b, u32_at(bodies + b * 0xb0 + 0x6c), run.out.len() - n);
                }
            }
            if deadline.is_some_and(|d| now >= d) {
                end = i;
                break;
            }
            let body = bodies + i * 0xb0;
            let shape = unsafe { *((body + 0x60) as *const usize) };
            if shape == 0 || self.exclude.contains(&(i as u32)) {
                continue;
            }
            let layer = u32_at(body + 0x6c);
            let t = vec3_at(body + 0x30);
            // the stored quaternion maps world -> body space; we need body -> world (verified: 1319/1327
            // ground-truth points within 2 cm with the inverse vs 504 without)
            let q = Quat::from_xyzw(f32_at(body + 0x80), f32_at(body + 0x84), f32_at(body + 0x88), f32_at(body + 0x8c)).conjugate();
            // skip layers we don't want before touching the shape
            if !self.layers.is_empty() && !self.layers.contains(&(layer & 0xff)) {
                *run.seen_layers.entry(layer).or_default() += 1;
                continue;
            }
            // taken out of the physics world (+0x78 broadphase id -1): an opened door's blocker,
            // a broken crate... the body stays in the list but nothing collides with it
            if u32_at(body + 0x78) == u32::MAX {
                self.not_in_world += 1;
                continue;
            }
            run.n_layer_ok += 1;
            // shapes get freed and re-allocated as the world streams: validate the cache entry
            // unknown shapes (and stale pointers in unused body slots) get one real memory check,
            // after which they're cached; known shapes are read directly
            if matches!(self.meshes.get(&shape), Some((0, 0, None))) {
                continue;
            }
            if !self.meshes.contains_key(&shape) && !self.convex.contains_key(&shape) && !readable(shape, 0x50) {
                self.meshes.insert(shape, (0, 0, None));
                continue;
            }
            let vtable = unsafe { *(shape as *const usize) };
            let convex = match self.convex.get(&shape) {
                Some((vt, m)) if *vt == vtable => Some(m.clone()),
                Some(_) => {
                    self.convex.remove(&shape);
                    None
                }
                None => None,
            };
            let md = unsafe { *((shape + 0x48) as *const usize) };
            // (no VirtualQuery here: it is a slow Wine server call; memory is validated on decode)
            let nprims = if convex.is_some() { 0 } else { match self.meshes.get(&shape) {
                // non-mesh shapes (boxes etc.) are cached as None: nothing to read, skip them
                Some((cmd, _, None)) if *cmd == md => continue,
                Some((cmd, _, Some(_))) if *cmd == md && md != 0 => u32_at(md + 0x78),
                _ => 0,
            } };
            let mesh = if let Some(m) = convex { m } else { match self.meshes.get(&shape) {
                Some((cmd, cn, m)) if *cmd == md && *cn == nprims && md != 0 => m.clone(),
                _ if self.decoding.contains_key(&shape) => {
                    // decoded off the game thread: the query waits at this body until it is done,
                    // never skips it (the window would have a hole)
                    let (dmd, dn) = { let d = &self.decoding[&shape]; (d.0, d.1) };
                    match self.decoding[&shape].2.try_recv() {
                        Err(std::sync::mpsc::TryRecvError::Empty) => {
                            end = i;
                            break;
                        }
                        got => {
                            self.decoding.remove(&shape);
                            let m = got.ok().flatten().or_else(|| self.custom_box(shape, dmd, i, layer));
                            self.meshes.insert(shape, (dmd, dn, m.clone()));
                            if dmd != md {
                                // reallocated meanwhile (streaming): decoded afresh next query
                                continue;
                            }
                            m
                        }
                    }
                }
                _ => {
                    run.n_decoded += 1;
                    if self.queries == 0 {
                        crate::dlog(format!("  decoding body {i} layer {layer:#x} shape {shape:#x} md {md:#x} class {:?}", class_of(shape)));
                    }
                    let cls = class_of(shape).unwrap_or_default();
                    if cls.contains("ConvexPolytopeShape") || cls.contains("BoxShape") || cls.contains("CylinderShape") {
                        let tris = decode_convex(shape).filter(|t| !t.is_empty());
                        let m = tris.map(|t| Arc::new(Mesh::new(t)));
                        self.meshes.remove(&shape);
                        self.convex.insert(shape, (vtable, m.clone()));
                        m
                    } else {
                    let t_decode = std::time::Instant::now();
                    if cls.contains("CompressedMeshShape") && deadline.is_some() {
                        if let Some(raw) = copy_raw(md) {
                            let n = u32_at(md + 0x78);
                            let (tx, rx) = std::sync::mpsc::channel();
                            std::thread::spawn(move || {
                                let t = decode_raw(&raw);
                                let _ = tx.send((!t.is_empty()).then(|| Arc::new(Mesh::new(t))));
                            });
                            self.decoding.insert(shape, (md, n, rx));
                            end = i;
                            break;
                        }
                    }
                    let tris = if cls.contains("CompressedMeshShape") {
                        decode(md).filter(|t| !t.is_empty()).or_else(|| {
                            let b = custom_pieces_box(md);
                            if b.is_some() {
                                self.boxed.insert(shape);
                                log(format!("collision: body {i} (layer {layer:#x}) is custom pieces only: using its box"));
                            }
                            b
                        })
                    } else if cls.contains("CompoundShape") {
                        decode_compound(shape)
                    } else {
                        None
                    };
                    let decode_us = t_decode.elapsed().as_secs_f32() * 1e6;
                    let ntris = tris.as_ref().map_or(0, |t| t.len());
                    let m = tris.filter(|t| !t.is_empty()).map(|t| Arc::new(Mesh::new(t)));
                    let total_us = t_decode.elapsed().as_secs_f32() * 1e6;
                    if total_us > 500.0 {
                        crate::dlog(format!("  slow decode: body {i} layer {layer:#x} {cls}: {ntris} triangles, decode {decode_us:.0} µs + cells {:.0} µs", total_us - decode_us));
                    }
                    let n = if md != 0 && readable(md + 0x70, 16) { u32_at(md + 0x78) } else { 0 };
                    self.meshes.insert(shape, (md, n, m.clone()));
                    m
                    }
                }
            } };
            let Some(mesh) = mesh else { continue };
            if (t - run.center).length() > mesh.radius + run.win.radius + run.win.below {
                continue;
            }
            *run.seen_layers.entry(layer).or_default() += 1;
            // query boxes (world AABBs): the main box around the player and a narrow deep column under him
            let boxes = [
                (run.center - Vec3::new(run.win.radius, run.win.down, run.win.radius), run.center + Vec3::new(run.win.radius, run.win.up, run.win.radius)),
                (run.center - Vec3::new(run.win.column, run.win.below, run.win.column), run.center + Vec3::new(run.win.column, 0.0, run.win.column)),
            ];
            let inv = q.inverse();
            let c = |v: f32| (v / CELL).floor() as i32;
            // a Vec, sorted and deduplicated after: hashing tens of thousands of indices of a big
            // terrain mesh made single bodies take over 1 ms (Boss room, 2026-10-04)
            let mut picked: Vec<u32> = Vec::new();
            for (wlo, whi) in boxes {
                let (mut llo, mut lhi) = (Vec3::splat(f32::MAX), Vec3::splat(f32::MIN));
                for k in 0..8 {
                    let p = Vec3::new(
                        if k & 1 == 0 { wlo.x } else { whi.x },
                        if k & 2 == 0 { wlo.y } else { whi.y },
                        if k & 4 == 0 { wlo.z } else { whi.z },
                    );
                    let l = inv * (p - t);
                    llo = llo.min(l);
                    lhi = lhi.max(l);
                }
                for x in c(llo.x)..=c(lhi.x) {
                    for y in c(llo.y)..=c(lhi.y) {
                        for z in c(llo.z)..=c(lhi.z) {
                            if let Some(list) = mesh.cells.get(&(x, y, z)) {
                                picked.extend(list.iter().copied());
                            }
                        }
                    }
                }
            }
            picked.sort_unstable();
            picked.dedup();
            run.n_near += 1;
            run.n_picked += picked.len();
            let mut p = Pending { mesh, q, t, layer: layer & 0xff, body: i as u32, picked, at: 0 };
            if !emit(run, &mut p, deadline) {
                // the rest of this body next slice
                run.pending = Some(p);
                end = i + 1;
                break;
            }
        }
        if let Some((b, t, n)) = timing {
            let us = t.elapsed().as_secs_f32() * 1e6;
            if us > run.slowest.0 {
                run.slowest = (us, b, u32_at(bodies + b * 0xb0 + 0x6c), run.out.len() - n);
            }
        }
        run.next = end;
        if run.next < count || run.pending.is_some() {
            return Some(None);
        }
        self.queries += 1;
        if self.queries % 10 == 1 || run.slowest.0 > 800.0 || run.setup_max_us > 800.0 {
            crate::dlog(format!(
                "havok query: {:.1} ms, bodies {count}, layer ok {}, decoded {}, near {}, picked {}, out {}; slowest body #{} layer {:#x} {:.0} µs ({} out), slice set-up max {:.0} µs",
                run.started.elapsed().as_secs_f32() * 1000.0, run.n_layer_ok, run.n_decoded, run.n_near, run.n_picked, run.out.len(),
                run.slowest.1, run.slowest.2, run.slowest.0, run.slowest.3, run.setup_max_us
            ));
        }
        if !self.logged_layers {
            self.logged_layers = true;
            log(format!("havok collision: layers near the player (layer -> bodies): {:x?}", run.seen_layers));
        }
        Some(Some(std::mem::take(&mut run.out)))
    }
}

/// Keeps the `max` triangles of a window nearest `center` (distance to the triangle's box, not its
/// centre: a big floor triangle under the player has its centre metres away and got cut first).
/// Partitions instead of sorting: a full sort of 20,000+ took ~3 ms (2026-10-04). Split queries
/// (`query_step*`) return the window uncapped, so this can run off the game thread.
pub fn cap(out: &mut Vec<(Tri, u32, u32)>, center: Vec3, max: usize) {
    if out.len() <= max {
        return;
    }
    let d = |t: &(Tri, u32, u32)| {
        let lo = t.0[0].min(t.0[1]).min(t.0[2]);
        let hi = t.0[0].max(t.0[1]).max(t.0[2]);
        (center.clamp(lo, hi) - center).length_squared()
    };
    out.select_nth_unstable_by(max, |a, b| d(a).total_cmp(&d(b)));
    out.truncate(max);
}

/// A body's picked triangles not yet tested against the window: one dense mesh (20,000+ triangles
/// near the Secluded Cell grace) took over 1 ms on its own, so it is spread over slices.
struct Pending {
    mesh: Arc<Mesh>,
    q: Quat,
    t: Vec3,
    layer: u32,
    body: u32,
    picked: Vec<u32>,
    at: usize,
}

/// Moves `p`'s triangles inside the window to the output; false if `deadline` came first (`p.at`
/// says where to go on).
fn emit(run: &mut QueryRun, p: &mut Pending, deadline: Option<std::time::Instant>) -> bool {
    while p.at < p.picked.len() {
        if p.at % 1024 == 1023 && deadline.is_some_and(|d| std::time::Instant::now() >= d) {
            return false;
        }
        let w = p.mesh.tris[p.picked[p.at] as usize].map(|v| p.q * v + p.t);
        p.at += 1;
        let lo = w[0].min(w[1]).min(w[2]);
        let hi = w[0].max(w[1]).max(w[2]);
        let hits = |r: f32, down: f32, up: f32| {
            lo.x < run.center.x + r && hi.x > run.center.x - r && lo.z < run.center.z + r && hi.z > run.center.z - r
                && hi.y > run.center.y - down && lo.y < run.center.y + up
        };
        if hits(run.win.radius, run.win.down, run.win.up) || hits(run.win.column, run.win.below, 0.0) {
            run.out.push((w, p.layer, p.body));
        }
    }
    true
}

/// A window query in progress (`HavokCollision::query_step`).
pub struct QueryRun {
    pub center: Vec3,
    win: Window,
    next: usize,
    out: Vec<(Tri, u32, u32)>,
    seen_layers: HashMap<u32, u32>,
    n_layer_ok: u32,
    n_decoded: u32,
    n_near: u32,
    n_picked: usize,
    started: std::time::Instant,
    /// Diagnostics for frame time: the slowest body (µs, index, layer, triangles out) and the
    /// slowest slice set-up before the body loop (µs).
    slowest: (f32, usize, u32, usize),
    setup_max_us: f32,
    pending: Option<Pending>,
}

impl QueryRun {
    pub fn new(center: Vec3, win: Window) -> Self {
        QueryRun { center, win, next: 0, out: Vec::new(), seen_layers: HashMap::new(), n_layer_ok: 0, n_decoded: 0, n_near: 0, n_picked: 0, started: std::time::Instant::now(), slowest: (0.0, 0, 0, 0), setup_max_us: 0.0, pending: None }
    }
}
