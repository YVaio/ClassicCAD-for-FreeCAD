import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtWidgets, QtCore, QtGui
import ccad_layers
import ccad_cmd_xline
import ccad_cmd_trim
import ccad_cmd_join


def _handler_active():
    """True if any custom interactive handler is running."""
    if hasattr(Gui, 'ccad_xline_handler') and Gui.ccad_xline_handler:
        return True
    if hasattr(Gui, 'ccad_trim_handler') and Gui.ccad_trim_handler:
        return True
    if hasattr(Gui, 'ccad_fillet_handler') and Gui.ccad_fillet_handler:
        return True
    return False


class ClassicConsole(QtWidgets.QDockWidget):
    def __init__(self, parent_mw):
        super().__init__(parent_mw)
        self.setObjectName("ClassicConsole")
        self.setWindowTitle("COMMAND LINE")
        self.setTitleBarWidget(QtWidgets.QWidget())

        self.shortcuts = {
            'L': 'LINE',
            'C': 'CIRCLE',
            'A': 'ARC',
            'REC': 'RECTANG',
            'PL': 'PLINE',
            'PO': 'POINT',
            'M': 'MOVE',
            'CO': 'COPY',
            'RO': 'ROTATE',
            'SC': 'SCALE',
            'MI': 'MIRROR',
            'TR': 'TRIM',
            'EX': 'EXTEND',
            'O': 'OFFSET',
            'F': 'FILLET',
            'AR': 'ARRAY',
            'E': 'ERASE',
            'X': 'EXPLODE',
            'J': 'JOIN',
            'H': 'HATCH',
            'U': 'UNDO',
            'LO': 'LAYOFF',
            'LN': 'LAYON',
            'RR': 'RELOAD',
            'RE': 'REGEN',
            'XL': 'XLINE',
            'XLH': 'XLINEH',
            'XLV': 'XLINEV',
        }

        self.commands = {
            'LINE': 'Draft_Line',
            'CIRCLE': 'Draft_Circle',
            'ARC': 'Draft_Arc',
            'RECTANG': 'Draft_Rectangle',
            'PLINE': 'Draft_Wire',
            'POINT': 'Draft_Point',
            'MOVE': 'Draft_Move',
            'COPY': 'Draft_Copy',
            'ROTATE': 'Draft_Rotate',
            'SCALE': 'Draft_Scale',
            'MIRROR': 'Draft_Mirror',
            'TRIM': 'TRIM_CCAD',
            'EXTEND': 'EXTEND_CCAD',
            'OFFSET': 'Draft_Offset',
            'FILLET': 'FILLET_CCAD',
            'ARRAY': 'Draft_Array',
            'ERASE': 'Std_Delete',
            'EXPLODE': 'EXPLODE_CCAD',
            'JOIN': 'JOIN_CCAD',
            'HATCH': 'Draft_Hatch',
            'UNDO': 'Std_Undo',
            'LAYOFF': 'LAYOFF',
            'LAYON': 'LAYON',
            'RELOAD': 'RELOAD_CCAD',
            'REGEN': 'REGEN_CCAD',
            'XLINE': 'XLINE_CCAD',
            'XLINEH': 'XLINEH_CCAD',
            'XLINEV': 'XLINEV_CCAD',
        }

        self.last_command = None

        self.main_widget = QtWidgets.QWidget()
        self.layout = QtWidgets.QVBoxLayout(self.main_widget)
        self.layout.setContentsMargins(2, 2, 2, 2)
        self.layout.setSpacing(0)

        self.history = QtWidgets.QTextEdit()
        self.history.setReadOnly(True)
        self.history.setStyleSheet(
            "background:#0c0c0c; color:#aaa; font-family:'Consolas'; border:none; font-size:11px;")

        self.input = QtWidgets.QLineEdit()
        self.input.setStyleSheet(
            "background:#1e1e1e; color:#fff; border:1px solid #333; "
            "font-family:'Consolas'; padding:4px; font-size:12px;")

        self.search_data = []
        for alias, full in self.shortcuts.items():
            self.search_data.append(f"{alias} ({full})")
        for full in self.commands.keys():
            if full not in self.shortcuts.values():
                self.search_data.append(full)

        self.completer = QtWidgets.QCompleter(self.search_data)
        self.completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.completer.setFilterMode(QtCore.Qt.MatchStartsWith)
        self.completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        self.input.setCompleter(self.completer)

        self.layout.addWidget(self.history)
        self.layout.addWidget(self.input)
        self.setWidget(self.main_widget)

        self.input.returnPressed.connect(self.execute)
        self.input.textChanged.connect(self.check_space)

    def _on_ortho_click(self):
        import ccad_draft_tools
        dt = getattr(Gui, 'ccad_draft_tools', None)
        if dt:
            dt.toggle_ortho()
        else:
            ccad_draft_tools.ClassicDraftTools._ortho_enabled = not ccad_draft_tools.ClassicDraftTools._ortho_enabled
        bar = getattr(Gui, 'ccad_status_bar', None)
        if bar:
            bar.sync_ortho()

    def check_space(self, text):
        if text.endswith(" "):
            self.execute()

    # ── command dispatch ──────────────────────

    def execute(self, force_repeat=False):
        # If a custom handler (XLINE, etc.) owns the input, delegate to it
        handler = getattr(Gui, 'ccad_xline_handler', None)
        if handler and hasattr(handler, '_on_input'):
            handler._on_input()
            return

        # Fillet handler only intercepts when waiting for radius or R input
        fillet = getattr(Gui, 'ccad_fillet_handler', None)
        if fillet and hasattr(fillet, '_on_input'):
            text = self.input.text().strip().upper()
            if fillet._waiting_radius or text == 'R':
                fillet._on_input()
                return

        raw_text = self.input.text().strip().upper()

        if not raw_text:
            if force_repeat and self.last_command:
                raw_text = self.last_command
            else:
                return
        else:
            if raw_text not in self.shortcuts and raw_text not in self.commands:
                self.completer.setCompletionPrefix(raw_text)
                if self.completer.completionCount() > 0:
                    raw_text = self.completer.currentCompletion().upper()

        clean_input = raw_text.split(' ')[0]
        cmd_name = self.shortcuts.get(clean_input, clean_input)
        freecad_cmd = self.commands.get(cmd_name)

        if freecad_cmd:
            self.history.append(f"<span style='color:#55ff55;'>&gt; {cmd_name}</span>")
            self.last_command = clean_input
            self.input.clear()
            try:
                self._dispatch(freecad_cmd)
            except Exception as e:
                self.history.append(f"<span style='color:red;'>Command failed: {str(e)}</span>")
        else:
            if clean_input:
                self.history.append(f"<span style='color:#ff5555;'>Unknown command: {clean_input}</span>")
            self.input.clear()

        self.history.moveCursor(QtGui.QTextCursor.End)

    def _dispatch(self, freecad_cmd):
        # Clean up any active interactive handlers before starting a new command
        self._cleanup_handlers()

        # ── REGEN ──
        if freecad_cmd == 'REGEN_CCAD':
            import ccad_dev_tools, importlib
            importlib.reload(ccad_dev_tools)
            ccad_dev_tools.REGEN()
            return

        # ── JOIN (needs current selection, skip auto-deselect) ──
        if freecad_cmd == 'JOIN_CCAD':
            ccad_cmd_join.run(self)
            return

        # ── Auto-deselect before creation commands (not modify commands) ──
        _keep_sel = ('REGEN_CCAD', 'RELOAD_CCAD', 'JOIN_CCAD', 'EXPLODE_CCAD',
                     'Draft_Move', 'Draft_Copy', 'Draft_Rotate', 'Draft_Scale',
                     'Draft_Mirror', 'Draft_Offset', 'Std_Delete')
        if freecad_cmd not in _keep_sel:
            self._auto_deselect()

        # ── RELOAD ──
        if freecad_cmd == 'RELOAD_CCAD':
            self.input.clear()
            self.history.append("<span style='color:#ffff55;'>System Resetting...</span>")
            Gui.Selection.clearSelection()
            import ccad_dev_tools, importlib
            importlib.reload(ccad_dev_tools)
            ccad_dev_tools.reload_classic_cad()
            return  # self is dead after reload

        # ── XLINE ──
        if freecad_cmd in ('XLINE_CCAD', 'XLINEH_CCAD', 'XLINEV_CCAD'):
            opt = {'XLINE_CCAD': None, 'XLINEH_CCAD': 'H', 'XLINEV_CCAD': 'V'}[freecad_cmd]
            ccad_cmd_xline.run(self, opt)
            return

        # ── ERASE — close Draft_Edit grips first to avoid stale markers ──
        if freecad_cmd == 'Std_Delete':
            self._close_grips()
            Gui.runCommand('Std_Delete')
            Gui.Selection.clearSelection()
            return

        # ── TRIM / EXTEND ──
        if freecad_cmd in ('TRIM_CCAD', 'EXTEND_CCAD'):
            mode = 'TRIM' if freecad_cmd == 'TRIM_CCAD' else 'EXTEND'
            ccad_cmd_trim.run(self, mode)
            return

        # ── FILLET ──
        if freecad_cmd == 'FILLET_CCAD':
            ccad_cmd_trim.run_fillet(self)
            return

        # ── Layer commands ──
        if freecad_cmd in ('LAYOFF', 'LAYON'):
            if freecad_cmd == 'LAYOFF':
                ccad_layers.LAYOFF()
            else:
                ccad_layers.LAYON()
            return

        # ── EXPLODE ──
        if freecad_cmd == 'EXPLODE_CCAD':
            self._explode()
            return

        # ── Standard FreeCAD / Draft commands ──
        Gui.getMainWindow().setFocus()
        Gui.runCommand(freecad_cmd)

    def _cleanup_handlers(self):
        """Clean up any active interactive handlers."""
        for attr in ('ccad_xline_handler', 'ccad_trim_handler', 'ccad_fillet_handler'):
            handler = getattr(Gui, attr, None)
            if handler and hasattr(handler, 'cleanup'):
                handler.cleanup()

    def _close_grips(self):
        """Close Draft_Edit to remove grip markers from the viewport."""
        try:
            if hasattr(App, 'activeDraftCommand') and App.activeDraftCommand:
                cls = App.activeDraftCommand.__class__.__name__ or ''
                if 'Edit' in cls:
                    Gui.Control.closeDialog()
        except Exception:
            pass
        blocker = getattr(Gui, 'ccad_auto_blocker', None)
        if blocker:
            blocker._gripped_objects = []

    def _auto_deselect(self):
        """Clear selection and grips before starting a new command."""
        if hasattr(App, 'activeDraftCommand') and App.activeDraftCommand:
            try:
                Gui.Control.closeDialog()
            except Exception:
                pass
        blocker = getattr(Gui, 'ccad_auto_blocker', None)
        if blocker:
            blocker._opening_grips = True
            blocker._gripped_objects = []
        pickadd = getattr(Gui, 'ccad_pickadd_filter', None)
        if pickadd:
            pickadd._escaping = True
            pickadd.previous_selection = []
        Gui.Selection.clearSelection()
        if blocker:
            blocker._opening_grips = False
        if pickadd:
            pickadd._escaping = False

    def _explode(self):
        """Break selected wires into individual Draft lines."""
        import Draft
        sel = Gui.Selection.getSelection()
        if not sel:
            self.history.append(
                "<span style='color:#ff5555;'>EXPLODE: No objects selected</span>")
            return
        doc = App.ActiveDocument
        count = 0
        for obj in sel:
            if not hasattr(obj, 'Shape') or obj.Shape.isNull():
                continue
            edges = obj.Shape.Edges
            if len(edges) < 2:
                continue  # single-edge object, nothing to explode
            lc = None
            if hasattr(obj, 'ViewObject') and hasattr(obj.ViewObject, 'LineColor'):
                lc = tuple(obj.ViewObject.LineColor[:3]) + (0.0,)
            for e in edges:
                verts = e.Vertexes
                if len(verts) >= 2:
                    w = Draft.make_wire(
                        [verts[0].Point, verts[-1].Point],
                        closed=False, face=False)
                    if lc and hasattr(w, 'ViewObject'):
                        w.ViewObject.LineColor = lc
                    count += 1
            doc.removeObject(obj.Name)
        doc.recompute()
        Gui.Selection.clearSelection()
        self.history.append(
            f"<span style='color:#55ff55;'>EXPLODE: {count} lines created</span>")

    # ── utility queries ───────────────────────

    def is_draft_active(self):
        return hasattr(App, 'activeDraftCommand') and App.activeDraftCommand is not None

    def _is_non_edit_command(self):
        if not hasattr(App, 'activeDraftCommand') or not App.activeDraftCommand:
            return False
        cls_name = App.activeDraftCommand.__class__.__name__ or ''
        return 'Edit' not in cls_name

    # ── app-level event filter ────────────────

    def eventFilter(self, obj, event):
        # Block Space shortcut to prevent Std_ToggleVisibility from hiding objects
        if event.type() == QtCore.QEvent.ShortcutOverride and event.key() == QtCore.Qt.Key_Space:
            fw = QtWidgets.QApplication.focusWidget()
            if not isinstance(fw, (QtWidgets.QLineEdit, QtWidgets.QDoubleSpinBox, QtWidgets.QSpinBox)):
                event.accept()
                return True

        if event.type() == QtCore.QEvent.KeyPress:
            # Delete key: close grips first so markers are cleaned up
            if event.key() == QtCore.Qt.Key_Delete:
                self._close_grips()
                Gui.runCommand('Std_Delete')
                Gui.Selection.clearSelection()
                return True

            fw = QtWidgets.QApplication.focusWidget()
            is_input = isinstance(fw, (QtWidgets.QLineEdit,
                                       QtWidgets.QDoubleSpinBox,
                                       QtWidgets.QSpinBox))

            if event.key() == QtCore.Qt.Key_Escape:
                if self.input.hasFocus() and self.input.text():
                    self.input.clear()
                    return True

            if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter,
                               QtCore.Qt.Key_Space):
                if is_input and fw != self.input:
                    return False
                if fw == self.input:
                    return False

                if self._is_non_edit_command():
                    enter = QtGui.QKeyEvent(QtCore.QEvent.KeyPress,
                                            QtCore.Qt.Key_Return,
                                            QtCore.Qt.NoModifier)
                    QtWidgets.QApplication.postEvent(
                        QtWidgets.QApplication.focusWidget(), enter)
                    return True

                if _handler_active():
                    # Block Space to prevent Std_ToggleVisibility hiding objects
                    if event.key() == QtCore.Qt.Key_Space:
                        return True
                    return False

                self.execute(force_repeat=True)
                return True
        return False


