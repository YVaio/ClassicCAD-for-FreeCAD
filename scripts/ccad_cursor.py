import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtWidgets, QtCore, QtGui


def _find_visible_viewport():
    try:
        mw = Gui.getMainWindow()
        if not mw:
            return None

        mdi = mw.findChild(QtWidgets.QMdiArea)
        if mdi:
            sub = mdi.activeSubWindow()
            if sub:
                for widget in sub.findChildren(QtWidgets.QWidget):
                    try:
                        if "View3DInventor" in widget.metaObject().className() and widget.isVisible():
                            return widget
                    except Exception:
                        continue

        focus_widget = QtWidgets.QApplication.focusWidget()
        if focus_widget:
            for widget in [focus_widget] + list(focus_widget.findChildren(QtWidgets.QWidget)):
                try:
                    if "View3DInventor" in widget.metaObject().className() and widget.isVisible():
                        return widget
                except Exception:
                    continue

        for widget in mw.findChildren(QtWidgets.QWidget):
            try:
                if "View3DInventor" in widget.metaObject().className() and widget.isVisible():
                    return widget
            except Exception:
                continue
    except Exception:
        pass
    return None


def _is_file_dialog_like(widget):
    if not widget:
        return False
    try:
        for candidate in (widget, widget.window()):
            if not candidate:
                continue
            if isinstance(candidate, QtWidgets.QFileDialog):
                return True
            class_name = candidate.metaObject().className() if hasattr(candidate, "metaObject") else ""
            title = (candidate.windowTitle() or "").lower()
            object_name = (candidate.objectName() or "").lower()
            if (
                "filedialog" in class_name.lower()
                or "open" in title
                or "save" in title
                or "select" in title
                or "file" in object_name
            ):
                return True
    except Exception:
        pass
    return False


def _has_blocking_dialog():
    try:
        app = QtWidgets.QApplication.instance()
        if not app:
            return False

        active_modal = app.activeModalWidget()
        if active_modal and active_modal.isVisible():
            return True

        active_popup = app.activePopupWidget()
        if active_popup and active_popup.isVisible() and _is_file_dialog_like(active_popup):
            return True

        focus_widget = app.focusWidget()
        if focus_widget and _is_file_dialog_like(focus_widget):
            return True
    except Exception:
        pass
    return False


def _command_input_active():
    try:
        console = getattr(Gui, 'classic_console', None)
        if console and hasattr(console, 'input') and console.input.hasFocus():
            return True
    except Exception:
        pass
    return False


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


def _snap_world_to_qpoint(view, viewport, point):
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

    x = int(round(float(raw[0]) / ratio))
    y = int(round(viewport.height() - (float(raw[1]) / ratio)))
    return QtCore.QPoint(x, y)


def _snap_world_direction_to_qvector(view, viewport, point, direction):
    point = _coerce_vector(point)
    direction = _coerce_vector(direction)
    if point is None or direction is None:
        return None

    start = _snap_world_to_qpoint(view, viewport, point)
    end = _snap_world_to_qpoint(view, viewport, point.add(direction))
    if start is None or end is None:
        return None

    dx = float(end.x() - start.x())
    dy = float(end.y() - start.y())
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 1e-6:
        return None
    return QtCore.QPointF(dx / length, dy / length)


def _snap_info_target_shape(snap_info):
    if not isinstance(snap_info, dict):
        return None, None

    doc = App.ActiveDocument
    obj_name = snap_info.get('Object')
    component = snap_info.get('Component') or snap_info.get('SubName')
    if not doc or not obj_name or not component:
        return None, None

    try:
        obj = doc.getObject(obj_name)
    except Exception:
        obj = None
    if obj is None:
        return None, None

    shape = getattr(obj, 'Shape', None)
    if shape is None:
        return obj, None

    try:
        if component.startswith('Vertex'):
            index = max(int(component[6:]) - 1, 0)
            if index < len(shape.Vertexes):
                return obj, shape.Vertexes[index]
        elif component.startswith('Edge'):
            index = max(int(component[4:]) - 1, 0)
            if index < len(shape.Edges):
                return obj, shape.Edges[index]
        elif component.startswith('Face'):
            index = max(int(component[4:]) - 1, 0)
            if index < len(shape.Faces):
                return obj, shape.Faces[index]
    except Exception:
        pass

    return obj, None


