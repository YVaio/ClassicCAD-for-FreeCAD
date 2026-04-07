import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore, QtGui, QtWidgets

_original_snap = None

_DRAFT_PREFS_PATH = "User parameter:BaseApp/Preferences/Mod/Draft"

_ORTHO_SUSPEND_CMDS = ('Rectangle',)


def _ortho_snap(self, screenpos, lastpoint=None, active=True, constrain=False, noTracker=False):
    """Patched Snapper.snap: forces ortho when F8 is ON.

    Uses FreeCAD's native constraint so the rubberband/tracker draws along
    the ortho axis.  After snapping, if the snapper detected a real object
    snap (endpoint, midpoint, …) the point is re-snapped without constraint
    so the snap wins over ortho — both visually and in the returned value.
    """
    try:
        if ClassicDraftTools._ortho_enabled and lastpoint is not None:
            cmd = getattr(App, 'activeDraftCommand', None)
            cmd_name = cmd.__class__.__name__ if cmd else ''
            if cmd_name not in _ORTHO_SUSPEND_CMDS:
                # Reset constraint state for a clean ortho pass
                self.constraintAxis = None
                self.affinity = None
                # Snap WITH constraint — gives proper ortho rubberband
                pt = _original_snap(self, screenpos, lastpoint=lastpoint,
                                    active=active, constrain=True,
                                    noTracker=noTracker)
                # If the snapper found a real object snap, re-snap freely
                si = getattr(self, 'snapInfo', None)
                if si and isinstance(si, dict) and si.get('Object'):
                    return _original_snap(self, screenpos,
                                          lastpoint=lastpoint,
                                          active=active, constrain=False,
                                          noTracker=noTracker)
                return pt
    except Exception:
        pass
    return _original_snap(self, screenpos, lastpoint=lastpoint,
                          active=active, constrain=constrain,
                          noTracker=noTracker)


_PREF_GROUP = "User parameter:BaseApp/Preferences/Mod/ClassicCAD"

class ClassicDraftTools(QtCore.QObject):
    _ortho_enabled = App.ParamGet(_PREF_GROUP).GetBool("OrthoEnabled", False)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mw = Gui.getMainWindow()
        self._draft_params = App.ParamGet(_DRAFT_PREFS_PATH)
        self._original_focus_on_length = self._draft_params.GetBool("focusOnLength", False)
        self._draft_params.SetBool("focusOnLength", True)
        
        # Install app-level event filter so F3/F8 work even during commands
        QtWidgets.QApplication.instance().installEventFilter(self)

    def restore_preferences(self):
        try:
            self._draft_params.SetBool("focusOnLength", bool(self._original_focus_on_length))
        except Exception:
            pass

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.KeyPress and not event.isAutoRepeat():
            key = event.key()
            if key == QtCore.Qt.Key_F3:
                self.toggle_osnap()
                return True
            if key == QtCore.Qt.Key_F8:
                self.toggle_ortho()
                return True
        return False

    def print_msg(self, text):
        if hasattr(Gui, "classic_console") and hasattr(Gui.classic_console, "history"):
            try:
                clean = text.replace("<", "&lt;").replace(">", "&gt;")
                msg = f"<span style='color:#aaaaaa; font-family:Consolas;'>{clean}</span>"
                Gui.classic_console.history.append(msg)
            except Exception: pass

    _osnap_enabled = True  # assume snaps start ON

    def toggle_osnap(self):
        try:
            # Use FreeCAD's own toggle — this actually enables/disables snapping
            Gui.runCommand('Draft_Snap_Lock', 0)
            # Toggle our tracking flag
            ClassicDraftTools._osnap_enabled = not ClassicDraftTools._osnap_enabled
            snap_on = ClassicDraftTools._osnap_enabled
            state = "ON" if snap_on else "OFF"
            self.print_msg(f"< OSNAP {state} >")
            # Defer button sync so FreeCAD finishes its own UI update first
            QtCore.QTimer.singleShot(100, lambda: self._sync_snap_lock_button(snap_on))
            bar = getattr(Gui, 'ccad_status_bar', None)
            if bar and hasattr(bar, 'sync_osnap'):
                bar.sync_osnap()
        except Exception:
            self.print_msg("< OSNAP TOGGLED >")

    @staticmethod
    def _sync_snap_lock_button(snap_on):
        """Force the built-in Draft_Snap_Lock action checked state."""
        try:
            mw = Gui.getMainWindow()
            for act in mw.findChildren(QtGui.QAction):
                if act.objectName() == 'Draft_Snap_Lock' and act.isCheckable():
                    act.blockSignals(True)
                    act.setChecked(snap_on)
                    act.blockSignals(False)
        except Exception:
            pass

    def toggle_ortho(self):
        try:
            ClassicDraftTools._ortho_enabled = not ClassicDraftTools._ortho_enabled
            App.ParamGet(_PREF_GROUP).SetBool("OrthoEnabled", ClassicDraftTools._ortho_enabled)
            state = "ON" if ClassicDraftTools._ortho_enabled else "OFF"
            self.print_msg(f"< ORTHO {state} >")
            # Sync the status bar button
            bar = getattr(Gui, 'ccad_status_bar', None)
            if bar and hasattr(bar, 'sync_ortho'):
                bar.sync_ortho()
        except Exception:
            pass


def setup():
    global _original_snap
    mw = Gui.getMainWindow()
    if not mw: return
    
    # Cleanup old instance
    if hasattr(Gui, "ccad_draft_tools"):
        try:
            if hasattr(Gui.ccad_draft_tools, 'timer'):
                Gui.ccad_draft_tools.timer.stop()
            if hasattr(Gui.ccad_draft_tools, 'restore_preferences'):
                Gui.ccad_draft_tools.restore_preferences()
            app = QtWidgets.QApplication.instance()
            if app:
                app.removeEventFilter(Gui.ccad_draft_tools)
            Gui.ccad_draft_tools.deleteLater()
        except Exception: pass
        del Gui.ccad_draft_tools

    # Monkey-patch Snapper.snap for ortho
    from draftguitools.gui_snapper import Snapper
    if not hasattr(Snapper, '_ccad_original_snap'):
        Snapper._ccad_original_snap = Snapper.snap
    _original_snap = Snapper._ccad_original_snap
    Snapper.snap = _ortho_snap

    Gui.ccad_draft_tools = ClassicDraftTools(mw)


def tear_down():
    global _original_snap
    from draftguitools.gui_snapper import Snapper
    tool = getattr(Gui, 'ccad_draft_tools', None)
    if tool and hasattr(tool, 'restore_preferences'):
        try:
            tool.restore_preferences()
        except Exception:
            pass
    if hasattr(Snapper, '_ccad_original_snap'):
        Snapper.snap = Snapper._ccad_original_snap
        del Snapper._ccad_original_snap
    _original_snap = None


if __name__ == "__main__":
    setup()