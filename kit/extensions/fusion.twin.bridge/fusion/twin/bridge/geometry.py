"""Session-layer CAD cuts, with exposed caps and source topology restoration."""

import math
import sys
from pathlib import Path

import numpy as np
from pxr import Gf, Usd, UsdGeom, Vt

sys.path.insert(0, str(Path(__file__).resolve().parents[6] / "app"))
from fusion_twin.geometry import angular_bounds, clip_mesh_angular, merge_meshes, revolve_from_endcap


def _normals(points, triangles):
    corners = points[triangles]
    area = np.cross(corners[:, 1]-corners[:, 0], corners[:, 2]-corners[:, 0])
    unit = area / np.maximum(np.linalg.norm(area, axis=1, keepdims=True), 1e-15)
    _, welded = np.unique(np.round(points, 6), axis=0, return_inverse=True)
    ids = welded[triangles].ravel()
    faces = np.repeat(np.arange(len(triangles)), 3)
    order = np.argsort(ids)
    bounds = np.r_[0, np.flatnonzero(np.diff(ids[order]))+1, len(order)]
    result = np.empty((len(triangles)*3, 3), dtype=np.float32)
    for start, end in zip(bounds[:-1], bounds[1:]):
        slots = order[start:end]
        adjacent = faces[slots]
        weighted = ((unit[adjacent] @ unit[adjacent].T) >= math.cos(math.radians(38))) @ area[adjacent]
        weighted /= np.maximum(np.linalg.norm(weighted, axis=1, keepdims=True), 1e-15)
        result[slots] = weighted
    return result


