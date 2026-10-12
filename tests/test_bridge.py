"""Exercise the actual bridge against in-memory USD, without a Kit process."""

import asyncio
import importlib
import json
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from pxr import Gf, Tf, Usd, UsdGeom

from fusion_twin.protocol import CommandConsumer, CommandQueue, interaction_key
from fusion_twin.server import DEFAULT_STATE


def load_bridge(viewport):
    modules = {name: types.ModuleType(name) for name in (
        "carb", "omni", "omni.ext", "omni.kit", "omni.kit.app", "omni.usd",
        "omni.kit.viewport", "omni.kit.viewport.utility", "bridge_test_package")}
    modules["carb"].log_error = lambda message: None
    render_settings = {"/rtx/rendermode": "RealTimePathTracing", "/rtx/post/dlss/execMode": 2,
                       "/rtx-transient/rt2Enabled": True}
    settings = types.SimpleNamespace(get=render_settings.get, set=render_settings.__setitem__)
    modules["carb"].settings = types.SimpleNamespace(get_settings=lambda: settings)
    modules["omni"].ext = modules["omni.ext"]
    modules["omni.ext"].IExt = object
    modules["omni"].kit = modules["omni.kit"]
    modules["omni.kit"].app = modules["omni.kit.app"]
    modules["omni"].usd = modules["omni.usd"]
    selection = types.SimpleNamespace(get_selected_prim_paths=lambda: [], set_selected_prim_paths=lambda *_: None)
    context = types.SimpleNamespace(get_selection=lambda: selection, get_stage_streaming_status=lambda: 0,
                                    reset_renderer_accumulation=lambda: None)
    modules["omni.usd"].get_context = lambda: context
    modules["omni.kit.app"].get_app = lambda: types.SimpleNamespace(next_update_async=lambda: asyncio.sleep(0))
    utility = modules["omni.kit.viewport.utility"]
    utility.get_active_viewport = lambda: viewport
    utility.get_active_viewport_window = lambda: None
    utility.capture_viewport_to_file = lambda *_: None
    directory = Path(__file__).resolve().parents[1] / "kit/extensions/fusion.twin.bridge/fusion/twin/bridge"
    modules["bridge_test_package"].__path__ = [str(directory)]
    with patch.dict(sys.modules, modules):
        for name in ("bridge_test_package.extension", "bridge_test_package.geometry"):
            sys.modules.pop(name, None)
        return importlib.import_module("bridge_test_package.extension")


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fusion-bridge-test-")
        self.addCleanup(self.temporary.cleanup)
        self.viewport = types.SimpleNamespace(resolution=(1920, 1080), camera_path="/World/Cameras/overview", request_query=Mock())
        self.module = load_bridge(self.viewport)
        self.bridge = object.__new__(self.module.FusionTwinExtension)
        bridge = self.bridge
        bridge.stage = Usd.Stage.CreateInMemory()
        bridge.scene_ready = True
        machine = UsdGeom.Xform.Define(bridge.stage, "/World/Machine")
        variants = machine.GetPrim().GetVariantSets().AddVariantSet("design")
        for design, radius in (("conventional", 6.), ("longleg", 8.)):
            variants.AddVariant(design)
            variants.SetVariantSelection(design)
            with variants.GetVariantEditContext():
                for component in ("blanket", "divertor"):
                    sector = UsdGeom.Xform.Define(bridge.stage, f"/World/Machine/{component}/sector_00")
                    sector.AddRotateZOp().Set(0)
                    mesh = UsdGeom.Mesh.Define(bridge.stage, str(sector.GetPath()) + "/p000")
                    mesh.GetPrim().SetCustomDataByKey("sourcePartId", "p000")
                    mesh.CreatePointsAttr([(radius, 0, 0), (radius, .2, 0), (radius, .2, 1)])
                    mesh.CreateFaceVertexCountsAttr([3])
                    mesh.CreateFaceVertexIndicesAttr([0, 1, 2])
        variants.SetVariantSelection("conventional")
        UsdGeom.Camera.Define(bridge.stage, "/World/Cameras/overview")
        bridge.stage.SetEditTarget(bridge.stage.GetSessionLayer())
        UsdGeom.Xform.Define(bridge.stage, "/World/Fields/Surface")
        bridge.runtime = Path(self.temporary.name)
        bridge.state = {}
        bridge.revision = -1
        bridge.field_data = bridge.field_reference = None
        bridge.nvidia_workflow = None
        bridge.gpu_name = None
        bridge.applied_field_key = bridge.topology_key = bridge.equilibrium_key = bridge.color_key = None
        bridge.field_topology_loaded = False
        bridge.selected = bridge.measurement = None
        bridge.measure_points = []
        bridge.command_consumer = CommandConsumer("renderer-a")
        bridge.interaction_key = interaction_key
        bridge.command_task = bridge.reset_task = None
        bridge.command_seq = 0
        bridge.materials = {}
        bridge.camera_transforms = {"overview": Gf.Matrix4d(1)}
        bridge.error = None
        bridge.alive = True
        bridge.capture_pending = False
        bridge.capture_path = None
        bridge.render_resolution = (2560, 1440)
        bridge.interactive_resolution = (1920, 1080)
        bridge.settle_seconds = .75
        bridge.last_camera_pose = None
        bridge.last_camera_motion = 0
        bridge.quality = "detail"
        bridge.fps = 30.
        bridge._report = Mock()
        bridge._collect_components()
        bridge.geometry_controller = self.module.GeometryController(bridge.stage)
        self.data = {
            "surface_points": np.array([[6, 0, 0], [6, .2, 0], [6, .2, 1], [7, 0, 0], [7, .2, 0], [7, .2, 1]], dtype=np.float32),
            "surface_triangles": np.array([[0, 1, 2], [3, 4, 5]], dtype=np.int32),
            "surface_triangle_component": np.array([0, 1]),
            "temperature_rgb": np.full((6, 3), .2, dtype=np.float32),
            "heatflux_rgb": np.full((6, 3), .4, dtype=np.float32),
            "heatflux_log_rgb": np.full((6, 3), .7, dtype=np.float32),
            "delta_temperature_rgb": np.full((6, 3), .6, dtype=np.float32),
            "delta_heatflux_rgb": np.full((6, 3), .8, dtype=np.float32),
            "surface_normals": np.tile([1., 0., 0.], (6, 1)).astype(np.float32),
            "slice_points": np.array([[1., 0, 0], [1., 0, 1], [2., 0, 1]], dtype=np.float32),
            "slice_triangles": np.array([[0, 1, 2]], dtype=np.int32),
            "slice_rgb": np.full((3, 3), .4, dtype=np.float32),
            "magnetic_lines": np.array([[[4., 0, 0], [4., 1, 0]]], dtype=np.float32),
            "field_line_B_T": np.array([[2., 12.]], dtype=np.float32),
            "field_line_rgb": np.array([[[.1, .2, .8], [.9, .3, .1]]], dtype=np.float32),
        }
        self.reference = {"key": "field-a", "revision": 1, "topology_key": "topo-a", "equilibrium_key": "eq-a", "schema_version": 2, "path": "fields/a.npz"}
        bridge.load_field_packet = Mock(return_value=self.data)
        self.snapshot = {"server_epoch": "server-a", "revision": 1, "field_ref": self.reference,
                         "state": {**DEFAULT_STATE, "equilibrium": "reference", "cutaway": 0, "mode": "temperature", "visible": {}}, "commands": [], "command_ack_seq": 0}

    async def asyncTearDown(self):
        for task in (self.bridge.command_task, self.bridge.reset_task):
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    def publish(self):
        (self.bridge.runtime / "state.json").write_text(json.dumps(self.snapshot), encoding="utf-8")
        self.bridge._poll()

    async def test_update_waits_for_scene_setup_before_accepting_state(self):
        bridge = self.bridge
        bridge.scene_ready = False
        bridge.last_frame = bridge.last_report = time.perf_counter()
        bridge.last_poll, bridge.fps = 0, 0
        bridge._poll, bridge._selection_sync, bridge._update_quality = Mock(), Mock(), Mock()
        bridge._update(None)
        bridge._poll.assert_not_called()
        bridge.scene_ready = True
        bridge._update(None)
        bridge._poll.assert_called_once()

    async def test_all_modes_keep_rt2_and_report_accurate_status(self):
        bridge = self.bridge
        bridge.fps, bridge.quality = 30., "detail"
        settings = self.module.carb.settings.get_settings()
        context = self.module.omni.usd.get_context()
        modes = ("assembly", "volume", "temperature", "heatflux", "delta_temperature", "delta_heatflux", "slice", "magnetic", "assembly")
        with patch.object(context, "reset_renderer_accumulation") as broad_reset:
            for revision, mode in enumerate(modes, 1):
                settings.set("/rtx-transient/post/dlss/forceParamReset", False)
                self.snapshot["revision"] = revision
                self.snapshot["state"]["mode"] = mode
                self.publish()
                await bridge.reset_task
                self.assertTrue(settings.get("/rtx-transient/post/dlss/forceParamReset"))
                self.module.FusionTwinExtension._report(bridge)
                status = json.loads((bridge.runtime / "renderer.json").read_text(encoding="utf-8"))
                self.assertEqual(status["render_mode"], "RealTimePathTracing")
                self.assertTrue(status["rt2_enabled"])
                self.assertIn("RTX Real-Time 2.0", status["engine"])
                self.assertIsNone(status["samples_per_pixel"])
                self.assertIsNone(status["accumulation_samples"])
                self.assertEqual(status["sampling_strategy"], "temporal_reconstruction")
                self.assertEqual(status["render_reset"]["revision"], revision)
            broad_reset.assert_not_called()

    async def test_heat_scale_updates_colour_without_new_physics_or_topology(self):
        self.snapshot["state"].update(mode="heatflux", heatScale="linear")
        self.publish()
        path = "/World/Fields/Surface/sector_00/blanket"
        mesh = UsdGeom.Mesh.Get(self.bridge.stage, path)
        points = np.array(mesh.GetPointsAttr().Get())
        linear = np.array(mesh.GetDisplayColorPrimvar().Get())
        self.snapshot["revision"] += 1
        self.snapshot["state"]["heatScale"] = "log"
        self.publish()
        logarithmic = np.array(mesh.GetDisplayColorPrimvar().Get())
        self.assertFalse(np.array_equal(linear, logarithmic))
        np.testing.assert_array_equal(mesh.GetPointsAttr().Get(), points)
        self.assertEqual(self.bridge.applied_field_key, self.reference["key"])
        self.assertEqual(self.bridge.color_key, (self.reference["key"], "heatflux_log_rgb"))

    async def test_magnetic_colour_and_small_direction_animation_leave_traces_fixed(self):
        self.data["magnetic_lines"] = np.stack([np.column_stack((np.full(60, i+4), np.linspace(0, 10, 60), np.zeros(60)))
                                               for i in range(24)]).astype(np.float32)
        self.data["field_line_B_T"] = np.full((24, 60), 6., dtype=np.float32)
        self.data["field_line_rgb"] = np.full((24, 60, 3), .5, dtype=np.float32)
        self.snapshot["state"].update(mode="magnetic", lineMotion=True, fieldLines=True)
        self.publish()
        lines = UsdGeom.BasisCurves.Get(self.bridge.stage, "/World/Fields/FieldLines")
        markers = UsdGeom.BasisCurves.Get(self.bridge.stage, "/World/Fields/DirectionMarkers")
        original = np.array(lines.GetPointsAttr().Get())
        first = np.array(markers.GetPointsAttr().Get())
        self.assertEqual(len(first), 384)
        self.assertEqual(len(lines.GetDisplayColorPrimvar().Get()), 24*60)
        self.assertEqual(lines.GetDisplayColorPrimvar().GetInterpolation(), "vertex")
        np.testing.assert_allclose(UsdGeom.PrimvarsAPI(lines).GetPrimvar("magneticFieldTesla").Get(), 6.)
        self.bridge._animate_field_lines(self.bridge.last_line_update + .1)
        moved = np.array(markers.GetPointsAttr().Get())
        self.assertFalse(np.array_equal(first, moved))
        np.testing.assert_array_equal(lines.GetPointsAttr().Get(), original)
        self.bridge._animate_field_lines(self.bridge.last_line_update + .01)
        np.testing.assert_array_equal(markers.GetPointsAttr().Get(), moved)
        self.snapshot["state"]["lineMotion"] = False
        self.snapshot["revision"] += 1
        self.publish()
        self.bridge._animate_field_lines(self.bridge.last_line_update + .2)
        np.testing.assert_array_equal(markers.GetPointsAttr().Get(), moved)
        self.assertEqual(markers.ComputeVisibility(), "invisible")
        self.assertEqual(lines.ComputeVisibility(), "inherited")

    async def test_assembly_changes_resolution_without_switching_the_rt2_engine(self):
        bridge = self.bridge
        bridge.state = {**DEFAULT_STATE, "mode": "assembly"}
        settings = self.module.carb.settings.get_settings()
        bridge._update_quality(10.)
        self.assertEqual(bridge.quality, "interaction")
        self.assertEqual(settings.get("/rtx/rendermode"), "RealTimePathTracing")
        self.assertEqual(self.viewport.resolution, bridge.interactive_resolution)
        bridge._update_quality(10.74)
        self.assertEqual(bridge.quality, "interaction")
        bridge._update_quality(10.76)
        self.assertEqual(bridge.quality, "detail")
        self.assertEqual(settings.get("/rtx/rendermode"), "RealTimePathTracing")
        self.assertEqual(self.viewport.resolution, bridge.render_resolution)

        camera = UsdGeom.Xformable(bridge.stage.GetPrimAtPath(self.viewport.camera_path))
        camera.MakeMatrixXform().Set(Gf.Matrix4d().SetTranslate(Gf.Vec3d(1, 0, 0)))
        bridge._update_quality(12.)
        self.assertEqual(bridge.last_camera_motion, 12.)
        self.assertEqual(settings.get("/rtx/rendermode"), "RealTimePathTracing")
        bridge._update_quality(13.)
        self.assertEqual(settings.get("/rtx/rendermode"), "RealTimePathTracing")
        for control in ("orbit", "playing"):
            with self.subTest(control=control):
                bridge.state[control] = True
                bridge._update_quality(14.)
                self.assertEqual(bridge.quality, "interaction")
                self.assertEqual(settings.get("/rtx/rendermode"), "RealTimePathTracing")
                bridge.state[control] = False
                bridge._update_quality(15.)
                self.assertEqual(settings.get("/rtx/rendermode"), "RealTimePathTracing")
        bridge.state["orbit"] = True
        bridge.capture_pending = True
        bridge._update_quality(16.)
        self.assertEqual(bridge.quality, "detail")
        self.assertEqual(self.viewport.resolution, bridge.render_resolution)
        self.assertEqual(settings.get("/rtx/rendermode"), "RealTimePathTracing")

    async def test_all_views_keep_rt2_when_the_camera_has_settled(self):
        bridge = self.bridge
        settings = self.module.carb.settings.get_settings()
        for mode in ("assembly", "magnetic", "volume", "temperature", "heatflux", "delta_temperature", "delta_heatflux", "slice"):
            with self.subTest(mode=mode):
                bridge.state = {**DEFAULT_STATE, "mode": mode}
                bridge.last_camera_pose = None
                bridge._update_quality(10.)
                bridge._update_quality(20.)
                self.assertEqual(bridge.quality, "detail")
                self.assertEqual(self.viewport.resolution, bridge.render_resolution)
                self.assertEqual(settings.get("/rtx/rendermode"), "RealTimePathTracing")

    async def test_continuous_field_updates_share_pending_reset_and_report_latest_packet(self):
        bridge = self.bridge
        frames = asyncio.Queue()

        async def next_update():
            frame = asyncio.get_running_loop().create_future()
            frames.put_nowait(frame)
            await frame

        settings = self.module.carb.settings.get_settings()
        context = self.module.omni.usd.get_context()
        app = types.SimpleNamespace(next_update_async=next_update)
        with patch.object(self.module.omni.kit.app, "get_app", return_value=app), \
                patch.object(context, "reset_renderer_accumulation") as broad_reset, \
                patch.object(settings, "set", wraps=settings.set) as set_setting:
            self.publish()
            pending = bridge.reset_task
            for revision in (2, 3, 4):
                frame = await asyncio.wait_for(frames.get(), timeout=1)
                self.assertIs(bridge.reset_task, pending)
                self.assertFalse(pending.done())
                self.assertFalse(settings.get("/rtx-transient/post/dlss/forceParamReset"))
                self.snapshot["revision"] = revision
                self.snapshot["state"]["phase"] = revision / 10
                self.snapshot["field_ref"] = {**self.reference, "key": f"field-{revision}", "revision": revision}
                self.publish()
                self.assertIs(bridge.reset_task, pending)
                self.assertEqual(pending.cancelling(), 0)
                frame.set_result(None)
            await asyncio.wait_for(pending, timeout=1)
            self.assertEqual(bridge.render_reset["revision"], 4)
            self.assertEqual(bridge.render_reset["field_key"], "field-4")
            self.assertIsInstance(bridge.render_reset["time"], float)
            self.assertTrue(settings.get("/rtx-transient/post/dlss/forceParamReset"))
            self.assertEqual(sum(call.args == ("/rtx-transient/post/dlss/forceParamReset", True)
                                 for call in set_setting.call_args_list), 1)
            broad_reset.assert_not_called()
            self.module.FusionTwinExtension._report(bridge)
            status = json.loads((bridge.runtime / "renderer.json").read_text(encoding="utf-8"))
            self.assertEqual(status["render_reset"], bridge.render_reset)

            # A completed reset must not prevent the next field from requesting one.
            settings.set("/rtx-transient/post/dlss/forceParamReset", False)
            self.snapshot["revision"] = 5
            self.snapshot["state"]["phase"] = .5
            self.snapshot["field_ref"] = {**self.reference, "key": "field-5", "revision": 5}
            self.publish()
            following = bridge.reset_task
            self.assertIsNot(following, pending)
            # A pure field update settles for one frame and includes newer packets.
            frame = await asyncio.wait_for(frames.get(), timeout=1)
            self.assertFalse(settings.get("/rtx-transient/post/dlss/forceParamReset"))
            self.snapshot["revision"] = 6
            self.snapshot["state"]["phase"] = .6
            self.snapshot["field_ref"] = {**self.reference, "key": "field-6", "revision": 6}
            self.publish()
            self.assertIs(bridge.reset_task, following)
            self.assertEqual(following.cancelling(), 0)
            frame.set_result(None)
            await asyncio.wait_for(following, timeout=1)
            self.assertTrue(frames.empty())
            self.assertEqual(bridge.render_reset["revision"], 6)
            self.assertEqual(bridge.render_reset["field_key"], "field-6")
            self.assertEqual(sum(call.args == ("/rtx-transient/post/dlss/forceParamReset", True)
                                 for call in set_setting.call_args_list), 2)
            broad_reset.assert_not_called()

    async def test_field_updates_do_not_rewrite_static_curves_or_reload_on_view_changes(self):
        self.publish()
        self.assertEqual(self.bridge.load_field_packet.call_count, 1)
        changes = []
        notice = Tf.Notice.Register(Usd.Notice.ObjectsChanged, lambda event, sender: changes.extend(str(path) for path in event.GetChangedInfoOnlyPaths()), self.bridge.stage)
        self.snapshot["revision"] = 2
        self.snapshot["state"]["selected"] = "blanket"
        self.publish()
        self.assertEqual(self.bridge.load_field_packet.call_count, 1)
        self.snapshot["revision"] = 3
        self.snapshot["field_ref"] = {**self.reference, "key": "field-b", "revision": 3}
        self.bridge.load_field_packet.return_value = {**self.data, "temperature_rgb": np.full((6, 3), .7, dtype=np.float32)}
        self.publish()
        self.assertEqual(self.bridge.load_field_packet.call_count, 2)
        notice.Revoke()
        self.assertFalse(any(path.endswith("FieldLines.points") for path in changes), changes)
        self.assertFalse(any("/Surface/sector_" in path and path.endswith(".points") for path in changes), changes)
        self.assertTrue(any(path.endswith("primvars:displayColor") for path in changes))
        self.assertEqual(self.bridge.applied_field_key, "field-b")

    async def test_design_switch_rebuilds_fields_and_clears_old_session_geometry(self):
        self.publish()
        self.bridge.stage.GetPrimAtPath("/World/Machine/blanket").CreateAttribute("oldSessionMarker", self.module.Sdf.ValueTypeNames.Bool).Set(True)
        self.bridge.measure_points = [[1, 2, 3]]
        self.snapshot["state"]["design"] = "longleg"
        self.snapshot["revision"] = 2
        self.snapshot["field_ref"] = {**self.reference, "key": "longleg", "topology_key": "topo-longleg", "equilibrium_key": "eq-longleg"}
        self.publish()
        self.assertEqual(self.bridge.stage.GetPrimAtPath("/World/Machine").GetVariantSet("design").GetVariantSelection(), "longleg")
        self.assertFalse(self.bridge.stage.GetPrimAtPath("/World/Machine/blanket").GetAttribute("oldSessionMarker"))
        self.assertFalse(self.bridge.measure_points)
        self.assertEqual(self.bridge.topology_key, "topo-longleg")
        self.assertFalse(self.bridge.stage.GetCompositionErrors())

    async def test_measurement_ack_waits_for_query_callback(self):
        self.publish()
        queue = CommandQueue()
        renderer = {"ready": True, "renderer_epoch": "renderer-a"}
        record = queue.submit({"request_id": "measure", "type": "measure", "x": .5, "y": .5}, renderer,
                              {"design": "conventional", "equilibrium": "reference", "topology_key": "topo-a"})
        snapshot = {"server_epoch": queue.epoch, "commands": queue.active(), "command_ack_seq": 0}
        self.bridge.command_consumer.synchronize(snapshot)
        command = self.bridge.command_consumer.next(snapshot)
        task = asyncio.create_task(self.bridge._execute_command(command))
        self.bridge.command_task = task
        await asyncio.sleep(0)
        self.assertFalse(self.bridge.command_consumer.acks)
        callback = self.viewport.request_query.call_args.args[1]
        callback("/World/Machine/blanket/sector_00/p000", Gf.Vec3d(1, 2, 3))
        await task
        ack = self.bridge.command_consumer.acks[record["request_id"]]
        self.assertEqual(ack["status"], "completed")
        self.assertEqual(ack["result"]["measurement"]["type"], "point")

    async def test_changed_scene_cancels_query_without_appending_a_point(self):
        self.publish()
        self.bridge.state["design"] = "longleg"
        record = {"request_id": "stale", "seq": 1, "server_epoch": "server-a", "renderer_epoch": "renderer-a",
                  "context": {"design": "conventional", "topology_key": "topo-a"}, "action": {"type": "measure", "x": .5, "y": .5}}
        await self.bridge._execute_command(record)
        self.assertEqual(self.bridge.command_consumer.acks["stale"]["status"], "cancelled")
        self.viewport.request_query.assert_not_called()
        self.assertFalse(self.bridge.measure_points)

    async def test_view_change_during_async_query_cancels_stale_pick(self):
        self.publish()
        record = {"request_id": "stale-view", "seq": 1, "server_epoch": "server-a", "renderer_epoch": "renderer-a",
                  "context": {"topology_key": "topo-a", "interaction_key": interaction_key(self.bridge.state)},
                  "action": {"type": "measure", "x": .5, "y": .5}}
        task = asyncio.create_task(self.bridge._execute_command(record))
        self.bridge.command_task = task
        await asyncio.sleep(0)
        callback = self.viewport.request_query.call_args.args[1]
        self.bridge.state["cutaway"] = 100
        callback("/World/Machine/blanket/sector_00/p000", Gf.Vec3d(1, 2, 3))
        await task
        self.assertEqual(self.bridge.command_consumer.acks["stale-view"]["status"], "cancelled")
        self.assertFalse(self.bridge.measure_points)

    async def test_heat_and_selection_updates_during_query_preserve_measurement(self):
        self.publish()
        record = {"request_id": "stable-geometry", "seq": 1, "server_epoch": "server-a", "renderer_epoch": "renderer-a",
                  "context": {"topology_key": "topo-a", "field_key": "old-field", "interaction_key": interaction_key(self.bridge.state)},
                  "action": {"type": "measure", "x": .5, "y": .5}}
        task = asyncio.create_task(self.bridge._execute_command(record))
        self.bridge.command_task = task
        await asyncio.sleep(0)
        self.bridge.state.update(power=2400, selected="blanket", language="en")
        self.bridge.applied_field_key = "new-field"
        callback = self.viewport.request_query.call_args.args[1]
        callback("/World/Machine/blanket/sector_00/p000", Gf.Vec3d(1, 2, 3))
        await task
        self.assertEqual(self.bridge.command_consumer.acks["stable-geometry"]["status"], "completed")
        self.assertEqual(self.bridge.measure_points, [[1., 2., 3.]])

    async def test_capture_retry_returns_same_immutable_file(self):
        calls = []
        def capture(viewport, filename):
            self.assertEqual(viewport.resolution, self.bridge.render_resolution)
            self.assertEqual(self.module.carb.settings.get_settings().get("/rtx/rendermode"), "RealTimePathTracing")
            calls.append(filename)
            frame = f"capture-{len(calls)}".encode()
            class Capture:
                async def wait_for_result(self, completion_frames):
                    Path(filename).write_bytes(frame)
            return Capture()
        with patch.object(self.module, "capture_viewport_to_file", side_effect=capture):
            first = await self.bridge._capture("same-request", raise_errors=True)
            original = (self.bridge.runtime / first["capture_path"].removeprefix("runtime/")).read_bytes()
            again = await self.bridge._capture("same-request", raise_errors=True)
            await self.bridge._capture("different-request", raise_errors=True)
        self.assertEqual(first, again)
        self.assertEqual(len(calls), 2)
        self.assertEqual((self.bridge.runtime / first["capture_path"].removeprefix("runtime/")).read_bytes(), original)
        self.assertNotEqual((self.bridge.runtime / "preview.png").read_bytes(), original)
        self.assertTrue(first["capture_url"].startswith("/api/captures/"))


class SceneDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "tools/build_scene.py"
        spec = importlib.util.spec_from_file_location("fusion_scene_test", path)
        cls.builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.builder)

    def test_engineering_hall_is_small_and_separate_from_source_cad(self):
        builder = self.builder
        stage = Usd.Stage.CreateInMemory()
        builder.material_library(stage)
        builder.environment(stage)
        environment = stage.GetPrimAtPath("/World/Environment")
        self.assertTrue(environment.GetCustomDataByKey("visualizationOnly"))
        self.assertFalse(stage.GetPrimAtPath("/World/Machine"))
        self.assertFalse(stage.GetPrimAtPath("/World/Environment/GreenTrace"))
        self.assertFalse(stage.GetPrimAtPath("/World/Environment/Plinth"))
        self.assertTrue(stage.GetPrimAtPath("/World/Environment/Crane/Hoist"))
        self.assertTrue(stage.GetPrimAtPath("/World/Environment/Platform/Grating"))
        far_wall = stage.GetPrimAtPath("/World/Environment/Hall/SideWall_0")
        near_wall = stage.GetPrimAtPath("/World/Environment/Hall/SideWall_2")
        wall_bounds = UsdGeom.BBoxCache(0, ["default"])
        self.assertEqual(wall_bounds.ComputeWorldBound(far_wall).ComputeAlignedRange().GetMin()[1], -28.)
        self.assertEqual(wall_bounds.ComputeWorldBound(near_wall).ComputeAlignedRange().GetMin()[1], -5.)
        people = stage.GetPrimAtPath("/World/Environment/ScaleReferences").GetChildren()
        self.assertEqual(len(people), 4)
        bounds = UsdGeom.BBoxCache(0, ["default"])
        for person in people:
            self.assertEqual(person.GetCustomDataByKey("referenceHeightMeters"), 1.8)
            self.assertAlmostEqual(bounds.ComputeWorldBound(person).ComputeAlignedRange().GetSize()[2], 1.8, places=5)
        triangles = sum(len(UsdGeom.Mesh(p).GetFaceVertexCountsAttr().Get()) for p in Usd.PrimRange(environment)
                        if p.IsA(UsdGeom.Mesh))
        self.assertLess(triangles, 30_000)
        self.assertLess(sum(1 for _ in Usd.PrimRange(environment)), 160)

    def test_fixed_engineering_lenses_have_no_depth_of_field(self):
        stage = Usd.Stage.CreateInMemory()
        views = self.builder.cameras(stage)
        self.assertEqual(set(views), {"overview", "front", "top", "section", "divertor"})
        for view in views.values():
            camera = UsdGeom.Camera.Get(stage, view["usd_path"])
            self.assertGreaterEqual(camera.GetFocalLengthAttr().Get(), 35)
            self.assertLessEqual(camera.GetFocalLengthAttr().Get(), 50)
            self.assertEqual(camera.GetFStopAttr().Get(), 0.)
            self.assertEqual(camera.GetHorizontalApertureAttr().Get()/camera.GetVerticalApertureAttr().Get(), 16/9)
        self.assertLess(views["overview"]["eye_m"][2], 20)
        self.assertEqual(views["overview"]["target_m"], [0, 0, 0])
        self.assertEqual(views["overview"]["focal_length_mm"], 36)
        self.assertLess(views["divertor"]["target_m"][2], -7)

    def test_hall_camera_cut_hides_only_near_wall_and_linked_columns(self):
        stage = Usd.Stage.CreateInMemory()
        self.builder.material_library(stage)
        self.builder.environment(stage)
        machine = UsdGeom.Xform.Define(stage, "/World/Machine")
        machine.CreateVisibilityAttr("inherited")
        stage.SetEditTarget(stage.GetSessionLayer())
        module = load_bridge(types.SimpleNamespace())
        bridge = object.__new__(module.FusionTwinExtension)
        bridge.stage, bridge.state = stage, {"explode": 0, "visible": {"blanket": True}}
        bridge._collect_hall_walls()
        self.assertEqual(len(bridge.hall_walls), 3)
        changed = []
        def notice(event, sender):
            changed.extend(map(str, event.GetChangedInfoOnlyPaths()))
        registration = Tf.Notice.Register(Usd.Notice.ObjectsChanged, notice, stage)
        self.addCleanup(registration.Revoke)
        for eye, expected, columns in (
            ((62.64, -69.12, 17), set(), None),
            ((93, 0, 17), {"SideWall_2"}, "RightColumns"),
            ((-93, 0, 17), {"SideWall_0"}, "LeftColumns"),
            ((0, 93, 17), {"BackWall"}, "BackColumns"),
            ((0, 0, 17), set(), None),
            ((0, 0, 96), set(), None),
            ((93, 0, 300), set(), None),
            ((93, -200, 17), set(), None),
        ):
            bridge._update_hall_visibility(Gf.Vec3d(*eye))
            self.assertEqual(set(bridge.hall_hidden_walls), expected, eye)
            for wall in bridge.hall_walls:
                self.assertEqual(wall["attributes"][0].Get(), "invisible" if wall["name"] in expected else "inherited")
            if columns:
                self.assertEqual(UsdGeom.Imageable(stage.GetPrimAtPath("/World/Environment/Hall/"+columns)).ComputeVisibility(), "invisible")
            written = len(changed)
            bridge._update_hall_visibility(Gf.Vec3d(*eye))
            self.assertEqual(len(changed), written, "Unchanged wall state must not author USD again")
        self.assertTrue(changed)
        properties = [path for path in changed if "." in path.rsplit("/", 1)[-1]]
        self.assertTrue(all(path.startswith("/World/Environment/Hall/") and path.endswith(".visibility")
                            for path in properties), properties)
        self.assertFalse(stage.GetSessionLayer().GetPrimAtPath("/World/Machine"))
        self.assertEqual(machine.ComputeVisibility(), "inherited")
        self.assertEqual(bridge.state["visible"], {"blanket": True})

    def test_overview_has_crane_below_header_and_gentle_pit_fill(self):
        from pxr import UsdLux
        stage = Usd.Stage.CreateInMemory()
        self.builder.material_library(stage)
        self.builder.cameras(stage)
        self.builder.lighting(stage)
        cam = UsdGeom.Camera.Get(stage, "/World/Cameras/overview").GetCamera(0)
        # Native QHD projection; also check the same composition at a 1920x1080 UI.
        points = np.array([[-32, 11, 23.5, 1], [0, 11, 22.7, 1]])
        clip = points @ np.asarray(cam.frustum.ComputeViewMatrix()) @ np.asarray(cam.frustum.ComputeProjectionMatrix())
        ndc = clip[:, :2] / clip[:, 3, None]
        pixels = np.c_[(ndc[:, 0]+1)*960, (1-ndc[:, 1])*540]
        self.assertTrue(np.all(pixels[:, 1] > 70), pixels)
        self.assertTrue(np.all(pixels[:, 0] < 1920-408), pixels)
        fill = UsdLux.RectLight.Get(stage, "/World/Lighting/PitFill")
        key = UsdLux.RectLight.Get(stage, "/World/Lighting/Key")
        self.assertGreater(fill.GetIntensityAttr().Get(), 0)
        self.assertLess(fill.GetIntensityAttr().Get(), key.GetIntensityAttr().Get()*.15)

    def test_portable_mdl_assets_keep_preview_fallback_and_weak_plasma(self):
        from pxr import UsdShade
        with tempfile.TemporaryDirectory(prefix="fusion-material-test-") as directory:
            target = Path(directory)
            self.builder.write_material_assets(target)
            for name in ("concrete_normal.png", "brushed_normal.png"):
                content = (target / "materials" / name).read_bytes()
                self.assertEqual(content[:8], b"\x89PNG\r\n\x1a\n")
                self.assertLess(len(content), 200_000)
            self.assertIn("::OmniPBR::OmniPBR", (target / "materials/FusionPBR.mdl").read_text())
        stage = Usd.Stage.CreateInMemory()
        self.builder.material_library(stage)
        for name in ("steel", "tungsten", "copper", "concrete"):
            material = UsdShade.Material.Get(stage, "/World/Looks/" + name)
            self.assertTrue(material.GetSurfaceOutput().HasConnectedSource())
            self.assertTrue(material.GetSurfaceOutput("mdl").HasConnectedSource())
        plasma = UsdShade.Shader.Get(stage, "/World/Looks/plasma/Surface")
        self.assertLess(plasma.GetInput("opacity").Get(), .1)


if __name__ == "__main__":
    unittest.main()
