"""OFFSET command with ClassicCAD prompt flow and XLINE support."""

import FreeCAD as App
import FreeCADGui as Gui
import Draft
import DraftVecUtils
from PySide6 import QtCore, QtGui, QtWidgets

import ccad_cmd_xline
import ccad_layers

try:
    import DraftGeomUtils
except Exception:
    DraftGeomUtils = None

try:
    from draftutils import utils as draft_utils
except Exception:
    draft_utils = None

try:
    from draftguitools import gui_trackers as draft_trackers
except Exception:
    draft_trackers = None


_PREF_GROUP = 'User parameter:BaseApp/Preferences/Mod/ClassicCAD'
_OFFSET_DISTANCE_KEY = 'OffsetDistance'
_DRAFT_PREF_GROUP = 'User parameter:BaseApp/Preferences/Mod/Draft'
_DRAFT_OCC_KEY = 'Offset_OCC'
_OFFSET_DEFAULT_STATE_ATTR = 'ccad_offset_default_state'


def _prefs():
    return App.ParamGet(_PREF_GROUP)


def _draft_prefs():
    return App.ParamGet(_DRAFT_PREF_GROUP)


def _offset_default_state():
    state = getattr(Gui, _OFFSET_DEFAULT_STATE_ATTR, None)
    if isinstance(state, dict):
        return state

    state = {
        'distance': None,
        'locked': False,
    }
    try:
        setattr(Gui, _OFFSET_DEFAULT_STATE_ATTR, state)
    except Exception:
        pass
    return state


def _default_offset_distance():
    state = _offset_default_state()
    distance = state.get('distance')
    if state.get('locked') and distance is not None:
        try:
            value = float(distance)
        except Exception:
            value = None
        if value is not None and value > 1e-7:
            return value

    try:
        value = float(_prefs().GetFloat(_OFFSET_DISTANCE_KEY, 0.0))
    except Exception:
        value = 0.0

    if value > 1e-7:
        state['distance'] = value
        state['locked'] = True
        return value

    state['distance'] = None
    state['locked'] = False
    return None


def _lock_default_offset_distance(distance):
    state = _offset_default_state()
    try:
        value = float(distance)
    except Exception:
        return state.get('distance')

    if value <= 1e-7:
        return state.get('distance')

    state['distance'] = value
    state['locked'] = True
    try:
        _prefs().SetFloat(_OFFSET_DISTANCE_KEY, value)
    except Exception:
        pass
    return value


def _load_offset_distance():
    return _default_offset_distance()


def _save_offset_distance(distance):
    return _lock_default_offset_distance(distance)


def _load_occ_mode():
    try:
        return bool(_draft_prefs().GetBool(_DRAFT_OCC_KEY, False))
    except Exception:
        return False


def _format_length_value(value):
    try:
        quantity = App.Units.Quantity(float(value), App.Units.Length)
        text = str(getattr(quantity, 'UserString', '') or '').strip()
        if text:
            return text
        return f"{float(value):g}"
    except Exception:
        return '0'


def _msg(console, text, color='#aaa'):
    if console and hasattr(console, 'history'):
        console.history.append(f"<span style='color:{color};'>{text}</span>")
        try:
            console.history.moveCursor(QtGui.QTextCursor.End)
        except Exception:
            pass
    else:
        App.Console.PrintMessage(text + "\n")


def _draft_type(obj):
    if obj is None:
        return ''
    if draft_utils is not None:
        try:
            return str(draft_utils.get_type(obj) or '')
        except Exception:
            pass
    return str(getattr(obj, 'TypeId', '') or '')


def _copy_view_style(source, target):
    if source is None or target is None:
        return
    try:
        src_view = getattr(source, 'ViewObject', None)
        dst_view = getattr(target, 'ViewObject', None)
        if not src_view or not dst_view:
            return
        for attr in ('LineColor', 'LineWidth', 'DrawStyle', 'PointColor', 'PointSize', 'DisplayMode'):
            if hasattr(src_view, attr) and hasattr(dst_view, attr):
                setattr(dst_view, attr, getattr(src_view, attr))
    except Exception:
        pass


def _preserve_source_layer(source, result):
    if result is None:
        return
    layer = ccad_layers.get_object_layer(source)
    if layer:
        try:
            ccad_layers.assign_to_layer(result, layer)
        except Exception:
            pass
    _copy_view_style(source, result)


def _make_offset_feature(shape):
    doc = App.ActiveDocument
    if doc is None or shape is None:
        return None
    try:
        obj = doc.addObject('Part::Feature', 'Offset')
        obj.Shape = shape
        return obj
    except Exception:
        return None


