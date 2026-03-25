import FreeCAD as App
import FreeCADGui as Gui
import os
import sys
import importlib

# 1. Attach the function to Gui so it persists in memory
def silent_top_view():
    from PySide6 import QtCore
    view = Gui.activeView()
    if view:
        view.setCameraType("Orthographic")
        view.viewTop()
        view.setCameraOrientation(App.Rotation(App.Vector(0,0,1), 0))
        App.Console.PrintLog("ClassicCAD: Global Initial Top View Forced.\n")
    else:
        # Reference the function via the Gui object to avoid NameError
        QtCore.QTimer.singleShot(500, Gui.ccad_silent_top_view)

# Assign to Gui to prevent garbage collection/scope loss
Gui.ccad_silent_top_view = silent_top_view

# 2. Setup paths and global variables
active_modules = [
    "ccad_console",
    "ccad_cursor",
    "ccad_selection",
    "ccad_draft_tools",
    "ccad_layers",
    #"ccad_snaps",
    "ccad_dev_tools"
]

mod_path = os.path.join(App.getUserAppDataDir(), "Mod", "ClassicCAD", "scripts")
if os.path.exists(mod_path) and mod_path not in sys.path:
    sys.path.append(mod_path)

# 3. Initialize and Setup all modules globally
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

    # 4. Trigger the view setup
    from PySide6 import QtCore
    QtCore.QTimer.singleShot(1000, Gui.ccad_silent_top_view)