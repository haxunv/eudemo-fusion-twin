"""Build the OpenUSD scene (metres, Z-up) from the Bluemira EU-DEMO CAD in assets/source."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import struct
import sys
import zlib
from pathlib import Path

import numpy as np
from pxr import Gf, Kind, Sdf, Usd, UsdGeom, UsdLux, UsdShade, Vt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from fusion_twin.geometry import CONTINUOUS_COMPONENTS, merge_meshes, revolve_from_endcap
ASSETS = ROOT / "assets"
SOURCE = ASSETS / "source" / "eudemo"
SCENE = ASSETS / "scene"
VARIANTS = ("conventional", "longleg")
N_SECTORS = 18
CUT_SECTORS = (14, 15, 16, 17)

COMPONENTS = {
    "tf_coils": ("Toroidal field coils", "环向场线圈", "steel", True),
    "pf_coils": ("Poloidal field coils", "极向场线圈", "coil_blue", True),
    "cs_coils": ("Central solenoid", "中央螺线管", "copper", True),
    "coil_structures": ("Magnet support structures", "磁体支撑结构", "structure", True),
    "vacuum_vessel": ("Vacuum vessel and ports", "真空室与维护端口", "vessel", True),
    "blanket": ("Breeding blanket modules", "增殖包层模块", "blanket", True),
    "divertor": ("Divertor cassettes", "偏滤器盒体", "tungsten", True),
    "plasma": ("Plasma boundary", "等离子体边界", "plasma", True),
    "thermal_shield": ("Thermal shields", "热屏蔽", "gold", False),
    "cryostat": ("Cryostat and plugs", "低温恒温器与端口塞", "vessel", False),
    "radiation_shield": ("Biological shield", "辐射屏蔽", "concrete", False),
}

MATERIALS = {
    "steel": ((0.53, 0.60, 0.66), 0.90, 0.25),
    "vessel": ((0.42, 0.49, 0.54), 0.86, 0.32),
    "structure": ((0.23, 0.29, 0.34), 0.82, 0.36),
    "blanket": ((0.47, 0.42, 0.34), 0.78, 0.37),
    "tungsten": ((0.27, 0.31, 0.33), 0.88, 0.28),
    "copper": ((0.68, 0.35, 0.14), 0.84, 0.29),
    "gold": ((0.58, 0.48, 0.26), 0.94, 0.26),
    "coil_blue": ((0.055, 0.16, 0.23), 0.62, 0.29),
    "insulation": ((0.038, 0.051, 0.064), 0.12, 0.52),
    "concrete": ((0.34, 0.35, 0.34), 0.0, 0.86),
    "plasma": ((0.20, 0.32, 0.46), 0.0, 0.5),
    "floor": ((0.19, 0.21, 0.22), 0.08, 0.72),
    "plinth": ((0.055, 0.069, 0.080), 0.72, 0.34),
    "trim": ((0.16, 0.20, 0.23), 0.83, 0.23),
    "green": ((0.24, 0.51, 0.015), 0.20, 0.28),
    "white": ((0.65, 0.71, 0.73), 0.28, 0.30),
    "paint_blue": ((0.055, 0.13, 0.19), 0.22, 0.48),
    "safety_yellow": ((0.72, 0.42, 0.055), 0.12, 0.5),
    "rubber": ((0.026, 0.032, 0.036), 0.0, 0.87),
    "workwear": ((0.10, 0.20, 0.31), 0.0, 0.85),
    "skin": ((0.45, 0.30, 0.21), 0.0, 0.7),
}


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def copy_sources(legacy: Path, provenance_root: Path | None = None) -> None:
    origin = legacy / "source/specializations/fusion/data/eudemo"
    for variant in VARIANTS:
        shutil.copytree(origin / variant, SOURCE / variant, dirs_exist_ok=True)
    provenance = ASSETS / "source/provenance"
    provenance.mkdir(parents=True, exist_ok=True)
    for relative in ("tools/fusion/harvest_eudemo.py", "LICENSE", "README.md"):
        src = legacy / relative
        if src.is_file():
            shutil.copy2(src, provenance / ("legacy_" + src.name))
    if provenance_root is not None:
        for repo in ("bluemira", "eudemo"):
            for name in ("LICENSE", "README.md"):
                src = provenance_root / repo / name
                if src.is_file():
                    shutil.copy2(src, provenance / f"{repo}_{name}")
        config = provenance_root / "eudemo/studies/first/config"
        for name in ("params.json", "build_config.json", "fixed_boundary_eqdsk.json", "process/mockPROCESS.json"):
            src = config / name
            if src.is_file():
                dest = provenance / "generation_config" / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
    files = []
    for path in sorted(SOURCE.rglob("*")):
        if path.is_file():
            files.append({"path": path.relative_to(ASSETS).as_posix(), "bytes": path.stat().st_size,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    write_json(ASSETS / "source/provenance.json", {
        "source_kind": "open_source_concept_design_generated_locally",
        "geometry": "Bluemira EU-DEMO-like parametric CAD; not manufacturing drawings",
        "repositories": [
            {"url": "https://github.com/Fusion-Power-Plant-Framework/bluemira-eudemo",
             "commit": "12d152a2d10bdc5115f371f2a38822b3ecddffb0", "working_tree_modified": True},
            {"url": "https://github.com/Fusion-Power-Plant-Framework/bluemira",
             "commit": "43467e629386f489be6d7651faa9953125138053"}],
        "source_workspace": str(origin),
        "generation": {"script": "source/provenance/legacy_harvest_eudemo.py",
                       "radial_build": "mock PROCESS baseline inputs",
                       "geometry_engine": "Bluemira / FreeCAD",
                       "equilibria": "Bluemira free-boundary numerical solutions; custom ramp and leg constraints",
                       "mesh_deflection_m": 0.02},
        "known_data_issues": [
            "Source machine.json labels P_fus=1994.6 with unit W. The source is preserved; this field must not be used as a validated SI power.",
            "Longleg is a local design variant with div_L2D_ib=1.30 and div_L2D_ob=1.85.",
            "Source provides no physical sensor telemetry, validated time-dependent transport, or AI predictions."],
        "licenses": {"bluemira": "LGPL-2.1-or-later",
                     "eudemo": "Top-level MIT; retain file-level LGPL notices where present",
                     "harvest_script": "LGPL-2.1-or-later, retained source notice"},
        "files": files,
    })


def new_stage(path: Path, root="World") -> Usd.Stage:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(path))
    stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, "/" + root).GetPrim())
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    stage.SetTimeCodesPerSecond(24)
    return stage


def xform(prim, position=None, rotation=None, scale=None):
    xf = UsdGeom.Xformable(prim)
    if position is not None:
        xf.AddTranslateOp().Set(Gf.Vec3d(*map(float, position)))
    if rotation is not None:
        xf.AddRotateZOp().Set(float(rotation))
    if scale is not None:
        xf.AddScaleOp().Set(Gf.Vec3f(*map(float, scale)))


def write_material_assets(scene_dir):
    """Seeded procedural normal maps and the FusionPBR MDL wrapper around Kit's OmniPBR."""
    directory = scene_dir / "materials"
    directory.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(1842)
    for name, strength in (("concrete", .34), ("brushed", .08)):
        height = rng.normal(0, 1, (256, 256))
        if name == "brushed":
            height = np.repeat(height[:, :1], 256, axis=1) + height * .08
        dx, dy = np.gradient(height * strength)
        normals = np.stack((-dx, -dy, np.ones_like(height)), axis=-1)
        normals /= np.linalg.norm(normals, axis=-1, keepdims=True)
        image = np.clip((normals * .5 + .5) * 255, 0, 255).astype(np.uint8)
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
        raw = b"".join(b"\x00" + row.tobytes() for row in image)
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 256, 256, 8, 2, 0, 0, 0))
        (directory / f"{name}_normal.png").write_bytes(png + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    (directory / "FusionPBR.mdl").write_text('''mdl 1.7;
import ::OmniPBR::*;
export material FusionPBR(
    color base_color = color(0.3),
    float metallic = 0.0,
    float roughness = 0.5,
    uniform texture_2d normal_map = texture_2d(),
    uniform float normal_strength = 0.1,
    uniform float repeat_per_meter = 1.0
) = ::OmniPBR::OmniPBR(
    diffuse_color_constant: base_color,
    metallic_constant: metallic,
    reflection_roughness_constant: roughness,
    normalmap_texture: normal_map,
    bump_factor: normal_strength,
    project_uvw: true,
    world_or_object: true,
    texture_scale: float2(repeat_per_meter),
    round_edges_radius: 0.002
);
''', encoding="utf-8")


def material_library(stage, root="/World/Looks", material_assets="./materials"):
    for name, (color, metallic, roughness) in MATERIALS.items():
        mat = UsdShade.Material.Define(stage, f"{root}/{name}")
        shader = UsdShade.Shader.Define(stage, f"{root}/{name}/Surface")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
        shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(metallic)
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
        if name == "green":
            shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.11, 0.38, 0.005))
        elif name == "plasma":
            shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.015, 0.025, 0.045))
            shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(0.065)
            shader.CreateInput("ior", Sdf.ValueTypeNames.Float).Set(1.0)
        shader.CreateOutput("surface", Sdf.ValueTypeNames.Token)
        mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
        if name not in ("plasma", "green"):
            mdl = UsdShade.Shader.Define(stage, f"{root}/{name}/MDL")
            mdl.SetSourceAsset(Sdf.AssetPath(f"{material_assets}/FusionPBR.mdl"), "mdl")
            mdl.SetSourceAssetSubIdentifier("FusionPBR", "mdl")
            mdl.CreateInput("base_color", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
            mdl.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(metallic)
            mdl.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
            concrete = name in ("concrete", "floor")
            mdl.CreateInput("normal_map", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(f"{material_assets}/{'concrete' if concrete else 'brushed'}_normal.png"))
            mdl.CreateInput("normal_strength", Sdf.ValueTypeNames.Float).Set(.20 if concrete else .12)
            mdl.CreateInput("repeat_per_meter", Sdf.ValueTypeNames.Float).Set(1.0 if concrete else 16.)
            mdl.CreateOutput("out", Sdf.ValueTypeNames.Token)
            mat.CreateSurfaceOutput("mdl").ConnectToSource(mdl.ConnectableAPI(), "out")
            mat.GetPrim().SetCustomDataByKey("textureRepeatMeters", 1.0 if concrete else .0625)


def bind(prim, name, root="/World/Looks"):
    material = UsdShade.Material.Get(prim.GetStage(), f"{root}/{name}")
    UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)


