"""Protocol and cache integration tests; all state is isolated in temporary directories."""

import copy
import json
import math
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fusion_twin.protocol import CommandQueue, ProtocolError, interaction_key
from fusion_twin.server import TwinApplication


class FakeEngine:
    def __init__(self, root):
        self.runtime = root / "runtime"

    def compute(self, state, revision):
        key = f'packet-{state["power"]}-{state["design"]}-{state["equilibrium"]}'
        path = self.runtime / "fields" / (key + ".npz")
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"fixture")
        return {"field_ref": {"key": key, "path": f"fields/{key}.npz", "revision": revision,
                              "topology_key": state["design"], "equilibrium_key": state["equilibrium"]}}


class ApplicationReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fusion-service-reliability-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "assets").mkdir()
        (self.root / "assets/manifest.json").write_text(json.dumps({"components": [{"id": "blanket"}]}))
        self.app = TwinApplication(self.root, engine_factory=FakeEngine, start_background=False)
        self.app.patch({"mode": "assembly"})
        self.renderer = {}
        self.sync_renderer()

    def sync_renderer(self, **changes):
        reference = self.app.result["field_ref"]
        self.renderer = {"ready": True, "renderer_epoch": "renderer-test", "server_epoch": self.app.commands.epoch,
                         "applied_revision": self.app.revision, "applied_field_key": reference["key"],
                         "topology_key": reference["topology_key"], "interaction_key": interaction_key(self.app.state),
                         **changes}
        (self.app.runtime / "renderer.json").write_text(json.dumps(self.renderer))

    def action(self, kind="measure", **changes):
        return {"type": kind, "request_id": "test-request", "server_epoch": self.app.commands.epoch,
                "renderer_epoch": self.renderer["renderer_epoch"], "topology_key": self.renderer["topology_key"],
                "interaction_key": self.renderer["interaction_key"], **changes}

    def rejected(self, action, status):
        with self.assertRaises(ProtocolError) as caught:
            self.app.action(action)
        self.assertEqual(caught.exception.status, status)
        self.assertFalse(self.app.commands.active())

    def test_coordinate_pairs_and_numeric_domain_are_strict(self):
        for kind, coordinates in (("pick", {}), ("pick", {"x": .5}), ("measure", {"y": .5}),
                                  ("capture", {"x": .5, "y": .5})):
            with self.subTest(kind=kind, coordinates=coordinates), self.assertRaises(ValueError):
                self.app.action(self.action(kind, **coordinates))
        for value in (True, "0.5", None, math.nan, math.inf, -.1, 1.1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.app.action(self.action("pick", x=value, y=.5))
        self.assertFalse(self.app.commands.active())
        self.assertEqual(self.app.action(self.action("measure"))["status"], "pending")

    def test_request_and_both_session_identifiers_are_required(self):
        for key in ("request_id", "server_epoch", "renderer_epoch"):
            action = self.action("measure_clear")
            action.pop(key)
            self.rejected(action, 400)
        for key in ("server_epoch", "renderer_epoch"):
            self.rejected(self.action("measure_clear", **{key: "old-session"}), 409)
        self.sync_renderer(server_epoch="previous-server")
        self.rejected(self.action("measure_clear"), 409)

    def test_unready_renderer_rejects_without_binding_a_future_session(self):
        self.sync_renderer(ready=False)
        self.rejected(self.action("measure_clear"), 503)

    def test_renderer_read_failure_reuses_snapshot_without_mutating_it_and_recovers(self):
        self.sync_renderer(command_acks=[{"result": {"capture": "original"}}])
        file = self.app.runtime / "renderer.json"
        os.utime(file, (1000, 1000))
        with patch("fusion_twin.server.time.time", return_value=1001):
            first = self.app.renderer()
        first["ready"] = False
        first["command_acks"][0]["result"]["capture"] = "changed by caller"
        for index, error in enumerate((PermissionError("private path"), OSError("private path"),
                                       json.JSONDecodeError("incomplete write", "{", 1)), 2):
            with self.subTest(error=type(error).__name__), \
                    patch.object(Path, "open", side_effect=error), \
                    patch("fusion_twin.server.time.time", return_value=1000 + index):
                reused = self.app.renderer()
            self.assertTrue(reused["ready"])
            self.assertTrue(reused["state_read_reused"])
            self.assertEqual(reused["read_error"], type(error).__name__)
            self.assertEqual(reused["heartbeat_age_s"], index)
            self.assertEqual(reused["command_acks"][0]["result"]["capture"], "original")
            reused["command_acks"][0]["result"]["capture"] = "changed cached response"
        self.sync_renderer(applied_revision=42)
        os.utime(file, (1005, 1005))
        with patch("fusion_twin.server.time.time", return_value=1006):
            recovered = self.app.renderer()
        self.assertTrue(recovered["ready"])
        self.assertFalse(recovered["state_read_reused"])
        self.assertNotIn("read_error", recovered)
        self.assertEqual(recovered["applied_revision"], 42)
        self.assertEqual(recovered["heartbeat_age_s"], 1)

    def test_renderer_read_failures_never_extend_the_cached_heartbeat(self):
        os.utime(self.app.runtime / "renderer.json", (1000, 1000))
        with patch("fusion_twin.server.time.time", return_value=1001):
            self.assertTrue(self.app.renderer()["ready"])
        with patch.object(Path, "open", side_effect=PermissionError("sharing violation")):
            for age, ready in ((8, True), (15, True), (15.1, False), (30, False)):
                with self.subTest(age=age), patch("fusion_twin.server.time.time", return_value=1000 + age):
                    renderer = self.app.renderer()
                self.assertEqual(renderer["ready"], ready)
                self.assertEqual(renderer["heartbeat_age_s"], age)
                self.assertTrue(renderer["state_read_reused"])
                if not ready:
                    self.assertEqual(renderer["status"], "disconnected")

    def test_missing_renderer_file_clears_the_ready_cache(self):
        self.assertTrue(self.app.renderer()["ready"])
        (self.app.runtime / "renderer.json").unlink()
        self.assertEqual(self.app.renderer(), {"ready": False, "status": "starting"})
        with patch.object(Path, "open", side_effect=PermissionError("sharing violation")):
            unavailable = self.app.renderer()
        self.assertFalse(unavailable["ready"])
        self.assertFalse(unavailable["state_read_reused"])
        self.assertNotIn("renderer_epoch", unavailable)
        self.assertNotIn("heartbeat_age_s", unavailable)

    def test_renderer_restart_starting_and_unready_snapshots_replace_old_ready_cache(self):
        self.assertTrue(self.app.renderer()["ready"])
        for changes in ({"ready": False, "status": "starting", "renderer_epoch": "replacement"},
                        {"ready": False, "renderer_epoch": "replacement"}):
            with self.subTest(changes=changes):
                self.sync_renderer(**changes)
                self.assertFalse(self.app.renderer()["ready"])
                with patch.object(Path, "open", side_effect=PermissionError("sharing violation")):
                    reused = self.app.renderer()
                self.assertFalse(reused["ready"])
                self.assertTrue(reused["state_read_reused"])
                self.assertEqual(reused["renderer_epoch"], "replacement")
        self.sync_renderer(renderer_epoch="replacement")
        self.assertTrue(self.app.renderer()["ready"])

    def test_renderer_heartbeat_uses_the_read_handle_before_path_replacement(self):
        file = self.app.runtime / "renderer.json"
        os.utime(file, (1000, 1000))
        original_open = Path.open
        stream = original_open(file, encoding="utf-8")
        replacement = {**self.renderer, "applied_revision": 42}

        class ReplaceAfterClose:
            def __enter__(self):
                return stream

            def __exit__(self, *_):
                stream.close()
                with original_open(file, "w", encoding="utf-8") as writer:
                    json.dump(replacement, writer)
                os.utime(file, (1016, 1016))

        with patch.object(Path, "open", return_value=ReplaceAfterClose()), \
                patch("fusion_twin.server.time.time", return_value=1016):
            old_snapshot = self.app.renderer()
        self.assertEqual(old_snapshot["applied_revision"], self.renderer["applied_revision"])
        self.assertEqual(old_snapshot["heartbeat_age_s"], 16)
        self.assertFalse(old_snapshot["ready"])
        with patch("fusion_twin.server.time.time", return_value=1017):
            replacement_snapshot = self.app.renderer()
        self.assertEqual(replacement_snapshot["applied_revision"], 42)
        self.assertEqual(replacement_snapshot["heartbeat_age_s"], 1)
        self.assertTrue(replacement_snapshot["ready"])

    def test_transient_renderer_read_failure_does_not_reject_a_valid_command(self):
        self.assertTrue(self.app.renderer()["ready"])
        with patch("fusion_twin.server.json.load", side_effect=PermissionError("sharing violation")):
            accepted = self.app.action(self.action("measure_clear"))
        self.assertEqual(accepted["status"], "pending")
        self.assertEqual(len(self.app.commands.active()), 1)

    def test_retry_republishes_command_after_failed_snapshot_write(self):
        action = self.action("measure_clear")
        with patch("fusion_twin.server.atomic_json", side_effect=OSError("Transient write failure")), self.assertRaises(OSError):
            self.app.action(action)
        accepted = self.app.action(action)
        self.assertEqual(accepted["seq"], 1)
        saved = json.loads((self.app.runtime / "state.json").read_text())
        self.assertEqual([item["request_id"] for item in saved["commands"]], [action["request_id"]])

    def test_ack_publication_retries_after_durable_completion_write(self):
        accepted = self.app.action(self.action("capture"))
        self.sync_renderer(command_acks=[{**accepted, "status": "completed"}])
        with patch("fusion_twin.server.atomic_json", side_effect=OSError("Transient write failure")), self.assertRaises(OSError):
            self.app.action_status(accepted["request_id"])
        self.assertEqual(self.app.commands.get(accepted["request_id"])["status"], "completed")
        self.app.snapshot()
        saved = json.loads((self.app.runtime / "state.json").read_text())
        self.assertEqual(saved["command_ack_seq"], accepted["seq"])
        self.assertEqual(saved["commands"], [])

    def test_background_ack_worker_recovers_from_transient_io_failure(self):
        accepted = self.app.action(self.action("capture"))
        self.sync_renderer(command_acks=[{**accepted, "status": "completed"}])
        original = self.app.commands.terminals.put
        recovered = threading.Event()
        attempts = []
        def put(record):
            attempts.append(record["request_id"])
            if len(attempts) == 1:
                raise OSError("Transient sharing violation")
            original(record)
            recovered.set()
        worker = threading.Thread(target=self.app._playback, daemon=True)
        with patch.object(self.app.commands.terminals, "put", side_effect=put):
            worker.start()
            try:
                self.assertTrue(recovered.wait(3))
                self.assertTrue(worker.is_alive())
            finally:
                self.app.stop.set()
                worker.join(3)
        self.assertEqual(self.app.commands.get(accepted["request_id"])["status"], "completed")

    def test_coordinate_actions_bind_current_and_applied_topology_and_view(self):
        self.rejected(self.action("pick", x=.2, y=.5, topology_key="stale"), 409)
        action = self.action("pick", x=.2, y=.5)
        action.pop("topology_key")
        self.rejected(action, 409)
        action = self.action("pick", x=.2, y=.5)
        action.pop("interaction_key")
        self.rejected(action, 409)
        self.app.patch({"design": "longleg"})
        self.rejected(self.action("pick", x=.2, y=.5), 409)
        self.sync_renderer()
        self.app.patch({"cutaway": 100})
        self.rejected(self.action("pick", x=.2, y=.5), 409)
        self.sync_renderer()
        self.rejected(self.action("pick", x=.2, y=.5, interaction_key="previous-view"), 409)
        self.assertEqual(self.app.action(self.action("pick", x=.2, y=.5))["status"], "pending")

    def test_selection_language_and_thermal_only_revisions_allow_next_measurement(self):
        action = self.action("measure", x=.2, y=.5)
        self.app.patch({"selected": "blanket", "language": "en", "power": 2400})
        self.assertLess(self.renderer["applied_revision"], self.app.revision)
        self.assertEqual(self.app.action(action)["status"], "pending")

    def test_volume_waits_for_actual_volume_field_ack(self):
        self.app.patch({"mode": "volume"})
        self.sync_renderer(applied_volume_field_key="old")
        self.rejected(self.action("pick", x=.2, y=.5), 409)
        self.sync_renderer(applied_volume_field_key=self.app.result["field_ref"]["key"])
        self.assertEqual(self.app.action(self.action("pick", x=.2, y=.5))["status"], "pending")

    def test_archived_completion_is_returned_across_service_restart_with_old_epochs(self):
        action = self.action("capture")
        accepted = self.app.action(action)
        result = {"capture_url": "/api/captures/immutable.png", "sha256": "fixture"}
        self.sync_renderer(command_acks=[{**accepted, "status": "completed", "result": result}])
        completed = self.app.action_status(action["request_id"])
        restarted = TwinApplication(self.root, engine_factory=FakeEngine, start_background=False)
        retry = restarted.action(action)
        self.assertEqual(retry["status"], "completed")
        self.assertEqual(retry["result"], result)
        self.assertEqual(retry["completed_at"], completed["completed_at"])
        self.assertEqual(retry["seq"], accepted["seq"])
        with self.assertRaises(ProtocolError) as caught:
            restarted.action({**action, "type": "measure_clear"})
        self.assertEqual(caught.exception.status, 409)

    def test_cache_collection_respects_commands_renderer_watermarks_and_writer_lock(self):
        self.app.field_cache.keep = 2
        first_key = self.app.result["field_ref"]["key"]
        accepted = self.app.action(self.action("capture"))
        for power in (2100, 2200, 2300, 2400, 2500):
            self.app.patch({"power": power})
        paths = {key: self.app.runtime / item["path"] for key, item in self.app.field_cache.publications.items()}
        self.app.compute_lock.acquire()
        try:
            self.assertFalse(self.app.collect_fields()["deleted"])
        finally:
            self.app.compute_lock.release()
        self.assertFalse(self.app.collect_fields()["deleted"], "Renderer has not consumed newer snapshots")
        self.sync_renderer()
        reclaimed = self.app.collect_fields()
        self.assertEqual(len(reclaimed["deleted"]), 3)
        self.assertTrue(paths[first_key].exists(), "Pending action retains its field")
        self.sync_renderer(command_acks=[{**accepted, "status": "completed"}])
        self.assertIn(first_key, self.app.collect_fields()["deleted"])
        saved = json.loads((self.app.runtime / "state.json").read_text())
        self.assertEqual(len(saved["field_publications"]), 2)
        self.assertEqual(saved["field_ref"], saved["result"]["field_ref"])
        self.assertTrue((self.app.runtime / saved["field_ref"]["path"]).exists())


class DurableCompletionTests(unittest.TestCase):
    def test_renderer_restart_cancellation_retries_if_terminal_disk_write_fails(self):
        with tempfile.TemporaryDirectory(prefix="fusion-epoch-write-failure-") as directory:
            queue = CommandQueue(terminal_directory=directory)
            renderer = {"ready": True, "renderer_epoch": "old", "server_epoch": queue.epoch}
            queue.absorb(renderer)
            queue.submit({"type": "measure", "request_id": "old-command"}, renderer)
            replacement = {**renderer, "renderer_epoch": "new"}
            with patch.object(queue.terminals, "put", side_effect=OSError("Transient write failure")), self.assertRaises(OSError):
                queue.absorb(replacement)
            self.assertEqual(queue.renderer_epoch, "old")
            self.assertEqual(queue.get("old-command")["status"], "pending")
            queue.absorb(replacement)
            self.assertEqual(queue.renderer_epoch, "new")
            self.assertEqual(queue.get("old-command")["status"], "cancelled")
            self.assertEqual(queue.get("old-command")["error"], "renderer_restarted")

    def test_trimmed_terminal_records_remain_idempotent_after_restart(self):
        with tempfile.TemporaryDirectory(prefix="fusion-terminal-records-") as directory:
            queue = CommandQueue(retention=2, terminal_directory=directory)
            renderer = {"ready": True, "renderer_epoch": "renderer", "server_epoch": queue.epoch}
            for index in range(8):
                record = queue.submit({"type": "capture", "request_id": f"record-{index}"}, renderer)
                queue.absorb({**renderer, "command_acks": [{**record, "status": "completed", "result": {"capture": index}}]})
            self.assertEqual(len(queue.records), 2)
            self.assertEqual(len(list(Path(directory).glob("*.json"))), 8)
            restarted = CommandQueue(queue.saved(), retention=2, terminal_directory=directory)
            retry = restarted.submit({"type": "capture", "request_id": "record-0"}, {})
            self.assertEqual(retry["status"], "completed")
            self.assertEqual(retry["result"], {"capture": 0})
            self.assertEqual(restarted.seq, 8)

    def test_durable_ack_wins_over_stale_pending_snapshot_after_crash(self):
        with tempfile.TemporaryDirectory(prefix="fusion-terminal-crash-") as directory:
            queue = CommandQueue(terminal_directory=directory)
            renderer = {"ready": True, "renderer_epoch": "renderer", "server_epoch": queue.epoch}
            record = queue.submit({"type": "capture", "request_id": "durable"}, renderer)
            stale_snapshot = copy.deepcopy(queue.saved())
            queue.absorb({**renderer, "command_acks": [{**record, "status": "completed", "result": {"capture": "same"}}]})
            restarted = CommandQueue(stale_snapshot, terminal_directory=directory)
            self.assertEqual(restarted.get("durable")["status"], "completed")
            self.assertEqual(restarted.get("durable")["result"], {"capture": "same"})

    def test_failed_terminal_write_never_advances_ack_watermark(self):
        with tempfile.TemporaryDirectory(prefix="fusion-terminal-failure-") as directory:
            queue = CommandQueue(terminal_directory=directory)
            renderer = {"ready": True, "renderer_epoch": "renderer", "server_epoch": queue.epoch}
            record = queue.submit({"type": "capture", "request_id": "durable"}, renderer)
            ack = {**renderer, "command_acks": [{**record, "status": "completed"}]}
            with patch.object(queue.terminals, "put", side_effect=OSError("Disk full")), self.assertRaises(OSError):
                queue.absorb(ack)
            self.assertEqual(queue.ack_seq, 0)
            self.assertEqual(queue.get("durable")["status"], "pending")
            queue.absorb(ack)
            self.assertEqual(queue.ack_seq, 1)


if __name__ == "__main__":
    unittest.main()
