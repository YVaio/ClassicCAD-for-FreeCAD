import os
import sys

import FreeCAD as App
import FreeCADGui as Gui


class ClassicCADWorkbench(Workbench):
    """
    Standalone Draft-style workbench.

    It clones Draft's menus and toolbars into ClassicCAD, then loads the
    ClassicCAD behavior layer only while this workbench is active.
    """

    MenuText = "ClassicCAD"
    ToolTip = "Standalone Draft-style workbench with ClassicCAD behavior"
    _initial_top_view_done = False
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

    @staticmethod
    def _qtcore_module():
        try:
            from PySide6 import QtCore as _QtCore
        except Exception:
            try:
                from PySide2 import QtCore as _QtCore
            except Exception:
                _QtCore = None
        return _QtCore

    @staticmethod
    def _resolved_startup_workbench():
        start = "StartWorkbench"

        try:
            config_get = getattr(App, "ConfigGet", None)
            if callable(config_get):
                configured = config_get("StartWorkbench")
                if configured:
                    start = configured
        except Exception:
            pass

        try:
            prefs = App.ParamGet("User parameter:BaseApp/Preferences/General")
            autoload = prefs.GetString("AutoloadModule", start) or start
            if autoload == "$LastModule":
                autoload = prefs.GetString("LastModule", start) or start
            return autoload
        except Exception:
            return start

    def _init_draft_clone_ui(self):
        try:
            import Draft_rc
            import DraftTools
            import DraftGui

            Gui.addLanguagePath(":/translations")
            Gui.addIconPath(":/icons")
        except Exception as exc:
            App.Console.PrintError(str(exc) + "\n")
            App.Console.PrintError(
                "ClassicCAD: Draft modules failed to initialize; the workbench will not work as expected.\n"
            )
            raise

        import draftutils.init_tools as init_tools

        self.drawing_commands = init_tools.get_draft_drawing_commands()
        self.annotation_commands = init_tools.get_draft_annotation_commands()
        self.modification_commands = init_tools.get_draft_modification_commands()
        self.utility_commands_menu = init_tools.get_draft_utility_commands_menu()
        self.utility_commands_toolbar = init_tools.get_draft_utility_commands_toolbar()
        self.context_commands = init_tools.get_draft_context_commands()

        init_tools.init_toolbar(
            self,
            "Draft Creation",
            self.drawing_commands,
        )
        init_tools.init_toolbar(
            self,
            "Draft Annotation",
            self.annotation_commands,
        )
        init_tools.init_toolbar(
            self,
            "Draft Modification",
            self.modification_commands,
        )
        init_tools.init_toolbar(
            self,
            "Draft Utility",
            self.utility_commands_toolbar,
        )
        init_tools.init_toolbar(
            self,
            "Draft Snap",
            init_tools.get_draft_snap_commands(),
        )

        init_tools.init_menu(
            self,
            ["&Drafting"],
            self.drawing_commands,
        )
        init_tools.init_menu(
            self,
            ["&Annotation"],
            self.annotation_commands,
        )
        init_tools.init_menu(
            self,
            ["&Modification"],
            self.modification_commands,
        )
        init_tools.init_menu(
            self,
            ["&Utilities"],
            self.utility_commands_menu,
        )

        if hasattr(Gui, "draftToolBar") and not hasattr(Gui.draftToolBar, "loadedPreferences"):
            from draftutils import params

            params._param_observer_start()
            Gui.addPreferencePage(
                ":/ui/preferences-draft.ui", "Draft"
            )
            Gui.addPreferencePage(
                ":/ui/preferences-draftinterface.ui", "Draft"
            )
            Gui.addPreferencePage(
                ":/ui/preferences-draftsnap.ui", "Draft"
            )
            Gui.addPreferencePage(
                ":/ui/preferences-draftvisual.ui", "Draft"
            )
            Gui.addPreferencePage(
                ":/ui/preferences-drafttexts.ui", "Draft"
            )
            Gui.draftToolBar.loadedPreferences = True

        try:
            mw = Gui.getMainWindow()
            if mw and not getattr(self, "_main_window_close_hooked", False):
                mw.mainWindowClosed.connect(self.Deactivated)
                self._main_window_close_hooked = True
        except Exception:
            pass

        App.Console.PrintLog("Loading ClassicCAD workbench, done.\n")

    @staticmethod
    def _activate_draft_base():
        import WorkingPlane
        from draftutils import grid_observer

        if hasattr(Gui, "draftToolBar"):
            Gui.draftToolBar.Activated()
        if hasattr(Gui, "Snapper"):
            Gui.Snapper.show()
            from draftutils import init_draft_statusbar

            init_draft_statusbar.show_draft_statusbar()
        if hasattr(WorkingPlane, "_view_observer_start"):
            WorkingPlane._view_observer_start()
        else:
            App.Console.PrintWarning(
                "Improper loading of WorkingPlane code. ClassicCAD will not work correctly.\n"
            )
        if hasattr(grid_observer, "_view_observer_setup"):
            grid_observer._view_observer_setup()
        else:
            App.Console.PrintWarning(
                "Improper loading of grid_observer code. ClassicCAD will not work correctly.\n"
            )

    @staticmethod
    def _deactivate_draft_base():
        import WorkingPlane
        from draftutils import grid_observer

        if hasattr(Gui, "draftToolBar"):
            Gui.draftToolBar.Deactivated()
        if hasattr(Gui, "Snapper"):
            Gui.Snapper.hide()
            from draftutils import init_draft_statusbar

            init_draft_statusbar.hide_draft_statusbar()
        if hasattr(WorkingPlane, "_view_observer_stop"):
            WorkingPlane._view_observer_stop()
        if hasattr(grid_observer, "_view_observer_setup"):
            grid_observer._view_observer_setup()

    @classmethod
    def _schedule_initial_top_view(cls, manager, attempts=8, delay_ms=150):
        if cls._initial_top_view_done:
            return
        if cls._resolved_startup_workbench() != cls.__name__:
            return

        qtcore = cls._qtcore_module()

        def _apply(attempt=0):
            if cls._initial_top_view_done:
                return
            try:
                view = Gui.activeView()
            except Exception:
                view = None

            if view:
                manager._silent_top_view()
                cls._initial_top_view_done = True
                return

            if qtcore is not None and (attempt + 1) < attempts:
                qtcore.QTimer.singleShot(
                    delay_ms,
                    lambda next_attempt=attempt + 1: _apply(next_attempt),
                )

        if qtcore is None:
            _apply()
            return

        qtcore.QTimer.singleShot(0, _apply)

    def Initialize(self):
        self.__class__._ensure_paths()
        self._init_draft_clone_ui()

    def Activated(self):
        try:
            self._activate_draft_base()
        except Exception as exc:
            App.Console.PrintWarning(
                "ClassicCAD: could not activate Draft base UI: %s\n" % exc
            )

        try:
            manager = self.__class__._import_manager()
            manager.activate(expected_ui_workbench=self.__class__.__name__)

            try:
                import ccad_layers

                doc = App.ActiveDocument
                if doc:
                    ccad_layers.ensure_layer_0(doc, force_active=True)
                    _QtCore = self.__class__._qtcore_module()
                    if _QtCore is not None:
                        _QtCore.QTimer.singleShot(
                            250,
                            lambda d=doc: ccad_layers.ensure_layer_0(d, force_active=True),
                        )
            except Exception as layer_exc:
                App.Console.PrintWarning(
                    "ClassicCAD: Layer 0 activation warning: %s\n" % layer_exc
                )

            self.__class__._schedule_initial_top_view(manager)

            App.Console.PrintMessage(
                "ClassicCAD: standalone behavior layer activated.\n"
            )
        except Exception as exc:
            App.Console.PrintError(
                "ClassicCAD: activation failed: %s\n" % exc
            )
            raise

    def Deactivated(self):
        try:
            manager = self.__class__._import_manager()
            manager.deactivate()
        except Exception as exc:
            App.Console.PrintWarning(
                "ClassicCAD: deactivation warning: %s\n" % exc
            )

        try:
            self._deactivate_draft_base()
        except Exception as exc:
            App.Console.PrintWarning(
                "ClassicCAD: Draft base cleanup warning: %s\n" % exc
            )

    def ContextMenu(self, recipient):
        has_text = False
        for obj in Gui.Selection.getCompleteSelection():
            if hasattr(obj.Object, "Text"):
                has_text = True
                break

        if has_text:
            from draftguitools import gui_hyperlink

            hyperlinks_search = gui_hyperlink.Draft_Hyperlink()
            if hyperlinks_search.has_hyperlinks() and sys.platform in [
                "win32",
                "cygwin",
                "darwin",
                "linux",
            ]:
                self.appendContextMenu("", ["Draft_Hyperlink"])

        self.appendContextMenu("Utilities", getattr(self, "context_commands", []))

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(ClassicCADWorkbench())
