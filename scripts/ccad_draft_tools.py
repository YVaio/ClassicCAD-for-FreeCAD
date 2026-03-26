import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore, QtGui, QtWidgets

_original_snap = None

def _ortho_snap(self, screenpos, lastpoint=None, active=True, constrain=False, noTracker=False):
    """Patched Snapper.snap: forces constrain when F8 ortho is ON."""
    try:
        if ClassicDraftTools._ortho_enabled and lastpoint is not None:
            constrain = True
            self.constraintAxis = None
            self.affinity = None
    except Exception:
        pass
    return _original_snap(self, screenpos, lastpoint=lastpoint, active=active, constrain=constrain, noTracker=noTracker)


class ClassicDraftTools(QtCore.QObject):
    _ortho_enabled = False

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mw = Gui.getMainWindow()
        
        # Install app-level event filter so F3/F8 work even during commands
        QtWidgets.QApplication.instance().installEventFilter(self)

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
    if hasattr(Snapper, '_ccad_original_snap'):
        Snapper.snap = Snapper._ccad_original_snap
        del Snapper._ccad_original_snap
    _original_snap = None


if __name__ == "__main__":
    setup()