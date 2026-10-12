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
from fusion_twin.compute import FieldEngine, SCENARIOS, RESULT_CACHE_SIZE, HEATFLUX_RANGE, HEATFLUX_LOG_RANGE
from fusion_twin.pfc import build_pfc
from fusion_twin.physics import DESIGNS, EQUILIBRIA, HEATING_LEVELS, MagneticEquilibrium, heat_pattern, prescribed_loads


class PhysicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="fusion_physics_tests_")
        cls.runtime = Path(cls.temporary.name)
        cls.engine = FieldEngine(ROOT, device="cpu", runtime=cls.runtime)

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
        self.assertAlmostEqual(budget["absorbed_thermal_MW"] + budget["unresolved_MW"], 2050, places=8)
        recovered = result["mass_flow_kg_s"] * 5200 * (result["outlet_temperature_C"] - 300) / 1e6
        self.assertAlmostEqual(recovered, budget["absorbed_thermal_MW"], delta=0.1)
        self.assertGreater(abs(recovered - 2050), 10)

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
                eq = MagneticEquilibrium(source, name)
                for neon in (False, True):
                    with self.subTest(design=design, equilibrium=name, neon=neon):
                        q0 = prescribed_loads(coarse, heat_pattern(coarse, eq, neon=neon), 2000, 1, neon=neon)[0]
                        q1 = prescribed_loads(fine, heat_pattern(fine, eq, neon=neon), 2000, 1, neon=neon)[0]
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
        lines, magnitude = self.engine.lines, self.engine.line_B
        with patch.object(self.engine, "_trace_magnetic", side_effect=AssertionError("unexpected retrace")):
            result = self.engine.compute(self.state(equilibrium="eof", phase=0.52, power=1900, heating=65, neon=True), 711)
        self.assertIs(self.engine.lines, lines)
        self.assertIs(self.engine.line_B, magnitude)
        self.assertEqual(result["equilibrium"], "eof")

    def test_phase_changes_reuse_history_but_controls_invalidate_it(self):
        state = self.state(phase=0.251, power=1731, flow=0.83, inlet=288)
        first = self.engine.compute(state, 712)
        with patch.object(self.engine, "_solve", wraps=self.engine._solve) as solve:
            second = self.engine.compute({**state, "phase": 0.252}, 713)
        self.assertEqual(solve.call_count, 6)  # current, no-Ne baseline and the four-case summary
        self.assertIs(first["history"], second["history"])
        self.assertNotEqual(first["field_ref"]["key"], second["field_ref"]["key"])
        with patch.object(self.engine, "_solve", wraps=self.engine._solve) as solve:
            third = self.engine.compute({**state, "power": 1732}, 714)
        self.assertGreater(solve.call_count, 0)  # new controls still require the surface solves
        self.assertIsNot(third["history"], second["history"])

    def test_parameter_extremes_remain_finite_and_conservative(self):
        for design, equilibrium in itertools.product(DESIGNS, EQUILIBRIA):
            self.engine._select_context(design, equilibrium)
            for power, flow, inlet, phase, heating, neon in itertools.product((500, 2600), (0.4, 1.4), (200, 400), (0, 1), (20, 65), (False, True)):
                parameters = {"power": power, "flow": flow, "inlet": inlet, "hotspot": 1.35, "heating": heating, "neon": neon}
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
        result = self.engine.compute(self.state(design="longleg", equilibrium="eof", phase=0.623,
                                               power=1831, heating=20, flow=0.72, inlet=260), 705)
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

    def test_all_80_cases_close_channels_without_extra_wall_power(self):
        for design, equilibrium, heating, neon in itertools.product(DESIGNS, EQUILIBRIA, HEATING_LEVELS, (False, True)):
            with self.subTest(design=design, equilibrium=equilibrium, heating=heating, neon=neon):
                self.engine._select_context(design, equilibrium)
                parameters = {**SCENARIOS["nominal"], "heating": heating, "neon": neon}
                _, flux, _ = self.engine._solve(parameters, 1)
                budget = self.engine._last_budget
                self.assertAlmostEqual(budget["requested_thermal_MW"], 2000 + heating)
                self.assertAlmostEqual(budget["volume_blanket_MW"], 1600)
                self.assertAlmostEqual(budget["plasma_channel_MW"], 400 + heating)
                self.assertAlmostEqual(budget["radiation_sol_MW"] + budget["wall_particle_requested_MW"] +
                                       budget["target_requested_MW"], budget["separatrix_MW"], places=9)
                self.assertAlmostEqual(float(np.dot(flux, self.engine.mesh.vertex_area) * 18) +
                                       budget["volume_absorbed_MW"] + budget["unresolved_MW"], 2000 + heating, places=8)
                self.assertLessEqual(float(flux.max()), HEATFLUX_RANGE[1])
                self.assertGreaterEqual(float(self.engine.line_B.min()), 2)
                self.assertLessEqual(float(self.engine.line_B.max()), 12)

    def test_auxiliary_heating_adds_power_only_to_the_plasma_channel(self):
        engine = self.engine
        engine._select_context("conventional", "reference")
        parameters = {**SCENARIOS["nominal"], "heating": 20, "neon": False}
        low_t, low_q, _ = engine._solve(parameters, 0.61)
        low = engine._last_budget
        high_t, high_q, _ = engine._solve({**parameters, "heating": 65}, 0.61)
        high = engine._last_budget
        self.assertEqual(low["volume_blanket_MW"], high["volume_blanket_MW"])
        added = 45 * high["load_fraction"]
        self.assertAlmostEqual(high["requested_thermal_MW"] - low["requested_thermal_MW"], added)
        self.assertAlmostEqual(high["plasma_channel_MW"] - low["plasma_channel_MW"], added)
        np.testing.assert_allclose(high_q / low_q, 465 / 420, rtol=1e-7)
        self.assertTrue(np.all(high_t > low_t))

    def test_four_case_comparison_shares_budget_and_uses_same_design_baseline(self):
        state = self.state(design="longleg", equilibrium="sof", heating=65, neon=True, phase=0.671, power=1975)
        result = self.engine.compute(state, 730)
        cases = result["story"]["cases"]
        self.assertEqual({(c["design"], c["neon"]) for c in cases}, set(itertools.product(DESIGNS, (False, True))))
        self.assertEqual(len({c["power_budget"]["requested_thermal_MW"] for c in cases}), 1)
        self.assertEqual(len({c["power_budget"]["separatrix_MW"] for c in cases}), 1)
        for design in DESIGNS:
            off, on = [c for c in cases if c["design"] == design]
            self.assertLess(on["peak_divertor_heatflux_MW_m2"], off["peak_divertor_heatflux_MW_m2"])
            self.assertLess(on["relative_no_neon_percent"], 0)
            self.assertEqual(off["relative_no_neon_percent"], 0)
            self.assertEqual(off["heating"], on["heating"])
            self.assertEqual(off["equilibrium_key"], on["equilibrium_key"])
        self.assertEqual(result["color_ranges"]["heatflux"], HEATFLUX_RANGE)
        self.assertEqual(result["color_ranges"]["heatflux_log"], HEATFLUX_LOG_RANGE)
        self.assertEqual(result["comparison"]["context"]["baseline_parameters"]["heating"], 65)
        self.assertFalse(result["comparison"]["context"]["baseline_parameters"]["neon"])
        self.assertEqual(result["comparison"]["context"]["baseline_parameters"]["power"], 1975)

    def test_neon_and_heating_change_field_but_view_and_animation_do_not(self):
        state = self.state(phase=0.567)
        off = self.engine.compute(state, 731)
        on = self.engine.compute({**state, "neon": True}, 732)
        hot = self.engine.compute({**state, "heating": 65}, 733)
        self.assertEqual(len({r["field_ref"]["key"] for r in (off, on, hot)}), 3)
        viewed = self.engine.compute({**state, "heatScale": "log", "lineMotion": True, "mode": "heatflux"}, 734)
        self.assertIs(viewed, off)

    def test_result_lru_reuses_a_b_a_and_republishes_collected_packet_without_kernel(self):
        a_state = self.state(phase=0.681, heating=20, neon=True)
        a = self.engine.compute(a_state, 740)
        b_state = {**a_state, "design": "longleg"}
        self.engine.compute(b_state, 741)
        packet = self.runtime / a["field_ref"]["path"]
        original = packet.read_bytes()
        with patch.object(self.engine, "_solve", side_effect=AssertionError("LRU hit must not solve")), \
             patch.object(self.engine, "_trace_magnetic", side_effect=AssertionError("LRU hit must not trace")):
            self.assertIs(self.engine.compute(a_state, 742), a)
            packet.unlink()  # Simulated service GC, exclusively in this test's temporary runtime.
            self.engine.compute(b_state, 743)
            restored = self.engine.compute(a_state, 744)
        self.assertEqual(restored["field_ref"]["revision"], 740)
        with np.load(packet) as fields:
            self.assertEqual(int(fields["field_revision"]), 740)
            self.assertEqual(str(fields["field_key"]), a["field_ref"]["key"])
        self.assertEqual(len(packet.read_bytes()), len(original))
        self.assertLessEqual(len(self.engine._results), RESULT_CACHE_SIZE)
        self.assertLessEqual(len(self.engine._histories), RESULT_CACHE_SIZE)
        self.assertLessEqual(len(self.engine._stories), RESULT_CACHE_SIZE)

    def test_auxiliary_and_neon_types_are_checked_at_compute_boundary(self):
        for changes in ({"heating": 0}, {"heating": 51}, {"heating": True}, {"neon": "false"}, {"neon": 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.engine.compute(self.state(**changes), 750)


if __name__ == "__main__":
    unittest.main()
