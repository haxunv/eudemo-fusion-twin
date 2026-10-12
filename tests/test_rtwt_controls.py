"""CPU behavior tests of the production RTWT control and publication workers.

Only the worker methods are loaded; Kit, CUDA and USD
are replaced at their boundaries. Tests drive external notices and observe the
actual serialized authority requests rather than reproducing worker logic.
"""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / "kit/extensions/fusion.twin.bridge/fusion/twin/bridge/nvidia_workflow.py"
VOLUME = "/World/CAE/PlasmaVolume"


class Attribute:
    def __init__(self, values, name):
        self.values, self.name = values, name

    def Get(self):
        return self.values[self.name]


class Prim:
    def __init__(self, values):
        self.values = values

    def GetAttribute(self, name):
        return Attribute(self.values, name)


class ChangedPath:
    def __init__(self, name):
        self.name = name

    def GetPrimPath(self):
        return "/World/AppState"


class Notice:
    def __init__(self, names):
        self.paths = [ChangedPath(name) for name in names]

    def GetChangedInfoOnlyPaths(self):
        return self.paths


class Request:
    def __init__(self, patch):
        self.patch = dict(patch)
        self.response = asyncio.get_running_loop().create_future()

    def accept(self, revision=1):
        self.response.set_result({"accepted": True, "accepted_revision": revision})

    def reject(self):
        self.response.set_result({"accepted": False, "error": "ValueError: Invalid heating"})