def _qpoint_distance(a, b):
    if a is None or b is None:
        return None
    dx = float(a.x() - b.x())
    dy = float(a.y() - b.y())
    return (dx * dx + dy * dy) ** 0.5


def _projected_snap_match(view, viewport, snapped_qpoint, point, tolerance=7.0):
    candidate = _snap_world_to_qpoint(view, viewport, point)
    if candidate is None:
        return False
    distance = _qpoint_distance(candidate, snapped_qpoint)
    return distance is not None and distance <= tolerance


def _infer_snap_mode(view, viewport, snapper, point, mode):
    raw_mode = (mode or '').lower()
    if raw_mode and raw_mode not in ('near', 'passive'):
        return raw_mode

    snapped_qpoint = _snap_world_to_qpoint(view, viewport, point)
    if snapped_qpoint is None:
        return raw_mode or None

    snap_info = getattr(snapper, 'snapInfo', None)
    _, target = _snap_info_target_shape(snap_info)
    if target is None:
        return raw_mode or None

    try:
        if hasattr(target, 'Point'):
            if _projected_snap_match(view, viewport, snapped_qpoint, target.Point):
                return 'endpoint'
            return raw_mode or 'near'

        vertexes = list(getattr(target, 'Vertexes', []) or [])
        for vertex in vertexes:
            if _projected_snap_match(view, viewport, snapped_qpoint, getattr(vertex, 'Point', None)):
                return 'endpoint'

        curve = getattr(target, 'Curve', None)
        center = getattr(curve, 'Center', None) if curve is not None else None
        if center is not None and _projected_snap_match(view, viewport, snapped_qpoint, center):
            return 'center'

        midpoint = None
        first = getattr(target, 'FirstParameter', None)
        last = getattr(target, 'LastParameter', None)
        if first is not None and last is not None and hasattr(target, 'valueAt'):
            try:
                midpoint = target.valueAt((float(first) + float(last)) * 0.5)
            except Exception:
                midpoint = None
        if midpoint is not None and _projected_snap_match(view, viewport, snapped_qpoint, midpoint):
            return 'midpoint'

        if hasattr(target, 'CenterOfMass') and _projected_snap_match(view, viewport, snapped_qpoint, target.CenterOfMass):
            return 'center'
    except Exception:
        pass

    return raw_mode or 'near'


def _current_snap_marker(view=None, viewport=None):
    """Return (mode, qpoint, color, direction) for the current snap type, if any.

    The point is the exact snap marker position computed by FreeCAD's snapper,
    while the built-in orange marker is suppressed by ClassicCAD.
    """
    if not getattr(App, 'activeDraftCommand', None):
        return None

    view = view or Gui.activeView()
    viewport = viewport or _find_visible_viewport()
    snapper = getattr(Gui, 'Snapper', None)
    mode = getattr(snapper, '_ccad_snap_mode', None) if snapper else None
    point = _coerce_vector(getattr(snapper, '_ccad_snap_point', None)) if snapper else None
    if not mode or point is None:
        return None

    qpoint = _snap_world_to_qpoint(view, viewport, point)
    if qpoint is None:
        return None

    resolved_mode = _infer_snap_mode(view, viewport, snapper, point, mode)
    direction = None
    if str(resolved_mode).lower() == 'tangent':
        direction = _snap_world_direction_to_qvector(
            view,
            viewport,
            point,
            getattr(snapper, '_ccad_snap_direction', None),
        )

    return (str(resolved_mode).lower(), qpoint, QtGui.QColor(255, 170, 55), direction)


