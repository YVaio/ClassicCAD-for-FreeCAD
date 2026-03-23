import FreeCAD as App
import FreeCADGui as Gui
import os
import sys

def startup_classic_cad():
    # 1. Ορισμός μονοπατιών μέσα στη συνάρτηση
    mod_name = "ClassicCAD"
    user_mod_path = os.path.join(App.getUserAppDataDir(), "Mod", mod_name)
    scripts_path = os.path.join(user_mod_path, "scripts")

    if os.path.exists(scripts_path) and scripts_path not in sys.path:
        sys.path.append(scripts_path)

    # 2. Ορισμός της κλάσης ΜΕΣΑ στη συνάρτηση (Nested Class)
    # Αυτό την "κλειδώνει" στη μνήμη και αποκλείει το NameError
    class ClassicCADGlobal:
        ACTIVE_SCRIPTS = [
            "ccad_console",
            "ccad_cursor",
            "ccad_selection",
            "ccad_draft_tools",
            "ccad_layers",
            "ccad_snaps",
            "ccad_cmd_line",
            "ccad_dev_tools",
            "ccad_environment"
        ]

        def __init__(self):
            self.active_modules = ClassicCADGlobal.ACTIVE_SCRIPTS
            from PySide6 import QtCore
            QtCore.QTimer.singleShot(3000, self.inject_system)

        def inject_system(self):
            try:
                import importlib
                for mod_name in self.active_modules:
                    if mod_name in sys.modules:
                        module = importlib.reload(sys.modules[mod_name])
                    else:
                        module = __import__(mod_name)
                    
                    if hasattr(module, "setup"):
                        module.setup()
                
                App.Console.PrintLog("ClassicCAD Global: System Attached Successfully.\n")
            except Exception as e:
                App.Console.PrintError(f"ClassicCAD Global Error: {str(e)}\n")

    # 3. Ενεργοποίηση αμέσως
    if not hasattr(Gui, "ccad_global_active"):
        Gui.ccad_global_active = ClassicCADGlobal()

# Εκτέλεση της κεντρικής συνάρτησης
startup_classic_cad()