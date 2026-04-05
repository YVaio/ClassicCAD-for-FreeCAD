"""Custom TRIM and EXTEND commands."""

import math
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore


def parse_vector(p):
    if p is None:
        return None
    if isinstance(p, App.Vector):
        return p
    if hasattr(p, 'x') and hasattr(p, 'y'):
        try:
            return App.Vector(float(p.x), float(p.y), float(getattr(p, 'z', 0.0)))
        except Exception:
            return None
    if isinstance(p, (tuple, list)) and len(p) >= 2:
        try:
            z = p[2] if len(p) >= 3 else 0.0
            return App.Vector(float(p[0]), float(p[1]), float(z))
        except Exception:
            return None
    return None


def intersect_2d(a, b, c, d):
    x1, y1 = a.x, a.y
    x2, y2 = b.x, b.y
    x3, y3 = c.x, c.y
    x4, y4 = d.x, d.y

    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-9:
        return None

    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    return App.Vector(
        x1 + t * (x2 - x1),
        y1 + t * (y2 - y1),
        a.z + t * (b.z - a.z),
    )


def _edge_index(subname):
    if isinstance(subname, str) and subname.startswith('Edge'):
        try:
            return max(0, int(subname[4:]) - 1)
        except Exception:
            return 0
    return 0


def _to_world(obj, vec):
    try:
        if hasattr(obj, 'Placement') and obj.Placement:
            return obj.Placement.multVec(vec)
    except Exception:
        pass
    return vec


def _to_local(obj, vec):
    try:
        if hasattr(obj, 'Placement') and obj.Placement:
            return obj.Placement.inverse().multVec(vec)
    except Exception:
        pass
    return vec


def _draft_type(obj):
    try:
        import draftutils.utils as draft_utils
        return draft_utils.getType(obj)
    except Exception:
        return ''


def _get_shape_edge(obj, subname):
    try:
        edges = list(getattr(obj.Shape, 'Edges', []) or [])
        if not edges:
            return None
        idx = min(max(_edge_index(subname), 0), len(edges) - 1)
        return edges[idx]
    except Exception:
        return None


def _expand_boundary_subnames(obj, subname=None):
    if subname and 'Edge' in str(subname):
        return [str(subname)]

    try:
        edge_count = len(getattr(obj.Shape, 'Edges', []) or [])
    except Exception:
        edge_count = 0

    if edge_count > 0:
        return [f'Edge{i + 1}' for i in range(edge_count)]
    return ['Edge1']


def _get_points_target_info(obj, subname):
    points = list(getattr(obj, 'Points', []) or [])
    if len(points) < 2:
        return None

    closed = bool(getattr(obj, 'Closed', False)) and len(points) > 2
    edge_count = len(points) if closed else max(0, len(points) - 1)
    if edge_count <= 0:
        return None

    idx = min(max(_edge_index(subname), 0), edge_count - 1)
    a_local = points[idx]
    b_local = points[(idx + 1) % len(points)]
    return {
        'kind': 'points',
        'edge_index': idx,
        'closed': closed,
        'a_world': _to_world(obj, a_local),
        'b_world': _to_world(obj, b_local),
    }


def _get_target_info(obj, subname):
    obj_type = _draft_type(obj)

    if obj_type == 'Wire' and hasattr(obj, 'Points'):
        edge = _get_shape_edge(obj, subname)
        if edge:
            return {
                'kind': 'wire',
                'edge_index': min(max(_edge_index(subname), 0), len(getattr(obj.Shape, 'Edges', []) or []) - 1),
                'edge': edge,
                'object_type': obj_type,
            }

    if obj_type in ('BSpline', 'BezCurve', 'Sketch'):
        edge = _get_shape_edge(obj, subname)
        if edge:
            return {
                'kind': 'shape_edge',
                'edge_index': min(max(_edge_index(subname), 0), len(getattr(obj.Shape, 'Edges', []) or []) - 1),
                'edge': edge,
                'object_type': obj_type,
            }

    if hasattr(obj, 'Points'):
        info = _get_points_target_info(obj, subname)
        if info:
            return info

    if hasattr(obj, 'Start') and hasattr(obj, 'End'):
        return {
            'kind': 'start_end',
            'a_world': _to_world(obj, obj.Start),
            'b_world': _to_world(obj, obj.End),
        }

    if all(hasattr(obj, name) for name in ('X1', 'Y1', 'Z1', 'X2', 'Y2', 'Z2')):
        a = App.Vector(obj.X1, obj.Y1, obj.Z1)
        b = App.Vector(obj.X2, obj.Y2, obj.Z2)
        return {
            'kind': 'xyz_line',
            'a_world': _to_world(obj, a),
            'b_world': _to_world(obj, b),
        }

    if hasattr(obj, 'Radius') and hasattr(obj, 'Placement'):
        try:
            radius = float(getattr(obj.Radius, 'Value', obj.Radius))
        except Exception:
            radius = None
        if radius and radius > 1e-9:
            return {
                'kind': 'circle',
                'center': obj.Placement.Base,
                'radius': radius,
                'first_angle': float(getattr(obj, 'FirstAngle', 0.0)),
                'last_angle': float(getattr(obj, 'LastAngle', 360.0)),
            }

    return None


def _parameter_bounds(edge):
    first = float(getattr(edge, 'FirstParameter', 0.0))
    last = float(getattr(edge, 'LastParameter', 0.0))
    return (min(first, last), max(first, last))


def _parameter_in_range(edge, value, tol=1e-6):
    low, high = _parameter_bounds(edge)
    return (low - tol) <= value <= (high + tol)


def _edge_parameter(edge, point):
    curve = getattr(edge, 'Curve', None)
    if curve and hasattr(curve, 'parameter'):
        try:
            return float(curve.parameter(point))
        except Exception:
            pass
    try:
        import Part
        return float(edge.parameterAt(Part.Vertex(point)))
    except Exception:
        return None


