"""Windows launch ownership checks; no application process is started."""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows startup scripts")
class RuntimeTests(unittest.TestCase):
    def powershell(self, body):
        script = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
        script += ". '" + str(ROOT / "tools/runtime.ps1").replace("'", "''") + "'; " + body
        encoded = base64.b64encode(script.encode("utf-16-le")).decode()
        result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
                                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        return json.loads(result.stdout.decode("utf-8-sig"))

    def test_service_identity_distinguishes_relocated_projects(self):
        actual = self.powershell("@("
            "(Test-FusionServiceOwner -Health @{version='0.1.0';project_root='C:/Fusion Twin'} -ProjectRoot 'C:\\Fusion Twin'),"
            "(Test-FusionServiceOwner -Health @{version='0.1.0';project_root='C:/Other Twin'} -ProjectRoot 'C:\\Fusion Twin'),"
            "(Test-FusionServiceOwner -Health @{version='0.1.0'} -ProjectRoot 'C:\\Fusion Twin')"
            ") | ConvertTo-Json")
        self.assertEqual(actual, [True, False, False])

    def test_kit_identity_requires_the_exact_app_path(self):
        actual = self.powershell("$root='C:\\Fusion Twin'; @("
            "(Test-FusionKitOwner -Process @{Name='kit.exe';CommandLine='kit.exe \"C:/Fusion Twin/kit/apps/fusion_twin.kit\" --no-window'} -ProjectRoot $root),"
            "(Test-FusionKitOwner -Process @{Name='kit.exe';CommandLine='kit.exe \"C:/Other Twin/kit/apps/fusion_twin.kit\"'} -ProjectRoot $root),"
            "(Test-FusionKitOwner -Process @{Name='kit.exe';CommandLine='kit.exe \"C:/Fusion Twin/kit/apps/fusion_twin.kit.other\"'} -ProjectRoot $root)"
            ") | ConvertTo-Json")
        self.assertEqual(actual, [True, False, False])

    def test_relative_runtime_paths_resolve_from_project_not_shell_directory(self):
        with tempfile.TemporaryDirectory(prefix="Fusion Runtime ") as directory:
            root = Path(directory)
            (root / "python.exe").touch()
            (root / "kit.exe").touch()
            (root / "Extensions").mkdir()
            (root / "runtime.local.json").write_text(json.dumps({"python": "python.exe", "kit_executable": "kit.exe",
                                                               "extension_folders": ["Extensions"]}))
            escaped = str(root).replace("'", "''")
            actual = self.powershell("$env:FUSION_PYTHON=$null; $env:FUSION_KIT_EXE=$null; $env:FUSION_EXT_FOLDERS=$null; "
                                     f"Resolve-FusionRuntime -ProjectRoot '{escaped}' | ConvertTo-Json")
            self.assertEqual(Path(actual["Python"]), root / "python.exe")
            self.assertEqual(Path(actual["Kit"]), root / "kit.exe")
            self.assertEqual([Path(p) for p in actual["ExtensionFolders"]], [root / "Extensions"])

    def test_launch_keeps_explicit_python_and_quotes_paths_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="Fusion Launch ") as directory:
            root = Path(directory)
            (root / "tools").mkdir()
            for name in ("runtime.ps1", "launch_kit.ps1"):
                shutil.copy2(ROOT / "tools" / name, root / "tools" / name)
            for name in ("python.exe", "kit.exe"):
                (root / name).touch()
            (root / "Extensions Folder").mkdir()
            (root / "runtime.local.json").write_text(json.dumps({"python": "missing-python.exe", "kit_executable": "kit.exe",
                                                               "extension_folders": ["Extensions Folder"]}))
            escaped = str(root).replace("'", "''")
            actual = self.powershell("$env:FUSION_PYTHON=$null; $env:FUSION_KIT_EXE=$null; $env:FUSION_EXT_FOLDERS=$null; "
                f"$testRoot='{escaped}'; function Start-Process {{ param($FilePath,$ArgumentList,$WorkingDirectory,$WindowStyle,[switch]$PassThru,$RedirectStandardOutput,$RedirectStandardError); "
                "@{executable=$FilePath;args=$ArgumentList;working_directory=$WorkingDirectory} | ConvertTo-Json | "
                "Set-Content -LiteralPath (Join-Path $testRoot 'args.json') -Encoding UTF8; [pscustomobject]@{Id=987654} }; "
                "& (Join-Path $testRoot 'tools/launch_kit.ps1') -PythonPath (Join-Path $testRoot 'python.exe') -Port 8766 | Out-Null; "
                "Get-Content -LiteralPath (Join-Path $testRoot 'args.json') -Raw")
            self.assertEqual(actual["working_directory"], str(root))
            self.assertEqual(actual["args"][0], '"' + str(root / "kit/apps/fusion_twin.kit") + '"')
            self.assertIn('"--/fusion/serverUrl=http://127.0.0.1:8766"', actual["args"])
            self.assertIn('"' + str(root / "Extensions Folder") + '"', actual["args"])

    def test_live_server_blocks_other_port_but_dead_or_reused_pid_does_not(self):
        with tempfile.TemporaryDirectory(prefix="Fusion Port ") as directory:
            root = Path(directory)
            (root / "runtime").mkdir()
            escaped = str(root).replace("'", "''")
            actual = self.powershell(f"$testRoot='{escaped}'; " + r"""
                $stamp = [datetime]'2026-10-12T00:00:00Z'
                $testProcess = [pscustomobject]@{ProcessId=123; CreationDate=$stamp;
                    CommandLine='python.exe -m fusion_twin.server --port 8765'}
                @{project_root=$testRoot;pid=123;created_ticks=$stamp.ToUniversalTime().Ticks} |
                    ConvertTo-Json | Set-Content (Join-Path $testRoot 'runtime/server.identity.json')
                Set-Content (Join-Path $testRoot 'runtime/server.pid') '123'
                function Get-CimInstance { param($ClassName,$Filter,$ErrorAction); $testProcess }
                function Invoke-RestMethod { throw 'Offline service' }
                function Check-Port($Port) {
                    try { Assert-FusionProjectPort -ProjectRoot $testRoot -Port $Port; 'allowed' }
                    catch { $_.Exception.Message }
                }
                $result = @{same=Check-Port 8765; different=Check-Port 8766}
                $testProcess.CreationDate = $stamp.AddSeconds(1)
                $result.reused = Check-Port 8766
                $testProcess.CommandLine = 'python.exe -m another_service --port 8765'
                $result.unrelated = Check-Port 8766
                $testProcess = $null
                $result.dead = Check-Port 8766
                $result | ConvertTo-Json
            """)
            self.assertEqual(actual["same"], "allowed")
            self.assertIn("on port 8765", actual["different"])
            self.assertIn("on port 8766", actual["different"])
            self.assertEqual([actual[name] for name in ("reused", "unrelated", "dead")], ["allowed"] * 3)

    def test_health_verifies_legacy_pid_and_ignores_another_project(self):
        with tempfile.TemporaryDirectory(prefix="Fusion Health ") as directory:
            root = Path(directory)
            (root / "runtime").mkdir()
            (root / "runtime/server.pid").write_text("123")
            escaped = str(root).replace("'", "''")
            actual = self.powershell(f"$testRoot='{escaped}'; " + r"""
                $testHealth = @{version='0.1.0';project_root=$testRoot;pid=123}
                function Get-CimInstance { param($ClassName,$Filter,$ErrorAction)
                    [pscustomobject]@{ProcessId=123;CommandLine='python.exe -m fusion_twin.server --port=8765'} }
                function Invoke-RestMethod { param($Uri,$TimeoutSec); $testHealth }
                function Check-Port {
                    try { Assert-FusionProjectPort -ProjectRoot $testRoot -Port 8766; 'allowed' }
                    catch { $_.Exception.Message }
                }
                $result = @{owned=Check-Port}
                $testHealth.project_root = 'C:/Other Fusion Twin'
                $result.relocated = Check-Port
                $testHealth.project_root = $testRoot
                $testHealth.pid = 456
                $result.otherPid = Check-Port
                $result | ConvertTo-Json
            """)
            self.assertIn("on port 8765", actual["owned"])
            self.assertEqual(actual["relocated"], "allowed")
            self.assertEqual(actual["otherPid"], "allowed")

    def test_existing_kit_checks_server_url_and_exact_project(self):
        with tempfile.TemporaryDirectory(prefix="Fusion Kit Port ") as directory:
            root = Path(directory)
            (root / "runtime").mkdir()
            (root / "runtime/kit.pid").write_text("456")
            escaped = str(root).replace("'", "''")
            actual = self.powershell(f"$testRoot='{escaped}'; " + r"""
                $appFile = Join-Path $testRoot 'kit/apps/fusion_twin.kit'
                $testProcess = [pscustomobject]@{Name='kit.exe';
                    CommandLine=('kit.exe "' + $appFile + '" "--/fusion/serverUrl=http://127.0.0.1:8765"')}
                function Get-CimInstance { param($ClassName,$Filter,$ErrorAction); $testProcess }
                function Check-Port($Port) {
                    try { Assert-FusionProjectPort -ProjectRoot $testRoot -Port $Port; 'allowed' }
                    catch { $_.Exception.Message }
                }
                $result = @{same=Check-Port 8765; different=Check-Port 8766}
                $testProcess.CommandLine = 'kit.exe "' + $appFile + '" --/fusion/serverUrl=http://127.0.0.1:8766'
                $result.customPort = Check-Port 8766
                $testProcess.CommandLine = 'kit.exe "C:/Other Twin/kit/apps/fusion_twin.kit" --/fusion/serverUrl=http://127.0.0.1:8765'
                $result.relocated = Check-Port 8766
                $testProcess.CommandLine = 'kit.exe "' + $appFile + '"'
                $result.legacyDefault = Check-Port 8766
                $testProcess = $null
                $result.dead = Check-Port 8766
                $result | ConvertTo-Json
            """)
            self.assertEqual(actual["same"], "allowed")
            self.assertIn("targets port 8765", actual["different"])
            self.assertIn("port 8766", actual["different"])
            self.assertEqual([actual[name] for name in ("customPort", "relocated", "dead")], ["allowed"] * 3)
            self.assertIn("targets port 8765", actual["legacyDefault"])

    def test_both_entrypoints_reject_conflict_before_launch_or_runtime_writes(self):
        with tempfile.TemporaryDirectory(prefix="Fusion Entry Port ") as directory:
            root = Path(directory)
            (root / "runtime").mkdir()
            (root / "tools").mkdir()
            for name in ("runtime.ps1", "launch_kit.ps1"):
                shutil.copy2(ROOT / "tools" / name, root / "tools" / name)
            shutil.copy2(ROOT / "start-demo.ps1", root / "start-demo.ps1")
            (root / "runtime/renderer.json").write_text("unchanged")
            escaped = str(root).replace("'", "''")
            actual = self.powershell(f"$testRoot='{escaped}'; " + r"""
                $stamp = [datetime]'2026-10-12T00:00:00Z'
                @{project_root=$testRoot;pid=123;created_ticks=$stamp.ToUniversalTime().Ticks} |
                    ConvertTo-Json | Set-Content (Join-Path $testRoot 'runtime/server.identity.json')
                function Get-CimInstance { param($ClassName,$Filter,$ErrorAction)
                    [pscustomobject]@{ProcessId=123;CreationDate=$stamp;
                        CommandLine='python.exe -m fusion_twin.server --port 8765'} }
                function Start-Process { throw 'Unexpected launch' }
                $result = @{}
                try { & (Join-Path $testRoot 'start-demo.ps1') -Port 8766 -ServerOnly -NoBrowser | Out-Null;
                    $result.start = 'unexpected success' } catch { $result.start = $_.Exception.Message }
                try { & (Join-Path $testRoot 'tools/launch_kit.ps1') -Port 8766 | Out-Null;
                    $result.kit = 'unexpected success' } catch { $result.kit = $_.Exception.Message }
                $result.renderer = [string](Get-Content (Join-Path $testRoot 'runtime/renderer.json') -Raw)
                $result | ConvertTo-Json
            """)
            self.assertIn("on port 8765", actual["start"])
            self.assertIn("on port 8765", actual["kit"])
            self.assertEqual(actual["renderer"], "unchanged")


if __name__ == "__main__":
    unittest.main()