def _wire_points_from_shape(shape):
    if shape is None:
        return None, False

    if DraftGeomUtils is not None:
        try:
            points = [
                ccad_cmd_xline._coerce_vector(point)
                for point in (DraftGeomUtils.getVerts(shape) or [])
            ]
            points = [point for point in points if point is not None]
            if len(points) >= 2:
                try:
                    closed = bool(shape.isClosed())
                except Exception:
                    closed = False
                if closed and points[0].distanceToPoint(points[-1]) <= 1e-7:
                    points = points[:-1]
                if len(points) >= 2:
                    return points, closed
        except Exception:
            pass

    candidates = []
    try:
        candidates.extend(list(getattr(shape, 'Wires', []) or []))
    except Exception:
        pass
    candidates.append(shape)

    for candidate in candidates:
        try:
            ordered = list(getattr(candidate, 'OrderedVertexes', []) or [])
        except Exception:
            ordered = []
        if not ordered:
            continue

        points = []
        for vertex in ordered:
            point = ccad_cmd_xline._coerce_vector(getattr(vertex, 'Point', None))
            if point is not None:
                points.append(point)

        if len(points) < 2:
            continue

        try:
            closed = bool(candidate.isClosed())
        except Exception:
            closed = False

        if closed and points[0].distanceToPoint(points[-1]) <= 1e-7:
            points = points[:-1]

        if len(points) >= 2:
            return points, closed

    return None, False


def _make_offset_wire(shape):
    points, closed = _wire_points_from_shape(shape)
    if not points or len(points) < 2:
        return None
    try:
        return Draft.make_wire(points, closed=closed, face=False)
    except Exception:
        return None


def _edge_preview_points(edge, samples=24):
    if edge is None:
        return []

    try:
        verts = list(getattr(edge, 'Vertexes', []) or [])
    except Exception:
        verts = []

    if ccad_cmd_xline._edge_direction(edge) is not None and len(verts) >= 2:
        start = ccad_cmd_xline._coerce_vector(verts[0].Point)
        end = ccad_cmd_xline._coerce_vector(verts[-1].Point)
        return [point for point in (start, end) if point is not None]

    try:
        first = float(edge.FirstParameter)
        last = float(edge.LastParameter)
    except Exception:
        first = None
        last = None

    if first is None or last is None or abs(last - first) <= 1e-9:
        return [ccad_cmd_xline._coerce_vector(getattr(vertex, 'Point', None)) for vertex in verts]

    points = []
    for index in range(max(2, int(samples))):
        try:
            parameter = first + ((last - first) * float(index) / float(max(1, samples - 1)))
            point = ccad_cmd_xline._coerce_vector(edge.valueAt(parameter))
        except Exception:
            point = None
        if point is not None:
            points.append(point)
    return points


def _shape_preview_parts(shape):
    if shape is None:
        return []

    points, closed = _wire_points_from_shape(shape)
    if points and len(points) >= 2:
        if closed and points[0].distanceToPoint(points[-1]) > 1e-7:
            points = list(points) + [points[0]]
        return [points]

    try:
        wires = list(getattr(shape, 'Wires', []) or [])
    except Exception:
        wires = []
    if not wires:
        wires = [shape]

    direct_parts = []
    for wire in wires:
        points, closed = _wire_points_from_shape(wire)
        if points and len(points) >= 2:
            if closed and points[0].distanceToPoint(points[-1]) > 1e-7:
                points = list(points) + [points[0]]
            direct_parts.append(points)
    if direct_parts:
        return direct_parts

    parts = []
    for wire in wires:
        try:
            wire_closed = bool(wire.isClosed())
        except Exception:
            wire_closed = False
        try:
            edges = list(getattr(wire, 'Edges', []) or [])
        except Exception:
            edges = []
        if not edges:
            points, closed = _wire_points_from_shape(wire)
            if points and len(points) >= 2:
                if closed and points[0].distanceToPoint(points[-1]) > 1e-7:
                    points = list(points) + [points[0]]
                parts.append(points)
            continue

        current = []
        for edge in edges:
            edge_points = [point for point in _edge_preview_points(edge) if point is not None]
            if len(edge_points) < 2:
                continue
            if current and current[-1].distanceToPoint(edge_points[0]) <= 1e-6:
                current.extend(edge_points[1:])
            else:
                if len(current) >= 2:
                    parts.append(current)
                current = list(edge_points)
        if wire_closed and len(current) >= 2 and current[0].distanceToPoint(current[-1]) > 1e-7:
            current.append(current[0])
        if len(current) >= 2:
            parts.append(current)
    return parts


def _circle_preview_parts(edge, center, target_radius, samples=48):
    center = ccad_cmd_xline._coerce_vector(center)
    if edge is None or center is None or target_radius is None or target_radius <= 1e-7:
        return []

    try:
        first = float(edge.FirstParameter)
        last = float(edge.LastParameter)
    except Exception:
        first = 0.0
        last = 6.283185307179586

    points = []
    steps = max(12, int(samples))
    for index in range(steps):
        try:
            parameter = first + ((last - first) * float(index) / float(max(1, steps - 1)))
            base_point = ccad_cmd_xline._coerce_vector(edge.valueAt(parameter))
        except Exception:
            base_point = None
        if base_point is None:
            continue
        radial = base_point - center
        if radial.Length <= 1e-7:
            continue
        radial.normalize()
        points.append(center + (radial * float(target_radius)))

    return [points] if len(points) >= 2 else []


