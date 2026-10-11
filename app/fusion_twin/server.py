"""Local web application and serialized state/compute coordinator."""

from __future__ import annotations

import argparse
import copy
import json
import math
import mimetypes
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .compute import FieldEngine, SCENARIOS, atomic_json

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_STATE = {
    "language": "zh", "view": "overview", "tab": "explore", "mode": "assembly",
    "scenario": "nominal", "power": 2000.0, "flow": 1.0, "inlet": 300.0,
    "phase": 0.65, "cutaway": 80, "explode": 0.0, "opacity": 1.0,
    "visible": {}, "selected": "", "fieldLines": False, "orbit": False, "playing": False,
}
ENUMS = {
    "language": {"zh", "en"}, "view": {"overview", "front", "top", "section", "divertor"},
    "tab": {"explore", "compare"}, "mode": {"assembly", "temperature", "heatflux", "magnetic", "slice"},
    "scenario": set(SCENARIOS),
}
BOUNDS = {"power": (500, 2600), "flow": (0.4, 1.4), "inlet": (200, 400), "phase": (0, 1), "cutaway": (0, 180), "explode": (0, 1), "opacity": (0.1, 1)}
BOOLEANS = {"fieldLines", "orbit", "playing"}


def validate_patch(patch: dict, component_ids: set[str]) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("State patch must be an object")
    result = {}
    for key, value in patch.items():
        if key in ENUMS:
            if not isinstance(value, str) or value not in ENUMS[key]:
                raise ValueError(f"Invalid {key}")
        elif key in BOUNDS:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"Invalid number: {key}")
            low, high = BOUNDS[key]
            if not low <= value <= high:
                raise ValueError(f"{key} must be in [{low}, {high}]")
            value = float(value)
            if key == "cutaway":
                value = int(round(value / 20)) * 20
        elif key in BOOLEANS:
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be boolean")
        elif key == "selected":
            if value != "" and value not in component_ids:
                raise ValueError("Unknown component")
        elif key == "visible":
            if not isinstance(value, dict) or any(k not in component_ids or not isinstance(v, bool) for k, v in value.items()):
                raise ValueError("Invalid visibility map")
        else:
            raise ValueError(f"Unknown state key: {key}")
        result[key] = value
    return result


class TwinApplication:
    def __init__(self, root: Path):
        self.root = root
        self.runtime = root / "runtime"
        self.runtime.mkdir(exist_ok=True)
        self.manifest = json.loads((root / "assets/manifest.json").read_text(encoding="utf-8"))
        self.component_ids = {c["id"] for c in self.manifest["components"]}
        self.state = copy.deepcopy(DEFAULT_STATE)
        self.state["visible"] = {c["id"]: c.get("default_visible", True) for c in self.manifest["components"]}
        self.revision = 1
        self.command_seq = 0
        saved_path = self.runtime / "state.json"
        if saved_path.exists():
            saved = json.loads(saved_path.read_text(encoding="utf-8"))
            self.state.update(validate_patch(saved["state"], self.component_ids))
            self.state.update(playing=False, orbit=False)
            self.revision = int(saved["revision"]) + 1
            self.command_seq = int(saved.get("command_seq", 0))
        self.command = None
        self.lock = threading.RLock()
        self.engine = FieldEngine(root)
        self.result = self.engine.compute(self.state, self.revision)
        self._publish()
        self.stop = threading.Event()
        threading.Thread(target=self._playback, daemon=True, name="scenario-playback").start()

    def _publish(self):
        atomic_json(self.runtime / "state.json", {"revision": self.revision, "state": self.state, "result": self.result, "command_seq": self.command_seq, "command": self.command})

    def renderer(self):
        file = self.runtime / "renderer.json"
        if not file.exists():
            return {"ready": False, "status": "starting"}
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
            age = time.time() - file.stat().st_mtime
            payload["heartbeat_age_s"] = round(age, 2)
            if age > 15:
                payload["ready"] = False
                payload["status"] = "disconnected"
            return payload
        except (OSError, json.JSONDecodeError):
            return {"ready": False, "status": "starting"}

    def snapshot(self):
        with self.lock:
            return {"revision": self.revision, "state": copy.deepcopy(self.state), "result": self.result, "renderer": self.renderer()}

    def patch(self, patch):
        clean = validate_patch(patch, self.component_ids)
        with self.lock:
            if "scenario" in clean and clean["scenario"] != self.state["scenario"]:
                self.state.update({k: v for k, v in SCENARIOS[clean["scenario"]].items() if k != "hotspot"})
            if "visible" in clean:
                clean["visible"] = {**self.state["visible"], **clean["visible"]}
            self.state.update(clean)
            self.revision += 1
            self.result = self.engine.compute(self.state, self.revision)
            self._publish()
            return self.snapshot()

    def action(self, action):
        if not isinstance(action, dict) or action.get("type") not in {"capture", "pick", "measure", "measure_start", "measure_clear", "reset_camera"}:
            raise ValueError("Unknown action")
        for key in ("x", "y"):
            if key in action and (not isinstance(action[key], (int, float)) or not 0 <= action[key] <= 1):
                raise ValueError("Pick coordinates must be normalized")
        with self.lock:
            self.command_seq += 1
            self.command = action
            self._publish()
        return {"queued": True, "command_seq": self.command_seq}

    def _playback(self):
        while not self.stop.wait(0.5):
            with self.lock:
                if self.state["playing"]:
                    self.patch({"phase": round((self.state["phase"] + 0.01) % 1.0, 4)})


