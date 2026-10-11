"""Coordinated live restart/ACK-loss checks. No browser is opened.

Run only in the integration test window: python -B tools/qa/restart_reliability.py --execute.
Without --execute this prints the operations and exits without contacting the app.
"""

import argparse
import contextlib
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import subprocess
import time
from urllib import error, request
import uuid


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"


class RestartAudit:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.checks = []

    def api(self, route, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = request.Request(self.base + "/api/" + route, data=data,
                              headers={"Content-Type": "application/json"})
        with request.urlopen(req, timeout=15) as response:
            return json.load(response)

    def wait(self, predicate, timeout=90):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                value = predicate()
                if value:
                    return value
            except (OSError, error.URLError, json.JSONDecodeError):
                pass
            time.sleep(.1)
        raise AssertionError("Timed out waiting for application condition")

    def ready(self):
        state = self.api("state")
        renderer = state["renderer"]
        if renderer.get("error"):
            raise AssertionError(renderer["error"])
        return state if (renderer.get("ready") and renderer.get("applied_revision") == state["revision"]
                         and renderer.get("applied_field_key") == state["field_ref"]["key"]) else None

    def complete(self, identifier, expected="completed"):
        def done():
            record = self.api("actions/" + identifier)
            return record if record["status"] in {"completed", "failed", "cancelled"} else None
        record = self.wait(done)
        assert record["status"] == expected, record
        return record

    @staticmethod
    def action_context(state, kind, **values):
        renderer = state["renderer"]
        return {"type": kind, "request_id": str(uuid.uuid4()), "server_epoch": state["server_epoch"],
                "renderer_epoch": renderer["renderer_epoch"], "topology_key": renderer.get("topology_key"),
                "interaction_key": renderer.get("interaction_key"), **values}

    @staticmethod
    def powershell(script, *args):
        # Detached Kit can inherit pipe handles; waiting for PIPE EOF then blocks after PowerShell exits.
        log_path = RUNTIME / "qa/restart-launch.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as log:
            return subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
                                  cwd=ROOT, check=True, stdin=subprocess.DEVNULL, stdout=log, stderr=log)

    @staticmethod
    def verified_pid(kind):
        process_id = int((RUNTIME / f"{kind}.pid").read_text().strip())
        script = f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId = {process_id}'; if($p){{$p.CommandLine}}"
        completed = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script],
                                   check=True, capture_output=True, text=True)
        expected = "fusion_twin.server" if kind == "server" else "fusion_twin.kit"
        if expected not in completed.stdout:
            raise AssertionError(f"PID {process_id} does not identify this app's {kind}")
        return process_id

    def stop(self, kind):
        process_id = self.verified_pid(kind)
        script = (f"$target=Get-Process -Id {process_id} -ErrorAction Stop; "
                  "Stop-Process -InputObject $target -ErrorAction Stop; "
                  "if(-not $target.WaitForExit(30000)){throw 'Application process did not exit'}")
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", script],
                       check=True, capture_output=True, text=True)

    @contextlib.contextmanager
    def suspend_server(self, process_id=None):
        process_id = process_id or self.verified_pid("server")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        native = ctypes.WinDLL("ntdll")
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        native.NtSuspendProcess.argtypes = [wintypes.HANDLE]
        native.NtResumeProcess.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x0800, False, process_id)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        suspended = False
        try:
            if native.NtSuspendProcess(handle) != 0:
                raise RuntimeError("Cannot suspend application service for ACK-loss test")
            suspended = True
            yield
        finally:
            if suspended:
                native.NtResumeProcess(handle)
            kernel.CloseHandle(handle)

    def capture_digest(self, result):
        with request.urlopen(self.base + result["capture_url"], timeout=15) as response:
            return hashlib.sha256(response.read()).hexdigest()

    def ack_loss(self):
        state = self.wait(self.ready)
        process_id = self.verified_pid("server")
        action = self.action_context(state, "capture")
        accepted = self.api("action", action)
        with self.suspend_server(process_id):
            saved = json.loads((RUNTIME / "state.json").read_text(encoding="utf-8"))
            record = next(item for item in saved["action_records"] if item["request_id"] == action["request_id"])
            assert record["status"] in {"pending", "running"}, "Capture completed before service suspension; repeat ACK-loss phase"
            def renderer_ack():
                payload = json.loads((RUNTIME / "renderer.json").read_text(encoding="utf-8"))
                return next((item for item in payload.get("command_acks", []) if item["request_id"] == action["request_id"]), None)
            ack = self.wait(renderer_ack, timeout=15)
            assert ack["status"] == "completed", ack
            time.sleep(.75)
            retained = renderer_ack()
            assert retained and retained["seq"] == accepted["seq"], "Unacknowledged completion was overwritten"
        record = self.complete(action["request_id"])
        digest = self.capture_digest(record["result"])
        retry = self.api("action", action)
        assert retry["seq"] == accepted["seq"] and retry["status"] == "completed"
        assert self.capture_digest(retry["result"]) == digest
        self.checks.append({"name": "ack_loss_recovery", "request_id": action["request_id"], "seq": accepted["seq"], "sha256": digest})

    def kit_restart(self):
        state = self.wait(self.ready)
        old_epoch = state["renderer"]["renderer_epoch"]
        self.stop("kit")
        # The last heartbeat still names the old session; accepted work must be cancelled on its replacement.
        accepted = self.api("action", self.action_context(state, "measure", x=.5, y=.5))
        self.powershell(ROOT / "tools/launch_kit.ps1")
        def new_renderer():
            state = self.ready()
            return state if state and state["renderer"]["renderer_epoch"] != old_epoch else None
        current = self.wait(new_renderer, timeout=180)
        assert current["renderer"]["renderer_epoch"] != old_epoch
        cancelled = self.complete(accepted["request_id"], expected="cancelled")
        assert cancelled["error"] == "renderer_restarted", cancelled
        assert current["renderer"].get("measurement") is None
        marker = self.api("action", self.action_context(current, "measure_clear"))
        self.complete(marker["request_id"])
        self.checks.append({"name": "kit_restart_cancels_old_session", "old_epoch": old_epoch,
                            "new_epoch": current["renderer"]["renderer_epoch"], "cancelled_request": accepted["request_id"]})

    def server_restart(self):
        state = self.wait(self.ready)
        action = self.action_context(state, "capture")
        self.api("action", action)
        completed = self.complete(action["request_id"])
        digest = self.capture_digest(completed["result"])
        self.stop("server")
        self.powershell(ROOT / "start-demo.ps1", "-NoBrowser")
        def new_server():
            current = self.ready()
            return current if current and current["server_epoch"] != state["server_epoch"] else None
        current = self.wait(new_server, timeout=120)
        assert current["server_epoch"] != state["server_epoch"]
        assert current["renderer"]["renderer_epoch"] == state["renderer"]["renderer_epoch"]
        retry = self.api("action", action)
        assert retry["seq"] == completed["seq"] and retry["status"] == "completed"
        assert self.capture_digest(retry["result"]) == digest
        self.checks.append({"name": "server_restart_retains_completion", "request_id": action["request_id"],
                            "old_epoch": state["server_epoch"], "new_epoch": current["server_epoch"], "sha256": digest})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Run in the coordinated integration window; restarts app processes")
    parser.add_argument("--phase", choices=("all", "ack-loss", "kit-restart", "server-restart"), default="all")
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    if not args.execute:
        print("Plan only: briefly suspend app server to retain ACKs; restart Kit; restart app server; verify immutable captures. No browser. Add --execute in the coordinated test window.")
        return
    audit = RestartAudit(args.base)
    original = audit.wait(audit.ready)["state"]
    audit.api("state", {"playing": False, "orbit": False})
    try:
        for name, operation in (("ack-loss", audit.ack_loss), ("kit-restart", audit.kit_restart), ("server-restart", audit.server_restart)):
            if args.phase in {"all", name}:
                operation()
                print(name + ": passed", flush=True)
    finally:
        try:
            audit.api("state", original)
        finally:
            output = RUNTIME / "qa/restart-reliability.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps({"phase": args.phase, "checks": audit.checks}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
