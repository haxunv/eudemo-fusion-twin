"""Reproducible demonstration fields and equilibrium tracing on NVIDIA Warp.

The CAD and equilibrium are source data. Thermal loading, coolant flow and
temperature limits are explicitly authored demonstration assumptions.
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import time
import zipfile
from pathlib import Path

import numpy as np
import warp as wp
from .pfc import build_pfc
from .physics import DESIGNS, EQUILIBRIA, EICH_REFERENCE, MagneticEquilibrium, heat_pattern, prescribed_loads, load_fraction

wp.config.quiet = True


@wp.kernel
def thermal_kernel(
    heatflux: wp.array(dtype=float),
    regions: wp.array(dtype=wp.int32),
    flow: float,
    blanket_coolant: float,
    divertor_coolant: float,
    temperatures: wp.array(dtype=float),
):
    i = wp.tid()
    local_coolant = blanket_coolant
    resistance = float(0.0)
    if regions[i] == 1:
        local_coolant = divertor_coolant
        resistance = 0.004 / 140.0 + 1.0 / (55000.0 * wp.pow(flow, 0.8))
    else:
        resistance = 0.003 / 28.0 + 1.0 / (22000.0 * wp.pow(flow, 0.8))
    temperatures[i] = local_coolant + heatflux[i] * 1.0e6 * resistance


@wp.func
def bilinear(tex: wp.array2d(dtype=float), r: float, z: float, r0: float, z0: float, dr: float, dz: float) -> float:
    x = wp.clamp((r - r0) / dr, 0.0, float(tex.shape[0] - 1) - 0.001)
    y = wp.clamp((z - z0) / dz, 0.0, float(tex.shape[1] - 1) - 0.001)
    ix, iy = int(x), int(y)
    tx, ty = x - float(ix), y - float(iy)
    return (tex[ix, iy] * (1.0 - tx) + tex[ix + 1, iy] * tx) * (1.0 - ty) + (tex[ix, iy + 1] * (1.0 - tx) + tex[ix + 1, iy + 1] * tx) * ty


@wp.func
def rhs(p: wp.vec2, br: wp.array2d(dtype=float), bz: wp.array2d(dtype=float), r0: float, z0: float, dr: float, dz: float, fvac: float) -> wp.vec2:
    r = wp.max(p[0], 1.0)
    factor = r * r / fvac
    return wp.vec2(bilinear(br, r, p[1], r0, z0, dr, dz) * factor, bilinear(bz, r, p[1], r0, z0, dr, dz) * factor)


@wp.kernel
def trace_kernel(
    seeds: wp.array(dtype=wp.vec3), br: wp.array2d(dtype=float), bz: wp.array2d(dtype=float),
    r0: float, z0: float, dr: float, dz: float, fvac: float,
    steps: int, h: float, result: wp.array2d(dtype=wp.vec3),
):
    line = wp.tid()
    seed = seeds[line]
    p = wp.vec2(seed[0], seed[1])
    phi = seed[2]
    for k in range(steps):
        result[line, k] = wp.vec3(p[0] * wp.cos(phi), p[0] * wp.sin(phi), p[1])
        k1 = rhs(p, br, bz, r0, z0, dr, dz, fvac)
        k2 = rhs(p + h * 0.5 * k1, br, bz, r0, z0, dr, dz, fvac)
        k3 = rhs(p + h * 0.5 * k2, br, bz, r0, z0, dr, dz, fvac)
        k4 = rhs(p + h * k3, br, bz, r0, z0, dr, dz, fvac)
        p = p + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
        phi = phi + h


def colormap(values: np.ndarray, low: float, high: float) -> np.ndarray:
    """Fixed scientific legend shared with the web interface."""
    stops = np.array([[0.10, 0.18, 0.58], [0.00, 0.55, 0.85], [0.05, 0.80, 0.67], [0.88, 0.91, 0.17], [1.00, 0.43, 0.06], [0.75, 0.03, 0.07]])
    t = np.clip((values - low) / (high - low), 0, 1)
    return np.stack([np.interp(t, np.linspace(0, 1, len(stops)), stops[:, j]) for j in range(3)], axis=-1).astype(np.float32)


def atomic_replace(source: Path, destination: Path) -> None:
    """Allow a Windows reader's short file lock to clear before publication."""
    for attempt in range(11):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if os.name != "nt" or attempt == 10:
                raise
            time.sleep(0.02)


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    atomic_replace(tmp, path)


