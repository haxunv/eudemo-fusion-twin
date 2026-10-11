"""RTWT control requests and a real SimData / NanoVDB / IndeX result pipeline."""

import asyncio
from collections import OrderedDict
import hashlib
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
import carb.eventdispatcher
import carb.settings
import omni.kit.app
import omni.kit.livestream.messaging as messaging
import warp as wp
import warp_simdata as simdata
from omni.cae.core import cache
from omni.cae.core.commands import execute_command
from omni.cae.schema import viz as cae_viz
from omni.cae.simdata import GetField
from omni.cae.viz import Controller
from omni.cae.viz.controller import EVT_OPERATOR_COMPLETE
from omni.cae.viz.listener import Listener
from omni.rtwt.controller import control_registry, web_api
from omni.rtwt.controller.callbacks import CallbackRegistry
from omni.rtwt.inference import results
from pxr import Gf, OmniSci, OmniSciVtk, Sdf, Usd, UsdGeom, UsdVol, Vt

DATASET = "/World/FusionResults"
VOLUME = "/World/CAE/PlasmaVolume"
MODEL_VERSION = "axisymmetric-profile-grid-v2"
GRID_ORIGIN = (-32,-32,-28)
GRID_SPACING = (28/64,28/64,.3)
COLOR_STOPS = [0,.03,.15,.4,.7,1]
COLOR_RGBA = [(0,0,0,0),(0,0,0,0),(.03,.18,.62,.025),
              (.05,.75,.85,.08),(1,.67,.08,.25),(.95,.12,.025,.5)]
_active = None


def _volume_visibility(state):
    return [(VOLUME, "visibility", "inherited" if state.get("mode") == "volume" else "invisible")]


@web_api.app.request
async def fusion_set_state(state: dict):
    """SDK writes pass through the same validated, serialized HTTP coordinator."""
    if _active is None:
        return {"accepted": False, "error": "Fusion workflow is unavailable"}
    def post():
        server = carb.settings.get_settings().get("/fusion/serverUrl") or "http://127.0.0.1:8765"
        request = Request(server.rstrip("/")+"/api/state",
                          data=json.dumps(state).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=45) as response:
            return json.load(response)
    try:
        result = await asyncio.to_thread(post)
        _active.status["rtwt_remote_writes"] += 1
        return {"accepted": True, "accepted_revision": result.get("revision"), "state": result.get("state")}
    except Exception as exc:
        return {"accepted": False, "error": f"{type(exc).__name__}: {exc}"}


@web_api.app.request
def fusion_get_cache():
    return dict(_active.status) if _active else {"available": False}


def _sample_volume(data, cutaway):
    """Revolve the committed synthetic keV profile; do not infer new physics."""
    points = data["slice_points"]
    radii, heights = np.unique(points[:,0]), np.unique(points[:,2])
    temperatures = data["slice_temperature_keV"].copy()
    active = np.zeros(len(points),dtype=bool)
    active[np.unique(data["slice_triangles"])] = True
    temperatures[~active] = 0
    profile = temperatures.reshape(len(radii),len(heights))
    dimensions = (64,64,56)
    spacing = GRID_SPACING
    # The stock CAE XAC shader samples p / voxel_size - 0.5. Keep the same
    # world-space voxel centres in the profile, NanoVDB and ImageData metadata.
    origin = tuple((GRID_ORIGIN[i]+.5)*spacing[i] for i in range(3))
    x,y,z = np.meshgrid(*(origin[i]+np.arange(dimensions[i])*spacing[i] for i in range(3)),indexing="ij")
    r = np.sqrt(x*x+y*y)
    ri = np.clip(np.searchsorted(radii,r)-1,0,len(radii)-2)
    zi = np.clip(np.searchsorted(heights,z)-1,0,len(heights)-2)
    rf = np.clip((r-radii[ri])/(radii[ri+1]-radii[ri]),0,1)
    zf = np.clip((z-heights[zi])/(heights[zi+1]-heights[zi]),0,1)
    values = ((profile[ri,zi]*(1-rf)+profile[ri+1,zi]*rf)*(1-zf)
              +(profile[ri,zi+1]*(1-rf)+profile[ri+1,zi+1]*rf)*zf)
    angle = np.mod(np.degrees(np.arctan2(y,x)),360)
    mask = ((r>=radii[0]) & (r<=radii[-1]) & (z>=heights[0]) & (z<=heights[-1])
            & (angle<=360-float(cutaway)))
    values = np.where(mask,values,0).astype(np.float32)
    return values,origin,spacing