def _normalize_hit_points(hits):
    if not hits:
        return []
    if isinstance(hits, App.Vector):
        return [hits]

    result = []
    for hit in hits:
        if isinstance(hit, App.Vector):
            result.append(hit)
            continue
        point = parse_vector(hit)
        if isinstance(point, App.Vector):
            result.append(point)
    return result


def _dedupe_curve_points(points, tol=1e-6):
    unique = []
    for point in points:
        if not unique or point.distanceToPoint(unique[-1]) > tol:
            unique.append(point)
    return unique


def _sample_edge_polyline(edge, sample_count=64):
    try:
        points = list(edge.discretize(Number=max(2, int(sample_count))))
    except Exception:
        points = [vertex.Point for vertex in getattr(edge, 'Vertexes', [])]
    return _dedupe_curve_points(points)


def _edge_curve_name(edge):
    curve = getattr(edge, 'Curve', None)
    if not curve:
        return ''
    type_id = str(getattr(curve, 'TypeId', '') or '')
    class_name = getattr(getattr(curve, '__class__', None), '__name__', '') or ''
    return f'{type_id} {class_name}'.lower()


def _edge_line_points(edge):
    verts = list(getattr(edge, 'Vertexes', []) or [])
    if len(verts) < 2:
        return None
    name = _edge_curve_name(edge)
    if 'line' not in name and 'segment' not in name:
        return None
    return verts[0].Point, verts[-1].Point


def _edge_circle_data(edge):
    curve = getattr(edge, 'Curve', None)
    if not curve:
        return None
    name = _edge_curve_name(edge)
    if 'circle' not in name:
        return None
    center = getattr(curve, 'Center', None)
    radius = getattr(curve, 'Radius', None)
    if center is None or radius is None:
        return None
    try:
        radius = float(getattr(radius, 'Value', radius))
    except Exception:
        return None
    if radius <= 1e-9:
        return None
    return center, radius


def _approx_edge_intersections(target_edge, boundary_edge, infinite_target=False):
    target_points = _sample_edge_polyline(target_edge)
    boundary_points = _sample_edge_polyline(boundary_edge)
    if len(target_points) < 2 or len(boundary_points) < 2:
        return []

    tol = 1e-5
    points = []
    for idx in range(len(target_points) - 1):
        a = target_points[idx]
        b = target_points[idx + 1]
        for jdx in range(len(boundary_points) - 1):
            c = boundary_points[jdx]
            d = boundary_points[jdx + 1]
            hit = intersect_2d(a, b, c, d)
            if not hit:
                continue

            target_t = _line_parameter(a, b, hit)
            boundary_t = _line_parameter(c, d, hit)
            if not (-tol <= boundary_t <= 1.0 + tol):
                continue
            if (not infinite_target) and (not (-tol <= target_t <= 1.0 + tol)):
                continue
            if all(hit.distanceToPoint(existing) > tol for existing in points):
                points.append(hit)
    return points


def _analytic_edge_intersections(target_edge, boundary_edge, infinite_target=False):
    target_line = _edge_line_points(target_edge)
    boundary_line = _edge_line_points(boundary_edge)
    target_circle = _edge_circle_data(target_edge)
    boundary_circle = _edge_circle_data(boundary_edge)

    if target_line and boundary_line:
        hit = intersect_2d(target_line[0], target_line[1], boundary_line[0], boundary_line[1])
        return [hit] if hit else []

    if target_circle and boundary_line:
        return _segment_circle_intersections(
            target_circle[0],
            target_circle[1],
            boundary_line[0],
            boundary_line[1],
        )

    if target_line and boundary_circle:
        return _segment_circle_intersections(
            boundary_circle[0],
            boundary_circle[1],
            target_line[0],
            target_line[1],
            infinite_line=infinite_target,
        )

    return []


def _edge_intersections(target_edge, boundary_edge, infinite_target=False):
    points = _analytic_edge_intersections(target_edge, boundary_edge, infinite_target=infinite_target)

    if not points:
        try:
            import DraftGeomUtils
            hits = DraftGeomUtils.findIntersection(
                target_edge,
                boundary_edge,
                infinite_target,
                False,
                dts=False,
                findAll=True,
            )
            points.extend(_normalize_hit_points(hits))
        except Exception:
            pass

    if not points:
        try:
            curve1 = getattr(target_edge, 'Curve', None)
            curve2 = getattr(boundary_edge, 'Curve', None)
            if curve1 and curve2 and hasattr(curve1, 'intersectCC'):
                points.extend(_normalize_hit_points(curve1.intersectCC(curve2)))
        except Exception:
            pass

    if not points:
        points.extend(_approx_edge_intersections(target_edge, boundary_edge, infinite_target=infinite_target))

    unique = []
    for point in points:
        target_param = _edge_parameter(target_edge, point)
        boundary_param = _edge_parameter(boundary_edge, point)
        if boundary_param is None or not _parameter_in_range(boundary_edge, boundary_param):
            continue
        if target_param is None:
            continue
        if (not infinite_target) and (not _parameter_in_range(target_edge, target_param)):
            continue
        if all(point.distanceToPoint(existing) > 1e-6 for existing in unique):
            unique.append(point)
    return unique


def _iter_boundary_edges(doc, boundaries, exclude=None, exclude_objects=None):
    exclude = exclude or set()
    exclude_objects = {str(name) for name in (exclude_objects or set())}
    for boundary in boundaries:
        obj_name = boundary['obj_name']
        subname = boundary['sub']
        if _boundary_key(obj_name, subname) in exclude:
            continue
        if str(obj_name) in exclude_objects:
            continue

        obj = doc.getObject(obj_name) if doc else None
        if not obj:
            continue

        edge = _get_shape_edge(obj, subname)
        if edge:
            yield obj_name, subname, edge


def _collect_target_edge_hits(doc, target_name, target_sub, target_edge, boundaries, infinite_target=False):
    hits = []
    target_key = _boundary_key(target_name, target_sub)

    for _obj_name, _subname, boundary_edge in _iter_boundary_edges(
        doc,
        boundaries,
        exclude={target_key},
        exclude_objects={target_name},
    ):
        for point in _edge_intersections(target_edge, boundary_edge, infinite_target=infinite_target):
            param = _edge_parameter(target_edge, point)
            if param is None:
                continue
            hits.append((float(param), point))

    unique = []
    for param, point in sorted(hits, key=lambda item: item[0]):
        if all(point.distanceToPoint(existing[1]) > 1e-6 for existing in unique):
            unique.append((param, point))
    return unique


