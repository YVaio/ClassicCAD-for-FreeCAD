import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore, QtGui, QtWidgets

_original_snap = None
_PATCHED_DRAFT_METHODS = {}

_DRAFT_PREFS_PATH = "User parameter:BaseApp/Preferences/Mod/Draft"

_ORTHO_SUSPEND_CMDS = ('Rectangle',)
_LENGTH_FOCUS_RETRY_DELAYS = (0, 40, 140)
_TAB_NAVIGATION_WIDGETS = (
    'xValue',
    'yValue',
    'zValue',
    'lengthValue',
    'angleValue',
    'radiusValue',
    'numFaces',
    'pointButton',
    'finishButton',
    'closeButton',
    'wipeButton',
    'undoButton',
    'orientWPButton',
    'selectButton',
    'angleLock',
    'isRelative',
    'isGlobal',
    'makeFace',
    'isCopy',
    'isSubelementMode',
    'continueCmd',
    'chainedModeCmd',
    'occOffset',
)


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


def _is_classiccad_active():
    try:
        wb = Gui.activeWorkbench()
        return bool(wb and wb.__class__.__name__ == "ClassicCADWorkbench")
    except Exception:
        return False


def _active_draft_command():
    return getattr(App, 'activeDraftCommand', None)


def _is_non_edit_draft_command():
    cmd = _active_draft_command()
    cls_name = getattr(getattr(cmd, '__class__', None), '__name__', '') if cmd else ''
    return bool(cmd and 'Edit' not in cls_name)


def _is_text_entry_command():
    cmd = _active_draft_command()
    cls_name = getattr(getattr(cmd, '__class__', None), '__name__', '') if cmd else ''
    return any(token in cls_name for token in ('Text', 'ShapeString', 'Label'))


def _patch_draft_method(owner, name, wrapper_factory):
    key = (owner, name)
    if key in _PATCHED_DRAFT_METHODS:
        return
    original = getattr(owner, name, None)
    if not callable(original):
        return
    setattr(owner, name, wrapper_factory(original))
    _PATCHED_DRAFT_METHODS[key] = original


def _restore_draft_patches():
    for (owner, name), original in list(_PATCHED_DRAFT_METHODS.items()):
        try:
            setattr(owner, name, original)
        except Exception:
            pass
    _PATCHED_DRAFT_METHODS.clear()


def _spinbox_for_widget(widget):
    current = widget
    while current:
        if isinstance(current, QtWidgets.QAbstractSpinBox):
            return current
        current = current.parentWidget() if hasattr(current, 'parentWidget') else None
    return None


def _navigation_identity(widget):
    return _spinbox_for_widget(widget) or widget


def _is_focusable_widget(widget):
    if widget is None:
        return False
    try:
        return widget.isVisible() and widget.isEnabled() and widget.focusPolicy() != QtCore.Qt.NoFocus
    except Exception:
        return False


def _toolbar_navigation_targets(toolbar):
    targets = []
    seen = set()
    for name in _TAB_NAVIGATION_WIDGETS:
        widget = getattr(toolbar, name, None)
        identity = _navigation_identity(widget)
        if identity is None or identity in seen:
            continue
        if _is_focusable_widget(identity):
            seen.add(identity)
            targets.append(identity)
    return targets


def _cycle_task_panel_focus(toolbar, current_widget, backwards=False):
    targets = _toolbar_navigation_targets(toolbar)
    if not targets:
        return False

    current = _navigation_identity(current_widget)
    try:
        index = targets.index(current)
    except ValueError:
        index = -1 if not backwards else 0

    step = -1 if backwards else 1
    next_index = (index + step) % len(targets)
    return _focus_input_widget(targets[next_index], toolbar)


class _TaskPanelTabFilter(QtCore.QObject):
    def __init__(self, toolbar, parent=None):
        super().__init__(parent)
        self.toolbar = toolbar

    def eventFilter(self, obj, event):
        if not _is_classiccad_active():
            return False

        if event.type() == QtCore.QEvent.ShortcutOverride:
            key = event.key()
            if key in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Backtab, QtCore.Qt.Key_Space):
                event.accept()
            return False

        if event.type() != QtCore.QEvent.KeyPress:
            return False

        key = event.key()
        if key == QtCore.Qt.Key_Space and _should_force_task_panel_confirm():
            confirmed = _force_task_panel_confirm(self.toolbar)
            if confirmed:
                event.accept()
            return confirmed

        if key not in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Backtab):
            return False

        modifiers = event.modifiers()
        backwards = key == QtCore.Qt.Key_Backtab or bool(modifiers & QtCore.Qt.ShiftModifier)
        moved = _cycle_task_panel_focus(self.toolbar, obj, backwards=backwards)
        if moved:
            event.accept()
        return moved


def _task_panel_filter_widgets(toolbar):
    widgets = []
    seen = set()
    for name in _TAB_NAVIGATION_WIDGETS:
        target = getattr(toolbar, name, None)
        identity = _navigation_identity(target)
        for widget in (identity, getattr(identity, 'lineEdit', lambda: None)() if isinstance(identity, QtWidgets.QAbstractSpinBox) else None):
            if widget is None or widget in seen:
                continue
            seen.add(widget)
            widgets.append(widget)
    return widgets


