import FreeCADGui as Gui
import FreeCAD as App
import time
from PySide6 import QtWidgets, QtCore, QtGui
import ccad_cmd_xline


def _has_active_draft_command():
    """True if a non-Edit Draft command is running or in continue-mode gap."""
    if hasattr(App, 'activeDraftCommand') and App.activeDraftCommand:
        cls = App.activeDraftCommand.__class__.__name__ or ''
        if 'Edit' not in cls:
            return True
    blocker = getattr(Gui, 'ccad_auto_blocker', None)
    if blocker and time.time() - blocker._last_cmd_time < 1.0:
        return True
    return False


def _close_dialog_safe():
    """Close task panel only when a Draft command is actually active."""
    if hasattr(App, 'activeDraftCommand') and App.activeDraftCommand:
        try:
            Gui.Control.closeDialog()
        except Exception:
            pass


def _keep_edit_tools_enabled():
    """Re-enable workbench actions while Draft_Edit grips are open."""
    try:
        cmd = getattr(App, 'activeDraftCommand', None)
        cls_name = cmd.__class__.__name__ if cmd else ''
        if 'Edit' not in cls_name:
            return

        mw = Gui.getMainWindow()
        if not mw:
            return

        for action in mw.findChildren(QtGui.QAction):
            try:
                name = action.objectName() or ''
                if (
                    name.startswith(('Draft_', 'Std_', 'Part_', 'Sketcher_', 'Arch_', 'BIM_'))
                    or name.endswith('_CCAD')
                    or name.startswith('CCAD_')
                    or 'ClassicCAD' in name
                ):
                    action.setEnabled(True)
            except Exception:
                pass

        for widget in mw.findChildren(QtWidgets.QWidget):
            try:
                if isinstance(widget, (QtWidgets.QToolButton, QtWidgets.QPushButton)):
                    widget.setEnabled(True)
            except Exception:
                pass
    except Exception:
        pass


# =========================================================
# SELECTION BOX WIDGET
# =========================================================
class SelectionBox(QtWidgets.QWidget):
    def __init__(self, target_viewport):
        super().__init__(target_viewport)
        self.viewport = target_viewport
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self.setStyleSheet('background: transparent;')
        self.start_pos = None
        self.current_pos = None
        self.is_active = False
        self.preview_rects = []
        self.resize(self.viewport.size())
        self.hide()

    def paintEvent(self, event):
        if not self.is_active or not self.start_pos or not self.current_pos:
            return

        painter = QtGui.QPainter(self)
        rect = QtCore.QRect(self.start_pos, self.current_pos).normalized()
        crossing = self.current_pos.x() < self.start_pos.x()

        if crossing:
            painter.setBrush(QtGui.QColor(0, 255, 0, 60))
            painter.setPen(QtGui.QPen(QtCore.Qt.white, 1, QtCore.Qt.DashLine))
        else:
            painter.setBrush(QtGui.QColor(0, 100, 255, 60))
            painter.setPen(QtGui.QPen(QtCore.Qt.white, 1, QtCore.Qt.SolidLine))
        painter.drawRect(rect)

        if self.preview_rects:
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 120), 1, QtCore.Qt.DotLine))
            for prect in self.preview_rects:
                painter.drawRect(prect)


