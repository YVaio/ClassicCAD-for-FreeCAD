import FreeCAD as App
import FreeCADGui as Gui
import os
import sys

class ClassicCADWorkbench(Gui.Workbench):
    MenuText = "ClassicCAD"
    ToolTip = "AutoCAD-style interface for FreeCAD"
    Icon = """
    /* XPM */
    static char * xpm_x[] = {
    "16 16 2 1",
    "  c None",
    ". c #FFFFFF",
    "        .       ",
    "        .       ",
    "        .       ",
    "        .       ",
    "     .......    ",
    "     .     .    ",
    "     .     .    ",
    " .....     .....",
    "     .     .    ",
    "     .     .    ",
    "     .......    ",
    "        .       ",
    "        .       ",
    "        .       ",
    "        .       ",
    "                "};
    """

    def Initialize(self):
        self.active_modules = [
            "ccad_console",
            "ccad_cursor",
            "ccad_selection",
            "ccad_draft_tools",
            "ccad_layers",
            "ccad_snaps",
            "ccad_dev_tools"
        ]
        mod_path = os.path.join(App.getUserAppDataDir(), "Mod", "ClassicCAD", "scripts")
        if os.path.exists(mod_path) and mod_path not in sys.path:
            sys.path.append(mod_path)
        
        # Σημαία για να ξέρουμε αν είναι η πρώτη φορά που ενεργοποιείται (startup)
        if not hasattr(Gui, "ccad_first_run"):
            Gui.ccad_first_run = True
        else:
            Gui.ccad_first_run = False
            
        Gui.ccad_global_active = self

    def Activated(self):
        from PySide6 import QtCore
        import importlib
        
        for mod_name in self.active_modules:
            try:
                if mod_name in sys.modules:
                    module = importlib.reload(sys.modules[mod_name])
                else:
                    module = importlib.import_module(mod_name)
                
                if hasattr(module, "setup"):
                    module.setup()
            except Exception as e:
                App.Console.PrintError(f"ClassicCAD Error: {e}\n")
        
        # ΕΚΤΕΛΕΣΗ TOP VIEW ΜΟΝΟ ΣΤΟ STARTUP
        if Gui.ccad_first_run:
            def silent_top_view():
                view = Gui.activeView()
                if view:
                    # Επιβολή Orthographic και Top View χωρίς animation
                    view.setCameraType("Orthographic")
                    view.viewTop()
                    # Μηδενισμός περιστροφής για απόλυτο Top
                    view.setCameraOrientation(App.Rotation(App.Vector(0,0,1), 0))
                    # Σημειώνουμε ότι έγινε, ώστε να μην ξαναγίνει αν αλλάξεις workbench
                    Gui.ccad_first_run = False
                    App.Console.PrintLog("ClassicCAD: Initial Top View Forced.\n")
                else:
                    QtCore.QTimer.singleShot(100, silent_top_view)
            
            silent_top_view()

    def Deactivated(self):
        # 1. Βίαιο κλείσιμο Task Dialogs
        try:
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
        except: pass

        # 2. Ασφαλές Reset των modules
        for mod_name in self.active_modules:
            if mod_name in sys.modules:
                module = sys.modules[mod_name]
                if module and hasattr(module, "tear_down"):
                    try:
                        module.tear_down()
                    except Exception as e:
                        App.Console.PrintLog(f"ClassicCAD: Silent skip on {mod_name} reset.\n")

    def GetClassName(self): 
        return "Gui::PythonWorkbench"

Gui.addWorkbench(ClassicCADWorkbench())