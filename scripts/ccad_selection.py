import FreeCADGui as Gui
import FreeCAD as App
from PySide6 import QtWidgets, QtCore, QtGui

# =========================================================
# 1. ΔΙΑΧΕΙΡΙΣΗ SELECTION & ΑΥΤΟΜΑΤΑ GRIPS (ONE-CLICK)
# =========================================================
class AutoSelectionBlocker:
    def __init__(self):
        self.recent_objects = set()
        self._is_processing = False

    def slotCreatedObject(self, obj):
        try:
            self.recent_objects.add(obj.Name)
            QtCore.QTimer.singleShot(200, lambda n=obj.Name: self.recent_objects.discard(n))
        except: pass

    def addSelection(self, *args):
        """Ενεργοποιεί τα Grips με το ΠΡΩΤΟ κλικ χρησιμοποιώντας Force-Flush"""
        if self._is_processing or len(args) < 2: return
        
        obj_name = args[1]
        sub = args[2] if len(args) > 2 else ""

        # Αποφυγή auto-select μετά από δημιουργία
        if obj_name in self.recent_objects:
            doc = args[0]
            self._is_processing = True
            QtCore.QTimer.singleShot(0, lambda d=doc, o=obj_name: self._safe_remove(d, o))
            return

        # ΑΥΤΟΜΑΤΑ GRIPS (ONE-CLICK LOGIC)
        # Αν επιλέχθηκε ολόκληρο αντικείμενο, τρέχουμε τα grips ακαριαία
        if not sub:
            self._is_processing = True
            # Το singleShot(0) σπρώχνει την εντολή στο τέλος του τρέχοντος event loop
            # επιτρέποντας στο FreeCAD να ολοκληρώσει το selection πριν τρέξει το Edit
            QtCore.QTimer.singleShot(0, self._trigger_grips)

    def _safe_remove(self, doc, obj):
        Gui.Selection.removeSelection(doc, obj)
        self._is_processing = False

    def _trigger_grips(self):
        try:
            # Έλεγχος αν υπάρχει ήδη ενεργό dialog για να μην μπερδεύουμε άλλες εντολές
            if not Gui.Control.activeDialog() and Gui.Selection.getSelection():
                Gui.runCommand("Draft_Edit")
        except: pass
        finally:
            self._is_processing = False

    def removeSelection(self, *args):
        """Κλείνει τα Grips αν δεν υπάρχει πλέον επιλογή (ασφαλές για 1.1)"""
        if self._is_processing: return
        
        # Αν καθαρίσει το selection, κλείνουμε το Edit Mode
        if not Gui.Selection.getSelection():
            try:
                active_dlg = Gui.Control.activeDialog()
                if active_dlg is not None and active_dlg is not False:
                    # Στην 1.1 το objectName μπορεί να λείπει, κλείνουμε το dialog ούτως ή άλλως
                    # αν δεν τρέχει άλλη εντολή (το Draft_Edit είναι το μόνο 'παθητικό' dialog)
                    if hasattr(active_dlg, "objectName"):
                        if active_dlg.objectName() == "Draft_Edit":
                            Gui.Control.closeDialog()
                    else:
                        Gui.Control.closeDialog()
            except: pass

class SelectionManager:
    @staticmethod
    def force_pick_radius():
        """Επιβολή του PickRadius απευθείας στον Viewer του Coin3D"""
        try:
            view = Gui.activeView()
            if not view:
                return

            # Η τιμή που θέλουμε (AutoCAD Pickbox radius)
            # Δοκίμασε 15 για να δεις αν υπάρχει τεράστια διαφορά
            target_radius = 15 

            # 1. Ενημέρωση των παραμέτρων (για το μέλλον)
            param = App.ParamGet("User parameter:BaseApp/Preferences/View")
            if param.GetInt("PickSize") != target_radius:
                param.SetInt("PickSize", target_radius)

            # 2. Απευθείας επέμβαση στον Viewer
            # Το FreeCAD 1.1 χρησιμοποιεί το SoQt / Quarter
            viewer = view.getViewer()
            if hasattr(viewer, "setPickRadius"):
                viewer.setPickRadius(float(target_radius))
            
            # 3. Ενεργοποίηση Preselection (για να βλέπουμε το αποτέλεσμα)
            param.SetBool("EnablePreselection", True)
            # Έντονο Κίτρινο
            param.SetUnsigned("PreselectionColor", 4294967040)

        except:
            pass

