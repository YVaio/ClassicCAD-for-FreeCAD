"""XLINE command — AutoCAD-style construction lines for FreeCAD.

Creates a Draft Wire with an adaptive span large enough to behave as an
infinite construction line in the active work area without resorting to a
fixed ±1e6 world-space extent.
First click sets a point on the XLINE, second click sets the through-point direction.

Sub-options (typed in console while handler is active):
  H — Horizontal through a point
  V — Vertical through a point
  A — At a specific angle through a point
  B — Bisect: angle bisector between two lines
  O — Offset: parallel copy of an existing line
"""

import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore, QtGui, QtWidgets

import ccad_layers

_PREF_GROUP = 'User parameter:BaseApp/Preferences/Mod/ClassicCAD'
MIN_HALF_SPAN = 1.0
DEFAULT_HALF_SPAN = 10.0
VIEW_MARGIN_FACTOR = 1.05
EDGE_NAME_RE = re.compile(r'Edge(\d+)', re.IGNORECASE)
_XLINE_FLAG_PROP = 'CCADIsXLine'
_XLINE_PROP_GROUP = 'ClassicCAD'
_XLINE_OFFSET_DISTANCE_KEY = 'XLineOffsetDistance'
_XLINE_VIEW_MANAGER = None


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _screen_pos(event):
    return event.position().toPoint() if hasattr(event, 'position') else event.pos()


def _snap_coords(pos):
    raw = _qpoint_to_raw(pos)
    return [raw[0], raw[1]]


def _qpoint_to_raw(pos, viewport=None):
    viewport = viewport or _get_viewport()
    if pos is None or viewport is None:
        return (0, 0)

    try:
        ratio = float(viewport.devicePixelRatioF())
    except Exception:
        ratio = 1.0

    return (
        int(round(float(pos.x()) * ratio)),
        int(round((float(viewport.height()) - float(pos.y())) * ratio)),
    )


def _prefs():
    return App.ParamGet(_PREF_GROUP)


def _draw_style_to_pen_style(value):
    try:
        index = int(value)
    except Exception:
        index = None
    if index == 1:
        return QtCore.Qt.DashLine
    if index == 2:
        return QtCore.Qt.DotLine
    if index == 3:
        return QtCore.Qt.DashDotLine
    draw_style = str(value or '').lower()
    if 'dashdot' in draw_style:
        return QtCore.Qt.DashDotLine
    if 'dot' in draw_style:
        return QtCore.Qt.DotLine
    if 'dash' in draw_style:
        return QtCore.Qt.DashLine
    return QtCore.Qt.SolidLine


def _current_preview_pen():
    color = QtGui.QColor(90, 210, 255, 210)
    width = 2.0
    style = QtCore.Qt.DashLine

    try:
        doc = App.ActiveDocument
        layer = ccad_layers.get_active_layer(doc) if doc else None
        vobj = getattr(layer, 'ViewObject', None) if layer else None
        if vobj:
            rgb = getattr(vobj, 'LineColor', None)
            if isinstance(rgb, (tuple, list)) and len(rgb) >= 3:
                color = QtGui.QColor(
                    int(round(float(rgb[0]) * 255.0)),
                    int(round(float(rgb[1]) * 255.0)),
                    int(round(float(rgb[2]) * 255.0)),
                    210,
                )
            width = max(1.0, float(getattr(vobj, 'LineWidth', width) or width))
            style = _draw_style_to_pen_style(getattr(vobj, 'DrawStyle', 'Solid'))
        else:
            view_param = App.ParamGet('User parameter:BaseApp/Preferences/View')
            argb = int(view_param.GetUnsigned('DefaultShapeLineColor', 0xFFFFFFFF))
            width = max(1.0, float(view_param.GetInt('DefaultShapeLineWidth', int(width)) or width))
            style = _draw_style_to_pen_style(
                App.ParamGet('User parameter:BaseApp/Preferences/Mod/Draft').GetInt('DefaultDrawStyle', 0)
            )
            color = QtGui.QColor.fromRgba(argb)
            color.setAlpha(210)
    except Exception:
        pass

    return QtGui.QPen(color, width, style)


def _coerce_vector(value):
    if value is None:
        return None
    if isinstance(value, App.Vector):
        return App.Vector(value.x, value.y, value.z)
    if hasattr(value, 'getValue'):
        try:
            return _coerce_vector(value.getValue())
        except Exception:
            pass
    if hasattr(value, 'x') and hasattr(value, 'y') and hasattr(value, 'z'):
        try:
            return App.Vector(float(value.x), float(value.y), float(value.z))
        except Exception:
            pass
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return App.Vector(float(value[0]), float(value[1]), float(value[2]))
        except Exception:
            pass
    return None


