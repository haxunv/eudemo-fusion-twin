"""Relocate the deliverable to a fresh ASCII directory and audit startup.

Default is a plan only. --execute starts HTTP on 8766; --with-kit additionally
starts Kit and requires every other Fusion Kit to be stopped first. The copied
project and its logs remain as evidence. Only this audit's processes are stopped.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from urllib import request
import uuid


ROOT = Path(__file__).resolve().parents[2]


def powershell_json(code):
    code = "$ProgressPreference='SilentlyContinue'; " + code
    encoded = base64.b64encode(code.encode("utf-16-le")).decode("ascii")
    output = subprocess.check_output(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return json.loads(output.decode("utf-8-sig"))


def quoted(value):
    return "'" + str(value).replace("'", "''") + "'"


def runtime_configuration():
    return powershell_json(
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
        f". {quoted(ROOT / 'tools/runtime.ps1')}; "
        f"Resolve-FusionRuntime -ProjectRoot {quoted(ROOT)} | ConvertTo-Json -Depth 4"
    )


def api(base, route, body=None):
    payload = None if body is None else json.dumps(body).encode()
    req = request.Request(base + route, data=payload, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=20) as response:
        return json.load(response)


def wait(check, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (OSError, ValueError):
            pass
        time.sleep(.2)
    raise AssertionError("Timed out waiting for relocated application")


def renderer_ready(base, mode):
    snapshot = api(base, "/api/state")
    renderer = snapshot["renderer"]
    assert not renderer.get("error"), renderer.get("error")
    assert not renderer.get("volume_error"), renderer.get("volume_error")
    if not (snapshot["state"]["mode"] == mode and renderer.get("ready") and renderer.get("rtwt_ready") and
            renderer.get("applied_revision") == snapshot["revision"] and
            renderer.get("applied_field_key") == snapshot["field_ref"]["key"] and
            renderer.get("rtwt_state", {}).get("mode") == mode):
        return None
    if mode == "volume" and (renderer.get("volume_pending") or
                             renderer.get("applied_volume_field_key") != snapshot["field_ref"]["key"] or
                             renderer.get("volume_mask_angle") != snapshot["state"]["cutaway"]):
        return None
    return snapshot


def capture_native(base, evidence, name):
    # Allow the settled viewport to accumulate before saving a reviewable image.
    time.sleep(2.5)
    snapshot = api(base, "/api/state")
    renderer = snapshot["renderer"]
    capture = api(base, "/api/action", {"type": "capture", "request_id": str(uuid.uuid4()),
        "server_epoch": snapshot["server_epoch"], "renderer_epoch": renderer["renderer_epoch"],
        "topology_key": renderer.get("topology_key"), "interaction_key": renderer.get("interaction_key")})
    def completed():
        item = api(base, "/api/actions/" + capture["request_id"])
        assert item["status"] not in ("failed", "cancelled"), item
        return item if item["status"] == "completed" else None
    result = wait(completed)
    with request.urlopen(base + result["result"]["capture_url"], timeout=20) as response:
        png = response.read()
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", png[16:24]) == (2560, 1440)
    (evidence / name).write_bytes(png)
    return {"path": str(evidence / name), "sha256": hashlib.sha256(png).hexdigest(),
            "mode": snapshot["state"]["mode"], "revision": snapshot["revision"],
            "field_key": snapshot["field_ref"]["key"], "render_mode": renderer["render_mode"]}


def run_script(project, name, arguments, log, environment, *, success=True):
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(project / name), *arguments],
        cwd=project, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
        creationflags=subprocess.CREATE_NO_WINDOW, timeout=150,
    )
    if success:
        assert completed.returncode == 0, f"{name} failed; see startup.log"
    else:
        assert completed.returncode != 0, f"{name} accepted another project's process"


def copied_project(destination, configuration):
    destination.mkdir(parents=True, exist_ok=False)
    ignore = shutil.ignore_patterns("node_modules", "__pycache__", "*.pyc")
    for name in ("app", "assets", "kit", "web", "tools"):
        shutil.copytree(ROOT / name, destination / name, ignore=ignore)
    for name in ("start-demo.ps1", "stop-demo.ps1", "runtime.example.json", "pyproject.toml", "README.md"):
        shutil.copy2(ROOT / name, destination / name)
    config = {"python": configuration["Python"], "kit_executable": configuration["Kit"],
              "extension_folders": configuration["ExtensionFolders"]}
    (destination / "runtime.local.json").write_text(json.dumps(config, indent=2), encoding="utf-8")


def execute(args):
    destination = args.destination or Path(tempfile.gettempdir()) / ("Fusion Twin Portable " + uuid.uuid4().hex[:10])
    destination = destination.resolve()
    assert destination.is_absolute() and destination.as_posix().isascii(), "Choose an absolute ASCII destination"
    assert not destination.exists(), "Destination must be new; existing directories are never overwritten"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    if args.with_kit:
        active = powershell_json("ConvertTo-Json -InputObject @(Get-CimInstance Win32_Process -Filter \"Name = 'kit.exe'\" | "
                                 "Where-Object {$_.CommandLine -like '*fusion_twin.kit*'} | "
                                 "Select-Object ProcessId) -Compress")
        assert not active, "Another Fusion Kit is running; wait for the exclusive GPU test window"
    configuration = runtime_configuration()
    copied_project(destination, configuration)
    evidence = destination / "runtime/qa"
    evidence.mkdir(parents=True)
    report = {"ok": False, "mode": "kit" if args.with_kit else "http_only", "project": str(destination),
              "source": str(ROOT), "port": args.port, "checks": [], "runtime": configuration,
              "processes_stopped": False, "kit_started": False}
    runtime_paths = [str(Path(configuration["Kit"]).parent), *configuration["ExtensionFolders"]]
    scan = "@(" + ",".join(quoted(path) for path in runtime_paths) + ")"
    report["runtime_reparse_points"] = powershell_json(
        f"$links=@(foreach($folder in {scan}) {{Get-Item -LiteralPath $folder | "
        "Where-Object {$_.Attributes -band [IO.FileAttributes]::ReparsePoint}; "
        "Get-ChildItem -LiteralPath $folder -Recurse -Attributes ReparsePoint}); "
        "ConvertTo-Json -InputObject @($links | ForEach-Object {$_.FullName})"
    )
    assert not report["runtime_reparse_points"], "Configured runtime retains filesystem links"
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "FUSION_TWIN_ROOT", "FUSION_PYTHON", "FUSION_KIT_EXE", "FUSION_EXT_FOLDERS"):
        environment.pop(name, None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    base = f"http://127.0.0.1:{args.port}"
    start_args = ["-NoBrowser", "-Port", str(args.port)]
    if not args.with_kit:
        start_args.append("-ServerOnly")
    owned_pid = None
    with (evidence / "startup.log").open("ab") as log:
        try:
            run_script(destination, "start-demo.ps1", start_args, log, environment)
            health = api(base, "/api/status")
            assert Path(health["project_root"]).resolve() == destination
            owned_pid = health["pid"]
            assert int((destination / "runtime/server.pid").read_text().strip()) == owned_pid
            report["server_pid"] = owned_pid
            report["checks"].append("HTTP serves the relocated project and its actual PID")
            report["compute_device"] = health["compute_device"]
            run_script(destination, "start-demo.ps1", start_args, log, environment)
            assert api(base, "/api/status")["pid"] == owned_pid
            report["checks"].append("Repeated startup reuses only the matching project process")
            for route in ("/", "/app.js", "/assets/scene/fusion.usda"):
                with request.urlopen(base + route, timeout=20) as response:
                    assert response.status == 200 and response.read(32), route
            report["checks"].append("UI and USD assets resolve from the relocated directory")
            manifest = api(base, "/api/manifest")
            assert set(manifest["design_components"]) == {"conventional", "longleg"}
            for design in ("longleg", "conventional"):
                snapshot = api(base, "/api/state", {"design": design})
                assert snapshot["state"]["design"] == design
                reference = snapshot["field_ref"]
                assert (destination / "runtime" / reference["path"]).is_file()
            report["checks"].append("Both designs compute and publish fields inside the relocated runtime")
            # A second project with the same server version must not attach to this port.
            rival = destination / "Other Project"
            rival.mkdir()
            shutil.copy2(destination / "start-demo.ps1", rival / "start-demo.ps1")
            shutil.copy2(destination / "runtime.local.json", rival / "runtime.local.json")
            (rival / "tools").mkdir()
            shutil.copy2(destination / "tools/runtime.ps1", rival / "tools/runtime.ps1")
            run_script(rival, "start-demo.ps1", ["-NoBrowser", "-ServerOnly", "-Port", str(args.port)],
                       log, environment, success=False)
            assert api(base, "/api/status")["pid"] == owned_pid
            report["checks"].append("Another project on the same port is rejected without stopping the owner")
            # Copied PID/identity files must not authorize stopping the original project.
            shutil.copy2(destination / "stop-demo.ps1", rival / "stop-demo.ps1")
            for name in ("server.pid", "server.identity.json"):
                shutil.copy2(destination / "runtime" / name, rival / "runtime" / name)
            run_script(rival, "stop-demo.ps1", [], log, environment, success=False)
            assert api(base, "/api/status")["pid"] == owned_pid
            report["checks"].append("Copied PID files cannot stop the original project")
            if args.with_kit:
                report["kit_started"] = True
                report["kit_pid"] = int((destination / "runtime/kit.pid").read_text().strip())
                api(base, "/api/state", {"mode": "assembly"})
                snapshot = wait(lambda: renderer_ready(base, "assembly"), 180)
                assert snapshot["renderer"]["render_mode"] == "RealTimePathTracing"
                assert snapshot["renderer"]["rtwt_control_count"] == 20
                report["captures"] = [capture_native(base, evidence, "relocated-assembly.png")]
                report["checks"].append("Relocated CAD and RTWT load with RT2 and a QHD capture")
                api(base, "/api/state", {"mode": "volume"})
                snapshot = wait(lambda: renderer_ready(base, "volume"), 180)
                renderer = snapshot["renderer"]
                assert renderer["render_mode"] == "RealTimePathTracing", renderer["render_mode"]
                assert renderer["rt2_enabled"] and "RTX Real-Time 2.0" in renderer["engine"]
                assert renderer["sampling_strategy"] == "temporal_reconstruction"
                assert renderer["index_depth_mode"] == 3
                assert renderer["index_native_volume"] and renderer["index_composite"]
                assert renderer["volume_roundtrip"] == "exact" and renderer["volume_units"] == "keV"
                assert renderer["volume_grid"] == [128, 128, 112]
                assert renderer["index_source_field"] == "Temperature" and "colors" in renderer["index_fields"]
                report["volume"] = {key: renderer[key] for key in (
                    "rtwt_ready", "rtwt_control_count", "applied_volume_field_key", "applied_volume_key",
                    "volume_roundtrip", "volume_units", "volume_grid", "volume_range_keV",
                    "index_native_volume", "index_fields", "index_depth_mode", "render_mode", "rt2_enabled", "sampling_strategy")}
                report["captures"].append(capture_native(base, evidence, "relocated-volume.png"))
                report["checks"].append("IndeX adopts the current field; NanoVDB round-trip is exact; volume uses real-time RTX depth mode 3")
                api(base, "/api/state", {"mode": "assembly"})
                restored = wait(lambda: renderer_ready(base, "assembly"))
                assert restored["renderer"]["render_mode"] == "RealTimePathTracing"
                assert restored["renderer"]["sampling_strategy"] == "temporal_reconstruction"
                report["restored_mode"] = restored["renderer"]["render_mode"]
                report["captures"].append(capture_native(base, evidence, "relocated-assembly-restored.png"))
                report["checks"].append("Returning to assembly keeps RT2 and matching RTWT state")
            else:
                assert not (destination / "runtime/kit.pid").exists()
                report["checks"].append("HTTP-only startup creates no Kit process")
            report["ok"] = True
        except BaseException as exc:
            report["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            try:
                if owned_pid or (destination / "runtime/server.identity.json").exists():
                    stopped_at = time.monotonic()
                    run_script(destination, "stop-demo.ps1", [], log, environment)
                    with socket.socket() as probe:
                        assert probe.connect_ex(("127.0.0.1", args.port)) != 0, "Relocated service did not exit"
                    process_ids = [report.get("server_pid"), report.get("kit_pid")]
                    process_ids = [str(pid) for pid in process_ids if pid]
                    remaining = powershell_json("ConvertTo-Json -InputObject @(Get-CimInstance Win32_Process -Filter " +
                                                quoted(" OR ".join("ProcessId=" + pid for pid in process_ids)) +
                                                " | Select-Object ProcessId,Name) -Compress")
                    assert not remaining, remaining
                    report["processes_stopped"] = True
                    report["stop_seconds"] = round(time.monotonic() - stopped_at, 3)
            except BaseException as exc:
                report["cleanup_error"] = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                report["ok"] = report["ok"] and report["processes_stopped"]
                serialized = json.dumps(report, indent=2, ensure_ascii=False)
                (evidence / "portability.json").write_text(serialized, encoding="utf-8")
                source_evidence = ROOT / "runtime/qa"
                source_evidence.mkdir(parents=True, exist_ok=True)
                (source_evidence / ("portability-kit.json" if args.with_kit else "portability-http.json")).write_text(serialized, encoding="utf-8")
                print(serialized, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--with-kit", action="store_true")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    if not args.execute:
        print("Plan: copy app/assets/kit/web/tools to a new ASCII directory, resolve configured runtimes, "
              "start on port 8766, verify project ownership and both designs, then stop only the copied project. "
              "Use --execute for HTTP only; add --with-kit only during the exclusive GPU test window.")
        return
    execute(args)


if __name__ == "__main__":
    main()
