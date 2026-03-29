import importlib
import os
import sys

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except Exception:
    QtCore = None
    QtWidgets = None

try:
    from PySide2 import QtCore as QtCore2, QtWidgets as QtWidgets2
    if QtCore is None:
        QtCore = QtCore2
    if QtWidgets is None:
        QtWidgets = QtWidgets2
except Exception:
    pass


MODULES = [
    "ccad_console",
    "ccad_cursor",
    "ccad_selection",
    "ccad_draft_tools",
    "ccad_layers",
    "ccad_status_bar",
    "ccad_dev_tools",
]

COMMAND_MODULES = [
    "ccad_cmd_fillet",
    "ccad_cmd_join",
    "ccad_cmd_spline",
    "ccad_cmd_trim",
    "ccad_cmd_xline",
]

_STATE = {
    "active": False,
    "loaded_modules": [],
}


def _classiccad_root():
    mod = sys.modules.get(__name__)
    f = getattr(mod, "__file__", None)
    if f:
        return os.path.dirname(os.path.abspath(f))
    return os.path.join(App.getUserAppDataDir(), "Mod", "ClassicCAD")


def ensure_paths():
    root = _classiccad_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    scripts = os.path.join(root, "scripts")
    if not os.path.isdir(scripts):
        App.Console.PrintWarning(
            "ClassicCAD: scripts folder not found at %s\n" % scripts
        )
        return None
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return scripts


def _reload_or_import(name):
    if name in sys.modules:
        return importlib.reload(sys.modules[name])
    return importlib.import_module(name)


def _call_teardown(module):
    fn = getattr(module, "tear_down", None) or getattr(module, "teardown", None)
    if callable(fn):
        try:
            fn()
        except Exception as exc:
            App.Console.PrintWarning(
                "ClassicCAD: tear_down warning in %s: %s\n" % (module.__name__, exc)
            )


def _safe_delete_qobject(obj):
    if obj is None:
        return
    try:
        if hasattr(obj, "timer"):
            try:
                obj.timer.stop()
            except Exception:
                pass
        if hasattr(obj, "deleteLater"):
            obj.deleteLater()
    except Exception:
        pass


def _remove_event_filter(obj):
    if obj is None or QtWidgets is None:
        return
    try:
        app = QtWidgets.QApplication.instance()
        if app:
            app.removeEventFilter(obj)
    except Exception:
        pass


def _cleanup_console():
    if QtWidgets is None:
        return
    _remove_event_filter(getattr(Gui, "classic_console", None))
    _remove_event_filter(getattr(Gui, "ccad_focus_stealer", None))
    for shortcut in getattr(Gui, "ccad_shortcuts", []) or []:
        _safe_delete_qobject(shortcut)
    for name in ("classic_console", "ccad_focus_stealer"):
        obj = getattr(Gui, name, None)
        _safe_delete_qobject(obj)
        if hasattr(Gui, name):
            delattr(Gui, name)
    if hasattr(Gui, "ccad_shortcuts"):
        delattr(Gui, "ccad_shortcuts")


def _cleanup_cursor():
    if hasattr(Gui, "ccad_cursor"):
        _safe_delete_qobject(getattr(Gui, "ccad_cursor", None))
        delattr(Gui, "ccad_cursor")
    if hasattr(Gui, "ccad_find_cursor"):
        delattr(Gui, "ccad_find_cursor")


def _cleanup_selection():
    sel = getattr(Gui, "ccad_sel_logic", None)
    try:
        if sel and hasattr(sel, "viewport") and sel.viewport:
            sel.viewport.removeEventFilter(sel)
    except Exception:
        pass
    _safe_delete_qobject(getattr(sel, "box", None))
    _safe_delete_qobject(sel)
    if hasattr(Gui, "ccad_sel_logic"):
        delattr(Gui, "ccad_sel_logic")


