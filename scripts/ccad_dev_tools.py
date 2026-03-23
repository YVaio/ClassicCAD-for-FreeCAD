import importlib
import sys
import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtWidgets, QtCore

def REGEN():
    """Εντολή REGEN: Διορθώνει τα 'σπασίματα' στους κύκλους (Deviation)"""
    try:
        doc = App.ActiveDocument
        if doc:
            # 1. 'Touch' & 'Deviation' Fix
            # Ορίζουμε μια πολύ μικρή τιμή απόκλισης για μέγιστη εξομάλυνση
            target_deviation = 0.005 # Μικρότερο = Πιο στρογγυλό
            
            for obj in doc.Objects:
                # Αν το αντικείμενο έχει ViewObject (γραφικά), διορθώνουμε την ποιότητα
                if hasattr(obj, "ViewObject"):
                    # Το Deviation ελέγχει πόσο "σπασμένες" φαίνονται οι καμπύλες
                    if hasattr(obj.ViewObject, "Deviation"):
                        obj.ViewObject.Deviation = target_deviation
                
                # Αναγκάζουμε το αντικείμενο να ξανασχεδιαστεί
                obj.touch()
            
            # 2. Επαναϋπολογισμός
            doc.recompute()
            
            # 3. Βίαιη ανανέωση του Viewport μέσω Qt Repaint
            mw = Gui.getMainWindow()
            for w in mw.findChildren(QtWidgets.QWidget):
                if "View3DInventor" in w.metaObject().className() and w.isVisible():
                    w.repaint()
            
            App.Console.PrintLog(f"ClassicCAD: REGEN Complete (Curves smoothed to {target_deviation}).\n")
        else:
            App.Console.PrintWarning("REGEN: No active document found.\n")
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