def _get_boundary_segment(obj, subname):
    edge = _get_shape_edge(obj, subname)
    if edge and len(edge.Vertexes) >= 2:
        return edge.Vertexes[0].Point, edge.Vertexes[-1].Point

    info = _get_target_info(obj, subname)
    if info and 'a_world' in info and 'b_world' in info:
        return info['a_world'], info['b_world']

    try:
        edges = obj.Shape.Edges
        if not edges:
            return None
        idx = min(max(_edge_index(subname), 0), len(edges) - 1)
        edge = edges[idx]
        return _to_world(obj, edge.Vertexes[0].Point), _to_world(obj, edge.Vertexes[-1].Point)
    except Exception:
        return None


def _choose_endpoint(a_world, b_world, pick_world, intersection):
    try:
        if pick_world and pick_world.distanceToPoint(App.Vector(0, 0, 0)) > 1e-9:
            da = pick_world.distanceToPoint(a_world)
            db = pick_world.distanceToPoint(b_world)
            return 0 if da <= db else 1
    except Exception:
        pass

    da = intersection.distanceToPoint(a_world)
    db = intersection.distanceToPoint(b_world)
    return 0 if da <= db else 1


def _apply_target_point(obj, info, new_world_point, pick_world):
    end_index = _choose_endpoint(info['a_world'], info['b_world'], pick_world, new_world_point)
    new_local = _to_local(obj, new_world_point)

    if info['kind'] == 'points':
        pts = list(obj.Points)
        idx = info['edge_index']
        if end_index == 0:
            pts[idx] = new_local
        else:
            pts[idx + 1] = new_local
        obj.Points = pts
        return

    if info['kind'] == 'start_end':
        if end_index == 0:
            obj.Start = new_local
        else:
            obj.End = new_local
        return

    if info['kind'] == 'xyz_line':
        if end_index == 0:
            obj.X1, obj.Y1, obj.Z1 = new_local.x, new_local.y, new_local.z
        else:
            obj.X2, obj.Y2, obj.Z2 = new_local.x, new_local.y, new_local.z


def _line_parameter(a, b, p):
    dx = b.x - a.x
    dy = b.y - a.y
    dz = b.z - a.z
    denom = dx * dx + dy * dy + dz * dz
    if denom < 1e-12:
        return 0.0
    return ((p.x - a.x) * dx + (p.y - a.y) * dy + (p.z - a.z) * dz) / denom


def _closest_path_position(path_points, edge_starts, pick_world):
    best = None

    for idx in range(len(path_points) - 1):
        start = path_points[idx]
        end = path_points[idx + 1]
        t = max(0.0, min(1.0, _line_parameter(start, end, pick_world)))
        point = App.Vector(
            start.x + (end.x - start.x) * t,
            start.y + (end.y - start.y) * t,
            start.z + (end.z - start.z) * t,
        )
        distance = point.distanceToPoint(pick_world)
        score = (distance, idx)

        if best is None or score < best['score']:
            best = {
                'score': score,
                'edge_index': idx,
                't': t,
                'point': point,
                's': edge_starts[idx] + start.distanceToPoint(end) * t,
            }

    return best


def _boundary_key(obj_name, subname):
    return (str(obj_name), _edge_index(subname))


def _dedupe_points(points, tol=1e-6):
    unique = []
    for point in points:
        if all(point.distanceToPoint(existing) > tol for existing in unique):
            unique.append(point)
    return unique


def _set_segment_on_object(obj, info, start_world, end_world):
    start_local = _to_local(obj, start_world)
    end_local = _to_local(obj, end_world)

    if info['kind'] == 'points':
        pts = list(obj.Points)
        idx = info['edge_index']
        if len(pts) <= 2:
            obj.Points = [start_local, end_local]
        else:
            pts[idx] = start_local
            pts[idx + 1] = end_local
            obj.Points = pts
        return

    if info['kind'] == 'start_end':
        obj.Start = start_local
        obj.End = end_local
        return

    if info['kind'] == 'xyz_line':
        obj.X1, obj.Y1, obj.Z1 = start_local.x, start_local.y, start_local.z
        obj.X2, obj.Y2, obj.Z2 = end_local.x, end_local.y, end_local.z


def _copy_style_and_layer(src_obj, new_obj):
    try:
        import ccad_layers
        layer = ccad_layers.get_object_layer(src_obj) or ccad_layers.get_active_layer(src_obj.Document)
        ccad_layers.assign_to_layer(new_obj, layer)
    except Exception:
        pass

    try:
        src_view = getattr(src_obj, 'ViewObject', None)
        dst_view = getattr(new_obj, 'ViewObject', None)
        if src_view and dst_view:
            for attr in ('LineColor', 'LineWidth', 'DrawStyle', 'PointColor', 'PointSize'):
                if hasattr(src_view, attr) and hasattr(dst_view, attr):
                    setattr(dst_view, attr, getattr(src_view, attr))
    except Exception:
        pass


def _make_line_copy(src_obj, start_world, end_world):
    if start_world.distanceToPoint(end_world) < 1e-6:
        return None

    import Draft

    try:
        new_obj = Draft.make_line(start_world, end_world)
    except Exception:
        new_obj = Draft.make_wire([start_world, end_world], closed=False, face=False)

    _copy_style_and_layer(src_obj, new_obj)
    return new_obj


def _make_wire_copy(src_obj, world_points):
    if len(world_points) < 2:
        return None

    import Draft

    new_obj = Draft.make_wire(world_points, closed=False, face=False)
    _copy_style_and_layer(src_obj, new_obj)
    return new_obj


def _remove_object(doc, obj):
    if not doc or not obj:
        return False
    try:
        doc.removeObject(obj.Name)
        return True
    except Exception:
        return False


