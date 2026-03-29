import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtWidgets, QtCore, QtGui

class ClassicCursor(QtWidgets.QWidget):
    def __init__(self, target_viewport):
        super().__init__(target_viewport)
        self.viewport = target_viewport
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        
        self.mouse_pos = QtCore.QPoint(0, 0)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.sync)
        self.timer.start(10)

        self.viewport.installEventFilter(self)
        self._is_orbiting_or_panning = False
        self._cursor_state = None  # None, 'blank', 'cross'
        
        self.resize(self.viewport.size())
        self.show()

    def _set_cursor(self, state):
        if state == self._cursor_state:
            return
        if self._cursor_state is not None:
            QtWidgets.QApplication.restoreOverrideCursor()
        if state == 'blank':
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.BlankCursor)
        elif state == 'cross':
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CrossCursor)
        else:
            self.viewport.unsetCursor()
        self._cursor_state = state

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.MouseButtonPress:
            if event.button() == QtCore.Qt.MiddleButton:
                self._is_orbiting_or_panning = True
        elif event.type() == QtCore.QEvent.MouseButtonRelease:
            if event.button() == QtCore.Qt.MiddleButton:
                self._is_orbiting_or_panning = False
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

    @staticmethod
    def _is_draft_edit_dialog():
        if not hasattr(App, 'activeDraftCommand') or not App.activeDraftCommand:
            return False
        cls_name = App.activeDraftCommand.__class__.__name__ or ''
        return 'Edit' in cls_name

    def is_over_nav_cube(self, pos):
        width = self.viewport.width()
        if pos.x() > (width - 150) and pos.y() < 150:
            return True
        return False

    def sync(self):
        try:
            if not self.viewport or not self.viewport.isVisible(): return
            wb = Gui.activeWorkbench()
            if not wb: return
        except: return
        
        if self.size() != self.viewport.size():
            self.resize(self.viewport.size())

        if self._is_orbiting_or_panning:
            if self.isVisible(): self.hide()
            self._set_cursor('cross')
            return

        global_pos = QtGui.QCursor.pos()
        pos = self.viewport.mapFromGlobal(global_pos)
        
        widget_under_mouse = QtWidgets.QApplication.widgetAt(global_pos)
        is_occluded = widget_under_mouse is not None and widget_under_mouse.window() != self.viewport.window()

        if not self.viewport.rect().contains(pos) or self.is_over_nav_cube(pos) or is_occluded:
            if self.isVisible(): self.hide()
            self._set_cursor(None)
        else:
            if self.isHidden():
                self.show()
                self.raise_()
            self._set_cursor('blank')
            if pos != self.mouse_pos:
                self.mouse_pos = pos
                self.update()

    def paintEvent(self, event):
        try:
            view = Gui.activeView()
            if not view: return
        except: return

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        
        mx, my = self.mouse_pos.x(), self.mouse_pos.y()
        busy = self.is_busy() or self._is_orbiting_or_panning
        
        # --- ΑΣΦΑΛΗΣ ΕΛΕΓΧΟΣ ΓΙΑ PICKBOX-ONLY MODE ---
        is_pickbox_cmd = False
        
        # 1. Έλεγχος για δικά μας εργαλεία που ζητάνε αντικείμενο
        if getattr(Gui, 'ccad_trim_handler', None) or getattr(Gui, 'ccad_fillet_handler', None):
            is_pickbox_cmd = True
            
        # 2. Έλεγχος για Global μεταβλητή
        elif getattr(Gui, 'ccad_pickbox_only', False):
            is_pickbox_cmd = True
            
        # 3. Έλεγχος για Draft εντολές (Offset, Move, Copy) που περιμένουν επιλογή αντικειμένου
        else:
            try:
                if hasattr(App, 'activeDraftCommand') and App.activeDraftCommand:
                    cls_name = App.activeDraftCommand.__class__.__name__ or ''
                    modify_cmds = ('Offset', 'Move', 'Copy', 'Rotate', 'Scale', 'Mirror')
                    
                    if any(cmd in cls_name for cmd in modify_cmds):
                        # Αν το selection είναι άδειο, βρισκόμαστε στη φάση "Επιλογή Αντικειμένου"
                        if len(Gui.Selection.getSelection()) == 0:
                            is_pickbox_cmd = True
            except:
                pass
        # ---------------------------------------------

        alpha = 255 
        col_w = QtGui.QColor(205, 205, 205, alpha)
        
        cam_dir = view.getViewDirection()
        is_ortho = (abs(cam_dir.x) > 0.999999999 or abs(cam_dir.y) > 0.999999999 or abs(cam_dir.z) > 0.999999999)

        c_x = col_w if is_ortho else QtGui.QColor(205, 50, 50, alpha)
        c_y = col_w if is_ortho else QtGui.QColor(50, 205, 50, alpha)
        c_z = col_w if is_ortho else QtGui.QColor(50, 50, 205, alpha)
        
        mat = view.getCameraOrientation().toMatrix()
        axes_data = [(mat.A11, -mat.A12, c_x, abs(cam_dir.x)), 
                     (mat.A21, -mat.A22, c_y, abs(cam_dir.y)), 
                     (mat.A31, -mat.A32, c_z, abs(cam_dir.z))]
        
        gap = 0 if busy else 5
        
        # Ζωγραφίζουμε τις γραμμές ΜΟΝΟ αν δεν είμαστε σε λειτουργία pickbox
        if not is_pickbox_cmd:
            for vx, vy, col, dot in axes_data:
                if dot > 0.999999999: continue 
                mag = (vx**2 + vy**2)**0.5
                if mag > 0.000000001:
                    unit = QtCore.QPointF(vx, vy) / mag
                    painter.setPen(QtGui.QPen(col, 0))
                    p_c = QtCore.QPointF(mx, my)
                    painter.drawLine(p_c + unit * gap, p_c + unit * 10000)
                    painter.drawLine(p_c - unit * gap, p_c - unit * 10000)

        # Ζωγραφίζουμε το Pickbox αν η εφαρμογή είναι idle Ή αν τρέχει λειτουργία επιλογής
        if not busy or is_pickbox_cmd:
            painter.setPen(QtGui.QPen(QtGui.QColor(col_w), 0))
            painter.drawRect(mx-5, my-5, 10, 10)

def setup():
    mw = Gui.getMainWindow()
    if not mw: return
    tear_down()
    
    def find_and_attach():
        target = None
        for w in mw.findChildren(QtWidgets.QWidget):
            if "View3DInventor" in w.metaObject().className() and w.isVisible():
                target = w
                break
        if target:
            Gui.ccad_cursor = ClassicCursor(target)
            App.Console.PrintLog("ClassicCAD Cursor: Attached Globally.\n")
        else:
            QtCore.QTimer.singleShot(1000, Gui.ccad_find_cursor)

    Gui.ccad_find_cursor = find_and_attach
    Gui.ccad_find_cursor()

def tear_down():
    if hasattr(Gui, "ccad_cursor"):
        try:
            Gui.ccad_cursor.timer.stop()
            if Gui.ccad_cursor._cursor_state is not None:
                QtWidgets.QApplication.restoreOverrideCursor()
            Gui.ccad_cursor.hide()
            Gui.ccad_cursor.setParent(None)
            Gui.ccad_cursor.deleteLater()
            del Gui.ccad_cursor
        except: pass