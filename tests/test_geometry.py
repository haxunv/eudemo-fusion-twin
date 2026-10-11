"""Geometric checks for CAD-derived revolutions and closed angular clipping."""

import itertools
import math
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from fusion_twin.geometry import clip_mesh_angular, revolve_from_endcap


CAD = ROOT / "assets/source/eudemo"
WELD_TOL = 1e-5  # Metres; joins duplicated float32 CAD boundary vertices.


def source_mesh(name, variant="conventional"):
    with np.load(CAD / variant / "cad" / f"{name}.npz", allow_pickle=False) as data:
        return data["points"].astype(np.float64), data["tris"].copy()


def combine(meshes):
    points, triangles, offset = [], [], 0
    for p, t in meshes:
        points.append(p)
        triangles.append(np.asarray(t) + offset)
        offset += len(p)
    return np.concatenate(points), np.concatenate(triangles)


def signed_volume(points, triangles):
    faces = np.asarray(points, dtype=np.float64)[triangles] - np.mean(points, axis=0)
    return float(np.einsum("ij,ij->i", faces[:, 0], np.cross(faces[:, 1], faces[:, 2])).sum() / 6)


def face_areas(points, triangles):
    faces = np.asarray(points, dtype=np.float64)[triangles]
    return np.linalg.norm(np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0]), axis=1) / 2


def welded_indices(points, tolerance=WELD_TOL):
    """Compare topology after joining coincident coordinates across mesh parts."""
    cells, vertices, indices = {}, [], []
    offsets = tuple(itertools.product((-1, 0, 1), repeat=3))
    for point in points:
        cell = tuple(np.floor(point / tolerance).astype(np.int64))
        match = None
        for offset in offsets:
            key = tuple(cell[i] + offset[i] for i in range(3))
            for candidate in cells.get(key, ()):
                delta = point - vertices[candidate]
                if float(delta @ delta) <= tolerance * tolerance:
                    match = candidate
                    break
            if match is not None:
                break
        if match is None:
            match = len(vertices)
            vertices.append(point)
            cells.setdefault(cell, []).append(match)
        indices.append(match)
    return np.asarray(indices, dtype=np.int64)


def contains_point_2d(triangles, point):
    edges = np.roll(triangles, -1, axis=1) - triangles
    relative = np.asarray(point) - triangles
    cross = edges[:, :, 0] * relative[:, :, 1] - edges[:, :, 1] * relative[:, :, 0]
    return bool(np.any(np.all(cross >= -1e-10, axis=1) | np.all(cross <= 1e-10, axis=1)))