def _dedupe_sequential_points(points, tol=1e-6):
    unique = []
    for point in points:
        if not unique or point.distanceToPoint(unique[-1]) > tol:
            unique.append(point)
    return unique


def _wire_path_data(obj):
    points = [_to_world(obj, point) for point in list(getattr(obj, 'Points', []) or [])]
    points = _dedupe_sequential_points(points)
    if len(points) < 2:
        return [], False, [], 0.0

    closed = bool(getattr(obj, 'Closed', False))
    if (not closed) and len(points) > 2 and points[0].distanceToPoint(points[-1]) <= 1e-6:
        closed = True

    path_points = list(points)
    if closed and path_points[0].distanceToPoint(path_points[-1]) > 1e-6:
        path_points.append(path_points[0])

    edge_starts = []
    total_length = 0.0
    for idx in range(len(path_points) - 1):
        edge_starts.append(total_length)
        total_length += path_points[idx].distanceToPoint(path_points[idx + 1])

    return path_points, closed, edge_starts, total_length


def _merge_breakpoints(points):
    merged = []
    for item in sorted(points, key=lambda bp: bp['s']):
        if merged:
            prev = merged[-1]
            if abs(item['s'] - prev['s']) <= 1e-6 and item['point'].distanceToPoint(prev['point']) <= 1e-6:
                prev['stop'] = prev['stop'] or item['stop']
                continue
        merged.append({'s': item['s'], 'point': item['point'], 'stop': bool(item['stop'])})
    return merged


def _wire_breakpoints(doc, target_name, obj, boundaries, path_points, closed, edge_starts, total_length):
    items = []
    if not closed:
        items.append({'s': 0.0, 'point': path_points[0], 'stop': True})

    edge_count = len(path_points) - 1
    for idx in range(edge_count):
        start = path_points[idx]
        end = path_points[idx + 1]
        start_s = edge_starts[idx]
        edge = _get_shape_edge(obj, f'Edge{idx + 1}')

        if idx > 0 or closed:
            # Preserve internal vertices in the rebuilt wire without forcing
            # trim to stop at every corner of a connected polyline.
            items.append({'s': start_s, 'point': start, 'stop': False})

        if edge:
            hits = _collect_target_edge_hits(doc, target_name, f'Edge{idx + 1}', edge, boundaries)
            edge_len = start.distanceToPoint(end)
            for _param, point in hits:
                t = max(0.0, min(1.0, _line_parameter(start, end, point)))
                if 1e-6 < t < 1.0 - 1e-6:
                    items.append({'s': start_s + edge_len * t, 'point': point, 'stop': True})

    if closed:
        items.append({'s': total_length, 'point': path_points[0], 'stop': False})
    else:
        items.append({'s': total_length, 'point': path_points[-1], 'stop': True})

    return _merge_breakpoints(items)


def _collect_points_in_range(breakpoints, start_s, end_s):
    points = []
    for item in breakpoints:
        if start_s - 1e-6 <= item['s'] <= end_s + 1e-6:
            if not points or item['point'].distanceToPoint(points[-1]) > 1e-6:
                points.append(item['point'])
    return points


def _set_wire_points(obj, world_points):
    world_points = _dedupe_sequential_points(list(world_points))
    if len(world_points) > 1 and world_points[0].distanceToPoint(world_points[-1]) <= 1e-6:
        world_points = world_points[:-1]

    local_points = [_to_local(obj, point) for point in world_points]
    local_points = _dedupe_sequential_points(local_points)
    if len(local_points) < 2:
        return False

    if hasattr(obj, 'Closed'):
        obj.Closed = False
    if hasattr(obj, 'MakeFace'):
        obj.MakeFace = False
    obj.Points = local_points
    return True


def _trim_wire_target(doc, target_name, target_sub, obj, pick_world, boundaries):
    path_points, closed, edge_starts, total_length = _wire_path_data(obj)
    if len(path_points) < 2 or total_length <= 1e-9:
        return False, 'This wire cannot be trimmed.'

    breakpoints = _wire_breakpoints(doc, target_name, obj, boundaries, path_points, closed, edge_starts, total_length)
    stops = [item for item in breakpoints if item['stop']]
    if len(stops) < 2:
        return False, 'Need two intersections to trim that wire.'

    pick_info = _closest_path_position(path_points, edge_starts, pick_world)
    if not pick_info:
        return False, 'Could not determine the picked wire segment.'

    pick_s = pick_info['s']

    if closed:
        prev_stop = None
        next_stop = None
        for stop in stops:
            if stop['s'] < pick_s - 1e-6:
                prev_stop = stop
            elif stop['s'] > pick_s + 1e-6 and next_stop is None:
                next_stop = stop

        if prev_stop is None:
            prev_stop = stops[-1]
        if next_stop is None:
            next_stop = stops[0]

        prev_s = prev_stop['s']
        next_s = next_stop['s']
        if next_s <= pick_s + 1e-6:
            next_s += total_length

        extended = list(breakpoints)
        for item in breakpoints:
            if item['s'] < total_length - 1e-6:
                extended.append({'s': item['s'] + total_length, 'point': item['point'], 'stop': item['stop']})
        extended.sort(key=lambda bp: bp['s'])

        keep_points = _collect_points_in_range(extended, next_s, prev_s + total_length)
        if not _set_wire_points(obj, keep_points):
            return False, 'Could not rebuild the trimmed wire.'
        return True, None

    prev_stop = stops[0]
    next_stop = stops[-1]
    for stop in stops:
        if stop['s'] <= pick_s + 1e-6:
            prev_stop = stop
        if stop['s'] >= pick_s - 1e-6:
            next_stop = stop
            break

    if next_stop['s'] - prev_stop['s'] <= 1e-6:
        return False, 'Could not determine the wire segment to trim.'

    keep_ranges = []
    if prev_stop['s'] > 1e-6:
        keep_ranges.append((0.0, prev_stop['s']))
    if next_stop['s'] < total_length - 1e-6:
        keep_ranges.append((next_stop['s'], total_length))

    if not keep_ranges:
        return False, 'Trimming would remove the entire wire.'

    first_points = _collect_points_in_range(breakpoints, keep_ranges[0][0], keep_ranges[0][1])
    if not _set_wire_points(obj, first_points):
        return False, 'Could not rebuild the trimmed wire.'

    if len(keep_ranges) > 1:
        second_points = _collect_points_in_range(breakpoints, keep_ranges[1][0], keep_ranges[1][1])
        _make_wire_copy(obj, second_points)

    return True, None


