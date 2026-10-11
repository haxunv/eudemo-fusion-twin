import json
import math
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from fusion_twin.server import Handler, validate_patch


class StateValidationTests(unittest.TestCase):
    def test_numeric_controls_reject_nonfinite_and_out_of_range(self):
        for value in (math.nan, math.inf, -1, True, "2000"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_patch({"power": value}, {"blanket"})

    def test_visibility_is_limited_to_known_components(self):
        self.assertEqual(validate_patch({"visible": {"blanket": False}}, {"blanket"}), {"visible": {"blanket": False}})
        with self.assertRaises(ValueError):
            validate_patch({"visible": {"unknown": True}}, {"blanket"})

    def test_cutaway_uses_real_sector_resolution(self):
        self.assertEqual(validate_patch({"cutaway": 83}, set())["cutaway"], 80)

    def test_unknown_commands_do_not_enter_state(self):
        with self.assertRaises(ValueError):
            validate_patch({"exec": "arbitrary"}, set())

    def test_export_contains_complete_provenance_and_manifest_sources(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "assets/manifest.json").read_text(encoding="utf-8"))
        source_record = json.loads((root / "assets/source/provenance.json").read_text(encoding="utf-8"))
        handler = object.__new__(Handler)
        handler.path = "/api/export"
        handler.server = SimpleNamespace(app=SimpleNamespace(
            root=root, manifest=manifest,
            snapshot=lambda: {"revision": 7, "state": {"scenario": "nominal"}},
        ))
        handler.send_json = Mock()
        handler.do_GET()
        args, kwargs = handler.send_json.call_args
        payload = args[0]
        self.assertTrue(kwargs["attachment"])
        self.assertEqual(payload["provenance"]["manifest_source"], manifest["source"])
        self.assertEqual(payload["provenance"]["source_record"], source_record)
        self.assertTrue(payload["provenance"]["source_record"]["files"])
        self.assertIn("synthetic", payload["data_classification"])


if __name__ == "__main__":
    unittest.main()
