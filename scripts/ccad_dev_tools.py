import importlib
import sys
import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtWidgets, QtCore

def REGEN():
    """Εντολή REGEN: Δυναμική εξομάλυνση βάσει Camera Height (Orthographic)"""
    try:
        doc = App.ActiveDocument
        if not doc: return

        view = Gui.activeView()
        if not view: return

        # 1. Υπολογισμός Zoom Level μέσω του Camera Height
        # Το height στο Orthographic camera είναι το ορατό ύψος σε 3D μονάδες (mm)
        camera = view.getCameraNode()
        if hasattr(camera, "height"):
            visible_height = camera.height.getValue()
        else:
            # Fallback αν δεν είναι Orthographic
            visible_height = 100

        # 2. Υπολογισμός Deviation (Απόκλιση)
        # AutoCAD Logic: 0.1% του ορατού ύψους
        # Παράδειγμα: Αν βλέπεις 100mm, deviation = 0.1mm (Σχετικά λείο)
        # Αν βλέπεις 2mm (πολύ κοντά), deviation = 0.002mm (Τέλεια καμπύλη)
        dynamic_deviation = visible_height * 0.001
        
        # Περιορισμός ορίων για ασφάλεια
        if dynamic_deviation < 0.0005: dynamic_deviation = 0.0005 # Ultra Smooth
        if dynamic_deviation > 1.0: dynamic_deviation = 1.0       # Performance
        
        # 3. Εφαρμογή και 'Touch'
        for obj in doc.Objects:
            if hasattr(obj, "ViewObject") and hasattr(obj.ViewObject, "Deviation"):
                # Εφαρμόζουμε τη νέα τιμή μόνο αν διαφέρει σημαντικά
                obj.ViewObject.Deviation = dynamic_deviation
                obj.touch()

        # 4. Επαναϋπολογισμός
        doc.recompute()
        
        # 5. Βίαιο Repaint
        mw = Gui.getMainWindow()
        for w in mw.findChildren(QtWidgets.QWidget):
            if "View3DInventor" in w.metaObject().className() and w.isVisible():
                w.repaint()

        state = "DETAIL" if dynamic_deviation < 0.01 else "DRAFT"
        App.Console.PrintLog(f"ClassicCAD: REGEN [{state}] (Height: {visible_height:.2f}, Dev: {dynamic_deviation:.4f})\n")

    except Exception as e:
        App.Console.PrintError(f"REGEN Error: {str(e)}\n")

def reload_classic_cad():
    """Πλήρες Reload του συστήματος ClassicCAD"""
    App.Console.PrintLog("\n" + "="*20 + " SYSTEM RELOAD " + "="*20 + "\n")
    
    instance = getattr(Gui, "ccad_global_active", None)
    if not instance:
        App.Console.PrintError("Global system instance not found.\n")
        return
        
    modules = getattr(instance, "active_modules", [])
    
    # Πρώτα τρέχουμε το Deactivated για να καθαρίσουμε timers/widgets
    try:
        instance.Deactivated()
    except: pass
    
    for mod_name in modules:
        # Μην κάνεις reload το ίδιο το dev_tools την ώρα που τρέχει
        if mod_name == "ccad_dev_tools": continue
        
        try:
            if mod_name in sys.modules:
                # Επιβολή ανάγνωσης από τον δίσκο
                reloaded = importlib.reload(sys.modules[mod_name])
                if hasattr(reloaded, "setup"):
                    reloaded.setup()
                App.Console.PrintLog(f"OK: {mod_name}\n")
        except Exception as e:
            App.Console.PrintError(f"ERR: {mod_name} -> {str(e)}\n")
            
    App.Console.PrintLog("="*55 + "\n")

def setup():
    """Απαραίτητο για να αναγνωρίζεται από το InitGui"""
    # Εδώ μπορούμε να ορίσουμε παγκόσμιες συντομεύσεις αν χρειαστεί
    pass

def tear_down():
    """Απαραίτητο για το Reset"""
    pass