def _make_edge_piece(edge, start_param, end_param):
    if abs(end_param - start_param) <= 1e-9:
        return None

    try:
        curve = edge.Curve.trim(start_param, end_param)
        return curve.toShape()
    except Exception:
        pass

    try:
        return edge.Curve.toShape(start_param, end_param)
    except Exception:
        return None


def _sample_edge_points(edge, source_count=0):
    sample_count = max(16, int(source_count or 0) * 3)
    try:
        points = list(edge.discretize(Number=sample_count))
    except Exception:
        points = [vertex.Point for vertex in getattr(edge, 'Vertexes', [])]
    return _dedupe_sequential_points(points)


def _apply_bspline_piece(obj, piece_edge):
    points = _sample_edge_points(piece_edge, len(getattr(obj, 'Points', []) or []))
    local_points = [_to_local(obj, point) for point in points]
    local_points = _dedupe_sequential_points(local_points)
    if len(local_points) < 2:
        return False
    if hasattr(obj, 'Closed'):
        obj.Closed = False
    if hasattr(obj, 'MakeFace'):
        obj.MakeFace = False
    obj.Points = local_points
    return True


def _make_bspline_piece_copy(src_obj, piece_edge):
    import Draft

    points = _sample_edge_points(piece_edge, len(getattr(src_obj, 'Points', []) or []))
    if len(points) < 2:
        return None
    new_obj = Draft.make_bspline(points, closed=False, face=False)
    _copy_style_and_layer(src_obj, new_obj)
    return new_obj


def _apply_bezcurve_piece(obj, piece_edge):
    degree = int(getattr(obj, 'Degree', 3) or 3)
    curve = getattr(piece_edge, 'Curve', None)
    local_points = []

    if curve and hasattr(curve, 'getPoles'):
        try:
            local_points = [_to_local(obj, point) for point in list(curve.getPoles())]
        except Exception:
            local_points = []

    if len(local_points) < 2:
        points = _sample_edge_points(piece_edge, len(getattr(obj, 'Points', []) or []))
        local_points = [_to_local(obj, point) for point in points]

    local_points = _dedupe_sequential_points(local_points)
    if len(local_points) < 2:
        return False

    if hasattr(obj, 'Closed'):
        obj.Closed = False
    if hasattr(obj, 'MakeFace'):
        obj.MakeFace = False
    if hasattr(obj, 'Degree'):
        obj.Degree = min(max(1, degree), max(1, len(local_points) - 1))
    obj.Points = local_points
    return True


def _make_bezcurve_piece_copy(src_obj, piece_edge):
    import Draft

    degree = int(getattr(src_obj, 'Degree', 3) or 3)
    curve = getattr(piece_edge, 'Curve', None)
    points = []

    if curve and hasattr(curve, 'getPoles'):
        try:
            points = list(curve.getPoles())
        except Exception:
            points = []

    if len(points) < 2:
        points = _sample_edge_points(piece_edge, len(getattr(src_obj, 'Points', []) or []))

    if len(points) < 2:
        return None

    new_obj = Draft.make_bezcurve(points, closed=False, degree=min(max(1, degree), max(1, len(points) - 1)))
    _copy_style_and_layer(src_obj, new_obj)
    return new_obj


def _circle_local_angle(obj, point):
    local = _to_local(obj, point)
    return _normalize_angle(math.degrees(math.atan2(local.y, local.x)))


def _apply_circle_piece(obj, piece_edge):
    verts = list(getattr(piece_edge, 'Vertexes', []) or [])
    if len(verts) < 2:
        return False

    if hasattr(obj, 'MakeFace'):
        obj.MakeFace = False
    if not hasattr(obj, 'FirstAngle') or not hasattr(obj, 'LastAngle'):
        return False

    obj.FirstAngle = _circle_local_angle(obj, verts[0].Point)
    obj.LastAngle = _circle_local_angle(obj, verts[-1].Point)
    return True


def _make_circle_piece_copy(src_obj, piece_edge):
    import Draft

    try:
        new_obj = Draft.make_circle(piece_edge, face=False)
    except TypeError:
        new_obj = Draft.make_circle(piece_edge)

    if not new_obj:
        return None
    if hasattr(new_obj, 'MakeFace'):
        new_obj.MakeFace = False
    _copy_style_and_layer(src_obj, new_obj)
    return new_obj