def corner_normals(points, triangles, crease_deg=38.0):
    """Preserve CAD hard edges while smoothing tessellated analytic surfaces."""
    faces = points[triangles]
    area_normal = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
    unit = area_normal / np.maximum(np.linalg.norm(area_normal, axis=1, keepdims=True), 1e-15)
    _, welded = np.unique(np.round(points, 6), axis=0, return_inverse=True)
    vertex_ids = welded[triangles].ravel()
    face_ids = np.repeat(np.arange(len(triangles)), 3)
    order = np.argsort(vertex_ids)
    sorted_vertices = vertex_ids[order]
    edges = np.r_[0, np.flatnonzero(np.diff(sorted_vertices)) + 1, len(order)]
    result = np.empty((len(triangles) * 3, 3), dtype=np.float32)
    threshold = math.cos(math.radians(crease_deg))
    for start, end in zip(edges[:-1], edges[1:]):
        corners = order[start:end]
        adjacent = face_ids[corners]
        normals = unit[adjacent]
        weighted = ((normals @ normals.T) >= threshold) @ area_normal[adjacent]
        weighted /= np.maximum(np.linalg.norm(weighted, axis=1, keepdims=True), 1e-15)
        result[corners] = weighted
    return result


def mesh(stage, path, points, triangles, material, material_root="/World/Looks", smooth=True):
    points = np.asarray(points, dtype=np.float32)
    triangles = np.asarray(triangles, dtype=np.int32)
    obj = UsdGeom.Mesh.Define(stage, path)
    obj.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(points))
    obj.CreateFaceVertexCountsAttr(Vt.IntArray.FromNumpy(np.full(len(triangles), 3, dtype=np.int32)))
    obj.CreateFaceVertexIndicesAttr(Vt.IntArray.FromNumpy(triangles.ravel()))
    obj.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
    obj.CreateOrientationAttr(UsdGeom.Tokens.rightHanded)
    obj.CreateExtentAttr(Vt.Vec3fArray.FromNumpy(np.stack((points.min(0), points.max(0)))))
    if smooth:
        obj.CreateNormalsAttr(Vt.Vec3fArray.FromNumpy(corner_normals(points, triangles)))
        obj.SetNormalsInterpolation(UsdGeom.Tokens.faceVarying)
    bind(obj.GetPrim(), material, material_root)
    return obj


