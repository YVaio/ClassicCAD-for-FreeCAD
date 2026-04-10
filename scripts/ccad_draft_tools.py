import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore, QtGui, QtWidgets

try:
    import Part
except Exception:
    Part = None

_original_snap = None
_PATCHED_DRAFT_METHODS = {}
# Preferences saved on activation so they can be reliably restored on teardown
# even if the QObject instance was already cleared.
_SAVED_PREFS = {}

_DRAFT_PREFS_PATH = "User parameter:BaseApp/Preferences/Mod/Draft"
_PREF_GROUP = "User parameter:BaseApp/Preferences/Mod/ClassicCAD"

_ORTHO_SUSPEND_CMDS = ('Rectangle',)
_LENGTH_FOCUS_RETRY_DELAYS = (0, 40, 140)
_TAB_NAVIGATION_WIDGETS = (
    'xValue',
    'yValue',
    'zValue',
    'lengthValue',
    'angleValue',
    'radiusValue',
    'numFaces',
    'pointButton',
    'finishButton',
    'closeButton',
    'wipeButton',
    'undoButton',
    'orientWPButton',
    'selectButton',
    'angleLock',
    'isRelative',
    'isGlobal',
    'makeFace',
    'isCopy',
    'isSubelementMode',
    'continueCmd',
    'chainedModeCmd',
    'occOffset',
)


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


def _scale_vector(vec, scale):
    vec = _coerce_vector(vec)
    if vec is None:
        return None
    return App.Vector(vec.x * scale, vec.y * scale, vec.z * scale)


def _normalized_vector(vec):
    vec = _coerce_vector(vec)
    if vec is None:
        return None
    length = float(vec.Length)
    if length <= 1e-9:
        return None
    return App.Vector(vec.x / length, vec.y / length, vec.z / length)


def _screenpos_tuple(screenpos):
    if isinstance(screenpos, tuple):
        return screenpos
    if isinstance(screenpos, list):
        return tuple(screenpos)
    if hasattr(screenpos, 'getValue'):
        try:
            return tuple(screenpos.getValue())
        except Exception:
            pass
    return None


def _tracker_marker_point(tracker):
    coords = getattr(tracker, 'coords', None)
    point_field = getattr(coords, 'point', None) if coords is not None else None
    if point_field is None:
        return None

    getter = getattr(point_field, 'getValue', None)
    if callable(getter):
        try:
            point = _coerce_vector(getter())
            if point is not None:
                return point
        except Exception:
            pass

    getter = getattr(point_field, 'getValues', None)
    if callable(getter):
        for args in ((), (0,), (0, 1)):
            try:
                raw = getter(*args)
            except Exception:
                continue
            if isinstance(raw, (list, tuple)) and raw:
                point = _coerce_vector(raw[0])
                if point is not None:
                    return point

    return None


def _screen_distance_to_point(snapper, screenpos, point):
    screenpos = _screenpos_tuple(screenpos)
    view = getattr(snapper, 'activeview', None) or Gui.activeView()
    point = _coerce_vector(point)
    if screenpos is None or view is None or point is None:
        return None

    try:
        raw = view.getPointOnScreen(point)
    except Exception:
        return None

    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None

    try:
        return math.hypot(float(raw[0]) - float(screenpos[0]), float(raw[1]) - float(screenpos[1]))
    except Exception:
        return None


def _snap_range_pixels():
    try:
        return max(1.0, float(App.ParamGet(_DRAFT_PREFS_PATH).GetInt("snapRange", 8)))
    except Exception:
        return 8.0


def _snap_info_edge(snapper):
    snap_info = getattr(snapper, 'snapInfo', None)
    if not isinstance(snap_info, dict):
        return None

    component = snap_info.get('Component') or snap_info.get('SubName')
    obj_name = snap_info.get('Object')
    doc = App.ActiveDocument
    if not doc or not component or not obj_name or not str(component).startswith('Edge'):
        return None

    try:
        obj = doc.getObject(obj_name)
    except Exception:
        obj = None
    shape = getattr(obj, 'Shape', None) if obj is not None else None
    if shape is None:
        return None

    try:
        index = max(int(str(component)[4:]) - 1, 0)
        if index < len(shape.Edges):
            return shape.Edges[index]
    except Exception:
        pass

    if Part is not None:
        try:
            return Part.getShape(obj, str(component), needSubElement=True, noElementMap=True)
        except Exception:
            pass
    return None


def _point_is_on_edge(edge, point, tolerance=1e-5):
    edge = edge if edge is not None else None
    point = _coerce_vector(point)
    if edge is None or point is None:
        return False

    try:
        curve = getattr(edge, 'Curve', None)
        if curve is None or not hasattr(curve, 'parameter'):
            return False
        parameter = curve.parameter(point)
        if parameter < (float(edge.FirstParameter) - tolerance):
            return False
        if parameter > (float(edge.LastParameter) + tolerance):
            return False
        projected = edge.valueAt(parameter)
        return projected.sub(point).Length <= tolerance
    except Exception:
        return False