def _snapper_point(result, snapper):
    raw_point = _coerce_vector(result[0] if isinstance(result, tuple) else result)
    if raw_point is None:
        raw_point = _coerce_vector(getattr(snapper, 'spoint', None) if snapper else None)

    mode = getattr(snapper, '_ccad_snap_mode', None) if snapper else None
    if mode:
        mode = str(mode).lower()
    overlay_point = None
    if mode and mode not in ('', 'passive', 'near'):
        overlay_point = _coerce_vector(getattr(snapper, '_ccad_snap_point', None))
        if overlay_point is None:
            overlay_point = _coerce_vector(getattr(snapper, '_ccad_runtime_snap_point', None))

    candidates = [
        overlay_point,
        raw_point,
        _coerce_vector(getattr(snapper, '_ccad_runtime_snap_point', None) if snapper else None),
    ]
    for candidate in candidates:
        point = _coerce_vector(candidate)
        if point is not None:
            return point
    return None


def _snapper_mode(snapper):
    if snapper is None:
        return None

    for attr in ('_ccad_snap_mode', '_ccad_runtime_snap_mode', 'cursorMode'):
        value = getattr(snapper, attr, None)
        if value is None:
            continue
        value = str(value).lower()
        if value:
            return value
    return None


def get_3d_point(pos, lastpoint=None):
    """3D point from snapper (preferred) or plain view projection."""
    snapper = getattr(Gui, 'Snapper', None)
    try:
        if snapper is not None:
            result = snapper.snap(_snap_coords(pos), lastpoint=lastpoint)
            point = _snapper_point(result, snapper)
            if point is not None:
                return point
    except Exception:
        pass
    try:
        raw = _qpoint_to_raw(pos)
        return _coerce_vector(Gui.activeView().getPoint(raw[0], raw[1]))
    except Exception:
        return None


def get_snap_point(pos, lastpoint=None):
    """Return the current snapped point together with its snap mode."""
    snapper = getattr(Gui, 'Snapper', None)
    point = None
    mode = None
    try:
        if snapper is not None:
            result = snapper.snap(_snap_coords(pos), lastpoint=lastpoint)
            point = _snapper_point(result, snapper)
            mode = _snapper_mode(snapper)
    except Exception:
        point = None
        mode = None

    if point is None:
        try:
            raw = _qpoint_to_raw(pos)
            point = _coerce_vector(Gui.activeView().getPoint(raw[0], raw[1]))
        except Exception:
            point = None

    return point, mode


def is_xline(obj):
    """Return True if *obj* is an XLine (Draft Wire labelled 'XLine')."""
    try:
        if bool(getattr(obj, _XLINE_FLAG_PROP, False)):
            return True
    except Exception:
        pass
    return (hasattr(obj, 'Label') and obj.Label.startswith('XLine')
            and hasattr(obj, 'Points'))


def _normalized_direction(direction):
    try:
        vec = App.Vector(direction)
    except Exception:
        return None
    if vec.Length < 1e-7:
        return None
    vec.normalize()
    return vec


def _viewport_world_radius(midpoint):
    view = Gui.activeView()
    viewport = _get_viewport()
    if not view or not viewport:
        return 0.0

    try:
        rect = viewport.rect()
        samples = [
            rect.topLeft(),
            rect.topRight(),
            rect.bottomLeft(),
            rect.bottomRight(),
            rect.center(),
        ]
        radius = 0.0
        for sample in samples:
            raw = _qpoint_to_raw(sample, viewport)
            world = view.getPoint(raw[0], raw[1])
            if world is None:
                continue
            radius = max(radius, (App.Vector(world) - midpoint).Length)
        if radius > 0.0:
            return radius
    except Exception:
        pass

    try:
        camera = view.getCameraNode()
        if hasattr(camera, 'height'):
            height = float(camera.height.getValue())
            if height > 0.0:
                return height * 0.5
    except Exception:
        pass

    return 0.0


def _xline_half_span(midpoint):
    midpoint = App.Vector(midpoint)
    candidates = [DEFAULT_HALF_SPAN]

    view_radius = _viewport_world_radius(midpoint)
    if view_radius > 0.0:
        candidates.append(view_radius * VIEW_MARGIN_FACTOR)

    return max(MIN_HALF_SPAN, max(candidates))


def _xline_segment(midpoint, direction):
    midpoint = _coerce_vector(midpoint)
    direction = _normalized_direction(direction)
    if midpoint is None or direction is None:
        return None, None
    half_span = _xline_half_span(midpoint)
    return midpoint - (direction * half_span), midpoint + (direction * half_span)


def _world_to_qpoint(view, viewport, point):
    point = _coerce_vector(point)
    if point is None or view is None or viewport is None:
        return None
    try:
        raw = view.getPointOnScreen(point)
    except Exception:
        return None

    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None

    try:
        ratio = float(viewport.devicePixelRatioF())
    except Exception:
        ratio = 1.0

    return QtCore.QPoint(
        int(round(float(raw[0]) / ratio)),
        int(round(viewport.height() - (float(raw[1]) / ratio))),
    )


def _ensure_xline_flag(obj):
    if not obj:
        return
    if not hasattr(obj, _XLINE_FLAG_PROP):
        try:
            obj.addProperty('App::PropertyBool', _XLINE_FLAG_PROP, _XLINE_PROP_GROUP, 'ClassicCAD XLine flag')
        except Exception:
            pass
    if hasattr(obj, _XLINE_FLAG_PROP):
        try:
            setattr(obj, _XLINE_FLAG_PROP, True)
        except Exception:
            pass
        try:
            obj.setEditorMode(_XLINE_FLAG_PROP, 2)
        except Exception:
            pass