def part_material(component, name):
    lower = name.lower()
    if "insulation" in lower:
        return "insulation"
    if "winding" in lower:
        return "copper"
    if component == "blanket":
        if "fw" in lower:
            return "tungsten"
        if "manifold" in lower:
            return "steel"
    return COMPONENTS[component][2]


def component_parts(variant):
    manifest = json.loads((SOURCE / variant / "cad/manifest.json").read_text())
    with np.load(SOURCE / variant / "equilibria/eof.npz", allow_pickle=False) as data:
        coil_centres = np.column_stack((data["coil_x"], data["coil_z"]))
        coil_names, coil_types = data["coil_names"].copy(), data["coil_ctype"].copy()
    result = {key: [] for key in COMPONENTS}
    for source_component, parts in manifest.items():
        for part_id, info in parts.items():
            path = SOURCE / variant / "cad" / f"{source_component}__{part_id}.npz"
            with np.load(path, allow_pickle=False) as data:
                points, triangles = data["points"].copy(), data["tris"].copy()
            component = source_component
            if source_component == "pf_coils":
                radii = np.linalg.norm(points[:, :2], axis=1)
                centre = np.array(((radii.min()+radii.max())/2, (points[:,2].min()+points[:,2].max())/2))
                distances = np.linalg.norm(coil_centres-centre, axis=1)
                coil = int(distances.argmin())
                if distances[coil] > 0.001:
                    raise ValueError(f"CAD part {variant}/{part_id} does not match a source coil")
                component = "cs_coils" if str(coil_types[coil]).endswith("CS") else "pf_coils"
                info = {**info, "coil_name": str(coil_names[coil]), "coil_type": str(coil_types[coil])}
            if component in CONTINUOUS_COMPONENTS:
                points, triangles = merge_meshes(revolve_from_endcap(points, triangles).values())
            result[component].append((part_id, info, points, triangles, path))
    return result


