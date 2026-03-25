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

        camera = view.getCameraNode()
        if hasattr(camera, "height"):
            visible_height = camera.height.getValue()
        else:
            visible_height = 100

        dynamic_deviation = visible_height * 0.001
        if dynamic_deviation < 0.0005: dynamic_deviation = 0.0005
        if dynamic_deviation > 0.5: dynamic_deviation = 0.5

        import Part
        Part.setObjectDeviation(dynamic_deviation)
        doc.recompute()
        App.Console.PrintLog(f"REGEN: Done (Deviation: {dynamic_deviation:.4f})\n")
    except Exception as e:
        App.Console.PrintError(f"REGEN Error: {str(e)}\n")

def reload_classic_cad():
    """Πλήρες Reload του συστήματος ClassicCAD (Global Mode)"""
    App.Console.PrintLog("\n" + "#"*30 + "\n")
    App.Console.PrintLog("  CLASSIC CAD: DEEP RESET...\n")
    App.Console.PrintLog("#"*30 + "\n")
    
    # Η λίστα των modules
    modules_to_reload = [
        "ccad_console",
        "ccad_cursor",
        "ccad_selection",
        "ccad_draft_tools",
        "ccad_layers",
        "ccad_dev_tools" # Πρέπει να είναι τελευταίο
    ]

    # 1. ΚΑΘΑΡΙΣΜΟΣ EVENT FILTERS (Πριν το tear_down)
    app = QtWidgets.QApplication.instance()
    if hasattr(Gui, "classic_console"):
        try:
            app.removeEventFilter(Gui.classic_console)
            App.Console.PrintLog("EventFilter removed from Console.\n")
        except: pass

    # 2. TEAR DOWN (Με ανάποδη σειρά)
    for mod_name in reversed(modules_to_reload):
        if mod_name in sys.modules and mod_name != "ccad_dev_tools":
            mod = sys.modules[mod_name]
            if hasattr(mod, "tear_down"):
                try:
                    mod.tear_down()
                    App.Console.PrintLog(f"Cleaned: {mod_name}\n")
                except Exception as e:
                    App.Console.PrintLog(f"Skip Cleanup {mod_name}: {e}\n")

    # 3. RELOAD ΚΑΙ SETUP
    for mod_name in modules_to_reload:
        try:
            # ΕΙΔΙΚΟΣ ΧΕΙΡΙΣΜΟΣ ΓΙΑ ΤΟ DEV TOOLS
            if mod_name == "ccad_dev_tools":
                # Δεν κάνουμε setup εδώ, γιατί θα ξανακαλούσε την reload_classic_cad
                importlib.reload(sys.modules[mod_name])
                App.Console.PrintLog("Reloaded: ccad_dev_tools (self)\n")
                continue

            if mod_name in sys.modules:
                reloaded = importlib.reload(sys.modules[mod_name])
                if hasattr(reloaded, "setup"):
                    reloaded.setup()
                App.Console.PrintLog(f"Reloaded & Setup: {mod_name}\n")
            else:
                importlib.import_module(mod_name)
                App.Console.PrintLog(f"Imported: {mod_name}\n")
        except Exception as e:
            App.Console.PrintError(f"Failed {mod_name}: {str(e)}\n")

    App.Console.PrintLog("#"*30 + "\n")

def setup():
    """Προαιρετικό setup για το dev_tools"""
    pass

def tear_down():
    """Καθαρισμός πριν το reload"""
    pass