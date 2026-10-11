"""Integration checks on the shipped CAD-derived OpenUSD asset package."""

import hashlib
import json
import unittest
from pathlib import Path

import numpy as np
from pxr import Usd, UsdGeom, UsdUtils


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


class AssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
        cls.stage_path = ASSETS / cls.manifest["stage"]
        cls.stage = Usd.Stage.Open(str(cls.stage_path))

    def test_stage_has_no_unresolved_references(self):
        self.assertFalse(self.stage.GetCompositionErrors())
        _, _, unresolved = UsdUtils.ComputeAllDependencies(str(self.stage_path))
        self.assertEqual(unresolved, [])
        self.assertEqual(UsdGeom.GetStageMetersPerUnit(self.stage), 1.0)
        self.assertEqual(UsdGeom.GetStageUpAxis(self.stage), "Z")

    def test_both_designs_preserve_inspection_contract(self):
        variants = self.stage.GetPrimAtPath("/World/Machine").GetVariantSet("design")
        for variant in self.manifest["design_variants"]:
            variants.SetVariantSelection(variant)
            for component in self.manifest["components"]:
                group = self.stage.GetPrimAtPath(component["usd_path"])
                self.assertTrue(group, (variant, component["id"]))
                sectors = [p for p in group.GetChildren() if p.GetName().startswith("sector_")]
                self.assertEqual(len(sectors), component["sector_count"])
                mesh_count = sum(p.IsA(UsdGeom.Mesh) for p in Usd.PrimRange(group))
                self.assertEqual(mesh_count, component["part_count"])
        variants.SetVariantSelection("conventional")

    def test_manifest_counts_match_composed_geometry(self):
        root = self.stage.GetPrimAtPath("/World/Machine")
        meshes = [UsdGeom.Mesh(p) for p in Usd.PrimRange(root) if p.IsA(UsdGeom.Mesh)]
        self.assertEqual(len(meshes), self.manifest["total_part_count"])
        triangles = sum(len(mesh.GetFaceVertexCountsAttr().Get()) for mesh in meshes)
        self.assertEqual(triangles, self.manifest["total_triangle_count"])
        self.assertGreater(triangles, 1_000_000)

    def test_cameras_and_component_bounds_are_finite(self):
        for camera in self.manifest["cameras"].values():
            prim = self.stage.GetPrimAtPath(camera["usd_path"])
            self.assertTrue(prim.IsA(UsdGeom.Camera))
            transform = UsdGeom.Xformable(prim).GetLocalTransformation()
            self.assertTrue(np.isfinite(np.asarray(transform)).all())
        for component in self.manifest["components"]:
            bounds = np.asarray(component["bounds_m"])
            self.assertTrue(np.isfinite(bounds).all())
            self.assertTrue((bounds[1] > bounds[0]).all())
            self.assertTrue((ASSETS / component["source_step"]).is_file())

    def test_pf_cs_and_plasma_sector_angular_span(self):
        for variant in self.manifest["design_variants"]:
            for component in ("pf_coils", "cs_coils", "plasma"):
                stage = Usd.Stage.Open(str(ASSETS / "scene/geometry" / variant / f"{component}.usdc"))
                for prim in stage.Traverse():
                    if prim.IsA(UsdGeom.Mesh):
                        points = np.asarray(UsdGeom.Mesh(prim).GetPointsAttr().Get())
                        angle = np.degrees(np.arctan2(points[:, 1], points[:, 0]))
                        self.assertAlmostEqual(float(angle.min()), 0.0, places=3)
                        self.assertAlmostEqual(float(angle.max()), 20.0, places=3)

    def test_source_geometry_is_finite_and_retained_byte_for_byte(self):
        provenance = json.loads((ASSETS / "source/provenance.json").read_text(encoding="utf-8"))
        for entry in provenance["files"]:
            path = ASSETS / entry["path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"])
        for variant in self.manifest["design_variants"]:
            for path in (ASSETS / "source/eudemo" / variant / "cad").glob("*.npz"):
                with np.load(path, allow_pickle=False) as data:
                    points, triangles = data["points"], data["tris"]
                    self.assertTrue(np.isfinite(points).all(), path.name)
                    self.assertGreaterEqual(triangles.min(), 0, path.name)
                    self.assertLess(triangles.max(), len(points), path.name)
                    xyz = points[triangles]
                    area = np.linalg.norm(np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0]), axis=1)
                    self.assertTrue((area > 1e-12).all(), path.name)


if __name__ == "__main__":
    unittest.main()