class Handler(BaseHTTPRequestHandler):
    server_version = "FusionTwin/0.1"

    @property
    def app(self) -> TwinApplication:
        return self.server.app

    def log_message(self, format, *args):
        if args and str(args[1]) not in {"200", "204", "304"}:
            super().log_message(format, *args)

    def send_json(self, body, status=200, attachment=False):
        data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if attachment:
            self.send_header("Content-Disposition", 'attachment; filename="fusion-scenario.json"')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/api/state":
            return self.send_json(self.app.snapshot())
        if path == "/api/manifest":
            return self.send_json(self.app.manifest)
        if path == "/api/status":
            return self.send_json({"service": "ready", "version": "0.1.0", "renderer": self.app.renderer(), "compute_device": str(self.app.engine.device), "gpu_name": self.app.engine.device.name})
        if path == "/api/export":
            payload = self.app.snapshot()
            payload["provenance"] = {
                "manifest_source": self.app.manifest["source"],
                "source_record": json.loads((self.app.root / "assets/source/provenance.json").read_text(encoding="utf-8")),
            }
            payload["data_classification"] = "Bluemira concept CAD and equilibrium; synthetic thermal demonstration"
            return self.send_json(payload, attachment=True)
        if path == "/api/preview.png":
            file = self.app.runtime / "preview.png"
        elif path in {"/api/download/cad.zip", "/api/download/usd.zip"}:
            file = self.app.root / "assets/downloads" / Path(path).name
        elif path.startswith("/assets/"):
            base = self.app.root / "assets"
            file = (base / path.removeprefix("/assets/")).resolve()
            if not file.is_relative_to(base):
                return self.send_error(403)
        else:
            base = self.app.root / "web"
            file = (base / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
            if not file.is_relative_to(base):
                return self.send_error(403)
        if not file.is_file():
            return self.send_error(404)
        data = file.read_bytes()
        self.send_response(200)
        content_type = mimetypes.guess_type(str(file))[0] or "application/octet-stream"
        if file.suffix == ".js":
            content_type = "text/javascript"
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        if file.suffix.lower() in {".stp", ".step", ".zip"}:
            self.send_header("Content-Disposition", f'attachment; filename="{file.name}"')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 64000:
                return self.send_json({"error": "Invalid request size"}, 400)
            body = json.loads(self.rfile.read(length))
            if self.path == "/api/state":
                return self.send_json(self.app.patch(body))
            if self.path == "/api/action":
                return self.send_json(self.app.action(body))
            return self.send_json({"error": "Unknown endpoint"}, 404)
        except (ValueError, TypeError) as exc:
            return self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            print(f"Request failed: {type(exc).__name__}: {exc}", flush=True)
            return self.send_json({"error": "Compute request failed; see local server log"}, 500)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    app = TwinApplication(ROOT)
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    httpd.app = app
    (app.runtime / "server.pid").write_text(str(os.getpid()), encoding="ascii")
    print(f"Fusion Twin ready at http://127.0.0.1:{args.port}; compute={app.engine.device}", flush=True)
    try:
        httpd.serve_forever()
    finally:
        app.stop.set()
        httpd.server_close()


if __name__ == "__main__":
    main()
