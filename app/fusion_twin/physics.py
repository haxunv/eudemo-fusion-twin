"""Synthetic quasi-steady heat budget on source equilibria; not a solved fusion source."""

from dataclasses import dataclass
import hashlib

import numpy as np
from scipy.interpolate import RegularGridInterpolator
from scipy.optimize import brentq
from scipy.special import log_ndtr

from .pfc import sample_polyline

DESIGNS = ("conventional", "longleg")
EQUILIBRIA = ("reference", "rampup", "sof", "eof", "rampdown")
HEATING_LEVELS = (20, 35, 50, 65)
EICH_REFERENCE = "https://doi.org/10.1103/PhysRevLett.107.215001"


def exhaust_assumptions(design, neon=False, hotspot=1.0):
    return {"sol_radiation_fraction": 0.80 if neon else 0.30,
            "wall_particle_fraction": 0.03, "core_radiation_fraction": 0.65,
            "lambda_q_m": 0.006 * (1.5 if neon else 1.0) / hotspot,
            "spread_m": 0.002 * (1.35 if design == "longleg" else 1.0) * (2.0 if neon else 1.0) / hotspot,
            "neon": bool(neon), "design": design,
            "classification": "synthetic_radiation_and_spreading_hypothesis"}


def load_fraction(phase):
    return 0.22 + 0.78 * float(phase)


def eich_profile(s, lambda_q=0.006, spread=0.002):
    """Eich et al. 2011 profile in upstream-midplane metres; log form avoids private-flux overflow."""
    a = spread / (2 * lambda_q)
    log_shape = a * a - np.asarray(s) / lambda_q + log_ndtr(-np.sqrt(2) * (a - np.asarray(s) / spread))
    return np.exp(np.clip(log_shape, -745, 50))


class MagneticEquilibrium:
    def __init__(self, source, name):
        path = source / "equilibria" / f"{name}.npz"
        self.key = f"{source.name}/{name}:{hashlib.sha256(path.read_bytes()).hexdigest()[:16]}"
        with np.load(path, allow_pickle=False) as data:
            self.data = {key: data[key].copy() for key in data.files}
        self.name = name
        d = self.data
        self.r, self.z = d["x"][:, 0], d["z"][0]
        self.psi = RegularGridInterpolator((self.r, self.z), d["psi"], bounds_error=False, fill_value=np.nan)
        self.br = RegularGridInterpolator((self.r, self.z), d["Bx"], bounds_error=False, fill_value=np.nan)
        self.bz = RegularGridInterpolator((self.r, self.z), d["Bz"], bounds_error=False, fill_value=np.nan)
        self.axis = d["o_point"][:2]
        lower = d["x_points"][d["x_points"][:, 1] < self.axis[1]]
        self.xpoint = lower[np.argmin(np.abs(lower[:, 2] - float(d["psi_bndry"])))][:2] if len(lower) else None
        rr = np.linspace(self.axis[0] + 0.01, self.r[-1] - 0.01, 6000)
        pn = self.psin(np.column_stack((rr, np.full(len(rr), self.axis[1]))))
        # Outboard midplane map: first monotonic branch from the gridded psi minimum, no extrapolation.
        near_axis = max(2, int(np.searchsorted(rr, self.axis[0] + 0.5)))
        start = int(np.argmin(pn[:near_axis]))
        rr, pn = rr[start:], pn[start:]
        end = np.flatnonzero(np.diff(pn) <= 0)
        stop = int(end[0] + 1) if len(end) else len(rr)
        self.omp_r, self.omp_pn = rr[:stop], pn[:stop]
        self.r_sep = float(np.interp(1, self.omp_pn, self.omp_r)) if self.omp_pn[0] < 1 < self.omp_pn[-1] else None

    def psin(self, rz):
        d = self.data
        return (self.psi(rz) - float(d["psi_axis"])) / float(d["psi_bndry"] - d["psi_axis"])

    def field(self, points):
        r = np.linalg.norm(points[:, :2], axis=1)
        rz = np.column_stack((r, points[:, 2]))
        br, bz = self.br(rz), self.bz(rz)
        bphi = float(self.data["fvac"]) / r
        c, s = points[:, 0] / r, points[:, 1] / r
        return np.column_stack((br * c - bphi * s, br * s + bphi * c, bz))

    def intersections(self, profile):
        """Separatrix (psi_n=1) crossings of the divertor profile below the X-point."""
        points, arc = sample_polyline(profile, 0.005)
        delta = self.psin(points) - 1
        roots = []
        for k in np.flatnonzero(np.isfinite(delta[:-1] * delta[1:]) & (delta[:-1] * delta[1:] <= 0)):
            a, b = points[k], points[k + 1]
            t = brentq(lambda t: float(self.psin((a + t * (b - a))[None, :])[0] - 1), 0, 1)
            p = a + t * (b - a)
            s = float(arc[k] + t * (arc[k + 1] - arc[k]))
            if self.xpoint is None or p[1] >= self.xpoint[1]:
                continue
            if roots and abs(s - roots[-1]["s_m"]) < 1e-5:
                continue
            roots.append({"rz_m": p.tolist(), "s_m": s,
                          "leg": "inner" if p[0] < self.xpoint[0] else "outer",
                          "psi_n_residual": float(self.psin(p[None, :])[0] - 1)})
        return roots


@dataclass
class HeatPattern:
    radiation: np.ndarray
    particle_wall: np.ndarray
    target_inner: np.ndarray
    target_outer: np.ndarray
    strikes: dict


