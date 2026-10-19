"""Public import endpoints: scenario batches and external surface fields, on the real CPU engine."""

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import urlencode

import numpy as np

from fusion_twin import server as server_module
from fusion_twin.compute import FieldEngine
from fusion_twin.imports import SurfaceImport, interpolate, parse_cases
from fusion_twin.protocol import load_field_packet

ROOT = Path(__file__).resolve().parents[1]


class ParsingTests(unittest.TestCase):
    def test_json_and_csv_cases_parse_to_the_same_inputs(self):
        json_cases, json_apply = parse_cases(json.dumps({"cases": [
            {"id": "a", "heating": 65, "neon": True}, {"id": "b", "power": 1800}], "apply": "a"}).encode(),
            "application/json", {})
        csv_cases, csv_apply = parse_cases(b"id,heating,neon,power\na,65,true,\nb,,,1800\n", "text/csv", {"apply": "a"})
        self.assertEqual(json_cases, [("a", {"heating": 65, "neon": True}), ("b", {"power": 1800})])
        self.assertEqual(csv_cases, [("a", {"heating": 65.0, "neon": True}), ("b", {"power": 1800.0})])
        self.assertEqual(json_apply, csv_apply)

    def test_invalid_case_batches_are_rejected(self):
        for body in ({"cases": []}, {"cases": [{"id": "a", "mode": "volume"}]},
                     {"cases": [{"id": "a"}, {"id": "a"}]}, {"cases": [{"id": "a"}], "apply": "missing"}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_cases(json.dumps(body).encode(), "application/json", {})

    def test_surface_rows_are_validated(self):
        for rows in (None, [[1, 2]], [[1, 2, 3, 4, 5]], [[1, float("nan"), 3]]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                SurfaceImport("heatflux", rows)
        with self.assertRaises(ValueError):
            SurfaceImport("pressure", [[1, 2, 3]])
        surface = SurfaceImport.parse(b"R,Z,q\n9.0,-6.5,12\n9.1,-6.6,14\n", "text/csv",
                                      {"quantity": "heatflux", "max_distance": "0.3"})
        self.assertEqual(surface.rows.shape, (2, 3))
        self.assertEqual(surface.max_distance, 0.3)

    def test_interpolation_reproduces_samples_and_marks_uncovered_vertices(self):
        mesh = np.array([[10.0, 0, 1.0], [10.0, 0, 50.0]])
        field, coverage = interpolate(np.array([[10.0, 1.0, 7.5], [11.0, 1.0, 9.0]]), mesh, 0.5)
        self.assertAlmostEqual(field[0], 7.5, places=6)
        self.assertTrue(np.isnan(field[1]))
        self.assertEqual(coverage, 0.5)

    def test_3d_samples_fold_into_the_displayed_sector(self):
        mesh = np.array([[10.0, 0.0, 0.0]])
        angle = np.radians(40)
        rows = np.array([[10 * np.cos(angle), 10 * np.sin(angle), 0.0, 3.0]])
        field, coverage = interpolate(rows, mesh, 0.01)
        self.assertEqual(coverage, 1.0)
        self.assertAlmostEqual(field[0], 3.0)


class EndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="fusion-import-")
        root = Path(cls.temporary.name)
        (root / "assets").mkdir()
        (root / "assets/manifest.json").write_text(json.dumps({"components": [{"id": "blanket"}]}))
        cls.app = server_module.TwinApplication(
            root, engine_factory=lambda _: FieldEngine(ROOT, device="cpu", runtime=root / "runtime"),
            start_background=False)
        cls.httpd = server_module.FusionHTTPServer(("127.0.0.1", 0), server_module.Handler)
        cls.httpd.app = cls.app
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.temporary.cleanup()

    def request(self, method, path, body=None, content_type="application/json"):
        connection = http.client.HTTPConnection(*self.httpd.server_address, timeout=120)
        data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
        connection.request(method, path, body=data, headers={"Content-Type": content_type} if data else {})
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        return response.status, payload

    def test_scenario_batch_computes_without_changing_state_unless_applied(self):
        revision = self.app.revision
        status, payload = self.request("POST", "/api/import/scenarios", {"cases": [
            {"id": "low", "heating": 20}, {"id": "high", "heating": 65, "neon": True}]})
        self.assertEqual(status, 200, payload)
        self.assertEqual(self.app.revision, revision)
        low, high = payload["cases"]
        self.assertEqual(low["inputs"]["heating"], 20)
        self.assertLess(high["peak_divertor_heatflux_MW_m2"], low["peak_divertor_heatflux_MW_m2"])
        self.assertAlmostEqual(low["power_budget"]["requested_thermal_MW"], self.app.state["power"] + 20)

        status, payload = self.request("POST", "/api/import/scenarios?apply=high",
                                       b"id,heating,neon\nhigh,65,true\n", "text/csv")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["applied"], "high")
        self.assertEqual((self.app.state["heating"], self.app.state["neon"]), (65.0, True))
        self.request("POST", "/api/state", {"heating": 50, "neon": False})

    def test_invalid_scenario_values_report_the_case(self):
        status, payload = self.request("POST", "/api/import/scenarios", {"cases": [{"id": "bad", "heating": 40}]})
        self.assertEqual(status, 400)
        self.assertIn("bad", payload["error"])

    def test_surface_import_is_shown_survives_patches_and_clears(self):
        reference = self.app.result["field_ref"]
        data = load_field_packet(self.app.runtime, reference)
        divertor = data["surface_points"][data["surface_regions"] == 1][::40]
        rows = [[float(np.hypot(x, y)), float(z), 42.0] for x, y, z in divertor]
        status, payload = self.request("POST", "/api/import/surface",
                                       {"quantity": "heatflux", "label": "IR camera", "rows": rows, "max_distance": 0.2})
        self.assertEqual(status, 200, payload)
        summary = payload["imported_surface"]
        self.assertEqual((summary["label"], summary["unit"], summary["min"], summary["max"]), ("IR camera", "MW/m2", 42.0, 42.0))
        self.assertGreater(summary["coverage"], 0)
        self.assertEqual(self.app.state["mode"], "heatflux")

        imported = self.app.result["field_ref"]
        packet = load_field_packet(self.app.runtime, imported)
        flux = packet["surface_heatflux_MW_m2"]
        self.assertTrue(np.allclose(flux[np.isfinite(flux)], 42.0))
        self.assertTrue(np.isnan(flux).any())
        self.assertEqual(json.loads(str(packet["metadata_json"]))["imported_surface"]["label"], "IR camera")
        original = load_field_packet(self.app.runtime, self.app.result["source_field_ref"])
        self.assertFalse(np.isnan(original["surface_heatflux_MW_m2"]).any())

        self.request("POST", "/api/state", {"view": "divertor"})
        self.assertEqual(self.app.result["imported_surface"]["label"], "IR camera")
        self.assertEqual(self.request("GET", "/api/import/surface")[1]["imported_surface"]["label"], "IR camera")

        status, payload = self.request("DELETE", "/api/import/surface")
        self.assertEqual(status, 200)
        self.assertNotIn("imported_surface", self.app.result)
        self.assertEqual(self.app.result["field_ref"]["key"], reference["key"])

    def test_surface_far_from_the_machine_is_rejected_without_state_change(self):
        revision = self.app.revision
        status, payload = self.request("POST", "/api/import/surface",
                                       {"quantity": "temperature", "rows": [[500.0, 500.0, 300.0]]})
        self.assertEqual(status, 400)
        self.assertIn("max_distance", payload["error"])
        self.assertEqual(self.app.revision, revision)
        self.assertIsNone(self.app.surface_import)


if __name__ == "__main__":
    unittest.main()
