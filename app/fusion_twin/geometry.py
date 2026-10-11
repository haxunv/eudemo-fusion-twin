"""CAD-derived revolutions and closed angular mesh cuts, in metres and Z-up."""

from __future__ import annotations

import math
import numpy as np

TOLERANCE = 1e-5
CONTINUOUS_COMPONENTS = frozenset(("pf_coils", "cs_coils", "plasma"))


def weld_mesh(points, triangles, tolerance=TOLERANCE):
    points = np.asarray(points, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.int32).reshape(-1, 3)
    if not len(triangles):
        return np.empty((0, 3)), np.empty((0, 3), dtype=np.int32)
    _, first, inverse = np.unique(np.round(points / tolerance).astype(np.int64), axis=0,
                                  return_index=True, return_inverse=True)
    points, triangles = points[first], inverse[triangles]
    corners = points[triangles]
    keep = np.linalg.norm(np.cross(corners[:, 1] - corners[:, 0],
                                  corners[:, 2] - corners[:, 0]), axis=1) > 1e-12
    triangles = triangles[keep]
    used, inverse = np.unique(triangles, return_inverse=True)
    return points[used], inverse.reshape(-1, 3).astype(np.int32)


def angular_bounds(points, axis_tolerance=TOLERANCE):
    points = np.asarray(points)
    points = points[np.linalg.norm(points[:, :2], axis=1) > axis_tolerance]
    angles = np.degrees(np.arctan2(points[:, 1], points[:, 0]))
    return float(angles.min()), float(angles.max())


def merge_meshes(meshes):
    points, triangles, offset = [], [], 0
    for p, t in meshes:
        points.append(p)
        triangles.append(np.asarray(t) + offset)
        offset += len(p)
    return weld_mesh(np.concatenate(points), np.concatenate(triangles))


def revolve_from_endcap(points, triangles, angle_deg=20.0, max_step_deg=2.0):
    """Revolve the source zero-angle cap, preserving its holes and part boundary.

    Original cap triangulation supplies the RZ section. Only its boundary edges
    create the lateral surface; artificial radial caps remain separate meshes.
    """
    points, triangles = weld_mesh(points, triangles)
    cap = triangles[np.all(np.abs(points[triangles, 1]) <= TOLERANCE, axis=1)]
    if not len(cap):
        raise ValueError("Source part has no zero-angle planar end cap")
    profile, cap = weld_mesh(points, cap)
    profile = np.column_stack((np.linalg.norm(profile[:, :2], axis=1),
                               np.zeros(len(profile)), profile[:, 2]))
    # Start outward normal is -Y. Source tessellation winding is not assumed.
    normals = np.cross(profile[cap[:, 1]] - profile[cap[:, 0]],
                       profile[cap[:, 2]] - profile[cap[:, 0]])
    cap[normals[:, 1] > 0] = cap[normals[:, 1] > 0][:, ::-1]
    edges = np.concatenate((cap[:, [0, 1]], cap[:, [1, 2]], cap[:, [2, 0]]))
    _, inverse, counts = np.unique(np.sort(edges, axis=1), axis=0, return_inverse=True,
                                   return_counts=True)
    boundary = edges[counts[inverse] == 1]
    steps = max(1, math.ceil(angle_deg / max_step_deg))
    angles = np.linspace(0, math.radians(angle_deg), steps + 1)
    rings = np.empty((steps + 1, len(profile), 3))
    rings[:, :, 0] = np.cos(angles)[:, None] * profile[:, 0]
    rings[:, :, 1] = np.sin(angles)[:, None] * profile[:, 0]
    rings[:, :, 2] = profile[:, 2]
    faces = []
    n = len(profile)
    for step in range(steps):
        for a, b in boundary:
            # Reverse the cap boundary edge on the adjoining side wall.
            faces.extend(((b + step*n, a + step*n, a + (step+1)*n),
                          (b + step*n, a + (step+1)*n, b + (step+1)*n)))
    return {"body": weld_mesh(rings.reshape(-1, 3), faces),
            "cap_start": (rings[0].copy(), cap.copy()),
            "cap_end": (rings[-1].copy(), cap[:, ::-1].copy())}


def _area(points):
    return float(np.sum(points[:, 0] * np.roll(points[:, 1], -1)
                        - points[:, 1] * np.roll(points[:, 0], -1)) * 0.5)