# =========================================================
# NATIVE FREECAD BOX SELECTION (Two-click mode)
# =========================================================
class CCADSelectionLogic(QtCore.QObject):
    """
    AutoCAD-like two-click selection box driven by Coin3D viewer callbacks.
    """

    def __init__(self, viewport):
        super().__init__(viewport)
        self.viewport = viewport
        self.state = 0
        self.raw_start = None
        self.raw_current = None
        self._mouse_cb = None
        self._move_cb = None
        self._view = None
        self._suppress_qt_until = 0.0
        self._allow_native_event_until = 0.0
        self._native_box_active = False
        self.box = SelectionBox(viewport)
        try:
            self.viewport.installEventFilter(self)
        except Exception:
            pass
        self._install_callbacks()

    def _install_callbacks(self):
        try:
            self._view = Gui.activeView()
            if not self._view:
                return
            self._mouse_cb = self._view.addEventCallback("SoMouseButtonEvent", self._coin_mouse)
            self._move_cb = self._view.addEventCallback("SoLocation2Event", self._coin_move)
        except Exception as exc:
            App.Console.PrintWarning("ClassicCAD: failed to install selection callbacks: %s\n" % exc)

    def remove_callbacks(self):
        try:
            if self._view and self._mouse_cb:
                self._view.removeEventCallback("SoMouseButtonEvent", self._mouse_cb)
        except Exception:
            pass
        try:
            if self._view and self._move_cb:
                self._view.removeEventCallback("SoLocation2Event", self._move_cb)
        except Exception:
            pass
        self._mouse_cb = None
        self._move_cb = None
        self._view = None

    def eventFilter(self, obj, event):
        try:
            et = event.type()
            now = time.time()
            mouse_events = (
                QtCore.QEvent.MouseButtonPress,
                QtCore.QEvent.MouseButtonRelease,
                QtCore.QEvent.MouseButtonDblClick,
            )
            button = event.button() if hasattr(event, 'button') else QtCore.Qt.NoButton

            if now < self._suppress_qt_until and et in mouse_events:
                return button == QtCore.Qt.LeftButton

            # While our two-click mode is active, only intercept the real left
            # click used to confirm the box. Let middle/right clicks pass
            # through so panning and context actions still work, and cancel the
            # armed selection if the user starts one of those interactions.
            if self.state == 1 and et in mouse_events:
                if button in (QtCore.Qt.MiddleButton, QtCore.Qt.RightButton):
                    if et == QtCore.QEvent.MouseButtonPress:
                        self.cancel_box()
                    return False
                if button != QtCore.Qt.LeftButton:
                    return False
                if now < self._allow_native_event_until:
                    return False
                return True
        except Exception:
            pass
        return False


    def _get_viewer(self):
        try:
            view = Gui.activeView()
            return view.getViewer() if view else None
        except Exception:
            return None

    def _stop_native_box_mode(self, abort=False):
        self._native_box_active = False
        try:
            viewer = self._get_viewer()
            if viewer:
                if hasattr(viewer, 'isSelecting') and viewer.isSelecting():
                    if abort and hasattr(viewer, 'abortSelection'):
                        viewer.abortSelection()
                    elif hasattr(viewer, 'stopSelection'):
                        viewer.stopSelection()
                if hasattr(viewer, 'setSelectionEnabled'):
                    viewer.setSelectionEnabled(True)
        except Exception:
            pass

    def cancel_box(self):
        self.state = 0
        self.raw_start = None
        self.raw_current = None
        self.box.start_pos = None
        self.box.current_pos = None
        self.box.preview_rects = []
        self.box.is_active = False
        self.box.hide()
        self._stop_native_box_mode(abort=True)

    def _send_native_mouse_event(self, event_type, qpos, buttons):
        try:
            local = QtCore.QPointF(qpos)
            global_pos = self.viewport.mapToGlobal(qpos)
            global_f = QtCore.QPointF(global_pos)
            button = QtCore.Qt.LeftButton if event_type != QtCore.QEvent.MouseMove else QtCore.Qt.NoButton
            ev = QtGui.QMouseEvent(
                event_type,
                local,
                global_f,
                button,
                buttons,
                QtCore.Qt.NoModifier,
            )
            self._allow_native_event_until = time.time() + 0.35
            QtWidgets.QApplication.sendEvent(self.viewport, ev)
            return True
        except Exception:
            return False

    def _dispatch_coin_event(self, event):
        viewer = self._get_viewer()
        if not viewer:
            return False

        # Prefer the viewer's native SoEvent pipeline so FreeCAD's own
        # rubber-band selection starts drawing immediately.
        try:
            mgr = viewer.getSoEventManager() if hasattr(viewer, 'getSoEventManager') else None
            if mgr and hasattr(mgr, 'processEvent'):
                self._allow_native_event_until = time.time() + 0.35
                mgr.processEvent(event)
                return True
        except Exception:
            pass

        return False

    def _send_native_selection_event(self, kind, qpos):
        try:
            from pivy import coin

            raw = self._qpoint_to_raw(qpos)
            pos = coin.SbVec2s(int(raw[0]), int(raw[1]))

            if kind == 'move':
                ev = coin.SoLocation2Event()
                ev.setPosition(pos)
            else:
                ev = coin.SoMouseButtonEvent()
                ev.setButton(coin.SoMouseButtonEvent.BUTTON1)
                ev.setState(coin.SoButtonEvent.DOWN if kind == 'down' else coin.SoButtonEvent.UP)
                ev.setPosition(pos)

            if self._dispatch_coin_event(ev):
                return True
        except Exception:
            pass

        # Fallback for builds where the SoEventManager isn't exposed.
        if kind == 'move':
            return self._send_native_mouse_event(QtCore.QEvent.MouseMove, qpos, QtCore.Qt.LeftButton)
        if kind == 'down':
            return self._send_native_mouse_event(QtCore.QEvent.MouseButtonPress, qpos, QtCore.Qt.LeftButton)
        return self._send_native_mouse_event(QtCore.QEvent.MouseButtonRelease, qpos, QtCore.Qt.NoButton)

    def _raw_to_qpoint(self, pos):
        # Coin callback coordinates are good for picking, but in this FreeCAD build
        # they are visually offset from the QWidget overlay. For drawing the rubber
        # band, trust the real Qt cursor position relative to the viewport.
        try:
            gp = QtGui.QCursor.pos()
            qp = self.viewport.mapFromGlobal(gp)
            return QtCore.QPoint(int(qp.x()), int(qp.y()))
        except Exception:
            x, y = int(pos[0]), int(pos[1])
            h = self.viewport.height()
            return QtCore.QPoint(x, max(0, h - y))

    def _qpoint_to_raw(self, pt):
        # Convert the visually aligned Qt overlay coordinates back to the viewer
        # coordinates expected by ActiveView.getObjectsInfo().
        try:
            ratio = float(self.viewport.devicePixelRatioF())
        except Exception:
            ratio = 1.0
        x = int(round(pt.x() * ratio))
        y = int(round((self.viewport.height() - pt.y()) * ratio))
        return (x, y)

    def _raw_to_qpoint_math(self, pos):
        # True mathematical conversion from viewer/raw coordinates to Qt widget
        # coordinates. Use this for projected object geometry, NOT for the live
        # cursor/rubber-band display.
        try:
            ratio = float(self.viewport.devicePixelRatioF())
        except Exception:
            ratio = 1.0

        x = int(round(float(pos[0]) / ratio))
        y = int(round(self.viewport.height() - (float(pos[1]) / ratio)))
        return QtCore.QPoint(x, y)

    def _current_preselection_name(self):
        try:
            pre = Gui.Selection.getPreselection()
            if pre and getattr(pre, 'ObjectName', None):
                return pre.ObjectName
        except Exception:
            pass
        return ""

    def _as_qpoint(self, pos):
        if hasattr(pos, 'x') and hasattr(pos, 'y'):
            return QtCore.QPoint(int(pos.x()), int(pos.y()))
        return self._raw_to_qpoint(pos)

    def _start_box(self, start_pos):
        qpos = self._as_qpoint(start_pos)
        self.raw_start = self._qpoint_to_raw(qpos)
        self.raw_current = self.raw_start
        self.box.start_pos = QtCore.QPoint(qpos)
        self.box.current_pos = QtCore.QPoint(qpos)
        self.box.preview_rects = []
        self.box.is_active = True
        self.box.resize(self.viewport.size())
        if not self.box.isVisible():
            self.box.show()
        self.box.raise_()
        try:
            cursor = getattr(Gui, 'ccad_cursor', None)
            if cursor:
                cursor.lower()
        except Exception:
            pass
        self.box.update()
        self.state = 1

        try:
            Gui.getMainWindow().setFocus()
        except Exception:
            pass

        try:
            self._stop_native_box_mode(abort=True)
        except Exception:
            pass

    def _update_box(self, current_pos):
        qpos = self._as_qpoint(current_pos)
        self.raw_current = self._qpoint_to_raw(qpos)
        self.box.current_pos = QtCore.QPoint(qpos)
        self.box.is_active = True
        self.box.resize(self.viewport.size())
        if not self.box.isVisible():
            self.box.show()
        self.box.raise_()
        try:
            cursor = getattr(Gui, 'ccad_cursor', None)
            if cursor:
                cursor.lower()
        except Exception:
            pass
        self._update_preview()

    def _finish_box(self, end_pos):
        qpos = self._as_qpoint(end_pos)
        self._update_box(qpos)
        self._perform_selection()
        self.box.is_active = False
        self.box.hide()
        self._suppress_qt_until = time.time() + 0.60
        self._stop_native_box_mode(abort=True)
        self.state = 0

    def _coin_mouse(self, info):
        try:
            if hasattr(Gui, 'ccad_xline_handler') and Gui.ccad_xline_handler:
                return
            if hasattr(Gui, 'ccad_trim_handler') and Gui.ccad_trim_handler:
                return
            if hasattr(Gui, 'ccad_fillet_handler') and Gui.ccad_fillet_handler:
                return
            if _has_active_draft_command():
                return

            state = str(info.get("State", ""))
            button = str(info.get("Button", ""))
            pos = info.get("Position", None)

            if not pos:
                return

            is_left = "BUTTON1" in button or "LEFT" in button
            is_right = "BUTTON2" in button or "RIGHT" in button

            if is_right and state == "DOWN":
                if self.state == 1:
                    self.cancel_box()
                return

            if not is_left or state != "UP":
                return

            if self.state == 1:
                self._finish_box(pos)
                return

            if self._current_preselection_name():
                return

            self._start_box(pos)
        except Exception as exc:
            App.Console.PrintWarning("ClassicCAD: selection mouse callback warning: %s\n" % exc)

    def _coin_move(self, info):
        try:
            if self.state != 1:
                return
            pos = info.get("Position", None)
            if not pos:
                return
            self._update_box(pos)

            # Keep FreeCAD's native rubber-band rectangle visually updated
            # while the first-to-second click selection is active.
            if self._native_box_active:
                qpos = self._as_qpoint(pos)
                self._send_native_selection_event('move', qpos)
        except Exception as exc:
            App.Console.PrintWarning("ClassicCAD: selection move callback warning: %s\n" % exc)

    def _get_projection(self):
        try:
            from pivy import coin
            view = Gui.activeView()
            if not view:
                return None
            cam = view.getCameraNode()
            vol = cam.getViewVolume()
            w = self.viewport.width()
            h = self.viewport.height()
            return (coin, vol, w, h)
        except Exception:
            return None

    def _project_raw(self, proj, pt3d):
        coin_mod, vol, w, h = proj
        p = coin_mod.SbVec3f(float(pt3d.x), float(pt3d.y), float(pt3d.z))
        scr = coin_mod.SbVec3f()
        vol.projectToScreen(p, scr)
        v = scr.getValue()
        return (int(v[0] * w), int(v[1] * h))

    def _to_world_point(self, obj, p):
        try:
            if hasattr(obj, 'getGlobalPlacement'):
                gp = obj.getGlobalPlacement()
                if gp:
                    return gp.multVec(p)
        except Exception:
            pass
        try:
            if hasattr(obj, 'Placement') and obj.Placement:
                return obj.Placement.multVec(p)
        except Exception:
            pass
        return p

    def _project_obj_qpoints(self, obj, proj):
        try:
            shape = obj.Shape
            if shape.isNull():
                return []

            pts = []
            for v in shape.Vertexes:
                pts.append(v.Point)

            for edge in shape.Edges:
                try:
                    fp, lp = edge.FirstParameter, edge.LastParameter
                    pts.append(edge.valueAt(fp))
                    pts.append(edge.valueAt(lp))
                    ctype = type(edge.Curve).__name__
                    if ctype not in ('Line', 'LineSegment'):
                        for i in range(1, 9):
                            pts.append(edge.valueAt(fp + (lp - fp) * i / 9.0))
                except Exception:
                    pass

            # Fallback to bbox corners if needed
            if not pts:
                bb = shape.BoundBox
                if bb.isValid():
                    for x in (bb.XMin, bb.XMax):
                        for y in (bb.YMin, bb.YMax):
                            for z in (bb.ZMin, bb.ZMax):
                                pts.append(App.Vector(x, y, z))

            qpts = []
            for p in pts:
                try:
                    wp = self._to_world_point(obj, p)
                    raw = self._project_raw(proj, wp)
                    qpts.append(self._raw_to_qpoint_math(raw))
                except Exception:
                    pass
            return qpts
        except Exception:
            return []

    def _object_projected_qrect(self, obj, proj):
        qpts = self._project_obj_qpoints(obj, proj)
        if not qpts:
            return None
        xs = [p.x() for p in qpts]
        ys = [p.y() for p in qpts]
        return QtCore.QRect(
            QtCore.QPoint(min(xs), min(ys)),
            QtCore.QPoint(max(xs), max(ys))
        ).normalized()

    def _object_fully_inside_qrect(self, obj, qt_rect, proj):
        # Blue window selection:
        # the old strict containment rejected many objects that looked visibly
        # inside the box. Keep crossing unchanged, but make blue selection accept
        # objects whose projected screen-bounds are mostly inside the visible box.
        obj_rect = self._object_projected_qrect(obj, proj)
        if obj_rect is None:
            return False

        outer = qt_rect.adjusted(-6, -6, 6, 6)

        if outer.contains(obj_rect):
            return True

        inter = outer.intersected(obj_rect)
        if inter.isEmpty():
            return False

        inter_area = max(1, inter.width()) * max(1, inter.height())
        obj_area = max(1, obj_rect.width()) * max(1, obj_rect.height())
        coverage = float(inter_area) / float(obj_area)

        # Accept when most of the object's projected box is inside.
        if coverage >= 0.72:
            return True

        # Fallback for long thin objects: accept when center and the first/last
        # projected sample points lie inside the blue box.
        qpts = self._project_obj_qpoints(obj, proj)
        if qpts:
            test_rect = outer.adjusted(-2, -2, 2, 2)
            cx = int(sum(p.x() for p in qpts) / len(qpts))
            cy = int(sum(p.y() for p in qpts) / len(qpts))
            center = QtCore.QPoint(cx, cy)
            first = qpts[0]
            last = qpts[-1]
            if test_rect.contains(center) and test_rect.contains(first) and test_rect.contains(last):
                return True

        return False

    def _sample_points_in_rect(self, rect):
        # Sample in Qt/widget coordinates because the visible box is drawn there.
        width = max(1, rect.width())
        height = max(1, rect.height())

        # Slight inflation helps with rounding / HiDPI mismatch.
        rect = rect.adjusted(-4, -4, 4, 4)

        inner_step = 12
        edge_step = 4
        if width < 80 or height < 80:
            inner_step = 6
            edge_step = 2

        left, right = rect.left(), rect.right()
        top, bottom = rect.top(), rect.bottom()

        xs_inner = list(range(left, right + 1, inner_step))
        ys_inner = list(range(top, bottom + 1, inner_step))
        xs_edge = list(range(left, right + 1, edge_step))
        ys_edge = list(range(top, bottom + 1, edge_step))

        pts = set()

        # Dense border sampling
        for x in xs_edge:
            pts.add((int(x), int(top)))
            pts.add((int(x), int(bottom)))
        for y in ys_edge:
            pts.add((int(left), int(y)))
            pts.add((int(right), int(y)))

        # Interior grid sampling
        for y in ys_inner:
            for x in xs_inner:
                pts.add((int(x), int(y)))

        # Always include corners, edge midpoints, and center
        cx, cy = rect.center().x(), rect.center().y()
        extras = [
            (left, top), (right, top), (left, bottom), (right, bottom),
            (cx, top), (cx, bottom), (left, cy), (right, cy),
            (cx, cy),
        ]
        for p in extras:
            pts.add((int(p[0]), int(p[1])))

        return sorted(pts)

    def _pick_objects_in_rect(self, qt_rect):
        view = Gui.activeView()
        if not view:
            return set()

        hits = set()
        for qt_pt in self._sample_points_in_rect(qt_rect):
            try:
                raw_pt = self._qpoint_to_raw(QtCore.QPoint(int(qt_pt[0]), int(qt_pt[1])))
                infos = view.getObjectsInfo(raw_pt)
            except Exception:
                infos = None
            if not infos:
                continue

            if isinstance(infos, dict):
                infos = [infos]

            for info in infos:
                try:
                    obj_name = info.get("Object")
                    if obj_name:
                        hits.add(str(obj_name))
                    parent_name = info.get("ParentObject")
                    if parent_name:
                        hits.add(str(parent_name))
                except Exception:
                    pass
        return hits


    def _visible_shape_objects(self, doc):
        objs = []
        try:
            for obj in doc.Objects:
                try:
                    if not hasattr(obj, "ViewObject") or not obj.ViewObject.Visibility:
                        continue
                    if not hasattr(obj, "Shape") or obj.Shape.isNull():
                        continue
                    objs.append(obj)
                except Exception:
                    pass
        except Exception:
            pass
        return objs

    def _blue_window_candidate_names(self, qt_rect, doc, proj):
        names = []
        preview_rects = []
        if proj is None:
            return names, preview_rects

        outer = qt_rect.adjusted(-6, -6, 6, 6)
        for obj in self._visible_shape_objects(doc):
            try:
                obj_rect = self._object_projected_qrect(obj, proj)
                if obj_rect is None:
                    continue

                if outer.contains(obj_rect):
                    names.append(obj.Name)
                    preview_rects.append(obj_rect)
                    continue

                inter = outer.intersected(obj_rect)
                if inter.isEmpty():
                    continue

                inter_area = max(1, inter.width()) * max(1, inter.height())
                obj_area = max(1, obj_rect.width()) * max(1, obj_rect.height())
                coverage = float(inter_area) / float(obj_area)

                if coverage >= 0.88:
                    names.append(obj.Name)
                    preview_rects.append(obj_rect)
            except Exception:
                pass
        return names, preview_rects

    def _update_preview(self):
        doc = App.ActiveDocument
        if not doc or not self.box.start_pos or not self.box.current_pos:
            self._preview_names = []
            self.box.preview_rects = []
            self.box.update()
            return

        qt_rect = QtCore.QRect(self.box.start_pos, self.box.current_pos).normalized()
        if qt_rect.width() < 2 and qt_rect.height() < 2:
            self._preview_names = []
            self.box.preview_rects = []
            self.box.update()
            return

        is_crossing = self.box.current_pos.x() < self.box.start_pos.x()
        proj = self._get_projection()
        preview_names = []
        preview_rects = []

        if is_crossing:
            label_map = {}
            try:
                for obj in doc.Objects:
                    label_map[obj.Label] = obj.Name
            except Exception:
                pass

            object_names = self._pick_objects_in_rect(qt_rect)
            for name in sorted(object_names):
                real_name = name
                if not doc.getObject(real_name):
                    real_name = label_map.get(name, name)
                obj = doc.getObject(real_name)
                if not obj:
                    continue
                preview_names.append(real_name)
                try:
                    if proj is not None:
                        r = self._object_projected_qrect(obj, proj)
                        if r is not None:
                            preview_rects.append(r)
                except Exception:
                    pass
        else:
            preview_names, preview_rects = self._blue_window_candidate_names(qt_rect, doc, proj)

        self._preview_names = preview_names
        self.box.preview_rects = preview_rects
        self.box.update()

    def _apply_selection_names(self, names, reopen_grips=True):
        doc = App.ActiveDocument
        if not doc:
            return

        pickadd = getattr(Gui, 'ccad_pickadd_filter', None)
        if pickadd:
            pickadd.previous_selection = []

        blocker = getattr(Gui, 'ccad_auto_blocker', None)
        if blocker:
            blocker._opening_grips = True

        if not (QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ShiftModifier):
            Gui.Selection.clearSelection()

        selected = 0
        for real_name in names:
            try:
                if doc.getObject(real_name):
                    Gui.Selection.addSelection(doc.Name, real_name)
                    selected += 1
            except Exception:
                pass

        # If Draft opened edit mode from the second click, close it back down.
        try:
            if hasattr(App, 'activeDraftCommand') and App.activeDraftCommand:
                Gui.Control.closeDialog()
        except Exception:
            pass

        App.Console.PrintMessage("ClassicCAD: box selection selected %d object(s).\n" % selected)

        if blocker:
            blocker._opening_grips = False
            sel = Gui.Selection.getSelection()
            if sel and reopen_grips:
                blocker._opening_grips = True
                QtCore.QTimer.singleShot(30, blocker._open_grips)

    def _perform_selection(self):
        view = Gui.activeView()
        doc = App.ActiveDocument
        if not view or not doc or not self.box.start_pos or not self.box.current_pos:
            return

        # Use the visible Qt/widget rectangle as the single source of truth.
        qt_rect = QtCore.QRect(self.box.start_pos, self.box.current_pos).normalized()

        if qt_rect.width() < 2 and qt_rect.height() < 2:
            return

        is_crossing = self.box.current_pos.x() < self.box.start_pos.x()

        label_map = {}
        try:
            for obj in doc.Objects:
                label_map[obj.Label] = obj.Name
        except Exception:
            pass

        proj = self._get_projection()
        final_names = []

        if is_crossing:
            object_names = self._pick_objects_in_rect(qt_rect)
            for name in sorted(object_names):
                real_name = name
                if not doc.getObject(real_name):
                    real_name = label_map.get(name, name)
                if doc.getObject(real_name):
                    final_names.append(real_name)
        else:
            final_names, _ = self._blue_window_candidate_names(qt_rect, doc, proj)

        # Apply immediately, then reinforce once more a moment later.
        # This is more stable across slow/medium/fast second-click timing.
        self._apply_selection_names(list(final_names), reopen_grips=False)
        QtCore.QTimer.singleShot(80, lambda names=list(final_names): self._apply_selection_names(names, reopen_grips=True))