def build_prototypes(variant, parts, scene_dir=SCENE):
    for component, items in parts.items():
        path = scene_dir / "geometry" / variant / f"{component}.usdc"
        stage = new_stage(path, "Component")
        material_library(stage, "/Component/Looks", "../../materials")
        Usd.ModelAPI(stage.GetDefaultPrim()).SetKind(Kind.Tokens.component)
        for part_id, info, points, triangles, source_path in items:
            part_path = f"/Component/{part_id}"
            if component in CONTINUOUS_COMPONENTS:
                prim = UsdGeom.Xform.Define(stage, part_path).GetPrim()
                for role, (p, t) in revolve_from_endcap(points, triangles).items():
                    obj = mesh(stage, f"{part_path}/{role}", p, t,
                               part_material(component, info["name"]), "/Component/Looks")
                    obj.GetPrim().SetCustomDataByKey("geometryRole", role)
                    if role != "body":
                        obj.CreateVisibilityAttr(UsdGeom.Tokens.invisible)
                prim.SetCustomDataByKey("continuousRevolution", True)
            else:
                prim = mesh(stage, part_path, points, triangles,
                            part_material(component, info["name"]), "/Component/Looks").GetPrim()
            prim.SetDisplayName(info["name"])
            metadata = {"sourcePartPath": info["path"], "sourceMaterial": info.get("material") or "unspecified",
                                "sourceFile": source_path.relative_to(ASSETS).as_posix(),
                                "triangleCount": int(len(triangles)), "sourcePartId": part_id}
            if "coil_name" in info:
                metadata.update(sourceCoilName=info["coil_name"], sourceCoilType=info["coil_type"],
                                resolvedPartPath=f"Poloidal Coils/{info['coil_name']}/{info['name']}")
            for key, value in metadata.items():
                prim.SetCustomDataByKey(key, value)
        stage.GetRootLayer().Save()


def component_bounds(items, repeats):
    points = np.concatenate([item[2] for item in items])
    all_bounds = []
    for sector in range(repeats):
        angle = math.radians(360.0 * sector / repeats)
        rotation = np.array([[math.cos(angle), -math.sin(angle), 0], [math.sin(angle), math.cos(angle), 0], [0, 0, 1]])
        rotated = points @ rotation.T
        all_bounds.extend((rotated.min(0), rotated.max(0)))
    all_bounds = np.array(all_bounds)
    return [all_bounds.min(0).tolist(), all_bounds.max(0).tolist()]


def machine(stage, all_parts):
    root = UsdGeom.Xform.Define(stage, "/World/Machine").GetPrim()
    Usd.ModelAPI(root).SetKind(Kind.Tokens.assembly)
    variants = root.GetVariantSets().AddVariantSet("design")
    for variant in VARIANTS:
        variants.AddVariant(variant)
        variants.SetVariantSelection(variant)
        with variants.GetVariantEditContext():
            for component, (en, zh, material, visible) in COMPONENTS.items():
                group = UsdGeom.Xform.Define(stage, f"/World/Machine/{component}")
                group.GetPrim().SetDisplayName(en)
                group.GetPrim().SetCustomData({"componentId": component, "nameZh": zh, "source": "Bluemira EU-DEMO-like"})
                if not visible:
                    group.CreateVisibilityAttr(UsdGeom.Tokens.invisible)
                repeats = N_SECTORS
                for sector in range(repeats):
                    part = stage.DefinePrim(f"/World/Machine/{component}/sector_{sector:02d}", "Xform")
                    part.GetReferences().AddReference(f"./geometry/{variant}/{component}.usdc")
                    xform(part, rotation=360 * sector / repeats)
                    is_cut = sector in CUT_SECTORS
                    part.SetCustomDataByKey("sectionHidden", is_cut)
                    part.SetCustomDataByKey("sectorIndex", sector)
                    if is_cut:
                        UsdGeom.Imageable(part).CreateVisibilityAttr(UsdGeom.Tokens.invisible)
                    if component in CONTINUOUS_COMPONENTS:
                        for part_id, *_ in all_parts[variant][component]:
                            for role, shown in (("cap_start", sector == 0),
                                                ("cap_end", sector == min(CUT_SECTORS)-1)):
                                cap = stage.OverridePrim(f"{part.GetPath()}/{part_id}/{role}")
                                UsdGeom.Imageable(cap).CreateVisibilityAttr("inherited" if shown else "invisible")
    variants.SetVariantSelection("conventional")


def cube(stage, path, position, size, material, angle=0):
    obj = UsdGeom.Cube.Define(stage, path)
    obj.CreateSizeAttr(1)
    xform(obj.GetPrim(), position=position, rotation=angle, scale=size)
    bind(obj.GetPrim(), material)