def _cleanup_layers():
    obs = getattr(Gui, "ccad_layer_observer", None)
    if obs:
        try:
            App.removeDocumentObserver(obs)
        except Exception:
            pass
        if hasattr(Gui, "ccad_layer_observer"):
            delattr(Gui, "ccad_layer_observer")


def _cleanup_status_bar():
    bar = getattr(Gui, "ccad_status_bar", None)
    if bar is None:
        return
    try:
        mw = Gui.getMainWindow()
        if mw and QtWidgets is not None and hasattr(bar, "ortho_btn") and bar.ortho_btn:
            for tb in mw.findChildren(QtWidgets.QToolBar):
                try:
                    acts = tb.actions()
                except Exception:
                    acts = []
                if bar.ortho_btn in acts:
                    tb.removeAction(bar.ortho_btn)
                    break
    except Exception:
        pass
    _safe_delete_qobject(bar)
    if hasattr(Gui, "ccad_status_bar"):
        delattr(Gui, "ccad_status_bar")


def _cleanup_draft_tools():
    mod = sys.modules.get("ccad_draft_tools")
    if mod:
        _call_teardown(mod)
    tool = getattr(Gui, "ccad_draft_tools", None)
    _remove_event_filter(tool)
    _safe_delete_qobject(tool)
    if hasattr(Gui, "ccad_draft_tools"):
        delattr(Gui, "ccad_draft_tools")


def _cleanup_dev_tools():
    mod = sys.modules.get("ccad_dev_tools")
    if mod:
        _call_teardown(mod)


def _cleanup_misc_handlers():
    for name in (
        "ccad_xline_handler",
        "ccad_trim_handler",
        "ccad_fillet_handler",
        "ccad_spline_handler",
    ):
        obj = getattr(Gui, name, None)
        _safe_delete_qobject(obj)
        if hasattr(Gui, name):
            delattr(Gui, name)

    if hasattr(Gui, "ccad_initialized"):
        delattr(Gui, "ccad_initialized")

    if hasattr(Gui, "ccad_silent_top_view"):
        delattr(Gui, "ccad_silent_top_view")


def _fallback_cleanup():
    _cleanup_console()
    _cleanup_cursor()
    _cleanup_selection()
    _cleanup_draft_tools()
    _cleanup_layers()
    _cleanup_status_bar()
    _cleanup_dev_tools()
    _cleanup_misc_handlers()


def _import_and_setup(mod_name):
    module = _reload_or_import(mod_name)
    setup = getattr(module, "setup", None)
    if callable(setup):
        setup()
    return module


def activate():
    ensure_paths()
    if _STATE["active"]:
        return

    loaded = []
    try:
        for mod_name in COMMAND_MODULES:
            try:
                _reload_or_import(mod_name)
            except Exception as exc:
                App.Console.PrintWarning(
                    "ClassicCAD: command module %s warning: %s\n" % (mod_name, exc)
                )

        for mod_name in MODULES:
            module = _import_and_setup(mod_name)
            loaded.append(module.__name__)
            App.Console.PrintLog("ClassicCAD: activated %s\n" % mod_name)

        if QtCore is not None:
            QtCore.QTimer.singleShot(250, _silent_top_view)

        _STATE["active"] = True
        _STATE["loaded_modules"] = loaded
    except Exception:
        _fallback_cleanup()
        _STATE["active"] = False
        _STATE["loaded_modules"] = []
        raise


def deactivate():
    if not _STATE["active"]:
        _fallback_cleanup()
        return

    for mod_name in reversed(MODULES):
        module = sys.modules.get(mod_name)
        if module:
            _call_teardown(module)

    _fallback_cleanup()
    _STATE["active"] = False
    _STATE["loaded_modules"] = []
    App.Console.PrintLog("ClassicCAD: deactivated\n")


def _silent_top_view():
    try:
        view = Gui.activeView()
        if not view:
            return
        view.setCameraType("Orthographic")
        view.viewTop()
    except Exception as exc:
        App.Console.PrintWarning(
            "ClassicCAD: top-view warning: %s\n" % exc
        )