# =========================================================
# AUTO GRIPS & PICK RADIUS
# =========================================================
class AutoSelectionBlocker:
    def __init__(self):
        self.recent_objects = set()
        self._is_processing = False
        self._opening_grips = False
        self._gripped_objects = []
        self._last_cmd_time = 0

    def slotCreatedObject(self, obj):
        try:
            name = obj.Name
            self.recent_objects.add(name)
            QtCore.QTimer.singleShot(200, lambda n=name: self.recent_objects.discard(n))
            QtCore.QTimer.singleShot(50, lambda n=name: self._convert_rect_to_wire(n))
        except Exception:
            pass

    def _convert_rect_to_wire(self, obj_name):
        try:
            doc = App.ActiveDocument
            if not doc: return
            obj = doc.getObject(obj_name)
            if not obj or not hasattr(obj, 'Proxy'):
                return
            if obj.Proxy.__class__.__name__ != 'Rectangle':
                return
            
            import Draft, ccad_layers
            p = obj.Placement
            h = float(obj.Height)
            l = float(obj.Length)
            base = p.Base
            rot = p.Rotation
            
            pts = [
                App.Vector(0, 0, 0),
                App.Vector(l, 0, 0),
                App.Vector(l, h, 0),
                App.Vector(0, h, 0),
            ]
            pts = [rot.multVec(pt) + base for pt in pts]
            
            # Grab layer and visual properties before deleting
            layer = ccad_layers.get_object_layer(obj) or ccad_layers.get_active_layer(doc)
            lc = None
            lw = None
            if hasattr(obj, 'ViewObject') and obj.ViewObject:
                lc = getattr(obj.ViewObject, 'LineColor', None)
                lw = getattr(obj.ViewObject, 'LineWidth', None)
            
            doc.removeObject(obj.Name)
            
            wire = Draft.make_wire(pts, closed=True, face=False)
            ccad_layers.assign_to_layer(wire, layer)
            # Transfer visual properties
            if wire and hasattr(wire, 'ViewObject') and wire.ViewObject:
                if lc is not None:
                    wire.ViewObject.LineColor = lc
                if lw is not None:
                    wire.ViewObject.LineWidth = lw
            
            doc.recompute()
        except Exception:
            pass

    def _draft_command_active(self):
        """True if a Draft drawing command (not Draft_Edit) is running."""
        if hasattr(App, 'activeDraftCommand') and App.activeDraftCommand:
            cmd = App.activeDraftCommand
            cls_name = cmd.__class__.__name__ if cmd else ''
            if 'Edit' in cls_name:
                return False
            self._last_cmd_time = time.time()
            return True
        if time.time() - self._last_cmd_time < 1.0:
            return True
        return False

    def addSelection(self, *args):
        try:
            if self._is_processing or self._opening_grips or len(args) < 2:
                return
            obj_name = args[1]
            if obj_name in self.recent_objects:
                doc_name = args[0]
                self._is_processing = True
                QtCore.QTimer.singleShot(0, lambda d=doc_name, o=obj_name: self._safe_remove(d, o))
                return
            if self._draft_command_active():
                return
            if hasattr(App, 'activeDraftCommand') and App.activeDraftCommand:
                return
            self._opening_grips = True
            QtCore.QTimer.singleShot(30, self._open_grips)
        except Exception:
            pass

    def _safe_remove(self, doc_name, obj_name):
        try:
            doc = App.ActiveDocument
            if doc and doc.getObject(obj_name):
                Gui.Selection.removeSelection(doc_name, obj_name)
        except Exception:
            pass
        self._is_processing = False

    def _open_grips(self):
        try:
            pickadd = getattr(Gui, 'ccad_pickadd_filter', None)
            if pickadd and pickadd._escaping:
                return
            if self._draft_command_active():
                return
            if hasattr(App, 'activeDraftCommand') and App.activeDraftCommand:
                return
            sel = Gui.Selection.getSelection()
            if not sel:
                return
            editable = [o for o in sel if hasattr(o, 'Shape') and not o.Shape.isNull()]
            # Skip XLine objects — own Coin markers handle their grips
            editable = [o for o in editable if not ccad_cmd_xline.is_xline(o)]
            if not editable:
                return
            doc = App.ActiveDocument
            sel_info = [(o.Document.Name, o.Name) for o in editable]
            self._gripped_objects = list(sel_info)
            Gui.runCommand("Draft_Edit")
            QtCore.QTimer.singleShot(0, _keep_edit_tools_enabled)
            QtCore.QTimer.singleShot(120, _keep_edit_tools_enabled)
            for dn, on in sel_info:
                try:
                    if doc and doc.getObject(on):
                        Gui.Selection.addSelection(dn, on)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            self._opening_grips = False

    def removeSelection(self, *args):
        pass