# ─────────────────────────────────────────────
# Setup / teardown
# ─────────────────────────────────────────────
def setup():
    mw = Gui.getMainWindow()
    if not mw:
        return

    for child in mw.findChildren(QtWidgets.QDockWidget):
        if child.objectName() == "ClassicConsole":
            QtWidgets.QApplication.instance().removeEventFilter(child)
            child.deleteLater()

    Gui.classic_console = ClassicConsole(mw)
    mw.addDockWidget(QtCore.Qt.BottomDockWidgetArea, Gui.classic_console)
    QtWidgets.QApplication.instance().installEventFilter(Gui.classic_console)

    if hasattr(Gui, "ccad_shortcuts"):
        for s in Gui.ccad_shortcuts:
            s.deleteLater()
    Gui.ccad_shortcuts = []

    def focus_and_type(char):
        fw = QtWidgets.QApplication.focusWidget()
        if isinstance(fw, (QtWidgets.QLineEdit, QtWidgets.QDoubleSpinBox,
                           QtWidgets.QSpinBox)):
            return
        if _handler_active():
            return
        if hasattr(Gui, "classic_console"):
            if Gui.classic_console._is_non_edit_command():
                return
            Gui.classic_console.input.setFocus()
            Gui.classic_console.input.insert(char)

    for char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
        s = QtGui.QShortcut(QtGui.QKeySequence(char), mw)
        s.activated.connect(lambda c=char: focus_and_type(c))
        Gui.ccad_shortcuts.append(s)


if __name__ == "__main__":
    setup()