def _xline_definition(obj):
    points = list(getattr(obj, 'Points', []) or [])
    if len(points) < 2:
        return None, None
    start = _coerce_vector(points[0])
    end = _coerce_vector(points[-1])
    if start is None or end is None:
        return None, None
    midpoint = (start + end) * 0.5
    direction = _normalized_direction(end - start)
    return midpoint, direction


def _set_xline_points(obj, start, end):
    start = _coerce_vector(start)
    end = _coerce_vector(end)
    if obj is None or start is None or end is None or not hasattr(obj, 'Points'):
        return False

    current = list(getattr(obj, 'Points', []) or [])
    if len(current) >= 2:
        current_start = _coerce_vector(current[0])
        current_end = _coerce_vector(current[-1])
        if current_start and current_end:
            if current_start.distanceToPoint(start) <= 1e-6 and current_end.distanceToPoint(end) <= 1e-6:
                return False

    obj.Points = [start, end]
    try:
        obj.Closed = False
    except Exception:
        pass
    try:
        obj.MakeFace = False
    except Exception:
        pass
    return True


def _refresh_xline_object(obj):
    midpoint, direction = _xline_definition(obj)
    if midpoint is None or direction is None:
        return False
    start, end = _xline_segment(midpoint, direction)
    return _set_xline_points(obj, start, end)


def _xline_objects(doc=None):
    doc = doc or App.ActiveDocument
    if not doc:
        return []
    return [obj for obj in getattr(doc, 'Objects', []) if is_xline(obj) and hasattr(obj, 'Points')]


def _view_signature():
    view = Gui.activeView()
    viewport = _get_viewport()
    if view is None or viewport is None:
        return None

    signature = [viewport.width(), viewport.height()]
    try:
        camera = view.getCameraNode()
    except Exception:
        camera = None

    for name in ('position', 'orientation', 'height', 'heightAngle', 'focalDistance'):
        field = getattr(camera, name, None) if camera is not None else None
        if field is None:
            continue
        try:
            value = field.getValue()
            if hasattr(value, 'getValue'):
                value = value.getValue()
            signature.append(repr(value))
        except Exception:
            continue

    return tuple(signature)


class _XLineViewManager(QtCore.QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._tick)
        self._last_signature = None
        self._updating = False

    def ensure_running(self):
        if not self._timer.isActive():
            self._last_signature = None
            self._timer.start()

    def force_refresh(self):
        self._last_signature = None
        self.ensure_running()

    def _tick(self):
        if self._updating:
            return

        doc = App.ActiveDocument
        xlines = _xline_objects(doc)
        if not doc or not xlines:
            self._last_signature = None
            self._timer.stop()
            return

        signature = _view_signature()
        if signature is None or signature == self._last_signature:
            return

        self._last_signature = signature
        changed = []
        self._updating = True
        try:
            for obj in xlines:
                if _refresh_xline_object(obj):
                    changed.append(obj)
            if changed:
                try:
                    doc.recompute(changed)
                except Exception:
                    doc.recompute()
                Gui.updateGui()
        finally:
            self._updating = False


def _xline_view_manager():
    global _XLINE_VIEW_MANAGER
    if _XLINE_VIEW_MANAGER is None:
        _XLINE_VIEW_MANAGER = _XLineViewManager(Gui.getMainWindow())
    return _XLINE_VIEW_MANAGER


class XLinePreviewOverlay(QtWidgets.QWidget):
    def __init__(self, viewport):
        super().__init__(viewport)
        self.viewport = viewport
        self._segment = None
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

    def set_segment(self, start, end):
        start = _coerce_vector(start)
        end = _coerce_vector(end)
        self._segment = (start, end) if start is not None and end is not None else None
        self.raise_()
        self.update()

    def clear(self):
        self._segment = None
        self.update()

    def cleanup(self):
        try:
            self.viewport.removeEventFilter(self)
        except Exception:
            pass
        self.deleteLater()

    def paintEvent(self, event):
        view = Gui.activeView()
        if not view:
            return

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        if self._segment:
            q1 = _world_to_qpoint(view, self.viewport, self._segment[0])
            q2 = _world_to_qpoint(view, self.viewport, self._segment[1])
            if q1 is not None and q2 is not None:
                painter.setPen(_current_preview_pen())
                painter.drawLine(q1, q2)

        handler = getattr(Gui, 'ccad_xline_handler', None)
        if handler:
            snapper = getattr(Gui, 'Snapper', None)
            point = _coerce_vector(getattr(handler, '_hover_point', None))
            mode = getattr(handler, '_hover_mode', None) or _snapper_mode(snapper)
            if point is not None and not mode:
                snap_info = getattr(snapper, 'snapInfo', None) if snapper else None
                mode = 'near' if isinstance(snap_info, dict) and snap_info.get('Object') else None
            qpoint = _world_to_qpoint(view, self.viewport, point)
            resolved_mode = str(mode).lower() if mode else None
            if qpoint is not None and resolved_mode and resolved_mode not in ('near', 'passive'):
                self._draw_snap_symbol(painter, resolved_mode, qpoint)

        painter.end()

    @staticmethod
    def _draw_snap_symbol(painter, mode, center):
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 170, 55), 1.4))
        painter.setBrush(QtCore.Qt.NoBrush)

        x = float(center.x())
        y = float(center.y())
        size = 6.0

        def pt(dx, dy):
            return QtCore.QPointF(x + dx, y + dy)

        if mode == 'endpoint':
            painter.drawRect(QtCore.QRectF(x - size, y - size, size * 2.0, size * 2.0))
        elif mode == 'midpoint':
            painter.drawPolygon(QtGui.QPolygonF([pt(0, -size), pt(size, size), pt(-size, size)]))
        elif mode == 'center':
            painter.drawEllipse(QtCore.QRectF(x - size, y - size, size * 2.0, size * 2.0))
            painter.drawLine(pt(-size - 2, 0), pt(size + 2, 0))
            painter.drawLine(pt(0, -size - 2), pt(0, size + 2))
        elif mode == 'intersection':
            painter.drawLine(pt(-size, -size), pt(size, size))
            painter.drawLine(pt(-size, size), pt(size, -size))
        else:
            painter.drawPolygon(QtGui.QPolygonF([pt(0, -size), pt(size, 0), pt(0, size), pt(-size, 0)]))
        painter.restore()