def _draw_snap_symbol(painter, mode, center, color, direction=None):
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(QtGui.QPen(color, 1.4))
    painter.setBrush(QtCore.Qt.NoBrush)

    x = float(center.x())
    y = float(center.y())
    size = 6.0

    def pt(dx, dy):
        return QtCore.QPointF(x + dx, y + dy)

    mode = (mode or '').lower()
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
    elif mode == 'perpendicular':
        painter.drawLine(pt(-size, size), pt(-size, -size + 1))
        painter.drawLine(pt(-size, size), pt(size, size))
    elif mode == 'tangent':
        radius = size - 1.0
        painter.drawEllipse(QtCore.QRectF(x - radius, y - radius, radius * 2.0, radius * 2.0))
        line_half = radius + 1.5
        tangent_y = y - radius
        painter.drawLine(
            QtCore.QPointF(x - line_half, tangent_y),
            QtCore.QPointF(x + line_half, tangent_y),
        )
    elif mode == 'parallel':
        painter.drawLine(pt(-size, -size + 1), pt(-1, size))
        painter.drawLine(pt(1, -size), pt(size, size - 1))
    elif mode in ('extension', 'ortho'):
        painter.drawLine(pt(-size - 1, 0), pt(size + 1, 0))
        painter.drawLine(pt(0, -size - 1), pt(0, size + 1))
    elif mode in ('near', 'passive'):
        painter.drawPolygon(QtGui.QPolygonF([pt(0, -size), pt(size, 0), pt(0, size), pt(-size, 0)]))
    elif mode == 'grid':
        painter.drawLine(pt(-size, 0), pt(size, 0))
        painter.drawLine(pt(0, -size), pt(0, size))
    elif mode in ('angle', 'quadrant'):
        painter.drawPolygon(QtGui.QPolygonF([pt(0, -size), pt(size, 0), pt(0, size), pt(-size, 0)]))
    else:
        painter.drawPolygon(QtGui.QPolygonF([pt(0, -size), pt(size, 0), pt(0, size), pt(-size, 0)]))

    painter.restore()