def _inside(point, polygon):
    x, y = point
    a, b = polygon, np.roll(polygon, -1, axis=0)
    crosses = ((a[:, 1] > y) != (b[:, 1] > y))
    dy = b[:, 1] - a[:, 1]
    xx = a[:, 0] + (y-a[:, 1]) * (b[:, 0]-a[:, 0]) / np.where(abs(dy) > 1e-15, dy, 1)
    return bool(np.count_nonzero(crosses & (x < xx)) % 2)


def _cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])


def _proper_intersection(a, b, c, d):
    return _cross(a, b, c) * _cross(a, b, d) < -1e-16 and _cross(c, d, a) * _cross(c, d, b) < -1e-16


def _triangulate_loops(points, loops):
    """Ear clipping with visible bridges for nested planar contours."""
    polygons = [list(loop) for loop in loops if len(loop) >= 3]
    parents = []
    for i, loop in enumerate(polygons):
        enclosing = [j for j, other in enumerate(polygons) if i != j
                     and abs(_area(points[other])) > abs(_area(points[loop]))
                     and _inside(points[loop[0]], points[other])]
        parents.append(min(enclosing, key=lambda j: abs(_area(points[polygons[j]]))) if enclosing else None)
    depth = []
    for parent in parents:
        count = 0
        while parent is not None:
            count += 1
            parent = parents[parent]
        depth.append(count)
    result = []
    for i, outer in enumerate(polygons):
        if depth[i] % 2:
            continue
        outer = outer if _area(points[outer]) > 0 else outer[::-1]
        holes = [loop if _area(points[loop]) < 0 else loop[::-1]
                 for j, loop in enumerate(polygons) if parents[j] == i]
        for hole in sorted(holes, key=lambda loop: float(points[loop, 0].max()), reverse=True):
            candidates = sorted((float(np.linalg.norm(points[a]-points[b])), ai, bi)
                                for ai, a in enumerate(outer) for bi, b in enumerate(hole))
            for _, ai, bi in candidates:
                a, b = points[outer[ai]], points[hole[bi]]
                midpoint = (a+b)*0.5
                if not _inside(midpoint, points[polygons[i]]) or any(_inside(midpoint, points[h]) for h in holes):
                    continue
                contours = [outer] + holes
                if any(_proper_intersection(a,b,points[c],points[d]) for loop in contours
                       for c,d in zip(loop, loop[1:]+loop[:1])):
                    continue
                outer = outer[:ai+1] + hole[bi:] + hole[:bi+1] + [outer[ai]] + outer[ai+1:]
                break
            else:
                raise ValueError("Cannot bridge a cut-face hole")
        remaining = outer.copy()
        while len(remaining) > 3:
            found = False
            positions = points[remaining]
            for k, b in enumerate(remaining):
                a, c = remaining[k-1], remaining[(k+1) % len(remaining)]
                pa, pb, pc = points[[a,b,c]]
                if _cross(pa,pb,pc) <= 1e-12:
                    continue
                delta = positions[:,None,:]-np.array((pa,pb,pc))[None,:,:]
                distinct = np.min(np.sum(delta*delta,axis=2),axis=1) > TOLERANCE*TOLERANCE
                ab = (pb[0]-pa[0])*(positions[:,1]-pa[1])-(pb[1]-pa[1])*(positions[:,0]-pa[0])
                bc = (pc[0]-pb[0])*(positions[:,1]-pb[1])-(pc[1]-pb[1])*(positions[:,0]-pb[0])
                ca = (pa[0]-pc[0])*(positions[:,1]-pc[1])-(pa[1]-pc[1])*(positions[:,0]-pc[0])
                if np.any(distinct & (ab >= -1e-12) & (bc >= -1e-12) & (ca >= -1e-12)):
                    continue
                result.append((a,b,c))
                remaining.pop(k)
                found = True
                break
            if not found:
                # Boundary vertices from triangle cuts can be exactly collinear.
                for k,b in enumerate(remaining):
                    a,c = remaining[k-1],remaining[(k+1)%len(remaining)]
                    if abs(_cross(points[a],points[b],points[c])) < 1e-11:
                        remaining.pop(k)
                        found = True
                        break
            if not found:
                raise ValueError("Cut-face contour cannot be triangulated")
        if len(remaining) == 3 and abs(_cross(*points[remaining])) > 1e-12:
            result.append(tuple(remaining))
    return np.asarray(result, dtype=np.int32).reshape(-1,3)


