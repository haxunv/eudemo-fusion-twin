"""Bake 80 immutable design/heating/neon/equilibrium cases into a staging directory."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from fusion_twin.compute import FieldEngine, MODEL_VERSION, SCENARIOS, atomic_json
from fusion_twin.physics import DESIGNS, EQUILIBRIA, HEATING_LEVELS


def planned_cases(designs=DESIGNS, equilibria=EQUILIBRIA, heating_levels=HEATING_LEVELS):
    for design in designs:
        for equilibrium in equilibria:
            for heating in heating_levels:
                for neon in (False, True):
                    identifier = f"{design}/{equilibrium}/h{heating}/ne_{'on' if neon else 'off'}"
                    state = {**{k: v for k, v in SCENARIOS["nominal"].items() if k != "hotspot"},
                             "scenario": "nominal", "phase": 1.0, "design": design,
                             "equilibrium": equilibrium, "heating": heating, "neon": neon}
                    yield identifier, state


def bake(output, *, designs=DESIGNS, equilibria=EQUILIBRIA, heating_levels=HEATING_LEVELS, device=None):
    output = Path(output).resolve()
    for protected in (ROOT / "runtime", ROOT / "assets/scenarios"):
        if output == protected.resolve() or protected.resolve() in output.parents:
            raise ValueError("Bake into staging; live runtime and shipped scenarios cannot be overwritten")
    engine = FieldEngine(ROOT, device=device, runtime=output, compress_fields=True)
    cases = []
    for identifier, state in planned_cases(designs, equilibria, heating_levels):
        result = engine.compute(state, len(cases) + 1)
        if result["color_clipping"]["heatflux_above_max"] or result["color_clipping"]["magnetic_above_max"] or result["color_clipping"]["magnetic_below_min"]:
            raise ValueError(f"Fixed scientific legend excludes {identifier}")
        case_path = f"cases/{identifier}.json"
        atomic_json(output / case_path, {"state": state, "result": result, "data_class": "synthetic_demo",
                    "geometry": state["design"], "source_equilibrium": f"assets/source/eudemo/{state['design']}/equilibria/{state['equilibrium']}.npz"})
        cases.append({"id": identifier, "path": case_path, "fields": result["field_ref"]["path"],
                      "field_ref": result["field_ref"], "peak_temperature_C": result["peak_temperature_C"],
                      "peak_heatflux_MW_m2": result["peak_heatflux_MW_m2"]})
        print(f"[{len(cases):3d}] {identifier}: {result['peak_divertor_heatflux_MW_m2']:.3f} MW/m2", flush=True)
    manifest = {"schema_version": 2, "model_version": MODEL_VERSION, "data_class": "synthetic_demo",
                "generator": "tools/bake_scenarios.py", "axes": {"design": list(designs), "equilibrium": list(equilibria),
                "heating": list(heating_levels), "neon": [False, True]}, "phase": 1.0, "cases": cases}
    atomic_json(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Staging directory, outside live runtime and assets/scenarios")
    parser.add_argument("--design", choices=DESIGNS, action="append")
    parser.add_argument("--equilibrium", choices=EQUILIBRIA, action="append")
    parser.add_argument("--heating", choices=HEATING_LEVELS, type=int, action="append")
    parser.add_argument("--device", help="cpu or cuda:0; default selects the available backend")
    args = parser.parse_args()
    manifest = bake(args.output, designs=args.design or DESIGNS, equilibria=args.equilibrium or EQUILIBRIA,
                    heating_levels=args.heating or HEATING_LEVELS, device=args.device)
    print(json.dumps({"cases": len(manifest["cases"]), "output": str(args.output), "model": MODEL_VERSION}))


if __name__ == "__main__":
    main()
