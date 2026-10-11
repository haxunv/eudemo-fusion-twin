"""Conservation, source topology and immutable publication regression tests.

These verify the declared synthetic model, not reactor-design validity.
All publication is confined to a temporary directory.
"""

import hashlib
import itertools
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from fusion_twin.compute import FieldEngine, SCENARIOS
from fusion_twin.pfc import build_pfc
from fusion_twin.physics import DESIGNS, EQUILIBRIA, MagneticEquilibrium, heat_pattern, prescribed_loads


class PhysicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="fusion_physics_tests_")
        cls.runtime = Path(cls.temporary.name)
        cls.engine = FieldEngine(ROOT, runtime=cls.runtime)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def state(self, **changes):
        return {**SCENARIOS["nominal"], "scenario": "nominal", "phase": 1.0,
                "design": "conventional", "equilibrium": "reference", **changes}

    def test_budget_matches_triangle_integrals_for_every_design_and_equilibrium(self):
        engine = self.engine
        for design in DESIGNS:
            for name in EQUILIBRIA:
                engine._select_context(design, name)
                mesh = engine.mesh
                p = mesh.points[mesh.faces]
                area = np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1) / 2
                for phase in (0.0, 0.31, 1.0):
                    with self.subTest(design=design, equilibrium=name, phase=phase):
                        temperature, flux, _ = engine._solve(SCENARIOS["nominal"], phase)
                        budget = engine._last_budget
                        integrated = float(np.dot(area, flux[mesh.faces].mean(axis=1)) * 18)
                        self.assertAlmostEqual(integrated, budget["surface_absorbed_MW"], places=8)
                        self.assertAlmostEqual(integrated + budget["volume_absorbed_MW"] + budget["unresolved_MW"],
                                               budget["requested_thermal_MW"], places=8)
                        self.assertLess(abs(budget["closure_residual_MW"]), 1e-8)
                        self.assertTrue(np.all(np.isfinite(temperature)))
                        self.assertTrue(np.all(flux >= 0))

    def test_analysis_mesh_excludes_internal_solids_backs_and_end_caps(self):
        for design in DESIGNS:
            self.engine._select_context(design, "reference")
            mesh = self.engine.mesh
            source = ROOT / "assets/source/eudemo" / design
            manifest = json.loads((source / "cad/manifest.json").read_text())
            for identifier in np.unique(mesh.part_ids):
                component, part = identifier.split("/")
                self.assertIn(component, ("blanket", "divertor"))
                if component == "blanket":
                    self.assertEqual(manifest[component][part]["material"], "FW_material")
            self.assertLess(mesh.provenance["full_machine_area_m2"], 3000)
            self.assertGreater(mesh.provenance["full_machine_area_m2"], 1000)
            radius = np.linalg.norm(mesh.points[:, :2], axis=1)
            toroidal = np.column_stack((-mesh.points[:, 1] / radius, mesh.points[:, 0] / radius, np.zeros(len(radius))))
            np.testing.assert_allclose(np.sum(mesh.normals * toroidal, axis=1), 0, atol=1e-12)
            p = mesh.points[mesh.faces]
            face_normal = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
            self.assertTrue(np.all(np.sum(face_normal * mesh.normals[mesh.faces].mean(axis=1), axis=1) > 0))
            self.assertTrue(np.all(mesh.vertex_area > 0))

    def test_strike_points_are_source_flux_intersections_and_change_with_equilibrium(self):
        self.engine._select_context("conventional", "reference")
        reference = self.engine._pattern(1).strikes
        for leg in ("inner", "outer"):
            point = np.array(reference[leg]["rz_m"])[None, :]
            self.assertLess(abs(float(self.engine.equilibrium.psin(point)[0]) - 1), 1e-8)
            self.assertEqual(reference[leg]["status"], "intersection_model")
        self.engine._select_context("conventional", "eof")
        current = self.engine._pattern(1).strikes
        self.assertGreater(np.linalg.norm(np.array(reference["inner"]["rz_m"]) - current["inner"]["rz_m"]), 0.1)

    def test_missing_inner_strike_is_unresolved_and_excluded_from_coolant(self):
        result = self.engine.compute(self.state(equilibrium="rampup"), 601)
        budget = result["power_budget"]
        self.assertEqual(result["strike_points"]["inner"]["status"], "unresolved")
        self.assertNotIn("rz_m", result["strike_points"]["inner"])
        self.assertGreater(budget["unresolved_MW"], 0)
        self.assertAlmostEqual(budget["absorbed_thermal_MW"] + budget["unresolved_MW"], 2000, places=8)
        recovered = result["mass_flow_kg_s"] * 5200 * (result["outlet_temperature_C"] - 300) / 1e6
        self.assertAlmostEqual(recovered, budget["absorbed_thermal_MW"], delta=0.1)
        self.assertGreater(abs(recovered - 2000), 10)

    def test_coolant_outlet_follows_the_same_phase_load_as_surface_fields(self):
        early = self.engine.compute(self.state(phase=0), 602)
        late = self.engine.compute(self.state(phase=1), 603)
        self.assertLess(early["outlet_temperature_C"], late["outlet_temperature_C"])
        self.assertAlmostEqual(early["power_budget"]["surface_absorbed_MW"] /
                               late["power_budget"]["surface_absorbed_MW"], 0.22, places=10)
        self.assertEqual(late["power_budget"]["unresolved_MW"], 0)

    def test_refined_surface_keeps_peak_heatflux_within_two_percent(self):
        for design in DESIGNS:
            source = ROOT / "assets/source/eudemo" / design
            coarse, fine = build_pfc(source), build_pfc(source, spacing_scale=0.5)
            for name in EQUILIBRIA:
                with self.subTest(design=design, equilibrium=name):
                    eq = MagneticEquilibrium(source, name)
                    q0 = prescribed_loads(coarse, heat_pattern(coarse, eq), 2000, 1)[0]
                    q1 = prescribed_loads(fine, heat_pattern(fine, eq), 2000, 1)[0]
                    self.assertLess(abs(float(q0.max() / q1.max()) - 1), 0.02)

    def test_field_identity_is_immutable_and_view_independent(self):
        first = self.engine.compute(self.state(phase=0.413), 701)
        ref = first["field_ref"]
        path = self.runtime / ref["path"]
        digest, mtime = hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns
        current = self.engine.compute(self.state(phase=0.413, field="magnetic", camera="top", cutaway=180), 999)
        self.assertEqual(current["field_ref"], ref)
        self.assertEqual(path.stat().st_mtime_ns, mtime)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        self.assertFalse((self.runtime / "fields.npz").exists())
        with np.load(path, allow_pickle=False) as packet:
            self.assertEqual(str(packet["field_key"]), ref["key"])
            self.assertEqual(int(packet["field_revision"]), 701)
            self.assertEqual(str(packet["equilibrium_key"]), ref["equilibrium_key"])
            self.assertEqual(str(packet["topology_key"]), ref["topology_key"])
            self.assertEqual(int(packet["schema_version"]), 2)

    def test_equilibrium_and_design_change_field_identity_with_correct_topology(self):
        first = self.engine.compute(self.state(phase=0.431), 702)
        second = self.engine.compute(self.state(phase=0.431, equilibrium="sof"), 703)
        third = self.engine.compute(self.state(phase=0.431, design="longleg", equilibrium="sof"), 704)
        a, b, c = (r["field_ref"] for r in (first, second, third))
        self.assertEqual(a["topology_key"], b["topology_key"])
        self.assertNotEqual(a["equilibrium_key"], b["equilibrium_key"])
        self.assertNotEqual(b["topology_key"], c["topology_key"])
        self.assertEqual(len({a["key"], b["key"], c["key"]}), 3)
        with np.load(self.runtime / a["path"]) as one, np.load(self.runtime / b["path"]) as two:
            self.assertFalse(np.array_equal(one["magnetic_lines"], two["magnetic_lines"]))

    def test_thermal_controls_reuse_cached_magnetic_geometry(self):
        self.engine.compute(self.state(equilibrium="eof", phase=0.51), 710)
        lines = self.engine.lines
        with patch.object(self.engine, "_trace_magnetic", side_effect=AssertionError("unexpected retrace")):
            result = self.engine.compute(self.state(equilibrium="eof", phase=0.52, power=1900), 711)
        self.assertIs(self.engine.lines, lines)
        self.assertEqual(result["equilibrium"], "eof")

    def test_phase_changes_reuse_history_but_controls_invalidate_it(self):
        state = self.state(phase=0.251, power=1731, flow=0.83, inlet=288)
        first = self.engine.compute(state, 712)
        with patch.object(self.engine, "_solve", wraps=self.engine._solve) as solve:
            second = self.engine.compute({**state, "phase": 0.252}, 713)
        self.assertEqual(solve.call_count, 2)  # current field and baseline only
        self.assertIs(first["history"], second["history"])
        self.assertNotEqual(first["field_ref"]["key"], second["field_ref"]["key"])
        with patch.object(self.engine, "_solve", wraps=self.engine._solve) as solve:
            third = self.engine.compute({**state, "power": 1732}, 714)
        self.assertEqual(solve.call_count, 33)
        self.assertIsNot(third["history"], second["history"])

    def test_parameter_extremes_remain_finite_and_conservative(self):
        for design, equilibrium in itertools.product(DESIGNS, EQUILIBRIA):
            self.engine._select_context(design, equilibrium)
            for power, flow, inlet, phase in itertools.product((500, 2600), (0.4, 1.4), (200, 400), (0, 1)):
                parameters = {"power": power, "flow": flow, "inlet": inlet, "hotspot": 1.35}
                with self.subTest(design=design, equilibrium=equilibrium, parameters=parameters, phase=phase):
                    temperature, flux, _ = self.engine._solve(parameters, phase)
                    budget = self.engine._last_budget
                    self.assertTrue(np.isfinite(temperature).all())
                    self.assertTrue(np.isfinite(flux).all())
                    self.assertTrue(np.all(temperature >= inlet))
                    self.assertTrue(np.all(flux >= 0))
                    self.assertLess(abs(budget["closure_residual_MW"]), 1e-8)
                    integrated = float(np.dot(flux, self.engine.mesh.vertex_area) * 18)
                    self.assertAlmostEqual(integrated, budget["surface_absorbed_MW"], places=8)
                    metrics = self.engine.metrics(temperature, flux, parameters)
                    recovered = metrics["mass_flow_kg_s"] * 5200 * (metrics["outlet_temperature_C"] - inlet) / 1e6
                    self.assertAlmostEqual(recovered, budget["absorbed_thermal_MW"],
                                           delta=metrics["mass_flow_kg_s"] * 5200 * 0.0051 / 1e6)

    def test_baseline_difference_is_zero_for_same_geometry_equilibrium_and_controls(self):
        result = self.engine.compute(self.state(design="longleg", equilibrium="eof", phase=0.623), 705)
        with np.load(self.runtime / result["field_ref"]["path"]) as fields:
            np.testing.assert_array_equal(fields["delta_temperature_C"], 0)
            np.testing.assert_array_equal(fields["delta_heatflux_MW_m2"], 0)
        for field in ("delta_temperature", "delta_heatflux"):
            low, high = result["color_ranges"][field]
            self.assertEqual(-low, high)
            self.assertGreater(high, 0)
        self.assertEqual(result["comparison"]["context"]["design"], "longleg")

    def test_failed_atomic_publication_does_not_return_or_replace_previous_field(self):
        previous = self.engine.compute(self.state(phase=0.813), 706)
        path = self.runtime / previous["field_ref"]["path"]
        original = path.read_bytes()
        with patch("fusion_twin.compute.atomic_replace", side_effect=PermissionError("simulated publication failure")):
            with self.assertRaises(PermissionError):
                self.engine.compute(self.state(phase=0.814), 707)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.engine.last_result["field_ref"], previous["field_ref"])


if __name__ == "__main__":
    unittest.main()
