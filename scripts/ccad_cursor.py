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
        
        self.resize(self.viewport.size())
        self.show()
        self._cursor_forced = False

    def is_busy(self):
        try:
            # Έλεγχος Task Panel
            if Gui.Control.activeDialog():
                return True
            # Έλεγχος Draft Sniffer με προστασία από σφάλματα του Draft
            import DraftGui
            if hasattr(DraftGui, "sniffer") and DraftGui.sniffer:
                return DraftGui.sniffer.active()
        except Exception:
            # Αν το Draft workbench "σκάσει" εσωτερικά, 
            # επιστρέφουμε False για να μην κολλήσει και ο κέρσορας
            return False
        return False

    def is_over_nav_cube(self, pos):
        width = self.viewport.width()
        if pos.x() > (width - 150) and pos.y() < 150:
            return True
        return False

    def sync(self):
        try:
            active_wb = Gui.activeWorkbench().name()
        except: active_wb = ""

        if "ClassicCAD" not in active_wb:
            if self.isVisible():
                self.hide()
                if self._cursor_forced:
                    QtWidgets.QApplication.restoreOverrideCursor()
                    self._cursor_forced = False
            return

        if not self.viewport or not self.viewport.isVisible(): return
        
        if self.size() != self.viewport.size():
            self.resize(self.viewport.size())

        global_pos = QtGui.QCursor.pos()
        pos = self.viewport.mapFromGlobal(global_pos)
        
        widget_under_mouse = QtWidgets.QApplication.widgetAt(global_pos)
        is_occluded = widget_under_mouse is not None and widget_under_mouse.window() != self.viewport.window()

        if not self.viewport.rect().contains(pos) or self.is_over_nav_cube(pos) or is_occluded:
            if self.isVisible(): self.hide()
            if self._cursor_forced:
                QtWidgets.QApplication.restoreOverrideCursor()
                self._cursor_forced = False
        else:
            if self.isHidden(): 
                self.show()
                self.raise_()

            if not self._cursor_forced:
                QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.BlankCursor)
                self._cursor_forced = True
            
            if pos != self.mouse_pos:
                self.mouse_pos = pos
                self.update()

    def paintEvent(self, event):
        try:
            if "ClassicCAD" not in Gui.activeWorkbench().name(): return
        except: return

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        
        mx, my = self.mouse_pos.x(), self.mouse_pos.y()
        busy = self.is_busy()
        
        # Ρύθμιση εμφάνισης
        alpha = 255 # Πλήρης ορατότητα
        col_w = QtGui.QColor(255, 255, 255, alpha)
        
        view = Gui.activeView()
        if not view: return
        cam_dir = view.getViewDirection()
        is_ortho = (abs(cam_dir.x) > 0.999 or abs(cam_dir.y) > 0.999 or abs(cam_dir.z) > 0.999)

        c_x = col_w if is_ortho else QtGui.QColor(255, 50, 50, alpha)
        c_y = col_w if is_ortho else QtGui.QColor(50, 255, 50, alpha)
        c_z = col_w if is_ortho else QtGui.QColor(50, 50, 255, alpha)
        
        mat = view.getCameraOrientation().toMatrix()
        axes_data = [(mat.A11, -mat.A12, c_x, abs(cam_dir.x)), 
                     (mat.A21, -mat.A22, c_y, abs(cam_dir.y)), 
                     (mat.A31, -mat.A32, c_z, abs(cam_dir.z))]
        
        # ΛΕΙΤΟΥΡΓΙΑ: Αν είναι busy, το κενό μηδενίζεται
        gap = 0 if busy else 5
        
        for vx, vy, col, dot in axes_data:
            if dot > 0.999: continue 
            mag = (vx**2 + vy**2)**0.5
            if mag > 0.001:
                unit = QtCore.QPointF(vx, vy) / mag
                painter.setPen(QtGui.QPen(col, 0)) # 1 pixel πάχος
                p_c = QtCore.QPointF(mx, my)
                painter.drawLine(p_c + unit * gap, p_c + unit * 10000)
                painter.drawLine(p_c - unit * gap, p_c - unit * 10000)

        # ΛΕΙΤΟΥΡΓΙΑ: Το Pickbox σχεδιάζεται μόνο αν ΔΕΝ τρέχει εντολή
        if not busy:
            painter.setPen(QtGui.QPen(QtCore.Qt.white, 0))
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
        else:
            QtCore.QTimer.singleShot(1000, find_and_attach)

    find_and_attach()

def tear_down():
    if hasattr(Gui, "ccad_cursor"):
        try:
            # Σταμάτημα του timer αμέσως
            Gui.ccad_cursor.timer.stop()
            # Επαναφορά του κέρσορα συστήματος
            if Gui.ccad_cursor._cursor_forced:
                QtWidgets.QApplication.restoreOverrideCursor()
            # Άμεση απόκρυψη και αποδέσμευση
            Gui.ccad_cursor.hide()
            Gui.ccad_cursor.setParent(None) # Αποσύνδεση από το viewport
            Gui.ccad_cursor.deleteLater()
            del Gui.ccad_cursor
            App.Console.PrintLog("ClassicCAD Cursor: Reset Complete.\n")
        except Exception as e:
            App.Console.PrintLog(f"Cursor Tear-down failed: {str(e)}\n")