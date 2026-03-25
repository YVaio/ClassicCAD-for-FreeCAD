import FreeCADGui as Gui
import FreeCAD as App
from PySide6 import QtWidgets, QtCore, QtGui

# =========================================================
# 1. SELECTION BOX WIDGET (Παθητικό οπτικό στοιχείο)
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
        if not self.is_active or not self.start_pos or not self.current_pos: return
        painter = QtGui.QPainter(self)
        rect = QtCore.QRect(self.start_pos, self.current_pos).normalized()
        is_crossing = self.current_pos.x() < self.start_pos.x()
        
        if is_crossing:
            painter.setBrush(QtGui.QBrush(QtGui.QColor(0, 255, 0, 60)))
            painter.setPen(QtGui.QPen(QtCore.Qt.white, 1, QtCore.Qt.DashLine))
        else:
            painter.setBrush(QtGui.QBrush(QtGui.QColor(0, 100, 255, 60)))
            painter.setPen(QtGui.QPen(QtCore.Qt.white, 1, QtCore.Qt.SolidLine))
        painter.drawRect(rect)

# =========================================================
# 2. ΩΜΗ ΛΟΓΙΚΗ ΕΠΙΛΟΓΗΣ
# =========================================================
class CCADSelectionLogic(QtCore.QObject):
    def __init__(self, viewport):
        super().__init__(viewport)
        self.viewport = viewport
        self.box = SelectionBox(viewport)
        self.esc_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Esc"), self.viewport)
        self.esc_shortcut.activated.connect(self.force_escape)
        self.viewport.installEventFilter(self)
        self.state = 0 

    def force_escape(self):
        self.state = 0
        self.box.is_active = False
        self.box.hide()
        Gui.Selection.clearSelection()

    def eventFilter(self, obj, event):
        # 1. ΠΑΤΗΜΑ (PRESS)
        if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            if Gui.Control.activeDialog(): return False

            # Αν το κουτί είναι ανοιχτό -> Δεύτερο κλικ -> Ολοκλήρωση
            if self.state == 1:
                self._perform_selection()
                self.box.is_active = False
                self.box.hide()
                self.state = 0
                return True 

            # ΠΡΩΤΟ ΚΛΙΚ: Ελέγχουμε αυστηρά το Preselection
            try:
                pre = Gui.Selection.getPreselection()
                # Η διόρθωση του TypeError: Ελέγχουμε απλά αν το 'pre' δεν είναι None/False
                if pre:
                    # Υπάρχει "φωτισμένο" αντικείμενο. Άστο στο FreeCAD.
                    return False 
            except: pass

            # Δεν υπάρχει τίποτα. Ξεκινάμε το Box.
            pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
            self.box.start_pos = pos
            self.box.current_pos = pos
            self.box.is_active = True
            self.box.show()
            self.state = 1
            # Επιστρέφουμε True για να κόψουμε το "drag" του FreeCAD
            return True 

        # 2. ΑΦΗΣΗ (RELEASE)
        elif event.type() == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
            if self.state == 1:
                # Καταπίνουμε το άφημα. Ο χρήστης ΠΡΕΠΕΙ να ξανακάνει κλικ (Click-to-Click)
                return True 
            return False

        # 3. ΚΙΝΗΣΗ (MOVE)
        elif event.type() == QtCore.QEvent.MouseMove:
            if self.state == 1:
                # Ενημερώνουμε το κουτί μας
                pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
                self.box.current_pos = pos
                self.box.update()
                # Κόβουμε την κίνηση από το FreeCAD για να μην πετάξει το Disambiguation Menu
                return True 
            return False

        elif event.type() == QtCore.QEvent.Resize:
            self.box.resize(event.size())
            
        return False

    def _perform_selection(self):
        view = Gui.activeView()
        if not view: return
        rect = QtCore.QRect(self.box.start_pos, self.box.current_pos).normalized()
        mode = 1 if self.box.current_pos.x() < self.box.start_pos.x() else 0
        
        try:
            objs = view.getObjectsInRegion(int(rect.left()), int(rect.top()), int(rect.right()), int(rect.bottom()), mode)
            if not (QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ShiftModifier):
                Gui.Selection.clearSelection()

            for o in objs:
                doc_name, obj_name = "", ""
                if isinstance(o, dict):
                    doc_name = o.get('Document', App.ActiveDocument.Name if App.ActiveDocument else "")
                    obj_name = o.get('Object', o.get('ObjectName', ''))
                elif hasattr(o, 'Document') and hasattr(o, 'Name'):
                    doc_name, obj_name = o.Document.Name, o.Name
                elif hasattr(o, 'ObjectName'):
                    doc_name, obj_name = App.ActiveDocument.Name, o.ObjectName

                if doc_name and obj_name:
                    Gui.Selection.addSelection(doc_name, obj_name)
        except: pass

