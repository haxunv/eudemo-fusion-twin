"""Validate the shipped data package independently of a running solver."""

import itertools
import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np

from fusion_twin.protocol import load_field_packet
from fusion_twin.compute import MODEL_VERSION
from tools.bake_scenarios import bake, planned_cases


ROOT = Path(__file__).resolve().parents[1]
CASES = Path(os.environ.get("FUSION_BAKED_DIR", str(ROOT / "assets/scenarios")))


class BakedScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((CASES / "manifest.json").read_text(encoding="utf-8"))

    def test_complete_unique_design_equilibrium_scenario_coverage(self):
        if self.manifest.get("model_version"):
            self.assertEqual(self.manifest["model_version"], MODEL_VERSION)
            expected = {identifier for identifier, _ in planned_cases()}
        else:
            # The previous shipped package remains readable while v3 is staged.
            expected = {"/".join(case) for case in itertools.product(
                ("conventional", "longleg"), ("reference", "rampup", "sof", "eof", "rampdown"),
                ("nominal", "ramp", "lowflow", "highload"))}
        cases = self.manifest["cases"]
        self.assertEqual(len(cases), len(expected))
        self.assertEqual({case["id"] for case in cases}, expected)
        self.assertEqual(len({case["field_ref"]["key"] for case in cases}), len(expected))

    def test_shipped_packets_match_metadata_power_integrals_and_coolant(self):
        for entry in self.manifest["cases"]:
            with self.subTest(case=entry["id"]):
                case = json.loads((CASES / entry["path"]).read_text(encoding="utf-8"))
                state, result = case["state"], case["result"]
                self.assertEqual(case["data_class"], "synthetic_demo")
                self.assertTrue((ROOT / case["source_equilibrium"]).is_file())
                self.assertEqual(result["field_ref"], entry["field_ref"])
                data = load_field_packet(CASES, entry["field_ref"])
                metadata = json.loads(data["metadata_json"].item())
                budget = result["power_budget"]
                self.assertEqual(metadata["power_budget"], budget)
                self.assertEqual(metadata["design"], state["design"])
                self.assertEqual(metadata["equilibrium"], state["equilibrium"])

                triangles = data["surface_points"].astype(float)[data["surface_triangles"]]
                areas = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0],
                                                triangles[:, 2] - triangles[:, 0]), axis=1) / 2
                heat = data["surface_heatflux_MW_m2"][data["surface_triangles"]].mean(axis=1)
                integrated = float(np.dot(areas, heat) * 18)
                tolerance = budget["requested_thermal_MW"] * 0.001
                self.assertAlmostEqual(integrated, budget["surface_absorbed_MW"], delta=tolerance)
                self.assertAlmostEqual(integrated + budget["volume_absorbed_MW"] + budget["unresolved_MW"],
                                       budget["requested_thermal_MW"], delta=tolerance)
                outlet = state["inlet"] + budget["absorbed_thermal_MW"] * 1e6 / (result["mass_flow_kg_s"] * 5200)
                self.assertAlmostEqual(result["outlet_temperature_C"], outlet, delta=0.01)
                self.assertAlmostEqual(result["peak_temperature_C"], float(data["surface_temperature_C"].max()), delta=0.01)
                self.assertAlmostEqual(result["peak_heatflux_MW_m2"], float(data["surface_heatflux_MW_m2"].max()), delta=0.001)
                if self.manifest.get("model_version"):
                    self.assertEqual(metadata["model_version"], MODEL_VERSION)
                    self.assertEqual(metadata["parameters"]["neon"], state["neon"])
                    self.assertEqual(metadata["parameters"]["heating"], state["heating"])
                    self.assertAlmostEqual(budget["requested_thermal_MW"], state["power"] + state["heating"])
                    self.assertEqual(result["color_clipping"]["heatflux_above_max"], 0)
                    self.assertEqual(result["color_clipping"]["magnetic_below_min"], 0)
                    self.assertEqual(result["color_clipping"]["magnetic_above_max"], 0)
                    self.assertEqual(len(result["story"]["cases"]), 4)


class StagingBakeTests(unittest.TestCase):
    def test_full_plan_has_80_distinct_inputs_and_equal_four_case_controls(self):
        cases = list(planned_cases())
        self.assertEqual(len(cases), 80)
        self.assertEqual(len({identifier for identifier, _ in cases}), 80)
        for _, state in cases:
            self.assertEqual(state["phase"], 1)
            self.assertEqual(state["power"], 2000)
            self.assertIn(state["heating"], (20, 35, 50, 65))
            self.assertIsInstance(state["neon"], bool)

    def test_bake_cannot_overwrite_live_or_shipped_data(self):
        for path in (ROOT / "runtime", ROOT / "runtime/scenarios", ROOT / "assets/scenarios"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                bake(path, device="cpu")

    def test_staged_four_case_packets_are_complete_and_do_not_touch_shipped_assets(self):
        shipped = (ROOT / "assets/scenarios/manifest.json").read_bytes()
        with tempfile.TemporaryDirectory(prefix="fusion_bake_test_") as temporary:
            output = Path(temporary)
            manifest = bake(output, equilibria=("reference",), heating_levels=(35,), device="cpu")
            self.assertEqual(manifest["model_version"], MODEL_VERSION)
            self.assertEqual(len(manifest["cases"]), 4)
            for entry in manifest["cases"]:
                case = json.loads((output / entry["path"]).read_text(encoding="utf-8"))
                data = load_field_packet(output, entry["field_ref"])
                self.assertEqual(data["heatflux_log_rgb"].shape, data["surface_points"].shape)
                self.assertEqual(data["field_line_rgb"].shape, data["magnetic_lines"].shape)
                self.assertEqual(case["state"]["heating"], 35)
                self.assertEqual(case["result"]["color_ranges"]["heatflux_log"], [0.01, 200.0])
        self.assertEqual((ROOT / "assets/scenarios/manifest.json").read_bytes(), shipped)


if __name__ == "__main__":
    unittest.main()