def _trim_shape_edge_target(doc, target_name, target_sub, obj, target_info, pick_world, boundaries):
    obj_type = target_info.get('object_type')
    if obj_type == 'Sketch' and hasattr(obj, 'trim'):
        try:
            obj.trim(target_info['edge_index'], pick_world)
            return True, None
        except Exception as exc:
            return False, f'Could not trim sketch: {exc}'

    edge = target_info.get('edge')
    if not edge:
        return False, 'This curve cannot be trimmed.'

    intersections = _collect_target_edge_hits(doc, target_name, target_sub, edge, boundaries)
    if not intersections:
        return False, 'No valid cutting edge found for that curve.'

    low, high = _parameter_bounds(edge)
    endpoint_tol = 1e-6
    low_hit = any(abs(param - low) <= endpoint_tol for param, _point in intersections)
    high_hit = any(abs(param - high) <= endpoint_tol for param, _point in intersections)
    inner = [(param, point) for param, point in intersections if low + 1e-6 < param < high - 1e-6]
    if not inner:
        if low_hit and high_hit:
            if _remove_object(doc, obj):
                return True, None
            return False, 'Could not remove the trimmed curve.'
        return False, 'No cutting edge intersects the selected curve.'

    pick_param = _edge_parameter(edge, pick_world)
    if pick_param is None:
        pick_param = low
    pick_param = max(low, min(high, pick_param))

    params = [low] + [param for param, _point in inner] + [high]
    seg_index = len(params) - 2
    for idx in range(len(params) - 1):
        if params[idx] - 1e-6 <= pick_param <= params[idx + 1] + 1e-6:
            seg_index = idx
            break

    keep_ranges = []
    if seg_index == 0:
        keep_ranges.append((params[1], high))
    elif seg_index == len(params) - 2:
        keep_ranges.append((low, params[-2]))
    else:
        keep_ranges.append((low, params[seg_index]))
        keep_ranges.append((params[seg_index + 1], high))

    pieces = [piece for piece in (_make_edge_piece(edge, start, end) for start, end in keep_ranges) if piece]
    if not pieces:
        return False, 'Could not rebuild the trimmed curve.'

    if obj_type == 'BSpline':
        if not _apply_bspline_piece(obj, pieces[0]):
            return False, 'Could not rebuild the trimmed spline.'
        if len(pieces) > 1:
            _make_bspline_piece_copy(obj, pieces[1])
        return True, None

    if obj_type == 'BezCurve':
        if not _apply_bezcurve_piece(obj, pieces[0]):
            return False, 'Could not rebuild the trimmed bezier curve.'
        if len(pieces) > 1:
            _make_bezcurve_piece_copy(obj, pieces[1])
        return True, None

    return False, 'This curve type is not supported yet.'


def _find_line_intersections(doc, target_name, target_sub, target_info, boundaries):
    if not doc:
        return []

    a_world = target_info['a_world']
    b_world = target_info['b_world']
    line_edge = _get_shape_edge(doc.getObject(target_name), target_sub)
    if line_edge is None:
        try:
            import Part
            line_edge = Part.Edge(Part.LineSegment(a_world, b_world))
        except Exception:
            line_edge = None

    if line_edge is None:
        return []

    hits = []
    for _param, point in _collect_target_edge_hits(doc, target_name, target_sub, line_edge, boundaries):
        hits.append((_line_parameter(a_world, b_world, point), point))

    unique = []
    for t, point in sorted(hits, key=lambda item: item[0]):
        if all(point.distanceToPoint(existing[1]) > 1e-6 for existing in unique):
            unique.append((t, point))
    return unique


def _segment_circle_intersections(center, radius, a, b, infinite_line=False):
    dx = b.x - a.x
    dy = b.y - a.y
    fx = a.x - center.x
    fy = a.y - center.y

    qa = dx * dx + dy * dy
    if qa < 1e-12:
        return []

    qb = 2.0 * (fx * dx + fy * dy)
    qc = fx * fx + fy * fy - radius * radius
    disc = qb * qb - 4.0 * qa * qc
    if disc < -1e-9:
        return []

    disc = max(0.0, disc)
    root = math.sqrt(disc)
    hits = []
    for sign in (-1.0, 1.0):
        t = (-qb + sign * root) / (2.0 * qa)
        if infinite_line or (-1e-6 <= t <= 1.0 + 1e-6):
            hits.append(App.Vector(a.x + t * dx, a.y + t * dy, center.z))
    return _dedupe_points(hits)


def _normalize_angle(angle):
    return angle % 360.0


def _point_angle(center, point):
    return _normalize_angle(math.degrees(math.atan2(point.y - center.y, point.x - center.x)))


def _angle_between(angle, start, end):
    angle = _normalize_angle(angle)
    start = _normalize_angle(start)
    end = _normalize_angle(end)
    span = (end - start) % 360.0
    return ((angle - start) % 360.0) <= span + 1e-6


def _trim_circle_target(doc, target_name, target_sub, obj, target_info, pick_world, boundaries):
    target_edge = _get_shape_edge(obj, target_sub)
    if not target_edge:
        return False, 'Circle trimming is not supported for this object type.'

    intersections = _collect_target_edge_hits(doc, target_name, target_sub, target_edge, boundaries)
    if not intersections:
        return False, 'No cutting edge intersects the selected circle/arc.'

    low, high = _parameter_bounds(target_edge)
    pick_param = _edge_parameter(target_edge, pick_world)
    if pick_param is None:
        pick_param = low

    try:
        is_closed = bool(target_edge.isClosed())
    except Exception:
        is_closed = len(getattr(target_edge, 'Vertexes', []) or []) <= 1

    endpoint_tol = 1e-6
    low_hit = any(abs(param - low) <= endpoint_tol for param, _point in intersections)
    high_hit = any(abs(param - high) <= endpoint_tol for param, _point in intersections)
    inner = [(param, point) for param, point in intersections if low + 1e-6 < param < high - 1e-6]

    if is_closed:
        if len(inner) < 2:
            return False, 'Need two intersections to trim that circle.'

        period = max(1e-9, high - low)
        pick_norm = (pick_param - low) % period
        cyclic = sorted((((param - low) % period), point) for param, point in inner)

        seg_index = len(cyclic) - 1
        for idx in range(len(cyclic)):
            start_norm = cyclic[idx][0]
            end_norm = cyclic[(idx + 1) % len(cyclic)][0]
            value = pick_norm
            if idx == len(cyclic) - 1:
                end_norm += period
                if value < start_norm:
                    value += period
            if start_norm - 1e-6 <= value <= end_norm + 1e-6:
                seg_index = idx
                break

        remove_start = cyclic[seg_index][1]
        remove_end = cyclic[(seg_index + 1) % len(cyclic)][1]

        if hasattr(obj, 'MakeFace'):
            obj.MakeFace = False
        if not hasattr(obj, 'FirstAngle') or not hasattr(obj, 'LastAngle'):
            return False, 'Circle trimming is not supported for this object type.'

        obj.FirstAngle = _circle_local_angle(obj, remove_end)
        obj.LastAngle = _circle_local_angle(obj, remove_start)
        return True, None

    if not inner:
        if low_hit and high_hit:
            if _remove_object(doc, obj):
                return True, None
            return False, 'Could not remove the trimmed arc.'
        return False, 'No cutting edge intersects the selected arc.'

    pick_param = max(low, min(high, pick_param))
    params = [low] + [param for param, _point in inner] + [high]

    seg_index = len(params) - 2
    for idx in range(len(params) - 1):
        if params[idx] - 1e-6 <= pick_param <= params[idx + 1] + 1e-6:
            seg_index = idx
            break

    keep_ranges = []
    if seg_index == 0:
        keep_ranges.append((params[1], high))
    elif seg_index == len(params) - 2:
        keep_ranges.append((low, params[-2]))
    else:
        keep_ranges.append((low, params[seg_index]))
        keep_ranges.append((params[seg_index + 1], high))

    pieces = [piece for piece in (_make_edge_piece(target_edge, start, end) for start, end in keep_ranges) if piece]
    if not pieces:
        return False, 'Could not rebuild the trimmed arc.'

    if not _apply_circle_piece(obj, pieces[0]):
        return False, 'Could not rebuild the trimmed arc.'

    if len(pieces) > 1 and not _make_circle_piece_copy(obj, pieces[1]):
        return False, 'Could not rebuild the split arc.'

    return True, None