class GeometryController:
    """Call reset after changing design, then apply with the committed state.

    apply controls component/part visibility and sector explode transforms. CAD
    source layers stay untouched. Cuts use un-exploded world angles [0,360-cut].
    """

    def __init__(self, stage):
        self.stage = stage
        self.modified = set()
        self.reset(stage)

    def reset(self, stage):
        for path in self.modified:
            prim = self.stage.GetPrimAtPath(path)
            if prim:
                for name in ("points", "faceVertexCounts", "faceVertexIndices", "normals", "extent"):
                    prim.GetAttribute(name).Clear()
        self.modified.clear()
        self.stage = stage
        self.components = {}
        self.records = []
        self.bounds = {}
        self.cut_cache = {}
        self.signature = None
        for component in stage.GetPrimAtPath("/World/Machine").GetChildren():
            name = component.GetName()
            self.components[name] = component
            for sector in component.GetChildren():
                if not sector.GetName().startswith("sector_"):
                    continue
                number = int(sector.GetName().rsplit("_", 1)[1])
                parts = []
                for part in sector.GetChildren():
                    if part.GetCustomDataByKey("sourcePartId") is None:
                        continue
                    continuous = bool(part.GetCustomDataByKey("continuousRevolution"))
                    meshes = list(part.GetChildren()) if continuous else [part]
                    geometry = {}
                    for prim in meshes:
                        if not prim.IsA(UsdGeom.Mesh):
                            continue
                        mesh = UsdGeom.Mesh(prim)
                        geometry[prim.GetName() if continuous else "solid"] = (
                            str(prim.GetPath()), np.asarray(mesh.GetPointsAttr().Get(), dtype=np.float64),
                            np.asarray(mesh.GetFaceVertexIndicesAttr().Get(), dtype=np.int32).reshape(-1,3))
                        self.bounds[str(prim.GetPath())] = angular_bounds(geometry[prim.GetName() if continuous else "solid"][1])
                    parts.append((continuous, geometry))
                self.records.append((name, number, sector, parts))

    def _restore(self, path):
        if path in self.modified:
            prim = self.stage.GetPrimAtPath(path)
            for name in ("points", "faceVertexCounts", "faceVertexIndices", "normals", "extent"):
                prim.GetAttribute(name).Clear()
            self.modified.remove(path)

    def _write(self, path, points, triangles):
        mesh = UsdGeom.Mesh(self.stage.GetPrimAtPath(path))
        mesh.GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(np.asarray(points, dtype=np.float32)))
        mesh.GetFaceVertexCountsAttr().Set(Vt.IntArray.FromNumpy(np.full(len(triangles),3,dtype=np.int32)))
        mesh.GetFaceVertexIndicesAttr().Set(Vt.IntArray.FromNumpy(np.asarray(triangles,dtype=np.int32).ravel()))
        mesh.GetNormalsAttr().Set(Vt.Vec3fArray.FromNumpy(_normals(points,triangles)))
        mesh.SetNormalsInterpolation(UsdGeom.Tokens.faceVarying)
        mesh.GetExtentAttr().Set(Vt.Vec3fArray.FromNumpy(np.asarray((points.min(0),points.max(0)),dtype=np.float32)))
        self.modified.add(path)

    def _visible(self, path, value):
        UsdGeom.Imageable(self.stage.GetPrimAtPath(path)).CreateVisibilityAttr().Set("inherited" if value else "invisible")

    def _cut(self, path, points, triangles, angle, end):
        low, high = self.bounds[path]
        intervals = []
        for turn in (-360,0,360):
            start = max(low+angle+turn,0)
            stop = min(high+angle+turn,end)
            if stop-start > 1e-4:
                intervals.append((start-angle-turn,stop-angle-turn))
        if not intervals:
            return None
        if sum(b-a for a,b in intervals) >= high-low-1e-4:
            return points,triangles,False
        # Identical source parts share clipped geometry across toroidal sectors.
        key = (path.split('/')[3],path.rsplit('/',1)[1],
               tuple((round(a,4),round(b,4)) for a,b in intervals))
        if key not in self.cut_cache:
            meshes=[clip_mesh_angular(points,triangles,a,b) for a,b in intervals]
            self.cut_cache[key]=merge_meshes(meshes) if len(meshes)>1 else meshes[0]
        return (*self.cut_cache[key],True)

    def apply(self, state):
        visible = state.get("visible", {})
        for name, component in self.components.items():
            UsdGeom.Imageable(component).CreateVisibilityAttr().Set("inherited" if visible.get(name,True) else "invisible")
        cut = min(180., max(0., float(state.get("cutaway",80))))
        explode = float(state.get("explode",0))
        signature = (cut, explode)
        if signature == self.signature:
            return
        end = 360-cut
        for name, number, sector, parts in self.records:
            angle = number*20.
            any_visible = False
            for continuous, geometry in parts:
                if continuous:
                    span = min(20., end-angle)
                    shown = span > 1e-7
                    any_visible |= shown
                    if not shown:
                        for path,_,_ in geometry.values():
                            self._visible(path,False)
                        continue
                    if span < 20-1e-7:
                        solid = merge_meshes((p,t) for _,p,t in geometry.values())
                        rebuilt = revolve_from_endcap(*solid,angle_deg=span)
                    else:
                        rebuilt = None
                    for role,(path,_,_) in geometry.items():
                        if rebuilt is None:
                            self._restore(path)
                        else:
                            self._write(path,*rebuilt[role])
                        cap = role != "body"
                        exposed = explode > 0 or (cut > 0 and ((role == "cap_start" and number == 0)
                                          or (role == "cap_end" and angle+span >= end-1e-7)))
                        self._visible(path,not cap or exposed)
                else:
                    for path, points, triangles in geometry.values():
                        if cut == 0:
                            self._restore(path)
                            self._visible(path,True)
                            any_visible = True
                            continue
                        result = self._cut(path,points,triangles,angle,end)
                        shown = result is not None
                        self._visible(path,shown)
                        any_visible |= shown
                        if shown:
                            local,faces,changed=result
                            if not changed:
                                self._restore(path)
                            else:
                                self._write(path,local,faces)
            UsdGeom.Imageable(sector).CreateVisibilityAttr().Set("inherited" if any_visible else "invisible")
            xform = UsdGeom.Xformable(sector)
            op = next((op for op in xform.GetOrderedXformOps() if op.GetOpName()=="xformOp:translate:explode"),None)
            if op is None:
                op=xform.AddTranslateOp(opSuffix="explode")
            direction=math.radians(0 if name=="tf_coils" else 10)
            offset=explode*(1+list(self.components).index(name)*.32)
            op.Set(Gf.Vec3d(math.cos(direction)*offset,math.sin(direction)*offset,0))
        self.signature = signature
