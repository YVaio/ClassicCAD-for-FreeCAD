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


# =========================================================
# SELECTION BOX WIDGET
# =========================================================
class SelectionBox(QtWidgets.QWidget):
    def __init__(self, target_viewport):
        super().__init__(target_viewport)
        self.viewport = target_viewport
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.start_pos = None
        self.current_pos = None
        self.is_active = False
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

# =========================================================
# SELECTION BOX LOGIC (Two-click mode)
# =========================================================
class CCADSelectionLogic(QtCore.QObject):
    DRAG_THRESHOLD = 5

    def __init__(self, viewport):
        super().__init__(viewport)
        self.viewport = viewport
        self.box = SelectionBox(viewport)
        self.viewport.installEventFilter(self)
        self.state = 0  # 0=idle, 1=first corner placed

    def cancel_box(self):
        self.state = 0
        self.box.is_active = False
        self.box.hide()

    def eventFilter(self, obj, event):
        # Let XLINE/TRIM handlers take over when active
        if hasattr(Gui, 'ccad_xline_handler') and Gui.ccad_xline_handler:
            return False
        if hasattr(Gui, 'ccad_trim_handler') and Gui.ccad_trim_handler:
            return False

        # --- LEFT PRESS ---
        if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            if _has_active_draft_command(): return False

            pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()

            # Second click → perform selection
            if self.state == 1:
                self.box.current_pos = pos
                self._perform_selection()
                self.box.is_active = False
                self.box.hide()
                self.state = 0
                return True

            # First click: object under cursor → let FreeCAD handle
            try:
                pre = Gui.Selection.getPreselection()
                if pre.ObjectName:
                    return False
            except: pass

            # First click on empty space → set first corner
            self.box.start_pos = pos
            self.box.current_pos = pos
            self.state = 1
            return True

        # --- RIGHT PRESS (cancel box) ---
        elif event.type() == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.RightButton:
            if self.state == 1:
                self.state = 0
                self.box.is_active = False
                self.box.hide()

        # --- MOUSE MOVE ---
        elif event.type() == QtCore.QEvent.MouseMove:
            if self.state == 1:
                pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
                self.box.current_pos = pos

                if not self.box.is_active:
                    dx = abs(pos.x() - self.box.start_pos.x())
                    dy = abs(pos.y() - self.box.start_pos.y())
                    if dx > self.DRAG_THRESHOLD or dy > self.DRAG_THRESHOLD:
                        self.box.is_active = True
                        self.box.show()

                self.box.update()
                return True
            return False

        # --- LEFT RELEASE (consume but no action) ---
        elif event.type() == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
            if self.state == 1:
                return True
            return False

        elif event.type() == QtCore.QEvent.Resize:
            self.box.resize(event.size())

        return False

    # ------ 3D → 2D PROJECTION (Coin3D) ------
    def _get_projection(self, view):
        """Υπολογισμός projection παραμέτρων μία φορά ανά selection."""
        try:
            from pivy import coin
            cam = view.getCameraNode()
            vol = cam.getViewVolume()
            # Use widget dimensions (logical pixels) to match mouse event coords
            w = self.viewport.width()
            h = self.viewport.height()
            return (coin, vol, w, h)
        except Exception:
            return None

    def _project(self, proj, pt3d):
        """Project ενός 3D σημείου → 2D pixel."""
        coin_mod, vol, w, h = proj
        p = coin_mod.SbVec3f(float(pt3d.x), float(pt3d.y), float(pt3d.z))
        scr = coin_mod.SbVec3f()
        vol.projectToScreen(p, scr)
        v = scr.getValue()
        return QtCore.QPoint(int(v[0] * w), int((1.0 - v[1]) * h))

    def _get_screen_points(self, obj, proj):
        """Πάρε projected 2D σημεία για ένα object (vertices + curve samples)."""
        pts = []
        try:
            shape = obj.Shape
            if shape.isNull(): return []

            # Vertices (αρκεί για ευθείες γραμμές/wires)
            for v in shape.Vertexes:
                pts.append(v.Point)

            # Sample καμπύλων ακμών (κύκλοι, τόξα, splines)
            for edge in shape.Edges:
                try:
                    ctype = type(edge.Curve).__name__
                    if ctype not in ('Line', 'LineSegment'):
                        fp, lp = edge.FirstParameter, edge.LastParameter
                        for i in range(1, 7):
                            pts.append(edge.valueAt(fp + (lp - fp) * i / 7))
                except Exception:
                    pass

            # Fallback σε BoundBox αν δεν βρέθηκαν σημεία
            if not pts:
                bb = shape.BoundBox
                if bb.isValid():
                    for x in (bb.XMin, bb.XMax):
                        for y in (bb.YMin, bb.YMax):
                            for z in (bb.ZMin, bb.ZMax):
                                pts.append(App.Vector(x, y, z))
        except Exception:
            return []

        result = []
        for p in pts:
            try:
                result.append(self._project(proj, p))
            except Exception:
                pass
        return result

    # ------ WINDOW / CROSSING SELECTION ------
    def _perform_selection(self):
        view = Gui.activeView()
        doc = App.ActiveDocument
        if not view or not doc: return

        rect = QtCore.QRect(self.box.start_pos, self.box.current_pos).normalized()
        is_crossing = self.box.current_pos.x() < self.box.start_pos.x()

        pickadd = getattr(Gui, 'ccad_pickadd_filter', None)
        if pickadd:
            pickadd.previous_selection = []

        blocker = getattr(Gui, 'ccad_auto_blocker', None)
        if blocker:
            blocker._opening_grips = True

        if not (QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ShiftModifier):
            Gui.Selection.clearSelection()

        proj = self._get_projection(view)
        if not proj:
            if blocker:
                blocker._opening_grips = False
            return

        for obj in doc.Objects:
            try:
                if not hasattr(obj, 'ViewObject') or not obj.ViewObject.Visibility:
                    continue
                if not hasattr(obj, 'Shape') or obj.Shape.isNull():
                    continue

                screen_pts = self._get_screen_points(obj, proj)
                if not screen_pts:
                    continue

                if is_crossing:
                    # Crossing: projected bounding rect τέμνει selection rect
                    xs = [p.x() for p in screen_pts]
                    ys = [p.y() for p in screen_pts]
                    obj_rect = QtCore.QRect(
                        QtCore.QPoint(min(xs), min(ys)),
                        QtCore.QPoint(max(xs), max(ys))
                    )
                    if rect.intersects(obj_rect):
                        Gui.Selection.addSelection(doc.Name, obj.Name)
                else:
                    # Window: ΟΛΑ τα σημεία μέσα στο rect
                    if all(rect.contains(p) for p in screen_pts):
                        Gui.Selection.addSelection(doc.Name, obj.Name)
            except Exception:
                continue

        # Άνοιξε grips για όλα τα επιλεγμένα objects
        if blocker:
            blocker._opening_grips = False
            sel = Gui.Selection.getSelection()
            if sel:
                blocker._opening_grips = True
                QtCore.QTimer.singleShot(30, blocker._open_grips)

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
            
            import Draft
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
            # Εφαρμογή rotation και μετατόπιση
            pts = [rot.multVec(pt) + base for pt in pts]
            
            # Αντιγραφή visual properties πριν τη διαγραφή
            layer = getattr(obj, 'Layer', None)
            
            # Διαγραφή rectangle
            doc.removeObject(obj.Name)
            
            # Δημιουργία Wire
            wire = Draft.make_wire(pts, closed=True, face=False)
            if layer and hasattr(wire, 'Layer'):
                wire.Layer = layer
            
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
        self.timer.timeout.connect(SelectionManager.force_pick_radius)
        self.timer.start(1000)

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
        if hasattr(Gui, 'ccad_xline_handler') and Gui.ccad_xline_handler:
            return False
        if hasattr(Gui, 'ccad_trim_handler') and Gui.ccad_trim_handler:
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
            # Cancel XLINE
            if hasattr(Gui, 'ccad_xline_handler') and Gui.ccad_xline_handler:
                Gui.ccad_xline_handler._cleanup()
                return True
            # Cancel TRIM/EXTEND
            if hasattr(Gui, 'ccad_trim_handler') and Gui.ccad_trim_handler:
                Gui.ccad_trim_handler._cleanup()
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
            Gui.ccad_sel_logic.box.deleteLater()
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
    """Βρες το viewport. Αν δεν είναι ακόμα έτοιμο, ξαναδοκίμασε."""
    target = next((w for w in mw.findChildren(QtWidgets.QWidget)
                   if "View3DInventor" in w.metaObject().className() and w.isVisible()), None)
    if target:
        Gui.ccad_sel_logic = CCADSelectionLogic(target)
        App.Console.PrintLog("ClassicCAD Selection: Viewport attached.\n")
    elif retries < 10:
        QtCore.QTimer.singleShot(500, lambda: _attach_viewport(mw, retries + 1))

def tear_down():
    if hasattr(Gui, "ccad_sel_logic"):
        try:
            Gui.ccad_sel_logic.viewport.removeEventFilter(Gui.ccad_sel_logic)
            Gui.ccad_sel_logic.box.deleteLater()
            Gui.ccad_sel_logic.deleteLater()
            del Gui.ccad_sel_logic
        except: pass
    
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