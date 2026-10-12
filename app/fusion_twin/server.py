"""Local web application and serialized state/compute coordinator."""

from __future__ import annotations

import argparse
import copy
import json
import math
import mimetypes
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .compute import FieldEngine, SCENARIOS, atomic_json
from .field_cache import FieldCache
from .protocol import CommandQueue, ProtocolError, interaction_key

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_STATE = {
    "language": "zh", "view": "overview", "tab": "explore", "mode": "volume",
    "design": "conventional", "equilibrium": "sof", "heating": 50.0, "neon": False,
    "scenario": "nominal", "power": 2000.0, "flow": 1.0, "inlet": 300.0,
    "phase": 1.0, "cutaway": 80, "explode": 0.0, "opacity": 1.0,
    "heatScale": "log", "volumeStyle": "plasma", "lineMotion": True,
    "visible": {}, "selected": "", "fieldLines": True, "orbit": False, "playing": False,
}
ENUMS = {
    "design": {"conventional", "longleg"}, "equilibrium": {"reference", "rampup", "sof", "eof", "rampdown"},
    "language": {"zh", "en"}, "view": {"overview", "front", "top", "section", "divertor"},
    "tab": {"explore", "compare", "engineering"}, "mode": {"assembly", "temperature", "heatflux", "delta_temperature", "delta_heatflux", "magnetic", "slice", "volume"},
    "heatScale": {"log", "linear"}, "volumeStyle": {"plasma", "temperature"},
    "scenario": set(SCENARIOS),
}
BOUNDS = {"power": (500, 2600), "heating": (20, 65), "flow": (0.4, 1.4), "inlet": (200, 400), "phase": (0, 1), "cutaway": (0, 180), "explode": (0, 1), "opacity": (0.1, 1)}
BOOLEANS = {"fieldLines", "lineMotion", "neon", "orbit", "playing"}


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
            if key == "heating" and value not in (20, 35, 50, 65):
                raise ValueError("heating must be one of 20, 35, 50, 65 MW")
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
    def __init__(self, root: Path, *, engine_factory=None, start_background=True):
        self.root = root
        self.runtime = root / "runtime"
        self.runtime.mkdir(exist_ok=True)
        self.manifest = json.loads((root / "assets/manifest.json").read_text(encoding="utf-8"))
        self.component_ids = {c["id"] for c in self.manifest["components"]}
        self.state = copy.deepcopy(DEFAULT_STATE)
        self.state["visible"] = {c["id"]: c.get("default_visible", True) for c in self.manifest["components"]}
        self.revision = 1
        saved = {}
        saved_path = self.runtime / "state.json"
        if saved_path.exists():
            saved = json.loads(saved_path.read_text(encoding="utf-8"))
            self.state.update(validate_patch(saved["state"], self.component_ids))
            self.state.update(playing=False, orbit=False)
            self.revision = int(saved["revision"]) + 1
        self.lock = threading.RLock()
        self.compute_lock = threading.Lock()
        self._renderer_snapshot = None
        self.commands = CommandQueue(saved.get("action_records", []), terminal_directory=self.runtime / "commands/completed")
        self.field_cache = FieldCache(self.runtime, saved.get("field_publications", []))
        self.engine = (engine_factory or FieldEngine)(root)
        self.result = self.engine.compute(self.state, self.revision)
        self._publish()
        self.stop = threading.Event()
        if start_background:
            threading.Thread(target=self._playback, daemon=True, name="scenario-playback").start()

    def _publish(self):
        self.publication_pending = True
        self.field_cache.record(self.result.get("field_ref"), self.revision)
        atomic_json(self.runtime / "state.json", {
            "server_epoch": self.commands.epoch, "revision": self.revision,
            "state": self.state, "result": self.result, "field_ref": self.result.get("field_ref"),
            "commands": self.commands.active(), "command_ack_seq": self.commands.ack_seq,
            "action_records": self.commands.saved(), "published_at": time.time(),
            "field_publications": self.field_cache.saved(),
        })
        self.publication_pending = False

    def collect_fields(self):
        # Never collect concurrently with the single field writer or its publication.
        if not self.compute_lock.acquire(blocking=False):
            return {"deleted": [], "bytes": 0}
        try:
            with self.lock:
                renderer = self.renderer()
                self._sync_commands(renderer)
                result = self.field_cache.collect(
                    current_key=(self.result.get("field_ref") or {}).get("key"),
                    server_epoch=self.commands.epoch, renderer=renderer,
                    extra_protected=(record.get("context", {}).get("field_key") for record in self.commands.active()),
                )
                if result["deleted"]:
                    self._publish()
                return result
        finally:
            self.compute_lock.release()

    def _sync_commands(self, renderer):
        if self.commands.absorb(renderer) or self.publication_pending:
            self._publish()

    def renderer(self):
        file = self.runtime / "renderer.json"
        with self.lock:
            read_error = None
            try:
                with file.open(encoding="utf-8") as stream:
                    payload = json.load(stream)
                    modified = os.fstat(stream.fileno()).st_mtime
            except FileNotFoundError:
                self._renderer_snapshot = None
                return {"ready": False, "status": "starting"}
            except (OSError, json.JSONDecodeError) as exc:
                read_error = type(exc).__name__
                if self._renderer_snapshot is None:
                    return {"ready": False, "status": "starting", "state_read_reused": False,
                            "read_error": read_error}
            else:
                self._renderer_snapshot = (payload, modified)
            # Preserve the successful file's timestamp and keep callers out of the cache.
            payload, modified = self._renderer_snapshot
            payload = copy.deepcopy(payload)
            age = time.time() - modified
            payload["heartbeat_age_s"] = round(age, 2)
            payload["state_read_reused"] = read_error is not None
            if read_error:
                payload["read_error"] = read_error
            if age > 15:
                payload["ready"] = False
                payload["status"] = "disconnected"
            elif payload.get("status") == "starting":
                payload["ready"] = False
            return payload

    def snapshot(self):
        with self.lock:
            renderer = self.renderer()
            self._sync_commands(renderer)
            return {"server_epoch": self.commands.epoch, "revision": self.revision,
                    "state": copy.deepcopy(self.state), "result": self.result,
                    "field_ref": self.result.get("field_ref"), "renderer": renderer,
                    "actions": self.commands.saved()[-32:]}

    def patch(self, patch):
        clean = validate_patch(patch, self.component_ids)
        with self.compute_lock:
            with self.lock:
                state = copy.deepcopy(self.state)
                revision = self.revision + 1
            if "scenario" in clean and clean["scenario"] != state["scenario"]:
                state.update({k: v for k, v in SCENARIOS[clean["scenario"]].items() if k != "hotspot"})
            if "visible" in clean:
                clean["visible"] = {**state["visible"], **clean["visible"]}
            if any(clean.get(key, state[key]) != state[key] for key in ("design", "equilibrium")):
                state["selected"] = ""
            state.update(clean)
            result = self.engine.compute(state, revision)
            with self.lock:
                self.state, self.revision, self.result = state, revision, result
                self._publish()
                return self.snapshot()

    def action(self, action):
        if not isinstance(action, dict) or action.get("type") not in {"capture", "pick", "measure", "measure_start", "measure_clear", "reset_camera"}:
            raise ValueError("Unknown action")
        has_coordinates = "x" in action or "y" in action
        if action["type"] == "pick" and not ("x" in action and "y" in action):
            raise ValueError("Pick requires both x and y")
        if has_coordinates and (action["type"] not in {"pick", "measure"} or not ("x" in action and "y" in action)):
            raise ValueError("Coordinates require a pick/measure action with both x and y")
        for key in ("x", "y"):
            if key in action and (isinstance(action[key], bool) or not isinstance(action[key], (int, float)) or not math.isfinite(action[key]) or not 0 <= action[key] <= 1):
                raise ValueError("Pick coordinates must be normalized")
        if "view" in action and (not isinstance(action["view"], str) or action["view"] not in ENUMS["view"]):
            raise ValueError("Unknown camera view")
        with self.lock:
            renderer = self.renderer()
            self._sync_commands(renderer)
            record = self.commands.retry(action)
            if record is None:
                for key in ("server_epoch", "renderer_epoch"):
                    if not isinstance(action.get(key), str) or not action[key]:
                        raise ProtocolError(f"Missing {key}")
                if not renderer.get("ready") or not renderer.get("renderer_epoch"):
                    raise ProtocolError("Renderer session is not ready", 503)
                if action["server_epoch"] != self.commands.epoch or renderer.get("server_epoch") != self.commands.epoch:
                    raise ProtocolError("Server session changed; wait for renderer synchronization", 409)
                if action["renderer_epoch"] != renderer.get("renderer_epoch"):
                    raise ProtocolError("Renderer session changed", 409)
                reference = self.result.get("field_ref") or {}
                context = {key: self.state[key] for key in ("design", "equilibrium")}
                context.update(topology_key=reference.get("topology_key"), field_key=reference.get("key"))
                if has_coordinates:
                    geometry_key = interaction_key(self.state)
                    if not action.get("topology_key") or action["topology_key"] != reference.get("topology_key") or action["topology_key"] != renderer.get("topology_key"):
                        raise ProtocolError("Scene topology changed; retry after synchronization", 409)
                    if renderer.get("interaction_key") != geometry_key or action.get("interaction_key") != geometry_key:
                        raise ProtocolError("Scene view changed; retry after synchronization", 409)
                    if self.state["mode"] == "volume" and renderer.get("applied_volume_field_key") != reference.get("key"):
                        raise ProtocolError("Volume field is still synchronizing", 409)
                    context["interaction_key"] = geometry_key
                record = self.commands.submit(action, renderer, context)
            # A retry also republishes work if a prior disk write failed before its HTTP response.
            self._publish()
        return {"accepted": True, "queued": record["status"] not in {"completed", "failed", "cancelled"}, "command_seq": record["seq"], **record}

    def action_status(self, request_id):
        with self.lock:
            self._sync_commands(self.renderer())
            return self.commands.get(request_id)

    def _playback(self):
        next_phase = time.monotonic() + 0.5
        next_collection = time.monotonic() + 5.0
        while not self.stop.wait(0.05):
            try:
                with self.lock:
                    self._sync_commands(self.renderer())
                    phase = round((self.state["phase"] + 0.01) % 1.0, 4) if self.state["playing"] else None
                if time.monotonic() >= next_phase:
                    next_phase = time.monotonic() + 0.5
                    if phase is not None:
                        self.patch({"phase": phase})
                if time.monotonic() >= next_collection:
                    next_collection = time.monotonic() + 5.0
                    self.collect_fields()
            except OSError as exc:
                print(f"Background persistence will retry: {type(exc).__name__}", flush=True)
                if self.stop.wait(0.5):
                    return


