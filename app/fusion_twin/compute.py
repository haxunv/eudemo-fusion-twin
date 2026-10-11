"""Reproducible demonstration fields and equilibrium tracing on NVIDIA Warp.

The CAD and equilibrium are source data. Thermal loading, coolant flow and
temperature limits are explicitly authored demonstration assumptions.
"""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

import numpy as np
import warp as wp
from scipy.interpolate import RegularGridInterpolator

wp.config.quiet = True


@wp.kernel
def thermal_kernel(
    points: wp.array(dtype=wp.vec3),
    regions: wp.array(dtype=wp.int32),
    power_ratio: float,
    flow: float,
    inlet: float,
    phase: float,
    hotspot: float,
    temperatures: wp.array(dtype=float),
    heatflux: wp.array(dtype=float),
):
    i = wp.tid()
    p = points[i]
    r = wp.sqrt(p[0] * p[0] + p[1] * p[1])
    z = p[2]
    response = 0.22 + 0.78 * (1.0 - wp.exp(-phase * 7.0))
    coolant_rise = power_ratio * (2000.0e6 / (3500.0 * 5200.0)) / flow
    local_coolant = inlet + coolant_rise * (0.3 + 0.25 * (z + 8.0) / 16.0)
    q = float(0.0)
    resistance = float(0.0)
    if regions[i] == 1:
        outer = wp.exp(-wp.pow((r - 9.8) / 1.4, 2.0) - wp.pow((z + 6.25) / 0.9, 2.0))
        inner = wp.exp(-wp.pow((r - 6.0) / 0.85, 2.0) - wp.pow((z + 6.0) / 0.8, 2.0))
        q = (0.12 + 8.7 * outer + 3.6 * inner) * power_ratio * hotspot * response
        resistance = 0.004 / 140.0 + 1.0 / (55000.0 * wp.pow(flow, 0.8))
    else:
        q = (0.26 + 0.74 * wp.exp(-wp.pow((z - 0.5) / 4.5, 2.0))) * power_ratio * response
        resistance = 0.003 / 28.0 + 1.0 / (22000.0 * wp.pow(flow, 0.8))
    heatflux[i] = q
    temperatures[i] = local_coolant + q * 1.0e6 * resistance


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


SCENARIOS = {
    "nominal": {"power": 2000.0, "flow": 1.0, "inlet": 300.0, "hotspot": 1.0},
    "ramp": {"power": 1200.0, "flow": 0.9, "inlet": 280.0, "hotspot": 1.0},
    "lowflow": {"power": 2000.0, "flow": 0.55, "inlet": 300.0, "hotspot": 1.0},
    "highload": {"power": 2400.0, "flow": 0.85, "inlet": 320.0, "hotspot": 1.35},
}


