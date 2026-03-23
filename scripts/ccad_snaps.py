import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore, QtGui, QtWidgets
import Draft

class SnapChildOverlay(QtWidgets.QWidget):
    def __init__(self, viewport):
        super().__init__(viewport) # Παιδί του Viewport
        self.viewport = viewport
        
        # Ρυθμίσεις για διαφάνεια και ignore mouse
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self._active_snap = False
        self._snap_pos = QtCore.QPoint(0, 0)
        self._snap_type = "Generic"
        
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_logic)
        self.timer.start(15)
        
        self.show()

    def update_logic(self):
        # Πάντα συγχρονισμένο μέγεθος
        if self.size() != self.viewport.size():
            self.resize(self.viewport.size())
            self.raise_()

        try:
            snapper = Draft.Snapper
            if hasattr(snapper, "active") and snapper.active:
                point = snapper.snapPoint
                if point:
                    view = Gui.activeView()
                    # Μετατροπή 3D σε 2D Pixels
                    pos_2d = view.getPoint(point.x, point.y, point.z)
                    self._snap_pos = QtCore.QPoint(int(pos_2d[0]), int(pos_2d[1]))
                    
                    # Διάβασμα τύπου από το status bar
                    msg = Gui.getMainWindow().statusBar().currentMessage()
                    if "Endpoint" in msg: self._snap_type = "Endpoint"
                    elif "Midpoint" in msg: self._snap_type = "Midpoint"
                    elif "Center" in msg: self._snap_type = "Center"
                    elif "Intersection" in msg: self._snap_type = "Intersection"
                    elif "Perpendicular" in msg: self._snap_type = "Perpendicular"
                    else: self._snap_type = "Generic"

                    self._active_snap = True
                    self.update()
                    return
            
            if self._active_snap:
                self._active_snap = False
                self.update()
        except:
            self._active_snap = False

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        
        # --- DEBUG LINE: Αν βλέπεις ένα λεπτό κόκκινο πλαίσιο, το script δουλεύει! ---
        # painter.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.red, 1))
        # painter.drawRect(0, 0, self.width()-1, self.height()-1)
        
        if not self._active_snap:
            return

        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 255, 0), 2))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        
        x, y = self._snap_pos.x(), self._snap_pos.y()
        s = 16 

        if self._snap_type == "Endpoint":
            painter.drawRect(x - s//2, y - s//2, s, s)
        elif self._snap_type == "Midpoint":
            path = QtGui.QPainterPath()
            path.moveTo(x, y - s//2)
            path.lineTo(x + s//2, y + s//2)
            path.lineTo(x - s//2, y + s//2)
            path.closeSubpath()
            painter.drawPath(path)
        elif self._snap_type == "Center":
            painter.drawEllipse(QtCore.QPoint(x, y), s//2, s//2)
        elif self._snap_type == "Intersection" or self._snap_type == "Generic":
            d = s//2
            painter.drawLine(x-d, y-d, x+d, y+d)
            painter.drawLine(x+d, y-d, x-d, y+d)
        elif self._snap_type == "Perpendicular":
            d = s//2
            painter.drawLine(x-d, y+d, x+d, y+d)
            painter.drawLine(x-d, y+d, x-d, y-d)
            painter.drawLine(x-d, y, x, y)
            painter.drawLine(x, y, x, y+d)

def setup():
    mw = Gui.getMainWindow()
    
    # Καθαρισμός προηγούμενων
    if hasattr(Gui, "ccad_snap_child_overlay"):
        try:
            Gui.ccad_snap_child_overlay.timer.stop()
            Gui.ccad_snap_child_overlay.deleteLater()
        except: pass

    # Εύρεση του Viewport
    target = None
    for w in mw.findChildren(QtWidgets.QWidget):
        if "View3DInventor" in w.metaObject().className() and w.isVisible():
            target = w
            break
    
    if target:
        # Μηδενίζουμε τα native snaps
        p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
        p.SetInt("SnapSize", 0)
        
        Gui.ccad_snap_child_overlay = SnapChildOverlay(target)
        App.Console.PrintLog("ClassicCAD: SNAP OVERLAY CHILD-MODE ACTIVE.\n")

# Εκτέλεση με delay
QtCore.QTimer.singleShot(2000, setup)