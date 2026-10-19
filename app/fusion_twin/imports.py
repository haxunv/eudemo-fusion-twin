"""Public data import: batch scenario cases and external surface fields."""

import csv
import hashlib
import io
import json
import math

import numpy as np
from scipy.spatial import cKDTree

from .compute import (HEATFLUX_LOG_RANGE, HEATFLUX_RANGE, ZERO_COLOR, atomic_replace, colormap,
                      scientific_colors, write_npz)

SCENARIO_KEYS = ("design", "equilibrium", "scenario", "power", "heating", "neon", "flow", "inlet", "phase")
NUMERIC_KEYS = {"power", "heating", "flow", "inlet", "phase"}
SUMMARY_KEYS = ("peak_temperature_C", "peak_heatflux_MW_m2", "peak_divertor_heatflux_MW_m2",
                "outlet_temperature_C", "cooling_margin_C", "relative_no_neon_percent")
SURFACE_MODES = {"heatflux": ("heatflux", "MW/m2"), "temperature": ("temperature", "degC")}
MAX_CASES = 32
MAX_POINTS = 1_000_000
MAX_BODY_BYTES = 64 * 1024 * 1024
SECTOR = 2 * math.pi / 18


def _is_csv(content_type):
    return content_type.split(";")[0].strip().lower() == "text/csv"


def _csv_value(key, text):
    if key == "neon":
        if text.lower() not in ("true", "false", "1", "0"):
            raise ValueError(f"neon must be true or false, got {text!r}")
        return text.lower() in ("true", "1")
    return float(text) if key in NUMERIC_KEYS else text


def parse_cases(body, content_type, query):
    """Return ([(id, partial state)], id to apply or None) from JSON or CSV."""
    if _is_csv(content_type):
        rows = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
        cases = [{key.strip(): _csv_value(key.strip(), value.strip()) for key, value in row.items()
                  if key and value and value.strip()} for row in rows]
        apply = query.get("apply")
    else:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("Body must be a JSON object with a cases array")
        cases, apply = payload.get("cases"), payload.get("apply")
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise ValueError(f"cases must contain 1-{MAX_CASES} entries")
    parsed = []
    for index, case in enumerate(cases, 1):
        if not isinstance(case, dict):
            raise ValueError("Each case must be an object")
        case = dict(case)
        identifier = str(case.pop("id", f"case-{index}"))
        if not 1 <= len(identifier) <= 64 or identifier in dict(parsed):
            raise ValueError(f"Case id must be unique and 1-64 characters: {identifier!r}")
        unknown = sorted(set(case) - set(SCENARIO_KEYS))
        if unknown:
            raise ValueError(f"{identifier}: unsupported keys {unknown}")
        parsed.append((identifier, case))
    if apply is not None and apply not in dict(parsed):
        raise ValueError(f"apply refers to an unknown case id: {apply!r}")
    return parsed, apply


def summarize_case(result):
    return {**{key: result[key] for key in SUMMARY_KEYS}, "power_budget": result["power_budget"],
            "strike_points": {leg: point["status"] for leg, point in result["strike_points"].items()}}


def interpolate(rows, mesh_points, max_distance):
    """Inverse-distance (k=4) interpolation onto mesh vertices; NaN where no sample is near.

    Rows are (R, Z, value) for axisymmetric data or (x, y, z, value) in world metres. The display
    repeats one 20-degree sector, so 3D samples are folded into it, with copies across its seams.
    """
    coords, values = rows[:, :-1], rows[:, -1]
    if coords.shape[1] == 2:
        targets = np.column_stack((np.hypot(mesh_points[:, 0], mesh_points[:, 1]), mesh_points[:, 2]))
    else:
        radius = np.hypot(coords[:, 0], coords[:, 1])
        phi = np.mod(np.arctan2(coords[:, 1], coords[:, 0]), SECTOR)
        coords = np.vstack([np.column_stack((radius * np.cos(phi + shift), radius * np.sin(phi + shift), coords[:, 2]))
                            for shift in (-SECTOR, 0.0, SECTOR)])
        values = np.tile(values, 3)
        targets = mesh_points
    distance, index = cKDTree(coords).query(targets, k=min(4, len(coords)))
    distance, index = distance.reshape(len(targets), -1), index.reshape(len(targets), -1)
    weights = 1 / np.maximum(distance, 1e-9)
    field = (weights * values[index]).sum(axis=1) / weights.sum(axis=1)
    covered = distance[:, 0] <= max_distance
    field[~covered] = np.nan
    return field, float(covered.mean())


def temperature_range(summary):
    if summary["min"] is None:
        return [0, 1000]
    low, high = math.floor(summary["min"] / 50) * 50, math.ceil(summary["max"] / 50) * 50
    return [low, max(high, low + 50)]