def _circle_tangent_points(edge, lastpoint):
    curve = getattr(edge, 'Curve', None) if edge is not None else None
    center = _coerce_vector(getattr(curve, 'Center', None)) if curve is not None else None
    axis = _normalized_vector(getattr(curve, 'Axis', None)) if curve is not None else None
    radius = float(getattr(curve, 'Radius', 0.0) or 0.0) if curve is not None else 0.0
    base = _coerce_vector(lastpoint)
    if center is None or axis is None or base is None or radius <= 1e-9:
        return []

    delta = base.sub(center)
    projected = base.sub(_scale_vector(axis, delta.dot(axis)))
    radial = projected.sub(center)
    distance = float(radial.Length)
    if distance <= (radius + 1e-6):
        return []

    u = _normalized_vector(radial)
    v = _normalized_vector(axis.cross(u)) if u is not None else None
    if u is None or v is None:
        return []

    along = (radius * radius) / distance
    offset = radius * math.sqrt(max((distance * distance) - (radius * radius), 0.0)) / distance
    base_point = center.add(_scale_vector(u, along))

    candidates = []
    for sign in (-1.0, 1.0):
        tangent_point = base_point.add(_scale_vector(v, sign * offset))
        if _point_is_on_edge(edge, tangent_point):
            candidates.append(tangent_point)
    return candidates


def _curve_tangent_value(edge, point, parameter):
    point = _coerce_vector(point)
    if edge is None or point is None:
        return None

    try:
        curve_point = edge.valueAt(parameter)
    except Exception:
        return None

    tangent = None
    try:
        tangent = edge.tangentAt(parameter)
    except Exception:
        tangent = None

    if isinstance(tangent, (list, tuple)) and tangent:
        tangent = tangent[0]
    tangent = _coerce_vector(tangent)
    if tangent is None or tangent.Length <= 1e-9:
        return None
    return curve_point.sub(point).dot(tangent)


def _curve_tangent_error(edge, point, parameter):
    point = _coerce_vector(point)
    if edge is None or point is None:
        return None

    try:
        curve_point = edge.valueAt(parameter)
    except Exception:
        return None

    try:
        tangent = edge.tangentAt(parameter)
    except Exception:
        tangent = None

    if isinstance(tangent, (list, tuple)) and tangent:
        tangent = tangent[0]
    tangent = _normalized_vector(tangent)
    delta = _normalized_vector(curve_point.sub(point))
    if tangent is None or delta is None:
        return None
    return abs(tangent.dot(delta))


def _edge_tangent_direction(edge, point):
    point = _coerce_vector(point)
    if edge is None or point is None:
        return None

    curve = getattr(edge, 'Curve', None)
    if curve is None or not hasattr(curve, 'parameter'):
        return None

    try:
        parameter = curve.parameter(point)
        tangent = edge.tangentAt(parameter)
    except Exception:
        tangent = None

    if isinstance(tangent, (list, tuple)) and tangent:
        tangent = tangent[0]
    return _normalized_vector(tangent)


