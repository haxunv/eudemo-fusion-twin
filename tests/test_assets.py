"""Integration checks on the shipped CAD-derived OpenUSD asset package."""

import hashlib
import importlib.util
import json
import os
import unittest
from pathlib import Path

import numpy as np
from pxr import Usd, UsdGeom, UsdUtils


ROOT = Path(__file__).resolve().parents[1]
ASSETS = Path(os.environ.get("FUSION_TEST_ASSETS", ROOT / "assets"))
SOURCE_ASSETS = ROOT / "assets"


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
            for component in self.manifest["design_components"][variant]:
                group = self.stage.GetPrimAtPath(component["usd_path"])
                self.assertTrue(group, (variant, component["id"]))
                sectors = [p for p in group.GetChildren() if p.GetName().startswith("sector_")]
                self.assertEqual(len(sectors), component["sector_count"])
                mesh_count = sum(p.IsA(UsdGeom.Mesh) for p in Usd.PrimRange(group))
                self.assertEqual(mesh_count, component["mesh_count"])
                part_count = sum(p.GetCustomDataByKey("sourcePartId") is not None for p in Usd.PrimRange(group))
                self.assertEqual(part_count, component["part_count"])
        variants.SetVariantSelection("conventional")

    def test_manifest_counts_match_composed_geometry(self):
        root = self.stage.GetPrimAtPath("/World/Machine")
        meshes = [UsdGeom.Mesh(p) for p in Usd.PrimRange(root) if p.IsA(UsdGeom.Mesh)]
        self.assertEqual(len(meshes), self.manifest["total_mesh_count"])
        triangles = sum(len(mesh.GetFaceVertexCountsAttr().Get()) for mesh in meshes)
        self.assertEqual(triangles, self.manifest["total_triangle_count"])
        self.assertGreater(triangles, 1_000_000)

    def test_cameras_and_component_bounds_are_finite(self):
        for camera in self.manifest["cameras"].values():
            prim = self.stage.GetPrimAtPath(camera["usd_path"])
            self.assertTrue(prim.IsA(UsdGeom.Camera))
            transform = UsdGeom.Xformable(prim).GetLocalTransformation()
            self.assertTrue(np.isfinite(np.asarray(transform)).all())
        for design, components in self.manifest["design_components"].items():
            for component in components:
                bounds = np.asarray(component["bounds_m"])
                self.assertTrue(np.isfinite(bounds).all())
                self.assertTrue((bounds[1] > bounds[0]).all())
                self.assertIn(f"/{design}/", component["source_step"])
                self.assertTrue((SOURCE_ASSETS / component["source_step"]).is_file())

    def test_pf_cs_and_plasma_sector_angular_span(self):
        for variant in self.manifest["design_variants"]:
            for component in ("pf_coils", "cs_coils", "plasma"):
                stage = Usd.Stage.Open(str(ASSETS / "scene/geometry" / variant / f"{component}.usdc"))
                for prim in stage.Traverse():
                    if prim.IsA(UsdGeom.Mesh):
                        points = np.asarray(UsdGeom.Mesh(prim).GetPointsAttr().Get())
                        angle = np.degrees(np.arctan2(points[:, 1], points[:, 0]))
                        self.assertGreaterEqual(float(angle.min()), -1e-4)
                        self.assertLessEqual(float(angle.max()), 20.0001)
                        if prim.GetName() == "body":
                            self.assertAlmostEqual(float(angle.min()), 0.0, places=3)
                            self.assertAlmostEqual(float(angle.max()), 20.0, places=3)

    def test_coil_identity_comes_from_source_semantics(self):
        for design in self.manifest["design_variants"]:
            for component, prefix in (("pf_coils", "PF_"), ("cs_coils", "CS_")):
                stage = Usd.Stage.Open(str(ASSETS / "scene/geometry" / design / f"{component}.usdc"))
                for part in stage.GetDefaultPrim().GetChildren():
                    if part.GetCustomDataByKey("sourcePartId") is None:
                        continue
                    self.assertTrue(part.GetCustomDataByKey("sourceCoilName").startswith(prefix))
                    self.assertIn(prefix, part.GetCustomDataByKey("resolvedPartPath"))
                    self.assertTrue(part.GetCustomDataByKey("continuousRevolution"))
                    self.assertEqual({p.GetName() for p in part.GetChildren()}, {"body", "cap_start", "cap_end"})

    def test_world_cuts_and_exposed_caps_in_both_designs(self):
        path = ROOT / "kit/extensions/fusion.twin.bridge/fusion/twin/bridge/geometry.py"
        spec = importlib.util.spec_from_file_location("fusion_geometry_controller", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for design in self.manifest["design_variants"]:
            stage = Usd.Stage.Open(str(self.stage_path))
            stage.SetEditTarget(stage.GetSessionLayer())
            stage.GetPrimAtPath("/World/Machine").GetVariantSet("design").SetVariantSelection(design)
            controller = module.GeometryController(stage)
            continuous_parts = sum(c["unique_part_count"] for c in self.manifest["design_components"][design]
                                   if c["continuous_revolution"])
            for cut in (80, 0, 180, 85):
                controller.apply({"cutaway": cut, "explode": 0, "visible": {}})
                transform_cache = UsdGeom.XformCache()
                exposed_caps = 0
                for prim in Usd.PrimRange(stage.GetPrimAtPath("/World/Machine")):
                    if not prim.IsA(UsdGeom.Mesh) or UsdGeom.Imageable(prim).ComputeVisibility() == "invisible":
                        continue
                    exposed_caps += prim.GetName().startswith("cap_")
                    points = np.asarray(UsdGeom.Mesh(prim).GetPointsAttr().Get(), dtype=float)
                    matrix = np.asarray(transform_cache.GetLocalToWorldTransform(prim))
                    world = (np.c_[points, np.ones(len(points))] @ matrix)[:, :3]
                    angles = np.mod(np.degrees(np.arctan2(world[:, 1], world[:, 0])), 360)
                    angles[np.abs(angles-360) < 1e-4] = 0
                    radial = np.linalg.norm(world[:, :2], axis=1) > 1e-5
                    if cut:
                        self.assertTrue(np.all(angles[radial] <= 360-cut+1e-4), (design, cut, str(prim.GetPath())))
                self.assertEqual(exposed_caps, 2*continuous_parts if cut else 0)
                if cut == 80:
                    # The TF centred at 280 degrees is cut in half, not discarded.
                    tf = stage.GetPrimAtPath("/World/Machine/tf_coils/sector_14/p000")
                    self.assertEqual(UsdGeom.Imageable(tf).ComputeVisibility(), "inherited")
            controller.apply({"cutaway": 80, "explode": 0.5, "visible": {}})
            caps = [p for p in Usd.PrimRange(stage.GetPrimAtPath("/World/Machine"))
                    if p.GetName().startswith("cap_") and UsdGeom.Imageable(p).ComputeVisibility() != "invisible"]
            self.assertEqual(len(caps), 14*2*continuous_parts)

    def test_source_geometry_is_finite_and_retained_byte_for_byte(self):
        provenance = json.loads((SOURCE_ASSETS / "source/provenance.json").read_text(encoding="utf-8"))
        for entry in provenance["files"]:
            path = SOURCE_ASSETS / entry["path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"])
        for variant in self.manifest["design_variants"]:
            for path in (SOURCE_ASSETS / "source/eudemo" / variant / "cad").glob("*.npz"):
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
