"""Run inside an isolated Kit process; leave live state and Kit untouched."""

import asyncio
import importlib.util
import json
import os
import shutil
import tempfile
import traceback
from pathlib import Path

import numpy as np
import omni.kit.app
import omni.usd
from omni.kit.viewport.utility import capture_viewport_to_file,get_active_viewport
from pxr import Gf,UsdGeom


async def probe():
    root=Path(os.environ["FUSION_TWIN_ROOT"])
    out=root/"runtime/workflow-probe"
    out.mkdir(parents=True,exist_ok=True)
    report={"ok":False,"checks":[]}
    capture_dir=Path(tempfile.mkdtemp(prefix="fusion-workflow-probe-"))
    app=omni.kit.app.get_app()
    workflow=None
    try:
        await omni.usd.get_context().open_stage_async(str(root/"assets/scene/fusion.usda"))
        stage=omni.usd.get_context().get_stage()
        stage.SetEditTarget(stage.GetSessionLayer())
        spec=importlib.util.spec_from_file_location("fusion_workflow_probe",root/"kit/extensions/fusion.twin.bridge/fusion/twin/bridge/nvidia_workflow.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        snapshot=json.loads((root/"runtime/state.json").read_text(encoding="utf-8"))
        reference=snapshot["field_ref"]
        with np.load(root/"runtime"/reference["path"],allow_pickle=False) as archive:
            data={name:archive[name].copy() for name in archive.files}
        state={**snapshot["state"],"mode":"volume","cutaway":80,"orbit":False,"playing":False}
        UsdGeom.Imageable(stage.GetPrimAtPath("/World/Machine")).CreateVisibilityAttr("invisible")
        viewport=get_active_viewport();viewport.resolution=(1280,720);viewport.camera_path="/World/Cameras/overview"
        camera=stage.GetPrimAtPath(viewport.camera_path)
        matrix=Gf.Matrix4d().SetLookAt(Gf.Vec3d(52,-60,33),Gf.Vec3d(0,0,-2),Gf.Vec3d(0,0,1)).GetInverse()
        UsdGeom.Xformable(camera).MakeMatrixXform().Set(matrix)
        workflow=module.NvidiaWorkflow(stage,root)
        workflow.submit({**state,"mode":"assembly","power":1234.},data,reference)
        await asyncio.wait_for(workflow.task,timeout=180)
        report["power_binding_MW"]=workflow.dataset.GetAttribute("fusion:baselineThermalPowerMW").Get()
        if report["power_binding_MW"]!=1234.:
            raise RuntimeError("RTWT attribute binding did not apply")
        for mode,cut in (("volume",80),("assembly",80),("volume",80),("volume",100)):
            state.update(mode=mode,cutaway=cut)
            workflow.submit(state,data,reference)
            await asyncio.wait_for(workflow.task,timeout=180)
            status=dict(workflow.status)
            report["checks"].append({"mode":mode,"cut":cut,"status":status})
            if status.get("volume_error"):
                raise RuntimeError(status["volume_error"])
            if mode=="volume" and status.get("applied_volume_field_key")!=reference["key"]:
                raise RuntimeError("IndeX completion did not acknowledge the source field key")
            if cut==80:
                for _ in range(45):await app.next_update_async()
                filename=f"{mode}-{len(report['checks'])}.png"
                capture=capture_viewport_to_file(viewport,str(capture_dir/filename))
                await capture.wait_for_result(completion_frames=20)
                if not (capture_dir/filename).is_file():
                    raise RuntimeError("Native capture did not create an image")
                shutil.copy2(capture_dir/filename,out/filename)
        report["ok"]=(workflow.status["volume_cache_hits"]>=1
                      and report["checks"][0]["status"]["applied_volume_key"]!=report["checks"][-1]["status"]["applied_volume_key"])
        report["session_layer"]=str(out/"session.usda")
        report["operator_events"]=workflow.operator_events
        stage.GetSessionLayer().Export(str(out/"session.usda"))
    except Exception:
        report["error"]=traceback.format_exc()
    finally:
        if workflow:workflow.close()
        (out/"report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
        app.post_quit(0 if report["ok"] else 1)


asyncio.ensure_future(probe())