class WorkflowHarness:
    def __init__(self):
        self.initial = {"mode": "assembly", "power": 2000, "heating": 20, "neon": False}
        self.authority = dict(self.initial)
        self.attributes = {f"fusion:{key}": value for key, value in self.initial.items()}
        self.calls = []
        self.requests = asyncio.Queue()
        self.sync_writes = []
        self.fail_sync = False
        self.volume = Prim({"visibility": "invisible"})
        self.dataset = Prim({"fusion:baselineThermalPowerMW": 2000})
        self.stage = SimpleNamespace(GetPrimAtPath=lambda path: self.volume)
        self.web_api = SimpleNamespace(set_state=self.sync_state, get_state=self.native_state)
        self.app = SimpleNamespace(next_update_async=self.next_update)
        namespace = {
            "asyncio": asyncio,
            "omni": SimpleNamespace(kit=SimpleNamespace(app=SimpleNamespace(get_app=lambda: self.app))),
            "web_api": self.web_api,
            "fusion_set_state": self.post,
            "Listener": SimpleNamespace(wait_for_sync_idle=self.next_update),
            "cache": SimpleNamespace(get=lambda *args, **kwargs: None),
            "Usd": SimpleNamespace(TimeCode=SimpleNamespace(EarliestTime=lambda: None)),
            "VOLUME": VOLUME,
        }
        source = ast.parse(WORKFLOW_PATH.read_text(encoding="utf-8"))
        workflow = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "NvidiaWorkflow")
        names = {"submit", "_controls_changed", "_commit_control_requests", "_sync_controls", "_run", "_publish", "_operator_complete"}
        methods = [node for node in workflow.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
        if {node.name for node in methods} != names:
            raise AssertionError("Production RTWT control methods changed; update boundary harness")
        extracted = ast.ClassDef(name="NvidiaWorkflow", bases=[], keywords=[], body=methods, decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[extracted], type_ignores=[]))
        exec(compile(module, str(WORKFLOW_PATH), "exec"), namespace)
        self.workflow = namespace["NvidiaWorkflow"]()
        self.workflow.__dict__.update(
            stage=self.stage, dataset=self.dataset, app_state=Prim(self.attributes),
            keys=set(self.initial), attribute_keys={f"fusion:{key}": key for key in self.initial},
            committed_controls=dict(self.initial), requested_controls={}, inflight_controls={},
            syncing_controls=False, control_task=None, task=None, latest=None, closed=False,
            operator_events={}, volume_key=None,
            status={"control_pending": False, "control_error": None, "rtwt_standard_writes": 0},
        )

    @staticmethod
    async def next_update():
        await asyncio.sleep(0)

    def native_state(self):
        return {key: self.attributes[f"fusion:{key}"] for key in self.initial}

    def external_edit(self, patch):
        """A standard set_state write modifies USD, then emits ObjectsChanged."""
        for key, value in patch.items():
            self.attributes[f"fusion:{key}"] = value
        self.workflow._controls_changed(Notice([f"fusion:{key}" for key in patch]), self.stage)

    async def sync_state(self, patch):
        self.sync_writes.append(dict(patch))
        if self.fail_sync:
            self.fail_sync = False
            raise RuntimeError("Injected RTWT synchronization failure")
        # USD notices also fire during internal set_state. The real guard must
        # keep these writes from becoming new solver requests.
        self.external_edit(patch)
        if "power" in patch:
            self.dataset.values["fusion:baselineThermalPowerMW"] = patch["power"]
        return True

    async def post(self, patch):
        request = Request(patch)
        self.calls.append(dict(patch))
        self.requests.put_nowait(request)
        response = await request.response
        if response["accepted"]:
            self.authority.update(patch)
        return response

    async def next_request(self):
        return await asyncio.wait_for(self.requests.get(), timeout=1)

    async def drain(self):
        if self.workflow.control_task:
            await asyncio.wait_for(self.workflow.control_task, timeout=1)

    async def close(self):
        tasks = {task for task in (self.workflow.control_task, self.workflow.task) if task is not None}
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class RtwtControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.harness = WorkflowHarness()

    async def asyncTearDown(self):
        await self.harness.close()

    async def test_last_a_replaces_pending_b_before_first_commit(self):
        h = self.harness
        h.external_edit({"heating": 35})
        h.external_edit({"heating": 20})
        request = await h.next_request()
        self.assertEqual(request.patch, {"heating": 20})
        request.accept()
        await h.drain()
        self.assertEqual(h.calls, [{"heating": 20}])
        self.assertEqual(h.authority["heating"], 20)
        self.assertFalse(h.workflow.status["control_pending"])

    async def test_last_a_survives_inflight_b_while_committed_is_still_a(self):
        h = self.harness
        h.external_edit({"heating": 35})
        first = await h.next_request()
        self.assertEqual(h.workflow.committed_controls["heating"], 20)
        h.external_edit({"heating": 20})
        first.accept(2)
        final = await h.next_request()
        self.assertEqual(final.patch, {"heating": 20})
        final.accept(3)
        await h.drain()
        self.assertEqual(h.calls, [{"heating": 35}, {"heating": 20}])
        self.assertEqual(h.authority["heating"], 20)
        self.assertEqual(h.workflow.status["control_accepted_revision"], 3)
        self.assertEqual(h.workflow.status["rtwt_standard_writes"], 2)
        self.assertFalse(h.workflow.status["control_pending"])

    async def test_internal_sync_notices_do_not_submit_solver_requests(self):
        h = self.harness
        self.assertTrue(await h.workflow._sync_controls({"heating": 65, "neon": True}))
        await asyncio.sleep(0)
        self.assertEqual(h.native_state()["heating"], 65)
        self.assertEqual(h.calls, [])
        self.assertEqual(h.authority, h.initial)
        self.assertIsNone(h.workflow.control_task)
        self.assertFalse(h.workflow.syncing_controls)

    async def test_committed_snapshot_preserves_inflight_and_pending_edits(self):
        h = self.harness
        h.external_edit({"heating": 35})
        first = await h.next_request()
        h.external_edit({"neon": True})
        # A delayed committed snapshot still contains heating=20 and neon=False.
        h.workflow.submit(dict(h.initial), {}, {"key": "committed-a"})
        await asyncio.wait_for(h.workflow.task, timeout=1)
        self.assertIsNone(h.workflow.status["volume_error"])
        self.assertTrue(h.workflow.status["rtwt_ready"])
        self.assertEqual(h.sync_writes, [{"mode": "assembly", "power": 2000}])
        self.assertEqual(h.native_state()["heating"], 35)
        self.assertTrue(h.native_state()["neon"])
        self.assertEqual(h.calls, [{"heating": 35}])
        first.accept(2)
        following = await h.next_request()
        self.assertEqual(following.patch, {"neon": True})
        following.accept(3)
        await h.drain()
        self.assertEqual(h.authority["heating"], 35)
        self.assertTrue(h.authority["neon"])
        self.assertEqual(len(h.calls), 2)

    async def test_invalid_patch_rolls_back_to_committed_without_feedback(self):
        h = self.harness
        h.external_edit({"heating": 999})
        request = await h.next_request()
        request.reject()
        await h.drain()
        self.assertEqual(h.native_state(), h.initial)
        self.assertEqual(h.authority, h.initial)
        self.assertEqual(h.calls, [{"heating": 999}])
        self.assertEqual(h.sync_writes, [{"heating": 20}])
        self.assertIn("Invalid heating", h.workflow.status["control_error"])
        self.assertFalse(h.workflow.status["control_pending"])

    async def test_invalid_patch_rolls_back_other_keys_and_preserves_newer_request(self):
        h = self.harness
        h.external_edit({"heating": 999, "neon": True})
        invalid = await h.next_request()
        h.external_edit({"heating": 65})
        invalid.reject()
        latest = await h.next_request()
        self.assertEqual(h.sync_writes, [{"neon": False}])
        self.assertEqual(h.native_state()["heating"], 65)
        self.assertFalse(h.native_state()["neon"])
        self.assertEqual(latest.patch, {"heating": 65})
        latest.accept(2)
        await h.drain()
        self.assertEqual(h.authority, {**h.initial, "heating": 65})
        self.assertEqual(h.calls, [{"heating": 999, "neon": True}, {"heating": 65}])
        self.assertEqual(h.workflow.status["rtwt_standard_writes"], 1)
        self.assertIsNone(h.workflow.status["control_error"])
        self.assertFalse(h.workflow.status["control_pending"])

    async def test_sync_failure_releases_guard_for_next_external_request(self):
        h = self.harness
        h.fail_sync = True
        with self.assertRaisesRegex(RuntimeError, "synchronization failure"):
            await h.workflow._sync_controls({"heating": 50})
        self.assertFalse(h.workflow.syncing_controls)
        h.external_edit({"heating": 35})
        request = await h.next_request()
        request.accept()
        await h.drain()
        self.assertEqual(h.calls, [{"heating": 35}])
        self.assertEqual(h.authority["heating"], 35)