def _trim_line_target(doc, target_name, target_sub, obj, target_info, pick_world, boundaries):
    intersections = _find_line_intersections(doc, target_name, target_sub, target_info, boundaries)
    if not intersections:
        return False, 'No valid cutting edge found for that side.'

    a_world = target_info['a_world']
    b_world = target_info['b_world']
    pick_t = _line_parameter(a_world, b_world, pick_world)
    inner = [(t, point) for t, point in intersections if -1e-6 <= t <= 1.0 + 1e-6]
    inner.sort(key=lambda item: item[0])

    if not inner:
        return False, 'No cutting edge intersects the selected object.'

    params = [0.0] + [t for t, _ in inner] + [1.0]
    points = [a_world] + [point for _, point in inner] + [b_world]
    pick_t = max(0.0, min(1.0, pick_t))

    seg_index = len(params) - 2
    for idx in range(len(params) - 1):
        if params[idx] - 1e-6 <= pick_t <= params[idx + 1] + 1e-6:
            seg_index = idx
            break

    left_point = points[seg_index]
    right_point = points[seg_index + 1]

    # Clicked segment touches an end: simple trim of that end.
    if seg_index == 0:
        _apply_target_point(obj, target_info, right_point, pick_world)
        return True, None
    if seg_index == len(points) - 2:
        _apply_target_point(obj, target_info, left_point, pick_world)
        return True, None

    _set_segment_on_object(obj, target_info, a_world, left_point)
    _make_line_copy(obj, right_point, b_world)
    return True, None


def _find_best_intersection(doc, target_name, target_sub, target_info, pick_world, boundaries, mode):
    if not doc or not boundaries or target_info.get('kind') == 'circle':
        return None

    a_world = target_info['a_world']
    b_world = target_info['b_world']
    end_index = _choose_endpoint(a_world, b_world, pick_world, a_world)
    best_score = None
    best_point = None
    eps = 1e-6

    line_edge = _get_shape_edge(doc.getObject(target_name), target_sub)
    if line_edge is None:
        try:
            import Part
            line_edge = Part.Edge(Part.LineSegment(a_world, b_world))
        except Exception:
            line_edge = None

    if line_edge is None:
        return None

    for _param, intersection in _collect_target_edge_hits(doc, target_name, target_sub, line_edge, boundaries, infinite_target=True):
        t = _line_parameter(a_world, b_world, intersection)
        if mode == 'TRIM':
            if end_index == 0:
                if not (eps < t <= 1.0 + eps):
                    continue
                score = abs(t)
            else:
                if not (-eps <= t < 1.0 - eps):
                    continue
                score = abs(1.0 - t)
        else:
            if end_index == 0:
                if not (t < -eps):
                    continue
                score = abs(t)
            else:
                if not (t > 1.0 + eps):
                    continue
                score = abs(t - 1.0)

        if best_score is None or score < best_score:
            best_score = score
            best_point = intersection

    return best_point