def ring(stage, path, inner, outer, z, thickness, material, n=180, start=0., sweep=360.):
    vertices = []
    closed = abs(sweep - 360.) < 1e-6
    count = n if closed else n + 1
    for height in (z, z - thickness):
        for radius in (inner, outer):
            vertices.extend((radius * math.cos(math.radians(start + sweep*i/n)),
                             radius * math.sin(math.radians(start + sweep*i/n)), height) for i in range(count))
    triangles = []
    for i in range(n):
        j = (i + 1) % count
        for a, b, c, d in ((i, count+i, count+j, j), (2*count+j, 3*count+j, 3*count+i, 2*count+i),
                           (count+i, 3*count+i, 3*count+j, count+j), (i, j, 2*count+j, 2*count+i)):
            triangles.extend(((a, b, c), (a, c, d)))
    if not closed:
        for i, reverse in ((0, True), (n, False)):
            face = (i, i+count, i+3*count, i+2*count)
            if reverse:
                face = face[::-1]
            triangles.extend(((face[0], face[1], face[2]), (face[0], face[2], face[3])))
    mesh(stage, path, vertices, triangles, material)


def bars(stage, path, items, material):
    points, triangles = [], []
    corners = np.array([[-1,-1,-1], [1,-1,-1], [1,1,-1], [-1,1,-1],
                        [-1,-1,1], [1,-1,1], [1,1,1], [-1,1,1]], dtype=float) / 2
    faces = np.array([[0,2,1],[0,3,2],[4,5,6],[4,6,7],[0,1,5],[0,5,4],
                      [1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]])
    for centre, size, angle in items:
        a = math.radians(angle)
        rotation = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0,0,1]])
        triangles.extend(faces + len(points))
        points.extend((corners * size) @ rotation.T + centre)
    if points:
        return mesh(stage, path, points, triangles, material, smooth=False)


def rod(stage, path, start, end, radius, material):
    delta = Gf.Vec3d(*end) - Gf.Vec3d(*start)
    obj = UsdGeom.Cylinder.Define(stage, path)
    obj.CreateRadiusAttr(radius)
    obj.CreateHeightAttr(delta.GetLength())
    obj.CreateAxisAttr("Z")
    obj.AddTranslateOp().Set((Gf.Vec3d(*start) + Gf.Vec3d(*end)) / 2)
    rotation = Gf.Rotation(Gf.Vec3d(0, 0, 1), delta.GetNormalized()).GetQuat()
    obj.AddOrientOp().Set(Gf.Quatf(rotation))
    bind(obj.GetPrim(), material)


def worker(stage, path, position, angle=0):
    person = UsdGeom.Xform.Define(stage, path)
    xform(person.GetPrim(), position=position, rotation=angle)
    person.GetPrim().SetCustomDataByKey("referenceHeightMeters", 1.8)
    cube(stage, path + "/Torso", (0, 0, 1.16), (.43, .23, .57), "workwear")
    cube(stage, path + "/Vest", (0, -.13, 1.25), (.44, .025, .36), "safety_yellow")
    for side in (-1, 1):
        rod(stage, path + f"/Leg_{'L' if side<0 else 'R'}", (side*.11, 0, .13), (side*.11, 0, .9), .085, "workwear")
        cube(stage, path + f"/Boot_{'L' if side<0 else 'R'}", (side*.11, -.035, .07), (.18, .29, .14), "rubber")
        rod(stage, path + f"/Arm_{'L' if side<0 else 'R'}", (side*.29, 0, 1.39), (side*.31, -.03, .90), .065, "workwear")
    for name, z, scale, material in (("Head", 1.61, (.13, .12, .15), "skin"),
                                      ("Helmet", 1.735, (.155, .15, .065), "safety_yellow")):
        obj = UsdGeom.Sphere.Define(stage, path + "/" + name)
        obj.CreateRadiusAttr(1)
        xform(obj.GetPrim(), position=(0, 0, z), scale=scale)
        bind(obj.GetPrim(), material)


