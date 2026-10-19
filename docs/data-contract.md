# Runtime contract

The Windows HTTP service owns validated application state and field computation. Kit consumes atomic snapshots and reports completion. NVIDIA RTWT integration uses the official WebRTC message channel and workflow bindings; the validated HTTP coordinator remains the authority for state changes. No cloud inference or AI agent is required.

## State and fields

`GET /api/state` returns `{server_epoch, revision, state, result, field_ref, renderer, actions}`. `POST /api/state` accepts a partial state. A computation finishes before its state/result pair is committed. State reads and action admission do not hold the compute lock.

`field_ref` contains `path`, `key`, `revision`, `topology_key`, `equilibrium_key`, and `schema_version=2`. Its path is relative to `runtime/`, for example `fields/<key>.npz`. The immutable packet embeds the same identifiers; Kit checks identity, array shapes, finite values and design/equilibrium metadata before applying it. Pure view changes reuse a field reference, so a state revision need not equal a field revision. `renderer.applied_field_key` reports the applied surface/slice field. A file read alone does not prove that a volume has finished rendering.

The field cache only collects packets recorded as published, after the renderer has consumed the relevant snapshot. It protects the latest 16 keys, current state, applied/pending volume, active commands, and snapshots beyond the renderer watermark. It never deletes unknown files or unpublished producer output. Collection and compute publication share a writer lock.

Interactive packets use uncompressed NPZ to avoid compression in the response path; shipped baked cases use DEFLATE. Both encodings carry identical arrays and identity fields. Encoding does not change field keys or numeric results.

## Commands

`POST /api/action` requires `type`, `request_id`, `server_epoch` and `renderer_epoch`. Coordinate `pick` and `measure` also require both normalized `x,y`, the observed `renderer.topology_key` and `renderer.interaction_key`. Missing or non-finite coordinates are invalid. A coordinate-free `measure` requests component bounds.

The interaction identity covers design, equilibrium, view, visualization mode, cutaway, explode, opacity, visibility and magnetic overlay. Selection, language and numeric thermal controls do not invalidate an otherwise applicable coordinate operation. The service rejects stale context with HTTP 409; the renderer checks the context again before and after asynchronous picking.

The FIFO permits 128 active commands. HTTP 429 means it is full; 503 means the renderer is unavailable. The response means admitted, not completed. Poll `GET /api/actions/<request_id>` for `pending`, `running`, `completed`, `failed` or `cancelled`. Results become completed only after the actual callback/capture finishes. Kit retains every completion until the service acknowledges a contiguous sequence watermark.

Identical request IDs return the recorded result. Reusing an ID with a different action body returns 409. The service keeps 256 terminal records in memory and persists terminal records under `runtime/commands/completed/`; memory eviction does not permit replay. Storage is written and flushed before its completion is acknowledged. A new renderer session cancels work for its predecessor. A service restart preserves completed results and cancels unfinished commands. This is explicit cancellation/retry behavior, not a promise to resume arbitrary GPU callbacks after a crash.

Capture results have immutable per-request URLs `/api/captures/<hash>.png`. `GET /api/preview.png` is only a fallback preview. Browser screenshots download the completed native RTX capture.

## Rendering and NVIDIA workflow

The output/stream resolution is fixed at 2560×1440 (QHD), targeting 30 FPS with frame generation disabled. `render_resolution` reports the viewport texture, which stays at 2560×1440 during motion and at rest: the interactive size (`/fusion/render/interactiveWidth/Height`) equals the output size because every viewport resize rebuilds the Kit 110.1.3 RTX Hydra engine, and repeated rebuilds deadlocked the main thread in `UsdContext` scheduling. `quality` still reports interaction/detail, but no longer changes the viewport size. PNG captures come from the current RTX viewport. RT2 additionally uses DLSS temporal reconstruction, so viewport dimensions do not imply native per-pixel sampling.

All modes (`assembly`, `magnetic`, `temperature`, `heatflux`, `delta_temperature`, `delta_heatflux`, `slice`, `volume`) use RTX Real-Time 2.0 (`RealTimePathTracing`) for both live video and PNG capture. Camera motion, settling and capture keep the same engine; quality changes adjust viewport resolution only. There is no automatic switch to offline Path Tracing or progressive 256-sample accumulation.

RT2 uses DLSS Quality (`/rtx/post/dlss/execMode=2`). Volume mode additionally uses IndeX stable depth compositing (`/rtx/index/compositeDepthMode=3`), checked against opaque CAD in same-scene comparisons. `renderer.render_mode` and `renderer.engine` describe the actual engine; RT2 reports null `samples_per_pixel` and `accumulation_samples`, with `sampling_strategy=temporal_reconstruction`.

For surface/slice fields, a pure field update schedules `/rtx-transient/post/dlss/forceParamReset` after one Kit update frame. Structural/mode changes request the same DLSS reset after three frames in every mode. Continuous numeric input reuses the pending reset instead of cancelling it; an existing three-frame reset completes on its original schedule. The reset records the latest applied `revision`, `field_key` and wall-clock `time` in `renderer.render_reset`. `dlss_reset_pending` exposes the transient reset request. These values record reset issuance and do not prove presentation of the new pixels. Volume publication retains its separate completion contract below.

`renderer.apply_timing` separates packet loading from snapshot application on the Kit CPU thread. `fps` measures Kit update events; browser presentation must be measured with video-frame callbacks and WebRTC statistics. Pixel-response QA requires both fixed blanket regions and the full visible thermal mask to pass low/high/low return checks before reporting latency. The current configuration passed integrated motion, complete functional-workflow and 20-trial pixel-response acceptance on the documented Windows host; see [verification.md](verification.md) for evidence and limits.