class FieldEngine:
    def __init__(self, root: Path, device: str | None = None):
        self.root = root
        self.source = root / "assets/source/eudemo/conventional"
        self.runtime = root / "runtime"
        self.runtime.mkdir(exist_ok=True)
        wp.init()
        self.device = wp.get_device(device or ("cuda:0" if wp.is_cuda_available() else "cpu"))
        self.points, self.faces, self.regions = self._load_surface()
        self.wp_points = wp.array(self.points, dtype=wp.vec3, device=self.device)
        self.wp_regions = wp.array(self.regions, dtype=wp.int32, device=self.device)
        self.wp_temperature = wp.empty(len(self.points), dtype=float, device=self.device)
        self.wp_heatflux = wp.empty(len(self.points), dtype=float, device=self.device)
        self.eq = dict(np.load(self.source / "equilibria/reference.npz", allow_pickle=False))
        self.lines, self.trace_ms = self._trace_magnetic()
        self.slice_points, self.slice_faces, self.slice_psin = self._make_slice()
        self._solve(SCENARIOS["nominal"], 0.65)
        self.last_signature = None
        self.last_result = None

    def _load_surface(self):
        vertices, triangles, regions = [], [], []
        offset = 0
        for component, region in [("blanket", 0), ("divertor", 1)]:
            for file in sorted((self.source / "cad").glob(f"{component}__p*.npz")):
                with np.load(file, allow_pickle=False) as data:
                    points = data["points"].astype(np.float32)
                    vertices.append(points)
                    triangles.append(data["tris"].astype(np.int32) + offset)
                    regions.append(np.full(len(points), region, dtype=np.int32))
                    offset += len(points)
        return np.concatenate(vertices), np.concatenate(triangles), np.concatenate(regions)

    def _trace_magnetic(self):
        eq = self.eq
        r = eq["x"][:, 0]
        z = eq["z"][0]
        axis = eq["o_point"]
        lcfs_r = float(eq["lcfs"][0].max())
        seeds = np.array([[axis[0] + frac * (lcfs_r - axis[0]), axis[1], phi] for frac in (0.3, 0.55, 0.8, 0.94) for phi in np.linspace(0, 2 * np.pi, 6, endpoint=False)], dtype=np.float32)
        steps = 1800
        output = wp.empty((len(seeds), steps), dtype=wp.vec3, device=self.device)
        inputs = [wp.array(seeds, dtype=wp.vec3, device=self.device), wp.array(eq["Bx"].astype(np.float32), device=self.device), wp.array(eq["Bz"].astype(np.float32), device=self.device), float(r[0]), float(z[0]), float(r[1] - r[0]), float(z[1] - z[0]), float(eq["fvac"]), steps, 0.026, output]
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
        r, z = np.linspace(3.7, 13.3, 97), np.linspace(-7, 6, 121)
        rr, zz = np.meshgrid(r, z, indexing="ij")
        coords = np.stack([rr.ravel(), zz.ravel()], axis=-1)
        interp = RegularGridInterpolator((eq["x"][:, 0], eq["z"][0]), eq["psi"], bounds_error=False, fill_value=np.nan)
        psin = (interp(coords) - float(eq["psi_axis"])) / float(eq["psi_bndry"] - eq["psi_axis"])
        points = np.stack([rr.ravel(), np.full(rr.size, -0.04), zz.ravel()], axis=-1).astype(np.float32)
        triangles = []
        for i in range(len(r) - 1):
            for j in range(len(z) - 1):
                a = i * len(z) + j
                for tri in ((a, a + len(z), a + 1), (a + 1, a + len(z), a + len(z) + 1)):
                    if all(0 <= psin[k] <= 1 and points[k, 2] > -5.4 for k in tri):
                        triangles.append(tri)
        return points, np.array(triangles, dtype=np.int32), psin

    def _solve(self, parameters: dict, phase: float):
        started = time.perf_counter()
        wp.launch(thermal_kernel, dim=len(self.points), inputs=[self.wp_points, self.wp_regions, float(parameters["power"]) / 2000, float(parameters["flow"]), float(parameters["inlet"]), float(phase), float(parameters.get("hotspot", 1)), self.wp_temperature, self.wp_heatflux], device=self.device)
        wp.synchronize_device(self.device)
        milliseconds = (time.perf_counter() - started) * 1000
        return self.wp_temperature.numpy().copy(), self.wp_heatflux.numpy().copy(), milliseconds

    @staticmethod
    def metrics(temperature, heatflux, parameters):
        # 3500 kg/s helium, cp=5200 J/(kg K), assumed effective thermal load=power MW.
        mass_flow = 3500 * parameters["flow"]
        outlet = parameters["inlet"] + parameters["power"] * 1e6 / (mass_flow * 5200)
        peak = float(np.max(temperature))
        return {"peak_temperature_C": round(peak, 2), "peak_heatflux_MW_m2": round(float(np.max(heatflux)), 3), "outlet_temperature_C": round(outlet, 2), "cooling_margin_C": round(900 - peak, 2), "limit_temperature_C": 900.0, "mass_flow_kg_s": round(mass_flow, 1), "thermal_power_MW": parameters["power"]}

    def compute(self, state: dict, revision: int) -> dict:
        parameters = {key: float(state[key]) for key in ("power", "flow", "inlet")}
        parameters["hotspot"] = SCENARIOS[state["scenario"]]["hotspot"]
        phase = float(state["phase"])
        signature = (state["scenario"], *parameters.values(), phase)
        if signature == self.last_signature:
            return self.last_result
        temperatures, heatflux, gpu_ms = self._solve(parameters, phase)
        candidate = self.metrics(temperatures, heatflux, parameters)
        baseline_t, baseline_q, _ = self._solve(SCENARIOS["nominal"], phase)
        baseline = self.metrics(baseline_t, baseline_q, SCENARIOS["nominal"])
        history = []
        for t in np.linspace(0, 1, 31):
            series_t, series_q, _ = self._solve(parameters, float(t))
            temp = round(float(np.max(series_t)), 2)
            history.append({"phase": round(float(t), 4), "time_s": round(float(t * 600), 1), "heatflux": round(float(np.max(series_q)), 3), "temperature": temp, "peak_temperature_C": temp})
        slice_temperature = np.nan_to_num(np.maximum(1 - self.slice_psin, 0) ** 1.5) * 25 * parameters["power"] / 2000
        arrays = dict(surface_points=self.points, surface_triangles=self.faces, surface_regions=self.regions, surface_triangle_component=self.regions[self.faces[:, 0]], surface_temperature_C=temperatures, surface_heatflux_MW_m2=heatflux, temperature_rgb=colormap(temperatures, 300, 1100), heatflux_rgb=colormap(heatflux, 0, 12), magnetic_lines=self.lines, slice_points=self.slice_points, slice_triangles=self.slice_faces, slice_rgb=colormap(slice_temperature, 0, 30), slice_temperature_keV=slice_temperature.astype(np.float32))
        temporary = self.runtime / "fields.tmp.npz"
        np.savez(temporary, **arrays)
        atomic_replace(temporary, self.runtime / "fields.npz")
        atomic_json(self.runtime / "fields.json", {"revision": revision, "path": "runtime/fields.npz", "ranges": {"temperature": [300, 1100], "heatflux": [0, 12], "slice": [0, 30]}, "source": "Synthetic thermal boundary conditions + reduced-order heat transfer; Bluemira reference magnetic equilibrium", "units": {"geometry": "m", "temperature": "degC", "heatflux": "MW/m2", "slice": "keV"}, "device": str(self.device), "magnetic_integration": "RK4, dphi=0.026 rad, 1800 steps, Bphi=fvac/R"})
        result = {**candidate, "gpu_ms": round(gpu_ms, 3), "compute_backend": "CUDA / Warp" if self.device.is_cuda else "CPU / Warp", "gpu_device": str(self.device), "gpu_name": self.device.name, "gpu_timing_scope": "Warp launch + synchronized kernel, excludes host transfer", "field_samples": len(self.points), "magnetic_line_count": len(self.lines), "magnetic_trace_ms": round(self.trace_ms, 3), "source_label": "synthetic_thermal_bluemira_equilibrium", "scenario_label": state["scenario"], "history": history, "comparison": {"baseline": baseline, "candidate": candidate, "delta": {key: round(candidate[key] - baseline[key], 3) for key in baseline}}, "assumptions": {"thermal": "Synthetic surface heat-flux distribution and wall thermal resistance; not normalized as a conservative full-reactor heat solution", "coolant": "Separate assumed helium circuit energy balance: cp=5200 J/(kg K), nominal flow=3500 kg/s", "limit": "900 degC demonstration threshold; not a material qualification limit", "magnetics": "Bluemira reference equilibrium, Bphi=fvac/R approximation; unchanged by thermal controls", "plasma_slice": "Synthetic 25 keV core profile shaped by source normalized poloidal flux"}}
        self.last_signature, self.last_result = signature, result
        return result