def _qpoint_distance(a, b):
    if a is None or b is None:
        return None
    dx = float(a.x() - b.x())
    dy = float(a.y() - b.y())
    return (dx * dx + dy * dy) ** 0.5


def _point_segment_distance(point, start, end):
    if point is None or start is None or end is None:
        return None

    px = float(point.x())
    py = float(point.y())
    x1 = float(start.x())
    y1 = float(start.y())
    x2 = float(end.x())
    y2 = float(end.y())

    dx = x2 - x1
    dy = y2 - y1
    if abs(dx) <= 1e-9 and abs(dy) <= 1e-9:
        return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5

    t = ((px - x1) * dx + (py - y1) * dy) / float((dx * dx) + (dy * dy))
    t = max(0.0, min(1.0, t))
    proj_x = x1 + (t * dx)
    proj_y = y1 + (t * dy)
    return ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5


def _preview_parts_screen_distance(parts, viewport, pos):
    if not parts or viewport is None or pos is None:
        return None

    view = Gui.activeView()
    if not view:
        return None

    cursor = QtCore.QPoint(pos)
    best = None
    for part in parts:
        qpart = []
        for point in part:
            qpoint = ccad_cmd_xline._world_to_qpoint(view, viewport, point)
            if qpoint is not None:
                qpart.append(qpoint)
        if not qpart:
            continue

        for qpoint in qpart:
            distance = _qpoint_distance(cursor, qpoint)
            if distance is not None and (best is None or distance < best):
                best = distance

        for index in range(len(qpart) - 1):
            distance = _point_segment_distance(cursor, qpart[index], qpart[index + 1])
            if distance is not None and (best is None or distance < best):
                best = distance

    return best


def _shape_area_metric(shape):
    if shape is None:
        return None
    try:
        area = abs(float(getattr(shape, 'Area', 0.0) or 0.0))
        if area > 1e-9:
            return area
    except Exception:
        pass

    try:
        bbox = getattr(shape, 'BoundBox', None)
        if bbox and bbox.isValid():
            width = abs(float(bbox.XMax) - float(bbox.XMin))
            height = abs(float(bbox.YMax) - float(bbox.YMin))
            area = width * height
            if area > 1e-9:
                return area
    except Exception:
        pass
    return None


def _point_in_polygon_xy(points, point):
    if not points or len(points) < 3 or point is None:
        return None

    x = float(point.x)
    y = float(point.y)
    inside = False
    count = len(points)
    for index in range(count):
        p1 = points[index]
        p2 = points[(index + 1) % count]
        x1 = float(p1.x)
        y1 = float(p1.y)
        x2 = float(p2.x)
        y2 = float(p2.y)

        if abs(y2 - y1) <= 1e-12:
            continue

        intersects = ((y1 > y) != (y2 > y))
        if not intersects:
            continue

        x_at_y = x1 + ((y - y1) * (x2 - x1) / (y2 - y1))
        if x < x_at_y:
            inside = not inside

    return inside


def _wire_source_contains_point(shape, point):
    if shape is None or point is None:
        return None

    try:
        if not bool(shape.isClosed()):
            return None
    except Exception:
        return None

    points, _closed = _wire_points_from_shape(shape)
    if not points or len(points) < 3:
        return None
    return _point_in_polygon_xy(points, point)


class OffsetPreviewOverlay(QtWidgets.QWidget):
    def __init__(self, viewport):
        super().__init__(viewport)
        self.viewport = viewport
        self._parts = []
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self._sync_geometry()
        viewport.installEventFilter(self)
        self.show()
        self.raise_()

    def _sync_geometry(self):
        if self.viewport is None:
            return
        try:
            self.setGeometry(self.viewport.rect())
        except Exception:
            pass

    def eventFilter(self, obj, event):
        if obj is self.viewport and event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Show, QtCore.QEvent.Move):
            self._sync_geometry()
            self.update()
        return False

    def set_parts(self, parts):
        self._parts = list(parts or [])
        self.raise_()
        self.update()

    def clear(self):
        self._parts = []
        self.update()

    def cleanup(self):
        try:
            self.viewport.removeEventFilter(self)
        except Exception:
            pass
        self.deleteLater()

    def paintEvent(self, event):
        if not self._parts:
            return

        view = Gui.activeView()
        if not view:
            return

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(ccad_cmd_xline._current_preview_pen())

        for part in self._parts:
            qpart = []
            for point in part:
                qpoint = ccad_cmd_xline._world_to_qpoint(view, self.viewport, point)
                if qpoint is not None:
                    qpart.append(qpoint)
            if len(qpart) < 2:
                continue
            if len(qpart) == 2:
                painter.drawLine(qpart[0], qpart[1])
            else:
                painter.drawPolyline(QtGui.QPolygon(qpart))

        painter.end()