The RTWT extension exposes 20 typed controls through `get_control_manifest`, `get_state`, standard `set_state`, `fusion_set_state`, and `fusion_get_cache` requests. The browser sends `{event_type: "<name>_request", payload: {id, ...arguments}}`; replies carry the matching ID and response. `fusion_set_state` routes changes through the validated coordinator. Standard `set_state` first authors USD, then a notice queues the same validated computation; its immediate boolean reply is not a solver completion. `control_pending`, `control_error` and `control_accepted_revision` report that later outcome. Invalid values roll back to committed values without overwriting newer edits. Internal synchronization does not trigger a second computation. Disconnected preview operation can still use HTTP.

The workflow adapter reports readiness separately: `rtwt_ready`, `volume_pending`, `pending_volume_field_key`, `applied_volume_field_key`, `applied_volume_key`, `volume_mask_angle` and `volume_error`. A synchronized volume requires the current field key and cutaway, no pending operation and no volume error. The volume cache identity includes the field content key, sampling-model version and cutaway. Source keV profiles remain labeled synthetic. Visibility bindings are completed before publishing new volume fields, because CAE skips hidden operators and clears their changes. Starting a different publication invalidates the previous applied-key shortcut until CAE and native GPU adoption complete, so superseded or failed A→B→A work cannot reuse a replaced dataset. Superseded work yields to the latest snapshot without claiming completion.

The grid is 128×128×112 with spacing (0.21875, 0.21875, 0.15) m. `volumeStyle=plasma` uses an illustrative pink transfer function; `temperature` uses a fixed 0–40 keV legend. Both use the same scalar grid. `heatScale` and `volumeStyle` only change display mapping, not the physics field key. Hall walls and their columns may hide when they obstruct the machine; this changes only the authored display environment, with `hall_hidden_walls` reporting the affected walls.

Actual RTWT/IndeX integration is accepted only after the independent GPU probe and browser `tools/qa/nvidia.mjs` pass; defining the schema or loading an extension is insufficient.

## Public controls and arrays

- `design`: conventional / longleg; `equilibrium`: reference / rampup / sof / eof / rampdown.
- `view`: overview / front / top / section / divertor; `mode`: assembly / temperature / heatflux / delta_temperature / delta_heatflux / magnetic / slice / volume.
- `scenario`: nominal / ramp / lowflow / highload; `power`: 500–2600 MW baseline thermal budget excluding auxiliary heating; `flow`: 0.4–1.4 nominal flow ratio; `inlet`: 200–400°C.
- `heating`: exactly 20 / 35 / 50 / 65 MW; `neon`: boolean synthetic radiation/spreading assumption. `result.story.cases` contains the conventional/LongLeg × Ne off/on comparison with all other controls fixed.
- `heatScale`: log / linear; `volumeStyle`: plasma / temperature; `lineMotion`: boolean illustrative direction markers, not particle velocity.
- `phase`: 0–1 quasi-steady load coordinate; `cutaway`: 0–180° in 20° UI steps; `explode`: 0–1; `opacity`: 0.1–1.
- `visible`: component-to-boolean map; `selected`: component ID; `fieldLines`, `orbit`, `playing`: booleans; `language`: zh / en; `tab`: explore / compare / engineering.

NPZ arrays include surface points/triangles/normals/vertex areas/regions/part IDs, temperature in °C, heat flux in MW/m², radiation and particle contributions, difference fields and colors, 3D magnetic lines, and a source-flux-shaped synthetic keV slice. Region 0 is blanket; region 1 is divertor. Surface data cover one physical sector; the renderer replicates about Z. Magnetic lines and the section use world coordinates in metres.

`heatflux_log_rgb` maps 0.01–200 MW/m² through a shared log10 scale; linear colors use 0–200 MW/m². `field_line_B_T` and `field_line_rgb` retain the 24×1800 line sampling and fixed 2–12 T range. Color stops, under/over-range counts and the zero-value policy travel with the result. Histories retain 31 quasi-steady samples; a single Warp launch evaluates the two region maxima for every sample with the same thermal law as the surface kernel. Result, history and four-case summary caches each retain at most eight entries.

`metadata_json` records `synthetic_demo`, units, design/equilibrium, power budget, strike points, assumptions and PFC provenance. The power ledger, coolant KPI and visualization share the same committed result. Physical interpretation and limitations are documented in [physics-model.md](physics-model.md).

`GET /api/export` includes `manifest_source` and the complete source provenance record with upstream commits, licenses and asset hashes. The source B-rep is a sector asset; CAD ZIP preserves it. USD contains both design variants and the assembled machine.

## Data import

`POST /api/import/scenarios` computes 1–32 partial states (JSON `{"cases": [...], "apply": id}` or CSV with `?apply=id`) on top of the current state and returns per-case metrics and power budgets. Only the case named by `apply` is committed; others do not change `revision`. Each case is validated with the same rules as `POST /api/state`.

`POST /api/import/surface` interpolates `[R, Z, value]` or `[x, y, z, value]` rows (metres, machine frame) onto the analysis mesh with k=4 inverse-distance weighting; vertices farther than `max_distance` from every sample are NaN (neutral colour). The service writes a separate packet derived from the computed one, so the computed packet is never modified, and records the computed packet as `result.source_field_ref`. The import persists across later state changes until `DELETE /api/import/surface`, is reported as `result.imported_surface`, and is not persisted across a service restart. Zero coverage is rejected without a state change.
