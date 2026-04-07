import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore


_DRAFT_PREFS_PATH = "User parameter:BaseApp/Preferences/Mod/Draft"
_DRAFT_CONTINUE_PREFS_PATH = "User parameter:BaseApp/Preferences/Mod/Draft/ContinueMode"


def _msg(console, text):
    if console and hasattr(console, "history"):
        console.history.append(text)
    else:
        App.Console.PrintMessage(text + "\n")


def _warn(console, text):
    if console and hasattr(console, "history"):
        console.history.append(text)
    else:
        App.Console.PrintWarning(text + "\n")


def _draft_params():
    return App.ParamGet(_DRAFT_PREFS_PATH)


def _draft_continue_params():
    return App.ParamGet(_DRAFT_CONTINUE_PREFS_PATH)


def _set_copy_checkbox(ui, copy_mode):
    if not ui or not hasattr(ui, "isCopy"):
        return False
    try:
        ui.isCopy.show()
        ui.isCopy.setChecked(bool(copy_mode))
        return True
    except Exception:
        return False


def _set_continue_checkbox(ui, continue_mode):
    if not ui or not hasattr(ui, "continueCmd"):
        return False
    try:
        checkbox = ui.continueCmd
        checkbox.show()
        blocked = checkbox.blockSignals(True)
        checkbox.setChecked(bool(continue_mode))
        checkbox.blockSignals(blocked)
        ui.continueMode = bool(continue_mode)
        return True
    except Exception:
        return False


def _set_move_mode_on_active_draft_command(copy_mode):
    cmd = getattr(App, "activeDraftCommand", None)
    if not cmd:
        return False

    enabled = False
    continue_mode = bool(copy_mode)

    # Draft Move stores the actual mode on `copymode`.
    if hasattr(cmd, "copymode"):
        try:
            cmd.copymode = bool(copy_mode)
            enabled = True
        except Exception:
            pass

    # Update both the command UI and the shared Draft toolbar, if available.
    if _set_copy_checkbox(getattr(cmd, "ui", None), copy_mode):
        enabled = True
    if _set_copy_checkbox(getattr(Gui, "draftToolBar", None), copy_mode):
        enabled = True
    if _set_continue_checkbox(getattr(cmd, "ui", None), continue_mode):
        enabled = True
    if _set_continue_checkbox(getattr(Gui, "draftToolBar", None), continue_mode):
        enabled = True

    return enabled


def _post_set_move_mode(copy_mode, console=None):
    # Draft command activation is asynchronous enough that flipping the flag
    # immediately can miss the real active command instance.
    if not _set_move_mode_on_active_draft_command(copy_mode) and console:
        name = "COPY" if copy_mode else "MOVE"
        _warn(console, f"{name}: Draft Move started, but the task-panel copy option could not be confirmed")


class _CopySession(QtCore.QObject):
    def __init__(self, console=None):
        parent = Gui.getMainWindow() if hasattr(Gui, "getMainWindow") else None
        super().__init__(parent)
        self.console = console
        self._draft_params = _draft_params()
        self._continue_params = _draft_continue_params()
        self._original_copy_mode = self._draft_params.GetBool("CopyMode", False)
        self._original_select_base = self._draft_params.GetBool("selectBaseObjects", False)
        self._original_move_continue = self._continue_params.GetBool("Move", False)
        self._restored = False
        self._last_move_seen = time.time()
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(120)
        self.apply_preferences()

    def _move_is_active(self):
        cmd = getattr(App, "activeDraftCommand", None)
        feature_name = getattr(cmd, "featureName", "") if cmd else ""
        class_name = getattr(getattr(cmd, "__class__", None), "__name__", "") if cmd else ""
        if feature_name == "Move" or class_name == "Move":
            self._last_move_seen = time.time()
            return True

        toolbar = getattr(Gui, "draftToolBar", None)
        source_cmd = getattr(toolbar, "sourceCmd", None) if toolbar else None
        if getattr(source_cmd, "featureName", "") == "Move":
            self._last_move_seen = time.time()
            return True

        return False

    def apply_preferences(self):
        if self._restored:
            return

        self._draft_params.SetBool("CopyMode", True)
        self._draft_params.SetBool("selectBaseObjects", True)
        self._continue_params.SetBool("Move", True)
        _set_move_mode_on_active_draft_command(True)

    def _poll(self):
        if self._restored:
            return

        self.apply_preferences()
        if self._move_is_active():
            return

        if time.time() - self._last_move_seen < 0.8:
            return

        self.restore()

    def restore(self):
        if self._restored:
            return

        self._restored = True
        try:
            self._timer.stop()
        except Exception:
            pass

        self._draft_params.SetBool("CopyMode", self._original_copy_mode)
        self._draft_params.SetBool("selectBaseObjects", self._original_select_base)
        self._continue_params.SetBool("Move", self._original_move_continue)

        toolbar = getattr(Gui, "draftToolBar", None)
        if toolbar:
            try:
                toolbar.continueMode = bool(self._original_move_continue)
            except Exception:
                pass
            try:
                checkbox = getattr(toolbar, "isCopy", None)
                if checkbox:
                    blocked = checkbox.blockSignals(True)
                    checkbox.setChecked(bool(self._original_copy_mode))
                    checkbox.blockSignals(blocked)
            except Exception:
                pass

        if getattr(Gui, "ccad_copy_session", None) is self:
            Gui.ccad_copy_session = None


def _stop_copy_session():
    session = getattr(Gui, "ccad_copy_session", None)
    if session and hasattr(session, "restore"):
        try:
            session.restore()
        except Exception:
            pass


def _start_copy_session(console=None):
    _stop_copy_session()
    Gui.ccad_copy_session = _CopySession(console=console)
    return Gui.ccad_copy_session


def run(console=None, copy_mode=True):
    command_name = "COPY" if copy_mode else "MOVE"

    if copy_mode:
        _start_copy_session(console=console)
    else:
        _stop_copy_session()

    # Close Draft Edit grips if they are open so Move starts cleanly.
    try:
        if hasattr(App, "activeDraftCommand") and App.activeDraftCommand:
            cls = getattr(App.activeDraftCommand.__class__, "__name__", "") or ""
            if "Edit" in cls:
                Gui.Control.closeDialog()
    except Exception:
        pass

    try:
        Gui.getMainWindow().setFocus()
    except Exception:
        pass

    try:
        Gui.runCommand("Draft_Move", 0)
    except TypeError:
        Gui.runCommand("Draft_Move")
    except Exception as exc:
        if copy_mode:
            _stop_copy_session()
        _warn(console, f"{command_name}: could not start Draft Move ({exc})")
        return

    # Apply the desired state repeatedly until the task panel is fully ready.
    for delay in (0, 50, 150, 300):
        QtCore.QTimer.singleShot(delay, lambda mode=copy_mode: _post_set_move_mode(mode, console))

    mode_text = "copy enabled, continue enabled" if copy_mode else "copy disabled, continue disabled"
    _msg(console, f"{command_name}: Draft Move started ({mode_text})")
