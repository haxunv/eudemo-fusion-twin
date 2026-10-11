import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np

from fusion_twin.protocol import CommandConsumer, CommandQueue, ProtocolError, load_field_packet
from fusion_twin.server import TwinApplication


class CommandProtocolTests(unittest.TestCase):
    def setUp(self):
        self.queue = CommandQueue()
        self.consumer = CommandConsumer("renderer-a")
        self.renderer = {"renderer_epoch": "renderer-a", "ready": True}

    def snapshot(self):
        return {"server_epoch": self.queue.epoch, "commands": self.queue.active(), "command_ack_seq": self.queue.ack_seq}

    def test_one_hundred_commands_survive_delayed_ack_polling(self):
        for i in range(100):
            self.queue.submit({"request_id": f"action-{i}", "type": "measure", "x": i / 100, "y": .5}, self.renderer)
        self.consumer.synchronize(self.snapshot())
        seen = []
        for i in range(100):
            command = self.consumer.next(self.snapshot())
            seen.append(command["seq"])
            self.assertIsNone(self.consumer.next(self.snapshot()), "Asynchronous command must finish before next starts")
            self.consumer.finish(command, result={"point": i})
        self.assertEqual(seen, list(range(1, 101)))
        self.assertEqual(len(self.consumer.acks), 100)
        self.assertTrue(self.queue.absorb({**self.renderer, "server_epoch": self.queue.epoch,
                                           "command_acks": list(reversed(list(self.consumer.acks.values())))}))
        self.assertEqual(self.queue.ack_seq, 100)
        self.assertFalse(self.queue.active())
        self.consumer.synchronize(self.snapshot())
        self.assertFalse(self.consumer.acks)
        self.assertIsNone(self.consumer.next(self.snapshot()))

    def test_retries_are_idempotent_and_conflicting_payload_is_rejected(self):
        action = {"request_id": "same", "type": "capture"}
        first = self.queue.submit(action, self.renderer)
        self.assertEqual(self.queue.submit(action, self.renderer), first)
        with self.assertRaises(ProtocolError) as error:
            self.queue.submit({**action, "type": "reset_camera"}, self.renderer)
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.queue.seq, 1)

    def test_capacity_and_missing_renderer_are_explicit(self):
        queue = CommandQueue(capacity=2)
        with self.assertRaises(ProtocolError) as error:
            queue.submit({"type": "capture"}, {})
        self.assertEqual(error.exception.status, 503)
        for i in range(2):
            queue.submit({"request_id": str(i), "type": "capture"}, self.renderer)
        with self.assertRaises(ProtocolError) as error:
            queue.submit({"request_id": "overflow", "type": "capture"}, self.renderer)
        self.assertEqual(error.exception.status, 429)

    def test_renderer_restart_cancels_pending_and_never_replays_old_command(self):
        record = self.queue.submit({"request_id": "old", "type": "measure", "x": .2, "y": .4}, self.renderer)
        consumer = CommandConsumer("renderer-b")
        consumer.synchronize(self.snapshot())
        self.assertIsNone(consumer.next(self.snapshot()))
        self.queue.absorb({"renderer_epoch": "renderer-b", "server_epoch": self.queue.epoch})
        self.assertEqual(self.queue.get(record["request_id"])["status"], "cancelled")
        with self.assertRaises(ProtocolError):
            self.queue.submit({"type": "capture", "renderer_epoch": "renderer-a"}, {"renderer_epoch": "renderer-b", "ready": True})

    def test_server_restart_retains_results_and_cancels_unfinished(self):
        first = self.queue.submit({"request_id": "done", "type": "capture"}, self.renderer)
        self.queue.submit({"request_id": "waiting", "type": "measure_start"}, self.renderer)
        self.queue.absorb({**self.renderer, "server_epoch": self.queue.epoch, "command_acks": [
            {**first, "status": "completed", "result": {"capture_path": "preview.png"}}]})
        restarted = CommandQueue(self.queue.saved())
        self.assertNotEqual(restarted.epoch, self.queue.epoch)
        self.assertEqual(restarted.get("done")["status"], "completed")
        self.assertEqual(restarted.get("waiting")["status"], "cancelled")
        self.assertEqual(restarted.submit({"request_id": "done", "type": "capture"}, {}), restarted.get("done"))

    def test_out_of_order_ack_does_not_advance_over_pending(self):
        first = self.queue.submit({"request_id": "first", "type": "capture"}, self.renderer)
        second = self.queue.submit({"request_id": "second", "type": "capture"}, self.renderer)
        self.queue.absorb({**self.renderer, "server_epoch": self.queue.epoch,
                           "command_acks": [{**second, "status": "completed"}]})
        self.assertEqual(self.queue.ack_seq, 0)
        self.queue.absorb({**self.renderer, "server_epoch": self.queue.epoch,
                           "command_acks": [{**first, "status": "completed", "renderer_epoch": "wrong"}]})
        self.assertEqual(self.queue.get("first")["status"], "pending")


class FieldPacketTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="fusion-protocol-test-")
        self.addCleanup(self.directory.cleanup)
        self.runtime = Path(self.directory.name)
        self.reference = {"path": "fields/a.npz", "key": "a", "revision": 4, "topology_key": "mesh-a", "equilibrium_key": "eq-a", "schema_version": 1}
        self.arrays = {"field_key": "a", "field_revision": 4, "topology_key": "mesh-a", "equilibrium_key": "eq-a", "schema_version": 1,
                       "surface_points": np.zeros((3, 3)), "surface_triangles": np.array([[0, 1, 2]]),
                       "temperature_rgb": np.zeros((3, 3)), "heatflux_rgb": np.zeros((3, 3)), "magnetic_lines": np.zeros((1, 2, 3))}
        (self.runtime / "fields").mkdir()
        self.write()

    def write(self):
        np.savez(self.runtime / self.reference["path"], **self.arrays)

    def test_loads_referenced_packet_while_latest_pointer_advances(self):
        np.savez(self.runtime / "fields/b.npz", **{**self.arrays, "field_key": "b", "field_revision": 100})
        (self.runtime / "fields.json").write_text(json.dumps({"revision": 100, "path": "fields/b.npz"}))
        data = load_field_packet(self.runtime, self.reference)
        self.assertEqual(data["field_key"].item(), "a")
        self.assertEqual(data["field_revision"].item(), 4)

    def test_wrong_identity_shape_and_traversal_are_rejected(self):
        for key, value in (("key", "b"), ("revision", 5), ("topology_key", "other"), ("path", "../outside.npz")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                load_field_packet(self.runtime, {**self.reference, key: value})
        self.arrays["temperature_rgb"] = np.zeros((2, 3))
        self.write()
        with self.assertRaises(ValueError):
            load_field_packet(self.runtime, self.reference)


class SnapshotConcurrencyTests(unittest.TestCase):
    def test_read_and_action_remain_available_during_compute_and_snapshot_stays_consistent(self):
        entered, release = threading.Event(), threading.Event()
        class FakeEngine:
            def compute(self, state, revision):
                if revision > 1:
                    entered.set()
                    if not release.wait(3):
                        raise RuntimeError("Test did not release compute")
                return {"power": state["power"], "field_ref": {"key": str(state["power"]), "path": f'fields/{state["power"]}.npz', "revision": revision}}
        with tempfile.TemporaryDirectory(prefix="fusion-server-test-") as temporary:
            root = Path(temporary)
            (root / "assets").mkdir()
            (root / "assets/manifest.json").write_text(json.dumps({"components": [{"id": "blanket"}]}))
            app = TwinApplication(root, engine_factory=lambda _: FakeEngine(), start_background=False)
            (root / "runtime/renderer.json").write_text(json.dumps({"ready": True, "renderer_epoch": "test-renderer", "server_epoch": app.commands.epoch}))
            worker = threading.Thread(target=lambda: app.patch({"power": 2200}))
            worker.start()
            self.assertTrue(entered.wait(2))
            try:
                started = time.perf_counter()
                snapshot = app.snapshot()
                action = app.action({"request_id": "during-compute", "type": "capture", "server_epoch": app.commands.epoch, "renderer_epoch": "test-renderer"})
                self.assertLess(time.perf_counter() - started, .5)
                self.assertEqual(snapshot["state"]["power"], 2000)
                self.assertEqual(snapshot["result"]["power"], 2000)
                self.assertEqual(action["status"], "pending")
            finally:
                release.set()
                worker.join(3)
            self.assertFalse(worker.is_alive())
            published = json.loads((root / "runtime/state.json").read_text())
            self.assertEqual(published["state"]["power"], 2200)
            self.assertEqual(published["field_ref"], published["result"]["field_ref"])
            self.assertEqual(published["commands"][0]["request_id"], "during-compute")


if __name__ == "__main__":
    unittest.main()