def _generic_tangent_points(edge, lastpoint, samples=192):
    point = _coerce_vector(lastpoint)
    if edge is None or point is None:
        return []

    try:
        start = float(edge.FirstParameter)
        end = float(edge.LastParameter)
    except Exception:
        return []

    if end <= start:
        return []

    roots = []
    epsilon = 1e-7
    samples_data = []

    def add_root(value):
        for existing in roots:
            if abs(existing - value) <= 1e-5:
                return
        roots.append(value)

    previous_param = start
    previous_value = _curve_tangent_value(edge, point, previous_param)
    previous_error = _curve_tangent_error(edge, point, previous_param)
    samples_data.append((previous_param, previous_value, previous_error))
    if previous_value is not None and abs(previous_value) <= epsilon:
        add_root(previous_param)

    for index in range(1, samples + 1):
        ratio = float(index) / float(samples)
        current_param = start + ((end - start) * ratio)
        current_value = _curve_tangent_value(edge, point, current_param)
        current_error = _curve_tangent_error(edge, point, current_param)
        samples_data.append((current_param, current_value, current_error))

        if current_value is not None and abs(current_value) <= epsilon:
            add_root(current_param)
        elif previous_value is not None and current_value is not None and ((previous_value < 0.0 < current_value) or (previous_value > 0.0 > current_value)):
            low_param = previous_param
            high_param = current_param
            low_value = previous_value
            high_value = current_value
            for _ in range(24):
                mid_param = (low_param + high_param) * 0.5
                mid_value = _curve_tangent_value(edge, point, mid_param)
                if mid_value is None:
                    break
                if abs(mid_value) <= epsilon:
                    low_param = high_param = mid_param
                    break
                if (low_value < 0.0 < mid_value) or (low_value > 0.0 > mid_value):
                    high_param = mid_param
                    high_value = mid_value
                else:
                    low_param = mid_param
                    low_value = mid_value
            add_root((low_param + high_param) * 0.5)

        previous_param = current_param
        previous_value = current_value
        previous_error = current_error

    for index in range(1, len(samples_data) - 1):
        prev_param, _, prev_error = samples_data[index - 1]
        mid_param, _, mid_error = samples_data[index]
        next_param, _, next_error = samples_data[index + 1]
        if mid_error is None or prev_error is None or next_error is None:
            continue
        if mid_error > 0.08:
            continue
        if not (mid_error <= prev_error and mid_error <= next_error):
            continue

        low_param = prev_param
        high_param = next_param
        for _ in range(20):
            left_param = low_param + ((high_param - low_param) / 3.0)
            right_param = high_param - ((high_param - low_param) / 3.0)
            left_error = _curve_tangent_error(edge, point, left_param)
            right_error = _curve_tangent_error(edge, point, right_param)
            if left_error is None or right_error is None:
                break
            if left_error <= right_error:
                high_param = right_param
            else:
                low_param = left_param

        refined = (low_param + high_param) * 0.5
        refined_error = _curve_tangent_error(edge, point, refined)
        if refined_error is not None and refined_error <= 0.05:
            add_root(refined)

    points = []
    for parameter in roots:
        try:
            tangent_point = edge.valueAt(parameter)
        except Exception:
            continue
        if _point_is_on_edge(edge, tangent_point, tolerance=1e-4):
            points.append(tangent_point)
    return points


def _tangent_candidate_points(edge, lastpoint):
    curve = getattr(edge, 'Curve', None) if edge is not None else None
    if curve is None:
        return []

    if hasattr(curve, 'Center') and hasattr(curve, 'Radius'):
        points = _circle_tangent_points(edge, lastpoint)
        if points:
            return points

    curve_name = curve.__class__.__name__ if curve is not None else ''
    if any(token in curve_name for token in ('Spline', 'Bezier', 'Ellipse', 'Circle', 'Arc')) or hasattr(curve, 'tangent'):
        return _generic_tangent_points(edge, lastpoint)
    return []


def _apply_custom_tangent_snap(snapper, screenpos, lastpoint):
    mode = getattr(snapper, 'cursorMode', None)
    mode = str(mode).lower() if mode else None

    if lastpoint is None:
        return None

    try:
        tangent_enabled = bool(
            ClassicDraftTools._tangent_enabled
            and snapper.isEnabled("Lock")
        )
    except Exception:
        tangent_enabled = False
    if not tangent_enabled:
        return None

    edge = _snap_info_edge(snapper)
    curve = getattr(edge, 'Curve', None) if edge is not None else None
    if curve is None:
        return None

    current_point = _tracker_marker_point(getattr(snapper, 'tracker', None)) or _coerce_vector(getattr(snapper, 'spoint', None))
    current_distance = None
    if mode not in (None, '', 'passive'):
        current_distance = _screen_distance_to_point(snapper, screenpos, current_point)

    best_point = None
    best_distance = None
    for tangent_point in _tangent_candidate_points(edge, lastpoint):
        distance = _screen_distance_to_point(snapper, screenpos, tangent_point)
        if distance is None:
            continue
        if best_distance is None or distance < best_distance:
            best_point = tangent_point
            best_distance = distance

    if best_point is None or best_distance is None or best_distance > _snap_range_pixels():
        return None

    if current_distance is not None and best_distance >= (current_distance - 0.25):
        return None

    tracker = getattr(snapper, 'tracker', None)
    if tracker is not None:
        try:
            tracker.setCoords(best_point)
        except Exception:
            pass

    tangent_direction = _edge_tangent_direction(edge, best_point)

    try:
        snapper._ccad_runtime_snap_mode = 'tangent'
        snapper._ccad_runtime_snap_point = best_point
        snapper._ccad_runtime_snap_direction = tangent_direction
    except Exception:
        pass

    try:
        snapper.setCursor('tangent')
    except Exception:
        try:
            snapper.cursorMode = 'tangent'
        except Exception:
            pass
    return best_point


def _clear_snap_overlay_state(snapper):
    try:
        snapper._ccad_snap_mode = None
        snapper._ccad_snap_point = None
        snapper._ccad_snap_direction = None
        snapper._ccad_runtime_snap_mode = None
        snapper._ccad_runtime_snap_point = None
        snapper._ccad_runtime_snap_direction = None
    except Exception:
        pass


def _begin_snap_overlay_cycle(snapper):
    try:
        snapper._ccad_snap_mode = None
        snapper._ccad_snap_point = None
        snapper._ccad_snap_direction = None
        snapper._ccad_runtime_snap_mode = None
        snapper._ccad_runtime_snap_point = None
        snapper._ccad_runtime_snap_direction = None
    except Exception:
        pass