def clip_mesh_plane(points, triangles, normal, offset=0.0):
    """Keep dot(point, normal)>=offset and close every exposed cut contour."""
    points, triangles = np.asarray(points,dtype=float), np.asarray(triangles,dtype=np.int32)
    normal = np.asarray(normal, dtype=float)
    normal /= np.linalg.norm(normal)
    distances = points @ normal - offset
    if np.all(distances >= -TOLERANCE):
        return points, triangles
    if np.all(distances <= TOLERANCE):
        return np.empty((0,3)), np.empty((0,3), dtype=np.int32)
    points,triangles=weld_mesh(points,triangles)
    distances=points@normal-offset
    output, faces = [], []
    for face in triangles:
        polygon = []
        for ai, bi in zip(face, np.roll(face,-1)):
            a,b = points[ai],points[bi]
            da,db = distances[ai],distances[bi]
            if da >= -TOLERANCE:
                polygon.append(a if abs(da)>TOLERANCE else a-da*normal)
            if (da > TOLERANCE and db < -TOLERANCE) or (da < -TOLERANCE and db > TOLERANCE):
                polygon.append(a+(b-a)*(da/(da-db)))
        if len(polygon)>=3:
            begin=len(output);output.extend(polygon)
            faces.extend((begin,begin+i,begin+i+1) for i in range(1,len(polygon)-1))
    points,triangles=weld_mesh(output,faces)
    if not len(triangles):
        return points,triangles
    edges=np.concatenate((triangles[:,[0,1]],triangles[:,[1,2]],triangles[:,[2,0]]))
    _,inv,counts=np.unique(np.sort(edges,axis=1),axis=0,return_inverse=True,return_counts=True)
    boundary=edges[(counts[inv]==1) & np.all(np.abs(points[edges]@normal-offset)<=TOLERANCE*2,axis=1)]
    adjacency={}
    for a,b in boundary:
        adjacency.setdefault(int(a),[]).append(int(b));adjacency.setdefault(int(b),[]).append(int(a))
    if any(len(neighbors)!=2 for neighbors in adjacency.values()):
        raise ValueError("Cut boundary is not a closed two-manifold contour")
    loops=[];unvisited=set(adjacency)
    while unvisited:
        start=next(iter(unvisited));loop=[start];previous=None;current=start
        while True:
            neighbors=adjacency[current];nxt=next(x for x in neighbors if x!=previous)
            if nxt==start:break
            loop.append(nxt);previous,current=current,nxt
        unvisited.difference_update(loop);loops.append(loop)
    outward=-normal
    reference=np.array((0.,0.,1.)) if abs(outward[2])<.9 else np.array((1.,0.,0.))
    u=np.cross(reference,outward);u/=np.linalg.norm(u);v=np.cross(outward,u)
    projected=np.column_stack((points@u,points@v))
    caps=_triangulate_loops(projected,loops)
    return weld_mesh(points,np.concatenate((triangles,caps)))


def clip_mesh_angular(points, triangles, start_deg, end_deg):
    """Keep a convex world-angle wedge (at most 180 degrees) and close it."""
    if not 0 < end_deg-start_deg <= 180.000001:
        raise ValueError("Angular clipping wedge must span (0,180] degrees")
    a,b=map(math.radians,(start_deg,end_deg))
    result=clip_mesh_plane(points,triangles,(-math.sin(a),math.cos(a),0))
    if not len(result[1]):return result
    return clip_mesh_plane(*result,(math.sin(b),-math.cos(b),0))


def clip_visible_arc(points, triangles, end_deg):
    """Keep [0,end] for a source part spanning less than 180 degrees.

    The demo retains 180..360 degrees. Parts across the zero-angle seam can
    become two disconnected solids; each is independently capped.
    """
    if end_deg >= 360-1e-7:
        return np.asarray(points), np.asarray(triangles)
    if not 180 <= end_deg < 360:
        raise ValueError("Visible arc must span [180,360] degrees")
    points=np.asarray(points)
    end=math.radians(end_deg)
    end_normal=(math.sin(end),-math.cos(end),0)
    if np.min(points[:,1]) >= -TOLERANCE:
        return points,np.asarray(triangles)
    if np.max(points[:,1]) <= TOLERANCE or np.mean(points[:,0]) < 0:
        return clip_mesh_plane(points,triangles,end_normal)
    upper=clip_mesh_plane(points,triangles,(0,1,0))
    lower=clip_mesh_plane(points,triangles,(0,-1,0))
    if len(lower[1]):
        lower=clip_mesh_plane(*lower,end_normal)
    return merge_meshes((upper,lower))