def heat_pattern(mesh, eq, hotspot=1.0, neon=False):
    """Per-MW deposition patterns; each integrates to 1 over 18 sectors, or 0 if unresolved."""
    weights = mesh.vertex_area * 18
    n = len(weights)
    model = exhaust_assumptions(eq.key.split("/", 1)[0], neon, hotspot)

    def normalize(values):
        power = float(np.dot(values, weights))
        return values / power if power > 1e-25 else np.zeros(n)

    wall, div = mesh.regions == 0, mesh.regions == 1
    radiation = 0.90 * normalize(wall.astype(float)) + 0.10 * normalize(div.astype(float))
    particle_wall = normalize(wall.astype(float))
    roots = eq.intersections(mesh.divertor_profile)
    rz = np.column_stack((np.linalg.norm(mesh.points[:, :2], axis=1), mesh.points[:, 2]))
    psin = eq.psin(rz)
    b = eq.field(mesh.points)
    magnitude = np.linalg.norm(b, axis=1)
    incidence = np.abs(np.sum(b * mesh.normals, axis=1)) / np.maximum(magnitude, 1e-30)
    mapped = np.interp(psin, eq.omp_pn, eq.omp_r, left=np.nan, right=np.nan)
    shapes, strikes = {}, {}
    for leg in ("inner", "outer"):
        candidates = [p for p in roots if p["leg"] == leg]
        shape = np.zeros(n)
        if len(candidates) == 1 and eq.r_sep is not None:
            strike = candidates[0]
            mask = div & (np.abs(mesh.poloidal_s - strike["s_m"]) <= 0.75) & np.isfinite(mapped)
            mask &= (rz[:, 0] < eq.xpoint[0]) if leg == "inner" else (rz[:, 0] >= eq.xpoint[0])
            s = mapped[mask] - eq.r_sep
            field_omp = eq.field(np.array([[eq.r_sep, 0.0, eq.axis[1]]]))
            b_omp = float(np.linalg.norm(field_omp[0]))
            shape[mask] = eich_profile(s, model["lambda_q_m"], model["spread_m"]) * incidence[mask] * magnitude[mask] / b_omp
            shape = normalize(shape)
            resolved = bool(np.any(shape > 0))
            strikes[leg] = {**strike, "status": "intersection_model" if resolved else "unresolved",
                            "reason": "source separatrix/cavity crossing; attached synthetic local footprint" if resolved else "no finite wetted samples"}
        else:
            strikes[leg] = {"status": "unresolved", "reason": "missing or ambiguous lower-leg intersection or outboard map",
                            "candidate_count": len(candidates)}
        shapes[leg] = shape
    return HeatPattern(radiation, particle_wall, shapes["inner"], shapes["outer"], strikes)


def prescribed_loads(mesh, pattern, power, phase, heating=50.0, neon=False):
    """Power ledger; target power at an unresolved strike point is reported, not deposited."""
    fraction = load_fraction(phase)
    base = float(power) * fraction
    auxiliary = float(heating) * fraction
    requested = base + auxiliary
    volume = 0.80 * base
    plasma_channel = 0.20 * base + auxiliary
    core_rad = 0.65 * plasma_channel
    sep = plasma_channel - core_rad
    sol_fraction = 0.80 if neon else 0.30
    sol_rad = sol_fraction * sep
    wall_particle = 0.03 * sep
    target = sep - sol_rad - wall_particle
    radiation = (core_rad + sol_rad) * pattern.radiation
    particle = wall_particle * pattern.particle_wall + target * (0.30 * pattern.target_inner + 0.70 * pattern.target_outer)
    weights = mesh.vertex_area * 18
    mask = mesh.regions == 0
    rad_abs = float(np.dot(radiation, weights))
    wall_abs = float(np.dot(particle[mask], weights[mask]))
    div_abs = float(np.dot(particle[~mask], weights[~mask]))
    unresolved = target * (0.30 * (not np.any(pattern.target_inner)) + 0.70 * (not np.any(pattern.target_outer)))
    surface = rad_abs + wall_abs + div_abs
    blanket = volume + float(np.dot((radiation + particle)[mask], weights[mask]))
    divertor = float(np.dot((radiation + particle)[~mask], weights[~mask]))
    budget = {"definition": "synthetic_base_plus_auxiliary_thermal_budget", "load_fraction": fraction,
              "nominal_thermal_MW": float(power), "base_thermal_MW": base,
              "nominal_auxiliary_MW": float(heating), "auxiliary_absorbed_MW": auxiliary,
              "plasma_channel_MW": plasma_channel, "requested_thermal_MW": requested,
              "volume_blanket_MW": volume, "radiation_core_MW": core_rad, "separatrix_MW": sep,
              "sol_radiation_fraction": sol_fraction, "target_requested_MW": target,
              "wall_particle_requested_MW": wall_particle,
              "radiation_sol_MW": sol_rad, "radiation_absorbed_MW": rad_abs,
              "particle_blanket_MW": wall_abs, "particle_divertor_MW": div_abs,
              "surface_absorbed_MW": surface, "volume_absorbed_MW": volume,
              "absorbed_thermal_MW": surface + volume, "unresolved_MW": unresolved,
              "closure_residual_MW": requested - surface - volume - unresolved,
              "blanket_absorbed_MW": blanket, "divertor_absorbed_MW": divertor,
              "full_machine_pfc_area_m2": float(weights.sum())}
    return radiation + particle, radiation, particle, budget
