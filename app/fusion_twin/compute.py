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
from collections import OrderedDict
from pathlib import Path

import numpy as np
import warp as wp
from .pfc import build_pfc
from .physics import (DESIGNS, EQUILIBRIA, HEATING_LEVELS, EICH_REFERENCE, MagneticEquilibrium,
                      exhaust_assumptions, heat_pattern, prescribed_loads, load_fraction)

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


@wp.kernel
def thermal_history_kernel(
    heatflux: wp.array2d(dtype=float),
    coolant: wp.array2d(dtype=float),
    flow: float,
    temperatures: wp.array2d(dtype=float),
):
    phase, region = wp.tid()
    resistance = float(0.0)
    if region == 1:
        resistance = 0.004 / 140.0 + 1.0 / (55000.0 * wp.pow(flow, 0.8))
    else:
        resistance = 0.003 / 28.0 + 1.0 / (22000.0 * wp.pow(flow, 0.8))
    temperatures[phase, region] = coolant[phase, region] + heatflux[phase, region] * 1.0e6 * resistance


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
MODEL_VERSION = "pfc-aux-neon-budget-v3.0"
RESULT_CACHE_SIZE = 8
HEATFLUX_RANGE = [0.0, 200.0]
HEATFLUX_LOG_RANGE = [0.01, 200.0]
MAGNETIC_RANGE = [2.0, 12.0]
# Samples of the Matplotlib inferno / viridis tables, stored without a plotting dependency.
INFERNO = [[0.001462, 0.000466, 0.013866], [0.129285, 0.047293, 0.290788],
           [0.341500, 0.062325, 0.429425], [0.540920, 0.134729, 0.415123],
           [0.735683, 0.215906, 0.330245], [0.894305, 0.353399, 0.193584],
           [0.978422, 0.557937, 0.034931], [0.974638, 0.797692, 0.206332],
           [0.988362, 0.998364, 0.644924]]
VIRIDIS = [[0.267004, 0.004874, 0.329415], [0.229739, 0.322361, 0.545706],
           [0.127568, 0.566949, 0.550556], [0.369214, 0.788888, 0.382914],
           [0.993248, 0.906157, 0.143936]]
ZERO_COLOR = [0.12, 0.14, 0.16]


def scientific_colors(values, bounds, *, logarithmic=False, magnetic=False):
    values = np.asarray(values)
    low, high = bounds
    scaled = np.log10(np.clip(values, low, high)) if logarithmic else values
    domain = np.log10(bounds) if logarithmic else bounds
    t = np.clip((scaled - domain[0]) / (domain[1] - domain[0]), 0, 1)
    stops = np.asarray(VIRIDIS if magnetic else INFERNO)
    colors = np.stack([np.interp(t, np.linspace(0, 1, len(stops)), stops[:, i]) for i in range(3)], axis=-1)
    colors[(values <= 0) | ~np.isfinite(values)] = ZERO_COLOR
    return colors.astype(np.float32)


