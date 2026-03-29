import FreeCAD as App
import FreeCADGui as Gui
import os
import sys
import importlib

# --- 1. DYNAMIC PATH FIX ---
# Gets the exact folder where InitGui.py lives, avoiding GitHub "-main" folder naming issues.
current_dir = os.path.dirname(os.path.abspath(__file__))
scripts_dir = os.path.join(current_dir, "scripts")

if os.path.exists(scripts_dir) and scripts_dir not in sys.path:
    sys.path.append(scripts_dir)

# --- 2. GLOBAL SETUP FUNCTIONS ---
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

active_modules = [
    "ccad_console",
    "ccad_cursor",
    "ccad_selection",
    "ccad_draft_tools",
    "ccad_layers",
    "ccad_status_bar",
    "ccad_dev_tools"
]

# --- 3. WORKBENCH REGISTRATION ---
class ClassicCADWorkbench(Gui.Workbench):
    MenuText = "ClassicCAD"
    ToolTip = "AutoCAD-like workflow for FreeCAD"
    
    # Optional: If you have an icon, uncomment and point to it here
    # Icon = os.path.join(current_dir, "Resources", "icons", "ClassicCAD.svg")

    def Initialize(self):
        """This runs once when FreeCAD starts and loads the Workbench."""
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

            # Trigger the view setup
            from PySide6 import QtCore
            QtCore.QTimer.singleShot(1000, Gui.ccad_silent_top_view)

    def Activated(self):
        """Runs when the user switches to the ClassicCAD workbench in the UI."""
        pass

    def Deactivated(self):
        """Runs when the user switches away from the ClassicCAD workbench."""
        pass

# Add the workbench to FreeCAD
Gui.addWorkbench(ClassicCADWorkbench())