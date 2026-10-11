"""Kit-only, single-process IndeX/CAD depth-compositing comparison.

Run with fusion_workflow_probe.kit after stopping the main project Kit. The
HTTP service and its committed state are left unchanged. Output is kept in
runtime/depth-probe; every image uses the same committed field and camera.
"""

import asyncio
import importlib.util
import json
import os
import shutil
import tempfile
import traceback
from pathlib import Path

import carb.settings
import numpy as np
import omni.kit.app
import omni.usd
from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport
from pxr import Gf, UsdGeom


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def probe():
    root = Path(os.environ["FUSION_TWIN_ROOT"])
    out = root / "runtime/depth-probe" / os.environ.get("FUSION_DEPTH_RUN", "baseline")
    out.mkdir(parents=True, exist_ok=True)
    app = omni.kit.app.get_app()
    settings = carb.settings.get_settings()
    report = {"ok": False, "cases": []}
    workflow = None
    capture_dir = Path(tempfile.mkdtemp(prefix="fusion-depth-probe-"))
    try:
        snapshot = json.loads((root / "runtime/state.json").read_text(encoding="utf-8"))
        reference = snapshot["field_ref"]
        with np.load(root / "runtime" / reference["path"], allow_pickle=False) as archive:
            data = {name: archive[name].copy() for name in archive.files}
        state = {**snapshot["state"], "mode": "volume", "cutaway": 80,
                 "opacity": 1., "explode": 0., "orbit": False, "playing": False}
        report["source_field_ref"] = reference
        report["state"] = state
        await omni.usd.get_context().open_stage_async(str(root / "assets/scene/fusion.usda"))
        stage = omni.usd.get_context().get_stage()
        stage.SetEditTarget(stage.GetSessionLayer())
        stage.GetPrimAtPath("/World/Machine").GetVariantSet("design").SetVariantSelection(state["design"])
        bridge = root / "kit/extensions/fusion.twin.bridge/fusion/twin/bridge"
        geometry = load_module("fusion_depth_geometry", bridge / "geometry.py")
        geometry.GeometryController(stage).apply(state)
        UsdGeom.Imageable(stage.GetPrimAtPath("/World/Machine/plasma")).CreateVisibilityAttr().Set("invisible")
        camera = UsdGeom.Camera(stage.GetPrimAtPath("/World/Cameras/overview"))
        target = Gf.Vec3d(0, 0, -2.6)
        eye = UsdGeom.Xformable(camera).GetLocalTransformation().ExtractTranslation()
        eye = target + (eye - target) * 1.5
        camera_matrix = Gf.Matrix4d().SetLookAt(eye, target, Gf.Vec3d(0, 0, 1)).GetInverse()
        UsdGeom.Xformable(camera).MakeMatrixXform().Set(camera_matrix)
        for name, multiplier in (("Key", 1.65), ("Fill", 1.45), ("Section", 1.8)):
            light = stage.GetPrimAtPath(f"/World/Lighting/{name}")
            if light and light.GetAttribute("inputs:intensity"):
                intensity = light.GetAttribute("inputs:intensity")
                intensity.Set(intensity.Get() * multiplier)
        viewport = get_active_viewport()
        viewport.resolution = (1280, 720)
        viewport.camera_path = str(camera.GetPath())
        module = load_module("fusion_depth_workflow", bridge / "nvidia_workflow.py")
        workflow = module.NvidiaWorkflow(stage, root)
        workflow.submit(state, data, reference)
        await asyncio.wait_for(workflow.task, timeout=180)
        if workflow.status.get("volume_error"):
            raise RuntimeError(workflow.status["volume_error"])
        report["workflow"] = dict(workflow.status)
        report["camera_matrix"] = [list(row) for row in camera_matrix]
        report["meters_per_unit"] = UsdGeom.GetStageMetersPerUnit(stage)
        report["initial_settings"] = {key: settings.get(key) for key in (
            "/app/asyncRendering", "/rtx/index/compositeEnabled", "/rtx/index/outputDepthBuffer",
            "/rtx-transient/post/aa/limitedOps", "/rtx/post/aa/op",
            "/persistent/rtx/modes/rt/enabled", "/persistent/rtx/modes/rt2/enabled",
            "/persistent/rtx/modes/pt/enabled", "/rtx-transient/rt2Enabled")}
        cases = [("PathTracing", offset, mode) for offset in (2.8, 0.) for mode in (0, 1, 2, 3)]
        cases += [("RaytracedLighting", 0., mode) for mode in (1, 3)]
        cases += [("RealTimePathTracing", offset, mode) for offset in (2.8, 0.) for mode in (1, 3)]
        if os.environ.get("FUSION_DEPTH_CASES"):
            cases = json.loads(os.environ["FUSION_DEPTH_CASES"])
        volume = UsdGeom.Imageable(stage.GetPrimAtPath(module.VOLUME))
        for case_spec in cases:
            renderer, offset, mode = case_spec[:3]
            overrides = case_spec[3] if len(case_spec) > 3 else {}
            for key, value in overrides.items():
                settings.set(key, value)
            settings.set("/rtx/rendermode", renderer)
            settings.set("/rtx/index/compositeDepthMode", mode)
            camera.GetHorizontalApertureOffsetAttr().Set(offset)
            for shown in (False, True):
                volume.CreateVisibilityAttr().Set("inherited" if shown else "invisible")
                for _ in range(5):
                    await app.next_update_async()
                omni.usd.get_context().reset_renderer_accumulation()
                for _ in range(45):
                    await app.next_update_async()
                name = f"{renderer}-offset{offset}-depth{mode}-{'volume' if shown else 'cad'}.png"
                capture = capture_viewport_to_file(viewport, str(capture_dir / name))
                await capture.wait_for_result(completion_frames=8)
                shutil.copy2(capture_dir / name, out / name)
                case = {"renderer": renderer, "offset": offset, "depth_mode": mode,
                        "volume": shown, "image": name, "overrides": overrides,
                        "actual_render_mode": settings.get("/rtx/rendermode"),
                        "actual_depth_mode": settings.get("/rtx/index/compositeDepthMode"),
                        "projection": [list(row) for row in viewport.projection],
                        "view": [list(row) for row in viewport.view]}
                report["cases"].append(case)
                (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
                print(f"DEPTH_PROBE_CAPTURE {name}", flush=True)
        report["ok"] = True
        stage.GetSessionLayer().Export(str(out / "session.usda"))
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if workflow:
            workflow.close()
        (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        app.post_quit(0 if report["ok"] else 1)


asyncio.ensure_future(probe())
