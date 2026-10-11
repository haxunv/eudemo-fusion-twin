"""Bake immutable design/equilibrium/scenario cases outside live runtime."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from fusion_twin.compute import FieldEngine, SCENARIOS, atomic_json
from fusion_twin.physics import DESIGNS, EQUILIBRIA


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "assets/scenarios")
    parser.add_argument("--design", choices=DESIGNS, action="append")
    parser.add_argument("--equilibrium", choices=EQUILIBRIA, action="append")
    parser.add_argument("--scenario", choices=tuple(SCENARIOS), action="append")
    args = parser.parse_args()
    output = args.output.resolve()
    if output == (ROOT / "runtime").resolve() or (ROOT / "runtime").resolve() in output.parents:
        raise ValueError("Baked scenarios must not target live runtime")
    engine = FieldEngine(ROOT, runtime=output, compress_fields=True)
    cases = []
    for design in args.design or DESIGNS:
        for equilibrium in args.equilibrium or EQUILIBRIA:
            for name in args.scenario or SCENARIOS:
                settings = SCENARIOS[name]
                state = {**{k: v for k, v in settings.items() if k != "hotspot"}, "scenario": name,
                         "phase": 0.65, "design": design, "equilibrium": equilibrium}
                result = engine.compute(state, len(cases) + 1)
                case_path = f"cases/{design}/{equilibrium}/{name}.json"
                atomic_json(output / case_path, {"state": state, "result": result, "data_class": "synthetic_demo",
                            "geometry": design, "source_equilibrium": f"assets/source/eudemo/{design}/equilibria/{equilibrium}.npz"})
                cases.append({"id": f"{design}/{equilibrium}/{name}", "path": case_path,
                              "fields": result["field_ref"]["path"], "field_ref": result["field_ref"],
                              "peak_temperature_C": result["peak_temperature_C"], "peak_heatflux_MW_m2": result["peak_heatflux_MW_m2"]})
    atomic_json(output / "manifest.json", {"schema_version": 2, "generator": "tools/bake_scenarios.py", "cases": cases})
    print(json.dumps(cases, indent=2))


if __name__ == "__main__":
    main()