def cube():
    points = np.array([
        [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
        [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1],
    ], dtype=np.float64)
    triangles = np.array([
        [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
        [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7],
    ], dtype=np.int32)
    return points, triangles


def square_tube():
    """Square annulus extruded between z=-1 and z=1; volume is 24 m³."""
    outer = np.array([[-2, -2], [2, -2], [2, 2], [-2, 2]], dtype=np.float64)
    inner = outer / 2
    points = np.concatenate([
        np.column_stack((loop, np.full(4, z)))
        for loop, z in ((outer, -1), (outer, 1), (inner, -1), (inner, 1))
    ])
    triangles = []
    for i in range(4):
        j = (i + 1) % 4
        triangles.extend([
            (i, j, j + 4), (i, j + 4, i + 4),
            (i + 8, j + 12, j + 8), (i + 8, i + 12, j + 12),
            (i + 4, j + 4, j + 12), (i + 4, j + 12, i + 12),
            (i, i + 8, j + 8), (i, j + 8, j),
        ])
    return points, np.asarray(triangles, dtype=np.int32)


class GeometryAssertions(unittest.TestCase):
    def assert_closed_mesh(self, points, triangles):
        points, triangles = np.asarray(points), np.asarray(triangles)
        self.assertTrue(np.isfinite(points).all())
        self.assertGreater(len(triangles), 0)
        self.assertEqual(triangles.shape[1], 3)
        self.assertGreaterEqual(int(triangles.min()), 0)
        self.assertLess(int(triangles.max()), len(points))
        self.assertTrue((face_areas(points, triangles) > 1e-12).all(), "Degenerate faces")
        welded = welded_indices(points)[triangles]
        edges = np.concatenate((welded[:, [0, 1]], welded[:, [1, 2]], welded[:, [2, 0]]))
        self.assertTrue((edges[:, 0] != edges[:, 1]).all(), "Collapsed edges")
        _, inverse, counts = np.unique(np.sort(edges, axis=1), axis=0,
                                       return_inverse=True, return_counts=True)
        self.assertTrue((counts == 2).all(),
                        f"Unpaired/non-manifold edges: {int(np.count_nonzero(counts != 2))}")
        direction = np.where(edges[:, 0] < edges[:, 1], 1, -1)
        self.assertTrue((np.bincount(inverse, weights=direction) == 0).all(),
                        "Adjacent faces have inconsistent winding")
        self.assertGreater(signed_volume(points, triangles), 0)

    def assert_in_wedge(self, points, start_deg, end_deg):
        start, end = np.radians([start_deg, end_deg])
        # Half-spaces also handle wraparound and points on the rotation axis.
        start_distance = points[:, 1] * math.cos(start) - points[:, 0] * math.sin(start)
        end_distance = points[:, 0] * math.sin(end) - points[:, 1] * math.cos(end)
        self.assertGreaterEqual(float(start_distance.min()), -WELD_TOL)
        self.assertGreaterEqual(float(end_distance.min()), -WELD_TOL)


class RevolveGeometryTests(GeometryAssertions):
    def test_real_pf_cs_and_plasma_are_closed_twenty_degree_solids(self):
        cases = [("conventional", name) for name in
                 ("pf_coils__p000", "pf_coils__p001", "pf_coils__p002",
                  "pf_coils__p030", "plasma__p000")]
        cases.append(("longleg", "plasma__p000"))
        for variant, name in cases:
            with self.subTest(variant=variant, component=name):
                source_points, source_triangles = source_mesh(name, variant)
                result = revolve_from_endcap(source_points, source_triangles,
                                             angle_deg=20, max_step_deg=2)
                points, triangles = combine(result.values())
                self.assert_closed_mesh(points, triangles)
                self.assert_in_wedge(points, 0, 20)

                body_points, body_triangles = result["body"]
                body_faces = body_points[body_triangles]
                for angle in (0, 20):
                    radians = math.radians(angle)
                    distances = body_faces[:, :, 1] * math.cos(radians) - body_faces[:, :, 0] * math.sin(radians)
                    self.assertFalse(np.any(np.all(np.abs(distances) < WELD_TOL, axis=1)),
                                     "Body retains an artificial radial endcap")

                source_cap = source_triangles[np.all(np.abs(source_points[source_triangles, 1]) < WELD_TOL, axis=1)]
                cap_area = face_areas(source_points, source_cap)
                radial_centroid = source_points[source_cap, 0].mean(axis=1)
                continuous_volume = math.radians(20) * float(cap_area @ radial_centroid)
                self.assertAlmostEqual(signed_volume(points, triangles), continuous_volume,
                                       delta=continuous_volume * 0.002)

    def test_pf_insulation_and_casing_endcaps_preserve_holes(self):
        for name in ("pf_coils__p001", "pf_coils__p002"):
            with self.subTest(component=name):
                source_points, source_triangles = source_mesh(name)
                source_cap = source_triangles[np.all(np.abs(source_points[source_triangles, 1]) < WELD_TOL, axis=1)]
                source_area = float(face_areas(source_points, source_cap).sum())
                source_rz = source_points[np.unique(source_cap)][:, [0, 2]]
                hole_center = (source_rz.min(axis=0) + source_rz.max(axis=0)) / 2
                result = revolve_from_endcap(source_points, source_triangles)
                for cap_name in ("cap_start", "cap_end"):
                    p, t = result[cap_name]
                    self.assertAlmostEqual(float(face_areas(p, t).sum()), source_area,
                                           delta=max(1e-7, source_area * 2e-5))
                    rz = np.column_stack((np.linalg.norm(p[:, :2], axis=1), p[:, 2]))
                    self.assertFalse(contains_point_2d(rz[t], hole_center),
                                     f"{cap_name} fills the winding opening")

    def test_eighteen_bodies_form_closed_ring_without_internal_endcaps(self):
        for name in ("pf_coils__p002", "plasma__p000"):
            with self.subTest(component=name):
                p, t = revolve_from_endcap(*source_mesh(name))["body"]
                instances = []
                for sector in range(18):
                    angle = math.radians(sector * 20)
                    rotation = np.array([[math.cos(angle), -math.sin(angle), 0],
                                         [math.sin(angle), math.cos(angle), 0], [0, 0, 1]])
                    instances.append((p @ rotation.T, t))
                self.assert_closed_mesh(*combine(instances))


class AngularClipTests(GeometryAssertions):
    def test_cube_cuts_are_closed_and_have_expected_volume(self):
        for start, end, volume in ((0, 90, 2), (-45, 45, 2), (0, 180, 4),
                                   (350, 370, 2 * math.tan(math.radians(10)))):
            with self.subTest(start=start, end=end):
                p, t = clip_mesh_angular(*cube(), start, end)
                self.assert_closed_mesh(p, t)
                self.assert_in_wedge(p, start, end)
                self.assertAlmostEqual(signed_volume(p, t), volume, places=6)

    def test_hollow_extrusion_cuts_keep_cavity_and_volume(self):
        for start, end, volume in ((0, 90, 6), (45, 135, 6), (0, 180, 12)):
            with self.subTest(start=start, end=end):
                p, t = clip_mesh_angular(*square_tube(), start, end)
                self.assert_closed_mesh(p, t)
                self.assert_in_wedge(p, start, end)
                self.assertAlmostEqual(signed_volume(p, t), volume, places=6)
                if end == 180:
                    cap_faces = t[np.all(np.abs(p[t, 1]) < WELD_TOL, axis=1)]
                    self.assertGreater(len(cap_faces), 0)
                    self.assertFalse(contains_point_2d(p[cap_faces][:, :, [0, 2]], (0, 0)),
                                     "Coplanar cut caps bridge the central cavity")

    def test_radiation_shield_axis_vertex_does_not_create_ninety_degree_sector(self):
        p, t = source_mesh("radiation_shield__p000")
        radii = np.linalg.norm(p[:, :2], axis=1)
        angles = np.degrees(np.arctan2(p[:, 1], p[:, 0]))
        self.assertGreater(float(angles.max()), 80)  # Undefined azimuth near R=0.
        self.assertLessEqual(float(angles[radii > WELD_TOL].max()), 20.0001)
        clipped_p, clipped_t = clip_mesh_angular(p, t, 0, 20)
        self.assert_closed_mesh(clipped_p, clipped_t)
        self.assert_in_wedge(clipped_p, 0, 20)
        self.assertAlmostEqual(signed_volume(clipped_p, clipped_t), signed_volume(p, t),
                               delta=abs(signed_volume(p, t)) * 1e-5)

    def test_unsupported_angular_spans_are_rejected(self):
        for start, end in ((20, 20), (20, 10), (0, 181)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                clip_mesh_angular(*cube(), start, end)


if __name__ == "__main__":
    unittest.main()
