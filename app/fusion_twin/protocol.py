"""Transport-independent command and immutable-field protocol."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import time
import uuid
from pathlib import Path


TERMINAL = {"completed", "failed", "cancelled"}
ACTION_BINDINGS = {"request_id", "renderer_epoch", "server_epoch", "topology_key", "interaction_key"}


def interaction_key(state):
    """Geometry/view identity, independent of selection, UI text and thermal values."""
    keys = ("design", "equilibrium", "view", "mode", "cutaway", "explode", "opacity", "visible", "fieldLines")
    encoded = json.dumps({key: state.get(key) for key in keys}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ProtocolError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class TerminalStore:
    """Small durable completion records; memory retention never permits UUID replay."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path(self, request_id):
        name = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
        return self.directory / (name + ".json")

    def get(self, request_id):
        path = self.path(request_id)
        if not path.exists():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["request_id"] != request_id or record["status"] not in TERMINAL:
            raise ValueError("Invalid durable command completion")
        return record

    def put(self, record):
        path = self.path(record["request_id"])
        if path.exists():
            return
        fd, temporary = tempfile.mkstemp(prefix=".completion-", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(record, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)


class CommandQueue:
    def __init__(self, saved=(), capacity=128, retention=256, terminal_directory=None):
        self.epoch = uuid.uuid4().hex
        self.capacity = capacity
        self.retention = retention
        self.terminals = TerminalStore(terminal_directory) if terminal_directory else None
        self.records = {record["request_id"]: copy.deepcopy(record) for record in saved}
        self.seq = max((record["seq"] for record in self.records.values()), default=0)
        self.renderer_epoch = None
        for request_id, record in self.records.items():
            durable = self.terminals.get(request_id) if self.terminals else None
            if durable:
                self.records[request_id] = durable
            elif record["status"] not in TERMINAL:
                self._finish(record, "cancelled", error="server_restarted")
            elif self.terminals:
                self.terminals.put(record)
        self._trim()

    def _finish(self, record, status, result=None, error=None):
        finished = {**record, "status": status, "completed_at": time.time()}
        if result is not None:
            finished["result"] = copy.deepcopy(result)
        if error:
            finished["error"] = error
        # The producer may drop its ACK only after this record is durable.
        if self.terminals:
            self.terminals.put(finished)
        record.update(finished)

    def _trim(self):
        terminal = [record for record in self.records.values() if record["status"] in TERMINAL]
        for record in sorted(terminal, key=lambda item: item["seq"])[:-self.retention]:
            self.records.pop(record["request_id"], None)

    @property
    def ack_seq(self):
        pending = [record["seq"] for record in self.records.values() if record["status"] not in TERMINAL]
        return min(pending) - 1 if pending else self.seq

    def active(self):
        return [copy.deepcopy(record) for record in sorted(self.records.values(), key=lambda item: item["seq"]) if record["status"] not in TERMINAL]

    def saved(self):
        return copy.deepcopy(list(self.records.values()))

    def get(self, request_id):
        record = self.records.get(request_id)
        if record is None and self.terminals:
            record = self.terminals.get(request_id)
        if record is None:
            raise ProtocolError("Unknown request_id", 404)
        return copy.deepcopy(record)

    def retry(self, action):
        request_id = action.get("request_id")
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise ProtocolError("Invalid request_id")
        try:
            record = self.get(request_id)
        except ProtocolError as exc:
            if exc.status == 404:
                return None
            raise
        payload = {key: value for key, value in action.items() if key not in ACTION_BINDINGS}
        previous = {key: value for key, value in record["action"].items() if key not in ACTION_BINDINGS}
        if previous != payload:
            raise ProtocolError("request_id already identifies a different action", 409)
        return record

    def submit(self, action, renderer, context=None):
        request_id = action.get("request_id") or uuid.uuid4().hex
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise ProtocolError("Invalid request_id")
        payload = {key: value for key, value in action.items() if key not in ACTION_BINDINGS}
        retry = self.retry({**action, "request_id": request_id})
        if retry is not None:
            return retry
        epoch = renderer.get("renderer_epoch")
        if not renderer.get("ready") or not epoch:
            raise ProtocolError("Renderer session is not ready", 503)
        if action.get("renderer_epoch", epoch) != epoch:
            raise ProtocolError("Renderer session changed; retry with the current session", 409)
        if action.get("server_epoch", self.epoch) != self.epoch:
            raise ProtocolError("Server session changed", 409)
        if len(self.active()) >= self.capacity:
            raise ProtocolError("Command queue is full", 429)
        self.seq += 1
        record = {"request_id": request_id, "server_epoch": self.epoch, "renderer_epoch": epoch,
                  "seq": self.seq, "status": "pending", "accepted_at": time.time(), "action": payload,
                  "context": copy.deepcopy(context or {})}
        self.records[request_id] = record
        return copy.deepcopy(record)

    def absorb(self, renderer):
        epoch = renderer.get("renderer_epoch")
        if not epoch:
            return False
        changed = False
        if epoch != self.renderer_epoch:
            for record in self.records.values():
                if record["status"] not in TERMINAL and record["renderer_epoch"] != epoch:
                    self._finish(record, "cancelled", error="renderer_restarted")
                    changed = True
            self.renderer_epoch = epoch
        if renderer.get("server_epoch") != self.epoch:
            return changed
        current = renderer.get("current_command") or {}
        for ack in [current, *renderer.get("command_acks", [])]:
            record = self.records.get(ack.get("request_id"))
            if not record or record["status"] in TERMINAL:
                continue
            if (ack.get("seq"), ack.get("server_epoch"), ack.get("renderer_epoch")) != (record["seq"], self.epoch, record["renderer_epoch"]):
                continue
            status = ack.get("status")
            if status in TERMINAL:
                self._finish(record, status, ack.get("result"), ack.get("error"))
                changed = True
            elif status == "running" and record["status"] == "pending":
                record.update(status="running", started_at=ack.get("started_at", time.time()))
                changed = True
        self._trim()
        return changed


class CommandConsumer:
    """Single in-flight operation; retain every completion until its watermark is acknowledged."""
    def __init__(self, renderer_epoch=None):
        self.renderer_epoch = renderer_epoch or uuid.uuid4().hex
        self.server_epoch = None
        self.acks = {}
        self.current = None

    def synchronize(self, snapshot):
        epoch = snapshot.get("server_epoch")
        changed = epoch != self.server_epoch
        if changed:
            self.server_epoch = epoch
            self.acks.clear()
            self.current = None
        watermark = snapshot.get("command_ack_seq", 0)
        self.acks = {key: ack for key, ack in self.acks.items() if ack["seq"] > watermark}
        return changed

    def next(self, snapshot):
        if self.current or not self.server_epoch:
            return None
        for command in sorted(snapshot.get("commands", []), key=lambda item: item["seq"]):
            if (command["server_epoch"], command["renderer_epoch"]) != (self.server_epoch, self.renderer_epoch):
                continue
            if command["seq"] <= snapshot.get("command_ack_seq", 0) or command["request_id"] in self.acks:
                continue
            self.current = {**copy.deepcopy(command), "status": "running", "started_at": time.time()}
            return copy.deepcopy(command)
        return None

    def finish(self, command, status="completed", result=None, error=None):
        if command["server_epoch"] != self.server_epoch:
            return
        ack = {key: command[key] for key in ("request_id", "seq", "server_epoch", "renderer_epoch")}
        ack.update(status=status, completed_at=time.time())
        if result is not None:
            ack["result"] = copy.deepcopy(result)
        if error:
            ack["error"] = error
        self.acks[command["request_id"]] = ack
        if self.current and self.current["request_id"] == command["request_id"]:
            self.current = None


def load_field_packet(runtime: Path, reference: dict):
    """Read exactly the immutable file named by the snapshot and validate identity."""
    import numpy as np

    if reference.get("schema_version") not in {1, 2}:
        raise ValueError("Unsupported field packet schema")
    path = (runtime / reference["path"]).resolve()
    if not path.is_relative_to(runtime.resolve()) or not path.is_file():
        raise ValueError("Invalid field packet path")
    with np.load(path, allow_pickle=False) as packet:
        for member, value in (("field_key", reference["key"]), ("field_revision", reference["revision"]),
                              ("topology_key", reference["topology_key"]), ("equilibrium_key", reference["equilibrium_key"]),
                              ("schema_version", reference["schema_version"])):
            if packet[member].item() != value:
                raise ValueError(f"Field packet identity mismatch: {member}")
        data = {key: packet[key] for key in packet.files}
    points, faces = data["surface_points"], data["surface_triangles"]
    if points.ndim != 2 or points.shape[1] != 3 or faces.ndim != 2 or faces.shape[1] != 3:
        raise ValueError("Invalid surface topology shape")
    if not np.issubdtype(faces.dtype, np.integer) or (faces.size and (faces.min() < 0 or faces.max() >= len(points))):
        raise ValueError("Surface triangle index outside point array")
    for key in ("temperature_rgb", "heatflux_rgb"):
        if data[key].shape != points.shape:
            raise ValueError(f"Field size mismatch: {key}")
    if reference["schema_version"] >= 2:
        for key in ("delta_temperature_rgb", "delta_heatflux_rgb", "surface_normals"):
            if data[key].shape != points.shape or not np.isfinite(data[key]).all():
                raise ValueError(f"Field size or values mismatch: {key}")
        if data["surface_triangle_component"].shape != (len(faces),):
            raise ValueError("Triangle component size mismatch")
        slice_points, slice_faces = data["slice_points"], data["slice_triangles"]
        if slice_points.ndim != 2 or slice_points.shape[1] != 3 or data["slice_rgb"].shape != slice_points.shape:
            raise ValueError("Invalid slice point/color shape")
        if slice_faces.ndim != 2 or slice_faces.shape[1] != 3 or (slice_faces.size and (slice_faces.min() < 0 or slice_faces.max() >= len(slice_points))):
            raise ValueError("Invalid slice topology")
    if data["magnetic_lines"].ndim != 3 or data["magnetic_lines"].shape[-1] != 3:
        raise ValueError("Invalid magnetic line shape")
    if not np.isfinite(points).all() or any(not np.isfinite(data[key]).all() for key in ("temperature_rgb", "heatflux_rgb", "magnetic_lines")):
        raise ValueError("Field packet contains non-finite values")
    return data
