use crate::Vec3;
use parry3d::{
    bounding_volume::Aabb,
    na::{Isometry3, Point3},
    query::{cast_shapes, contact, Ray, RayCast, ShapeCastOptions},
    shape::{Capsule, TriMesh},
};
use std::{collections::BTreeMap, error::Error, fmt};

pub type ChunkId = u64;
pub type Triangle = [Vec3; 3];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WorldError(pub &'static str);
impl fmt::Display for WorldError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.0)
    }
}
impl Error for WorldError {}

/// Static, double-sided, Y-up triangle terrain, in raw Apex units.
/// Chunk edits are transactional and rebuild the BVH once per batch.
#[derive(Clone, Default)]
pub struct World {
    chunks: BTreeMap<ChunkId, Vec<Triangle>>,
    mesh: Option<TriMesh>,
    triangle_count: usize,
    revision: u64,
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct Hit {
    pub fraction: f32,
    pub normal: Vec3,
    pub surface_normal: Vec3,
    pub point: Vec3,
}

impl World {
    pub fn from_triangles(triangles: &[Triangle]) -> Result<Self, WorldError> {
        let mut world = Self::default();
        world.replace_triangles(triangles)?;
        Ok(world)
    }

    /// Replace the entire streamed local window, including removing old geometry.
    pub fn replace_triangles(&mut self, triangles: &[Triangle]) -> Result<(), WorldError> {
        let chunks = BTreeMap::from([(0, triangles.to_vec())]);
        self.commit(chunks)
    }

    /// Replace/insert named chunks and remove obsolete chunks. Replacements win
    /// if an ID occurs in both lists. A failed update leaves the old world intact.
    pub fn update_chunks(
        &mut self,
        replacements: &[(ChunkId, &[Triangle])],
        removals: &[ChunkId],
    ) -> Result<(), WorldError> {
        let mut chunks = self.chunks.clone();
        for id in removals {
            chunks.remove(id);
        }
        for (id, triangles) in replacements {
            chunks.insert(*id, triangles.to_vec());
        }
        self.commit(chunks)
    }

    fn commit(&mut self, chunks: BTreeMap<ChunkId, Vec<Triangle>>) -> Result<(), WorldError> {
        let mut vertices = Vec::new();
        let mut indices = Vec::new();
        for triangle in chunks.values().flatten() {
            if triangle.iter().any(|v| v.iter().any(|x| !x.is_finite())) {
                return Err(WorldError("non-finite triangle vertex"));
            }
            let cross = (triangle[1] - triangle[0]).cross(&(triangle[2] - triangle[0]));
            if !cross.norm_squared().is_finite() {
                return Err(WorldError("triangle exceeds f32 geometry range"));
            }
            // Degenerate Havok triangles carry no collision area.
            if cross.norm_squared() < 1.0e-12 {
                continue;
            }
            if vertices.len() > u32::MAX as usize - 3 {
                return Err(WorldError("too many triangle vertices"));
            }
            let base = vertices.len() as u32;
            vertices.extend(triangle.iter().map(|v| Point3::from(*v)));
            indices.push([base, base + 1, base + 2]);
        }
        let count = indices.len();
        let mesh = if count == 0 {
            None
        } else {
            Some(TriMesh::new(vertices, indices).map_err(|_| WorldError("TriMesh build failed"))?)
        };
        self.chunks = chunks;
        self.mesh = mesh;
        self.triangle_count = count;
        self.revision = self.revision.wrapping_add(1);
        Ok(())
    }

    pub fn triangle_count(&self) -> usize {
        self.triangle_count
    }
    pub fn revision(&self) -> u64 {
        self.revision
    }

    fn bounds(feet: Vec3, delta: Vec3, radius: f32, height: f32, skin: f32) -> Aabb {
        let end = feet + delta;
        let pad = Vec3::new(radius + skin, skin, radius + skin);
        Aabb::new(
            Point3::from(feet.inf(&end) - pad),
            Point3::from(feet.sup(&end) + Vec3::new(0.0, height, 0.0) + pad),
        )
    }