class SelectionManager:
    @staticmethod
    def force_pick_radius():
        try:
            view = Gui.activeView()
            if not view: return
            target_radius = 10 
            param = App.ParamGet("User parameter:BaseApp/Preferences/View")
            if param.GetInt("PickSize") != target_radius:
                param.SetInt("PickSize", target_radius)

            viewer = view.getViewer()
            if hasattr(viewer, "setPickRadius"):
                viewer.setPickRadius(float(target_radius))
            
            param.SetBool("EnablePreselection", True)
            param.SetUnsigned("PreselectionColor", 4294967040)
        except: pass

class SelectionObserver(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(250)

    def refresh(self):
        SelectionManager.force_pick_radius()
        _keep_edit_tools_enabled()
        try:
            mw = Gui.getMainWindow()
            if mw:
                _attach_viewport(mw)
        except Exception:
            pass

# =========================================================
class AdditiveSelectionFilter(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.previous_selection = []
        self.active = True
        self._escaping = False

    def handle_full_escape(self):
        if self._escaping:
            return
        self.previous_selection = []
        self._escaping = True
        blocker = getattr(Gui, 'ccad_auto_blocker', None)
        if blocker:
            blocker._opening_grips = True
            blocker._gripped_objects = []
        _close_dialog_safe()
        Gui.Selection.clearSelection()
        QtCore.QTimer.singleShot(100, self._finish_escape)

    def _finish_escape(self):
        try:
            Gui.Selection.clearSelection()
        except Exception:
            pass
        blocker = getattr(Gui, 'ccad_auto_blocker', None)
        if blocker:
            blocker._opening_grips = False
        self._escaping = False

    def eventFilter(self, obj, event):
        if not self.active or self._escaping:
            return False

        if event.type() == QtCore.QEvent.Type.KeyPress and event.key() == QtCore.Qt.Key_Escape:
            # Console text editing takes priority
            console = getattr(Gui, 'classic_console', None)
            if console and console.input.hasFocus() and console.input.text():
                return False
            # Cancel selection box
            sel_logic = getattr(Gui, 'ccad_sel_logic', None)
            if sel_logic:
                sel_logic.cancel_box()

            for attr in ('ccad_xline_handler', 'ccad_trim_handler', 'ccad_fillet_handler', 'ccad_spline_handler'):
                handler = getattr(Gui, attr, None)
                if handler:
                    cleanup = getattr(handler, '_cleanup', None)
                    if not callable(cleanup):
                        cleanup = getattr(handler, 'cleanup', None)
                    if callable(cleanup):
                        cleanup()
                    return True

            # If a non-Edit Draft command is running, let FreeCAD handle ESC
            if hasattr(App, 'activeDraftCommand') and App.activeDraftCommand:
                cls = App.activeDraftCommand.__class__.__name__ or ''
                if 'Edit' not in cls:
                    self.previous_selection = []
                    return False
            # Full escape (Edit grips or idle)
            self.handle_full_escape()
            return True

        if hasattr(Gui, 'ccad_xline_handler') and Gui.ccad_xline_handler:
            return False
        if hasattr(Gui, 'ccad_trim_handler') and Gui.ccad_trim_handler:
            return False
        if hasattr(Gui, 'ccad_fillet_handler') and Gui.ccad_fillet_handler:
            return False
        if hasattr(Gui, 'ccad_spline_handler') and Gui.ccad_spline_handler:
            return False

        try:
            if hasattr(obj, 'metaObject') and "View3DInventor" in obj.metaObject().className():
                if event.type() == QtCore.QEvent.Type.MouseButtonPress:
                    if event.button() == QtCore.Qt.MouseButton.LeftButton:
                        if event.modifiers() == QtCore.Qt.KeyboardModifier.NoModifier:
                            self.previous_selection = Gui.Selection.getSelectionEx()

                elif event.type() == QtCore.QEvent.Type.MouseButtonRelease:
                    if event.button() == QtCore.Qt.MouseButton.LeftButton:
                        if event.modifiers() == QtCore.Qt.KeyboardModifier.NoModifier:
                            QtCore.QTimer.singleShot(15, self.restore_additive)
        except Exception:
            pass
        return False

    def restore_additive(self):
        if not self.active or self._escaping:
            return
        try:
            current = Gui.Selection.getSelectionEx()
            current_names = set(s.ObjectName for s in current)
            previous_names = set(s.ObjectName for s in self.previous_selection)

            if current_names == previous_names:
                return

            doc = App.ActiveDocument
            if not current and self.previous_selection:
                self.active = False
                for old in self.previous_selection:
                    if doc and doc.getObject(old.ObjectName):
                        try:
                            Gui.Selection.addSelection(old.DocumentName, old.ObjectName)
                        except Exception:
                            pass
                self.active = True
                return

            if current and self.previous_selection:
                self.active = False
                for old in self.previous_selection:
                    if old.ObjectName not in current_names:
                        if doc and doc.getObject(old.ObjectName):
                            try:
                                Gui.Selection.addSelection(old.DocumentName, old.ObjectName)
                            except Exception:
                                pass
                self.active = True

                new_objects = current_names - previous_names
                has_edit = (hasattr(App, 'activeDraftCommand') and App.activeDraftCommand
                           and 'Edit' in (App.activeDraftCommand.__class__.__name__ or ''))
                if new_objects and has_edit:
                    self._refresh_grips(Gui.Selection.getSelection())
        except Exception:
            pass

    def _refresh_grips(self, sel):
        if self._escaping or not sel:
            return
        blocker = getattr(Gui, 'ccad_auto_blocker', None)
        if not blocker:
            return
        try:
            sel_info = [(o.Document.Name, o.Name) for o in sel]
            blocker._opening_grips = True
            blocker._gripped_objects = list(sel_info)
            _close_dialog_safe()
            # closeDialog clears selection; Draft_Edit needs it on startup
            doc = App.ActiveDocument
            for d, n in sel_info:
                try:
                    if doc and doc.getObject(n):
                        Gui.Selection.addSelection(d, n)
                except Exception:
                    pass
            Gui.runCommand("Draft_Edit")
            QtCore.QTimer.singleShot(0, _keep_edit_tools_enabled)
            QtCore.QTimer.singleShot(120, _keep_edit_tools_enabled)
            # Re-add: Draft_Edit may consume selection
            for d, n in sel_info:
                try:
                    if doc and doc.getObject(n):
                        Gui.Selection.addSelection(d, n)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            blocker._opening_grips = False

# =========================================================
# SETUP
# =========================================================
def setup():
    mw = Gui.getMainWindow()
    if not mw: return

    # Fix Draft Grid spacing zero error (gridSpacing is a string param, e.g. "10 mm")
    grid_param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
    grid_spacing_str = grid_param.GetString("gridSpacing", "")
    try:
        spacing_val = App.Units.Quantity(grid_spacing_str).Value if grid_spacing_str else 0
    except Exception:
        spacing_val = 0
    if spacing_val <= 0:
        grid_param.SetString("gridSpacing", "10 mm")
    grid_param.SetBool("SubSelection", False)

    # Raise Draft_Edit limit (default is 5)
    draft_param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
    draft_param.SetInt("DraftEditMaxObjects", 100)

    if hasattr(Gui, "ccad_sel_logic"):
        try:
            Gui.ccad_sel_logic.viewport.removeEventFilter(Gui.ccad_sel_logic)
            Gui.ccad_sel_logic.deleteLater()
        except: pass
        del Gui.ccad_sel_logic
    
    if hasattr(Gui, "ccad_auto_blocker"):
        try:
            App.removeDocumentObserver(Gui.ccad_auto_blocker)
            Gui.Selection.removeObserver(Gui.ccad_auto_blocker)
        except: pass
        del Gui.ccad_auto_blocker

    Gui.ccad_auto_blocker = AutoSelectionBlocker()
    App.addDocumentObserver(Gui.ccad_auto_blocker)
    Gui.Selection.addObserver(Gui.ccad_auto_blocker)

    _attach_viewport(mw)

    if hasattr(Gui, "ccad_selection_observer"):
        try:
            Gui.ccad_selection_observer.timer.stop()
            Gui.ccad_selection_observer.deleteLater()
        except: pass

    Gui.ccad_selection_observer = SelectionObserver()
    SelectionManager.force_pick_radius()
    App.Console.PrintLog("ClassicCAD Selection: Barebones Mode Active.\n")

    # --- ΕΝΕΡΓΟΠΟΙΗΣΗ PICKADD LOGIC ---
    app = QtWidgets.QApplication.instance()
    if hasattr(Gui, "ccad_pickadd_filter"):
        try: app.removeEventFilter(Gui.ccad_pickadd_filter)
        except: pass
    
    Gui.ccad_pickadd_filter = AdditiveSelectionFilter()
    app.installEventFilter(Gui.ccad_pickadd_filter)

def _attach_viewport(mw, retries=0):
    """Βρες το τρέχον viewport και επανασύνδεσε τη λογική αν άλλαξε document/view."""
    target = next((w for w in mw.findChildren(QtWidgets.QWidget)
                   if "View3DInventor" in w.metaObject().className() and w.isVisible()), None)
    if target:
        current = getattr(Gui, "ccad_sel_logic", None)
        try:
            if current and getattr(current, "viewport", None) is target:
                return
        except Exception:
            pass

        if current:
            try:
                current.remove_callbacks()
            except Exception:
                pass
            try:
                current.viewport.removeEventFilter(current)
            except Exception:
                pass
            try:
                current.deleteLater()
            except Exception:
                pass
            if hasattr(Gui, "ccad_sel_logic"):
                del Gui.ccad_sel_logic

        Gui.ccad_sel_logic = CCADSelectionLogic(target)
        App.Console.PrintLog("ClassicCAD Selection: Viewport attached.\n")
    elif retries < 10:
        QtCore.QTimer.singleShot(500, lambda: _attach_viewport(mw, retries + 1))

def tear_down():
    if hasattr(Gui, "ccad_sel_logic"):
        try:
            try:
                Gui.ccad_sel_logic.remove_callbacks()
            except Exception:
                pass
            try:
                Gui.ccad_sel_logic.viewport.removeEventFilter(Gui.ccad_sel_logic)
            except Exception:
                pass
            Gui.ccad_sel_logic.deleteLater()
            del Gui.ccad_sel_logic
        except:
            pass
    
    if hasattr(Gui, "ccad_auto_blocker"):
        try:
            App.removeDocumentObserver(Gui.ccad_auto_blocker)
            Gui.Selection.removeObserver(Gui.ccad_auto_blocker)
            del Gui.ccad_auto_blocker
        except: pass

    if hasattr(Gui, "ccad_selection_observer"):
        try:
            Gui.ccad_selection_observer.timer.stop()
            Gui.ccad_selection_observer.deleteLater()
            del Gui.ccad_selection_observer
        except: pass

if __name__ == "__main__":
    setup()