class SelectionObserver(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(SelectionManager.force_pick_radius)
        # Έλεγχος κάθε 1 δευτερόλεπτο
        self.timer.start(1000)

# =========================================================
# 2. CTRL+CLICK & SMART CLICK LOGIC
# =========================================================
class CCADSelectionLogic(QtCore.QObject):
    def __init__(self, viewport):
        super().__init__(viewport)
        self.viewport = viewport
        self.esc_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Esc"), self.viewport)
        self.esc_shortcut.activated.connect(self.force_escape)
        self.viewport.installEventFilter(self)

    def force_escape(self):
        Gui.Selection.clearSelection()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        self.viewport.setFocus()

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            # Αν τρέχει άλλη εντολή (π.χ. Line), αφήνουμε το FreeCAD ήσυχο
            active_dlg = Gui.Control.activeDialog()
            if active_dlg is not None and active_dlg is not False:
                try:
                    if hasattr(active_dlg, "objectName") and active_dlg.objectName() != "Draft_Edit":
                        return False
                except: return False

            # --- CTRL + CLICK: Segment Selection ---
            if event.modifiers() & QtCore.Qt.ControlModifier:
                view = Gui.activeView()
                if view:
                    info = view.getObjectInfo((event.pos().x(), event.pos().y()))
                    if info and 'Subname' in info and "Edge" in info['Subname']:
                        Gui.Selection.clearSelection()
                        Gui.Selection.addSelection(info['Document'], info['ObjectName'], info['Subname'])
                        return True

            # Επιστρέφουμε False για να γίνει το selection snappy από το FreeCAD
            return False
            
        return False

# =========================================================
# 3. SETUP
# =========================================================
def setup():
    mw = Gui.getMainWindow()
    if not mw: return

    # Ρύθμιση για AutoCAD selection style
    param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
    param.SetBool("SubSelection", False) 

    # Cleanup
    if hasattr(Gui, "ccad_sel_logic"):
        try:
            Gui.ccad_sel_logic.viewport.removeEventFilter(Gui.ccad_sel_logic)
            Gui.ccad_sel_logic.deleteLater()
        except: pass
    
    if hasattr(Gui, "ccad_auto_blocker"):
        try:
            App.removeDocumentObserver(Gui.ccad_auto_blocker)
            Gui.Selection.removeObserver(Gui.ccad_auto_blocker)
        except: pass

    # Initialization
    Gui.ccad_auto_blocker = AutoSelectionBlocker()
    App.addDocumentObserver(Gui.ccad_auto_blocker)
    Gui.Selection.addObserver(Gui.ccad_auto_blocker)

    target = next((w for w in mw.findChildren(QtWidgets.QWidget) 
                  if "View3DInventor" in w.metaObject().className() and w.isVisible()), None)
    
    if target:
        Gui.ccad_sel_logic = CCADSelectionLogic(target)

    print("ClassicCAD: One-Click Grips & Snappy Selection Active.")

    if hasattr(Gui, "ccad_selection_observer"):
        try:
            Gui.ccad_selection_observer.timer.stop()
            Gui.ccad_selection_observer.deleteLater()
        except: pass

    Gui.ccad_selection_observer = SelectionObserver()
    SelectionManager.force_pick_radius()
    
    App.Console.PrintLog("ClassicCAD Selection: Brute Force PickRadius Active.\n")

if __name__ == "__main__":
    setup()