def _remember_runtime_snap_mode(snapper, mode):
    if not mode:
        return

    mode = str(mode).lower()
    if mode in ('passive', ''):
        return

    try:
        snapper._ccad_runtime_snap_mode = mode
        point = _tracker_marker_point(getattr(snapper, 'tracker', None))
        if point is not None:
            snapper._ccad_runtime_snap_point = point
    except Exception:
        pass


def _record_snap_overlay_state(snapper, fallback_point=None):
    mode = getattr(snapper, 'cursorMode', None)
    if mode is not None:
        mode = str(mode).lower()

    if mode in (None, '', 'passive'):
        _clear_snap_overlay_state(snapper)
        return

    point = _tracker_marker_point(getattr(snapper, 'tracker', None))

    if point is None:
        point = _coerce_vector(getattr(snapper, '_ccad_runtime_snap_point', None))

    if point is None:
        point = _coerce_vector(fallback_point) or _coerce_vector(getattr(snapper, 'spoint', None))

    if point is None:
        _clear_snap_overlay_state(snapper)
        return

    try:
        snapper._ccad_snap_mode = mode
        snapper._ccad_snap_point = point
        snapper._ccad_snap_direction = _coerce_vector(getattr(snapper, '_ccad_runtime_snap_direction', None))
    except Exception:
        pass


def _hide_builtin_snap_marker(snapper):
    tracker = getattr(snapper, 'tracker', None)
    if tracker is not None:
        try:
            tracker.off()
        except Exception:
            pass


def _run_snap(self, screenpos, lastpoint=None, active=True, constrain=False, noTracker=False):
    _begin_snap_overlay_cycle(self)
    point = _original_snap(
        self,
        screenpos,
        lastpoint=lastpoint,
        active=active,
        constrain=constrain,
        noTracker=noTracker,
    )
    tangent_point = _apply_custom_tangent_snap(self, screenpos, lastpoint)
    if tangent_point is not None:
        point = tangent_point
        try:
            self.spoint = tangent_point
        except Exception:
            pass
    _record_snap_overlay_state(self, fallback_point=point)
    _hide_builtin_snap_marker(self)
    return point


def _set_focus_on_length(enabled):
    try:
        App.ParamGet(_DRAFT_PREFS_PATH).SetBool("focusOnLength", bool(enabled))
    except Exception:
        pass


def _repair_stale_length_focus():
    try:
        prefs = App.ParamGet(_PREF_GROUP)
        if prefs.GetBool("OwnsFocusOnLength", False):
            _set_focus_on_length(False)
            prefs.SetBool("OwnsFocusOnLength", False)
    except Exception:
        pass


def _ortho_snap(self, screenpos, lastpoint=None, active=True, constrain=False, noTracker=False):
    """Patched Snapper.snap: forces ortho when F8 is ON.

    Uses FreeCAD's native constraint so the rubberband/tracker draws along
    the ortho axis.  After snapping, if the snapper detected a real object
    snap (endpoint, midpoint, …) the point is re-snapped without constraint
    so the snap wins over ortho — both visually and in the returned value.
    """
    try:
        if ClassicDraftTools._ortho_enabled and lastpoint is not None:
            cmd = getattr(App, 'activeDraftCommand', None)
            cmd_name = cmd.__class__.__name__ if cmd else ''
            if cmd_name not in _ORTHO_SUSPEND_CMDS:
                # Reset constraint state for a clean ortho pass
                self.constraintAxis = None
                self.affinity = None
                # Snap WITH constraint — gives proper ortho rubberband
                pt = _run_snap(self, screenpos, lastpoint=lastpoint,
                               active=active, constrain=True,
                               noTracker=noTracker)
                # If the snapper found a real object snap, re-snap freely
                si = getattr(self, 'snapInfo', None)
                if si and isinstance(si, dict) and si.get('Object'):
                    return _run_snap(self, screenpos,
                                     lastpoint=lastpoint,
                                     active=active, constrain=False,
                                     noTracker=noTracker)
                return pt
    except Exception:
        pass
    return _run_snap(self, screenpos, lastpoint=lastpoint,
                     active=active, constrain=constrain,
                     noTracker=noTracker)


def _is_classiccad_active():
    try:
        wb = Gui.activeWorkbench()
        return bool(wb and wb.__class__.__name__ == "ClassicCADWorkbench")
    except Exception:
        return False


def _active_draft_command():
    return getattr(App, 'activeDraftCommand', None)


def _is_non_edit_draft_command():
    cmd = _active_draft_command()
    cls_name = getattr(getattr(cmd, '__class__', None), '__name__', '') if cmd else ''
    return bool(cmd and 'Edit' not in cls_name)


