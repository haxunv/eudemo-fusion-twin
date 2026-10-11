"""Build an inspectable OpenUSD assembly from harvested Bluemira EU-DEMO CAD.

The source CAD is retained unchanged. Render geometry is assembled in metres,
Z-up; continuous PF/CS and plasma surfaces are revolved from their source RZ
sections. Original CAD assets remain unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
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

# Color choices aid component inspection; CAD source material names remain metadata.
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
    "concrete": ((0.24, 0.26, 0.28), 0.02, 0.78),
    "plasma": ((0.13, 0.56, 0.73), 0.10, 0.25),
    "floor": ((0.025, 0.031, 0.041), 0.26, 0.48),
    "plinth": ((0.055, 0.069, 0.080), 0.72, 0.34),
    "trim": ((0.16, 0.20, 0.23), 0.83, 0.23),
    "green": ((0.24, 0.51, 0.015), 0.20, 0.28),
    "white": ((0.65, 0.71, 0.73), 0.28, 0.30),
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


def material_library(stage, root="/World/Looks"):
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
            shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.075, 0.23, 0.33))
            shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(0.22)
            shader.CreateInput("ior", Sdf.ValueTypeNames.Float).Set(1.0)
        shader.CreateOutput("surface", Sdf.ValueTypeNames.Token)
        mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")


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
        material_library(stage, "/Component/Looks")
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


def ring(stage, path, inner, outer, z, thickness, material, n=180):
    vertices = []
    for height in (z, z - thickness):
        for radius in (inner, outer):
            vertices.extend((radius * math.cos(i * math.tau / n), radius * math.sin(i * math.tau / n), height) for i in range(n))
    triangles = []
    for i in range(n):
        j = (i + 1) % n
        for a, b, c, d in ((i, n+i, n+j, j), (2*n+j, 3*n+j, 3*n+i, 2*n+i),
                           (n+i, 3*n+i, 3*n+j, n+j), (i, j, 2*n+j, 2*n+i)):
            triangles.extend(((a, b, c), (a, c, d)))
    mesh(stage, path, vertices, triangles, material)


def environment(stage):
    UsdGeom.Xform.Define(stage, "/World/Environment")
    # Exhibition support is clearly separate from reactor CAD and its engineering BOM.
    cube(stage, "/World/Environment/Floor", (0, 0, -16.4), (180, 180, 0.6), "floor")
    plinth = UsdGeom.Cylinder.Define(stage, "/World/Environment/Plinth")
    plinth.CreateRadiusAttr(22.2)
    plinth.CreateHeightAttr(0.8)
    plinth.CreateAxisAttr("Z")
    xform(plinth.GetPrim(), position=(0, 0, -15.65))
    bind(plinth.GetPrim(), "plinth")
    ring(stage, "/World/Environment/PlinthRim", 21.85, 22.3, -15.19, 0.15, "trim")
    ring(stage, "/World/Environment/GreenTrace", 22.26, 22.31, -15.40, 0.04, "green")
    ring(stage, "/World/Environment/ServiceWalk", 19.3, 21.6, -14.95, 0.12, "structure")
    for i in range(36):
        angle = 10 * i
        a = math.radians(angle)
        cube(stage, f"/World/Environment/RadialMark_{i:02d}", (21.9*math.cos(a), 21.9*math.sin(a), -15.10),
             (0.23 if i % 3 else 0.48, 0.035, 0.013), "white", angle)
    for i in range(18):
        angle = math.radians(20 * i + 10)
        cube(stage, f"/World/Environment/SupportShoe_{i:02d}", (16.6*math.cos(angle), 16.6*math.sin(angle), -15.10),
             (2.5, 1.2, 0.3), "steel", math.degrees(angle))
    # A restrained technical grid grounds the machine without interfering with selection.
    for i in range(-9, 10):
        cube(stage, f"/World/Environment/GridX_{i+9:02d}", (i*5, 0, -16.087), (0.013, 90, 0.006), "trim")
        cube(stage, f"/World/Environment/GridY_{i+9:02d}", (0, i*5, -16.087), (90, 0.013, 0.006), "trim")


def aim(prim, eye, target, up=(0, 0, 1)):
    matrix = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(*up)).GetInverse()
    UsdGeom.Xformable(prim).AddTransformOp().Set(matrix)


def lighting(stage):
    UsdGeom.Xform.Define(stage, "/World/Lighting")
    dome = UsdLux.DomeLight.Define(stage, "/World/Lighting/StudioFill")
    dome.CreateIntensityAttr(230)
    dome.CreateColorAttr(Gf.Vec3f(0.72, 0.81, 0.93))
    # Large white studio sources produce broad readable reflections on the metal casing.
    for name, eye, size, intensity, color in (
        ("Key", (18, -29, 29), (20, 14), 2000, (1.0, 0.96, 0.89)),
        ("Left", (-27, -13, 14), (12, 24), 1600, (0.78, 0.88, 1.0)),
        ("Back", (4, 25, 24), (18, 11), 2300, (0.86, 0.93, 1.0)),
        ("Section", (27, -24, 3), (12, 18), 850, (1.0, 0.95, 0.86)),
    ):
        light = UsdLux.RectLight.Define(stage, "/World/Lighting/" + name)
        light.CreateWidthAttr(size[0])
        light.CreateHeightAttr(size[1])
        light.CreateIntensityAttr(intensity)
        light.CreateColorAttr(Gf.Vec3f(*color))
        aim(light.GetPrim(), eye, (0, 0, 0))


def cameras(stage):
    UsdGeom.Xform.Define(stage, "/World/Cameras")
    views = {
        "overview": ((43, -44, 27), (0, 0, -1.8), 39, (0, 0, 1)),
        "front": ((38, -45, 2), (0, 0, -1.5), 43, (0, 0, 1)),
        "top": ((0, 0, 64), (0, 0, 0), 43, (0, 1, 0)),
        "section": ((28, -30, 7), (2, -1, -0.4), 36, (0, 0, 1)),
        "divertor": ((18, -19, -2), (6, -4, -6.2), 34, (0, 0, 1)),
    }
    result = {}
    for name, (eye, target, focal, up) in views.items():
        path = f"/World/Cameras/{name}"
        camera = UsdGeom.Camera.Define(stage, path)
        camera.CreateHorizontalApertureAttr(36.0)
        camera.CreateVerticalApertureAttr(22.5)
        camera.CreateFocalLengthAttr(focal)
        camera.CreateClippingRangeAttr(Gf.Vec2f(0.05, 2000))
        camera.CreateFocusDistanceAttr(float(np.linalg.norm(np.subtract(eye, target))))
        aim(camera.GetPrim(), eye, target, up)
        result[name] = {"usd_path": path, "eye_m": list(eye), "target_m": list(target)}
    return result


def build(legacy: Path | None = None, copy=True, output_assets: Path | None = None,
          provenance_root: Path | None = None):
    output_assets = Path(output_assets) if output_assets is not None else ASSETS
    scene_dir = output_assets / "scene"
    if copy and legacy is not None:
        copy_sources(legacy, provenance_root=provenance_root)
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
        "cutaway": {"start_deg": 280, "end_deg": 360, "sector_indices": list(CUT_SECTORS),
                    "description": "80 degree opening follows four exact 20 degree CAD sectors."},
        "geometry_notes": ["Full named component hierarchy from source CAD; no reactor components replaced by display primitives.",
                           "PF/CS and plasma are revolved from source RZ end-cap sections; artificial radial caps are separately controlled.",
                           "PF/CS classification uses source equilibrium coil names/types, verified against CAD section centres.",
                           "Studio plinth, floor and supports are visualization-only environment geometry.",
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