def _is_circular_edge(edge):
    curve = getattr(edge, 'Curve', None)
    return bool(curve and hasattr(curve, 'Center') and hasattr(curve, 'Radius'))


def _is_straight_edge(edge):
    if edge is None:
        return False
    direction = ccad_cmd_xline._edge_direction(edge)
    if direction is None:
        return False
    try:
        verts = list(edge.Vertexes or [])
        if len(verts) < 2:
            return False
        start = ccad_cmd_xline._coerce_vector(verts[0].Point)
        end = ccad_cmd_xline._coerce_vector(verts[-1].Point)
        if start is None or end is None:
            return False
        midpoint = ccad_cmd_xline._coerce_vector(
            edge.valueAt((float(edge.FirstParameter) + float(edge.LastParameter)) * 0.5)
        )
        if midpoint is None:
            return True
        return midpoint.distanceToPoint((start + end) * 0.5) <= max(1e-6, (end - start).Length * 1e-6)
    except Exception:
        return True


def _first_edge(obj):
    try:
        edges = list(getattr(getattr(obj, 'Shape', None), 'Edges', []) or [])
    except Exception:
        edges = []
    return edges[0] if edges else None


def _build_source(obj, edge=None, preferred_point=None):
    if obj is None:
        return None

    shape = getattr(obj, 'Shape', None)
    edges = list(getattr(shape, 'Edges', []) or [])
    if edge is None:
        edge = _first_edge(obj)

    if ccad_cmd_xline.is_xline(obj):
        midpoint, direction = ccad_cmd_xline._xline_definition(obj)
        if midpoint is None or direction is None:
            return None
        return {
            'kind': 'xline',
            'object': obj,
            'point': midpoint,
            'direction': direction,
        }

    draft_type = _draft_type(obj)
    if draft_type in ('BSpline', 'BezCurve'):
        return {
            'kind': 'native',
            'object': obj,
        }

    if edge is not None and _is_circular_edge(edge):
        curve = edge.Curve
        return {
            'kind': 'circle',
            'object': obj,
            'edge': edge,
            'center': ccad_cmd_xline._coerce_vector(curve.Center),
            'radius': float(curve.Radius),
        }

    if len(edges) == 1 and edge is not None and _is_straight_edge(edge):
        verts = list(edge.Vertexes or [])
        if len(verts) < 2:
            return None
        start = ccad_cmd_xline._coerce_vector(verts[0].Point)
        end = ccad_cmd_xline._coerce_vector(verts[-1].Point)
        direction = ccad_cmd_xline._edge_direction(edge)
        if start is None or end is None or direction is None:
            return None
        return {
            'kind': 'linear',
            'object': obj,
            'edge': edge,
            'point': ccad_cmd_xline._edge_anchor(edge, preferred_point),
            'direction': direction,
            'start': start,
            'end': end,
        }

    if len(edges) > 1:
        return {
            'kind': 'wire',
            'object': obj,
            'shape': shape,
        }

    return {
        'kind': 'native',
        'object': obj,
    }


def _start_transaction(name):
    doc = App.ActiveDocument
    if not doc or not hasattr(doc, 'openTransaction'):
        return None
    try:
        doc.openTransaction(name)
        return doc
    except Exception:
        return None


def _commit_transaction(doc, result=None):
    if not doc:
        return
    try:
        if result is not None:
            try:
                doc.recompute([result])
            except Exception:
                doc.recompute()
        elif hasattr(doc, 'recompute'):
            doc.recompute()
    finally:
        try:
            if hasattr(doc, 'commitTransaction'):
                doc.commitTransaction()
        except Exception:
            pass


def _abort_transaction(doc):
    if not doc:
        return
    try:
        if hasattr(doc, 'abortTransaction'):
            doc.abortTransaction()
    except Exception:
        pass


def _launch_native_offset(obj, console=None):
    if obj is None:
        _msg(console, 'OFFSET: Unsupported object type', color='#ff5555')
        return False
    try:
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj)
    except Exception:
        pass
    try:
        Gui.getMainWindow().setFocus()
    except Exception:
        pass
    try:
        Gui.runCommand('Draft_Offset')
    except TypeError:
        Gui.runCommand('Draft_Offset', 0)
    _msg(console, 'OFFSET: Switched to native Draft Offset for this object type')
    return True


def _raw_view_point(pos):
    raw = ccad_cmd_xline._qpoint_to_raw(pos)
    try:
        view = Gui.activeView()
        if view:
            return ccad_cmd_xline._coerce_vector(view.getPoint(raw[0], raw[1]))
    except Exception:
        pass
    return None


