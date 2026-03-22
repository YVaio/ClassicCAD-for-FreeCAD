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
        self.timer.start(16)
        
        self.resize(self.viewport.size())
        self.show()
        self._cursor_forced = False

    def is_busy(self):
        if Gui.Control.activeDialog(): return True
        try:
            import DraftGui
            return hasattr(DraftGui, "sniffer") and DraftGui.sniffer and DraftGui.sniffer.active()
        except: return False

    def is_over_nav_cube(self, pos):
        """Περιοχή Navigation Cube πάνω δεξιά"""
        width = self.viewport.width()
        if pos.x() > (width - 150) and pos.y() < 150:
            return True
        return False

    def sync(self):
        if not self.viewport or not self.viewport.isVisible():
            if self._cursor_forced: QtWidgets.QApplication.restoreOverrideCursor()
            self.deleteLater()
            return
            
        if self.viewport.underMouse():
            self.mouse_pos = self.viewport.mapFromGlobal(QtGui.QCursor.pos())
            over_cube = self.is_over_nav_cube(self.mouse_pos)
            
            if over_cube:
                if self._cursor_forced:
                    QtWidgets.QApplication.restoreOverrideCursor()
                    self._cursor_forced = False
            else:
                if not self._cursor_forced:
                    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.BlankCursor)
                    self._cursor_forced = True
            
            if self.size() != self.viewport.size():
                self.resize(self.viewport.size())
            self.update()
        else:
            if self._cursor_forced:
                QtWidgets.QApplication.restoreOverrideCursor()
                self._cursor_forced = False

    def paintEvent(self, event):
        view = Gui.activeView()
        if not view: return
        if self.is_over_nav_cube(self.mouse_pos): return

        painter = QtGui.QPainter(self)
        mx, my = self.mouse_pos.x(), self.mouse_pos.y()
        busy = self.is_busy()
        
        cam_dir = view.getViewDirection()
        is_ortho = any(abs(getattr(cam_dir, a)) > 0.999999999 for a in ['x', 'y', 'z'])
        
        alpha = 150
        col_w = QtGui.QColor(255, 255, 255, alpha)
        c_x = col_w if is_ortho else QtGui.QColor(255, 50, 50, alpha)
        c_y = col_w if is_ortho else QtGui.QColor(50, 255, 50, alpha)
        c_z = col_w if is_ortho else QtGui.QColor(50, 50, 255, alpha)
        
        mat = view.getCameraOrientation().toMatrix()
        axes_data = [(mat.A11, -mat.A12, c_x, abs(cam_dir.x)), 
                     (mat.A21, -mat.A22, c_y, abs(cam_dir.y)), 
                     (mat.A31, -mat.A32, c_z, abs(cam_dir.z))]
        
        gap = 0 if busy else 5
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        
        for i, (vx, vy, col, dot) in enumerate(axes_data):
            if dot > 0.999: continue 
            mag = (vx**2 + vy**2)**0.5
            if mag > 0.001:
                unit = QtCore.QPointF(vx, vy) / mag
                painter.setPen(QtGui.QPen(col, 1))
                p_c = QtCore.QPointF(mx, my)
                painter.drawLine(p_c + unit * gap, p_c + unit * 2000)
                painter.drawLine(p_c - unit * gap, p_c - unit * 2000)

        if not busy:
            painter.setPen(QtGui.QPen(QtCore.Qt.white, 1))
            painter.drawRect(mx - 5, my - 5, 10, 10)
        painter.end()

def setup():
    def find_and_attach():
        mw = Gui.getMainWindow()
        if not mw: return
        target = next((w for w in mw.findChildren(QtWidgets.QWidget) 
                      if "View3DInventor" in w.metaObject().className() and w.isVisible()), None)
        if target and not target.findChildren(ClassicCursor): ClassicCursor(target)
        QtCore.QTimer.singleShot(2000, find_and_attach)
    find_and_attach()