class NvidiaWorkflow:
    """submit is non-blocking; status reports volume completion independently."""

    def __init__(self, stage, root):
        global _active
        self.stage, self.root = stage, Path(root)
        self.task = None
        self.latest = None
        self.closed = False
        self.volume_key = None
        self.operator_events = {}
        self.operator_subscription = carb.eventdispatcher.get_eventdispatcher().observe_event(
            observer_name="fusion.workflow.operators",event_name=EVT_OPERATOR_COMPLETE+":immediate",
            on_event=self._operator_complete)
        self.memory_keys = OrderedDict()
        self.status = {"rtwt_workflow": "fusion-engineering", "rtwt_ready": False,
                       "rtwt_remote_writes": 0, "rtwt_control_count": 0,
                       "volume_pending": False, "pending_volume_field_key": None, "volume_error": None,
                       "applied_volume_field_key": None, "applied_volume_key": None,
                       "index_native_volume": False, "volume_roundtrip": None,
                       "volume_cache_hits": 0, "volume_cache_misses": 0,
                       "volume_units": "keV", "volume_source": "synthetic axisymmetric temperature profile",
                       "volume_colormap":{"positions":COLOR_STOPS,"rgba":COLOR_RGBA}}
        self.directory = self.root / "runtime/nvidia"
        self.directory.mkdir(parents=True,exist_ok=True)
        CallbackRegistry.register("fusion.engineering.volume_visibility",_volume_visibility)
        self.dataset = OmniSci.Dataset.Define(stage,DATASET).GetPrim()
        self.dataset.AddAppliedSchema("RtwtInferenceResultsAPI")
        self.dataset.CreateAttribute("omni:rtwt:inference_results:revision",Sdf.ValueTypeNames.Token).Set("")
        self.dataset.CreateAttribute("fusion:effectiveThermalPowerMW",Sdf.ValueTypeNames.Float).Set(2000.)
        self.dataset.SetCustomDataByKey("dataProvenance","Synthetic profile on public Bluemira equilibrium; not a transport solution")
        field = OmniSci.FieldAPI.Apply(self.dataset,"Temperature")
        field.CreateNameAttr("Temperature")
        field.CreateAssociationAttr("node")
        OmniSci.ArrayAPI.Apply(self.dataset,"Temperature")
        UsdGeom.Xform.Define(stage,"/World/CAE")
        UsdVol.Volume.Define(stage,VOLUME).CreateVisibilityAttr("invisible")
        self.app_state = stage.DefinePrim("/World/AppState","Prim")
        self.app_state.AddAppliedSchema("FusionTwinAppStateAPI")
        cae_viz.OperatorAPI.Apply(self.app_state).CreateEnabledAttr(True)
        registry = control_registry.get_workflow_registry()
        if registry is None or any(not c.usd_type for c in registry.controls()):
            raise RuntimeError("RTWT workflow/schema configuration is incomplete")
        self.keys = set(registry.short_to_full())
        self.status.update(rtwt_registered=True,rtwt_control_count=len(self.keys))
        messaging.register_event_type_to_send("fusion_cache_signal")
        _active = self

    def submit(self, state, field_data, field_ref):
        self.latest = (dict(state),field_data,dict(field_ref))
        pending = state.get("mode") == "volume"
        self.status.update(volume_pending=pending,pending_volume_field_key=field_ref["key"] if pending else None)
        if self.task is None or self.task.done():
            self.task = asyncio.ensure_future(self._run())

    def _operator_complete(self, event):
        path = event.get("prim_path")
        if path in ("/World/AppState",VOLUME):
            count = self.operator_events.get(path,{}).get("count",0)+1
            self.operator_events[path] = {"count":count,"success":bool(event.get("success"))}

    def close(self):
        global _active
        self.closed = True
        self.latest = None
        self.status.update(volume_pending=False,pending_volume_field_key=None)
        if self.task:
            self.task.cancel()
        self.operator_subscription.reset()
        if _active is self:
            _active = None
        CallbackRegistry.unregister("fusion.engineering.volume_visibility")

    def _emit_cache(self, state, field_key, volume_key):
        omni.kit.app.queue_event("fusion_cache_signal",{
            "state":state,"field_key":field_key,"volume_key":volume_key,
            "hits":self.status["volume_cache_hits"],"misses":self.status["volume_cache_misses"]})

    def _volume_bytes(self, state, data, reference):
        identity = f"{MODEL_VERSION}:{reference['key']}:{float(state.get('cutaway',80))}"
        key = hashlib.sha256(identity.encode()).hexdigest()[:32]
        memory_key = f"fusion:volume:{key}"
        cached = cache.get(memory_key)
        disk = self.directory / f"{key}.npz"
        source = "memory"
        if cached is None and disk.is_file():
            with np.load(disk,allow_pickle=False) as archive:
                cached = {name:archive[name].copy() for name in archive.files}
            source = "disk"
        if cached is None:
            self.status["volume_cache_misses"] += 1
            self._emit_cache("miss",reference["key"],key)
            values,origin,spacing = _sample_volume(data,state.get("cutaway",80))
            field = simdata.Field.from_array(wp.array(values.ravel(order="F"),dtype=wp.float32,device="cuda:0"),simdata.AssociationType.NODE)
            volume = field.to_nanovdb(dims=wp.vec3i(*values.shape),origin=wp.vec3i(*GRID_ORIGIN),
                                     voxel_size=wp.vec3f(*spacing),device="cuda:0")
            raw = volume.get_data().array().numpy().copy()
            cached = {"buffer":raw,"origin":np.array(origin),"spacing":np.array(spacing),
                      "dimensions":np.array(values.shape),"range":np.array((values.min(),values.max())),
                      "field_key":np.array(reference["key"]),"model_version":np.array(MODEL_VERSION)}
            temporary = disk.with_suffix(".tmp.npz")
            np.savez_compressed(temporary,**cached)
            temporary.replace(disk)
            source = "computed"
        else:
            self.status["volume_cache_hits"] += 1
            self._emit_cache("hit",reference["key"],key)
        cache.put_ex(memory_key,cached,prims=[cache.PrimWatch(self.dataset,on="delete")],force=True)
        self.memory_keys[memory_key] = None
        self.memory_keys.move_to_end(memory_key)
        while len(self.memory_keys)>6:
            oldest,_=self.memory_keys.popitem(last=False)
            cache.remove(oldest)
        files=sorted(self.directory.glob("*.npz"),key=lambda p:p.stat().st_mtime,reverse=True)
        protected={key,self.volume_key}
        for stale in files[16:]:
            if stale.stem not in protected and len(stale.stem)==32 and all(c in "0123456789abcdef" for c in stale.stem):
                stale.unlink()
        return key,cached,source

    async def _publish(self, state, data, reference):
        key,payload,source = self._volume_bytes(state,data,reference)
        if self.volume_key == key:
            self.status["volume_cache_source"] = source
            return key,source
        dimensions = tuple(int(x) for x in payload["dimensions"])
        image = OmniSciVtk.ImageDataAPI.Apply(self.dataset)
        image.CreateMinExtentAttr(Gf.Vec3i(*GRID_ORIGIN))
        image.CreateMaxExtentAttr(Gf.Vec3i(*(GRID_ORIGIN[i]+dimensions[i]-1 for i in range(3))))
        image.CreateOriginAttr(Gf.Vec3f(*(float(s)*.5 for s in payload["spacing"])))
        image.CreateSpacingAttr(Gf.Vec3f(*map(float,payload["spacing"])))
        revision = results.publish_results(self.dataset,{"Temperature":payload["buffer"]},origin=GRID_ORIGIN,dimensions=dimensions)
        field = await GetField.invoke(self.dataset,"Temperature",device="cuda:0",timeCode=Usd.TimeCode.Default())
        actual_range = np.asarray(field.get_range(),dtype=float).reshape(-1)
        if not np.allclose(actual_range,payload["range"],rtol=1e-4,atol=1e-5):
            raise RuntimeError(f"NanoVDB/SimData round-trip mismatch: {actual_range}")
        if not np.array_equal(field.get_data().array().numpy(),payload["buffer"]):
            raise RuntimeError("NanoVDB/SimData round-trip changed the grid buffer")
        decoded = field.to_array().numpy().reshape(dimensions,order="F")
        expected,_,_ = _sample_volume(data,state.get("cutaway",80))
        if not np.array_equal(decoded,expected):
            raise RuntimeError("NanoVDB voxel values do not match the sampled profile")
        if not self.stage.GetPrimAtPath(VOLUME+"/Material"):
            await execute_command("CreateCaeVizVolume",dataset_path=DATASET,prim_path=VOLUME,type="vdb")
            volume = self.stage.GetPrimAtPath(VOLUME)
            cae_viz.FieldSelectionAPI(volume,"colors").CreateFieldNamesAttr().Set(["Temperature"])
            colormap = self.stage.GetPrimAtPath(VOLUME+"/Material/Colormap")
            colormap.GetAttribute("rgbaPoints").Set(Vt.Vec4fArray([Gf.Vec4f(*color) for color in COLOR_RGBA]))
            colormap.GetAttribute("xPoints").Set(Vt.FloatArray(COLOR_STOPS))
        self.stage.GetPrimAtPath(VOLUME+"/Material/Colormap").GetAttribute("domain").Set(Gf.Vec2f(0,max(float(payload["range"][1]),.01)))
        self.status.update(volume_grid=list(dimensions),volume_range_keV=actual_range.tolist(),
                           rtwt_result_revision=revision,volume_cache_source=source,nanovdb_roundtrip=True,
                           volume_roundtrip="exact",volume_grid_voxels=int(np.prod(dimensions)))
        return key,source

    async def _run(self):
        while self.latest is not None and not self.closed:
            state,data,reference = self.latest
            self.latest = None
            try:
                self.status["volume_error"] = None
                key = None
                prior_volume_events = self.operator_events.get(VOLUME,{}).get("count",0)
                native_cache_key = f"[viz:index_compute_task_vdb]::{VOLUME}"
                prior_native = cache.get(native_cache_key,timeCode=Usd.TimeCode.EarliestTime())
                if state.get("mode") == "volume":
                    key,_ = await self._publish(state,data,reference)
                await Listener.wait_for_sync_idle()
                accepted = await web_api.set_state({k:v for k,v in state.items() if k in self.keys})
                if accepted is not True:
                    raise RuntimeError("RTWT did not accept committed application state")
                # USD/Fabric population and the CAE listener run on subsequent Kit updates.
                # Wait for the actual binding/output, not merely for set_state to return.
                expected_visibility = "inherited" if key is not None else "invisible"
                for _ in range(200):
                    await omni.kit.app.get_app().next_update_async()
                    volume_event = self.operator_events.get(VOLUME,{})
                    output_ready = (key is None or key == self.volume_key or
                                    (volume_event.get("count",0)>prior_volume_events and volume_event.get("success")))
                    bindings_ready = (self.stage.GetPrimAtPath(VOLUME).GetAttribute("visibility").Get()==expected_visibility
                                      and abs(self.dataset.GetAttribute("fusion:effectiveThermalPowerMW").Get()-state["power"])<.01)
                    if output_ready and bindings_ready:
                        break
                    await asyncio.sleep(.01)
                else:
                    raise RuntimeError(f"RTWT/IndeX completion timeout: {self.operator_events}")
                if key is not None:
                    dataset = cache.get(f"[viz:index_volume]::{VOLUME}",timeCode=Usd.TimeCode.EarliestTime())
                    volume = self.stage.GetPrimAtPath(VOLUME)
                    # FieldSelectionAPI:colors maps the source Temperature to its instance name.
                    if dataset is None or "colors" not in dataset.get_field_names():
                        names = dataset.get_field_names() if dataset is not None else None
                        raise RuntimeError(f"IndeX did not publish selected colors; available fields: {names}")
                    # CAE skips voxelization (and cae_mask) when the source is already NanoVDB.
                    if not isinstance(dataset.get_field("colors").get_data(),wp.Volume):
                        raise RuntimeError("IndeX did not retain the NanoVDB field")
                    if not volume.GetAttribute("nvindex:composite").Get():
                        raise RuntimeError("IndeX volume has not enabled compositing")
                    for _ in range(200):
                        native = cache.get(native_cache_key,timeCode=Usd.TimeCode.EarliestTime())
                        if native and (key==self.volume_key or native is not prior_native):
                            break
                        await omni.kit.app.get_app().next_update_async()
                    else:
                        raise RuntimeError("IndeX GPU compute did not adopt the current NanoVDB buffer")
                    self.volume_key = key
                    self.status.update(applied_volume_field_key=reference["key"],applied_volume_key=key,
                                       volume_mask_angle=float(state.get("cutaway",80)),volume_pending=False,
                                       index_fields=dataset.get_field_names(),index_source_field="Temperature",index_composite=True,
                                       index_depth_mode=carb.settings.get_settings().get("/rtx/index/compositeDepthMode"),
                                       index_native_volume=True)
                    self._emit_cache("ready",reference["key"],key)
                else:
                    self.status["volume_pending"] = False
                self.status["rtwt_state"] = web_api.get_state()
                self.status["rtwt_ready"] = True
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status.update(volume_error=f"{type(exc).__name__}: {exc}",volume_pending=False)
            finally:
                pending = self.latest is not None and self.latest[0].get("mode") == "volume"
                self.status.update(volume_pending=pending,
                                   pending_volume_field_key=self.latest[2]["key"] if pending else None)