def environment(stage):
    root = "/World/Environment"
    facility = UsdGeom.Xform.Define(stage, root).GetPrim()
    facility.SetCustomDataByKey("visualizationOnly", True)
    facility.SetCustomDataByKey("description", "Conceptual tokamak hall; illustrative civil works outside source CAD BOM")
    cube(stage, root + "/Floor", (0, 0, -16.4), (108, 108, .6), "floor")
    ring(stage, root + "/Pit/RetainingWall", 22.0, 23.4, -14.8, 1.3, "concrete")
    ring(stage, root + "/Pit/InnerLiner", 21.92, 22.0, -15.0, 1.0, "steel")
    cube(stage, root + "/Hall/BackWall", (0, 35.0, 4), (72, 1.5, 40), "concrete")
    for side in (-1, 1):
        centre_y, length = (3.5, 63.) if side < 0 else (15., 40.)
        cube(stage, root + f"/Hall/SideWall_{side+1}", (side*35, centre_y, 4), (1.5, length, 40), "concrete")
    joints, back_columns, side_columns, crane_rails = [], [], {-1: [], 1: []}, []
    for x in np.arange(-32, 33, 8):
        back_columns.append(((x, 33.9, 4), (.72, 1.0, 40), 0))
        joints.append(((x, 34.22, 4), (.025, .03, 40), 0))
    for z in np.arange(-12, 24, 4):
        joints.append(((0, 34.22, z), (70, .03, .025), 0))
    for side in (-1, 1):
        for y in ((-27, -19, -11, -3, 5, 13, 21, 29) if side < 0 else (-3, 5, 13, 21, 29)):
            side_columns[side].append(((side*33.8, y, 4), (1.0, .72, 40), 0))
        crane_rails.append(((side*32.5, 13.5, 21.5), (.75, 43, 1.3), 0))
        crane_rails.append(((side*32.5, 13.5, 22.22), (.12, 43, .14), 0))
    bars(stage, root + "/Hall/BackColumns", back_columns, "paint_blue")
    bars(stage, root + "/Hall/LeftColumns", side_columns[-1], "paint_blue")
    bars(stage, root + "/Hall/RightColumns", side_columns[1], "paint_blue")
    bars(stage, root + "/Hall/ConcretePanelJoints", joints, "structure")
    # Walls the renderer may hide when they block the camera; never applied to the CAD assembly.
    for name, axis, plane, tangent_range, sign, linked in (
        ("BackWall", 1, 35., (-36., 36.), 1, ("BackColumns", "ConcretePanelJoints")),
        ("SideWall_0", 0, -35., (-28., 35.), -1, ("LeftColumns",)),
        ("SideWall_2", 0, 35., (-5., 35.), 1, ("RightColumns",)),
    ):
        stage.GetPrimAtPath(root + "/Hall/" + name).SetCustomDataByKey("cameraCutaway", {
            "axis": axis, "plane": plane, "tangentMin": tangent_range[0], "tangentMax": tangent_range[1],
            "zMin": -16., "zMax": 24., "outsideSign": sign,
            "linkedPrims": Vt.StringArray([root + "/Hall/" + part for part in linked]),
        })
    bars(stage, root + "/Crane/RunwayRails", crane_rails, "steel")
    for y in (9.5, 12.5):
        cube(stage, root + f"/Crane/Bridge_{int(y)}", (0, y, 23.5), (65, .85, 1.6), "safety_yellow")
    cube(stage, root + "/Crane/Trolley", (-21, 11, 24.3), (4, 4.2, .7), "structure")
    cube(stage, root + "/Crane/Hoist", (-21, 11, 22), (1.2, 1.0, 1.0), "safety_yellow")
    for dx in (-.35, .35):
        rod(stage, root + f"/Crane/Cable_{'L' if dx<0 else 'R'}", (-21+dx, 11, 21.5), (-21+dx, 11, 9), .035, "steel")
    cube(stage, root + "/Crane/HookBlock", (-21, 11, 8.6), (1.0, .7, .8), "safety_yellow")
    rod(stage, root + "/Crane/Hook", (-21, 11, 8.2), (-20.8, 11, 7.7), .12, "steel")

    ring(stage, root + "/Platform/InnerGirder", 22.8, 23.05, -8.0, .6, "structure", 120, 10, 225)
    ring(stage, root + "/Platform/OuterGirder", 25.2, 25.45, -8.0, .6, "structure", 120, 10, 225)
    grating, posts = [], []
    for angle in np.arange(10, 235, .36):
        a = math.radians(angle)
        grating.append(((24.1*math.cos(a), 24.1*math.sin(a), -7.98), (2.6, .025, .05), angle))
    for radius in np.arange(23.0, 25.31, .38):
        ring(stage, root + f"/Platform/CrossBar_{int(radius*100)}", radius, radius+.015, -7.98, .04, "steel", 120, 10, 225)
    for angle in np.arange(10, 236, 5):
        a = math.radians(angle)
        posts.append(((25.35*math.cos(a), 25.35*math.sin(a), -7.43), (.055,.055,1.1), angle))
    for level in (-7.45, -6.9):
        ring(stage, root + f"/Platform/Rail_{int(abs(level)*100)}", 25.32, 25.37, level, .05, "safety_yellow", 120, 10, 225)
    bars(stage, root + "/Platform/Grating", grating, "steel")
    bars(stage, root + "/Platform/RailPosts", posts, "safety_yellow")
    supports = []
    for angle in range(15, 236, 20):
        a = math.radians(angle)
        supports.append(((24.0*math.cos(a), 24.0*math.sin(a), -12.1), (.3,.3,7.9), angle))
    bars(stage, root + "/Platform/Columns", supports, "structure")
    stairs = []
    for step in range(36):
        stairs.append(((-27.6, -8.8+step*.29, -15.97+step*.225), (2.0,.31,.08), 0))
    bars(stage, root + "/Maintenance/Stairs", stairs, "steel")
    for x in (-28.6, -26.6):
        rod(stage, root + f"/Maintenance/StairRail_{int(abs(x)*10)}", (x,-8.8,-14.9), (x,1.35,-7.0), .035, "safety_yellow")
    for i in range(4):
        cube(stage, root + f"/Maintenance/Cabinet_{i}", (28.8, 5+i*1.6, -14.7), (.85,1.3,2.8), "paint_blue")
        cube(stage, root + f"/Maintenance/CabinetPanel_{i}", (28.35,5+i*1.6,-14.4), (.04,.95,1.6), "white")
    cube(stage, root + "/Maintenance/Transporter", (-26,-12,-15.3), (3.6,5.5,1.1), "safety_yellow")
    for x in (-27.7, -24.3):
        for y in (-13.8,-10.2):
            rod(stage, root + f"/Maintenance/Wheel_{int(abs(x)*10)}_{int(abs(y)*10)}", (x-.18,y,-15.7),(x+.18,y,-15.7),.42,"rubber")
    cube(stage, root + "/Maintenance/ToolingCradle", (-26,-12,-14.4), (2.8,3.8,.7), "steel")
    for i in range(18):
        angle = math.radians(20 * i + 10)
        cube(stage, root + f"/Pit/SupportShoe_{i:02d}", (16.6*math.cos(angle),16.6*math.sin(angle),-15.45),
             (2.5,1.2,1.3), "concrete", math.degrees(angle))
    markings = [((x,0,-16.093),(.018,92,.008),0) for x in range(-45,46,5)]
    markings += [((0,y,-16.093),(92,.018,.008),0) for y in range(-45,46,5)]
    bars(stage, root + "/Hall/FloorExpansionJoints", markings, "structure")
    for i, (position, angle) in enumerate((((21,-17,-16.1),-25),((22,-15.5,-16.1),20),((-23,-15,-16.1),-20),((24,7,-7.95),130))):
        worker(stage, root + f"/ScaleReferences/Engineer_{i}", position, angle)


