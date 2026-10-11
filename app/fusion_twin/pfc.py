"""Analysis skins reconstructed from the CAD-generating poloidal profiles.

Only the first wall and divertor cavity boundary are revolved. Solid backs,
breeding-zone/manifold interfaces and toroidal end caps are not analysis faces.
The result is an axisymmetric analysis approximation of the segmented CAD.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import numpy as np


def arc_lengths(poly):
    return np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(poly, axis=0), axis=1))]


def sample_polyline(poly, spacing):
    arc = arc_lengths(poly)
    samples = np.unique(np.r_[arc, np.arange(0, arc[-1], spacing)])
    samples = samples[np.r_[True, np.diff(samples) > 1e-8]]
    return np.column_stack([np.interp(samples, arc, poly[:, k]) for k in (0, 1)]), samples


def project_to_polyline(points, poly):
    """Closest R,Z projection, returning distance and poloidal arclength."""
    edge = np.diff(poly, axis=0)
    length = np.linalg.norm(edge, axis=1)
    delta = np.asarray(points)[:, None, :] - poly[None, :-1, :]
    fraction = np.clip(np.sum(delta * edge, axis=2) / np.maximum(length**2, 1e-30), 0, 1)
    distance = np.linalg.norm(delta - fraction[:, :, None] * edge, axis=2)
    index = distance.argmin(axis=1)
    row = np.arange(len(points))
    return distance[row, index], arc_lengths(poly)[index] + fraction[row, index] * length[index]


def trim_polyline(poly, start, end):
    arc = arc_lengths(poly)
    s = np.r_[start, arc[(arc > start) & (arc < end)], end]
    return np.column_stack([np.interp(s, arc, poly[:, k]) for k in (0, 1)])


def clip_radial(poly, low, high):
    """Clip a continuous first-wall profile to a source part's radial bounds."""
    output = []
    for a, b in zip(poly[:-1], poly[1:]):
        cuts = [0.0, 1.0]
        if abs(b[0] - a[0]) > 1e-12:
            cuts += [(bound - a[0]) / (b[0] - a[0]) for bound in (low, high)
                     if 0 < (bound - a[0]) / (b[0] - a[0]) < 1]
        cuts = sorted(cuts)
        for u, v in zip(cuts[:-1], cuts[1:]):
            if low - 1e-8 <= (a + (u + v) * 0.5 * (b - a))[0] <= high + 1e-8:
                for t in (u, v):
                    point = a + t * (b - a)
                    if not output or np.linalg.norm(point - output[-1]) > 1e-8:
                        output.append(point)
    return np.asarray(output)


@dataclass
class PFCMesh:
    points: np.ndarray
    faces: np.ndarray
    regions: np.ndarray
    normals: np.ndarray
    vertex_area: np.ndarray
    part_ids: np.ndarray
    poloidal_s: np.ndarray
    divertor_profile: np.ndarray
    topology_key: str
    provenance: dict