class CpuVolume:
    def __init__(self, value):
        self.values = np.full((1, 1, 1), value, dtype=np.float32)

    def array(self):
        return SimpleNamespace(numpy=lambda: self.values.ravel())


class CpuField:
    def __init__(self, value):
        self.volume = CpuVolume(value)

    def get_data(self):
        return self.volume

    def get_range(self):
        return (self.volume.values.min(), self.volume.values.max())

    def to_array(self):
        return self.volume.array()


class VolumeHarness(WorkflowHarness):
    """Model only CAE/USD boundaries; run the production publication state machine."""

    def __init__(self):
        super().__init__()
        self.values = {"A": 1., "B": 2.}
        self.initial.update(mode="volume")
        self.volume.values.update(visibility="inherited", **{"nvindex:composite": True})
        self.dataset_key = self.gpu_key = "A"
        self.published = []
        self.adopted = []
        self.ready_keys = []
        self.pending_gpu_key = None
        self.return_to_a_after_publish = False
        self.fail_readback = None
        self.native = object()
        self.index_field = CpuField(self.values["A"])
        self.workflow.volume_key = "A"
        self.workflow.status.update(applied_volume_key="A", applied_volume_field_key="A")
        namespace = self.workflow._run.__globals__
        namespace.update(
            np=np, wp=SimpleNamespace(Volume=CpuVolume),
            Gf=SimpleNamespace(Vec3i=lambda *values: values, Vec3f=lambda *values: values),
            GRID_ORIGIN=(0, 0, 0),
            OmniSciVtk=SimpleNamespace(ImageDataAPI=SimpleNamespace(Apply=lambda _: SimpleNamespace(
                CreateMinExtentAttr=lambda *_: None, CreateMaxExtentAttr=lambda *_: None,
                CreateOriginAttr=lambda *_: None, CreateSpacingAttr=lambda *_: None))),
            results=SimpleNamespace(publish_results=self.publish_results),
            GetField=SimpleNamespace(invoke=self.get_field),
            _sample_volume=lambda data, _: (data["sample"], None, None),
            cache=SimpleNamespace(get=self.cache_get),
            carb=SimpleNamespace(settings=SimpleNamespace(get_settings=lambda: SimpleNamespace(get=lambda _: 3))),
            Usd=SimpleNamespace(TimeCode=SimpleNamespace(EarliestTime=lambda: None, Default=lambda: None)),
        )
        self.workflow._volume_bytes = self.volume_bytes
        self.workflow._apply_transfer = lambda state: None
        self.workflow._emit_cache = lambda state, field, key: self.ready_keys.append(key)

    def packet(self, key):
        return {"sample": np.full((1, 1, 1), self.values[key], dtype=np.float32)}

    def submit(self, key):
        self.workflow.submit(dict(self.initial), self.packet(key), {"key": key})

    def volume_bytes(self, state, data, reference):
        sample = data["sample"]
        return reference["key"], {"dimensions": (1, 1, 1), "spacing": (1., 1., 1.),
                                 "buffer": sample.ravel(), "range": (sample.min(), sample.max())}, "memory"

    def publish_results(self, dataset, fields, **kwargs):
        value = fields["Temperature"][0]
        self.dataset_key = next(key for key, candidate in self.values.items() if candidate == value)
        self.published.append(self.dataset_key)
        self.pending_gpu_key = self.dataset_key
        return f"revision-{len(self.published)}"

    async def get_field(self, *args, **kwargs):
        key = self.dataset_key
        if key == "B" and self.return_to_a_after_publish:
            self.return_to_a_after_publish = False
            self.submit("A")
        await asyncio.sleep(0)
        if key == self.fail_readback:
            self.fail_readback = None
            raise RuntimeError("Injected failure after dataset publication")
        return CpuField(self.values[key])

    async def next_update(self):
        if self.pending_gpu_key is not None:
            self.gpu_key = self.pending_gpu_key
            self.pending_gpu_key = None
            self.index_field = CpuField(self.values[self.gpu_key])
            self.native = object()
            self.adopted.append(self.gpu_key)
            self.workflow._operator_complete({"prim_path": VOLUME, "success": True})
        await asyncio.sleep(0)

    def cache_get(self, name, **kwargs):
        if name.startswith("[viz:index_compute_task_vdb]"):
            return self.native
        if name.startswith("[viz:index_volume]"):
            return SimpleNamespace(get_field_names=lambda: ["colors"], get_field=lambda _: self.index_field)
        return None


class RtwtVolumePublicationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.harness = VolumeHarness()

    async def asyncTearDown(self):
        await self.harness.close()

    async def test_return_to_applied_a_after_b_publication_republishes_a(self):
        h = self.harness
        h.return_to_a_after_publish = True
        h.submit("B")
        await asyncio.wait_for(h.workflow.task, timeout=1)
        self.assertEqual(h.published, ["B", "A"])
        self.assertEqual(h.adopted, ["B", "A"])
        self.assertEqual(h.dataset_key, "A")
        self.assertEqual(h.gpu_key, "A")
        self.assertEqual(h.workflow.volume_key, "A")
        self.assertEqual(h.workflow.status["applied_volume_field_key"], "A")
        self.assertEqual(h.ready_keys, ["A"])
        self.assertIsNone(h.workflow.status["volume_error"])
        self.assertFalse(h.workflow.status["volume_pending"])

    async def test_failed_b_readback_invalidates_reuse_then_a_recovers(self):
        h = self.harness
        h.fail_readback = "B"
        h.submit("B")
        await asyncio.wait_for(h.workflow.task, timeout=1)
        self.assertEqual(h.dataset_key, "B")
        self.assertIsNone(h.workflow.volume_key)
        self.assertIn("Injected failure", h.workflow.status["volume_error"])
        self.assertEqual(h.workflow.status["applied_volume_field_key"], "A")
        self.assertEqual(h.ready_keys, [])
        h.submit("A")
        await asyncio.wait_for(h.workflow.task, timeout=1)
        self.assertEqual(h.published, ["B", "A"])
        self.assertEqual(h.gpu_key, "A")
        self.assertEqual(h.workflow.volume_key, "A")
        self.assertEqual(h.ready_keys, ["A"])
        self.assertIsNone(h.workflow.status["volume_error"])

    async def test_unchanged_applied_a_keeps_native_cache_fast_path(self):
        h = self.harness
        original_native = h.native
        h.submit("A")
        await asyncio.wait_for(h.workflow.task, timeout=1)
        self.assertEqual(h.published, [])
        self.assertEqual(h.adopted, [])
        self.assertIs(h.native, original_native)
        self.assertEqual(h.workflow.volume_key, "A")
        self.assertEqual(h.ready_keys, ["A"])
        self.assertIsNone(h.workflow.status["volume_error"])


if __name__ == "__main__":
    unittest.main()