def write_npz(path: Path, arrays: dict, *, compressed=False) -> None:
    """Runtime packets favor latency; shipped presets use compact archives."""
    compression = zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED
    with zipfile.ZipFile(path, "w", compression=compression, compresslevel=1 if compressed else None) as archive:
        for name, values in arrays.items():
            with archive.open(f"{name}.npy", "w", force_zip64=True) as member:
                np.lib.format.write_array(member, np.asanyarray(values), allow_pickle=False)


SCENARIOS = {
    "nominal": {"power": 2000.0, "flow": 1.0, "inlet": 300.0, "hotspot": 1.0},
    "ramp": {"power": 1200.0, "flow": 0.9, "inlet": 280.0, "hotspot": 1.0},
    "lowflow": {"power": 2000.0, "flow": 0.55, "inlet": 300.0, "hotspot": 1.0},
    "highload": {"power": 2400.0, "flow": 0.85, "inlet": 320.0, "hotspot": 1.35},
}

SCHEMA_VERSION = 2
MODEL_VERSION = "pfc-budget-eich-v2.2"


def diverging_colors(values, limit):
    stops = np.array([[0.12, 0.32, 0.82], [0.94, 0.96, 0.98], [0.86, 0.16, 0.12]])
    t = np.clip(np.asarray(values) / limit, -1, 1)
    return np.stack([np.interp(t, [-1, 0, 1], stops[:, k]) for k in range(3)], axis=-1).astype(np.float32)