class TrimExtendHandler:
    def __init__(self, console, mode):
        self.console = console
        self.mode = (mode or 'TRIM').upper()
        self.step = 0
        self.boundaries = []
        self.last_sel_time = 0.0
        self._last_sel_key = None
        self._txn_open = False

        preselected = []
        try:
            preselected = list(Gui.Selection.getSelectionEx())
        except Exception:
            preselected = []

        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)
        Gui.ccad_trim_handler = self

        self._collect_selected_boundaries(preselected)

        if self.boundaries:
            self.step = 1
            self.console.history.append(
                f"<span style='color:#aaa;'>{self.mode}: Using {len(self.boundaries)} preselected cutting edge(s).</span>"
            )

        self._prompt()

    def _prompt(self):
        if self.step == 0:
            count = len(self.boundaries)
            suffix = f" ({count} selected)" if count else ""
            self.console.history.append(
                f"<span style='color:#aaa;'>{self.mode}: Select cutting edges{suffix}. Press Enter when done or Esc to cancel.</span>"
            )
        elif self.step == 1:
            verb = 'trim' if self.mode == 'TRIM' else 'extend'
            self.console.history.append(
                f"<span style='color:#aaa;'>{self.mode}: Select object to {verb}. Click more objects to continue; press Enter or Esc to finish.</span>"
            )

    def _add_boundary(self, obj_name, subname, silent=False):
        key = _boundary_key(obj_name, subname)
        for boundary in self.boundaries:
            if _boundary_key(boundary['obj_name'], boundary['sub']) == key:
                return False

        self.boundaries.append({'obj_name': obj_name, 'sub': subname})
        if not silent:
            self.console.history.append(
                f"<span style='color:#55ff55;'>{self.mode}: Cutting edge added ({len(self.boundaries)} total).</span>"
            )
        return True

    def _collect_selected_boundaries(self, selection=None):
        added = 0
        try:
            current = list(selection) if selection is not None else list(Gui.Selection.getSelectionEx())
        except Exception:
            current = []

        for sel in current:
            obj = getattr(sel, 'Object', None)
            obj_name = getattr(sel, 'ObjectName', None)
            if not obj_name:
                continue
            subnames = list(getattr(sel, 'SubElementNames', []) or _expand_boundary_subnames(obj))
            for subname in subnames:
                if 'Edge' in str(subname):
                    names = [str(subname)]
                else:
                    names = _expand_boundary_subnames(obj, subname)
                for name in names:
                    if self._add_boundary(obj_name, name, silent=True):
                        added += 1
        return added

    def _on_input(self):
        text = self.console.input.text().strip().upper()
        self.console.input.clear()

        if text in ('C', 'CANCEL'):
            self.console.history.append(
                f"<span style='color:#aaa;'>{self.mode}: Cancelled</span>"
            )
            self.cleanup()
            return True

        if self.step == 0:
            if text == '':
                self._collect_selected_boundaries()
                if not self.boundaries:
                    self.console.history.append(
                        f"<span style='color:#ff5555;'>{self.mode}: Select at least one cutting edge first.</span>"
                    )
                else:
                    self.step = 1
                    try:
                        Gui.Selection.clearSelection()
                    except Exception:
                        pass
                    self._prompt()
                return True
            return False

        if self.step == 1 and text == '':
            self.console.history.append(
                f"<span style='color:#aaa;'>{self.mode}: Finished</span>"
            )
            self.cleanup()
            return True

        return False

    def _open_transaction(self, name='Trim/extend'):
        doc = App.ActiveDocument
        if doc and not self._txn_open:
            try:
                doc.openTransaction(name)
                self._txn_open = True
            except Exception:
                self._txn_open = False

    def _commit_transaction(self):
        doc = App.ActiveDocument
        if doc and self._txn_open:
            try:
                doc.commitTransaction()
            except Exception:
                pass
        self._txn_open = False

    def _abort_transaction(self):
        doc = App.ActiveDocument
        if doc and self._txn_open:
            try:
                doc.abortTransaction()
            except Exception:
                pass
        self._txn_open = False

    def addSelection(self, doc, obj_name, sub, pnt):
        now = time.time()
        subnames = [str(sub)] if sub and 'Edge' in str(sub) else _expand_boundary_subnames(App.ActiveDocument.getObject(obj_name) if App.ActiveDocument else None, sub)
        subname = subnames[0] if subnames else 'Edge1'
        sel_key = (str(obj_name), str(subname), int(self.step))
        if self._last_sel_key == sel_key and (now - self.last_sel_time) < 0.15:
            return
        self.last_sel_time = now
        self._last_sel_key = sel_key

        pick = parse_vector(pnt) or App.Vector(0, 0, 0)

        if self.step == 0:
            for boundary_sub in subnames:
                self._add_boundary(obj_name, boundary_sub)
            return

        if self.step == 1:
            QtCore.QTimer.singleShot(
                40,
                lambda name=obj_name, edge=subname, picked=pick: self._execute_target(name, edge, picked),
            )
            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass

    def removeSelection(self, doc, obj_name, sub):
        pass

    def setSelection(self, doc):
        pass

    def clearSelection(self, doc):
        pass

    def _execute_target(self, target_name, target_sub, target_pick):
        doc = App.ActiveDocument
        target = doc.getObject(target_name) if doc else None

        if not target or not self.boundaries:
            self.console.history.append(
                f"<span style='color:#ff5555;'>{self.mode}: Invalid selection.</span>"
            )
            return

        target_info = _get_target_info(target, target_sub)
        if not target_info:
            self.console.history.append(
                f"<span style='color:#ff5555;'>{self.mode}: Only lines, wires, arcs/circles, splines, bezier curves, and sketches are supported.</span>"
            )
            return

        try:
            self._open_transaction('Trim/extend')

            if self.mode == 'TRIM':
                if target_info.get('kind') == 'wire':
                    ok, error = _trim_wire_target(doc, target_name, target_sub, target, target_pick, self.boundaries)
                elif target_info.get('kind') == 'circle':
                    ok, error = _trim_circle_target(doc, target_name, target_sub, target, target_info, target_pick, self.boundaries)
                elif target_info.get('kind') == 'shape_edge':
                    ok, error = _trim_shape_edge_target(doc, target_name, target_sub, target, target_info, target_pick, self.boundaries)
                else:
                    ok, error = _trim_line_target(doc, target_name, target_sub, target, target_info, target_pick, self.boundaries)
            else:
                if target_info.get('kind') in ('wire', 'shape_edge', 'circle'):
                    ok, error = False, 'Extend is currently supported only for line-like objects.'
                else:
                    intersection = _find_best_intersection(
                        doc,
                        target_name,
                        target_sub,
                        target_info,
                        target_pick,
                        self.boundaries,
                        self.mode,
                    )
                    if intersection:
                        _apply_target_point(target, target_info, intersection, target_pick)
                        ok, error = True, None
                    else:
                        ok, error = False, 'No valid cutting edge found for that side.'

            if not ok:
                self._abort_transaction()
                self.console.history.append(
                    f"<span style='color:#ff5555;'>{self.mode}: {error}</span>"
                )
                return

            doc.recompute()
            self._commit_transaction()
            self.console.history.append(
                f"<span style='color:#55ff55;'>{self.mode}: Done</span>"
            )
        except Exception as exc:
            self._abort_transaction()
            self.console.history.append(
                f"<span style='color:#ff5555;'>{self.mode} Error: {str(exc)}</span>"
            )

    def cleanup(self, clear_selection=True):
        try:
            Gui.Selection.removeObserver(self)
        except Exception:
            pass
        self._abort_transaction()
        if clear_selection:
            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass
        Gui.ccad_trim_handler = None

    def _cleanup(self):
        self.cleanup()


def run(console, mode):
    if hasattr(Gui, 'ccad_trim_handler') and Gui.ccad_trim_handler:
        try:
            Gui.ccad_trim_handler.cleanup()
        except Exception:
            pass
    TrimExtendHandler(console, mode)