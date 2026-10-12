"""Exercise explicit QA archival using disposable directories only."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import archive_qa


class ArchiveQATests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fusion_archive_test_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.qa = self.root / "runtime/qa"
        self.source = self.qa / "run one"
        (self.source / "nested/empty").mkdir(parents=True)
        self.contents = {"report.json": b'{"passed":true,"hash":"unchanged"}\r\n',
                         "view.png": b"PNG bytes\x00\xff", "nested/detail.PNG": b"nested image"}
        for name, content in self.contents.items():
            (self.source / name).write_bytes(content)

    def assert_source_unchanged(self):
        for name, content in self.contents.items():
            self.assertEqual((self.source / name).read_bytes(), content)

    def test_default_dry_run_counts_pngs_and_writes_nothing(self):
        report = archive_qa.archive_qa(self.root, "run one")
        self.assertEqual(report["mode"], "dry_run")
        self.assertEqual(report["file_count"], 3)
        self.assertEqual(report["png_count"], 2)
        self.assertEqual(report["png_bytes"], len(self.contents["view.png"]) + len(self.contents["nested/detail.PNG"]))
        self.assertFalse((self.qa / "archives").exists())
        self.assert_source_unchanged()

    def test_verified_archive_preserves_all_bytes_hashes_and_empty_directories(self):
        report = archive_qa.archive_qa(self.root, "run one", execute=True)
        self.assertTrue(report["verified"])
        self.assertEqual(report["removed_files"], 3)
        with zipfile.ZipFile(self.qa / report["archive"]) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["source_directory"], "run one")
            self.assertIn("source/nested/empty/", archive.namelist())
            for entry in manifest["files"]:
                original = self.contents[entry["path"]]
                self.assertEqual(archive.read("source/" + entry["path"]), original)
                self.assertEqual(entry["sha256"], hashlib.sha256(original).hexdigest())
                self.assertEqual(entry["size"], len(original))
        self.assertTrue((self.source / "nested/empty").is_dir())
        self.assertFalse(any(path.is_file() for path in self.source.rglob("*")))

    def test_paths_cannot_escape_or_archive_root_or_archives(self):
        for relative in (".", "", "..", "run one/../run one", "archives", "ARCHIVES/old", "archives. ", "archive", str(self.source)):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                archive_qa.archive_qa(self.root, relative, execute=True)
        self.assert_source_unchanged()
        self.assertFalse((self.qa / "archives").exists())

    def test_existing_archive_is_never_overwritten(self):
        destination = self.qa / "archives/run one.zip"
        destination.parent.mkdir()
        destination.write_bytes(b"existing archive")
        with self.assertRaises(FileExistsError):
            archive_qa.archive_qa(self.root, "run one", execute=True)
        self.assertEqual(destination.read_bytes(), b"existing archive")
        self.assert_source_unchanged()

    def test_verification_failure_keeps_every_source_file(self):
        with patch.object(archive_qa, "verify_archive", side_effect=ValueError("injected checksum failure")):
            with self.assertRaises(ValueError):
                archive_qa.archive_qa(self.root, "run one", execute=True)
        self.assert_source_unchanged()

    def test_changed_source_aborts_removal_and_new_files_are_kept(self):
        verify = archive_qa.verify_archive

        def change_source(path, manifest):
            verify(path, manifest)
            (self.source / "view.png").write_bytes(b"new rendering")

        with patch.object(archive_qa, "verify_archive", side_effect=change_source):
            with self.assertRaisesRegex(ValueError, "Source changed"):
                archive_qa.archive_qa(self.root, "run one", execute=True)
        self.assertEqual((self.source / "report.json").read_bytes(), self.contents["report.json"])
        self.assertEqual((self.source / "nested/detail.PNG").read_bytes(), self.contents["nested/detail.PNG"])
        self.assertEqual((self.source / "view.png").read_bytes(), b"new rendering")

    def test_new_files_created_after_inventory_are_not_removed(self):
        verify = archive_qa.verify_archive

        def add_source(path, manifest):
            verify(path, manifest)
            (self.source / "new.png").write_bytes(b"new capture")

        with patch.object(archive_qa, "verify_archive", side_effect=add_source):
            report = archive_qa.archive_qa(self.root, "run one", execute=True)
        self.assertEqual(report["removed_files"], 3)
        self.assertEqual((self.source / "new.png").read_bytes(), b"new capture")

    def test_real_symlink_is_rejected_before_creating_archive(self):
        outside = self.root / "outside"
        outside.mkdir()
        link = self.source / "linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Local symlink creation unavailable: {type(error).__name__}")
        with self.assertRaisesRegex(ValueError, "Links and junctions"):
            archive_qa.archive_qa(self.root, "run one", execute=True)
        self.assert_source_unchanged()
        self.assertFalse((self.qa / "archives").exists())

    @unittest.skipUnless(os.name == "nt", "Windows directory junction test")
    def test_windows_junction_is_rejected_for_source_and_archive_destination(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep.json").write_bytes(b"outside source")
        for link in (self.source / "linked", self.qa / "archives"):
            with self.subTest(link=link.name):
                created = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                                         capture_output=True, text=True, check=False)
                self.assertEqual(created.returncode, 0, created.stderr)
                try:
                    with self.assertRaisesRegex(ValueError, "Links and junctions"):
                        archive_qa.archive_qa(self.root, "run one", execute=True)
                    self.assert_source_unchanged()
                    self.assertEqual((outside / "keep.json").read_bytes(), b"outside source")
                    self.assertEqual(len(list(outside.iterdir())), 1)
                finally:
                    link.rmdir()

    def test_independent_verification_rejects_tampered_content(self):
        report = archive_qa.archive_qa(self.root, "run one", execute=True)
        destination = self.qa / report["archive"]
        with zipfile.ZipFile(destination) as archive:
            entries = {info.filename: archive.read(info) for info in archive.infolist()}
        manifest = json.loads(entries["manifest.json"])
        entries["source/view.png"] = b"corrupt bytes"
        with zipfile.ZipFile(destination, "w") as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            archive_qa.verify_archive(destination, manifest)


if __name__ == "__main__":
    unittest.main()