# =========================================================
# 3. ΔΙΑΧΕΙΡΙΣΗ AUTO GRIPS & PICK RADIUS (Το δικό σου setup)
# =========================================================
class AutoSelectionBlocker:
    def __init__(self):
        self.recent_objects = set()
        self._is_processing = False

    def slotCreatedObject(self, obj):
        try:
            self.recent_objects.add(obj.Name)
            QtCore.QTimer.singleShot(200, lambda n=obj.Name: self.recent_objects.discard(n))
            
            # Αυτόματη μετατροπή Rectangle σε Wire
            QtCore.QTimer.singleShot(50, lambda: self._convert_rect_to_wire(obj))
        except: pass

    def _convert_rect_to_wire(self, obj):
        try:
            doc = App.ActiveDocument
            if not doc or obj.Name not in doc.PropertiesList and not doc.getObject(obj.Name):
                return
            obj = doc.getObject(obj.Name)
            if not obj or not hasattr(obj, 'Proxy'):
                return
            if obj.Proxy.__class__.__name__ != 'Rectangle':
                return
            
            import Draft, DraftVecUtils
            # Πάρε τα 4 σημεία του rectangle
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

    def addSelection(self, *args):
        if self._is_processing or len(args) < 2: return
        obj_name = args[1]
        sub = args[2] if len(args) > 2 else ""

        if obj_name in self.recent_objects:
            doc = args[0]
            self._is_processing = True
            QtCore.QTimer.singleShot(0, lambda d=doc, o=obj_name: self._safe_remove(d, o))
            return

        if not sub:
            self._is_processing = True
            QtCore.QTimer.singleShot(0, self._trigger_grips)

    def _safe_remove(self, doc, obj):
        Gui.Selection.removeSelection(doc, obj)
        self._is_processing = False

    def _trigger_grips(self):
        try:
            if not Gui.Control.activeDialog() and Gui.Selection.getSelection():
                Gui.runCommand("Draft_Edit")
        except: pass
        finally:
            self._is_processing = False

    def removeSelection(self, *args):
        if self._is_processing: return
        if not Gui.Selection.getSelection():
            try:
                active_dlg = Gui.Control.activeDialog()
                if active_dlg is not None and active_dlg is not False:
                    if hasattr(active_dlg, "objectName") and active_dlg.objectName() == "Draft_Edit":
                        Gui.Control.closeDialog()
                    else:
                        Gui.Control.closeDialog()
            except: pass

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

    def eventFilter(self, obj, event):
        if not self.active: return False

        # 1. Πιάσιμο του Esc για καθαρισμό της επιλογής
        if event.type() == QtCore.QEvent.Type.KeyPress:
            if event.key() == QtCore.Qt.Key_Escape:
                self.previous_selection = []
                Gui.Selection.clearSelection()
                # Δεν κάνουμε return True, αφήνουμε το FreeCAD να λάβει το Esc 
                # για να ακυρώσει και τυχόν ενεργές εντολές.

        if "View3DInventor" in obj.metaObject().className():
            # Καταγραφή πριν καθαρίσει το FreeCAD
            if event.type() == QtCore.QEvent.Type.MouseButtonPress:
                if event.button() == QtCore.Qt.MouseButton.LeftButton:
                    if event.modifiers() == QtCore.Qt.KeyboardModifier.NoModifier:
                        self.previous_selection = Gui.Selection.getSelectionEx()

            # Ανάκτηση αφού καθαρίσει το FreeCAD
            elif event.type() == QtCore.QEvent.Type.MouseButtonRelease:
                if event.button() == QtCore.Qt.MouseButton.LeftButton:
                    if event.modifiers() == QtCore.Qt.KeyboardModifier.NoModifier:
                        QtCore.QTimer.singleShot(15, self.restore_additive)
        return False

    def restore_additive(self):
        if not self.active: return
        current = Gui.Selection.getSelectionEx()
        
        # 2. Αν το FreeCAD άδειασε την επιλογή (κλικ στο κενό), την επαναφέρουμε!
        if not current and self.previous_selection:
            self.active = False 
            for old in self.previous_selection:
                doc_name = old.DocumentName
                obj_name = old.ObjectName
                if hasattr(old, "HasSubObjects") and old.HasSubObjects:
                    sub_names = getattr(old, "SubElementNames", getattr(old, "SubObjectNames", []))
                    for sub in sub_names:
                        Gui.Selection.addSelection(doc_name, obj_name, sub)
                else:
                    Gui.Selection.addSelection(doc_name, obj_name)
            self.active = True
            return

        # Κανονική προσθετική λειτουργία για νέα κλικ
        if current and self.previous_selection:
            current_names = [s.ObjectName for s in current]
            self.active = False 
            
            for old in self.previous_selection:
                if old.ObjectName not in current_names:
                    doc_name = old.DocumentName
                    obj_name = old.ObjectName
                    
                    if hasattr(old, "HasSubObjects") and old.HasSubObjects:
                        sub_names = getattr(old, "SubElementNames", getattr(old, "SubObjectNames", []))
                        for sub in sub_names:
                            Gui.Selection.addSelection(doc_name, obj_name, sub)
                    else:
                        Gui.Selection.addSelection(doc_name, obj_name)
                        
            self.active = True

# =========================================================
# 4. SETUP
# =========================================================
def setup():
    mw = Gui.getMainWindow()
    if not mw: return

    param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
    param.SetBool("SubSelection", False) 

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

    target = next((w for w in mw.findChildren(QtWidgets.QWidget) 
                  if "View3DInventor" in w.metaObject().className() and w.isVisible()), None)
    
    if target:
        Gui.ccad_sel_logic = CCADSelectionLogic(target)

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