def aim(prim, eye, target, up=(0, 0, 1)):
    matrix = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(*up)).GetInverse()
    UsdGeom.Xformable(prim).AddTransformOp().Set(matrix)


def lighting(stage):
    UsdGeom.Xform.Define(stage, "/World/Lighting")
    dome = UsdLux.DomeLight.Define(stage, "/World/Lighting/StudioFill")
    dome.CreateIntensityAttr(290)
    dome.CreateColorAttr(Gf.Vec3f(0.85, 0.89, 0.95))
    for name, eye, size, intensity, color in (
        ("Key", (18, -26, 28), (20, 14), 2900, (1.0, 0.95, 0.87)),
        ("Left", (-27, -13, 14), (12, 24), 1900, (0.79, 0.87, 1.0)),
        ("Back", (4, 25, 22), (18, 11), 2400, (0.85, 0.92, 1.0)),
        ("Section", (27, -24, 3), (12, 18), 1400, (1.0, 0.96, 0.9)),
        ("PitFill", (10, -26, -5), (14, 6), 280, (0.94, 0.96, 1.0)),
    ):
        light = UsdLux.RectLight.Define(stage, "/World/Lighting/" + name)
        light.CreateWidthAttr(size[0])
        light.CreateHeightAttr(size[1])
        light.CreateIntensityAttr(intensity)
        light.CreateColorAttr(Gf.Vec3f(*color))
        aim(light.GetPrim(), eye, (0, 0, -13) if name == "PitFill" else (0, 0, 0))
    for side in (-1, 1):
        light = UsdLux.RectLight.Define(stage, f"/World/Lighting/Hall_{side+1}")
        light.CreateWidthAttr(4)
        light.CreateHeightAttr(22)
        light.CreateIntensityAttr(1100)
        light.CreateColorAttr(Gf.Vec3f(1.0, .96, .89))
        aim(light.GetPrim(), (side*27, 14, 23.5), (side*24, 10, -15))
        cube(stage, f"/World/Environment/Hall/Luminaire_{side+1}", (side*27,14,23.8), (4,22,.12), "white")


def cameras(stage):
    UsdGeom.Xform.Define(stage, "/World/Cameras")
    views = {
        "overview": ((62.64, -69.12, 17), (0, 0, 0), 36, (0, 0, 1)),
        "front": ((55, -58, -.5), (0, 0, -1.5), 43, (0, 0, 1)),
        "top": ((0, 0, 86), (0, 0, -1), 40, (0, 1, 0)),
        "section": ((32, -36, 4), (2, -1, -1.8), 40, (0, 0, 1)),
        "divertor": ((18, -24, -4), (7, -4.5, -8.1), 45, (0, 0, 1)),
    }
    result = {}
    for name, (eye, target, focal, up) in views.items():
        path = f"/World/Cameras/{name}"
        camera = UsdGeom.Camera.Define(stage, path)
        camera.CreateHorizontalApertureAttr(36.0)
        camera.CreateVerticalApertureAttr(20.25)
        camera.CreateHorizontalApertureOffsetAttr(2.8 if name == "overview" else 0.)
        camera.CreateFocalLengthAttr(focal)
        camera.CreateFStopAttr(0.0)
        camera.CreateClippingRangeAttr(Gf.Vec2f(0.05, 2000))
        camera.CreateFocusDistanceAttr(float(np.linalg.norm(np.subtract(eye, target))))
        aim(camera.GetPrim(), eye, target, up)
        result[name] = {"usd_path": path, "eye_m": list(eye), "target_m": list(target),
                        "focal_length_mm": focal, "f_stop": 0.0}
    return result