def _picked_object_info(pos):
    try:
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else Gui.activeView()
        return view.getObjectInfo(_qpoint_to_raw(pos)) if pos else None
    except Exception:
        return None


def _edge_index_from_info(info):
    if not isinstance(info, dict):
        return 0

    for key in ('Component', 'SubName', 'SubElement', 'Subelement'):
        value = info.get(key)
        if not isinstance(value, str):
            continue
        match = EDGE_NAME_RE.search(value)
        if match:
            try:
                return max(0, int(match.group(1)) - 1)
            except Exception:
                return 0
    return 0


def _info_point(info, pos=None):
    if isinstance(info, dict):
        try:
            return App.Vector(float(info['x']), float(info['y']), float(info.get('z', 0.0)))
        except Exception:
            pass
    if pos is not None:
        return get_3d_point(pos)
    return None


def _picked_edge(pos):
    info = _picked_object_info(pos)
    if not isinstance(info, dict):
        return None, None, None, None

    doc = App.ActiveDocument
    obj_name = info.get('Object')
    obj = doc.getObject(obj_name) if doc and obj_name else None
    if not obj or not hasattr(obj, 'Shape') or not getattr(obj.Shape, 'Edges', None):
        return obj, None, _info_point(info, pos), info

    edges = list(obj.Shape.Edges)
    idx = min(max(_edge_index_from_info(info), 0), len(edges) - 1)
    return obj, edges[idx], _info_point(info, pos), info


def _edge_direction(edge):
    try:
        param = 0.5 * (edge.FirstParameter + edge.LastParameter)
        tangent = edge.tangentAt(param)
        direction = _normalized_direction(tangent)
        if direction is not None:
            return direction
    except Exception:
        pass

    try:
        verts = list(edge.Vertexes or [])
        if len(verts) >= 2:
            direction = _normalized_direction(verts[-1].Point - verts[0].Point)
            if direction is not None:
                return direction
    except Exception:
        pass

    return None


def _line_intersection_2d(point_a, dir_a, point_b, dir_b):
    denominator = (dir_a.x * dir_b.y) - (dir_a.y * dir_b.x)
    if abs(denominator) < 1e-9:
        return None

    delta = point_b - point_a
    t = ((delta.x * dir_b.y) - (delta.y * dir_b.x)) / denominator
    return App.Vector(
        point_a.x + (dir_a.x * t),
        point_a.y + (dir_a.y * t),
        (point_a.z + point_b.z) * 0.5,
    )


def _perpendicular_2d(direction):
    return App.Vector(-direction.y, direction.x, 0)


def _edge_anchor(edge, preferred=None):
    preferred = _coerce_vector(preferred)
    if preferred is not None:
        return preferred

    try:
        param = 0.5 * (edge.FirstParameter + edge.LastParameter)
        point = _coerce_vector(edge.valueAt(param))
        if point is not None:
            return point
    except Exception:
        pass

    try:
        verts = list(edge.Vertexes or [])
        if verts:
            point = _coerce_vector(verts[0].Point)
            if point is not None:
                return point
    except Exception:
        pass

    return None