    /// BVH broad phase, exact continuous capsule/triangle narrow phase. Checking
    /// candidates individually lets tangential floor contacts coexist with walls.
    pub(crate) fn sweep(
        &self,
        feet: Vec3,
        delta: Vec3,
        radius: f32,
        height: f32,
        skin: f32,
    ) -> Option<Hit> {
        self.sweep_filtered(feet, delta, radius, height, skin, -1.0)
    }

    pub(crate) fn sweep_support(
        &self,
        feet: Vec3,
        delta: Vec3,
        radius: f32,
        height: f32,
        skin: f32,
        slope_cos: f32,
    ) -> Option<Hit> {
        self.sweep_filtered(feet, delta, radius, height, skin, slope_cos)
    }

    #[allow(clippy::too_many_arguments)]
    fn sweep_filtered(
        &self,
        feet: Vec3,
        delta: Vec3,
        radius: f32,
        height: f32,
        skin: f32,
        min_surface_y: f32,
    ) -> Option<Hit> {
        let mesh = self.mesh.as_ref()?;
        if delta.norm_squared() < 1.0e-12 {
            return None;
        }
        let bounds = Self::bounds(feet, delta, radius, height, skin);
        let capsule = Capsule::new_y(height * 0.5 - radius, radius);
        let pose = Isometry3::translation(feet.x, feet.y + height * 0.5, feet.z);
        let mut nearest: Option<Hit> = None;
        #[cfg(feature = "profile")]
        crate::profile::SWEEPS.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let center = pose.translation.vector;
        let half_segment = height * 0.5 - radius;
        // Broad phase, then the cheap plane test per candidate: the capsule cannot touch a
        // triangle before it touches the triangle's plane, so `earliest` (the time it reaches the
        // plane) is a lower bound of its time of impact. Candidates go nearest-bound first and the
        // sweep stops once no candidate can beat the nearest hit (exact casts dominated the cost
        // when pressing into dense Elden Ring meshes: 1300 casts per tick, journal 2026-10-04).
        let mut candidates: Vec<(f32, u32, Vec3, f32, f32)> = Vec::new();
        for id in mesh.bvh().intersect_aabb(&bounds) {
            #[cfg(feature = "profile")]
            crate::profile::CANDIDATES.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            let triangle = mesh.triangle(id);
            let mut face = *triangle.normal().expect("nondegenerate triangle");
            if (center - triangle.a.coords).dot(&face) < 0.0 {
                face = -face;
            }
            if face.y < min_surface_y {
                continue;
            }
            let extent = radius + half_segment * face.y.abs();
            let gap = (center - triangle.a.coords).dot(&face) - extent;
            let approach = delta.dot(&face);
            // A tangent/separating capsule cannot hit any part of a triangle
            // while remaining outside its supporting plane. This also removes
            // numerical seam contacts on large coplanar Havok triangles.
            if gap >= -skin && approach >= -1.0e-6 {
                continue;
            }
            if gap > skin && gap + approach > skin {
                continue;
            }
            // nor can it reach a triangle farther from its axis than its radius, the skin and the
            // whole motion (the AABB corners of a dense mesh are mostly such)
            let axis = (
                center - Vec3::y() * half_segment,
                center + Vec3::y() * half_segment,
            );
            if segment_triangle_distance(
                axis,
                triangle.a.coords,
                triangle.b.coords,
                triangle.c.coords,
            ) > radius + skin + delta.norm()
            {
                continue;
            }
            let earliest = if approach < -1.0e-6 {
                ((gap - skin) / -approach).max(0.0)
            } else {
                0.0
            };
            candidates.push((earliest, id, face, gap, approach));
        }
        candidates.sort_by(|a, b| a.0.total_cmp(&b.0));
        let identity = Isometry3::identity();
        let mut casts = 0;
        for (earliest, id, face, gap, approach) in candidates {
            // nothing beats a hit at the start (pressing into a wall): the caller's next slide
            // iteration meets the other contacts with its clipped motion
            if earliest > nearest.map_or(1.0, |h| h.fraction)
                || nearest.is_some_and(|h| h.fraction <= 0.0)
            {
                break;
            }
            let triangle = mesh.triangle(id);
            if approach < -1.0e-6 {
                let fraction = ((gap - skin) / -approach).max(0.0);
                if fraction <= nearest.map_or(1.0, |h| h.fraction) {
                    let support = center + delta * fraction
                        - face * (radius + skin)
                        - Vec3::y() * (half_segment * face.y.signum());
                    if inside_triangle(
                        support,
                        triangle.a.coords,
                        triangle.b.coords,
                        triangle.c.coords,
                    ) {
                        nearest = Some(Hit {
                            fraction,
                            normal: face,
                            surface_normal: face,
                            point: support,
                        });
                        continue;
                    }
                }
            }
            // Out of exact casts (dense rubble): stop at this candidate's plane, a lower bound of
            // its time of impact. Never deeper than the true contact; at worst a little early.
            if casts >= MAX_CASTS {
                nearest = Some(Hit {
                    fraction: earliest,
                    normal: face,
                    surface_normal: face,
                    point: center + delta * earliest - face * (radius + skin),
                });
                break;
            }
            casts += 1;
            #[cfg(feature = "profile")]
            crate::profile::CASTS.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            let options = ShapeCastOptions {
                max_time_of_impact: nearest.map_or(1.0, |h| h.fraction),
                target_distance: skin,
                stop_at_penetration: false,
                compute_impact_geometry_on_penetration: true,
            };
            // Capsule/triangle is a supported pair in pinned parry3d 0.25.1.
            let Some(hit) = cast_shapes(
                &pose,
                &delta,
                &capsule,
                &identity,
                &Vec3::zeros(),
                &triangle,
                options,
            )
            .expect("supported capsule/triangle query") else {
                continue;
            };
            let normal = *hit.normal2;
            // Only a contact the motion approaches blocks it. Relative to the motion: an edge or
            // vertex contact within the skin returns a slightly different normal every cast, so
            // motion clipped along one still met the next at time 0 by ~1e-5 and the capsule hung
            // in the air for good, gravity piling up (Boss room, 2026-10-04).
            if delta.dot(&normal) >= -1.0e-3 * delta.norm() {
                continue;
            }
            let mut surface_normal = *triangle.normal().expect("nondegenerate triangle");
            if surface_normal.dot(&normal) < 0.0 {
                surface_normal = -surface_normal;
            }
            nearest = Some(Hit {
                fraction: hit.time_of_impact,
                normal,
                surface_normal,
                point: hit.witness2.coords,
            });
        }
        nearest
    }

