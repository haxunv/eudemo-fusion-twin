"""Run CPU-only UI behavior regressions with Node's built-in test runner."""

from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WebUIBehaviorTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for UI behavior tests")
    def test_ui_state_and_accessibility(self):
        completed = subprocess.run(
            [shutil.which("node"), "--test", "tests/web_ui_state.mjs"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