def _is_text_entry_command():
    cmd = _active_draft_command()
    cls_name = getattr(getattr(cmd, '__class__', None), '__name__', '') if cmd else ''
    return any(token in cls_name for token in ('Text', 'ShapeString', 'Label'))


def _patch_draft_method(owner, name, wrapper_factory):
    key = (owner, name)
    if key in _PATCHED_DRAFT_METHODS:
        return
    original = getattr(owner, name, None)
    if not callable(original):
        return
    setattr(owner, name, wrapper_factory(original))
    _PATCHED_DRAFT_METHODS[key] = original


def _restore_draft_patches():
    for (owner, name), original in list(_PATCHED_DRAFT_METHODS.items()):
        try:
            setattr(owner, name, original)
        except Exception:
            pass
    _PATCHED_DRAFT_METHODS.clear()


def _spinbox_for_widget(widget):
    current = widget
    while current:
        if isinstance(current, QtWidgets.QAbstractSpinBox):
            return current
        current = current.parentWidget() if hasattr(current, 'parentWidget') else None
    return None


def _navigation_identity(widget):
    return _spinbox_for_widget(widget) or widget


def _is_focusable_widget(widget):
    if widget is None:
        return False
    try:
        return widget.isVisible() and widget.isEnabled() and widget.focusPolicy() != QtCore.Qt.NoFocus
    except Exception:
        return False


def _toolbar_navigation_targets(toolbar):
    targets = []
    seen = set()
    for name in _TAB_NAVIGATION_WIDGETS:
        widget = getattr(toolbar, name, None)
        identity = _navigation_identity(widget)
        if identity is None or identity in seen:
            continue
        if _is_focusable_widget(identity):
            seen.add(identity)
            targets.append(identity)
    return targets


def _cycle_task_panel_focus(toolbar, current_widget, backwards=False):
    targets = _toolbar_navigation_targets(toolbar)
    if not targets:
        return False

    current = _navigation_identity(current_widget)
    try:
        index = targets.index(current)
    except ValueError:
        index = -1 if not backwards else 0

    step = -1 if backwards else 1
    next_index = (index + step) % len(targets)
    return _focus_input_widget(targets[next_index], toolbar)


class _TaskPanelTabFilter(QtCore.QObject):
    def __init__(self, toolbar, parent=None):
        super().__init__(parent)
        self.toolbar = toolbar

    def eventFilter(self, obj, event):
        if not _is_classiccad_active():
            return False

        if event.type() == QtCore.QEvent.ShortcutOverride:
            key = event.key()
            if key in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Backtab, QtCore.Qt.Key_Space):
                event.accept()
            return False

        if event.type() != QtCore.QEvent.KeyPress:
            return False

        key = event.key()
        if key == QtCore.Qt.Key_Space and _should_force_task_panel_confirm():
            confirmed = _force_task_panel_confirm(self.toolbar)
            if confirmed:
                event.accept()
            return confirmed

        if key not in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Backtab):
            return False

        modifiers = event.modifiers()
        backwards = key == QtCore.Qt.Key_Backtab or bool(modifiers & QtCore.Qt.ShiftModifier)
        moved = _cycle_task_panel_focus(self.toolbar, obj, backwards=backwards)
        if moved:
            event.accept()
        return moved


def _task_panel_filter_widgets(toolbar):
    widgets = []
    seen = set()
    for name in _TAB_NAVIGATION_WIDGETS:
        target = getattr(toolbar, name, None)
        identity = _navigation_identity(target)
        for widget in (identity, getattr(identity, 'lineEdit', lambda: None)() if isinstance(identity, QtWidgets.QAbstractSpinBox) else None):
            if widget is None or widget in seen:
                continue
            seen.add(widget)
            widgets.append(widget)
    return widgets


def _ensure_task_panel_tab_filter(toolbar):
    base_widget = getattr(toolbar, 'baseWidget', None)
    if not base_widget:
        return

    tab_filter = getattr(toolbar, '_ccad_task_panel_tab_filter', None)
    needs_new_filter = tab_filter is None
    if tab_filter is not None:
        try:
            needs_new_filter = tab_filter.parent() is not base_widget
        except RuntimeError:
            needs_new_filter = True
            try:
                toolbar._ccad_task_panel_tab_filter = None
            except Exception:
                pass

    if needs_new_filter:
        tab_filter = _TaskPanelTabFilter(toolbar, base_widget)
        toolbar._ccad_task_panel_tab_filter = tab_filter

    for widget in _task_panel_filter_widgets(toolbar):
        try:
            if widget.property('_ccadTaskPanelTabFilterInstalled'):
                continue
            widget.installEventFilter(tab_filter)
            widget.setProperty('_ccadTaskPanelTabFilterInstalled', True)
        except Exception:
            pass


