"""Validate the shipped data package independently of a running solver."""

import itertools
import json
from pathlib import Path
import unittest

import numpy as np

from fusion_twin.protocol import load_field_packet


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "assets/scenarios"


class BakedScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((CASES / "manifest.json").read_text(encoding="utf-8"))

    def test_complete_unique_design_equilibrium_scenario_coverage(self):
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


if __name__ == "__main__":
    unittest.main()