def build_pfc(source: Path, spacing_scale=1.0):
    machine = json.loads((source / "machine.json").read_text(encoding="utf-8"))
    manifest = json.loads((source / "cad/manifest.json").read_text(encoding="utf-8"))
    # These panel vertices generate the actual planar FW panels; the smooth
    # fw_inner_boundary is the design envelope, not the final panel face.
    wall = np.asarray(machine["blanket_panel_points"], dtype=float)[[0, 2]].T
    divertor = np.asarray(machine["div_internal_boundary"], dtype=float)[[0, 2]].T
    _, junction = project_to_polyline(wall[[0, -1]], divertor)
    divertor = trim_polyline(divertor, float(junction.min()), float(junction.max()))
    points, faces, regions, normals, part_ids, poloidal_s = [], [], [], [], [], []
    offset = 0
    source_parts = []
    for component in ("blanket", "divertor"):
        for part_id, info in manifest[component].items():
            if component == "blanket" and info["material"] != "FW_material":
                continue
            with np.load(source / "cad" / f"{component}__{part_id}.npz", allow_pickle=False) as data:
                cad = data["points"].astype(float)
            radius = np.linalg.norm(cad[:, :2], axis=1)
            angles = np.arctan2(cad[:, 1], cad[:, 0])
            profile = (clip_radial(wall, radius.min(), radius.max())
                       if component == "blanket" else divertor)
            profile, s = sample_polyline(profile, (0.10 if component == "blanket" else 0.005) * spacing_scale)
            count = max(2, int(np.ceil(np.ptp(angles) / np.radians(1.5 * spacing_scale))))
            phi = np.linspace(angles.min(), angles.max(), count + 1)
            r, z = profile.T
            xyz = np.stack([r[:, None] * np.cos(phi), r[:, None] * np.sin(phi),
                            np.broadcast_to(z[:, None], (len(r), len(phi)))], axis=-1)
            edges = np.diff(profile, axis=0)
            edges /= np.linalg.norm(edges, axis=1)[:, None]
            tangent = np.vstack([edges[0], edges[:-1] + edges[1:], edges[-1]])
            # FW runs up the inner wall and down the outer wall; divertor runs
            # inner-to-outer underneath the plasma. Both normals face the cavity.
            normal_rz = np.column_stack((tangent[:, 1], -tangent[:, 0]))
            if component == "divertor":
                normal_rz *= -1
            normal_rz /= np.linalg.norm(normal_rz, axis=1)[:, None]
            n = np.stack([normal_rz[:, :1] * np.cos(phi), normal_rz[:, :1] * np.sin(phi),
                          np.broadcast_to(normal_rz[:, 1:], (len(r), len(phi)))], axis=-1)
            i, j = np.meshgrid(np.arange(len(r) - 1), np.arange(len(phi) - 1), indexing="ij")
            a = (i * len(phi) + j).ravel() + offset
            b, c, d = a + 1, a + len(phi), a + len(phi) + 1
            triangles = np.stack([np.column_stack((a, c, d)), np.column_stack((a, d, b))], axis=1).reshape(-1, 3)
            if component == "blanket":
                triangles = triangles[:, ::-1]
            size = xyz.size // 3
            points.append(xyz.reshape(-1, 3))
            normals.append(n.reshape(-1, 3))
            faces.append(triangles)
            regions.append(np.full(size, int(component == "divertor"), dtype=np.int32))
            part_ids.append(np.full(size, f"{component}/{part_id}", dtype="U24"))
            poloidal_s.append(np.repeat(s, len(phi)))
            source_parts.append({"id": f"{component}/{part_id}", "name": info["name"],
                                 "profile": "blanket_panel_points" if component == "blanket" else "div_internal_boundary",
                                 "angular_bounds_deg": np.degrees([angles.min(), angles.max()]).tolist()})
            offset += size
    points, faces = np.vstack(points), np.vstack(faces).astype(np.int32)
    triangle = points[faces]
    area = np.linalg.norm(np.cross(triangle[:, 1] - triangle[:, 0], triangle[:, 2] - triangle[:, 0]), axis=1) * 0.5
    weights = np.zeros(len(points))
    for k in range(3):
        np.add.at(weights, faces[:, k], area / 3)
    digest = hashlib.sha256(points.tobytes() + faces.tobytes()).hexdigest()[:20]
    provenance = {"method": "CAD-generating poloidal profiles revolved over source FW/cassette angular bounds",
                  "parts": source_parts, "sector_count": 18, "base_sector_degrees": 20,
                  "full_machine_area_m2": float(weights.sum() * 18),
                  "excluded": ["BZ", "MANIFOLD", "solid backs", "material interfaces", "toroidal end caps"],
                  "limitation": "Axisymmetric analysis skin; no toroidal bevel, gap-edge heating or 3D shadow model"}
    return PFCMesh(points, faces, np.concatenate(regions), np.vstack(normals), weights,
                   np.concatenate(part_ids), np.concatenate(poloidal_s), divertor,
                   f"{source.name}:pfc-v2:{digest}", provenance)