def _focus_input_widget(widget, toolbar=None):
    target = _spinbox_for_widget(widget) or widget
    line_edit = None
    if isinstance(target, QtWidgets.QAbstractSpinBox):
        try:
            line_edit = target.lineEdit()
        except Exception:
            line_edit = None

    focus_widget = line_edit or target
    try:
        focus_widget.setFocus(QtCore.Qt.OtherFocusReason)
    except Exception:
        return False

    try:
        if line_edit:
            line_edit.selectAll()
        elif toolbar and hasattr(toolbar, 'number_length') and hasattr(target, 'setSelection') and hasattr(target, 'text'):
            target.setSelection(0, toolbar.number_length(target.text()))
        elif hasattr(target, 'selectAll'):
            target.selectAll()
    except Exception:
        pass
    return True


def _focus_length_input(toolbar=None):
    if not _is_classiccad_active():
        return False

    toolbar = toolbar or getattr(Gui, 'draftToolBar', None)
    if not toolbar:
        return False

    target = getattr(toolbar, 'lengthValue', None)
    if not target:
        return False

    try:
        visible = target.isVisible() and target.isEnabled()
    except Exception:
        visible = False
    if not visible:
        return False

    return _focus_input_widget(target, toolbar)


def _schedule_length_focus(toolbar=None, delays=None):
    if not _is_classiccad_active():
        return

    toolbar = toolbar or getattr(Gui, 'draftToolBar', None)
    if not toolbar:
        return

    for delay in (delays or _LENGTH_FOCUS_RETRY_DELAYS):
        QtCore.QTimer.singleShot(delay, lambda tb=toolbar: _focus_length_input(tb))


def _reset_toolbar_transients(toolbar=None):
    toolbar = toolbar or getattr(Gui, 'draftToolBar', None)
    if not toolbar:
        return

    for name in ('xValue', 'yValue', 'zValue', 'lengthValue', 'angleValue', 'radiusValue'):
        widget = getattr(toolbar, name, None)
        target = _spinbox_for_widget(widget) or widget
        if not target:
            continue

        line_edit = None
        if isinstance(target, QtWidgets.QAbstractSpinBox):
            try:
                line_edit = target.lineEdit()
            except Exception:
                line_edit = None

        try:
            if line_edit:
                line_edit.deselect()
                line_edit.clearFocus()
            elif hasattr(target, 'deselect'):
                target.deselect()
        except Exception:
            pass

        try:
            target.clearFocus()
        except Exception:
            pass

    for name in ('angleLock',):
        button = getattr(toolbar, name, None)
        if not isinstance(button, QtWidgets.QAbstractButton):
            continue
        try:
            button.blockSignals(True)
            button.setChecked(False)
        except Exception:
            pass
        finally:
            try:
                button.blockSignals(False)
            except Exception:
                pass


def _force_task_panel_confirm(toolbar):
    if not toolbar:
        return False

    focus_widget = QtWidgets.QApplication.focusWidget()
    spinbox = _spinbox_for_widget(focus_widget)
    if spinbox is not None:
        try:
            spinbox.interpretText()
        except Exception:
            pass

    validate_point = getattr(toolbar, 'validatePoint', None)
    if not callable(validate_point):
        return False

    try:
        return validate_point()
    except TypeError:
        try:
            return validate_point(False)
        except Exception:
            return False
    except Exception:
        return False


def _should_force_task_panel_confirm():
    return _is_classiccad_active() and _is_non_edit_draft_command() and not _is_text_entry_command()


