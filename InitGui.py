import FreeCAD as App
import FreeCADGui as Gui
import os
import sys

# --- 1. DYNAMIC PATH FIX (GitHub ZIP Safe) ---
current_dir = None
try:
    current_dir = os.path.dirname(os.path.abspath(__file__))
except NameError:
    mod_base = os.path.join(App.getUserAppDataDir(), "Mod")
    if os.path.exists(mod_base):
        for folder in os.listdir(mod_base):
            if "ClassicCAD" in folder:  
                test_dir = os.path.join(mod_base, folder)
                if os.path.exists(os.path.join(test_dir, "scripts")):
                    current_dir = test_dir
                    break

if current_dir:
    scripts_dir = os.path.join(current_dir, "scripts")
    if scripts_dir not in sys.path:
        sys.path.append(scripts_dir)
else:
    App.Console.PrintError("ClassicCAD: Failed to locate the mod folder.\n")


# --- 2. GLOBAL SETUP FUNCTIONS ---
def silent_top_view():
    import FreeCAD as App
    import FreeCADGui as Gui
    from PySide6 import QtCore
    
    view = Gui.activeView()
    if view:
        view.setCameraType("Orthographic")
        view.viewTop()
        view.setCameraOrientation(App.Rotation(App.Vector(0,0,1), 0))
        App.Console.PrintLog("ClassicCAD: Global Initial Top View Forced.\n")
    else:
        QtCore.QTimer.singleShot(500, Gui.ccad_silent_top_view)

Gui.ccad_silent_top_view = silent_top_view


# --- 3. INITIALIZATION ROUTINE ---
def startup_classic_cad():
    # Εισαγωγή των modules ΕΔΩ ΜΕΣΑ για να μην χαθούν ποτέ από το scope του Timer
    import FreeCAD as App
    import FreeCADGui as Gui
    import sys
    import importlib
    
    active_modules = [
        "ccad_console",
        "ccad_cursor",
        "ccad_selection",
        "ccad_draft_tools",
        "ccad_layers",
        "ccad_status_bar",
        "ccad_dev_tools"
    ]
    
    if not hasattr(Gui, "ccad_initialized"):
        Gui.ccad_initialized = True
        
        for mod_name in active_modules:
            try:
                if mod_name in sys.modules:
                    module = importlib.reload(sys.modules[mod_name])
                else:
                    module = importlib.import_module(mod_name)
                
                if hasattr(module, "setup"):
                    module.setup()
                App.Console.PrintLog(f"ClassicCAD: Loaded {mod_name} globally.\n")
            except Exception as e:
                App.Console.PrintError(f"ClassicCAD Error loading {mod_name}: {e}\n")

        from PySide6 import QtCore
        QtCore.QTimer.singleShot(1000, Gui.ccad_silent_top_view)


# Καθυστερούμε την εκκίνηση για να σιγουρευτούμε ότι το FreeCAD MainWindow έχει φορτώσει
from PySide6 import QtCore
QtCore.QTimer.singleShot(2000, startup_classic_cad)