class ClassicCursor(QtWidgets.QWidget):
    def __init__(self, target_viewport):
        super().__init__(target_viewport)
        self.viewport = target_viewport
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)

        self.mouse_pos = QtCore.QPoint(0, 0)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.sync)
        self.timer.start(16)

        try:
            self.viewport.installEventFilter(self)
            self.viewport.setMouseTracking(True)
            self.setMouseTracking(True)
            self.setCursor(QtCore.Qt.BlankCursor)
        except Exception:
            pass
        self._is_orbiting_or_panning = False
        self._cursor_state = None  # None, 'blank', 'cross'
        self._owns_override_cursor = False
        self._last_occluded = False
        self._occlusion_changed_at = 0
        self._last_hover_widget = None
        self._last_snap_marker_state = None
        self._typing_until = 0

        try:
            app = QtWidgets.QApplication.instance()
            if app:
                app.installEventFilter(self)
        except Exception:
            pass

        try:
            self.resize(self.viewport.size())
        except Exception:
            pass
        self.show()

    def _viewport_is_usable(self):
        try:
            return bool(self.viewport and self.viewport.isVisible())
        except Exception:
            return False

    def _belongs_to_viewport(self, widget):
        try:
            if widget is None:
                return False
            if widget is self or widget is self.viewport:
                return True
            if self.isAncestorOf(widget):
                return True
            if self.viewport and self.viewport.isAncestorOf(widget):
                return True
        except Exception:
            pass
        return False

    def _set_cursor(self, state, force=False, hover_widget=None):
        desired_shape = None
        if state == 'blank':
            desired_shape = QtCore.Qt.BlankCursor
        elif state == 'cross':
            desired_shape = QtCore.Qt.CrossCursor
        elif state == 'arrow':
            desired_shape = QtCore.Qt.ArrowCursor

        viewport_shape = None
        overlay_shape = None
        hover_shape = None
        try:
            if self._viewport_is_usable():
                viewport_shape = self.viewport.cursor().shape()
        except Exception:
            pass
        try:
            overlay_shape = self.cursor().shape()
        except Exception:
            pass
        try:
            if hover_widget is not None:
                hover_shape = hover_widget.cursor().shape()
        except Exception:
            pass

        if (
            not force
            and state == self._cursor_state
            and viewport_shape == desired_shape
            and overlay_shape == desired_shape
            and (hover_widget is None or hover_shape == desired_shape)
        ):
            return

        widgets = []
        for widget in (self.viewport, self, hover_widget):
            if widget is not None and widget not in widgets:
                widgets.append(widget)

        for widget in widgets:
            try:
                if desired_shape is None:
                    widget.unsetCursor()
                else:
                    widget.setCursor(desired_shape)
            except Exception:
                pass

        try:
            app = QtWidgets.QApplication
            current = app.overrideCursor()
            if desired_shape in (QtCore.Qt.BlankCursor, QtCore.Qt.CrossCursor):
                qcursor = QtGui.QCursor(desired_shape)
                if current is None:
                    app.setOverrideCursor(qcursor)
                    self._owns_override_cursor = True
                elif self._owns_override_cursor:
                    try:
                        app.changeOverrideCursor(qcursor)
                    except Exception:
                        app.restoreOverrideCursor()
                        app.setOverrideCursor(qcursor)
                elif current.shape() != desired_shape:
                    app.setOverrideCursor(qcursor)
                    self._owns_override_cursor = True
            elif self._owns_override_cursor and current is not None:
                app.restoreOverrideCursor()
                self._owns_override_cursor = False
        except Exception:
            pass

        self._cursor_state = state

    def eventFilter(self, obj, event):
        try:
            if obj is self.viewport:
                if event.type() == QtCore.QEvent.MouseButtonPress:
                    if event.button() == QtCore.Qt.MiddleButton:
                        self._is_orbiting_or_panning = True
                elif event.type() == QtCore.QEvent.MouseButtonRelease:
                    if event.button() == QtCore.Qt.MiddleButton:
                        self._is_orbiting_or_panning = False

            if event.type() in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease) and _command_input_active():
                self._typing_until = QtCore.QDateTime.currentMSecsSinceEpoch() + 180
                if self._viewport_is_usable():
                    try:
                        global_pos = QtGui.QCursor.pos()
                        pos = self.viewport.mapFromGlobal(global_pos)
                        if self.viewport.rect().contains(pos) and not self.is_over_nav_cube(pos):
                            hover_widget = QtWidgets.QApplication.widgetAt(global_pos)
                            if not self._belongs_to_viewport(hover_widget):
                                hover_widget = None
                            if self.isHidden():
                                self.show()
                                self.raise_()
                            self._last_hover_widget = hover_widget
                            self._set_cursor('blank', force=True, hover_widget=hover_widget)
                    except Exception:
                        pass
        except Exception:
            pass
        return False

    def is_busy(self):
        try:
            if hasattr(App, 'activeDraftCommand') and App.activeDraftCommand:
                cls_name = App.activeDraftCommand.__class__.__name__ or ''
                if 'Edit' not in cls_name:
                    return True
        except Exception:
            return False
        return False

    def is_over_nav_cube(self, pos):
        try:
            width = self.viewport.width()
            return pos.x() > (width - 150) and pos.y() < 150
        except Exception:
            return False

    def _selection_box_active(self):
        try:
            sel_logic = getattr(Gui, 'ccad_sel_logic', None)
            box = getattr(sel_logic, 'box', None) if sel_logic else None
            return bool(box and getattr(box, 'is_active', False) and box.isVisible())
        except Exception:
            return False

    def sync(self):
        try:
            wb = Gui.activeWorkbench()
            if not wb or wb.__class__.__name__ != "ClassicCADWorkbench":
                if self.isVisible():
                    self.hide()
                self._last_snap_marker_state = None
                self._set_cursor(None)
                return
        except Exception:
            return

        if not self._viewport_is_usable():
            if self.isVisible():
                self.hide()
            self._last_snap_marker_state = None
            self._set_cursor(None)
            return

        if _has_blocking_dialog():
            if self.isVisible():
                self.hide()
            self._last_snap_marker_state = None
            self._set_cursor(None, force=True)
            return

        if _command_input_active():
            try:
                global_pos = QtGui.QCursor.pos()
                pos = self.viewport.mapFromGlobal(global_pos)
                outside = not self.viewport.rect().contains(pos)
            except Exception:
                outside = True

            if outside:
                if self.isVisible():
                    self.hide()
                self._last_snap_marker_state = None
                self._set_cursor(None)
                return

        resized = False
        try:
            if self.size() != self.viewport.size():
                self.resize(self.viewport.size())
                resized = True
        except Exception:
            return

        if self._is_orbiting_or_panning:
            if self.isVisible():
                self.hide()
            self._last_snap_marker_state = None
            self._set_cursor('cross')
            return

        try:
            global_pos = QtGui.QCursor.pos()
            pos = self.viewport.mapFromGlobal(global_pos)
            widget_under_mouse = QtWidgets.QApplication.widgetAt(global_pos)
            hover_widget = widget_under_mouse if self._belongs_to_viewport(widget_under_mouse) else None
            is_occluded = widget_under_mouse is not None and hover_widget is None
        except Exception:
            return

        try:
            outside = not self.viewport.rect().contains(pos)
        except Exception:
            outside = True

        now_ms = QtCore.QDateTime.currentMSecsSinceEpoch()
        if is_occluded != self._last_occluded:
            self._last_occluded = is_occluded
            self._occlusion_changed_at = now_ms

        occlusion_stable = (now_ms - self._occlusion_changed_at) > 120
        typing_active = _command_input_active() and now_ms < self._typing_until

        if outside:
            if self.isVisible():
                self.hide()
            self._last_snap_marker_state = None
            self._last_hover_widget = None
            self._set_cursor(None, force=(self._cursor_state is not None))
        elif self.is_over_nav_cube(pos):
            if self.isVisible():
                self.hide()
            self._last_snap_marker_state = None
            self._last_hover_widget = hover_widget
            self._set_cursor('arrow', force=True, hover_widget=hover_widget)
        elif is_occluded and occlusion_stable:
            if self.isVisible():
                self.hide()
            self._last_snap_marker_state = None
            self._last_hover_widget = None
            self._set_cursor(None, force=(self._cursor_state is not None))
        else:
            if self.isHidden():
                self.show()
            if self._selection_box_active():
                try:
                    self.lower()
                except Exception:
                    pass
            else:
                self.raise_()
            force_blank = (
                typing_active
                or self._cursor_state != 'blank'
                or hover_widget is not self._last_hover_widget
            )
            self._last_hover_widget = hover_widget
            self._set_cursor('blank', force=force_blank, hover_widget=hover_widget)
            snap_marker = _current_snap_marker(view=Gui.activeView(), viewport=self.viewport)
            snap_state = None
            if snap_marker:
                mode, qpoint, _, direction = snap_marker
                if direction is not None:
                    snap_state = (
                        mode,
                        int(qpoint.x()),
                        int(qpoint.y()),
                        round(float(direction.x()), 4),
                        round(float(direction.y()), 4),
                    )
                else:
                    snap_state = (mode, int(qpoint.x()), int(qpoint.y()))

            needs_update = resized or snap_state != self._last_snap_marker_state or pos != self.mouse_pos
            self._last_snap_marker_state = snap_state
            if pos != self.mouse_pos:
                self.mouse_pos = pos
            if needs_update:
                self.update()

    def paintEvent(self, event):
        try:
            view = Gui.activeView()
            if not view:
                return
        except Exception:
            return

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)

        mx, my = self.mouse_pos.x(), self.mouse_pos.y()
        busy = self.is_busy() or self._is_orbiting_or_panning
        selection_box_active = self._selection_box_active()
        cmd = getattr(App, 'activeDraftCommand', None)
        cls_name = cmd.__class__.__name__ if cmd else ''

        cursor_mode = 'normal'
        if getattr(Gui, 'ccad_trim_handler', None) or getattr(Gui, 'ccad_fillet_handler', None) or getattr(Gui, 'ccad_layoff_handler', None) or getattr(Gui, 'ccad_matchprop_handler', None) or getattr(Gui, 'ccad_chamfer_handler', None):
            cursor_mode = 'pickbox'
        elif cmd and 'Stretch' in cls_name:
            step = int(getattr(cmd, 'step', 0) or 0)
            if getattr(Gui, 'ccad_pickbox_only', False) and step <= 1:
                cursor_mode = 'pickbox'
            else:
                cursor_mode = 'cross'
        elif getattr(Gui, 'ccad_pickbox_only', False):
            cursor_mode = 'cross' if selection_box_active else 'pickbox'
        else:
            try:
                if cmd:
                    modify_cmds = ('Offset', 'Move', 'Copy', 'Rotate', 'Scale', 'Mirror')
                    if any(name in cls_name for name in modify_cmds) and len(Gui.Selection.getSelection()) == 0:
                        cursor_mode = 'pickbox'
            except Exception:
                pass

        alpha = 255
        col_w = QtGui.QColor(205, 205, 205, alpha)

        cam_dir = view.getViewDirection()
        is_ortho = (abs(cam_dir.x) > 0.999999999 or abs(cam_dir.y) > 0.999999999 or abs(cam_dir.z) > 0.999999999)

        c_x = col_w if is_ortho else QtGui.QColor(205, 50, 50, alpha)
        c_y = col_w if is_ortho else QtGui.QColor(50, 205, 50, alpha)
        c_z = col_w if is_ortho else QtGui.QColor(50, 50, 205, alpha)

        mat = view.getCameraOrientation().toMatrix()
        axes_data = [
            (mat.A11, -mat.A12, c_x, abs(cam_dir.x)),
            (mat.A21, -mat.A22, c_y, abs(cam_dir.y)),
            (mat.A31, -mat.A32, c_z, abs(cam_dir.z)),
        ]

        gap = 0 if busy else 5

        if cursor_mode != 'pickbox':
            for vx, vy, col, dot in axes_data:
                if dot > 0.999999999:
                    continue
                mag = (vx**2 + vy**2) ** 0.5
                if mag > 0.000000001:
                    unit = QtCore.QPointF(vx, vy) / mag
                    painter.setPen(QtGui.QPen(col, 0))
                    p_c = QtCore.QPointF(mx, my)
                    painter.drawLine(p_c + unit * gap, p_c + unit * 10000)
                    painter.drawLine(p_c - unit * gap, p_c - unit * 10000)

        if cursor_mode != 'cross' and (not busy or cursor_mode == 'pickbox'):
            painter.setPen(QtGui.QPen(QtGui.QColor(col_w), 0))
            painter.drawRect(mx - 5, my - 5, 10, 10)

        snap_marker = _current_snap_marker(view=view, viewport=self.viewport)
        if snap_marker and not selection_box_active:
            mode, qpoint, color, direction = snap_marker
            _draw_snap_symbol(painter, mode, qpoint, color, direction=direction)