def _ensure_task_panel_tab_filter(toolbar):
    base_widget = getattr(toolbar, 'baseWidget', None)
    if not base_widget:
        return

    tab_filter = getattr(toolbar, '_ccad_task_panel_tab_filter', None)
    needs_new_filter = tab_filter is None
    if tab_filter is not None:
        try:
            needs_new_filter = tab_filter.parent() is not base_widget
        except RuntimeError:
            needs_new_filter = True
            try:
                toolbar._ccad_task_panel_tab_filter = None
            except Exception:
                pass

    if needs_new_filter:
        tab_filter = _TaskPanelTabFilter(toolbar, base_widget)
        toolbar._ccad_task_panel_tab_filter = tab_filter

    for widget in _task_panel_filter_widgets(toolbar):
        try:
            if widget.property('_ccadTaskPanelTabFilterInstalled'):
                continue
            widget.installEventFilter(tab_filter)
            widget.setProperty('_ccadTaskPanelTabFilterInstalled', True)
        except Exception:
            pass


def _focus_input_widget(widget, toolbar=None):
    target = _spinbox_for_widget(widget) or widget
    line_edit = None
    if isinstance(target, QtWidgets.QAbstractSpinBox):
        try:
            line_edit = target.lineEdit()
        except Exception:
            line_edit = None

    focus_widget = line_edit or target
    try:
        focus_widget.setFocus(QtCore.Qt.OtherFocusReason)
    except Exception:
        return False

    try:
        if line_edit:
            line_edit.selectAll()
        elif toolbar and hasattr(toolbar, 'number_length') and hasattr(target, 'setSelection') and hasattr(target, 'text'):
            target.setSelection(0, toolbar.number_length(target.text()))
        elif hasattr(target, 'selectAll'):
            target.selectAll()
    except Exception:
        pass
    return True


def _focus_length_input(toolbar=None):
    if not _is_classiccad_active():
        return False

    toolbar = toolbar or getattr(Gui, 'draftToolBar', None)
    if not toolbar:
        return False

    target = getattr(toolbar, 'lengthValue', None)
    if not target:
        return False

    try:
        visible = target.isVisible() and target.isEnabled()
    except Exception:
        visible = False
    if not visible:
        return False

    return _focus_input_widget(target, toolbar)


def _schedule_length_focus(toolbar=None, delays=None):
    if not _is_classiccad_active():
        return

    toolbar = toolbar or getattr(Gui, 'draftToolBar', None)
    if not toolbar:
        return

    for delay in (delays or _LENGTH_FOCUS_RETRY_DELAYS):
        QtCore.QTimer.singleShot(delay, lambda tb=toolbar: _focus_length_input(tb))


def _force_task_panel_confirm(toolbar):
    if not toolbar:
        return False

    focus_widget = QtWidgets.QApplication.focusWidget()
    spinbox = _spinbox_for_widget(focus_widget)
    if spinbox is not None:
        try:
            spinbox.interpretText()
        except Exception:
            pass

    validate_point = getattr(toolbar, 'validatePoint', None)
    if not callable(validate_point):
        return False

    try:
        return validate_point()
    except TypeError:
        try:
            return validate_point(False)
        except Exception:
            return False
    except Exception:
        return False


def _should_force_task_panel_confirm():
    return _is_classiccad_active() and _is_non_edit_draft_command() and not _is_text_entry_command()


def _install_draft_taskpanel_patches():
    _restore_draft_patches()

    try:
        import DraftGui
    except Exception:
        return

    toolbar_cls = getattr(DraftGui, 'DraftToolBar', None)
    if not toolbar_cls:
        return

    def _confirm_wrapper(original):
        def patched(self, *args, **kwargs):
            if _should_force_task_panel_confirm():
                return _force_task_panel_confirm(self)
            return original(self, *args, **kwargs)

        return patched

    for name in ('checkx', 'checky', 'checklength'):
        _patch_draft_method(toolbar_cls, name, _confirm_wrapper)

    def _extra_line_ui_wrapper(original):
        def patched(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            _schedule_length_focus(self)
            return result

        return patched

    _patch_draft_method(toolbar_cls, 'extraLineUi', _extra_line_ui_wrapper)

    def _wire_ui_wrapper(original):
        def patched(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            if not getattr(self, 'lengthValue', None) or not self.lengthValue.isVisible():
                self.extraLineUi()
            return result

        return patched

    _patch_draft_method(toolbar_cls, 'wireUi', _wire_ui_wrapper)

    def _setup_toolbar_wrapper(original):
        def patched(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            _ensure_task_panel_tab_filter(self)
            return result

        return patched

    _patch_draft_method(toolbar_cls, 'setupToolBar', _setup_toolbar_wrapper)


_PREF_GROUP = "User parameter:BaseApp/Preferences/Mod/ClassicCAD"

class ClassicDraftTools(QtCore.QObject):
    _ortho_enabled = App.ParamGet(_PREF_GROUP).GetBool("OrthoEnabled", False)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mw = Gui.getMainWindow()
        self._draft_params = App.ParamGet(_DRAFT_PREFS_PATH)
        self._original_focus_on_length = self._draft_params.GetBool("focusOnLength", False)
        self._draft_params.SetBool("focusOnLength", True)
        _install_draft_taskpanel_patches()
        
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
    _restore_draft_patches()
    
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
    _restore_draft_patches()
    _original_snap = None


if __name__ == "__main__":
    setup()