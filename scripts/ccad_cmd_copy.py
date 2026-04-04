import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore


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


def _set_copy_checkbox(ui, copy_mode):
    if not ui or not hasattr(ui, "isCopy"):
        return False
    try:
        ui.isCopy.show()
        ui.isCopy.setChecked(bool(copy_mode))
        return True
    except Exception:
        return False


def _set_move_mode_on_active_draft_command(copy_mode):
    cmd = getattr(App, "activeDraftCommand", None)
    if not cmd:
        return False

    enabled = False

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

    return enabled


def _post_set_move_mode(copy_mode, console=None):
    # Draft command activation is asynchronous enough that flipping the flag
    # immediately can miss the real active command instance.
    if not _set_move_mode_on_active_draft_command(copy_mode) and console:
        name = "COPY" if copy_mode else "MOVE"
        _warn(console, f"{name}: Draft Move started, but the task-panel copy option could not be confirmed")


def run(console=None, copy_mode=True):
    command_name = "COPY" if copy_mode else "MOVE"

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
        _warn(console, f"{command_name}: could not start Draft Move ({exc})")
        return

    # Apply the desired state repeatedly until the task panel is fully ready.
    for delay in (0, 50, 150, 300):
        QtCore.QTimer.singleShot(delay, lambda mode=copy_mode: _post_set_move_mode(mode, console))

    mode_text = "copy enabled" if copy_mode else "copy disabled"
    _msg(console, f"{command_name}: Draft Move started ({mode_text})")
