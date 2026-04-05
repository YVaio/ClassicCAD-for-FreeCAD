import FreeCAD as App
import FreeCADGui as Gui
import time
from PySide6 import QtCore


_SUPPORTED_TYPES = {"Rectangle", "Wire", "BSpline", "BezCurve", "Sketch", "Wall"}


def _msg(console, text):
    if console and hasattr(console, 'history'):
        console.history.append(text)
    else:
        App.Console.PrintMessage(text + "\n")


def _warn(console, text):
    if console and hasattr(console, 'history'):
        console.history.append(text)
    else:
        App.Console.PrintWarning(text + "\n")


def _close_grips():
    blocker = getattr(Gui, 'ccad_auto_blocker', None)
    previous_state = getattr(blocker, '_opening_grips', False) if blocker else False
    if blocker:
        blocker._opening_grips = True
        blocker._gripped_objects = []

    try:
        try:
            if hasattr(App, 'activeDraftCommand') and App.activeDraftCommand:
                cls_name = getattr(App.activeDraftCommand.__class__, '__name__', '') or ''
                if 'Edit' in cls_name:
                    Gui.Control.closeDialog()
        except Exception:
            pass

        try:
            if getattr(Gui, 'ActiveDocument', None) and hasattr(Gui.ActiveDocument, 'resetEdit'):
                Gui.ActiveDocument.resetEdit()
        except Exception:
            pass
    finally:
        if blocker:
            blocker._opening_grips = previous_state


def _draft_type(obj):
    try:
        from draftutils import utils as draft_utils
        return draft_utils.getType(obj)
    except Exception:
        return ''


def _supports_stretch(obj, seen=None):
    if not obj:
        return False

    seen = seen or set()
    name = getattr(obj, 'Name', None)
    if name in seen:
        return False
    if name:
        seen.add(name)

    if _draft_type(obj) in _SUPPORTED_TYPES:
        return True

    for attr in ('Source', 'Base'):
        base = getattr(obj, attr, None)
        if base and _supports_stretch(base, seen):
            return True

    return False


def _wrapped_target_names(obj, seen=None):
    if not obj:
        return []

    seen = seen or set()
    name = getattr(obj, 'Name', None)
    if name in seen:
        return []
    if name:
        seen.add(name)

    if _draft_type(obj) in _SUPPORTED_TYPES:
        return []

    targets = []
    for attr in ('Source', 'Base'):
        base = getattr(obj, attr, None)
        if not base:
            continue
        if _draft_type(base) in _SUPPORTED_TYPES:
            base_name = getattr(base, 'Name', None)
            if base_name:
                targets.append(base_name)
        else:
            targets.extend(_wrapped_target_names(base, seen))
    return targets


def _visible_stretch_candidates(doc):
    wrapped_targets = set()
    visible_supported = []

    for obj in getattr(doc, 'Objects', []):
        view_obj = getattr(obj, 'ViewObject', None)
        if not view_obj or not getattr(view_obj, 'Visibility', False):
            continue
        if not _supports_stretch(obj):
            continue
        visible_supported.append(obj)
        wrapped_targets.update(_wrapped_target_names(obj))

    candidates = []
    for obj in visible_supported:
        if _draft_type(obj) in _SUPPORTED_TYPES and getattr(obj, 'Name', '') in wrapped_targets:
            continue
        candidates.append(obj)
    return candidates


def _suppress_auto_grips(seconds=2.5):
    blocker = getattr(Gui, 'ccad_auto_blocker', None)
    if blocker:
        blocker._suppress_until = max(getattr(blocker, '_suppress_until', 0.0), time.time() + seconds)


def _set_pickbox_only(enabled):
    if enabled:
        Gui.ccad_pickbox_only = True
    elif hasattr(Gui, 'ccad_pickbox_only'):
        del Gui.ccad_pickbox_only


def _watch_stretch_cursor():
    cmd = getattr(App, 'activeDraftCommand', None)
    if not cmd or 'Stretch' not in (cmd.__class__.__name__ or ''):
        _set_pickbox_only(False)
        return

    step = int(getattr(cmd, 'step', 0) or 0)
    if step >= 2:
        _set_pickbox_only(False)

    QtCore.QTimer.singleShot(90, _watch_stretch_cursor)


def _set_selection(doc, objects):
    blocker = getattr(Gui, 'ccad_auto_blocker', None)
    pickadd = getattr(Gui, 'ccad_pickadd_filter', None)
    previous_state = getattr(blocker, '_opening_grips', False) if blocker else False

    try:
        if blocker:
            blocker._opening_grips = True
            blocker._gripped_objects = []
        _suppress_auto_grips()
        if pickadd:
            pickadd.previous_selection = []
            pickadd._pending_target = ''
            pickadd._skip_restore = True

        Gui.Selection.clearSelection()
        for obj in objects:
            try:
                if doc.getObject(obj.Name):
                    Gui.Selection.addSelection(doc.Name, obj.Name)
            except Exception:
                pass
    finally:
        if blocker:
            blocker._opening_grips = previous_state


def _clear_selection():
    blocker = getattr(Gui, 'ccad_auto_blocker', None)
    pickadd = getattr(Gui, 'ccad_pickadd_filter', None)
    previous_state = getattr(blocker, '_opening_grips', False) if blocker else False

    try:
        if blocker:
            blocker._opening_grips = True
            blocker._gripped_objects = []
        _suppress_auto_grips()
        if pickadd:
            pickadd.previous_selection = []
            pickadd._pending_target = ''
            pickadd._skip_restore = True
        Gui.Selection.clearSelection()
    finally:
        if blocker:
            blocker._opening_grips = previous_state


def run(console=None):
    stale = getattr(Gui, 'ccad_stretch_handler', None)
    if stale:
        cleanup = getattr(stale, 'cleanup', None)
        if callable(cleanup):
            try:
                cleanup(cancelled=True)
            except TypeError:
                cleanup()
        elif hasattr(Gui, 'ccad_stretch_handler'):
            del Gui.ccad_stretch_handler

    _set_pickbox_only(False)

    doc = App.ActiveDocument
    if not doc:
        _warn(console, 'STRETCH: No active document')
        return

    _close_grips()

    try:
        Gui.getMainWindow().setFocus()
    except Exception:
        pass

    preselected = list(Gui.Selection.getSelection())
    temp_candidates = []
    used_temp_selection = False

    if not preselected:
        temp_candidates = _visible_stretch_candidates(doc)
        if temp_candidates:
            _set_selection(doc, temp_candidates)
            used_temp_selection = True

    _set_pickbox_only(True)
    QtCore.QTimer.singleShot(0, _watch_stretch_cursor)

    try:
        Gui.runCommand('Draft_Stretch')
    except Exception as exc:
        _clear_selection()
        _set_pickbox_only(False)
        _warn(console, f'STRETCH: could not start Draft Stretch ({exc})')
        return

    _suppress_auto_grips(3.0)

    if used_temp_selection or preselected:
        QtCore.QTimer.singleShot(0, _clear_selection)
        QtCore.QTimer.singleShot(120, _clear_selection)

    if used_temp_selection:
        _msg(console, f'STRETCH: Draft Stretch started on {len(temp_candidates)} visible candidate(s)')
    elif preselected:
        _msg(console, f'STRETCH: Draft Stretch started on {len(preselected)} selected object(s)')
    else:
        _set_pickbox_only(False)
        _msg(console, 'STRETCH: Select object(s) to stretch')
