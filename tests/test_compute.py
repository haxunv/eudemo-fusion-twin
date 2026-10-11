"""Physical-direction, data-contract and numerical checks for the demo fields.

These checks establish consistency of the declared reduced demonstration model.
They do not validate the model as a reactor thermal or plasma solver.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import warp as wp
from scipy.interpolate import RegularGridInterpolator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from fusion_twin.compute import FieldEngine, SCENARIOS, atomic_json, atomic_replace, colormap


class AtomicPublicationTests(unittest.TestCase):
    def test_json_publication_recovers_after_temporary_windows_lock(self):
        with tempfile.TemporaryDirectory(prefix="fusion_atomic_test_") as temporary:
            target = Path(temporary) / "state.json"
            target.write_text('{"revision": 1}', encoding="utf-8")
            replace_file = os.replace
            attempts = 0

            def locked_then_replace(source, destination):
                nonlocal attempts
                attempts += 1
                if attempts <= 2:
                    raise PermissionError("Windows reader still holds destination")
                replace_file(source, destination)

            with patch("fusion_twin.compute.os.name", "nt"), \
                 patch("fusion_twin.compute.os.replace", side_effect=locked_then_replace), \
                 patch("fusion_twin.compute.time.sleep") as sleep:
                atomic_json(target, {"revision": 2})
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"revision": 2})
            self.assertFalse(target.with_suffix(".json.tmp").exists())
            self.assertEqual(attempts, 3)
            self.assertEqual(sleep.call_count, 2)
            sleep.assert_called_with(0.02)

    def test_persistent_windows_lock_exhausts_budget_and_preserves_files(self):
        with tempfile.TemporaryDirectory(prefix="fusion_atomic_test_") as temporary:
            source, destination = Path(temporary) / "fields.tmp.npz", Path(temporary) / "fields.npz"
            source.write_bytes(b"new fields")
            destination.write_bytes(b"previous fields")
            with patch("fusion_twin.compute.os.name", "nt"), \
                 patch("fusion_twin.compute.os.replace", side_effect=PermissionError("locked")) as replace_file, \
                 patch("fusion_twin.compute.time.sleep") as sleep:
                with self.assertRaises(PermissionError):
                    atomic_replace(source, destination)
            self.assertEqual(replace_file.call_count, 11)
            self.assertEqual(sleep.call_count, 10)
            self.assertAlmostEqual(sum(call.args[0] for call in sleep.call_args_list), 0.2)
            self.assertEqual(source.read_bytes(), b"new fields")
            self.assertEqual(destination.read_bytes(), b"previous fields")


class ComputeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = tempfile.TemporaryDirectory(prefix="fusion_compute_test_")
        cls.engine = FieldEngine(ROOT, runtime=Path(cls.output.name))

    @classmethod
    def tearDownClass(cls):
        cls.output.cleanup()

    def solve(self, parameters, phase=1.0):
        self.engine._select_context("conventional", "reference")
        temperature, heatflux, _ = self.engine._solve(parameters, phase)
        return temperature.copy(), heatflux.copy()

    def test_increasing_power_increases_temperature_and_heatflux(self):
        low = {**SCENARIOS["nominal"], "power": 1000.0}
        high = {**SCENARIOS["nominal"], "power": 2400.0}
        low_t, low_q = self.solve(low)
        high_t, high_q = self.solve(high)
        self.assertTrue(np.all(high_t > low_t))
        self.assertTrue(np.all(high_q > low_q))
        np.testing.assert_allclose(high_q / low_q, 2.4, rtol=2e-5)

    def test_low_flow_heats_wall_without_changing_prescribed_heat_load(self):
        nominal_t, nominal_q = self.solve(SCENARIOS["nominal"])
        low_t, low_q = self.solve(SCENARIOS["lowflow"])
        self.assertTrue(np.all(low_t > nominal_t))
        np.testing.assert_allclose(low_q, nominal_q, atol=1e-6, rtol=1e-6)

    def test_inlet_temperature_is_an_additive_offset(self):
        cold = {**SCENARIOS["nominal"], "inlet": 250.0}
        warm = {**cold, "inlet": 390.0}
        cold_t, cold_q = self.solve(cold)
        warm_t, warm_q = self.solve(warm)
        np.testing.assert_allclose(warm_t - cold_t, 140.0, atol=1e-3)
        np.testing.assert_array_equal(warm_q, cold_q)

    def test_coolant_outlet_obeys_declared_energy_balance(self):
        for flow in (0.4, 0.55, 1.0, 1.4):
            parameters = {**SCENARIOS["nominal"], "power": 1750.0, "flow": flow, "inlet": 287.0}
            temp, flux = self.solve(parameters)
            metrics = self.engine.metrics(temp, flux, parameters)
            mass_flow = metrics["mass_flow_kg_s"]
            self.assertAlmostEqual(mass_flow, 3500.0 * flow, places=3)
            recovered_power = mass_flow * 5200.0 * (metrics["outlet_temperature_C"] - parameters["inlet"])
            # The exported outlet temperature is rounded to 0.01 degrees Celsius.
            rounding_error_watts = mass_flow * 5200.0 * 0.0051
            self.assertLess(abs(recovered_power - 1750.0e6), rounding_error_watts)
            self.assertGreater(metrics["outlet_temperature_C"], parameters["inlet"])

    def test_history_matches_kernel_across_the_scenario(self):
        state = {**SCENARIOS["highload"], "phase": 0.7, "scenario": "highload"}
        result = self.engine.compute(state, 101)
        self.assertEqual(len(result["history"]), 31)
        previous_peak = -np.inf
        for sample in result["history"]:
            self.assertNotIn("time_s", sample)
            phase = sample["phase"]
            temperature, heatflux = self.solve(state, phase)
            self.assertAlmostEqual(sample["peak_temperature_C"], float(temperature.max()), delta=0.02)
            self.assertAlmostEqual(sample["heatflux"], float(heatflux.max()), delta=0.002)
            self.assertGreaterEqual(sample["peak_temperature_C"], previous_peak)
            previous_peak = sample["peak_temperature_C"]

    def test_switching_scenario_updates_cached_result_label(self):
        # Low-flow can be manually adjusted back to the nominal numerical inputs.
        state = {**SCENARIOS["nominal"], "phase": 0.65, "scenario": "lowflow"}
        previous = self.engine.compute(state, 201)
        current = self.engine.compute({**state, "scenario": "nominal"}, 202)
        self.assertEqual(previous["scenario_label"], "lowflow")
        self.assertEqual(current["scenario_label"], "nominal")
        self.assertEqual(previous["peak_temperature_C"], current["peak_temperature_C"])
        self.assertIs(self.engine.compute({**state, "scenario": "nominal"}, 203), current)

    def test_published_fields_have_consistent_shapes_units_and_legends(self):
        state = {**SCENARIOS["lowflow"], "phase": 0.73, "scenario": "lowflow"}
        result = self.engine.compute(state, 102)
        fields = np.load(self.engine.runtime / result["field_ref"]["path"], allow_pickle=False)
        metadata = json.loads(str(fields["metadata_json"]))
        n, m = len(fields["surface_points"]), len(fields["surface_triangles"])
        self.assertEqual(fields["surface_points"].shape, (n, 3))
        self.assertEqual(fields["surface_triangles"].shape, (m, 3))
        self.assertEqual(fields["surface_temperature_C"].shape, (n,))
        self.assertEqual(fields["surface_heatflux_MW_m2"].shape, (n,))
        self.assertEqual(fields["surface_triangle_component"].shape, (m,))
        self.assertGreaterEqual(int(fields["surface_triangles"].min()), 0)
        self.assertLess(int(fields["surface_triangles"].max()), n)
        self.assertEqual(metadata["units"]["temperature"], "degC")
        self.assertEqual(metadata["units"]["heatflux"], "MW/m2")
        self.assertEqual(metadata["units"]["slice"], "keV")
        for array in fields.values():
            if array.dtype.kind in "fi":
                self.assertTrue(np.isfinite(array).all())
        for name in ("temperature_rgb", "heatflux_rgb", "slice_rgb", "delta_temperature_rgb", "delta_heatflux_rgb"):
            self.assertEqual(fields[name].shape[1], 3)
            self.assertTrue(np.all((fields[name] >= 0) & (fields[name] <= 1)))
        for bounds in metadata["ranges"].values():
            self.assertLess(bounds[0], bounds[1])
        self.assertAlmostEqual(float(fields["surface_temperature_C"].max()), result["peak_temperature_C"], delta=0.006)
        self.assertAlmostEqual(float(fields["surface_heatflux_MW_m2"].max()), result["peak_heatflux_MW_m2"], delta=0.0006)
        self.assertIn("synthetic", result["source_label"].lower())
        self.assertIn("synthetic", result["assumptions"]["plasma_slice"].lower())
        self.assertIn("demonstration", result["assumptions"]["limit"].lower())
        self.assertEqual(str(fields["field_key"]), result["field_ref"]["key"])
        self.assertEqual(int(fields["field_revision"]), result["field_ref"]["revision"])
        self.assertEqual(str(fields["topology_key"]), result["field_ref"]["topology_key"])
        fields.close()

    def test_magnetic_lines_stay_in_equilibrium_domain_and_follow_flux(self):
        eq, lines = self.engine.eq, self.engine.lines
        self.assertTrue(np.isfinite(lines).all())
        self.assertEqual(lines.shape[2], 3)
        r, z = eq["x"][:, 0], eq["z"][0]
        cylindrical = np.stack((np.linalg.norm(lines[:, :, :2], axis=2), lines[:, :, 2]), axis=-1)
        self.assertGreaterEqual(float(cylindrical[:, :, 0].min()), float(r.min()))
        self.assertLessEqual(float(cylindrical[:, :, 0].max()), float(r.max()))
        self.assertGreaterEqual(float(cylindrical[:, :, 1].min()), float(z.min()))
        self.assertLessEqual(float(cylindrical[:, :, 1].max()), float(z.max()))
        interpolate_flux = RegularGridInterpolator((r, z), eq["psi"], bounds_error=True)
        psi = interpolate_flux(cylindrical)
        psin = (psi - float(eq["psi_axis"])) / float(eq["psi_bndry"] - eq["psi_axis"])
        # Following an axisymmetric magnetic line should preserve its poloidal flux.
        max_drift = float(np.ptp(psin, axis=1).max())
        self.assertLess(max_drift, 0.06, f"Normalized poloidal-flux drift {max_drift}")

    def test_magnetic_line_tangent_uses_stored_poloidal_field(self):
        eq, lines = self.engine.eq, self.engine.lines
        r_axis, z_axis = eq["x"][:, 0], eq["z"][0]
        indices = np.arange(20, lines.shape[1] - 20, 73)
        radius = np.linalg.norm(lines[:, :, :2], axis=2)
        rz = np.stack((radius[:, indices], lines[:, indices, 2]), axis=-1)
        br = RegularGridInterpolator((r_axis, z_axis), eq["Bx"])(rz)
        bz = RegularGridInterpolator((r_axis, z_axis), eq["Bz"])(rz)
        h = 0.026
        observed = np.stack(((radius[:, indices + 1] - radius[:, indices - 1]) / (2 * h),
                             (lines[:, indices + 1, 2] - lines[:, indices - 1, 2]) / (2 * h)), axis=-1)
        expected = np.stack((br, bz), axis=-1) * (rz[:, :, :1] ** 2 / float(eq["fvac"]))
        np.testing.assert_allclose(observed, expected, atol=0.012, rtol=0.025)

    def test_colormap_clips_values_beyond_fixed_legend(self):
        colors = colormap(np.array([-100, 0, 6, 12, 100], dtype=float), 0, 12)
        np.testing.assert_array_equal(colors[0], colors[1])
        np.testing.assert_array_equal(colors[3], colors[4])
        self.assertFalse(np.array_equal(colors[1], colors[2]))
        self.assertTrue(np.isfinite(colors).all())
        self.assertTrue(np.all((colors >= 0) & (colors <= 1)))


@unittest.skipUnless(wp.is_cuda_available(), "CUDA device is unavailable")
class DeviceConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cpu = FieldEngine(ROOT, device="cpu")
        cls.gpu = FieldEngine(ROOT, device="cuda:0")

    def test_cpu_and_cuda_thermal_results_agree(self):
        for design in ("conventional", "longleg"):
            for equilibrium in ("reference", "rampup", "sof", "eof", "rampdown"):
                self.cpu._select_context(design, equilibrium)
                self.gpu._select_context(design, equilibrium)
                for parameters in (SCENARIOS["nominal"], SCENARIOS["highload"]):
                    with self.subTest(design=design, equilibrium=equilibrium, parameters=parameters):
                        cpu_t, cpu_q, _ = self.cpu._solve(parameters, 0.41)
                        gpu_t, gpu_q, _ = self.gpu._solve(parameters, 0.41)
                        np.testing.assert_allclose(cpu_t, gpu_t, atol=1e-3, rtol=1e-5)
                        np.testing.assert_allclose(cpu_q, gpu_q, atol=1e-5, rtol=1e-5)

    def test_returned_cpu_fields_survive_a_following_solve(self):
        temperatures, heatflux, _ = self.cpu._solve(SCENARIOS["highload"], 0.8)
        expected_t, expected_q = temperatures.copy(), heatflux.copy()
        self.cpu._solve(SCENARIOS["nominal"], 0.8)
        np.testing.assert_array_equal(temperatures, expected_t)
        np.testing.assert_array_equal(heatflux, expected_q)

    def test_all_equilibrium_traces_stay_in_domain_and_agree_between_devices(self):
        for design in ("conventional", "longleg"):
            for equilibrium in ("reference", "rampup", "sof", "eof", "rampdown"):
                with self.subTest(design=design, equilibrium=equilibrium):
                    self.cpu._select_context(design, equilibrium)
                    self.gpu._select_context(design, equilibrium)
                    lines, eq = self.gpu.lines, self.gpu.equilibrium
                    rz = np.stack((np.linalg.norm(lines[:, :, :2], axis=2), lines[:, :, 2]), axis=-1)
                    self.assertTrue(np.isfinite(lines).all())
                    self.assertGreaterEqual(float(rz[:, :, 0].min()), float(eq.r.min()))
                    self.assertLessEqual(float(rz[:, :, 0].max()), float(eq.r.max()))
                    self.assertGreaterEqual(float(rz[:, :, 1].min()), float(eq.z.min()))
                    self.assertLessEqual(float(rz[:, :, 1].max()), float(eq.z.max()))
                    self.assertLess(float(np.ptp(eq.psin(rz), axis=1).max()), 0.005)
                    self.assertLess(float(np.linalg.norm(self.cpu.lines - lines, axis=2).max()), 0.002)


if __name__ == "__main__":
    unittest.main()