class SurfaceImport:
    def __init__(self, quantity, rows, label="imported", max_distance=0.5):
        if quantity not in SURFACE_MODES:
            raise ValueError("quantity must be heatflux or temperature")
        if rows is None:
            raise ValueError("rows is required")
        rows = np.asarray(rows, dtype=float)
        if rows.ndim != 2 or rows.shape[1] not in (3, 4) or not 1 <= len(rows) <= MAX_POINTS:
            raise ValueError(f"rows must be 1-{MAX_POINTS} rows of [R, Z, value] or [x, y, z, value]")
        if not np.isfinite(rows).all():
            raise ValueError("rows must contain only finite numbers")
        max_distance = float(max_distance)
        if not 0 < max_distance <= 5:
            raise ValueError("max_distance must be in (0, 5] metres")
        self.quantity, self.rows, self.max_distance = quantity, rows, max_distance
        self.mode, self.unit = SURFACE_MODES[quantity]
        self.label = str(label)[:64]
        self.id = hashlib.sha256(f"{quantity}:{max_distance}".encode() + rows.tobytes()).hexdigest()[:16]
        self.fields = {}

    @classmethod
    def parse(cls, body, content_type, query):
        if not _is_csv(content_type):
            options = json.loads(body)
            if not isinstance(options, dict):
                raise ValueError("Body must be a JSON object")
            return cls(options.get("quantity"), options.get("rows"), options.get("label", "imported"),
                       options.get("max_distance", 0.5))
        lines = body.decode("utf-8-sig").strip().splitlines()
        try:
            [float(value) for value in lines[0].split(",")]
        except (ValueError, IndexError):
            lines = lines[1:]
        if not lines:
            raise ValueError("CSV contains no data rows")
        rows = np.loadtxt(lines, delimiter=",", ndmin=2)
        return cls(query.get("quantity"), rows, query.get("label", "imported"), query.get("max_distance", 0.5))

    def _field(self, mesh_points, topology_key):
        if topology_key not in self.fields:
            field, coverage = interpolate(self.rows, mesh_points, self.max_distance)
            covered = field[np.isfinite(field)]
            summary = {"label": self.label, "quantity": self.quantity, "unit": self.unit, "mode": self.mode,
                       "points": len(self.rows), "coverage": round(coverage, 4),
                       "min": round(float(covered.min()), 4) if len(covered) else None,
                       "max": round(float(covered.max()), 4) if len(covered) else None}
            self.fields[topology_key] = (field, summary)
        return self.fields[topology_key]

    def apply(self, runtime, result, require_coverage=False):
        """Return a result whose field_ref shows this import; the computed packet stays untouched."""
        reference = result["field_ref"]
        key = hashlib.sha256(f"{reference['key']}:{self.id}".encode()).hexdigest()[:32]
        path = runtime / "fields" / f"{key}.npz"
        with np.load(runtime / reference["path"], allow_pickle=False) as packet:
            arrays = None if _current(path, reference["revision"]) else {name: packet[name] for name in packet.files}
            field, summary = self._field(packet["surface_points"], reference["topology_key"])
        if require_coverage and summary["coverage"] == 0:
            raise ValueError("No analysis-mesh vertex lies within max_distance of the data; "
                             "coordinates must be metres in the machine frame")
        if arrays is not None:
            self._write(path, key, arrays, field, summary)
        ranges = dict(result["color_ranges"])
        if self.quantity == "temperature":
            ranges["temperature"] = temperature_range(summary)
        return {**result, "field_ref": {**reference, "key": key, "path": f"fields/{key}.npz"},
                "source_field_ref": reference, "color_ranges": ranges, "imported_surface": summary}

    def _write(self, path, key, arrays, field, summary):
        if self.quantity == "heatflux":
            arrays["surface_heatflux_MW_m2"] = field
            arrays["heatflux_rgb"] = scientific_colors(field, HEATFLUX_RANGE)
            arrays["heatflux_log_rgb"] = scientific_colors(field, HEATFLUX_LOG_RANGE, logarithmic=True)
        else:
            colors = colormap(field, *temperature_range(summary))
            colors[~np.isfinite(field)] = ZERO_COLOR
            arrays["surface_temperature_C"] = field.astype(np.float32)
            arrays["temperature_rgb"] = colors
        metadata = json.loads(str(arrays["metadata_json"]))
        metadata["imported_surface"] = summary
        arrays.update(field_key=np.asarray(key), metadata_json=np.asarray(json.dumps(metadata, allow_nan=False)))
        temporary = path.with_name(f"{key}.tmp.npz")
        write_npz(temporary, arrays)
        atomic_replace(temporary, path)


def _current(path, revision):
    if not path.is_file():
        return False
    with np.load(path, allow_pickle=False) as packet:
        return int(packet["field_revision"]) == revision
