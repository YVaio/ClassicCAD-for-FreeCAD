import os
import sys

import FreeCAD as App
import FreeCADGui as Gui


class ClassicCADWorkbench(Workbench):
    """
    Clean extension mode:
    - Reuse Draft's native UI by switching to Draft when this workbench is selected.
    - Load ClassicCAD behavior only while ClassicCAD is active.
    - Remove ClassicCAD behavior when leaving.
    """

    MenuText = "ClassicCAD"
    ToolTip = "Draft UI with ClassicCAD behavior loaded only while this workbench is active"
    Icon = ""

    @staticmethod
    def _classiccad_root():
        g = globals()
        f = g.get("__file__")
        if f:
            return os.path.dirname(os.path.abspath(f))
        return os.path.join(App.getUserAppDataDir(), "Mod", "ClassicCAD")

    @classmethod
    def _ensure_paths(cls):
        root = cls._classiccad_root()
        if root not in sys.path:
            sys.path.insert(0, root)
        scripts = os.path.join(root, "scripts")
        if os.path.isdir(scripts) and scripts not in sys.path:
            sys.path.insert(0, scripts)
        return root, scripts

    @classmethod
    def _import_manager(cls):
        cls._ensure_paths()
        import classiccad_workbench_manager as manager
        return manager

    def Initialize(self):
        self.__class__._ensure_paths()

    def Activated(self):
        # Show the real native Draft UI.
        try:
            current = Gui.activeWorkbench().__class__.__name__ if Gui.activeWorkbench() else ""
        except Exception:
            current = ""

        try:
            if current != "DraftWorkbench":
                Gui.activateWorkbench("DraftWorkbench")
        except Exception as exc:
            App.Console.PrintWarning(
                "ClassicCAD: could not activate Draft UI base: %s\n" % exc
            )

        try:
            manager = self.__class__._import_manager()
            manager.activate()
            App.Console.PrintMessage("ClassicCAD: behavior layer activated on top of Draft.\n")
        except Exception as exc:
            App.Console.PrintError(
                "ClassicCAD: activation failed: %s\n" % exc
            )
            raise

    def Deactivated(self):
        try:
            manager = self.__class__._import_manager()
            manager.deactivate()
            App.Console.PrintMessage("ClassicCAD: behavior layer deactivated.\n")
        except Exception as exc:
            App.Console.PrintWarning(
                "ClassicCAD: deactivate warning: %s\n" % exc
            )

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(ClassicCADWorkbench())