def build(legacy: Path | None = None, copy=True, output_assets: Path | None = None,
          provenance_root: Path | None = None):
    output_assets = Path(output_assets) if output_assets is not None else ASSETS
    scene_dir = output_assets / "scene"
    if copy and legacy is not None:
        copy_sources(legacy, provenance_root=provenance_root)
    write_material_assets(scene_dir)
    all_parts = {variant: component_parts(variant) for variant in VARIANTS}
    for variant, parts in all_parts.items():
        build_prototypes(variant, parts, scene_dir)
    stage = new_stage(scene_dir / "fusion.usda")
    stage.GetRootLayer().documentation = "EU-DEMO-like conceptual CAD assembly. Original B-rep retained in assets/source. Render units: metres."
    stage.GetRootLayer().customLayerData = {"defaultCamera": "/World/Cameras/overview", "dataStatus": "conceptual_design_and_simulation", "copyright": "See source/provenance.json"}
    material_library(stage)
    machine(stage, all_parts)
    environment(stage)
    lighting(stage)
    camera_data = cameras(stage)
    stage.GetRootLayer().Save()
    design_components = {}
    for variant, parts in all_parts.items():
        components = []
        for component, (en, zh, material, visible) in COMPONENTS.items():
            items = parts[component]
            repeats = N_SECTORS
            source_component = "pf_coils" if component == "cs_coils" else component
            components.append({
            "id": component, "name_en": en, "name_zh": zh,
            "usd_path": f"/World/Machine/{component}", "material": material,
            "source": "Bluemira EU-DEMO-like CAD generated locally",
            "bounds_m": component_bounds(items, repeats),
            "part_count": len(items) * repeats,
            "triangle_count": sum(len(item[3]) for item in items) * repeats,
            "unique_part_count": len(items), "sector_count": repeats,
            "sector_angle_deg": 360 / repeats, "default_visible": visible,
            "source_step": f"source/eudemo/{variant}/cad/{source_component}.stp",
            "mesh_count": len(items) * repeats * (3 if component in CONTINUOUS_COMPONENTS else 1),
            "continuous_revolution": component in CONTINUOUS_COMPONENTS,
            })
        design_components[variant] = components
    components = design_components["conventional"]
    provenance = json.loads((ASSETS / "source/provenance.json").read_text(encoding="utf-8"))
    manifest = {
        "schema_version": 2, "title": "EU-DEMO Fusion Digital Twin",
        "stage": "scene/fusion.usda", "unit": "m", "up_axis": "Z",
        "components": components,
        "design_components": design_components,
        "total_part_count": sum(c["part_count"] for c in components),
        "total_triangle_count": sum(c["triangle_count"] for c in components),
        "total_mesh_count": sum(c["mesh_count"] for c in components),
        "unique_part_count": sum(c["unique_part_count"] for c in components),
        "source": provenance["repositories"],
        "cameras": camera_data,
        "default_camera": "/World/Cameras/overview",
        "design_variants": list(VARIANTS), "design_variant_set": "design",
        "environment": {"kind": "illustrative_tokamak_hall", "usd_path": "/World/Environment",
                        "hall_width_m": 72., "wall_height_m": 40., "person_height_m": 1.8,
                        "railing_height_m": 1.1, "included_in_cad_bom": False},
        "cutaway": {"start_deg": 280, "end_deg": 360, "sector_indices": list(CUT_SECTORS),
                    "description": "80 degree opening follows four exact 20 degree CAD sectors."},
        "geometry_notes": ["Full named component hierarchy from source CAD; no reactor components replaced by display primitives.",
                           "PF/CS and plasma are revolved from source RZ end-cap sections; artificial radial caps are separately controlled.",
                           "PF/CS classification uses source equilibrium coil names/types, verified against CAD section centres.",
                           "Tokamak hall, civil shielding pit, crane, maintenance platforms and 1.8m personnel are illustrative environment geometry, outside the CAD BOM.",
                           "Manufacturing tolerances, watertight B-rep quality and collision clearance have not been certified."],
    }
    write_json(output_assets / "manifest.json", manifest)
    print(json.dumps({"stage": str(scene_dir / "fusion.usda"), "parts": manifest["total_part_count"],
                      "triangles": manifest["total_triangle_count"], "source_files": len(provenance["files"])}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-project", type=Path,
                        help="Explicitly import source CAD from another project; otherwise use shipped assets/source")
    parser.add_argument("--skip-copy", action="store_true",
                        help="Use shipped source assets even when --source-project is supplied (compatibility option)")
    parser.add_argument("--provenance-root", type=Path,
                        help="Optional directory containing bluemira/ and eudemo/ repositories for imported provenance")
    parser.add_argument("--output-assets", type=Path, help="Build into an isolated assets directory")
    args = parser.parse_args()
    if args.provenance_root is not None and (args.source_project is None or args.skip_copy):
        parser.error("--provenance-root requires --source-project without --skip-copy")
    build(args.source_project, copy=not args.skip_copy, output_assets=args.output_assets,
          provenance_root=args.provenance_root)