def _dispose_cursor():
    cursor = getattr(Gui, "ccad_cursor", None)
    if not cursor:
        return
    try:
        cursor.timer.stop()
    except Exception:
        pass
    try:
        cursor._set_cursor(None, force=True)
    except Exception:
        pass
    try:
        app = QtWidgets.QApplication.instance()
        if app:
            app.removeEventFilter(cursor)
    except Exception:
        pass
    try:
        cursor.hide()
        cursor.setParent(None)
        cursor.deleteLater()
    except Exception:
        pass
    if hasattr(Gui, "ccad_cursor"):
        del Gui.ccad_cursor


class ClassicCursorManager(QtCore.QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.ensure_attached)
        self.timer.start()
        QtCore.QTimer.singleShot(0, self.ensure_attached)

    def ensure_attached(self):
        target = _find_visible_viewport()
        if target is None:
            cursor = getattr(Gui, "ccad_cursor", None)
            if cursor:
                try:
                    cursor.hide()
                    cursor._set_cursor(None)
                except Exception:
                    pass
            return

        current = getattr(Gui, "ccad_cursor", None)
        try:
            if current and current.viewport is target:
                return
        except Exception:
            pass

        _dispose_cursor()
        try:
            Gui.ccad_cursor = ClassicCursor(target)
            App.Console.PrintLog("ClassicCAD Cursor: Viewport attached.\n")
        except Exception as exc:
            App.Console.PrintWarning("ClassicCAD Cursor: attach warning: %s\n" % exc)


def setup():
    mw = Gui.getMainWindow()
    if not mw:
        return
    tear_down()
    Gui.ccad_cursor_manager = ClassicCursorManager(mw)
    Gui.ccad_find_cursor = Gui.ccad_cursor_manager.ensure_attached


def tear_down():
    manager = getattr(Gui, "ccad_cursor_manager", None)
    if manager:
        try:
            manager.timer.stop()
            manager.deleteLater()
        except Exception:
            pass
        if hasattr(Gui, "ccad_cursor_manager"):
            del Gui.ccad_cursor_manager
    _dispose_cursor()
    if hasattr(Gui, "ccad_find_cursor"):
        del Gui.ccad_find_cursor