def _parse_length_value(text):
    text = (text or '').strip()
    if not text:
        raise ValueError('empty length')

    def _has_explicit_unit(raw_text):
        compact = ''.join(ch for ch in str(raw_text or '') if not ch.isspace())
        if not compact:
            return False
        if any(ch.isalpha() for ch in compact):
            return True
        return any(ch in ('"', "'", '°') for ch in compact)

    parse_quantity = getattr(getattr(App, 'Units', None), 'parseQuantity', None)
    quantity = None

    if callable(parse_quantity):
        try:
            quantity = parse_quantity(text)
        except Exception:
            quantity = None

    def _quantity_value(qty):
        if qty is None:
            return None
        value = getattr(qty, 'Value', None)
        if value is not None:
            try:
                return float(value)
            except Exception:
                pass
        getter = getattr(qty, 'getValue', None)
        if callable(getter):
            try:
                return float(getter())
            except Exception:
                pass
        return None

    def _user_length_unit():
        getter = getattr(getattr(App, 'Units', None), 'getBasicLengthUnit', None)
        if callable(getter):
            try:
                unit = str(getter() or '').strip()
                if unit:
                    return unit
            except Exception:
                pass
        try:
            quantity = App.Units.Quantity(1.0, App.Units.Length)
            text_value = str(getattr(quantity, 'UserString', '') or '').strip()
            parts = text_value.split()
            if len(parts) >= 2:
                return parts[-1]
        except Exception:
            pass
        return 'mm'

    parse_text = text if _has_explicit_unit(text) else f'{text} {_user_length_unit()}'

    try:
        if quantity is not None:
            if _has_explicit_unit(text):
                value = _quantity_value(quantity)
            else:
                quantity = parse_quantity(parse_text) if callable(parse_quantity) else None
                value = _quantity_value(quantity)
            if value is None:
                raise ValueError('no quantity value')
        else:
            value = float(App.Units.Quantity(parse_text).Value)
    except Exception:
        value = float(text)

    if value <= 1e-7:
        raise ValueError('length must be positive')
    return value


def _looks_like_length(text):
    stripped = (text or '').strip()
    if not stripped:
        return False

    first = stripped[0]
    if first not in '+-.0123456789':
        return False

    try:
        _parse_length_value(stripped)
        return True
    except Exception:
        return False


def _load_offset_distance():
    try:
        value = float(_prefs().GetFloat(_XLINE_OFFSET_DISTANCE_KEY, 0.0))
    except Exception:
        value = 0.0
    return value if value > 1e-7 else None


def _save_offset_distance(distance):
    try:
        _prefs().SetFloat(_XLINE_OFFSET_DISTANCE_KEY, float(distance or 0.0))
    except Exception:
        pass


def _format_length_value(value):
    try:
        quantity = App.Units.Quantity(float(value), App.Units.Length)
        text = str(getattr(quantity, 'UserString', '') or '').strip()
        if text:
            return text
        return f"{float(value):g}"
    except Exception:
        return '0'


def _offset_line_definition(source_point, direction, hover_point, distance=None):
    source_point = _coerce_vector(source_point)
    direction = _normalized_direction(direction)
    hover_point = _coerce_vector(hover_point)
    if source_point is None or direction is None or hover_point is None:
        return None, None

    if distance is None or float(distance) <= 1e-7:
        return hover_point, direction

    normal = _normalized_direction(_perpendicular_2d(direction))
    if normal is None:
        return None, None

    signed = (hover_point - source_point).dot(normal)
    side = -1.0 if signed < 0.0 else 1.0
    return source_point + (normal * (side * float(distance))), direction


def _make_xline(midpoint, direction):
    """Create a Draft Wire named XLine through a picked point in *direction*."""
    import Draft

    midpoint = _coerce_vector(midpoint)
    d = _normalized_direction(direction)
    if midpoint is None or d is None:
        return None

    wire = Draft.make_wire([midpoint, midpoint + d], closed=False, face=False)
    wire.Label = "XLine"
    _ensure_xline_flag(wire)
    start, end = _xline_segment(midpoint, d)
    _set_xline_points(wire, start, end)
    manager = _xline_view_manager()
    manager.force_refresh()
    try:
        App.ActiveDocument.recompute([wire])
    except Exception:
        App.ActiveDocument.recompute()
    return wire


