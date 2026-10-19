"""RTWT controls and the plasma volume pipeline: SimData -> NanoVDB -> Kit-CAE -> IndeX."""

import asyncio
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError
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
from omni.cae.viz.controller import EVT_OPERATOR_COMPLETE
from omni.cae.viz.listener import Listener
from omni.rtwt.controller import control_registry, web_api
from omni.rtwt.controller.callbacks import CallbackRegistry
from omni.rtwt.inference import results
from pxr import Gf, OmniSci, OmniSciVtk, Sdf, Tf, Usd, UsdGeom, UsdVol, Vt

DATASET = "/World/FusionResults"
VOLUME = "/World/CAE/PlasmaVolume"
MODEL_VERSION = "axisymmetric-profile-grid-v3-128"
GRID_DIMENSIONS = (128,128,112)
GRID_ORIGIN = (-64,-64,-56)
GRID_SPACING = (28/128,28/128,.15)
COLOR_STOPS = [0,.025,.10,.3,.6,1]
TEMPERATURE_DOMAIN = (0,40)
COLOR_RGBA = [(0,0,0,0),(.07,.03,.19,.01),(.34,.06,.43,.04),
              (.73,.21,.33,.10),(.97,.55,.04,.23),(.99,1,.65,.45)]
PLASMA_RGBA = [(0,0,0,0),(.12,.015,.32,.005),(.35,.035,.75,.025),
               (.74,.10,.95,.065),(1,.33,.76,.15),(1,.80,.95,.28)]
_active = None


def _volume_visibility(state):
    return [(VOLUME, "visibility", "inherited" if state.get("mode") == "volume" else "invisible")]