class FieldEngine:
    def __init__(self, root: Path, device: str | None = None, runtime: Path | None = None, *, compress_fields=False):
        self.root = root
        self.runtime = Path(runtime) if runtime is not None else root / "runtime"
        self.compress_fields = compress_fields
        wp.init()
        self.device = wp.get_device(device or ("cuda:0" if wp.is_cuda_available() else "cpu"))
        self._meshes, self._equilibria, self._magnetics, self._patterns = {}, {}, {}, {}
        self._history_key, self._history = None, None
        self.last_signature = None
        self.last_result = None
        self._context = None
        self._select_context("conventional", "reference")
        self._solve(SCENARIOS["nominal"], 0.65)

    def _select_context(self, design, equilibrium):
        if design not in DESIGNS or equilibrium not in EQUILIBRIA:
            raise ValueError("Unknown design or equilibrium")
        if self._context == (design, equilibrium):
            return
        self.source = self.root / "assets/source/eudemo" / design
        if design not in self._meshes:
            self._meshes[design] = build_pfc(self.source)
        self.mesh = self._meshes[design]
        self.points = self.mesh.points
        self.faces, self.regions = self.mesh.faces, self.mesh.regions
        self.wp_regions = wp.array(self.regions, dtype=wp.int32, device=self.device)
        self.wp_temperature = wp.empty(len(self.points), dtype=float, device=self.device)
        context = (design, equilibrium)
        if context not in self._equilibria:
            self._equilibria[context] = MagneticEquilibrium(self.source, equilibrium)
        self.equilibrium = self._equilibria[context]
        self.eq = self.equilibrium.data
        if context not in self._magnetics:
            lines, trace_ms = self._trace_magnetic()
            self._magnetics[context] = (lines, trace_ms, *self._make_slice())
        self.lines, self.trace_ms, self.slice_points, self.slice_faces, self.slice_psin = self._magnetics[context]
        self._context = context

    def _pattern(self, hotspot):
        key = (self.mesh.topology_key, self.equilibrium.key, float(hotspot))
        if key not in self._patterns:
            self._patterns[key] = heat_pattern(self.mesh, self.equilibrium, float(hotspot))
        return self._patterns[key]

    def _trace_magnetic(self):
        eq = self.eq
        r, z = eq["x"][:, 0], eq["z"][0]
        axis = eq["o_point"]
        lcfs_r = float(eq["lcfs"][0].max())
        seeds = np.array([[axis[0] + frac * (lcfs_r - axis[0]), axis[1], phi]
                          for frac in (0.3, 0.55, 0.8, 0.94)
                          for phi in np.linspace(0, 2 * np.pi, 6, endpoint=False)], dtype=np.float32)
        steps = 1800
        output = wp.empty((len(seeds), steps), dtype=wp.vec3, device=self.device)
        inputs = [wp.array(seeds, dtype=wp.vec3, device=self.device),
                  wp.array(eq["Bx"].astype(np.float32), device=self.device),
                  wp.array(eq["Bz"].astype(np.float32), device=self.device),
                  float(r[0]), float(z[0]), float(r[1] - r[0]), float(z[1] - z[0]),
                  float(eq["fvac"]), steps, 0.026, output]
        wp.launch(trace_kernel, dim=len(seeds), inputs=inputs, device=self.device)
        wp.synchronize_device(self.device)
        started = time.perf_counter()
        wp.launch(trace_kernel, dim=len(seeds), inputs=inputs, device=self.device)
        wp.synchronize_device(self.device)
        elapsed = (time.perf_counter() - started) * 1000
        lines = output.numpy()
        if not np.isfinite(lines).all():
            raise ValueError("Magnetic integration produced non-finite points")
        return lines, elapsed

    def _make_slice(self):
        eq = self.eq
        r, z = np.linspace(3.7, 13.3, 97), np.linspace(-7.8, 6.8, 139)
        rr, zz = np.meshgrid(r, z, indexing="ij")
        coords = np.stack([rr.ravel(), zz.ravel()], axis=-1)
        psin = self.equilibrium.psin(coords)
        points = np.stack([rr.ravel(), np.full(rr.size, -0.04), zz.ravel()], axis=-1).astype(np.float32)
        triangles = []
        lower = self.equilibrium.xpoint[1] if self.equilibrium.xpoint is not None else float(eq["lcfs"][2].min())
        for i in range(len(r) - 1):
            for j in range(len(z) - 1):
                a = i * len(z) + j
                for tri in ((a, a + len(z), a + 1), (a + 1, a + len(z), a + len(z) + 1)):
                    if all(0 <= psin[k] <= 1 and points[k, 2] > lower for k in tri):
                        triangles.append(tri)
        return points, np.array(triangles, dtype=np.int32), psin

    def _solve(self, parameters: dict, phase: float):
        pattern = self._pattern(parameters.get("hotspot", 1.0))
        flux, radiation, particle, budget = prescribed_loads(self.mesh, pattern, parameters["power"], phase)
        flow, inlet = float(parameters["flow"]), float(parameters["inlet"])
        blanket_mean = inlet + budget["blanket_absorbed_MW"] * 1e6 / (2 * 3500 * 0.85 * flow * 5200)
        divertor_mean = inlet + budget["divertor_absorbed_MW"] * 1e6 / (2 * 3500 * 0.15 * flow * 5200)
        gpu_flux = wp.array(flux.astype(np.float32), dtype=float, device=self.device)
        started = time.perf_counter()
        wp.launch(thermal_kernel, dim=len(self.points), inputs=[gpu_flux, self.wp_regions, flow,
                  blanket_mean, divertor_mean, self.wp_temperature], device=self.device)
        wp.synchronize_device(self.device)
        milliseconds = (time.perf_counter() - started) * 1000
        self._last_budget, self._last_radiation, self._last_particle = budget, radiation, particle
        return self.wp_temperature.numpy().copy(), flux, milliseconds

    def metrics(self, temperature, heatflux, parameters, budget=None):
        budget = self._last_budget if budget is None else budget
        mass_flow = 3500 * parameters["flow"]
        outlet = parameters["inlet"] + budget["absorbed_thermal_MW"] * 1e6 / (mass_flow * 5200)
        peak = float(np.max(temperature))
        return {"peak_temperature_C": round(peak, 2), "peak_heatflux_MW_m2": round(float(np.max(heatflux)), 3),
                "outlet_temperature_C": round(outlet, 2), "cooling_margin_C": round(900 - peak, 2),
                "limit_temperature_C": 900.0, "mass_flow_kg_s": round(mass_flow, 1),
                "thermal_power_MW": budget["absorbed_thermal_MW"]}

    def _publish(self, key, revision, arrays, metadata):
        directory = self.runtime / "fields"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{key}.npz"
        if path.exists():
            with np.load(path, allow_pickle=False) as previous:
                if (str(previous["field_key"]) != key or str(previous["topology_key"]) != self.mesh.topology_key
                        or str(previous["equilibrium_key"]) != self.equilibrium.key
                        or int(previous["schema_version"]) != SCHEMA_VERSION):
                    raise ValueError("Immutable field metadata does not match its content key")
                revision = int(previous["field_revision"])
        else:
            temporary = directory / f"{key}.tmp.npz"
            packet = {**arrays, "field_key": np.asarray(key), "field_revision": np.asarray(revision),
                      "topology_key": np.asarray(self.mesh.topology_key), "equilibrium_key": np.asarray(self.equilibrium.key),
                      "schema_version": np.asarray(SCHEMA_VERSION), "metadata_json": np.asarray(json.dumps(metadata, allow_nan=False))}
            write_npz(temporary, packet, compressed=self.compress_fields)
            atomic_replace(temporary, path)
        return {"path": f"fields/{key}.npz", "key": key, "revision": revision,
                "topology_key": self.mesh.topology_key, "equilibrium_key": self.equilibrium.key,
                "schema_version": SCHEMA_VERSION}

    def compute(self, state: dict, revision: int) -> dict:
        design, equilibrium = state.get("design", "conventional"), state.get("equilibrium", "reference")
        self._select_context(design, equilibrium)
        parameters = {key: float(state[key]) for key in ("power", "flow", "inlet")}
        parameters["hotspot"] = SCENARIOS[state["scenario"]]["hotspot"]
        phase = float(state["phase"])
        if not (0 <= phase <= 1 and parameters["power"] > 0 and parameters["flow"] > 0
                and all(math.isfinite(v) for v in parameters.values())):
            raise ValueError("Invalid thermal inputs")
        payload = {"model": MODEL_VERSION, "topology": self.mesh.topology_key, "equilibrium": self.equilibrium.key,
                   "parameters": parameters, "phase": phase, "device": str(self.device)}
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]
        signature = (str(self.runtime), key, state["scenario"])
        if signature == self.last_signature:
            return self.last_result
        temperatures, heatflux, gpu_ms = self._solve(parameters, phase)
        budget, radiation, particle = self._last_budget, self._last_radiation, self._last_particle
        candidate = self.metrics(temperatures, heatflux, parameters, budget)
        baseline_t, baseline_q, _ = self._solve(SCENARIOS["nominal"], phase)
        baseline = self.metrics(baseline_t, baseline_q, SCENARIOS["nominal"], self._last_budget)
        delta_t, delta_q = temperatures - baseline_t, heatflux - baseline_q
        max_dt = max(1.0, math.ceil(float(np.max(np.abs(delta_t))) * 10) / 10)
        max_dq = max(0.01, math.ceil(float(np.max(np.abs(delta_q))) * 100) / 100)
        ranges = {"temperature": [min(250, math.floor(float(temperatures.min()) / 50) * 50),
                                  max(1100, math.ceil(float(temperatures.max()) / 100) * 100)],
                  "heatflux": [0, max(12, math.ceil(float(heatflux.max())))], "slice": [0, 30],
                  "delta_temperature": [-max_dt, max_dt], "delta_heatflux": [-max_dq, max_dq]}
        history_key = (self.mesh.topology_key, self.equilibrium.key, state["scenario"], *parameters.values())
        if history_key != self._history_key:
            history = []
            for t in np.linspace(0, 1, 31):
                series_t, series_q, _ = self._solve(parameters, float(t))
                series_metrics = self.metrics(series_t, series_q, parameters)
                history.append({"phase": float(t), "load_fraction": load_fraction(t),
                                "heatflux": round(float(np.max(series_q)), 3),
                                "temperature": round(float(series_t.max()), 2),
                                "peak_temperature_C": round(float(series_t.max()), 2),
                                "outlet_temperature_C": series_metrics["outlet_temperature_C"],
                                "absorbed_thermal_MW": self._last_budget["absorbed_thermal_MW"]})
            self._history_key, self._history = history_key, history
        history = self._history
        slice_temperature = np.nan_to_num(np.maximum(1 - self.slice_psin, 0) ** 1.5) * 25 * parameters["power"] / 2000 * load_fraction(phase)
        arrays = dict(surface_points=self.points, surface_triangles=self.faces, surface_regions=self.regions,
                      surface_triangle_component=self.regions[self.faces[:, 0]], surface_normals=self.mesh.normals.astype(np.float32),
                      surface_vertex_area_m2=self.mesh.vertex_area, surface_part_id=self.mesh.part_ids,
                      surface_temperature_C=temperatures, surface_heatflux_MW_m2=heatflux,
                      surface_heatflux_radiation_MW_m2=radiation, surface_heatflux_particle_MW_m2=particle,
                      temperature_rgb=colormap(temperatures, *ranges["temperature"]), heatflux_rgb=colormap(heatflux, *ranges["heatflux"]),
                      delta_temperature_C=delta_t, delta_heatflux_MW_m2=delta_q,
                      delta_temperature_rgb=diverging_colors(delta_t, max_dt), delta_heatflux_rgb=diverging_colors(delta_q, max_dq),
                      magnetic_lines=self.lines, slice_points=self.slice_points, slice_triangles=self.slice_faces,
                      slice_rgb=colormap(slice_temperature, *ranges["slice"]), slice_temperature_keV=slice_temperature.astype(np.float32))
        strikes = self._pattern(parameters["hotspot"]).strikes
        assumptions = {
            "thermal": "Synthetic quasi-steady wall resistance; prescribed load scan, no time-dependent heat transport or qualified material model",
            "coolant": "Absorbed surface plus assumed blanket volume heat only; helium cp=5200 J/(kg K), 3500 kg/s times flow, 85/15% circuit split; unresolved power excluded",
            "budget": "Input is effective thermal power, not fusion power. Synthetic split: 80% blanket volume, 20% plasma-surface channel; 65% core radiation, then 70% SOL radiation, 3% wall particles and 27% targets; target inner/outer 30/70%",
            "radiation": "Uniform area deposition split 90/10% wall/divertor; no photon transport or neutron transport calculation",
            "target": "Eich upstream profile with synthetic lambda_q=6 mm, S=2 mm divided by hotspot, flux mapping and incidence; local +/-0.75 m neighborhood at a source psi=1 intersection; no 3D shadowing or detached SOL solution",
            "limit": "900 degC demonstration threshold; not a material qualification limit",
            "magnetics": "Selected Bluemira axisymmetric equilibrium, Bphi=fvac/R approximation; cached per equilibrium; no discrete TF ripple",
            "plasma_slice": "Synthetic 25 keV core profile shaped by selected source normalized poloidal flux",
            "history": "Dimensionless quasi-steady load scan, phase in [0,1]; no elapsed-time coordinate; equilibria are independently selected snapshots"}
        metadata = {"data_class": "synthetic_demo", "power_budget": budget, "strike_points": strikes,
                    "ranges": ranges, "assumptions": assumptions, "pfc": self.mesh.provenance,
                    "units": {"geometry": "m", "temperature": "degC", "heatflux": "MW/m2", "slice": "keV", "power": "MW"},
                    "design": design, "equilibrium": equilibrium, "eich_reference": EICH_REFERENCE}
        field_ref = self._publish(key, revision, arrays, metadata)
        result = {**candidate, "field_ref": field_ref, "power_budget": budget, "strike_points": strikes,
                  "color_ranges": ranges, "analysis_surface": self.mesh.provenance, "design": design, "equilibrium": equilibrium,
                  "gpu_ms": round(gpu_ms, 3), "compute_backend": "CUDA / Warp" if self.device.is_cuda else "CPU / Warp",
                  "gpu_device": str(self.device), "gpu_name": self.device.name,
                  "gpu_timing_scope": "Warp local thermal kernel and synchronization; excludes CPU budget, footprint construction and transfers",
                  "field_samples": len(self.points), "magnetic_line_count": len(self.lines), "magnetic_trace_ms": round(self.trace_ms, 3),
                  "source_label": "synthetic_demo_source_geometry_equilibrium", "scenario_label": state["scenario"],
                  "history": history, "comparison": {"baseline": baseline, "candidate": candidate,
                  "context": {"design": design, "equilibrium": equilibrium, "phase": phase},
                  "delta": {key: round(candidate[key] - baseline[key], 3) for key in baseline}}, "assumptions": assumptions}
        self.last_signature, self.last_result = signature, result
        self._last_budget, self._last_radiation, self._last_particle = budget, radiation, particle
        return result