# ─────────────────────────────────────────────
# Interactive pick handler
# ─────────────────────────────────────────────
class XlinePickHandler(QtCore.QObject):
    """Viewport event filter for interactive XLINE creation.

    Modes:
        None  — two-point (point + through point)
      'H'   — horizontal through one point
      'V'   — vertical through one point
      'A'   — angle mode: user types angle, then clicks point
        'B'   — bisect: click two lines
        'O'   — offset: choose distance/through, click a line, then side
    """

    def __init__(self, console, viewport):
        super().__init__()
        self.console = console
        self.mode = None
        self.midpoint = None
        self.node = []
        self.viewport = viewport
        self.angle = None           # for Angle mode
        self._bisect_edge1 = None   # for Bisect mode
        self._offset_obj = None     # for Offset mode
        self._offset_distance = _load_offset_distance()
        self._offset_waiting_value = False
        self._hover_point = None
        self._hover_mode = None
        self._hover_pos = None
        self._preview_segment = None
        self._preview = XLinePreviewOverlay(viewport) if viewport else None
        self._hover_timer = QtCore.QTimer(self)
        self._hover_timer.setInterval(16)
        self._hover_timer.timeout.connect(self._poll_hover)
        Gui.ccad_xline_handler = self
        finder = getattr(Gui, 'ccad_find_cursor', None)
        if callable(finder):
            try:
                finder()
            except Exception:
                pass
        if self.viewport:
            try:
                self.viewport.setMouseTracking(True)
            except Exception:
                pass
            self.viewport.installEventFilter(self)
        self._hover_timer.start()
        self._setup_task_panel()
        # Hook console input for sub-option entry
        self.console.input.returnPressed.disconnect()
        self.console.input.returnPressed.connect(self._on_input)

    def _setup_task_panel(self):
        toolbar = getattr(Gui, 'draftToolBar', None)
        if not toolbar:
            return
        try:
            toolbar.lineUi(title='XLINE', cancel=self.cleanup, icon='Draft_Line')
            toolbar.sourceCmd = self
        except Exception:
            pass

    # ── events ────────────────────────────────

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.MouseMove:
            pos = _screen_pos(event)
            self._update_hover(pos)
            return False

        if (event.type() == QtCore.QEvent.MouseButtonPress
                and event.button() == QtCore.Qt.LeftButton):
            pos = _screen_pos(event)
            point = self._click_point(pos)
            if point is None:
                return True
            return self._handle_point(point, pos)

        if (event.type() == QtCore.QEvent.KeyPress
                and event.key() == QtCore.Qt.Key_Escape):
            self._msg("XLINE: Cancelled")
            self.cleanup()
            return True

        return False

    # ── console input handler ─────────────────

    def _on_input(self):
        raw_text = self.console.input.text().strip()
        text = raw_text.upper()
        parts = raw_text.split(None, 1)
        command = parts[0].upper() if parts else ''
        argument = parts[1].strip() if len(parts) > 1 else ''
        self.console.input.clear()

        if not text:
            if self.mode == 'O' and self._offset_obj is None:
                self._offset_waiting_value = False
                self._msg(f'XLINE Offset: Using <{_format_length_value(self._offset_distance) if self._offset_distance is not None else "Through"}>. Select line to offset')
            return

        if self.mode == 'O' and self._offset_obj is None:
            self._offset_waiting_value = False

        # Sub-option selection (only when no clicks yet)
        if self.midpoint is None and self.mode is None and _looks_like_length(raw_text):
            self.mode = 'O'
            self._offset_distance = _parse_length_value(raw_text)
            _save_offset_distance(self._offset_distance)
            self._offset_waiting_value = False
            self._msg(f'XLINE Offset: Distance set to {_format_length_value(self._offset_distance)}. Select line to offset')
            return

        # Sub-option selection (only when no clicks yet)
        if self.midpoint is None and self.mode is None:
            if command in ('H', 'HOR', 'HORIZONTAL'):
                self.mode = 'H'
                self._msg('XLINE Hor: Specify through point')
                return
            elif command in ('V', 'VER', 'VERTICAL'):
                self.mode = 'V'
                self._msg('XLINE Ver: Specify through point')
                return
            elif command in ('A', 'ANG', 'ANGLE'):
                self.mode = 'A'
                if argument:
                    raw_text = argument
                    text = raw_text.upper()
                else:
                    self._msg("XLINE Angle: Enter angle (degrees)")
                    return
            elif command in ('B', 'BIS', 'BISECT'):
                self.mode = 'B'
                self._msg('XLINE Bisect: Select first line')
                return
            elif command in ('O', 'OFF', 'OFFSET'):
                self.mode = 'O'
                if argument:
                    raw_text = argument
                    text = raw_text.upper()
                    self._offset_waiting_value = False
                else:
                    self._offset_waiting_value = True
                    self._msg(self._offset_prompt())
                    return

        # Angle mode: user types the angle value
        if self.mode == 'A' and self.angle is None:
            try:
                import math
                self.angle = math.radians(float(raw_text))
                self._msg(f"XLINE Angle {raw_text}°: Specify through point")
            except ValueError:
                self._msg("XLINE: Invalid angle", err=True)
            return

        if self.mode == 'O':
            if text in ('T', 'THROUGH'):
                self._offset_distance = None
                _save_offset_distance(None)
                self._offset_waiting_value = False
                if self._offset_obj is None:
                    self._msg('XLINE Offset: Through mode. Select line to offset')
                else:
                    self._msg('XLINE Offset: Through mode. Specify through point')
                return

            try:
                self._offset_distance = _parse_length_value(raw_text)
                _save_offset_distance(self._offset_distance)
                self._offset_waiting_value = False
                value = _format_length_value(self._offset_distance)
                if self._offset_obj is None:
                    self._msg(f'XLINE Offset: Distance set to {value}. Select line to offset')
                else:
                    self._msg(f'XLINE Offset: Distance set to {value}. Specify side to offset')
            except ValueError:
                self._msg('XLINE Offset: Enter a positive distance or Through', err=True)
            return

    # ── point logic ───────────────────────────

    def _update_hover(self, pos):
        point, mode = get_snap_point(pos, self.midpoint)
        self._hover_point = point
        self._hover_mode = mode
        self._hover_pos = QtCore.QPoint(pos)
        toolbar = getattr(Gui, 'draftToolBar', None)
        if toolbar and point is not None:
            try:
                last_point = self.node[-1] if self.node else None
                toolbar.displayPoint(point, last=last_point)
            except Exception:
                pass
        self._update_preview(pos, point)
        cursor = getattr(Gui, 'ccad_cursor', None)
        if cursor:
            try:
                cursor.show()
                cursor.raise_()
                cursor.update()
            except Exception:
                pass
        return point

    def _poll_hover(self):
        if not self.viewport:
            return
        try:
            global_pos = QtGui.QCursor.pos()
            pos = self.viewport.mapFromGlobal(global_pos)
        except Exception:
            return
        try:
            if not self.viewport.rect().contains(pos):
                return
        except Exception:
            return
        if self._preview is not None:
            try:
                self._preview.raise_()
            except Exception:
                pass
        self._update_hover(pos)

    def _click_point(self, pos):
        if (
            self._hover_point is not None
            and self._hover_pos is not None
            and (self._hover_pos - pos).manhattanLength() <= 2
        ):
            return self._hover_point
        return self._update_hover(pos)

    def _offset_prompt(self):
        if self._offset_distance is None:
            default = 'Through'
        else:
            default = _format_length_value(self._offset_distance)
        return f'XLINE Offset: Enter offset distance or [Through] <{default}>, or click a line'

    def _offset_status_text(self):
        if self._offset_distance is None:
            return 'XLINE Offset: Specify through point'
        return f'XLINE Offset: Specify side to offset <{_format_length_value(self._offset_distance)}>'

    def _preview_definition(self, pos, point):
        if point is None:
            return None, None

        if self.mode == 'H':
            return point, App.Vector(1, 0, 0)

        if self.mode == 'V':
            return point, App.Vector(0, 1, 0)

        if self.mode == 'A' and self.angle is not None:
            import math
            return point, App.Vector(math.cos(self.angle), math.sin(self.angle), 0)

        if self.mode == 'O' and self._offset_obj is not None:
            direction = self._offset_obj.get('direction')
            source_point = self._offset_obj.get('point')
            if direction is not None and source_point is not None:
                return _offset_line_definition(source_point, direction, point, self._offset_distance)

        if self.mode == 'B' and self._bisect_edge1 is not None and pos is not None:
            _obj, edge, click_pt, info = _picked_edge(pos)
            if info and edge is not None:
                direction = _edge_direction(edge)
                if direction is not None:
                    anchor = click_pt or point
                    d1 = App.Vector(self._bisect_edge1['direction'])
                    d2 = App.Vector(direction)
                    if d1.dot(d2) < 0:
                        d2 = -d2
                    bisect = d1 + d2
                    if bisect.Length < 1e-7:
                        bisect = _perpendicular_2d(d1)
                    first_point = self._bisect_edge1.get('point')
                    base_point = None
                    if first_point is not None and anchor is not None:
                        base_point = _line_intersection_2d(first_point, d1, anchor, direction)
                    if base_point is None:
                        base_point = anchor or first_point or point
                    return base_point, bisect

        if self.midpoint is not None:
            direction = point - self.midpoint
            if direction.Length >= 0.001:
                return self.midpoint, direction

        return None, None

    def _update_preview(self, pos, point):
        base_point, direction = self._preview_definition(pos, point)
        if base_point is None or direction is None:
            self._preview_segment = None
            if self._preview is not None:
                self._preview.clear()
            cursor = getattr(Gui, 'ccad_cursor', None)
            if cursor:
                cursor.update()
            return
        start, end = _xline_segment(base_point, direction)
        self._preview_segment = (start, end)
        if self._preview is not None:
            self._preview.set_segment(start, end)
        cursor = getattr(Gui, 'ccad_cursor', None)
        if cursor:
            cursor.update()

    def _handle_point(self, point, pos=None):
        # ── Horizontal ──
        if self.mode == 'H':
            _make_xline(point, App.Vector(1, 0, 0))
            self._msg("XLINE H: Done", ok=True)
            self.cleanup()
            return True

        # ── Vertical ──
        if self.mode == 'V':
            _make_xline(point, App.Vector(0, 1, 0))
            self._msg("XLINE V: Done", ok=True)
            self.cleanup()
            return True

        # ── Angle ──
        if self.mode == 'A':
            if self.angle is None:
                self._msg("XLINE: Enter angle first", err=True)
                return True
            import math
            d = App.Vector(math.cos(self.angle), math.sin(self.angle), 0)
            _make_xline(point, d)
            self._msg("XLINE Angle: Done", ok=True)
            self.cleanup()
            return True

        # ── Bisect ──
        if self.mode == 'B':
            return self._handle_bisect(point, pos)

        # ── Offset ──
        if self.mode == 'O':
            return self._handle_offset(point, pos)

        # ── Default: point + through point ──
        if self.midpoint is None:
            self.midpoint = point
            self.node = [App.Vector(point)]
            self._msg('XLINE: Specify through point')
            return True

        d = point - self.midpoint
        if d.Length < 0.001:
            return True
        _make_xline(self.midpoint, d)
        self._msg("XLINE: Done", ok=True)
        self.cleanup()
        return True

    def numericInput(self, numx, numy, numz):
        point = App.Vector(numx, numy, numz)
        self._handle_point(point)

    # ── Bisect logic ──────────────────────────

    def _handle_bisect(self, point, pos):
        obj, edge, click_pt, info = _picked_edge(pos)

        if not info or edge is None:
            self._msg("XLINE Bisect: Click on a line", err=True)
            return True

        direction = _edge_direction(edge)
        if direction is None:
            self._msg("XLINE Bisect: Not a valid edge", err=True)
            return True

        anchor = click_pt or point

        if self._bisect_edge1 is None:
            self._bisect_edge1 = {
                'direction': direction,
                'point': anchor,
            }
            self._msg("XLINE Bisect: Click second line")
            return True

        d1 = App.Vector(self._bisect_edge1['direction'])
        d2 = App.Vector(direction)
        if d1.dot(d2) < 0:
            d2 = -d2

        bisect = d1 + d2
        if bisect.Length < 1e-7:
            bisect = _perpendicular_2d(d1)

        base_point = None
        first_point = self._bisect_edge1.get('point')
        if first_point is not None and anchor is not None:
            base_point = _line_intersection_2d(first_point, d1, anchor, direction)
        if base_point is None:
            if first_point is not None and anchor is not None:
                base_point = (first_point + anchor) * 0.5
            else:
                base_point = anchor or first_point or point

        _make_xline(base_point, bisect)
        self._msg("XLINE Bisect: Done", ok=True)
        self.cleanup()
        return True

    # ── Offset logic ──────────────────────────

    def _handle_offset(self, point, pos):
        if self._offset_obj is None:
            obj, edge, _click_pt, info = _picked_edge(pos)
            if not info or edge is None:
                self._msg("XLINE Offset: Click on a line", err=True)
                return True
            direction = _edge_direction(edge)
            if direction is None:
                self._msg("XLINE Offset: Not a valid edge", err=True)
                return True
            self._offset_obj = {
                'object': obj,
                'edge': edge,
                'direction': direction,
                'point': _edge_anchor(edge, _click_pt or point),
            }
            self._msg(self._offset_status_text())
            return True

        direction = self._offset_obj.get('direction')
        source_point = self._offset_obj.get('point')
        if direction is None or source_point is None:
            self.cleanup()
            return True

        base_point, final_direction = _offset_line_definition(
            source_point,
            direction,
            point,
            self._offset_distance,
        )
        if base_point is None or final_direction is None:
            self._msg('XLINE Offset: Could not determine offset line', err=True)
            return True

        _make_xline(base_point, final_direction)
        self._msg("XLINE Offset: Done", ok=True)
        self.cleanup()
        return True

    # ── helpers ───────────────────────────────

    def _msg(self, text, ok=False, err=False):
        if err:
            color = '#ff5555'
        elif ok:
            color = '#55ff55'
        else:
            color = '#aaa'
        self.console.history.append(f"<span style='color:{color};'>{text}</span>")

    def cleanup(self):
        try:
            Gui.Snapper.off()
        except Exception:
            pass
        try:
            self._hover_timer.stop()
        except Exception:
            pass
        self._preview_segment = None
        Gui.ccad_xline_handler = None
        self.node = []
        if self._preview:
            self._preview.clear()
            self._preview.cleanup()
            self._preview = None
        toolbar = getattr(Gui, 'draftToolBar', None)
        if toolbar:
            try:
                if getattr(toolbar, 'sourceCmd', None) is self:
                    toolbar.sourceCmd = None
                toolbar.pointcallback = None
                toolbar.offUi()
            except Exception:
                pass
        cursor = getattr(Gui, 'ccad_cursor', None)
        if cursor:
            try:
                cursor.update()
            except Exception:
                pass
        if self.viewport:
            self.viewport.removeEventFilter(self)
        # Restore console input connection
        try:
            self.console.input.returnPressed.disconnect()
        except Exception:
            pass
        self.console.input.returnPressed.connect(self.console.execute)
        self.deleteLater()


