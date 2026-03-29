import importlib
import sys
import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtWidgets, QtCore

def REGEN():
    """Εντολή REGEN: Δυναμική εξομάλυνση και επαναϋπολογισμός σύνθετης γεωμετρίας (Splines, Beziers, κλπ)."""
    try:
        doc = App.ActiveDocument
        if not doc: return
        view = Gui.activeView()
        if not view: return

        # Υπολογισμός Camera Height για Orthographic
        camera = view.getCameraNode()
        visible_height = camera.height.getValue() if hasattr(camera, "height") else 100

        # Δυναμικό Deviation βάσει zoom (όσο πιο κοντά, τόσο πιο μικρό deviation = πιο ομαλό)
        dynamic_deviation = visible_height * 0.001
        if dynamic_deviation < 0.0005: dynamic_deviation = 0.0005

        # Τύποι που αγνοούμε (απλές γραμμές και σημεία) για ταχύτητα
        simple_types = ('Part::Line', 'App::Origin', 'App::Plane')

        for obj in doc.Objects:
            # 1. Έλεγχος αν το αντικείμενο έχει Shape (άρα είναι γεωμετρία)
            if hasattr(obj, "Shape"):
                
                # 2. Αν δεν είναι απλή γραμμή, το μαρκάρουμε για πλήρη αναγέννηση
                # Αυτό επιβάλλει στις Splines/Beziers να ξαναφτιάξουν το πλέγμα τους
                if obj.TypeId not in simple_types:
                    obj.touch() 

                # 3. Ρύθμιση Deviation στο ViewObject για οπτική εξομάλυνση
                if hasattr(obj, 'ViewObject') and obj.ViewObject:
                    vo = obj.ViewObject
                    if hasattr(vo, "Deviation"):
                        vo.Deviation = dynamic_deviation
                    if hasattr(vo, "AngularDeflection"):
                        vo.AngularDeflection = dynamic_deviation * 10
        
        # 4. Επαναϋπολογισμός και ανανέωση οθόνης
        doc.recompute()
        Gui.updateGui()
        App.Console.PrintLog(f"REGEN: Done. Complex geometry smoothed (Deviation: {dynamic_deviation:.4f})\n")
    except Exception as e:
        App.Console.PrintError(f"REGEN Error: {str(e)}\n")

def reload_classic_cad():
    """Πλήρες Reload του συστήματος ClassicCAD (Global Mode)"""
    App.Console.PrintLog("\n" + "#"*30 + "\n")
    App.Console.PrintLog("  CLASSIC CAD: DEEP RESET...\n")
    App.Console.PrintLog("#"*30 + "\n")
    
    # Η λίστα των modules
    modules_to_reload = [
        "ccad_cmd_xline",
        "ccad_cmd_trim",
        "ccad_cmd_join",
        "ccad_cmd_spline",
        "ccad_cmd_fillet",
        "ccad_console",
        "ccad_cursor",
        "ccad_selection",
        "ccad_draft_tools",
        "ccad_layers",
        "ccad_status_bar",
        "ccad_dev_tools" # Must be last
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