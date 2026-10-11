# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LGPL-2.1-or-later
#
# Runs inside the bluemira-eudemo conda env (WSL). Drives the EU-DEMO reactor design
# routine from bluemira-eudemo/studies/first/reactor.py and harvests everything the
# fusion digital twin needs, per divertor configuration:
#
#   cad/<manager>.npz         tessellated single-sector solids (per named part)
#   cad/<manager>.stp         same sector as STEP (for usd-convert-cad)
#   equilibria/<state>.npz    psi / Bx / Bz maps, LCFS, separatrix, coils, profiles
#   machine.json              TF centreline + winding pack, 2D silhouettes, params
#
# Usage: python harvest_eudemo.py <out_dir> <variant> [param=value ...] [bc:Section.key=value ...]
"""Harvest EU-DEMO design data from bluemira for the Omniverse fusion twin."""

import importlib.util
import json
import sys
import time
import traceback
from copy import deepcopy
from pathlib import Path

import numpy as np

STUDY = Path.home() / "fusion/eudemo/studies/first"
sys.path.insert(0, str(STUDY))


def _load_reactor_module():
    spec = importlib.util.spec_from_file_location("eudemo_reactor", STUDY / "reactor.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _load_reactor_module()

from bluemira.base.look_and_feel import bluemira_print, bluemira_warn  # noqa: E402
from bluemira.base.reactor_config import ReactorConfig  # noqa: E402
from bluemira.base.tools import ConstructionParamValues  # noqa: E402
from bluemira.equilibria.optimisation.constraints import (  # noqa: E402
    FieldNullConstraint,
    IsofluxConstraint,
    MagneticConstraintSet,
)
from bluemira.equilibria.optimisation.problem import (  # noqa: E402
    UnconstrainedTikhonovCurrentGradientCOP,
)
from bluemira.equilibria.profiles import CustomProfile  # noqa: E402
from bluemira.equilibria.shapes import JohnerLCFS  # noqa: E402
from bluemira.equilibria.solve import DudsonConvergence, PicardIterator  # noqa: E402

TESS_TOL = 0.02  # [m] linear deflection for tessellation


def _coords(c):
    return np.asarray(c.xyz, dtype=np.float64)


def _wire_xyz(wire, n=400):
    if hasattr(wire, "create_shape"):  # GeometryParameterisation (e.g. TF TripleArc)
        wire = wire.create_shape()
    return np.asarray(wire.discretise(byedges=True, ndiscr=n).xyz, dtype=np.float64)


def _safe(label, fn):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        bluemira_warn(f"export of {label} failed:\n" + traceback.format_exc())
        return None


def _variant_build_config(build_overrides: dict) -> str:
    """Write a sibling build_config with nested overrides ("Lower Port.params.lp_height.value")."""
    if not build_overrides:
        return R.BUILD_CONFIG_FILE_PATH
    cfg = json.loads(Path(R.BUILD_CONFIG_FILE_PATH).read_text())
    for dotted, value in build_overrides.items():
        node = cfg
        *parents, leaf = dotted.split(".")
        for p in parents:
            node = node[p]
        node[leaf] = value
    path = Path(R.BUILD_CONFIG_FILE_PATH).with_name("build_config_fusion_twin.json")
    path.write_text(json.dumps(cfg, indent=4))
    return path.as_posix()


def run_design(variant_overrides: dict, build_overrides: dict | None = None):
    """Re-run the EU-DEMO design routine (mirrors studies/first/reactor.py __main__)."""
    reactor_config = ReactorConfig(
        _variant_build_config(build_overrides or {}), R.EUDEMOReactorParams
    )
    for name, value in variant_overrides.items():
        getattr(reactor_config.global_params, name).set_value(value, "fusion-twin")
    n_TF = reactor_config.global_params.n_TF.value
    reactor = R.EUDEMO("EUDEMO", n_sectors=n_TF)
    R.establish_material_cache(["eudemo.materials", "matproplib"])

    R.radial_build(
        reactor_config.params_for("Radial build").global_params,
        reactor_config.config_for("Radial build"),
    )
    lcfs_coords, profiles = R.run_designer(
        R.FixedEquilibriumDesigner,
        reactor_config.params_for("Fixed boundary equilibrium"),
        reactor_config.config_for("Fixed boundary equilibrium"),
    )
    lcfs_coords, profiles = R.run_designer(
        R.DummyFixedEquilibriumDesigner,
        reactor_config.params_for("Dummy fixed boundary equilibrium"),
        reactor_config.config_for("Dummy fixed boundary equilibrium"),
    )
    reactor.equilibria = R.EquilibriumManager()
    reference_eq = R.build_reference_equilibrium(
        reactor_config.params_for("Free boundary equilibrium"),
        reactor_config.config_for("Free boundary equilibrium"),
        reactor.equilibria,
        lcfs_coords,
        profiles,
    )
    reactor.plasma = R.build_plasma(
        reactor_config.params_for("Plasma"), reactor_config.config_for("Plasma"), reference_eq
    )
    ivc_shapes = R.design_ivc(
        reactor_config.params_for("IVC").global_params,
        reactor_config.config_for("IVC"),
        equilibrium=reference_eq,
    )
    reactor.vacuum_vessel = R.build_vacuum_vessel(
        reactor_config.params_for("Vacuum vessel"),
        reactor_config.config_for("Vacuum vessel"),
        ivc_shapes.outer_boundary,
    )
    reactor.divertor = R.build_divertor(
        reactor_config.params_for("Divertor"),
        reactor_config.config_for("Divertor"),
        ivc_shapes.divertor_face,
    )
    upper_port_koz_xz, r_inner_cut, cut_angle = R.UpperPortKOZDesigner(
        reactor_config.params_for("Upper Port"),
        reactor_config.config_for("Upper Port"),
        ivc_shapes.blanket_face,
    ).execute()
    reactor.blanket = R.build_blanket(
        reactor_config.params_for("Blanket"),
        reactor_config.config_for("Blanket"),
        ivc_shapes.inner_boundary,
        ivc_shapes.blanket_face,
        r_inner_cut,
        cut_angle,
    )
    zero_d_params = R.ZeroDNeutronicsModel(reactor_config.global_params).run()
    reactor_config.global_params.update_from_frame(zero_d_params)
    reactor.neutronics = R.NeutronicsManager(zero_d_params, None)

    vv_thermal_shield = R.build_vacuum_vessel_thermal_shield(
        reactor_config.params_for("Thermal shield"),
        reactor_config.config_for("Thermal shield", "VVTS"),
        reactor.vacuum_vessel.xz_boundary,
    )
    reactor.tf_coils, peak_opt_ripple = R.build_tf_coils(
        reactor_config.params_for("TF coils"),
        reactor_config.config_for("TF coils"),
        reactor.plasma.lcfs(),
        vv_thermal_shield.xz_boundary,
    )
    reactor_config.global_params.TF_peak_ripple_opt.set_value(peak_opt_ripple, "BLUEMIRA")
    eq_port_koz_xz = R.EquatorialPortKOZDesigner(
        reactor_config.params_for("Equatorial Port"),
        reactor_config.config_for("Equatorial Port"),
        x_ob=20.0,
    ).execute()
    (
        _lp_duct_xz_void_space,
        lower_port_koz_xz,
        lp_duct_angled_nowall_extrude_boundary,
        lp_duct_straight_nowall_extrude_boundary,
    ) = R.LowerPortKOZDesigner(
        reactor_config.params_for("Lower Port"),
        reactor_config.config_for("Lower Port"),
        ivc_shapes.divertor_face,
        ivc_shapes.div_wall_join_pt,
        reactor.tf_coils.xz_outer_boundary,
    ).execute()
    reactor.pf_coils = R.build_pf_coils(
        reactor_config.params_for("PF coils"),
        reactor_config.config_for("PF coils"),
        reactor.equilibria,
        reactor.tf_coils.xz_outer_boundary,
        pf_coil_keep_out_zones=[upper_port_koz_xz, eq_port_koz_xz, lower_port_koz_xz],
    )
    cryostat_thermal_shield = R.build_cryots(
        reactor_config.params_for("Thermal shield"),
        reactor_config.config_for("Thermal shield", "Cryostat"),
        reactor.pf_coils.xz_boundary,
        reactor.tf_coils.xz_outer_boundary,
    )
    reactor.thermal_shield = R.assemble_thermal_shield(vv_thermal_shield, cryostat_thermal_shield)
    reactor.coil_structures = R.build_coil_structures(
        reactor_config.params_for("Coil structures"),
        reactor_config.config_for("Coil structures"),
        tf_coil_xz_face=reactor.tf_coils.xz_face,
        pf_coil_xz_wires=reactor.pf_coils.PF_xz_boundary,
        pf_coil_keep_out_zones=[upper_port_koz_xz, eq_port_koz_xz, lower_port_koz_xz],
    )
    reactor.cryostat = R.build_cryostat(
        reactor_config.params_for("Cryostat"),
        reactor_config.config_for("Cryostat"),
        cryostat_thermal_shield.xz_boundary,
    )
    reactor.radiation_shield = R.build_radiation_shield(
        reactor_config.params_for("RadiationShield"),
        reactor_config.config_for("RadiationShield"),
        reactor.cryostat.xz_boundary,
    )
    ts_upper_port, vv_upper_port = R.build_upper_port(
        reactor_config.params_for("Upper Port"),
        reactor_config.config_for("Upper Port"),
        upper_port_koz_xz,
        cryostat_thermal_shield.xz_boundary,
    )
    ts_eq_port, vv_eq_port = R.build_equatorial_port(
        reactor_config.params_for("Equatorial Port"),
        reactor_config.config_for("Equatorial Port"),
        cryostat_thermal_shield.xz_boundary,
    )
    ts_lower_port, vv_lower_port = R.build_lower_port(
        reactor_config.params_for("Lower Port"),
        reactor_config.config_for("Lower Port"),
        lp_duct_angled_nowall_extrude_boundary,
        lp_duct_straight_nowall_extrude_boundary,
        reactor.cryostat.xz_boundary,
    )
    reactor.vacuum_vessel.add_ports([vv_upper_port, vv_eq_port, vv_lower_port], n_TF=n_TF)
    reactor.thermal_shield.add_ports([ts_upper_port, ts_eq_port, ts_lower_port], n_TF=n_TF)
    cr_plugs = R.build_cryostat_plugs(
        reactor_config.params_for("Cryostat"),
        reactor_config.config_for("Cryostat"),
        [ts_upper_port, ts_eq_port, ts_lower_port],
        reactor.cryostat.xz_boundary,
    )
    rs_plugs = R.build_radiation_plugs(
        reactor_config.params_for("RadiationShield"),
        reactor_config.config_for("RadiationShield"),
        cr_plugs,
        reactor.radiation_shield.xz_boundary,
    )
    reactor.cryostat.add_plugs(cr_plugs, n_TF=n_TF)
    reactor.radiation_shield.add_plugs(rs_plugs, n_TF=n_TF)

    sspc = R.SteadyStatePowerCycleSolver(reactor_config.global_params).execute()
    reactor_config.global_params.P_el_net.set_value(sspc["P_el_net"], "BLUEMIRA")
    try:
        R.add_useful_parameters(reactor, reactor_config, reference_eq)
    except Exception:  # noqa: BLE001
        bluemira_warn("add_useful_parameters failed:\n" + traceback.format_exc())
    return reactor, reactor_config, reference_eq, ivc_shapes


# ---------------------------------------------------------------------------------------
# CAD
# ---------------------------------------------------------------------------------------
_MANAGERS = [
    "plasma",
    "vacuum_vessel",
    "thermal_shield",
    "divertor",
    "blanket",
    "tf_coils",
    "pf_coils",
    "coil_structures",
    "cryostat",
    "radiation_shield",
]


def export_cad(reactor, out: Path):
    cad = out / "cad"
    cad.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name in _MANAGERS:
        manager = getattr(reactor, name, None)
        if manager is None:
            continue
        t0 = time.time()
        cpv = reactor._init_construction_param_values(
            None, {"n_sectors": 1, "disable_composite_grouping": True}
        )
        cpv.with_components = [manager]
        try:
            tree = reactor._build_component_tree("xyz", cpv, for_save=True)
        except Exception:  # noqa: BLE001
            bluemira_warn(f"CAD build failed for {name}:\n" + traceback.format_exc())
            continue
        leaves = tree.leaves
        parts = {}
        for i, leaf in enumerate(leaves):
            shape = getattr(leaf, "shape", None)
            if shape is None:
                continue
            try:
                verts, tris = shape._tessellate(TESS_TOL)
            except Exception:  # noqa: BLE001
                bluemira_warn(f"tessellation failed for {name}/{leaf.name}")
                continue
            mat = getattr(leaf, "material", None)
            key = f"p{i:03d}"
            parts[key] = {
                "name": leaf.name,
                "path": "/".join(a.name for a in leaf.path[1:]),
                "material": getattr(mat, "name", None) if mat is not None else None,
                "n_tris": int(len(tris)),
            }
            np.savez_compressed(
                cad / f"{name}__{key}.npz",
                points=np.asarray(verts, dtype=np.float32),
                tris=np.asarray(tris, dtype=np.int32),
            )
        try:
            reactor.save_cad(
                with_components=[manager],
                n_sectors=1,
                disable_composite_grouping=True,
                filename=name,
                directory=str(cad),
            )
        except Exception:  # noqa: BLE001
            bluemira_warn(f"STEP export failed for {name}:\n" + traceback.format_exc())
        manifest[name] = parts
        bluemira_print(
            f"CAD {name}: {len(parts)} parts, "
            f"{sum(p['n_tris'] for p in parts.values()):,} tris in {time.time() - t0:.1f}s"
        )
    (cad / "manifest.json").write_text(json.dumps(manifest, indent=1))


# ---------------------------------------------------------------------------------------
# Equilibria
# ---------------------------------------------------------------------------------------
def _eq_payload(eq, label: str) -> dict:
    psi = eq.psi()
    o_points, x_points = eq.get_OX_points(psi)
    lcfs = eq.get_LCFS(psi)
    try:
        sep = eq.get_separatrix(psi)
        sep = sep[0] if isinstance(sep, list) else sep
        sep_xyz = _coords(sep)
    except Exception:  # noqa: BLE001
        sep_xyz = np.zeros((3, 0))
    psinorm = np.linspace(0, 1, 101)
    cs = eq.coilset
    try:
        q = np.asarray(eq.q(np.linspace(0.02, 0.98, 25), o_points=o_points, x_points=x_points))
    except Exception:  # noqa: BLE001
        q = np.zeros(25)
    summary = {}
    try:
        summary = {k: float(v.value) for k, v in eq.analyse_plasma().to_dict().items()}
    except Exception:  # noqa: BLE001
        try:
            s = eq.analyse_plasma()
            summary = {k: float(getattr(s, k).value) for k in s.__annotations__}
        except Exception:  # noqa: BLE001
            summary = {}
    return {
        "label": np.array(label),
        "x": np.asarray(eq.x, dtype=np.float64),
        "z": np.asarray(eq.z, dtype=np.float64),
        "psi": np.asarray(psi, dtype=np.float64),
        "Bx": np.asarray(eq.Bx(), dtype=np.float64),
        "Bz": np.asarray(eq.Bz(), dtype=np.float64),
        "fvac": np.array(float(eq.fvac())),
        "psi_axis": np.array(float(o_points[0].psi)),
        "psi_bndry": np.array(float(x_points[0].psi) if x_points else float(np.amin(psi))),
        "o_point": np.array([o_points[0].x, o_points[0].z]),
        "x_points": np.array([[p.x, p.z, p.psi] for p in x_points[:2]]) if x_points else np.zeros((0, 3)),
        "lcfs": _coords(lcfs),
        "separatrix": sep_xyz,
        "psinorm": psinorm,
        "pprime": np.asarray(eq.pprime(psinorm), dtype=np.float64),
        "ffprime": np.asarray(eq.ffprime(psinorm), dtype=np.float64),
        "pressure": np.asarray(eq.pressure(psinorm), dtype=np.float64),
        "fRBpol": np.asarray(eq.fRBpol(psinorm), dtype=np.float64),
        "q_psinorm": np.linspace(0.02, 0.98, 25),
        "q": q,
        "coil_names": np.array(cs.name),
        "coil_x": np.asarray(cs.x),
        "coil_z": np.asarray(cs.z),
        "coil_dx": np.asarray(cs.dx),
        "coil_dz": np.asarray(cs.dz),
        "coil_current": np.asarray(cs.current),
        "coil_ctype": np.array([str(c) for c in cs.ctype]),
        "I_p": np.array(float(eq.profiles.I_p)),
        "summary": np.array(json.dumps(summary)),
    }


def _solve_ramp_state(snapshot, ip_scale: float, a_scale: float, kappa: float, delta: float):
    """Free-boundary solve for a reduced-current ramp phase on the final PF coilset."""
    eq = deepcopy(snapshot.eq)
    prof = eq.profiles
    pn = np.linspace(0, 1, 50)
    eq.profiles = CustomProfile(
        prof.pprime(pn) * ip_scale**2,
        prof.ffprime(pn) * ip_scale,
        prof.R_0,
        prof._B_0,
        I_p=prof.I_p * ip_scale,
    )
    o = eq.get_OX_points()[0][0]
    lcfs = eq.get_LCFS()
    a0 = 0.5 * (np.max(lcfs.x) - np.min(lcfs.x))
    r0 = 0.5 * (np.max(lcfs.x) + np.min(lcfs.x))
    shape = JohnerLCFS({
        "r_0": {"value": r0 - 0.15 * (1 - a_scale) * a0},
        "z_0": {"value": o.z},
        "a": {"value": a0 * a_scale},
        "kappa_u": {"value": kappa * 0.95},
        "kappa_l": {"value": kappa * 1.05},
        "delta_u": {"value": delta},
        "delta_l": {"value": delta},
        "phi_u_neg": {"value": 0.0},
        "phi_u_pos": {"value": 0.0},
        "phi_l_neg": {"value": 45.0},
        "phi_l_pos": {"value": 30.0},
    })
    c = shape.create_shape().discretise(byedges=True, ndiscr=60)
    i_in = int(np.argmin(c.x))
    isoflux = IsofluxConstraint(c.x, c.z, c.x[i_in], c.z[i_in], tolerance=0.5, constraint_value=0.0)
    i_xp = int(np.argmin(c.z))
    x_point = FieldNullConstraint(c.x[i_xp], c.z[i_xp], tolerance=1e-4)
    problem = UnconstrainedTikhonovCurrentGradientCOP(
        eq, MagneticConstraintSet([isoflux, x_point]), gamma=1e-7
    )
    PicardIterator(
        problem, convergence=DudsonConvergence(1e-2), fixed_coils=True, relaxation=0.2, maxiter=60
    )()
    return eq


def divertor_target_points(div_boundary: np.ndarray, x_point_r: float) -> tuple:
    """Mid-points of the inner and outer target plates (steep segments) of the divertor contour."""
    r, z = div_boundary[0], div_boundary[2]
    seg = np.hypot(np.diff(r), np.diff(z))
    steep = np.abs(np.diff(z)) / np.maximum(seg, 1e-9) > 0.6
    rm, zm = 0.5 * (r[1:] + r[:-1]), 0.5 * (z[1:] + z[:-1])
    targets = []
    for side in (rm < x_point_r, rm > x_point_r):
        sel = steep & side
        w = seg[sel]
        targets.append((float(np.sum(rm[sel] * w) / w.sum()), float(np.sum(zm[sel] * w) / w.sum())))
    return targets[0], targets[1]


def _solve_with_divertor_legs(snapshot, div_boundary: np.ndarray):
    """Re-solve a flat-top state on its coilset with the separatrix legs aimed at the target plates.

    The pulsed PF optimisation only constrains the LCFS and X-point, so its legs can drift onto the
    divertor dome. Isoflux points along straight legs from the X-point to the centres of the inner and
    outer target plates of the bluemira divertor put the strike points back on the targets.
    """
    eq = deepcopy(snapshot.eq)
    psi = eq.psi()
    _, x_points = eq.get_OX_points(psi)
    xp = x_points[0]
    (ri, zi_), (ro, zo_) = divertor_target_points(div_boundary, xp.x)
    lcfs = eq.get_LCFS(psi)
    stride = max(len(lcfs.x) // 70, 1)
    lx, lz = np.asarray(lcfs.x)[::stride], np.asarray(lcfs.z)[::stride]
    t = np.linspace(0.12, 1.0, 10)
    xo, zo = xp.x + t * (ro - xp.x), xp.z + t * (zo_ - xp.z)
    xi, zi = xp.x + t * (ri - xp.x), xp.z + t * (zi_ - xp.z)
    i_in = int(np.argmin(lx))
    iso = IsofluxConstraint(
        np.r_[lx, xo, xi],
        np.r_[lz, zo, zi],
        lx[i_in],
        lz[i_in],
        tolerance=1e-3,
        constraint_value=0.0,
    )
    null = FieldNullConstraint(xp.x, xp.z, tolerance=1e-4)
    problem = UnconstrainedTikhonovCurrentGradientCOP(eq, MagneticConstraintSet([iso, null]), gamma=1e-8)
    PicardIterator(
        problem, convergence=DudsonConvergence(1e-3), fixed_coils=True, relaxation=0.2, maxiter=80
    )()
    return eq


def export_equilibria(reactor, reference_eq, ivc_shapes, out: Path):
    eqd = out / "equilibria"
    eqd.mkdir(parents=True, exist_ok=True)
    mgr = reactor.equilibria
    states = {"reference": mgr.get_state(mgr.REFERENCE)}
    for key in ("BREAKDOWN", "SOF", "EOF"):
        states[key.lower()] = mgr.get_state(getattr(mgr, key))
    saved = []
    for name, snap in states.items():
        if snap is None:
            continue
        try:
            np.savez_compressed(eqd / f"{name}.npz", **_eq_payload(snap.eq, name))
            saved.append(name)
        except Exception:  # noqa: BLE001
            bluemira_warn(f"equilibrium export failed for {name}:\n" + traceback.format_exc())
    for name in ("sof", "eof"):
        snap = states.get(name)
        if snap is None:
            continue
        try:
            eq = _solve_with_divertor_legs(snap, _wire_xyz(ivc_shapes.div_internal_boundary, 600))
            payload = _eq_payload(eq, f"{name}_legs")
            payload["solver"] = np.array("bluemira free-boundary + EU-DEMO divertor-leg constraints")
            np.savez_compressed(eqd / f"{name}_legs.npz", **payload)
            saved.append(f"{name}_legs")
        except Exception:  # noqa: BLE001
            bluemira_warn(f"leg-constrained solve failed for {name}:\n" + traceback.format_exc())
    for name, base, kw in (
        ("rampup", "sof", {"ip_scale": 0.55, "a_scale": 0.80, "kappa": 1.55, "delta": 0.30}),
        ("rampdown", "eof", {"ip_scale": 0.45, "a_scale": 0.78, "kappa": 1.50, "delta": 0.28}),
    ):
        snap = states.get(base)
        if snap is None:
            continue
        try:
            eq = _solve_ramp_state(snap, **kw)
            payload = _eq_payload(eq, name)
            payload["solver"] = np.array("bluemira free-boundary (fixed final PF coilset)")
            np.savez_compressed(eqd / f"{name}.npz", **payload)
            saved.append(name)
        except Exception:  # noqa: BLE001
            bluemira_warn(f"ramp-state solve failed for {name}:\n" + traceback.format_exc())
    bluemira_print(f"equilibria saved: {saved}")
    return saved


# ---------------------------------------------------------------------------------------
# Machine description (TF centreline, silhouettes, params)
# ---------------------------------------------------------------------------------------
def export_machine(reactor, reactor_config, ivc_shapes, out: Path, variant: str):
    tf = reactor.tf_coils
    solver = tf._field_solver
    gp = reactor_config.global_params
    items = {
        "tf_centreline": lambda: _wire_xyz(tf.centreline, 300).tolist(),
        "tf_wp_width": lambda: float(gp.tf_wp_width.value),
        "tf_wp_depth": lambda: float(gp.tf_wp_depth.value),
        "tf_current_per_coil": lambda: float(solver.sources[0].sources[0].current),
        "tf_xz_outer": lambda: _wire_xyz(tf.xz_outer_boundary, 300).tolist(),
        "divertor_silhouette": lambda: _wire_xyz(reactor.divertor.silhouette(), 300).tolist(),
        "fw_inner_boundary": lambda: _wire_xyz(ivc_shapes.inner_boundary, 500).tolist(),
        "ivc_outer_boundary": lambda: _wire_xyz(ivc_shapes.outer_boundary, 400).tolist(),
        "div_internal_boundary": lambda: _wire_xyz(ivc_shapes.div_internal_boundary, 300).tolist(),
        "div_wall_join_pt": lambda: list(map(float, ivc_shapes.div_wall_join_pt)),
        "vv_xz_boundary": lambda: _wire_xyz(reactor.vacuum_vessel.xz_boundary, 400).tolist(),
        "plasma_lcfs": lambda: _wire_xyz(reactor.plasma.lcfs(), 400).tolist(),
        "blanket_panel_points": lambda: _coords(reactor.blanket.panel_points).tolist(),
    }
    data = {"variant": variant, "n_TF": int(gp.n_TF.value), "params": {}}
    for key, fn in items.items():
        data[key] = _safe(key, fn)
    try:
        for k, v in gp.to_dict(use_last=True).items():
            val = v.get("value") if isinstance(v, dict) else v
            if isinstance(val, (int, float, str, bool)) or val is None:
                data["params"][k] = {"value": val, "unit": v.get("unit") if isinstance(v, dict) else None}
    except Exception:  # noqa: BLE001
        bluemira_warn("param export failed:\n" + traceback.format_exc())
    (out / "machine.json").write_text(json.dumps(data, indent=1))


def main():
    out = Path(sys.argv[1]).expanduser()
    variant = sys.argv[2]
    # Remaining args: <global_param>=<float> or bc:<dotted.build.config.path>=<float>;
    # "--only=machine,equilibria,cad" restricts which exports run.
    overrides, build_overrides = {}, {}
    only = {"machine", "equilibria", "cad"}
    for arg in sys.argv[3:]:
        if arg.startswith("--only="):
            only = set(arg.split("=", 1)[1].split(","))
            continue
        key, value = arg.split("=", 1)
        if key.startswith("bc:"):
            build_overrides[key[3:]] = float(value)
        else:
            overrides[key] = float(value)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    reactor, reactor_config, reference_eq, ivc_shapes = run_design(overrides, build_overrides)
    bluemira_print(f"design complete in {time.time() - t0:.0f}s")
    if "machine" in only:
        _safe("machine", lambda: export_machine(reactor, reactor_config, ivc_shapes, out, variant))
    if "equilibria" in only:
        _safe("equilibria", lambda: export_equilibria(reactor, reference_eq, ivc_shapes, out))
    if "cad" in only:
        _safe("cad", lambda: export_cad(reactor, out))
    bluemira_print(f"harvest '{variant}' complete in {time.time() - t0:.0f}s -> {out}")


if __name__ == "__main__":
    main()