def _install_draft_taskpanel_patches():
    _restore_draft_patches()

    try:
        import DraftGui
    except Exception:
        return

    toolbar_cls = getattr(DraftGui, 'DraftToolBar', None)
    if not toolbar_cls:
        return

    def _confirm_wrapper(original):
        def patched(self, *args, **kwargs):
            if _should_force_task_panel_confirm():
                return _force_task_panel_confirm(self)
            return original(self, *args, **kwargs)

        return patched

    for name in ('checkx', 'checky', 'checklength'):
        _patch_draft_method(toolbar_cls, name, _confirm_wrapper)

    def _extra_line_ui_wrapper(original):
        def patched(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            _schedule_length_focus(self)
            return result

        return patched

    _patch_draft_method(toolbar_cls, 'extraLineUi', _extra_line_ui_wrapper)

    def _wire_ui_wrapper(original):
        def patched(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            if not getattr(self, 'lengthValue', None) or not self.lengthValue.isVisible():
                self.extraLineUi()
            return result

        return patched

    _patch_draft_method(toolbar_cls, 'wireUi', _wire_ui_wrapper)

    def _setup_toolbar_wrapper(original):
        def patched(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            _ensure_task_panel_tab_filter(self)
            return result

        return patched

    _patch_draft_method(toolbar_cls, 'setupToolBar', _setup_toolbar_wrapper)

class ClassicDraftTools(QtCore.QObject):
    _ortho_enabled = App.ParamGet(_PREF_GROUP).GetBool("OrthoEnabled", False)
    _tangent_enabled = App.ParamGet(_PREF_GROUP).GetBool("TangentEnabled", True)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mw = Gui.getMainWindow()
        self._draft_params = App.ParamGet(_DRAFT_PREFS_PATH)
        self._hooked_snap_lock_actions = set()
        self._osnap_bind_attempts = 0
        _repair_stale_length_focus()
        # Save at instance level for compat and at module level for reliability
        self._original_focus_on_length = self._draft_params.GetBool("focusOnLength", False)
        _SAVED_PREFS['focusOnLength'] = self._original_focus_on_length
        _set_focus_on_length(True)
        App.ParamGet(_PREF_GROUP).SetBool("OwnsFocusOnLength", True)
        _install_draft_taskpanel_patches()
        
        # Install app-level event filter so F3/F8 work even during commands
        QtWidgets.QApplication.instance().installEventFilter(self)
        self.rebind_osnap_lock_actions()
        ClassicDraftTools._osnap_enabled = self._current_osnap_state()

    def restore_preferences(self):
        try:
            _set_focus_on_length(False)
            App.ParamGet(_PREF_GROUP).SetBool("OwnsFocusOnLength", False)
        except Exception:
            pass

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.KeyPress and not event.isAutoRepeat():
            key = event.key()
            if key == QtCore.Qt.Key_F3:
                self.toggle_osnap()
                return True
            if key == QtCore.Qt.Key_F8:
                self.toggle_ortho()
                return True
        return False

    def print_msg(self, text):
        if hasattr(Gui, "classic_console") and hasattr(Gui.classic_console, "history"):
            try:
                clean = text.replace("<", "&lt;").replace(">", "&gt;")
                msg = f"<span style='color:#aaaaaa; font-family:Consolas;'>{clean}</span>"
                Gui.classic_console.history.append(msg)
            except Exception: pass

    _osnap_enabled = True  # assume snaps start ON

    def _current_osnap_state(self):
        try:
            snapper = getattr(Gui, 'Snapper', None)
            if snapper and hasattr(snapper, 'isEnabled'):
                return bool(snapper.isEnabled('Lock'))
        except Exception:
            pass

        try:
            mw = self.mw or Gui.getMainWindow()
            if mw:
                for act in mw.findChildren(QtGui.QAction):
                    if act.objectName() == 'Draft_Snap_Lock' and act.isCheckable():
                        return bool(act.isChecked())
        except Exception:
            pass

        return bool(ClassicDraftTools._osnap_enabled)

    def _apply_osnap_state(self, snap_on, announce=True):
        snap_on = bool(snap_on)
        changed = (ClassicDraftTools._osnap_enabled != snap_on)
        ClassicDraftTools._osnap_enabled = snap_on

        if changed and announce:
            state = "ON" if snap_on else "OFF"
            self.print_msg(f"< OSNAP {state} >")

        QtCore.QTimer.singleShot(100, lambda: self._sync_snap_lock_button(snap_on))
        bar = getattr(Gui, 'ccad_status_bar', None)
        if bar and hasattr(bar, 'sync_osnap'):
            bar.sync_osnap()

    def _sync_osnap_from_runtime(self, announce=False):
        self._apply_osnap_state(self._current_osnap_state(), announce=announce)

    def _on_snap_lock_action_toggled(self, checked):
        self._apply_osnap_state(bool(checked), announce=True)

    def rebind_osnap_lock_actions(self):
        bound_any = False

        try:
            mw = self.mw or Gui.getMainWindow()
            if mw:
                for act in mw.findChildren(QtGui.QAction):
                    if act.objectName() != 'Draft_Snap_Lock' or not act.isCheckable():
                        continue
                    action_id = id(act)
                    if action_id in self._hooked_snap_lock_actions:
                        continue
                    act.toggled.connect(self._on_snap_lock_action_toggled)
                    self._hooked_snap_lock_actions.add(action_id)
                    bound_any = True
        except Exception:
            pass

        self._osnap_bind_attempts += 1
        if self._osnap_bind_attempts < 12:
            QtCore.QTimer.singleShot(500, self.rebind_osnap_lock_actions)

        return bound_any

    def toggle_osnap(self):
        try:
            self.rebind_osnap_lock_actions()
            Gui.runCommand('Draft_Snap_Lock', 0)
            QtCore.QTimer.singleShot(100, lambda: self._sync_osnap_from_runtime(announce=True))
        except Exception:
            self.print_msg("< OSNAP TOGGLED >")

    @staticmethod
    def _sync_snap_lock_button(snap_on):
        """Force the built-in Draft_Snap_Lock action checked state."""
        try:
            mw = Gui.getMainWindow()
            for act in mw.findChildren(QtGui.QAction):
                if act.objectName() == 'Draft_Snap_Lock' and act.isCheckable():
                    act.blockSignals(True)
                    act.setChecked(snap_on)
                    act.blockSignals(False)
        except Exception:
            pass

    def toggle_ortho(self):
        try:
            ClassicDraftTools._ortho_enabled = not ClassicDraftTools._ortho_enabled
            App.ParamGet(_PREF_GROUP).SetBool("OrthoEnabled", ClassicDraftTools._ortho_enabled)
            state = "ON" if ClassicDraftTools._ortho_enabled else "OFF"
            self.print_msg(f"< ORTHO {state} >")
            # Sync the status bar button
            bar = getattr(Gui, 'ccad_status_bar', None)
            if bar and hasattr(bar, 'sync_ortho'):
                bar.sync_ortho()
        except Exception:
            pass


def setup():
    global _original_snap
    mw = Gui.getMainWindow()
    if not mw: return
    _repair_stale_length_focus()
    _restore_draft_patches()
    
    # Cleanup old instance
    if hasattr(Gui, "ccad_draft_tools"):
        try:
            if hasattr(Gui.ccad_draft_tools, 'timer'):
                Gui.ccad_draft_tools.timer.stop()
            if hasattr(Gui.ccad_draft_tools, 'restore_preferences'):
                Gui.ccad_draft_tools.restore_preferences()
            app = QtWidgets.QApplication.instance()
            if app:
                app.removeEventFilter(Gui.ccad_draft_tools)
            Gui.ccad_draft_tools.deleteLater()
        except Exception: pass
        del Gui.ccad_draft_tools

    # Monkey-patch Snapper.snap for ortho
    from draftguitools.gui_snapper import Snapper
    if not hasattr(Snapper, '_ccad_original_snap'):
        Snapper._ccad_original_snap = Snapper.snap
    _original_snap = Snapper._ccad_original_snap
    Snapper.snap = _ortho_snap

    def _snapper_set_cursor_wrapper(original):
        def patched(self, mode=None):
            try:
                self.cursorMode = mode
            except Exception:
                pass
            _remember_runtime_snap_mode(self, mode)
            if _is_classiccad_active():
                return None
            return original(self, mode)

        return patched

    def _snapper_off_wrapper(original):
        def patched(self, *args, **kwargs):
            _clear_snap_overlay_state(self)
            return original(self, *args, **kwargs)

        return patched

    _patch_draft_method(Snapper, 'setCursor', _snapper_set_cursor_wrapper)
    _patch_draft_method(Snapper, 'off', _snapper_off_wrapper)

    Gui.ccad_draft_tools = ClassicDraftTools(mw)


def tear_down():
    global _original_snap
    from draftguitools.gui_snapper import Snapper

    # Restore focusOnLength — try instance first, fall back to module-level save
    tool = getattr(Gui, 'ccad_draft_tools', None)
    restored = False
    if tool and hasattr(tool, '_original_focus_on_length'):
        try:
            draft_params = App.ParamGet(_DRAFT_PREFS_PATH)
            draft_params.SetBool("focusOnLength", bool(tool._original_focus_on_length))
            restored = True
        except Exception:
            pass
    if not restored and 'focusOnLength' in _SAVED_PREFS:
        try:
            draft_params = App.ParamGet(_DRAFT_PREFS_PATH)
            draft_params.SetBool("focusOnLength", bool(_SAVED_PREFS['focusOnLength']))
        except Exception:
            pass
    _SAVED_PREFS.clear()

    # Outside ClassicCAD, force Draft's global length-focus preference OFF so
    # no AutoCAD-like length lock persists in other workbenches.
    _set_focus_on_length(False)
    try:
        App.ParamGet(_PREF_GROUP).SetBool("OwnsFocusOnLength", False)
    except Exception:
        pass

    # Remove event filters ClassicCAD installed on DraftToolBar widgets
    toolbar = getattr(Gui, 'draftToolBar', None)
    if toolbar is not None:
        _reset_toolbar_transients(toolbar)
        tab_filter = getattr(toolbar, '_ccad_task_panel_tab_filter', None)
        if tab_filter is not None:
            base = getattr(toolbar, 'baseWidget', None)
            if base is not None:
                try:
                    for widget in base.findChildren(QtWidgets.QWidget):
                        try:
                            if widget.property('_ccadTaskPanelTabFilterInstalled'):
                                widget.removeEventFilter(tab_filter)
                                widget.setProperty('_ccadTaskPanelTabFilterInstalled', False)
                        except Exception:
                            pass
                except Exception:
                    pass
        try:
            toolbar._ccad_task_panel_tab_filter = None
        except Exception:
            pass

    if hasattr(Snapper, '_ccad_original_snap'):
        Snapper.snap = Snapper._ccad_original_snap
        del Snapper._ccad_original_snap
    _restore_draft_patches()
    _original_snap = None


if __name__ == "__main__":
    setup()