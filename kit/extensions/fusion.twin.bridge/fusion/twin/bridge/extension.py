"""Native USD/RTX controller; all edits live in the session layer."""

import asyncio
import json
import math
import os
import shutil
import tempfile
import time
import traceback
from io import BytesIO
from pathlib import Path

import carb
import omni.ext
import omni.kit.app
import omni.usd
from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport, get_active_viewport_window
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, Vt


class FusionTwinExtension(omni.ext.IExt):
    def on_startup(self, ext_id):
        self.root = Path(os.environ.get("FUSION_TWIN_ROOT", "D:/nv聚变"))
        settings = carb.settings.get_settings()
        settings.set("/rtx/background/source/type", 2)
        settings.set("/rtx/background/source/color", [0.012, 0.018, 0.026])
        self.render_resolution = (
            settings.get("/app/renderer/resolution/width"),
            settings.get("/app/renderer/resolution/height"),
        )
        self.interactive_resolution = (
            settings.get("/fusion/render/interactiveWidth"),
            settings.get("/fusion/render/interactiveHeight"),
        )
        self.settle_seconds = settings.get("/fusion/render/settleSeconds")
        self.last_camera_pose = None
        self.last_camera_motion = time.perf_counter()
        self.quality = "detail"
        self.runtime = self.root / "runtime"
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.stage = None
        self.state = {}
        self.revision = -1
        self.command_seq = 0
        self.last_poll = 0
        self.last_report = 0
        self.last_frame = time.perf_counter()
        self.fps = 0.0
        self.components = {}
        self.sectors = []
        self.materials = {}
        self.camera_transforms = {}
        self.field_topology_loaded = False
        self.original_bindings = {}
        self.measure_points = []
        self.measurement = None
        self.selected = None
        self.error = None
        self.capture_path = None
        self.capture_pending = False
        self.capture_task = None
        self.reset_task = None
        self.field_mtime = 0
        self.orbit_angle = 0.0
        self.alive = True
        self.task = asyncio.ensure_future(self._load())
        self.sub = omni.kit.app.get_app().get_update_event_stream().create_subscription_to_pop(self._update)
        self._report()

    async def _load(self):
        scene_path = self.root / "assets/scene/fusion.usda"
        while self.alive and not scene_path.exists():
            await asyncio.sleep(0.5)
        if not self.alive:
            return
        try:
            result = await omni.usd.get_context().open_stage_async(str(scene_path))
            if isinstance(result, tuple) and not result[0]:
                raise RuntimeError(str(result[1]))
            self.stage = omni.usd.get_context().get_stage()
            self.stage.SetEditTarget(self.stage.GetSessionLayer())
            UsdGeom.Xform.Define(self.stage, "/World/Fields")
            UsdGeom.Xform.Define(self.stage, "/World/Fields/Surface")
            machine = self.stage.GetPrimAtPath("/World/Machine")
            if not machine:
                raise RuntimeError("Scene has no /World/Machine assembly")
            for component in machine.GetChildren():
                self.components[component.GetName()] = component
                for sector in component.GetChildren():
                    if sector.GetName().startswith("sector_"):
                        number = int(sector.GetName().rsplit("_", 1)[1])
                        self.sectors.append((component.GetName(), number, sector))
                for prim in Usd.PrimRange(component):
                    if prim.IsA(UsdGeom.Mesh):
                        material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
                        self.original_bindings[str(prim.GetPath())] = material.GetPath() if material else None
            cameras = self.stage.GetPrimAtPath("/World/Cameras")
            if cameras:
                for camera in cameras.GetChildren():
                    if camera.GetName() == "overview":
                        transform = UsdGeom.Xformable(camera).GetLocalTransformation()
                        eye = transform.ExtractTranslation()
                        target = Gf.Vec3d(0, 0, -2.6)
                        eye = target + (eye - target) * 1.5
                        matrix = Gf.Matrix4d().SetLookAt(eye, target, Gf.Vec3d(0, 0, 1)).GetInverse()
                        UsdGeom.Xformable(camera).MakeMatrixXform().Set(matrix)
                        UsdGeom.Camera(camera).GetHorizontalApertureOffsetAttr().Set(2.8)
                    self.camera_transforms[camera.GetName()] = UsdGeom.Xformable(camera).GetLocalTransformation()
            for light_name, multiplier in (("Key", 1.65), ("Fill", 1.45), ("Section", 1.8)):
                light = self.stage.GetPrimAtPath(f"/World/Lighting/{light_name}")
                if light and light.GetAttribute("inputs:intensity"):
                    intensity = light.GetAttribute("inputs:intensity")
                    intensity.Set(float(intensity.Get()) * multiplier)
            fill = self.stage.GetPrimAtPath("/World/Lighting/StudioFill")
            if fill:
                fill.GetAttribute("inputs:intensity").Set(380.0)
            floor = self.stage.GetPrimAtPath("/World/Environment/Floor")
            if floor:
                floor.GetAttribute("xformOp:scale").Set(Gf.Vec3f(1000, 1000, 0.6))
            for _ in range(12):
                await omni.kit.app.get_app().next_update_async()
            self.viewport = get_active_viewport()
            if self.viewport:
                import omni.ui as ui
                window = get_active_viewport_window()
                if window:
                    window.dock_tab_bar_visible = False
                    window.dock_tab_bar_enabled = False
                    window.flags |= ui.WINDOW_FLAGS_NO_TITLE_BAR | ui.WINDOW_FLAGS_NO_MOVE | ui.WINDOW_FLAGS_NO_RESIZE
                self.viewport.fill_frame = False
                self.viewport.resolution = self.render_resolution
                self._set_camera("overview")
            self.error = None
            self._poll(force=True)
            for _ in range(120):
                await omni.kit.app.get_app().next_update_async()
            await self._capture()
        except Exception:
            self.error = traceback.format_exc()
            carb.log_error(self.error)
            self._report()

    def _update(self, event):
        now = time.perf_counter()
        dt = now - self.last_frame
        self.last_frame = now
        if dt > 0:
            self.fps = self.fps * 0.92 + min(1.0 / dt, 200.0) * 0.08
        if self.stage and now - self.last_poll >= 0.1:
            self.last_poll = now
            try:
                self._poll()
                self._selection_sync()
            except Exception:
                self.error = traceback.format_exc()
                carb.log_error(self.error)
        if self.stage and self.state.get("orbit"):
            self.orbit_angle += dt * 0.1
            self._orbit()
        if self.stage:
            self._update_quality(now)
        if now - self.last_report > 0.5:
            self.last_report = now
            self._report()

    def _update_quality(self, now):
        viewport = get_active_viewport()
        if not viewport:
            return
        camera = self.stage.GetPrimAtPath(viewport.camera_path)
        if not camera:
            return
        transform = UsdGeom.Xformable(camera).GetLocalTransformation()
        pose = (str(viewport.camera_path), tuple(value for row in transform for value in row))
        if pose != self.last_camera_pose:
            self.last_camera_pose = pose
            self.last_camera_motion = now
        interacting = self.state.get("orbit") or self.state.get("playing") or now - self.last_camera_motion < self.settle_seconds
        self.quality = "interaction" if interacting and not self.capture_pending else "detail"
        resolution = self.interactive_resolution if self.quality == "interaction" else self.render_resolution
        if tuple(viewport.resolution) != resolution:
            viewport.resolution = resolution

    def _poll(self, force=False):
        request_path = self.runtime / "state.json"
        if not request_path.exists():
            return
        try:
            request = json.loads(request_path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, PermissionError):
            return
        revision = int(request.get("revision", 0))
        if force or revision != self.revision:
            previous = self.state
            self.state = request.get("state", {})
            self._apply_state(previous)
            self.revision = revision
        seq = int(request.get("command_seq", 0))
        if seq != self.command_seq:
            self.command_seq = seq
            command = request.get("command") or {}
            if isinstance(command, str):
                command = {"type": command}
            self._command(command)
        fields_path = self.runtime / "fields.json"
        if fields_path.exists():
            mtime = fields_path.stat().st_mtime_ns
            if mtime != self.field_mtime:
                self.field_mtime = mtime
                self._apply_fields()

    def _apply_state(self, previous):
        state = self.state
        view = state.get("view", "overview")
        if view != previous.get("view"):
            self._set_camera(view)
        visible = state.get("visible", {})
        for name, component in self.components.items():
            UsdGeom.Imageable(component).GetVisibilityAttr().Set("inherited" if visible.get(name, True) else "invisible")
        cutaway = float(state.get("cutaway", 80))
        hidden_count = max(0, min(18, round(cutaway / 20)))
        exploded = float(state.get("explode", 0))
        for component_id, number, prim in self.sectors:
            UsdGeom.Imageable(prim).GetVisibilityAttr().Set("invisible" if number >= 18 - hidden_count else "inherited")
            xform = UsdGeom.Xformable(prim)
            op = next((item for item in xform.GetOrderedXformOps() if item.GetOpName() == "xformOp:translate:explode"), None)
            if op is None:
                op = xform.AddTranslateOp(opSuffix="explode")
            # This translate follows each sector's rotateZ, so the direction is local.
            angle = math.radians(10)
            component_index = list(self.components).index(component_id)
            offset = exploded * (1.0 + component_index * 0.32)
            op.Set(Gf.Vec3d(math.cos(angle) * offset, math.sin(angle) * offset, 0))
        selected = state.get("selected")
        if selected != previous.get("selected"):
            self._select(selected)
        self._apply_materials()
        self._field_visibility()
        field_prim = self.stage.GetPrimAtPath("/World/Fields/FieldLines")
        if field_prim:
            show = bool(state.get("fieldLines")) or state.get("mode") == "magnetic"
            UsdGeom.Imageable(field_prim).GetVisibilityAttr().Set("inherited" if show else "invisible")
        if any(state.get(key) != previous.get(key) for key in ("view", "mode", "visible", "cutaway", "explode", "opacity", "fieldLines")):
            if self.reset_task:
                self.reset_task.cancel()
            self.reset_task = asyncio.ensure_future(self._reset_renderer())

    async def _reset_renderer(self):
        app = omni.kit.app.get_app()
        context = omni.usd.get_context()
        for _ in range(3):
            await app.next_update_async()
        while self.alive and context.get_stage_streaming_status():
            await app.next_update_async()
        if self.alive:
            context.reset_renderer_accumulation()

    def _set_camera(self, name):
        viewport = get_active_viewport()
        camera_path = f"/World/Cameras/{name}"
        if viewport and self.stage.GetPrimAtPath(camera_path):
            viewport.camera_path = camera_path
            self.camera_view = name

    def _orbit(self):
        camera = UsdGeom.Camera.Get(self.stage, "/World/Cameras/overview")
        if not camera:
            return
        a = self.orbit_angle
        default_eye = self.camera_transforms.get("overview", Gf.Matrix4d(1)).ExtractTranslation()
        radius = math.hypot(default_eye[0], default_eye[1]) or 76
        eye = Gf.Vec3d(radius * math.cos(a), radius * math.sin(a), default_eye[2] or 34)
        mat = Gf.Matrix4d().SetLookAt(eye, Gf.Vec3d(0, 0, 0), Gf.Vec3d(0, 0, 1)).GetInverse()
        camera.GetPrim().GetAttribute("xformOp:transform").Set(mat)
        self._set_camera("overview")

    def _select(self, component_id):
        self.selected = component_id if component_id in self.components else None
        self._highlight_selection()
        self._measure_component()

    def _highlight_selection(self):
        paths = []
        if self.selected:
            if self.state.get("mode") in ("temperature", "heatflux") and self.selected in ("blanket", "divertor") and self.field_topology_loaded:
                surface = self.stage.GetPrimAtPath("/World/Fields/Surface")
                for sector in surface.GetChildren():
                    mesh = sector.GetChild(self.selected)
                    if mesh:
                        paths.append(str(mesh.GetPath()))
            else:
                paths = [str(self.components[self.selected].GetPath())]
        selection = omni.usd.get_context().get_selection()
        if selection.get_selected_prim_paths() != paths:
            selection.set_selected_prim_paths(paths, True)

    def _selection_sync(self):
        paths = omni.usd.get_context().get_selection().get_selected_prim_paths()
        selected = None
        for path in paths:
            if path.startswith("/World/Machine/"):
                selected = path.split("/")[3]
                break
            if path.startswith("/World/Fields/Surface/") and path.rsplit("/", 1)[-1] in self.components:
                selected = path.rsplit("/", 1)[-1]
                break
        if selected != self.selected:
            self.selected = selected
            self._measure_component()

    def _measure_component(self):
        if not self.selected or self.selected not in self.components:
            return
        cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render], useExtentsHint=True)
        bounds = cache.ComputeWorldBound(self.components[self.selected]).ComputeAlignedRange()
        dims = bounds.GetSize()
        self.measurement = {"type": "bounds", "component": self.selected, "dimensions_m": [round(float(v), 3) for v in dims], "unit": "m"}

    def _command(self, command):
        kind = command.get("type", command.get("action", ""))
        if kind in ("measure_start", "measure_clear"):
            self.measure_points = []
            self.measurement = None
        elif kind == "capture":
            if not self.capture_pending:
                self.capture_task = asyncio.ensure_future(self._capture())
        elif kind == "reset_camera":
            view = command.get("view", self.state.get("view", "overview"))
            camera = self.stage.GetPrimAtPath(f"/World/Cameras/{view}")
            if camera and view in self.camera_transforms:
                UsdGeom.Xformable(camera).MakeMatrixXform().Set(self.camera_transforms[view])
            self._set_camera(view)
        elif kind in ("pick", "measure") and "x" in command and "y" in command:
            viewport = get_active_viewport()
            if viewport:
                width, height = viewport.resolution
                pixel = (int(float(command["x"]) * width), int(float(command["y"]) * height))
                def done(path, world_pos, *_):
                    if path and path.startswith("/World/Machine/"):
                        self._select(path.split("/")[3])
                    elif path and path.startswith("/World/Fields/Surface/"):
                        self._select(path.rsplit("/", 1)[-1])
                    if kind == "measure" and path:
                        self.measure_points.append([float(v) for v in world_pos])
                        self.measure_points = self.measure_points[-2:]
                        if len(self.measure_points) == 2:
                            a, b = self.measure_points
                            distance = math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))
                            self.measurement = {"type": "distance", "points": self.measure_points, "distance_m": round(distance, 4), "unit": "m"}
                        else:
                            self.measurement = {"type": "point", "points": self.measure_points, "unit": "m"}
                    self._report()
                viewport.request_query(pixel, done)
        elif kind == "measure":
            self._measure_component()

    def _analysis_material(self, name, color, opacity):
        path = f"/World/Analysis/Materials/{name}"
        material = UsdShade.Material.Define(self.stage, path)
        shader = UsdShade.Shader.Define(self.stage, path + "/Surface")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.43)
        shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.15)
        shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(opacity)
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
        self.materials[name] = material
        return material

    def _apply_materials(self):
        mode = self.state.get("mode", "assembly")
        opacity = float(self.state.get("opacity", 1.0))
        for index, (name, component) in enumerate(self.components.items()):
            color = (0.48, 0.57, 0.65)
            material = self._analysis_material(name, color, opacity) if opacity < 0.999 else None
            component_binding = UsdShade.MaterialBindingAPI.Apply(component)
            if material:
                component_binding.Bind(material, UsdShade.Tokens.strongerThanDescendants)
            else:
                component_binding.UnbindDirectBinding()
            for prim in Usd.PrimRange(component):
                if not prim.IsA(UsdGeom.Mesh):
                    continue
                binding = UsdShade.MaterialBindingAPI.Apply(prim)
                if material:
                    binding.Bind(material)
                else:
                    original = self.original_bindings.get(str(prim.GetPath()))
                    if original:
                        binding.Bind(UsdShade.Material(self.stage.GetPrimAtPath(original)))
                    else:
                        binding.UnbindDirectBinding()
        self._apply_fields()

    def _apply_fields(self):
        # The producer owns engineering calculations; this consumer only draws its outputs.
        self.stage.GetPrimAtPath("/World/Fields/Surface").SetActive(True)
        fields_path = self.runtime / "fields.json"
        if not fields_path.exists():
            return
        try:
            fields = json.loads(fields_path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, PermissionError):
            return
        mode = self.state.get("mode", "assembly")
        npz_path = self.runtime / "fields.npz"
        if not npz_path.exists():
            return
        import numpy as np
        def linear_colors(values):
            rgb = np.asarray(values, dtype=np.float32)
            return Vt.Vec3fArray.FromNumpy(np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4).astype(np.float32))
        with np.load(BytesIO(npz_path.read_bytes()), allow_pickle=False) as data:
            if "surface_points" in data:
                points = Vt.Vec3fArray.FromNumpy(np.asarray(data["surface_points"], dtype=np.float32))
                triangles = np.asarray(data["surface_triangles"], dtype=np.int32)
                field_key = "heatflux_rgb" if mode == "heatflux" else "temperature_rgb"
                colors = linear_colors(data[field_key])
                material = self._vertex_material()
                for number in range(18):
                    sector = UsdGeom.Xform.Define(self.stage, f"/World/Fields/Surface/sector_{number:02d}")
                    if not self.field_topology_loaded:
                        sector.AddRotateZOp().Set(number * 20.0)
                    for component_index, component_id in enumerate(("blanket", "divertor")):
                        mesh = UsdGeom.Mesh.Define(self.stage, str(sector.GetPath()) + "/" + component_id)
                        if not self.field_topology_loaded:
                            subset = triangles[data["surface_triangle_component"] == component_index] if "surface_triangle_component" in data else triangles
                            mesh.CreatePointsAttr(points)
                            mesh.CreateFaceVertexCountsAttr(Vt.IntArray([3] * len(subset)))
                            mesh.CreateFaceVertexIndicesAttr(Vt.IntArray.FromNumpy(subset.reshape(-1)))
                            mesh.CreateSubdivisionSchemeAttr("none")
                            mesh.CreateDoubleSidedAttr(True)
                            mesh.AddTranslateOp(opSuffix="explode")
                            UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material)
                        mesh.CreateDisplayColorPrimvar(UsdGeom.Tokens.vertex).Set(colors)
                self.field_topology_loaded = True
            if "slice_points" in data:
                mesh = UsdGeom.Mesh.Define(self.stage, "/World/Fields/Slice")
                if not mesh.GetPointsAttr().HasAuthoredValueOpinion():
                    points = Vt.Vec3fArray.FromNumpy(np.asarray(data["slice_points"], dtype=np.float32))
                    triangles = np.asarray(data["slice_triangles"], dtype=np.int32)
                    mesh.CreatePointsAttr(points)
                    mesh.CreateFaceVertexCountsAttr(Vt.IntArray([3] * len(triangles)))
                    mesh.CreateFaceVertexIndicesAttr(Vt.IntArray.FromNumpy(triangles.reshape(-1)))
                    mesh.CreateSubdivisionSchemeAttr("none")
                    mesh.CreateDoubleSidedAttr(True)
                    UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(self._vertex_material())
                mesh.CreateDisplayColorPrimvar(UsdGeom.Tokens.vertex).Set(linear_colors(data["slice_rgb"]))
            if "magnetic_lines" in data:
                lines = data["magnetic_lines"]
                curves = UsdGeom.BasisCurves.Define(self.stage, "/World/Fields/FieldLines")
                curves.CreateTypeAttr("linear")
                curves.CreateWrapAttr("nonperiodic")
                curves.CreateCurveVertexCountsAttr(Vt.IntArray([len(line) for line in lines]))
                curves.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(np.asarray(lines.reshape(-1, 3), dtype=np.float32)))
                curves.CreateWidthsAttr([0.028])
                curves.SetWidthsInterpolation("constant")
                curves.CreateDisplayColorAttr([Gf.Vec3f(0.12, 0.8, 0.95)])
                show = self.state.get("fieldLines") or mode == "magnetic"
                curves.GetVisibilityAttr().Set("inherited" if show else "invisible")
        self._field_visibility()

    def _vertex_material(self):
        path = "/World/Fields/Materials/ScalarField"
        material = UsdShade.Material.Define(self.stage, path)
        shader = UsdShade.Shader.Define(self.stage, path + "/Surface")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(1.0)
        shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
        reader = UsdShade.Shader.Define(self.stage, path + "/Color")
        reader.CreateIdAttr("UsdPrimvarReader_float3")
        reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("displayColor")
        reader.CreateOutput("result", Sdf.ValueTypeNames.Float3)
        diffuse = shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f)
        diffuse.DisconnectSource()
        diffuse.Set(Gf.Vec3f(0.0))
        shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(reader.ConnectableAPI(), "result")
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
        return material

    def _field_visibility(self):
        mode = self.state.get("mode", "assembly")
        visible = self.state.get("visible", {})
        surface = self.stage.GetPrimAtPath("/World/Fields/Surface")
        show_surface = mode in ("temperature", "heatflux") and self.field_topology_loaded
        if surface:
            UsdGeom.Imageable(surface).GetVisibilityAttr().Set("inherited")
            hidden_count = max(0, min(18, round(float(self.state.get("cutaway", 80)) / 20)))
            for number, prim in enumerate(surface.GetChildren()):
                UsdGeom.Imageable(prim).GetVisibilityAttr().Set("invisible" if number >= 18 - hidden_count else "inherited")
                for child in prim.GetChildren():
                    component_id = child.GetName()
                    UsdGeom.Imageable(child).GetVisibilityAttr().Set("inherited" if visible.get(component_id, True) else "invisible")
                    component_index = list(self.components).index(component_id) if component_id in self.components else 0
                    offset = float(self.state.get("explode", 0)) * (1.0 + component_index * 0.32)
                    child.GetAttribute("xformOp:translate:explode").Set(Gf.Vec3d(math.cos(math.radians(10)) * offset, math.sin(math.radians(10)) * offset, 0))
            surface.SetActive(show_surface)
        for component_id in ("blanket", "divertor"):
            component = self.components.get(component_id)
            if component:
                show = visible.get(component_id, True) and not show_surface
                UsdGeom.Imageable(component).GetVisibilityAttr().Set("inherited" if show else "invisible")
        slice_prim = self.stage.GetPrimAtPath("/World/Fields/Slice")
        if slice_prim:
            UsdGeom.Imageable(slice_prim).GetVisibilityAttr().Set("inherited" if mode == "slice" else "invisible")
        self._highlight_selection()

    async def _capture(self):
        self.capture_pending = True
        try:
            viewport = get_active_viewport()
            if viewport:
                viewport.resolution = self.render_resolution
                target = self.runtime / "preview.png"
                # NVIDIA's image writer does not accept this workspace's Unicode directory.
                with tempfile.TemporaryDirectory(prefix="fusion-rtx-") as temporary:
                    capture_file = Path(temporary) / "preview.png"
                    capture = capture_viewport_to_file(viewport, str(capture_file))
                    await capture.wait_for_result(completion_frames=20)
                    for _ in range(120):
                        if capture_file.exists() and capture_file.stat().st_size > 0:
                            break
                        await omni.kit.app.get_app().next_update_async()
                    if not capture_file.exists():
                        raise RuntimeError("RTX capture did not create an image")
                    staging = self.runtime / "preview.next.png"
                    shutil.copyfile(capture_file, staging)
                    os.replace(staging, target)
                self.capture_path = "runtime/preview.png"
                self.error = None
        except Exception:
            self.error = traceback.format_exc()
            carb.log_error(self.error)
        finally:
            self.capture_pending = False
            self._report()

    def _report(self):
        field_visibility = {}
        viewport = get_active_viewport()
        settings = carb.settings.get_settings()
        if self.stage:
            for path in ("/World/Fields/Surface", "/World/Fields/Surface/sector_00/blanket", "/World/Fields/Surface/sector_00/divertor", "/World/Fields/Slice", "/World/Fields/FieldLines"):
                prim = self.stage.GetPrimAtPath(path)
                if prim:
                    field_visibility[path] = {"active": prim.IsActive(), "authored": UsdGeom.Imageable(prim).GetVisibilityAttr().Get(), "effective": UsdGeom.Imageable(prim).ComputeVisibility()}
        payload = {
            "ready": bool(self.stage and get_active_viewport()),
            "applied_revision": self.revision,
            "fps": round(self.fps, 1),
            "gpu": "NVIDIA GeForce RTX 5070 Ti",
            "engine": "NVIDIA Omniverse Kit 110.1.3 / RTX Path Tracing",
            "render_mode": settings.get("/rtx/rendermode"),
            "samples_per_pixel": settings.get("/rtx/pathtracing/spp"),
            "accumulation_samples": settings.get("/rtx/pathtracing/totalSpp"),
            "selected": self.selected,
            "mode": self.state.get("mode"),
            "field_visibility": field_visibility,
            "visible": {name: UsdGeom.Imageable(prim).ComputeVisibility() != UsdGeom.Tokens.invisible for name, prim in self.components.items()},
            "measurement": self.measurement,
            "error": self.error,
            "capture_path": self.capture_path,
            "capture_pending": self.capture_pending,
            "command_seq": self.command_seq,
            "timestamp": time.time(),
            "resolution": list(self.render_resolution),
            "render_resolution": list(viewport.resolution) if viewport else list(self.render_resolution),
            "quality": self.quality,
        }
        target = self.runtime / "renderer.json"
        tmp = self.runtime / "renderer.tmp"
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, target)
        except PermissionError:
            pass

    def on_shutdown(self):
        self.alive = False
        if self.reset_task:
            self.reset_task.cancel()
        if self.capture_task:
            self.capture_task.cancel()
        if self.task:
            self.task.cancel()
        self.sub = None