def remember(cache, key, value, limit=RESULT_CACHE_SIZE):
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > limit:
        cache.popitem(last=False)
    return value


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
        self._thermal_buffers = {}
        self._results, self._histories, self._stories = OrderedDict(), OrderedDict(), OrderedDict()
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
        if design not in self._thermal_buffers:
            self._thermal_buffers[design] = (wp.array(self.regions, dtype=wp.int32, device=self.device),
                                            wp.empty(len(self.points), dtype=float, device=self.device))
        self.wp_regions, self.wp_temperature = self._thermal_buffers[design]
        context = (design, equilibrium)
        if context not in self._equilibria:
            self._equilibria[context] = MagneticEquilibrium(self.source, equilibrium)
        self.equilibrium = self._equilibria[context]
        self.eq = self.equilibrium.data
        if context not in self._magnetics:
            lines, trace_ms = self._trace_magnetic()
            magnitude = np.linalg.norm(self.equilibrium.field(lines.reshape(-1, 3)), axis=1).reshape(lines.shape[:2]).astype(np.float32)
            colors = scientific_colors(magnitude, MAGNETIC_RANGE, magnetic=True)
            self._magnetics[context] = (lines, trace_ms, magnitude, colors, *self._make_slice())
        (self.lines, self.trace_ms, self.line_B, self.line_rgb,
         self.slice_points, self.slice_faces, self.slice_psin) = self._magnetics[context]
        self._context = context

    def _pattern(self, hotspot, neon=False):
        key = (self.mesh.topology_key, self.equilibrium.key, float(hotspot), bool(neon))
        if key not in self._patterns:
            self._patterns[key] = heat_pattern(self.mesh, self.equilibrium, float(hotspot), neon)
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
        r, z = np.linspace(3.7, 13.3, 193), np.linspace(-7.8, 6.8, 225)
        rr, zz = np.meshgrid(r, z, indexing="ij")
        coords = np.stack([rr.ravel(), zz.ravel()], axis=-1)
        psin = self.equilibrium.psin(coords)
        points = np.stack([rr.ravel(), np.full(rr.size, -0.04), zz.ravel()], axis=-1).astype(np.float32)
        lower = self.equilibrium.xpoint[1] if self.equilibrium.xpoint is not None else float(eq["lcfs"][2].min())
        a = (np.arange(len(r) - 1)[:, None] * len(z) + np.arange(len(z) - 1)).ravel()
        triangles = np.concatenate((np.column_stack((a, a + len(z), a + 1)),
                                    np.column_stack((a + 1, a + len(z), a + len(z) + 1))))
        valid = (psin >= 0) & (psin <= 1) & (points[:, 2] > lower)
        return points, triangles[valid[triangles].all(axis=1)].astype(np.int32), psin

    def _solve(self, parameters: dict, phase: float):
        neon = parameters.get("neon", False)
        pattern = self._pattern(parameters.get("hotspot", 1.0), neon)
        flux, radiation, particle, budget = prescribed_loads(self.mesh, pattern, parameters["power"], phase,
                                                            parameters.get("heating", 50.0), neon)
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
                "peak_divertor_heatflux_MW_m2": round(float(np.max(heatflux[self.regions == 1])), 3),
                "outlet_temperature_C": round(outlet, 2), "cooling_margin_C": round(900 - peak, 2),
                "limit_temperature_C": 900.0, "mass_flow_kg_s": round(mass_flow, 1),
                "thermal_power_MW": budget["absorbed_thermal_MW"]}

    def _solve_history(self, parameters):
        """Solve every phase, batching the exact two-region temperature maxima."""
        pattern = self._pattern(parameters.get("hotspot", 1.0), parameters.get("neon", False))
        phases = np.linspace(0, 1, 31)
        region_masks = (self.regions == 0, self.regions == 1)
        peak_flux, coolant = np.empty((len(phases), 2)), np.empty((len(phases), 2))
        budgets = []
        flow, inlet = float(parameters["flow"]), float(parameters["inlet"])
        for i, phase in enumerate(phases):
            flux, _, _, budget = prescribed_loads(self.mesh, pattern, parameters["power"], float(phase),
                                                  parameters.get("heating", 50.0), parameters.get("neon", False))
            budgets.append(budget)
            peak_flux[i] = [float(np.max(flux[mask])) for mask in region_masks]
            coolant[i, 0] = inlet + budget["blanket_absorbed_MW"] * 1e6 / (2 * 3500 * 0.85 * flow * 5200)
            coolant[i, 1] = inlet + budget["divertor_absorbed_MW"] * 1e6 / (2 * 3500 * 0.15 * flow * 5200)
        # Within each region, coolant and positive thermal resistance are constant.
        # Its hottest vertex is therefore its maximum-flux vertex, at every phase.
        # Use the same float32 inputs and Warp arithmetic as the full surface solve.
        output = wp.empty(peak_flux.shape, dtype=float, device=self.device)
        wp.launch(thermal_history_kernel, dim=peak_flux.shape,
                  inputs=[wp.array(peak_flux.astype(np.float32), device=self.device),
                          wp.array(coolant.astype(np.float32), device=self.device), flow, output], device=self.device)
        wp.synchronize_device(self.device)
        return output.numpy().max(axis=1), peak_flux.max(axis=1), budgets

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

    def _four_cases(self, parameters, phase, design, equilibrium):
        controls = {k: v for k, v in parameters.items() if k != "neon"}
        key = (equilibrium, phase, *controls.values())
        if key in self._stories:
            self._stories.move_to_end(key)
            return self._stories[key]
        cases = []
        try:
            for variant in DESIGNS:
                self._select_context(variant, equilibrium)
                for neon in (False, True):
                    inputs = {**controls, "neon": neon}
                    temperature, flux, _ = self._solve(inputs, phase)
                    cases.append({"id": f"{variant}/ne_{'on' if neon else 'off'}",
                                  "design": variant, "neon": neon, "heating": controls["heating"],
                                  "equilibrium": equilibrium, "equilibrium_key": self.equilibrium.key,
                                  "source_equilibrium": f"assets/source/eudemo/{variant}/equilibria/{equilibrium}.npz",
                                  **self.metrics(temperature, flux, inputs), "power_budget": self._last_budget,
                                  "strike_status": {leg: info["status"] for leg, info in self._pattern(inputs["hotspot"], neon).strikes.items()}})
        finally:
            self._select_context(design, equilibrium)
        for case in cases:
            baseline = next(c for c in cases if c["design"] == case["design"] and not c["neon"])
            case["relative_no_neon_percent"] = round(100 * (case["peak_divertor_heatflux_MW_m2"] /
                                                           baseline["peak_divertor_heatflux_MW_m2"] - 1), 3)
        return remember(self._stories, key, cases)

    def compute(self, state: dict, revision: int) -> dict:
        design, equilibrium = state.get("design", "conventional"), state.get("equilibrium", "reference")
        self._select_context(design, equilibrium)
        parameters = {key: float(state[key]) for key in ("power", "flow", "inlet")}
        parameters["hotspot"] = SCENARIOS[state["scenario"]]["hotspot"]
        heating, neon = state.get("heating", 50), state.get("neon", False)
        if isinstance(heating, bool) or heating not in HEATING_LEVELS or not isinstance(neon, bool):
            raise ValueError("Heating must be one of 20/35/50/65 MW and neon must be boolean")
        parameters.update(heating=float(heating), neon=neon)
        phase = float(state["phase"])
        if not (0 <= phase <= 1 and parameters["power"] > 0 and parameters["flow"] > 0
                and all(math.isfinite(v) for v in parameters.values())):
            raise ValueError("Invalid thermal inputs")
        payload = {"model": MODEL_VERSION, "topology": self.mesh.topology_key, "equilibrium": self.equilibrium.key,
                   "parameters": parameters, "phase": phase, "device": str(self.device)}
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]
        signature = (str(self.runtime), key, state["scenario"])
        if signature in self._results:
            result, arrays, metadata = self._results[signature]
            self._results.move_to_end(signature)
            # The service may have reclaimed an old published packet while its
            # bounded in-memory result is still reusable. Republish its arrays.
            reference = result["field_ref"]
            if not (self.runtime / reference["path"]).is_file():
                result["field_ref"] = self._publish(key, reference["revision"], arrays, metadata)
            self.last_signature, self.last_result = signature, result
            self._last_budget = result["power_budget"]
            self._last_radiation, self._last_particle = arrays["surface_heatflux_radiation_MW_m2"], arrays["surface_heatflux_particle_MW_m2"]
            return result
        temperatures, heatflux, gpu_ms = self._solve(parameters, phase)
        budget, radiation, particle = self._last_budget, self._last_radiation, self._last_particle
        candidate = self.metrics(temperatures, heatflux, parameters, budget)
        baseline_parameters = {**parameters, "neon": False}
        baseline_t, baseline_q, _ = self._solve(baseline_parameters, phase)
        baseline = self.metrics(baseline_t, baseline_q, baseline_parameters, self._last_budget)
        delta_t, delta_q = temperatures - baseline_t, heatflux - baseline_q
        max_dt = max(1.0, math.ceil(float(np.max(np.abs(delta_t))) * 10) / 10)
        max_dq = max(0.01, math.ceil(float(np.max(np.abs(delta_q))) * 100) / 100)
        ranges = {"temperature": [min(250, math.floor(float(temperatures.min()) / 50) * 50),
                                  max(1100, math.ceil(float(temperatures.max()) / 100) * 100)],
                  "heatflux": HEATFLUX_RANGE, "heatflux_log": HEATFLUX_LOG_RANGE,
                  "magnetic": MAGNETIC_RANGE, "slice": [0, 40],
                  "delta_temperature": [-max_dt, max_dt], "delta_heatflux": [-max_dq, max_dq]}
        history_key = (self.mesh.topology_key, self.equilibrium.key, state["scenario"], *parameters.values())
        if history_key not in self._histories:
            series_t, series_q, series_budgets = self._solve_history(parameters)
            history = []
            for t, peak_t, peak_q, series_budget in zip(np.linspace(0, 1, 31), series_t, series_q, series_budgets):
                outlet = parameters["inlet"] + series_budget["absorbed_thermal_MW"] * 1e6 / (3500 * parameters["flow"] * 5200)
                history.append({"phase": float(t), "load_fraction": load_fraction(t),
                                "heatflux": round(float(peak_q), 3),
                                "temperature": round(float(peak_t), 2),
                                "peak_temperature_C": round(float(peak_t), 2),
                                "outlet_temperature_C": round(outlet, 2),
                                "absorbed_thermal_MW": series_budget["absorbed_thermal_MW"]})
            remember(self._histories, history_key, history)
        self._histories.move_to_end(history_key)
        history = self._histories[history_key]
        slice_temperature = (np.nan_to_num(np.maximum(1 - self.slice_psin, 0) ** 1.5) *
                             25 * (0.2 * parameters["power"] + parameters["heating"]) / 450 *
                             load_fraction(phase) * (0.95 if neon else 1.0))
        arrays = dict(surface_points=self.points, surface_triangles=self.faces, surface_regions=self.regions,
                      surface_triangle_component=self.regions[self.faces[:, 0]], surface_normals=self.mesh.normals.astype(np.float32),
                      surface_vertex_area_m2=self.mesh.vertex_area, surface_part_id=self.mesh.part_ids,
                      surface_temperature_C=temperatures, surface_heatflux_MW_m2=heatflux,
                      surface_heatflux_radiation_MW_m2=radiation, surface_heatflux_particle_MW_m2=particle,
                      temperature_rgb=colormap(temperatures, *ranges["temperature"]),
                      heatflux_rgb=scientific_colors(heatflux, HEATFLUX_RANGE),
                      heatflux_log_rgb=scientific_colors(heatflux, HEATFLUX_LOG_RANGE, logarithmic=True),
                      delta_temperature_C=delta_t, delta_heatflux_MW_m2=delta_q,
                      delta_temperature_rgb=diverging_colors(delta_t, max_dt), delta_heatflux_rgb=diverging_colors(delta_q, max_dq),
                      magnetic_lines=self.lines, field_line_B_T=self.line_B, field_line_rgb=self.line_rgb,
                      slice_points=self.slice_points, slice_triangles=self.slice_faces,
                      slice_rgb=colormap(slice_temperature, *ranges["slice"]), slice_temperature_keV=slice_temperature.astype(np.float32))
        strikes = self._pattern(parameters["hotspot"], neon).strikes
        cases = self._four_cases(parameters, phase, design, equilibrium)
        selected_id = f"{design}/ne_{'on' if neon else 'off'}"
        selected_case = next(case for case in cases if case["id"] == selected_id)
        story = {"classification": "synthetic_demo", "comparison_controls": {
                     **{k: v for k, v in parameters.items() if k != "neon"}, "equilibrium": equilibrium, "phase": phase},
                 "selected_case_id": selected_id, "cases": cases,
                 "relative_metric": "peak_divertor_heatflux_MW_m2; 100*(case/same-design-no-neon - 1)",
                 "units": {"heatflux": "MW/m2", "temperature": "degC", "power": "MW", "relative_no_neon": "percent"}}
        color_maps = {"heatflux": {"name": "inferno_sampled", "positions": np.linspace(0, 1, len(INFERNO)).tolist(),
                                    "colors": INFERNO, "zero_color": ZERO_COLOR},
                      "magnetic": {"name": "viridis_sampled", "positions": np.linspace(0, 1, len(VIRIDIS)).tolist(),
                                    "colors": VIRIDIS}}
        color_scales = {"heatflux": "linear", "heatflux_log": "log10", "magnetic": "linear"}
        clipping = {"heatflux_above_max": int(np.count_nonzero(heatflux > HEATFLUX_RANGE[1])),
                    "heatflux_log_positive_below_min": int(np.count_nonzero((heatflux > 0) & (heatflux < HEATFLUX_LOG_RANGE[0]))),
                    "heatflux_nonpositive": int(np.count_nonzero(heatflux <= 0)),
                    "magnetic_below_min": int(np.count_nonzero(self.line_B < MAGNETIC_RANGE[0])),
                    "magnetic_above_max": int(np.count_nonzero(self.line_B > MAGNETIC_RANGE[1]))}
        assumptions = {
            "thermal": "Synthetic quasi-steady wall resistance; prescribed load scan, no time-dependent heat transport or qualified material model",
            "coolant": "Absorbed surface plus assumed blanket volume heat only; helium cp=5200 J/(kg K), 3500 kg/s times flow, 85/15% circuit split; unresolved power excluded",
            "budget": "power is the base thermal budget excluding auxiliary heating. At scan fraction L: total=(power+heating)*L; blanket volume=.8*power*L; plasma=(.2*power+heating)*L. Core radiation=.65*plasma; SOL radiation=.30 (Ne off) or .80 (Ne on) of separatrix power, wall particles=.03, targets receive the remainder, inner/outer 30/70%. All heating is assumed absorbed; no solved fusion source",
            "radiation": "Uniform area deposition split 90/10% wall/divertor; no photon transport or neutron transport calculation",
            "target": "Synthetic Eich widths: lambda_q=6 mm, S=2 mm, both divided by hotspot. Ne-on multipliers 1.5/2; longleg S multiplier 1.35. Flux mapping and incidence at source psi=1 intersections, local +/-0.75 m footprint; no 3D shadowing or detached SOL solution",
            "neon": "Boolean radiation/spreading hypothesis; no injection rate, impurity transport, radiation-front solve or measured detachment claim. Four cases share all controls except design/neon; differences use same design/equilibrium/controls with neon off",
            "color": "Fixed linear heatflux 0..200 and log10 0.01..200 MW/m2. Nonpositive/no-data samples are neutral; positive log values below minimum clamp to lower color. Out-of-range counts are explicit; no per-case autoscaling",
            "limit": "900 degC demonstration threshold; not a material qualification limit",
            "magnetics": "Selected Bluemira axisymmetric equilibrium, Bphi=fvac/R approximation; cached per equilibrium; no discrete TF ripple",
            "plasma_slice": "Synthetic source-flux-shaped core profile: 25 keV * (.2*power+heating)/450 * load_fraction, with a prescribed .95 multiplier for Ne on; 193x225 RZ sampling, not a plasma transport solution",
            "history": "Dimensionless quasi-steady load scan, phase in [0,1]; no elapsed-time coordinate; equilibria are independently selected snapshots"}
        metadata = {"data_class": "synthetic_demo", "model_version": MODEL_VERSION,
                    "power_budget": budget, "strike_points": strikes, "parameters": parameters, "phase": phase,
                    "ranges": ranges, "color_scales": color_scales, "color_maps": color_maps, "color_clipping": clipping,
                    "log_zero_policy": "neutral for nonpositive or missing; positive values below 0.01 clamp to lower color",
                    "exhaust_model": exhaust_assumptions(design, neon, parameters["hotspot"]),
                    "assumptions": assumptions, "pfc": self.mesh.provenance,
                    "units": {"geometry": "m", "temperature": "degC", "heatflux": "MW/m2", "slice": "keV", "power": "MW", "magnetic": "T"},
                    "design": design, "equilibrium": equilibrium, "eich_reference": EICH_REFERENCE}
        field_ref = self._publish(key, revision, arrays, metadata)
        result = {**candidate, "field_ref": field_ref, "power_budget": budget, "strike_points": strikes,
                  "model_version": MODEL_VERSION, "color_ranges": ranges, "color_maps": color_maps,
                  "color_scales": color_scales, "color_clipping": clipping, "story": story,
                  "relative_no_neon_percent": selected_case["relative_no_neon_percent"],
                  "analysis_surface": self.mesh.provenance, "design": design, "equilibrium": equilibrium,
                  "gpu_ms": round(gpu_ms, 3), "compute_backend": "CUDA / Warp" if self.device.is_cuda else "CPU / Warp",
                  "gpu_device": str(self.device), "gpu_name": self.device.name,
                  "gpu_timing_scope": "Warp local thermal kernel and synchronization; excludes CPU budget, footprint construction and transfers",
                  "field_samples": len(self.points), "magnetic_line_count": len(self.lines), "magnetic_trace_ms": round(self.trace_ms, 3),
                  "source_label": "synthetic_demo_source_geometry_equilibrium", "scenario_label": state["scenario"],
                  "history": history, "comparison": {"baseline": baseline, "candidate": candidate,
                  "context": {"design": design, "equilibrium": equilibrium, "phase": phase,
                              "baseline_parameters": baseline_parameters, "definition": "same-controls-neon-off"},
                  "delta": {key: round(candidate[key] - baseline[key], 3) for key in baseline}}, "assumptions": assumptions}
        self.last_signature, self.last_result = signature, result
        self._last_budget, self._last_radiation, self._last_particle = budget, radiation, particle
        remember(self._results, signature, (result, arrays, metadata))
        return result
