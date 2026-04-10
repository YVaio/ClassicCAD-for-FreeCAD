import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore

import ccad_layers


STYLE_ATTRS = (
    "LineColor",
    "ShapeColor",
    "PointColor",
    "LineWidth",
    "PointSize",
    "DrawStyle",
    "Transparency",
    "TextColor",
    "FontName",
    "FontSize",
    "ArrowSize",
)


def _msg(console, text, color="#aaa"):
    if console and hasattr(console, "history"):
        console.history.append(f"<span style='color:{color};'>{text}</span>")
    else:
        App.Console.PrintMessage(text + "\n")


def _warn(console, text):
    if console and hasattr(console, "history"):
        console.history.append(f"<span style='color:#ff5555;'>{text}</span>")
    else:
        App.Console.PrintWarning(text + "\n")


def _is_matchable_object(obj):
    if not obj:
        return False
    if ccad_layers._is_layer_container(obj):
        return False
    return True


def _copy_common_view_properties(source_obj, target_obj):
    source_view = getattr(source_obj, "ViewObject", None)
    target_view = getattr(target_obj, "ViewObject", None)
    if not source_view or not target_view:
        return False

    changed = False
    for attr in STYLE_ATTRS:
        if not hasattr(source_view, attr) or not hasattr(target_view, attr):
            continue
        try:
            src_val = getattr(source_view, attr)
            tgt_val = getattr(target_view, attr, None)
            if src_val != tgt_val:
                setattr(target_view, attr, src_val)
                changed = True
        except Exception:
            pass
    return changed


class MatchPropHandler(QtCore.QObject):
    """Selection-observer based MATCHPROP command.

    Uses Gui.Selection.addObserver so that FreeCAD's own Coin3D
    click-to-select drives picking.  No viewport event filter needed
    (and no competing pick logic).
    """

    def __init__(self, console, source=None):
        super().__init__()
        self.console = console
        self.source = None
        self._applying = False          # guard: ignore clearSelection we trigger ourselves
        Gui.ccad_matchprop_handler = self

        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

        if source:
            self._set_source(source)
        else:
            _msg(self.console, "MATCHPROP: Click source object.")

    # ── source setup ───────────────────────────────────────────────

    def _set_source(self, source):
        if not _is_matchable_object(source):
            _warn(self.console, "MATCHPROP: Pick a drawable object, not a layer container.")
            return
        self.source = source
        self._applying = True
        try:
            Gui.Selection.clearSelection()
        finally:
            self._applying = False
        label = getattr(source, "Label", getattr(source, "Name", "object"))
        _msg(self.console,
             f"MATCHPROP: Source '{label}' set. Click destination objects. Press Esc to finish.",
             color="#55ff55")

    # ── property transfer ──────────────────────────────────────────

    def _apply_to_target(self, target):
        # Guard: handler may have been cleaned up before a deferred timer fires.
        if getattr(Gui, 'ccad_matchprop_handler', None) is not self:
            return False
        if not self.source or not _is_matchable_object(target) or target == self.source:
            return False

        doc = getattr(target, "Document", None) or App.ActiveDocument
        if not doc:
            return False

        changed = False
        try:
            doc.openTransaction("Match Properties")
        except Exception:
            pass

        try:
            source_layer = ccad_layers.get_object_layer(self.source)
            if source_layer and ccad_layers.assign_to_layer(target, source_layer):
                changed = True

            if _copy_common_view_properties(self.source, target):
                changed = True
        finally:
            try:
                if changed:
                    doc.commitTransaction()
                elif hasattr(doc, "abortTransaction"):
                    doc.abortTransaction()
                else:
                    doc.commitTransaction()
            except Exception:
                pass

        if changed:
            try:
                doc.recompute()
            except Exception:
                pass
            label = getattr(target, "Label", getattr(target, "Name", "object"))
            _msg(self.console, f"MATCHPROP applied to '{label}'.", color="#55ff55")
        else:
            _warn(self.console, "MATCHPROP: Properties already match.")
        return changed

    # ── Selection Observer interface ───────────────────────────────

    def addSelection(self, doc, obj_name, sub, pnt):
        if self._applying:
            return

        doc_obj = App.ActiveDocument
        if not doc_obj:
            return
        obj = doc_obj.getObject(obj_name)
        if not _is_matchable_object(obj):
            self._applying = True
            try:
                Gui.Selection.clearSelection()
            finally:
                self._applying = False
            return

        if self.source is None:
            self._set_source(obj)
            return

        if obj == self.source:
            return

        self._applying = True
        try:
            Gui.Selection.clearSelection()
        finally:
            self._applying = False
        # Use a single-shot timer so the selection is fully cleared before we do
        # document operations (matches the Fillet handler pattern).
        QtCore.QTimer.singleShot(0, lambda t=obj: self._apply_to_target(t))

    def removeSelection(self, doc, obj_name, sub):
        pass

    def setSelection(self, doc):
        pass

    def clearSelection(self, doc):
        pass

    # ── cleanup ───────────────────────────────────────────────────

    def cleanup(self, cancelled=False):
        try:
            Gui.Selection.removeObserver(self)
        except Exception:
            pass
        if getattr(Gui, 'ccad_matchprop_handler', None) is self:
            Gui.ccad_matchprop_handler = None
        if cancelled:
            _msg(self.console, "MATCHPROP cancelled.")


def run(console):
    handler = getattr(Gui, 'ccad_matchprop_handler', None)
    if handler:
        handler.cleanup(cancelled=True)

    source = None
    try:
        selection = Gui.Selection.getSelection()
    except Exception:
        selection = []
    if selection:
        source = next((obj for obj in selection if _is_matchable_object(obj)), None)

    return MatchPropHandler(console, source=source)