def _selected_source_for_distance(distance):
    if distance is None:
        return None

    try:
        selected = list(Gui.Selection.getSelection() or [])
    except Exception:
        selected = []

    if len(selected) != 1:
        return None

    obj = selected[0]
    source = _build_source(obj)
    if source is None:
        return None
    if source.get('kind') == 'native':
        return None
    return source


class OffsetPickHandler(QtCore.QObject):
    def __init__(self, console, viewport, source=None):
        super().__init__()
        self.console = console
        self.viewport = viewport
        self.source = None
        self.default_distance = _load_offset_distance()
        self.distance = self.default_distance
        self.occ_mode = _load_occ_mode()
        self._stage = 'distance'
        self._hover_point = None
        self._hover_mode = None
        self._hover_pos = None
        self._native_through = False
        self._preview_candidate = None
        self._preview_pos = None
        self._preview = OffsetPreviewOverlay(viewport) if viewport else None
        self._wire_tracker = None

        Gui.ccad_offset_handler = self
        if self.viewport:
            try:
                self.viewport.setMouseTracking(True)
            except Exception:
                pass
            self.viewport.installEventFilter(self)

        try:
            self.console.input.returnPressed.disconnect()
        except Exception:
            pass
        self.console.input.returnPressed.connect(self._on_input)

        finder = getattr(Gui, 'ccad_find_cursor', None)
        if callable(finder):
            try:
                finder()
            except Exception:
                pass

        self._msg(self._current_prompt())
        self._prime_preview()

    def _msg(self, text, ok=False, err=False):
        color = '#55ff55' if ok else '#ff5555' if err else '#aaa'
        _msg(self.console, text, color=color)

    def _distance_prompt(self):
        default = 'Through' if self.default_distance is None else _format_length_value(self.default_distance)
        return f'OFFSET: Specify offset distance or [Through] <{default}>'

    def _select_prompt(self):
        return 'OFFSET: Select object to offset'

    def _side_prompt(self):
        if self.distance is None:
            return 'OFFSET: Specify through point'
        return f'OFFSET: Specify side to offset <{_format_length_value(self.distance)}>'

    def _current_prompt(self):
        if self._stage == 'distance':
            return self._distance_prompt()
        if self._stage == 'source':
            return self._select_prompt()
        return self._side_prompt()

    def _source_name(self):
        obj = self.source.get('object') if self.source else None
        if obj is None:
            return 'object'
        return getattr(obj, 'Label', None) or getattr(obj, 'Name', None) or 'object'

    def _on_input(self):
        raw_text = self.console.input.text().strip()
        text = raw_text.upper()
        self.console.input.clear()

        if not text:
            if self._stage == 'distance':
                self.distance = self.default_distance
                self._stage = 'source'
            self._msg(self._current_prompt())
            return True

        if text in ('T', 'THROUGH'):
            self.distance = None
            self._native_through = True
            if self._stage == 'distance':
                self._stage = 'source'
            elif self._stage == 'side' and self.source and self.source.get('kind') != 'xline':
                obj = self.source.get('object')
                self.cleanup()
                _launch_native_offset(obj, console=self.console)
                return True
            self._msg(self._current_prompt())
            return True

        try:
            distance = ccad_cmd_xline._parse_length_value(raw_text)
        except ValueError:
            self._msg('OFFSET: Enter a positive distance or [Through]', err=True)
            return True

        saved_distance = _save_offset_distance(distance)
        self.default_distance = saved_distance if saved_distance is not None else distance
        self.distance = self.default_distance
        self._native_through = False
        if self._stage == 'distance':
            self._stage = 'source'
        self._msg(self._current_prompt())
        return True

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.MouseMove:
            pos = ccad_cmd_xline._screen_pos(event)
            self._hover_pos = QtCore.QPoint(pos)
            if self._stage == 'side':
                self._hover_point = None
                self._hover_mode = None
                self._update_side_preview(pos)
            else:
                point, mode = ccad_cmd_xline.get_snap_point(pos)
                self._hover_point = point
                self._hover_mode = mode
                self._clear_preview()
            cursor = getattr(Gui, 'ccad_cursor', None)
            if cursor:
                try:
                    cursor.update()
                except Exception:
                    pass
            return False

        if (
            event.type() == QtCore.QEvent.MouseButtonPress
            and event.button() == QtCore.Qt.LeftButton
        ):
            pos = ccad_cmd_xline._screen_pos(event)
            if self._stage == 'distance':
                self._msg(self._distance_prompt())
                return True
            if self._stage == 'source':
                point = self._click_point(pos)
                return self._choose_source(pos, point)
            preview = self._cached_preview_candidate(pos)
            if preview is not None:
                return self._apply_offset(preview=preview, pos=pos)
            point = _raw_view_point(pos)
            if point is None:
                self._msg('OFFSET: Could not determine side point', err=True)
                return True
            preview = self._preview_for_point(point)
            if preview is not None:
                return self._apply_offset(preview=preview, pos=pos)
            return self._apply_offset(point=point, pos=pos)

        if event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Escape:
            self._msg('OFFSET: Cancelled')
            self.cleanup()
            return True

        return False

    def _click_point(self, pos):
        if (
            self._hover_point is not None
            and self._hover_pos is not None
            and (self._hover_pos - pos).manhattanLength() <= 2
        ):
            return self._hover_point
        point, mode = ccad_cmd_xline.get_snap_point(pos)
        self._hover_point = point
        self._hover_mode = mode
        self._hover_pos = QtCore.QPoint(pos)
        return point

    def _prime_preview(self):
        if not self.viewport:
            return

        try:
            pos = self.viewport.mapFromGlobal(QtGui.QCursor.pos())
        except Exception:
            return

        try:
            if not self.viewport.rect().contains(pos):
                return
        except Exception:
            return

        if self._stage == 'side':
            self._update_side_preview(pos)
        else:
            point, mode = ccad_cmd_xline.get_snap_point(pos)
            self._hover_point = point
            self._hover_mode = mode
            self._hover_pos = QtCore.QPoint(pos)

        cursor = getattr(Gui, 'ccad_cursor', None)
        if cursor:
            try:
                cursor.update()
            except Exception:
                pass

    def _clear_preview(self):
        self._preview_candidate = None
        self._preview_pos = None
        if self._preview is not None:
            self._preview.clear()
        if self._wire_tracker is not None:
            try:
                self._wire_tracker.off()
            except Exception:
                pass

    def _cached_preview_candidate(self, pos):
        if self._preview_candidate is None or self._preview_pos is None:
            return None
        try:
            if (self._preview_pos - pos).manhattanLength() <= 2:
                return self._preview_candidate
        except Exception:
            pass
        return None

    def _preview_point(self, pos):
        point, mode = ccad_cmd_xline.get_snap_point(pos)
        if point is None:
            point = _raw_view_point(pos)
            mode = None
        self._hover_point = point
        self._hover_mode = mode
        self._hover_pos = QtCore.QPoint(pos) if pos is not None else None
        return point

    def _wire_preview_candidates(self, obj, delta):
        if obj is None or delta is None or DraftGeomUtils is None:
            return []

        candidates = []
        deltas = [delta]
        if self.distance is not None and delta.Length > 1e-7:
            deltas.append(App.Vector(-delta.x, -delta.y, -delta.z))

        seen = set()
        for candidate_delta in deltas:
            key = (
                round(float(candidate_delta.x), 6),
                round(float(candidate_delta.y), 6),
                round(float(candidate_delta.z), 6),
            )
            if key in seen:
                continue
            seen.add(key)

            try:
                offset_shape = DraftGeomUtils.offsetWire(obj.Shape, candidate_delta, occ=self.occ_mode)
            except Exception:
                offset_shape = None
            if offset_shape is None:
                continue

            parts = _shape_preview_parts(offset_shape)
            if not parts:
                continue

            candidates.append({
                'kind': 'wire',
                'delta': candidate_delta,
                'offset_shape': offset_shape,
                'parts': parts,
                'area_metric': _shape_area_metric(offset_shape),
            })

        return candidates

    def _choose_wire_preview(self, obj, point, pos, previews):
        if not previews:
            return None

        contains = _wire_source_contains_point(getattr(obj, 'Shape', None), point)
        source_metric = _shape_area_metric(getattr(obj, 'Shape', None))

        if contains is not None and source_metric is not None and len(previews) > 1:
            if contains:
                smaller = [preview for preview in previews if (preview.get('area_metric') or 0.0) < source_metric]
                if smaller:
                    return min(smaller, key=lambda preview: preview.get('area_metric') or source_metric)
            else:
                larger = [preview for preview in previews if (preview.get('area_metric') or 0.0) > source_metric]
                if larger:
                    return max(larger, key=lambda preview: preview.get('area_metric') or 0.0)

        return self._choose_closest_preview(previews, pos)

    def _choose_closest_preview(self, previews, pos):
        if not previews:
            return None
        if len(previews) == 1 or pos is None:
            return previews[0]

        best = None
        best_distance = None
        for preview in previews:
            distance = _preview_parts_screen_distance(preview.get('parts'), self.viewport, pos)
            if distance is None:
                continue
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best = preview
        return best or previews[0]

    def _wire_apply_candidate(self, point, pos=None):
        source = self.source or {}
        obj = source.get('object')
        delta = self._wire_delta(point)
        if delta is None:
            return None

        previews = self._wire_preview_candidates(obj, delta)
        if previews:
            chosen = self._choose_wire_preview(obj, point, pos, previews)
            if chosen is not None:
                return chosen

        return {
            'kind': 'wire',
            'delta': delta,
        }

    def _preview_for_point(self, point, pos=None):
        source = self.source or {}
        kind = source.get('kind')
        if kind == 'xline':
            base_point, direction = ccad_cmd_xline._offset_line_definition(
                source.get('point'),
                source.get('direction'),
                point,
                self.distance,
            )
            if base_point is None or direction is None:
                return None
            start, end = ccad_cmd_xline._xline_segment(base_point, direction)
            return {
                'kind': 'xline',
                'base_point': base_point,
                'direction': direction,
                'parts': [[start, end]],
            }

        if kind == 'linear':
            delta = self._linear_delta(point)
            start = ccad_cmd_xline._coerce_vector(source.get('start'))
            end = ccad_cmd_xline._coerce_vector(source.get('end'))
            if delta is None or start is None or end is None:
                return None
            return {
                'kind': 'linear',
                'delta': delta,
                'parts': [[start + delta, end + delta]],
            }

        if kind == 'circle':
            target_radius = self._circle_target_radius(point)
            edge = source.get('edge')
            center = source.get('center')
            if target_radius is None:
                return None
            return {
                'kind': 'circle',
                'target_radius': target_radius,
                'parts': _circle_preview_parts(edge, center, target_radius),
            }

        if kind == 'wire':
            return None

        return None

    def _update_side_preview(self, pos):
        point = self._preview_point(pos)
        if point is None:
            self._clear_preview()
            return
        preview = self._preview_for_point(point, pos=pos)
        self._preview_candidate = preview
        self._preview_pos = QtCore.QPoint(pos) if preview is not None else None
        if self._wire_tracker is not None:
            try:
                self._wire_tracker.off()
            except Exception:
                pass
        if self._preview is not None:
            self._preview.set_parts(preview.get('parts') if preview else [])

    def _choose_source(self, pos, point):
        obj, edge, click_point, info = ccad_cmd_xline._picked_edge(pos)
        if obj is None:
            self._msg('OFFSET: Click on an object to offset', err=True)
            return True

        source = _build_source(obj, edge=edge, preferred_point=click_point or point)
        if source is None:
            self._msg('OFFSET: Could not determine offset geometry', err=True)
            return True

        if self._native_through and source.get('kind') != 'xline':
            self.cleanup()
            _launch_native_offset(obj, console=self.console)
            return True

        if source.get('kind') == 'native':
            self.cleanup()
            _launch_native_offset(obj, console=self.console)
            return True

        self.source = source
        self._stage = 'side'
        self._clear_preview()
        if self._wire_tracker is not None:
            try:
                self._wire_tracker.finalize()
            except Exception:
                pass
            self._wire_tracker = None
        if source.get('kind') == 'wire' and draft_trackers is not None:
            try:
                self._wire_tracker = draft_trackers.wireTracker(source.get('shape'))
            except Exception:
                self._wire_tracker = None
        try:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(obj)
        except Exception:
            pass
        self._msg(f'OFFSET: {self._source_name()} selected. {self._side_prompt()}')
        self._prime_preview()
        return True

    def _linear_delta(self, point):
        anchor = ccad_cmd_xline._coerce_vector(self.source.get('point'))
        direction = ccad_cmd_xline._normalized_direction(self.source.get('direction'))
        point = ccad_cmd_xline._coerce_vector(point)
        if anchor is None or direction is None or point is None:
            return None
        normal = ccad_cmd_xline._normalized_direction(ccad_cmd_xline._perpendicular_2d(direction))
        if normal is None:
            return None
        signed = (point - anchor).dot(normal)
        if self.distance is None:
            distance = signed
        else:
            distance = -float(self.distance) if signed < 0.0 else float(self.distance)
        if abs(distance) <= 1e-7:
            return None
        return normal * distance

    def _wire_delta(self, point):
        if DraftGeomUtils is None:
            return None
        shape = self.source.get('shape')
        if shape is None:
            return None
        try:
            dist = DraftGeomUtils.findPerpendicular(point, shape.Edges)
        except Exception:
            dist = None
        if not dist:
            return None
        try:
            delta = dist[0].negative()
            edge_index = int(dist[1])
            v1 = DraftGeomUtils.getTangent(shape.Edges[0], point)
            v2 = DraftGeomUtils.getTangent(shape.Edges[edge_index], point)
            angle = -DraftVecUtils.angle(v1, v2, App.Vector(0, 0, 1))
            dvec = DraftVecUtils.rotate(delta, angle, App.Vector(0, 0, 1))
        except Exception:
            return None
        if dvec is None or dvec.Length <= 1e-7:
            return None
        if self.distance is None:
            return dvec
        dvec.normalize()
        dvec.multiply(float(self.distance))
        return dvec

    def _circle_target_radius(self, point):
        center = ccad_cmd_xline._coerce_vector(self.source.get('center'))
        radius = float(self.source.get('radius') or 0.0)
        point = ccad_cmd_xline._coerce_vector(point)
        if center is None or point is None or radius <= 1e-7:
            return None
        clicked_radius = (point - center).Length
        if self.distance is None:
            target = clicked_radius
        else:
            target = radius + float(self.distance) if clicked_radius >= radius else radius - float(self.distance)
        if target <= 1e-7:
            return None
        return target

    def _apply_offset(self, point=None, preview=None, pos=None):
        source = self.source or {}
        kind = source.get('kind')
        obj = source.get('object')
        if obj is None:
            self.cleanup()
            return True

        result = None
        transaction = _start_transaction('ClassicCAD Offset')
        try:
            if kind == 'xline':
                base_point = preview.get('base_point') if preview else None
                direction = preview.get('direction') if preview else None
                if base_point is None or direction is None:
                    base_point, direction = ccad_cmd_xline._offset_line_definition(
                        source.get('point'),
                        source.get('direction'),
                        point,
                        self.distance,
                    )
                if base_point is None or direction is None:
                    self._msg('OFFSET: Could not determine XLINE offset', err=True)
                    _abort_transaction(transaction)
                    return True
                result = ccad_cmd_xline._make_xline(base_point, direction)
            elif kind == 'linear':
                delta = preview.get('delta') if preview else None
                if delta is None:
                    delta = self._linear_delta(point)
                if delta is None:
                    self._msg('OFFSET: Could not determine offset side', err=True)
                    _abort_transaction(transaction)
                    return True
                start = ccad_cmd_xline._coerce_vector(source.get('start'))
                end = ccad_cmd_xline._coerce_vector(source.get('end'))
                result = Draft.make_wire([start + delta, end + delta], closed=False, face=False)
            elif kind == 'circle':
                target_radius = preview.get('target_radius') if preview else None
                if target_radius is None:
                    target_radius = self._circle_target_radius(point)
                if target_radius is None:
                    self._msg('OFFSET: Invalid target radius', err=True)
                    _abort_transaction(transaction)
                    return True
                result = Draft.offset(obj, target_radius, copy=True, occ=self.occ_mode)
            elif kind == 'wire':
                wire_preview = preview if preview and preview.get('kind') == 'wire' else None
                if wire_preview is None:
                    wire_preview = self._wire_apply_candidate(point, pos=pos)

                offset_shape = wire_preview.get('offset_shape') if wire_preview else None
                if offset_shape is not None:
                    result = _make_offset_wire(offset_shape)
                    if result is None:
                        result = _make_offset_feature(offset_shape)

                if result is None:
                    delta = wire_preview.get('delta') if wire_preview else None
                    if delta is None:
                        delta = self._wire_delta(point)
                    if delta is not None:
                        result = Draft.offset(obj, delta, copy=True, occ=self.occ_mode)

                if result is None:
                    self._msg('OFFSET: Could not determine offset direction', err=True)
                    _abort_transaction(transaction)
                    return True
            else:
                _abort_transaction(transaction)
                self.cleanup()
                _launch_native_offset(obj, console=self.console)
                return True
        except Exception as exc:
            _abort_transaction(transaction)
            self._msg(f'OFFSET: {exc}', err=True)
            return True

        if result is None:
            _abort_transaction(transaction)
            self._msg('OFFSET: Command did not create a result', err=True)
            return True

        _preserve_source_layer(obj, result)
        if self.distance is not None:
            saved_distance = _save_offset_distance(self.distance)
            if saved_distance is not None:
                self.default_distance = saved_distance
        _commit_transaction(transaction, result=result)
        try:
            Gui.Selection.clearSelection()
        except Exception:
            pass
        self._clear_preview()
        self.source = None
        self._stage = 'source'
        self._msg('OFFSET: Done', ok=True)
        self._msg(self._select_prompt())
        cursor = getattr(Gui, 'ccad_cursor', None)
        if cursor:
            try:
                cursor.update()
            except Exception:
                pass
        return True

    def cleanup(self, cancelled=False, restore_input=True):
        Gui.ccad_offset_handler = None
        self._clear_preview()
        cursor = getattr(Gui, 'ccad_cursor', None)
        if cursor:
            try:
                cursor.update()
            except Exception:
                pass
        if self.viewport:
            try:
                self.viewport.removeEventFilter(self)
            except Exception:
                pass
        if self._preview:
            self._preview.clear()
            self._preview.cleanup()
            self._preview = None
        if self._wire_tracker is not None:
            try:
                self._wire_tracker.finalize()
            except Exception:
                pass
            self._wire_tracker = None
        if restore_input:
            try:
                self.console.input.returnPressed.disconnect()
            except Exception:
                pass
            self.console.input.returnPressed.connect(self.console.execute)
        self.deleteLater()


def run(console):
    viewport = ccad_cmd_xline._get_viewport()
    if not viewport:
        _msg(console, 'OFFSET: No viewport', color='#ff5555')
        return

    OffsetPickHandler(console, viewport)


def tear_down():
    handler = getattr(Gui, 'ccad_offset_handler', None)
    if handler and hasattr(handler, 'cleanup'):
        try:
            handler.cleanup(cancelled=True)
        except TypeError:
            handler.cleanup()