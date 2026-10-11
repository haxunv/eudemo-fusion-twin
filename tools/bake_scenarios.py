"""Bake four reproducible demo cases without touching the live renderer state."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from fusion_twin.compute import FieldEngine, SCENARIOS, atomic_json


def main():
    engine = FieldEngine(ROOT)
    cases = []
    for index, (name, settings) in enumerate(SCENARIOS.items(), 1):
        engine.runtime = ROOT / "assets/scenarios" / name
        engine.runtime.mkdir(parents=True, exist_ok=True)
        state = {**{k: v for k, v in settings.items() if k != "hotspot"}, "scenario": name, "phase": 0.65}
        result = engine.compute(state, index)
        atomic_json(engine.runtime / "case.json", {"state": state, "result": result, "data_class": "synthetic_demo", "geometry": "conventional", "source_equilibrium": "assets/source/eudemo/conventional/equilibria/reference.npz"})
        cases.append({"id": name, "path": f"{name}/case.json", "fields": f"{name}/fields.npz", "peak_temperature_C": result["peak_temperature_C"], "peak_heatflux_MW_m2": result["peak_heatflux_MW_m2"]})
    atomic_json(ROOT / "assets/scenarios/manifest.json", {"schema_version": 1, "generator": "tools/bake_scenarios.py", "cases": cases})
    print(json.dumps(cases, indent=2))


if __name__ == "__main__":
    main()