class FusionHTTPServer(ThreadingHTTPServer):
    # Python's default backlog of five resets burst connections on Windows.
    request_queue_size = 256


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
        if path.startswith("/api/actions/"):
            try:
                return self.send_json(self.app.action_status(path.removeprefix("/api/actions/")))
            except ProtocolError as exc:
                return self.send_json({"error": str(exc)}, exc.status)
        if path == "/api/state":
            return self.send_json(self.app.snapshot())
        if path == "/api/manifest":
            return self.send_json(self.app.manifest)
        if path == "/api/status":
            return self.send_json({"service": "ready", "version": "0.1.0", "project_root": str(self.app.root.resolve()),
                                   "pid": os.getpid(), "renderer": self.app.renderer(),
                                   "compute_device": str(self.app.engine.device), "gpu_name": self.app.engine.device.name})
        if path == "/api/export":
            payload = self.app.snapshot()
            payload["provenance"] = {
                "manifest_source": self.app.manifest["source"],
                "source_record": json.loads((self.app.root / "assets/source/provenance.json").read_text(encoding="utf-8")),
            }
            payload["data_classification"] = "Bluemira concept CAD and equilibrium; synthetic thermal demonstration"
            return self.send_json(payload, attachment=True)
        if path.startswith("/api/captures/"):
            name = path.removeprefix("/api/captures/")
            if not re.fullmatch(r"[0-9a-f]{64}\.png", name):
                return self.send_error(404)
            file = self.app.runtime / "captures" / name
        elif path == "/api/preview.png":
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
        except ProtocolError as exc:
            return self.send_json({"error": str(exc)}, exc.status)
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
    httpd = FusionHTTPServer(("127.0.0.1", args.port), Handler)
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