    pub(crate) fn ray_down(&self, origin: Vec3, distance: f32) -> Option<Hit> {
        let mesh = self.mesh.as_ref()?;
        let ray = Ray::new(Point3::from(origin), -Vec3::y());
        let hit = mesh.cast_local_ray_and_get_normal(&ray, distance, false)?;
        let mut normal = hit.normal;
        if normal.y < 0.0 {
            normal = -normal;
        }
        Some(Hit {
            fraction: hit.time_of_impact / distance,
            normal,
            surface_normal: normal,
            point: (ray.origin + ray.dir * hit.time_of_impact).coords,
        })
    }

    /// The first surface along a ray, for callers' own projectiles (a thrown launch pad): the
    /// distance along `dir` (normalized here), the point and the surface normal facing the ray.
    pub fn ray_cast(
        &self,
        origin: Vec3,
        dir: Vec3,
        max_distance: f32,
    ) -> Option<(f32, Vec3, Vec3)> {
        let mesh = self.mesh.as_ref()?;
        let dir = dir.try_normalize(1.0e-9)?;
        if !max_distance.is_finite() || max_distance <= 0.0 || origin.iter().any(|v| !v.is_finite())
        {
            return None;
        }
        let ray = Ray::new(Point3::from(origin), dir);
        let hit = mesh.cast_local_ray_and_get_normal(&ray, max_distance, false)?;
        let normal = if hit.normal.dot(&dir) > 0.0 {
            -hit.normal
        } else {
            hit.normal
        };
        Some((
            hit.time_of_impact,
            (ray.origin + dir * hit.time_of_impact).coords,
            normal,
        ))
    }

