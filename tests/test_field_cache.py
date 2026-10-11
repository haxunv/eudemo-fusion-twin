import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fusion_twin.field_cache import FieldCache


class FieldCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fusion-field-cache-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "fields").mkdir()
        self.cache = FieldCache(self.root, keep=2)
        for revision in range(1, 9):
            key = f"packet-{revision}"
            (self.root / f"fields/{key}.npz").write_bytes(bytes([revision]) * 8)
            self.cache.record({"key": key, "path": f"fields/{key}.npz"}, revision)
        self.renderer = {"ready": True, "server_epoch": "server", "applied_revision": 6,
                         "applied_field_key": "packet-6", "applied_volume_field_key": "packet-2",
                         "pending_volume_field_key": "packet-5"}

    def collect(self, renderer=None):
        return self.cache.collect(current_key="packet-8", server_epoch="server", renderer=self.renderer if renderer is None else renderer)

    def test_only_acknowledged_unreferenced_publications_are_removed(self):
        (self.root / "fields/unpublished.npz").write_bytes(b"producer has not committed this")
        result = self.collect()
        self.assertEqual(result["deleted"], ["packet-1", "packet-3", "packet-4"])
        for key in (2, 5, 6, 7, 8):
            self.assertTrue((self.root / f"fields/packet-{key}.npz").exists())
        self.assertTrue((self.root / "fields/unpublished.npz").exists())

    def test_renderer_restart_or_unknown_epoch_prevents_collection(self):
        for renderer in ({}, {**self.renderer, "ready": False}, {**self.renderer, "server_epoch": "old"}):
            self.assertFalse(self.collect(renderer)["deleted"])

    def test_reused_old_content_key_is_protected_by_new_snapshot_revision(self):
        self.cache.record({"key": "packet-1", "path": "fields/packet-1.npz"}, 20)
        self.collect()
        self.assertTrue((self.root / "fields/packet-1.npz").exists())

    def test_open_windows_file_is_preserved_and_ledger_survives_reload(self):
        unlink = Path.unlink
        def locked(path, *args, **kwargs):
            if path.name == "packet-1.npz":
                raise PermissionError("file is in use")
            return unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", locked):
            self.collect()
        reloaded = FieldCache(self.root, self.cache.saved(), keep=2)
        self.assertIn("packet-1", reloaded.publications)
        self.assertTrue((self.root / "fields/packet-1.npz").exists())


if __name__ == "__main__":
    unittest.main()
