"""Real TCP burst regression, isolated from the running demo and renderer."""

import collections
import concurrent.futures
import http.client
import json
import math
import tempfile
import threading
import time
import unittest
from pathlib import Path

from fusion_twin import server as server_module


class FakeEngine:
    def __init__(self, root):
        pass

    def compute(self, state, revision):
        return {"field_ref": {"key": "test-field", "path": "fields/test-field.npz", "revision": revision,
                              "topology_key": "test-topology", "equilibrium_key": "test-equilibrium"}}


def latency_summary(values):
    ordered = sorted(values)
    if not ordered:
        return None
    return {"min_ms": round(ordered[0], 2),
            "p50_ms": round(ordered[math.ceil(len(ordered) * .50) - 1], 2),
            "p95_ms": round(ordered[math.ceil(len(ordered) * .95) - 1], 2),
            "max_ms": round(ordered[-1], 2)}


def run_burst(server_class, count=100, timeout=5):
    """Each barrier participant opens exactly one connection and sends one POST."""
    with tempfile.TemporaryDirectory(prefix="fusion-http-burst-") as temporary:
        root = Path(temporary)
        (root / "assets").mkdir()
        (root / "assets/manifest.json").write_text(
            json.dumps({"components": [{"id": "blanket"}]}), encoding="utf-8")
        app = server_module.TwinApplication(root, engine_factory=FakeEngine, start_background=False)
        (app.runtime / "renderer.json").write_text(json.dumps({
            "ready": True, "renderer_epoch": "test", "server_epoch": app.commands.epoch,
            "applied_revision": app.revision, "applied_field_key": app.result["field_ref"]["key"],
            "topology_key": "test-topology", "equilibrium_key": "test-equilibrium",
        }), encoding="utf-8")
        httpd = server_class(("127.0.0.1", 0), server_module.Handler)
        httpd.app = app
        host, port = httpd.server_address
        worker = threading.Thread(target=httpd.serve_forever, daemon=True, name="isolated-http-burst")
        worker.start()
        barrier = threading.Barrier(count)

        def post(index):
            request_id = f"burst-{index:03d}"
            body = json.dumps({"type": "measure_clear", "request_id": request_id,
                               "server_epoch": app.commands.epoch, "renderer_epoch": "test"})
            connection = http.client.HTTPConnection(host, port, timeout=timeout)
            connected_ms = None
            phase = "connect"
            barrier.wait(timeout=20)
            started = time.perf_counter()
            try:
                connection.connect()
                connected_ms = (time.perf_counter() - started) * 1000
                phase = "response"
                connection.request("POST", "/api/action", body=body,
                                   headers={"Content-Type": "application/json", "Connection": "close"})
                response = connection.getresponse()
                payload = json.loads(response.read())
                return {"request_id": request_id, "http_status": response.status, "body": payload,
                        "connect_ms": connected_ms, "elapsed_ms": (time.perf_counter() - started) * 1000}
            except (OSError, http.client.HTTPException, ValueError) as exc:
                return {"request_id": request_id, "failure": f"{phase}:{type(exc).__name__}",
                        "errno": getattr(exc, "errno", None), "winerror": getattr(exc, "winerror", None),
                        "connect_ms": connected_ms, "elapsed_ms": (time.perf_counter() - started) * 1000}
            finally:
                connection.close()

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=count) as clients:
                outcomes = list(clients.map(post, range(count)))
        finally:
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=5)
            app.stop.set()
        successes = [item for item in outcomes if item.get("http_status") == 200]
        failures = collections.Counter(item.get("failure", f"HTTP {item.get('http_status')}")
                                       for item in outcomes if item.get("http_status") != 200)
        report = {"server": server_class.__name__, "request_queue_size": httpd.request_queue_size,
                  "connections": count, "attempts_per_connection": 1, "successes": len(successes),
                  "failure_types": dict(failures), "accepted_commands": len(app.commands.records),
                  "latency": latency_summary([item["elapsed_ms"] for item in outcomes]),
                  "successful_latency": latency_summary([item["elapsed_ms"] for item in successes]),
                  "connect_latency": latency_summary([item["connect_ms"] for item in outcomes
                                                      if item["connect_ms"] is not None])}
        records = app.commands.saved()
        return report, outcomes, records


class HTTPConcurrencyTests(unittest.TestCase):
    def test_one_hundred_simultaneous_connections_are_all_accepted_once(self):
        report, outcomes, records = run_burst(server_module.FusionHTTPServer)
        print("HTTP_BURST " + json.dumps(report, sort_keys=True), flush=True)
        self.assertEqual(report["successes"], 100, report)
        self.assertEqual(report["failure_types"], {}, report)
        self.assertEqual(len(records), 100)
        self.assertEqual({record["request_id"] for record in records},
                         {f"burst-{index:03d}" for index in range(100)})
        self.assertEqual(sorted(record["seq"] for record in records), list(range(1, 101)))
        for outcome in outcomes:
            self.assertEqual(outcome["body"]["request_id"], outcome["request_id"])
            self.assertEqual(outcome["body"]["status"], "pending")
        self.assertTrue(all(record["status"] == "pending" for record in records))


if __name__ == "__main__":
    unittest.main()