    pub(crate) fn overlaps(&self, feet: Vec3, radius: f32, height: f32, tolerance: f32) -> bool {
        self.deepest_overlap(feet, radius, height, tolerance)
            .is_some()
    }

    pub(crate) fn deepest_overlap(
        &self,
        feet: Vec3,
        radius: f32,
        height: f32,
        tolerance: f32,
    ) -> Option<(Vec3, f32)> {
        let mesh = self.mesh.as_ref()?;
        let bounds = Self::bounds(feet, Vec3::zeros(), radius, height, 0.0);
        let capsule = Capsule::new_y(height * 0.5 - radius, radius);
        let pose = Isometry3::translation(feet.x, feet.y + height * 0.5, feet.z);
        let mut deepest = None;
        for id in mesh.bvh().intersect_aabb(&bounds) {
            if let Some(contact) = contact(
                &pose,
                &capsule,
                &Isometry3::identity(),
                &mesh.triangle(id),
                0.0,
            )
            .expect("supported capsule/triangle contact")
            {
                if contact.dist < -tolerance
                    && deepest.is_none_or(|(_, depth)| -contact.dist > depth)
                {
                    deepest = Some((*contact.normal2, -contact.dist));
                }
            }
        }
        deepest
    }
}

/// Exact capsule/triangle casts per sweep before the rest are taken at their planes (bounds a
/// tick's cost in dense meshes: up to 1.6 ms otherwise in Elden Ring's boss arena, 2026-10-04).
const MAX_CASTS: usize = 48;

/// Closest point of triangle abc to p (Ericson, Real-Time Collision Detection 5.1.5).
fn closest_on_triangle(p: Vec3, a: Vec3, b: Vec3, c: Vec3) -> Vec3 {
    let (ab, ac, ap) = (b - a, c - a, p - a);
    let (d1, d2) = (ab.dot(&ap), ac.dot(&ap));
    if d1 <= 0.0 && d2 <= 0.0 {
        return a;
    }
    let bp = p - b;
    let (d3, d4) = (ab.dot(&bp), ac.dot(&bp));
    if d3 >= 0.0 && d4 <= d3 {
        return b;
    }
    let vc = d1 * d4 - d3 * d2;
    if vc <= 0.0 && d1 >= 0.0 && d3 <= 0.0 {
        return a + ab * (d1 / (d1 - d3));
    }
    let cp = p - c;
    let (d5, d6) = (ab.dot(&cp), ac.dot(&cp));
    if d6 >= 0.0 && d5 <= d6 {
        return c;
    }
    let vb = d5 * d2 - d1 * d6;
    if vb <= 0.0 && d2 >= 0.0 && d6 <= 0.0 {
        return a + ac * (d2 / (d2 - d6));
    }
    let va = d3 * d6 - d5 * d4;
    if va <= 0.0 && (d4 - d3) >= 0.0 && (d5 - d6) >= 0.0 {
        return b + (c - b) * ((d4 - d3) / ((d4 - d3) + (d5 - d6)));
    }
    let denom = 1.0 / (va + vb + vc);
    a + ab * (vb * denom) + ac * (vc * denom)
}

/// Distance between segments p1q1 and p2q2 (Ericson 5.1.9).
fn segment_segment_distance(p1: Vec3, q1: Vec3, p2: Vec3, q2: Vec3) -> f32 {
    let (d1, d2, r) = (q1 - p1, q2 - p2, p1 - p2);
    let (a, e, f) = (d1.dot(&d1), d2.dot(&d2), d2.dot(&r));
    let (s, t) = if a <= 1.0e-12 && e <= 1.0e-12 {
        (0.0, 0.0)
    } else if a <= 1.0e-12 {
        (0.0, (f / e).clamp(0.0, 1.0))
    } else {
        let c = d1.dot(&r);
        if e <= 1.0e-12 {
            ((-c / a).clamp(0.0, 1.0), 0.0)
        } else {
            let b = d1.dot(&d2);
            let denom = a * e - b * b;
            let mut s = if denom > 1.0e-12 {
                ((b * f - c * e) / denom).clamp(0.0, 1.0)
            } else {
                0.0
            };
            let mut t = (b * s + f) / e;
            if t < 0.0 {
                t = 0.0;
                s = (-c / a).clamp(0.0, 1.0);
            } else if t > 1.0 {
                t = 1.0;
                s = ((b - c) / a).clamp(0.0, 1.0);
            }
            (s, t)
        }
    };
    ((p1 + d1 * s) - (p2 + d2 * t)).norm()
}

/// Distance from segment pq to triangle abc: 0 if it crosses the triangle, else the least of its
/// ends to the triangle and of it to the triangle's edges.
fn segment_triangle_distance((p, q): (Vec3, Vec3), a: Vec3, b: Vec3, c: Vec3) -> f32 {
    let n = (b - a).cross(&(c - a));
    let (dp, dq) = (n.dot(&(p - a)), n.dot(&(q - a)));
    if dp * dq <= 0.0 && (dp - dq).abs() > 1.0e-12 {
        let x = p + (q - p) * (dp / (dp - dq));
        if inside_triangle(x, a, b, c) {
            return 0.0;
        }
    }
    [
        (p - closest_on_triangle(p, a, b, c)).norm(),
        (q - closest_on_triangle(q, a, b, c)).norm(),
        segment_segment_distance(p, q, a, b),
        segment_segment_distance(p, q, b, c),
        segment_segment_distance(p, q, c, a),
    ]
    .into_iter()
    .fold(f32::MAX, f32::min)
}

fn inside_triangle(point: Vec3, a: Vec3, b: Vec3, c: Vec3) -> bool {
    // f64 barycentric arithmetic prevents loss of precision on large flat faces.
    let u = (b - a).cast::<f64>();
    let v = (c - a).cast::<f64>();
    let w = (point - a).cast::<f64>();
    let uu = u.dot(&u);
    let uv = u.dot(&v);
    let vv = v.dot(&v);
    let wu = w.dot(&u);
    let wv = w.dot(&v);
    let denominator = uu * vv - uv * uv;
    if denominator <= 0.0 {
        return false;
    }
    let s = (vv * wu - uv * wv) / denominator;
    let t = (uu * wv - uv * wu) / denominator;
    s >= -1.0e-8 && t >= -1.0e-8 && s + t <= 1.0 + 1.0e-8
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn segment_triangle_distances() {
        let (a, b, c) = (
            Vec3::new(0.0, 0.0, 0.0),
            Vec3::new(10.0, 0.0, 0.0),
            Vec3::new(0.0, 0.0, 10.0),
        );
        // straight above the face, crossing it, beside an edge, beyond a vertex
        let d = |p: Vec3, q: Vec3| segment_triangle_distance((p, q), a, b, c);
        assert!((d(Vec3::new(2.0, 3.0, 2.0), Vec3::new(2.0, 8.0, 2.0)) - 3.0).abs() < 1.0e-5);
        assert_eq!(d(Vec3::new(2.0, -1.0, 2.0), Vec3::new(2.0, 1.0, 2.0)), 0.0);
        assert!((d(Vec3::new(5.0, -4.0, -2.0), Vec3::new(5.0, 4.0, -2.0)) - 2.0).abs() < 1.0e-5);
        assert!((d(Vec3::new(-3.0, -1.0, -4.0), Vec3::new(-3.0, 1.0, -4.0)) - 5.0).abs() < 1.0e-5);
    }
}