# ─────────────────────────────────────────────
# Console entry-point
# ─────────────────────────────────────────────
def run(console, option=None):
    """Launch the XLINE interactive handler with options prompt.

    *option* can be None (interactive), 'H' (horizontal) or 'V' (vertical).
    """
    vp = _get_viewport()
    if not vp:
        console.history.append(
            "<span style='color:#ff5555;'>XLINE: No viewport</span>")
        return
    console.history.append(
        "<span style='color:#aaa;'>Specify a point or "
        "[<span style='color:#6af;'>B</span>isect "
        "<span style='color:#6af;'>H</span>or "
        "<span style='color:#6af;'>V</span>er "
        "<span style='color:#6af;'>A</span>ng "
        "<span style='color:#6af;'>O</span>ffset]:</span>")
    handler = XlinePickHandler(console, vp)
    if option in ('H', 'V'):
        handler.mode = option
        label = 'Hor' if option == 'H' else 'Ver'
        handler._msg(f"XLINE {label}: Specify through point")


def _get_viewport():
    from PySide6 import QtWidgets
    if hasattr(Gui, 'ccad_sel_logic') and Gui.ccad_sel_logic:
        return Gui.ccad_sel_logic.viewport
    mw = Gui.getMainWindow()
    if mw:
        for w in mw.findChildren(QtWidgets.QWidget):
            if "View3DInventor" in w.metaObject().className() and w.isVisible():
                return w
    return None