@web_api.app.request
async def fusion_set_state(state: dict):
    """RTWT writes go through the same validated HTTP coordinator as the browser."""
    if _active is None:
        return {"accepted": False, "error": "Fusion workflow is unavailable"}
    def post():
        server = carb.settings.get_settings().get("/fusion/serverUrl") or "http://127.0.0.1:8765"
        request = Request(server.rstrip("/")+"/api/state",
                          data=json.dumps(state).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=45) as response:
                return json.load(response)
        except HTTPError as exc:
            detail = json.load(exc)
            raise ValueError(detail.get("error", f"HTTP {exc.code}")) from None
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
    """Revolve the R-Z keV slice into the voxel grid, masking the cutaway wedge."""
    points = data["slice_points"]
    radii, heights = np.unique(points[:,0]), np.unique(points[:,2])
    temperatures = data["slice_temperature_keV"].copy()
    active = np.zeros(len(points),dtype=bool)
    active[np.unique(data["slice_triangles"])] = True
    temperatures[~active] = 0
    profile = temperatures.reshape(len(radii),len(heights))
    dimensions = GRID_DIMENSIONS
    spacing = GRID_SPACING
    # The CAE shader samples at p / voxel_size - 0.5; offset origins so voxel centres agree.
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
    """submit() is non-blocking; status reports when the volume actually reaches IndeX."""

    def __init__(self, stage, root):
        global _active
        self.stage, self.root = stage, Path(root)
        self.task = None
        self.latest = None
        self.closed = False
        self.volume_key = None
        self.transfer_style = None
        self.syncing_controls = False
        self.committed_controls = {}
        self.requested_controls = {}
        self.inflight_controls = {}
        self.control_task = None
        self.operator_events = {}
        self.operator_subscription = carb.eventdispatcher.get_eventdispatcher().observe_event(
            observer_name="fusion.workflow.operators",event_name=EVT_OPERATOR_COMPLETE+":immediate",
            on_event=self._operator_complete)
        self.memory_keys = OrderedDict()
        self.status = {"rtwt_workflow": "fusion-engineering", "rtwt_ready": False,
                       "rtwt_remote_writes": 0, "rtwt_control_count": 0,
                       "rtwt_standard_writes": 0, "control_pending": False, "control_error": None,
                       "volume_pending": False, "pending_volume_field_key": None, "volume_error": None,
                       "applied_volume_field_key": None, "applied_volume_key": None,
                       "index_native_volume": False, "volume_roundtrip": None,
                       "volume_cache_hits": 0, "volume_cache_misses": 0,
                       "volume_units": "keV", "volume_source": "synthetic axisymmetric temperature profile",
                       "volume_colormap":{"positions":COLOR_STOPS,"rgba":PLASMA_RGBA,"domain":list(TEMPERATURE_DOMAIN)},
                       "volume_style":"plasma","volume_spacing_m":list(GRID_SPACING)}
        self.directory = self.root / "runtime/nvidia"
        self.directory.mkdir(parents=True,exist_ok=True)
        CallbackRegistry.register("fusion.engineering.volume_visibility",_volume_visibility)
        self.dataset = OmniSci.Dataset.Define(stage,DATASET).GetPrim()
        self.dataset.AddAppliedSchema("RtwtInferenceResultsAPI")
        self.dataset.CreateAttribute("omni:rtwt:inference_results:revision",Sdf.ValueTypeNames.Token).Set("")
        self.dataset.CreateAttribute("fusion:baselineThermalPowerMW",Sdf.ValueTypeNames.Float).Set(2000.)
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
        self.attribute_keys = {full:short for short,full in registry.short_to_full().items()}
        self.state_notice = Tf.Notice.Register(Usd.Notice.ObjectsChanged,self._controls_changed,stage)
        self.status.update(rtwt_registered=True,rtwt_control_count=len(self.keys))
        messaging.register_event_type_to_send("fusion_cache_signal")
        _active = self

    def submit(self, state, field_data, field_ref):
        self.committed_controls = {key:value for key,value in state.items() if key in self.keys}
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
        if self.control_task:
            self.control_task.cancel()
        self.state_notice.Revoke()
        self.operator_subscription.reset()
        if _active is self:
            _active = None
        CallbackRegistry.unregister("fusion.engineering.volume_visibility")

    def _controls_changed(self, notice, stage):
        """Standard RTWT set_state writes USD; forward the change to the validated coordinator."""
        if self.closed or self.syncing_controls or not self.committed_controls:
            return
        for path in notice.GetChangedInfoOnlyPaths():
            if str(path.GetPrimPath()) != "/World/AppState":
                continue
            name = path.name
            key = self.attribute_keys.get(name)
            if key:
                value = self.app_state.GetAttribute(name).Get()
                if (value != self.committed_controls.get(key) or key in self.requested_controls
                        or key in self.inflight_controls):
                    self.requested_controls[key] = value
        if self.requested_controls and (self.control_task is None or self.control_task.done()):
            self.control_task = asyncio.ensure_future(self._commit_control_requests())

    async def _sync_controls(self, state):
        self.syncing_controls = True
        try:
            return await web_api.set_state(state)
        finally:
            self.syncing_controls = False

    async def _commit_control_requests(self):
        await omni.kit.app.get_app().next_update_async()
        while self.requested_controls and not self.closed:
            patch = self.requested_controls
            self.requested_controls = {}
            self.inflight_controls = patch
            self.status.update(control_pending=True,control_error=None)
            result = await fusion_set_state(patch)
            self.inflight_controls = {}
            if result.get("accepted"):
                self.status["rtwt_standard_writes"] += 1
                self.status["control_accepted_revision"] = result["accepted_revision"]
            else:
                self.status["control_error"] = result.get("error","State rejected")
                await self._sync_controls({key:self.committed_controls[key] for key in patch
                                           if key in self.committed_controls and key not in self.requested_controls})
            self.status["control_pending"] = bool(self.requested_controls)

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
            self._apply_transfer(state)
            return key,source
        # The dataset is replaced before IndeX finishes; never reuse the old key after this point.
        self.volume_key = None
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
        self._apply_transfer(state)
        self.status.update(volume_grid=list(dimensions),volume_range_keV=actual_range.tolist(),
                           rtwt_result_revision=revision,volume_cache_source=source,nanovdb_roundtrip=True,
                           volume_roundtrip="exact",volume_grid_voxels=int(np.prod(dimensions)))
        return key,source

    def _apply_transfer(self,state):
        style = state.get("volumeStyle","plasma")
        if style == self.transfer_style:
            return
        colors = PLASMA_RGBA if style == "plasma" else COLOR_RGBA
        colormap = self.stage.GetPrimAtPath(VOLUME+"/Material/Colormap")
        colormap.GetAttribute("rgbaPoints").Set(Vt.Vec4fArray([Gf.Vec4f(*color) for color in colors]))
        colormap.GetAttribute("xPoints").Set(Vt.FloatArray(COLOR_STOPS))
        colormap.GetAttribute("domain").Set(Gf.Vec2f(*TEMPERATURE_DOMAIN))
        self.status.update(volume_style=style,volume_colormap={"positions":COLOR_STOPS,"rgba":colors,
                           "domain":list(TEMPERATURE_DOMAIN)},
                           volume_presentation="illustrative plasma glow" if style == "plasma" else "quantitative synthetic keV")
        self.transfer_style = style

    async def _run(self):
        while self.latest is not None and not self.closed:
            state,data,reference = self.latest
            self.latest = None
            try:
                self.status["volume_error"] = None
                key = None
                await Listener.wait_for_sync_idle()
                accepted = await self._sync_controls({k:v for k,v in state.items() if k in self.keys
                                                     and k not in self.requested_controls and k not in self.inflight_controls})
                if accepted is not True:
                    raise RuntimeError("RTWT did not accept committed application state")
                # CAE skips invisible operators and drops their pending updates: settle visibility first.
                expected_visibility = "inherited" if state.get("mode") == "volume" else "invisible"
                for _ in range(200):
                    await omni.kit.app.get_app().next_update_async()
                    if self.latest is not None:
                        break
                    bindings_ready = (self.stage.GetPrimAtPath(VOLUME).GetAttribute("visibility").Get()==expected_visibility
                                      and abs(self.dataset.GetAttribute("fusion:baselineThermalPowerMW").Get()-state["power"])<.01)
                    if bindings_ready:
                        break
                    await asyncio.sleep(.01)
                else:
                    raise RuntimeError(f"RTWT binding timeout: expected {expected_visibility}, power={state['power']}")
                if self.latest is not None:
                    continue
                await Listener.wait_for_sync_idle()
                prior_volume_events = self.operator_events.get(VOLUME,{}).get("count",0)
                native_cache_key = f"[viz:index_compute_task_vdb]::{VOLUME}"
                prior_native = cache.get(native_cache_key,timeCode=Usd.TimeCode.EarliestTime())
                if state.get("mode") == "volume":
                    key,_ = await self._publish(state,data,reference)
                # CAE runs on later Kit updates; wait for its operator output, not for set_state.
                for _ in range(200):
                    await omni.kit.app.get_app().next_update_async()
                    if self.latest is not None:
                        break
                    volume_event = self.operator_events.get(VOLUME,{})
                    output_ready = (key is None or key == self.volume_key or
                                    (volume_event.get("count",0)>prior_volume_events and volume_event.get("success")))
                    bindings_ready = (self.stage.GetPrimAtPath(VOLUME).GetAttribute("visibility").Get()==expected_visibility
                                      and abs(self.dataset.GetAttribute("fusion:baselineThermalPowerMW").Get()-state["power"])<.01)
                    if output_ready and bindings_ready:
                        break
                    await asyncio.sleep(.01)
                else:
                    raise RuntimeError(f"RTWT/IndeX completion timeout: output={output_ready}, bindings={bindings_ready}, events={self.operator_events}")
                if self.latest is not None:
                    continue
                if key is not None:
                    dataset = cache.get(f"[viz:index_volume]::{VOLUME}",timeCode=Usd.TimeCode.EarliestTime())
                    volume = self.stage.GetPrimAtPath(VOLUME)
                    if dataset is None or "colors" not in dataset.get_field_names():
                        names = dataset.get_field_names() if dataset is not None else None
                        raise RuntimeError(f"IndeX did not publish selected colors; available fields: {names}")
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
