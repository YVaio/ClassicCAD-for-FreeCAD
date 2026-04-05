import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtWidgets, QtCore, QtGui
import ccad_layers
import ccad_cmd_xline
import ccad_cmd_trim
import ccad_cmd_join
import ccad_cmd_spline
import ccad_cmd_copy
import ccad_cmd_stretch


def _handler_active():
    """True if any custom interactive handler is running."""
    if hasattr(Gui, 'ccad_xline_handler') and Gui.ccad_xline_handler:
        return True
    if hasattr(Gui, 'ccad_trim_handler') and Gui.ccad_trim_handler:
        return True
    if hasattr(Gui, 'ccad_fillet_handler') and Gui.ccad_fillet_handler:
        return True
    if hasattr(Gui, 'ccad_spline_handler') and Gui.ccad_spline_handler:
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
            'POL': 'POLYGON',
            'EL': 'ELLIPSE',
            'PL': 'PLINE',
            'PO': 'POINT',
            'SPL': 'SPLINE',
            'M': 'MOVE',
            'CO': 'COPY',
            'RO': 'ROTATE',
            'SC': 'SCALE',
            'MI': 'MIRROR',
            'S': 'STRETCH',
            'TR': 'TRIM',
            'EX': 'EXTEND',
            'O': 'OFFSET',
            'F': 'FILLET',
            'AR': 'ARRAY',
            'E': 'ERASE',
            'X': 'EXPLODE',
            'J': 'JOIN',
            'H': 'HATCH',
            'BO': 'BOUNDARY',
            'T': 'TEXT',
            'MT': 'MTEXT',
            'DIM': 'DIMENSION',
            'D': 'DIMENSION',
            'LE': 'LEADER',
            'G': 'GROUP',
            'U': 'UNDO',
            'R': 'REDO',
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
            'POLYGON': 'Draft_Polygon',
            'ELLIPSE': 'Draft_Ellipse',
            'PLINE': 'Draft_Wire',
            'POINT': 'Draft_Point',
            'MOVE': 'MOVE_CCAD',
            'COPY': 'COPY_CCAD',
            'ROTATE': 'Draft_Rotate',
            'SCALE': 'Draft_Scale',
            'MIRROR': 'Draft_Mirror',
            'STRETCH': 'STRETCH_CCAD',
            'TRIM': 'TRIM_CCAD',
            'EXTEND': 'EXTEND_CCAD',
            'OFFSET': 'Draft_Offset',
            'FILLET': 'FILLET_CCAD',
            'ARRAY': 'Draft_Array',
            'ERASE': 'Std_Delete',
            'EXPLODE': 'EXPLODE_CCAD',
            'JOIN': 'JOIN_CCAD',
            'HATCH': 'Draft_Hatch',
            'BOUNDARY': 'Draft_Upgrade',     # Το Upgrade του FreeCAD μετατρέπει wires σε faces (Region)
            'TEXT': 'Draft_Text',
            'MTEXT': 'Draft_ShapeString',    # Solid 3D κείμενο
            'DIMENSION': 'Draft_Dimension',
            'LEADER': 'Draft_Label',         # Τα labels στο FreeCAD λειτουργούν σαν Leaders
            'GROUP': 'Std_Group',
            'UNDO': 'Std_Undo',
            'REDO': 'Std_Redo',
            'LAYOFF': 'LAYOFF',
            'LAYON': 'LAYON',
            'RELOAD': 'RELOAD_CCAD',
            'REGEN': 'REGEN_CCAD',
            'XLINE': 'XLINE_CCAD',
            'XLINEH': 'XLINEH_CCAD',
            'XLINEV': 'XLINEV_CCAD',
            'SPLINE': 'SPLINE_CCAD',
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
        
        spline = getattr(Gui, 'ccad_spline_handler', None)
        if spline and hasattr(spline, '_on_input'):
            # Αν ο handler αναγνωρίσει το CV ή το F, επιστρέφει True και σταματάμε εδώ.
            if spline._on_input():
                return

        trim = getattr(Gui, 'ccad_trim_handler', None)
        if trim and hasattr(trim, '_on_input'):
            if trim._on_input():
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

        if cmd_name == 'SPLINE':
            self.history.append(f"<span style='color:#55ff55;'>&gt; {cmd_name}</span>")
            self.last_command = clean_input
            self.input.clear()
            import ccad_cmd_spline    # (ή σιγουρέψου ότι το έχεις κάνει import στην αρχή του αρχείου)
            ccad_cmd_spline.run(self)
            self.history.moveCursor(QtGui.QTextCursor.End)
            return
        
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
                     'MOVE_CCAD', 'COPY_CCAD', 'TRIM_CCAD', 'EXTEND_CCAD',
                     'STRETCH_CCAD',
                     'FILLET_CCAD', 'Draft_Rotate', 'Draft_Scale',
                     'Draft_Mirror', 'Draft_Offset', 'Std_Delete', 'Std_Undo',
                     'Std_Redo')
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

        # ── UNDO / REDO — exit any transient Draft edit state first ──
        if freecad_cmd in ('Std_Undo', 'Std_Redo'):
            self._close_grips()
            self._cleanup_handlers()

            try:
                toolbar = getattr(Gui, 'draftToolBar', None)
                if toolbar and hasattr(toolbar, 'finish'):
                    try:
                        toolbar.finish(cont=False)
                    except TypeError:
                        toolbar.finish(False)
            except Exception:
                pass

            try:
                active_cmd = getattr(App, 'activeDraftCommand', None)
                if active_cmd:
                    finish = getattr(active_cmd, 'finish', None)
                    if callable(finish):
                        try:
                            finish(cont=False)
                        except TypeError:
                            finish()
            except Exception:
                pass

            try:
                if getattr(Gui, 'ActiveDocument', None) and hasattr(Gui.ActiveDocument, 'resetEdit'):
                    Gui.ActiveDocument.resetEdit()
            except Exception:
                pass

            try:
                Gui.Control.closeDialog()
            except Exception:
                pass

            try:
                QtWidgets.QApplication.processEvents()
            except Exception:
                pass

            doc = App.ActiveDocument
            try:
                if doc:
                    transacting = False
                    check = getattr(doc, 'transacting', None)
                    if callable(check):
                        try:
                            transacting = bool(check())
                        except Exception:
                            transacting = False
                    if transacting and hasattr(doc, 'commitTransaction'):
                        doc.commitTransaction()
                        try:
                            QtWidgets.QApplication.processEvents()
                        except Exception:
                            pass

                if doc and hasattr(doc, 'undo') and freecad_cmd == 'Std_Undo':
                    doc.undo()
                elif doc and hasattr(doc, 'redo') and freecad_cmd == 'Std_Redo':
                    doc.redo()
                else:
                    Gui.runCommand(freecad_cmd)
            except Exception:
                Gui.runCommand(freecad_cmd)
            return

        # ── ERASE — close Draft_Edit grips first to avoid stale markers ──
        if freecad_cmd == 'Std_Delete':
            self._close_grips()
            Gui.runCommand('Std_Delete')
            Gui.Selection.clearSelection()
            return

        # ── TRIM / EXTEND ──
        if freecad_cmd in ('TRIM_CCAD', 'EXTEND_CCAD'):
            import importlib
            importlib.reload(ccad_cmd_trim)
            mode = 'TRIM' if freecad_cmd == 'TRIM_CCAD' else 'EXTEND'
            ccad_cmd_trim.run(self, mode)
            return

        if freecad_cmd == 'STRETCH_CCAD':
            import importlib
            importlib.reload(ccad_cmd_stretch)
            ccad_cmd_stretch.run(self)
            return

        # ── FILLET ──
        if freecad_cmd == 'FILLET_CCAD':
            import importlib
            import ccad_cmd_fillet
            importlib.reload(ccad_cmd_fillet)
            ccad_cmd_fillet.run(self)
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
        
        # ── MOVE / COPY ──
        if freecad_cmd == 'MOVE_CCAD':
            ccad_cmd_copy.run(self, copy_mode=False)
            return

        if freecad_cmd == 'COPY_CCAD':
            ccad_cmd_copy.run(self, copy_mode=True)
            return

        # ── Standard FreeCAD / Draft commands ──
        Gui.getMainWindow().setFocus()
        Gui.runCommand(freecad_cmd)

    def _cleanup_handlers(self):
        """Clean up any active interactive handlers."""
        for attr in ('ccad_xline_handler', 'ccad_trim_handler', 'ccad_fillet_handler', 'ccad_spline_handler', 'ccad_stretch_handler'):
            handler = getattr(Gui, attr, None)
            if not handler:
                continue
            cleanup = getattr(handler, 'cleanup', None)
            if callable(cleanup):
                try:
                    cleanup(cancelled=True)
                except TypeError:
                    cleanup()

    def _cancel_active_handler(self):
        """Cancel any running ClassicCAD interactive tool."""
        tools = (
            ('ccad_trim_handler', 'TRIM/EXTEND'),
            ('ccad_fillet_handler', 'FILLET'),
            ('ccad_xline_handler', 'XLINE'),
            ('ccad_spline_handler', 'SPLINE'),
            ('ccad_stretch_handler', 'STRETCH'),
        )
        for attr, label in tools:
            handler = getattr(Gui, attr, None)
            if not handler:
                continue

            try:
                toolbar = getattr(Gui, 'draftToolBar', None)
                if toolbar and hasattr(toolbar, 'escape'):
                    try:
                        toolbar.escape()
                    except Exception:
                        pass

                cleanup = getattr(handler, '_cleanup', None)
                if not callable(cleanup):
                    cleanup = getattr(handler, 'cleanup', None)
                if callable(cleanup):
                    try:
                        cleanup(cancelled=True)
                    except TypeError:
                        cleanup()
            finally:
                self.history.append(f"<span style='color:#aaa;'>{label}: Cancelled</span>")
            return True
        return False

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

    def _reassign_exploded_layer(self, object_names, layer_name):
        doc = App.ActiveDocument
        if not doc or not layer_name:
            return
        layer = doc.getObject(layer_name)
        if not layer:
            return

        changed = False
        for name in object_names or []:
            obj = doc.getObject(name)
            if not obj:
                continue
            if ccad_layers.assign_to_layer(obj, layer):
                changed = True

        if changed:
            try:
                proxy = getattr(getattr(layer, 'ViewObject', None), 'Proxy', None)
                if proxy and hasattr(proxy, 'reassign_props'):
                    proxy.reassign_props()
            except Exception:
                pass

    def _copy_explode_style(self, src_obj, dst_obj, layer=None):
        if not dst_obj:
            return
        try:
            ccad_layers.assign_to_layer(dst_obj, layer)
        except Exception:
            pass

        try:
            src_view = getattr(src_obj, 'ViewObject', None)
            dst_view = getattr(dst_obj, 'ViewObject', None)
            if src_view and dst_view:
                for attr in ('LineColor', 'LineWidth', 'DrawStyle', 'PointColor', 'PointSize', 'DisplayMode'):
                    if hasattr(src_view, attr) and hasattr(dst_view, attr):
                        setattr(dst_view, attr, getattr(src_view, attr))
        except Exception:
            pass

    def _explode(self):
        """Break selected wires into individual Draft lines while preserving their layer."""
        import Draft
        sel = Gui.Selection.getSelection()
        if not sel:
            self.history.append(
                "<span style='color:#ff5555;'>EXPLODE: No objects selected</span>")
            return
        doc = App.ActiveDocument
        count = 0
        created_by_layer = {}
        for obj in sel:
            if not hasattr(obj, 'Shape') or obj.Shape.isNull():
                continue
            edges = obj.Shape.Edges
            if len(edges) < 2:
                continue  # single-edge object, nothing to explode

            layer = ccad_layers.get_object_layer(obj) or ccad_layers.get_active_layer(doc)
            layer_name = getattr(layer, 'Name', None) if layer else None
            new_names = []

            for e in edges:
                verts = e.Vertexes
                if len(verts) >= 2:
                    w = Draft.make_wire(
                        [verts[0].Point, verts[-1].Point],
                        closed=False, face=False)
                    self._copy_explode_style(obj, w, layer)
                    if w and getattr(w, 'Name', None):
                        new_names.append(w.Name)
                    count += 1

            if layer_name and new_names:
                created_by_layer.setdefault(layer_name, []).extend(new_names)

            doc.removeObject(obj.Name)

        doc.recompute()

        for layer_name, names in created_by_layer.items():
            for delay in (0, 150, 500):
                QtCore.QTimer.singleShot(
                    delay,
                    lambda n=list(names), l=layer_name: self._reassign_exploded_layer(n, l)
                )

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

                sel_logic = getattr(Gui, 'ccad_sel_logic', None)
                if sel_logic:
                    try:
                        sel_logic.cancel_box()
                    except Exception:
                        pass

                if self._cancel_active_handler():
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

# === Η ΝΕΑ ΚΛΑΣΗ: Μπαίνει ακριβώς πάνω από τη συνάρτηση setup() ===
class CCADFocusStealer(QtCore.QObject):
    """Κλέβει το focus από το Task Panel πριν προλάβει να καταπιεί το πλήκτρο."""
    def eventFilter(self, obj, event):
        # Πιάνουμε το γεγονός στο στάδιο του ShortcutOverride (πριν το KeyPress)
        if event.type() == QtCore.QEvent.ShortcutOverride:
            key = event.key()
            # Ελέγχουμε αν είναι γράμμα (αλλά αφήνουμε τα X, Y, Z ελεύθερα για τους άξονες)
            if QtCore.Qt.Key_A <= key <= QtCore.Qt.Key_Z and key not in (QtCore.Qt.Key_X, QtCore.Qt.Key_Y, QtCore.Qt.Key_Z):
                spline_active = hasattr(Gui, 'ccad_spline_handler') and Gui.ccad_spline_handler
                xline_active = hasattr(Gui, 'ccad_xline_handler') and Gui.ccad_xline_handler
                trim_active = hasattr(Gui, 'ccad_trim_handler') and Gui.ccad_trim_handler
                fillet_active = hasattr(Gui, 'ccad_fillet_handler') and Gui.ccad_fillet_handler
                
                # Αν τρέχουν τα εργαλεία μας, ρίχνουμε το focus βίαια στην κονσόλα!
                if spline_active or xline_active or trim_active or fillet_active:
                    if hasattr(Gui, "classic_console"):
                        cmd_input = Gui.classic_console.input
                        if QtWidgets.QApplication.focusWidget() != cmd_input:
                            cmd_input.setFocus()
        return False
# ===================================================================

def setup():
    mw = Gui.getMainWindow()
    if not mw:
        return

    # Καθαρισμός παλιάς κονσόλας
    for child in mw.findChildren(QtWidgets.QDockWidget):
        if child.objectName() == "ClassicConsole":
            QtWidgets.QApplication.instance().removeEventFilter(child)
            child.deleteLater()

    # Δημιουργία νέας κονσόλας
    Gui.classic_console = ClassicConsole(mw)
    mw.addDockWidget(QtCore.Qt.BottomDockWidgetArea, Gui.classic_console)
    QtWidgets.QApplication.instance().installEventFilter(Gui.classic_console)

    # Εγκατάσταση του νέου Focus Stealer σε όλο το Application!
    if hasattr(Gui, "ccad_focus_stealer"):
        QtWidgets.QApplication.instance().removeEventFilter(Gui.ccad_focus_stealer)
        Gui.ccad_focus_stealer.deleteLater()
    Gui.ccad_focus_stealer = CCADFocusStealer()
    QtWidgets.QApplication.instance().installEventFilter(Gui.ccad_focus_stealer)

    if hasattr(Gui, "ccad_shortcuts"):
        for s in Gui.ccad_shortcuts:
            s.deleteLater()
    Gui.ccad_shortcuts = []

    def focus_and_type(char):
        fw = QtWidgets.QApplication.focusWidget()
        if hasattr(Gui, "classic_console") and fw == Gui.classic_console.input:
            return

        is_letter = char.isalpha()

        # Εξαίρεση: Αν τρέχουν τα εργαλεία μας
        handler_running = (hasattr(Gui, 'ccad_spline_handler') and Gui.ccad_spline_handler) or \
                          (hasattr(Gui, 'ccad_xline_handler') and Gui.ccad_xline_handler) or \
                          (hasattr(Gui, 'ccad_trim_handler') and Gui.ccad_trim_handler) or \
                          (hasattr(Gui, 'ccad_fillet_handler') and Gui.ccad_fillet_handler)

        if handler_running and is_letter and char.upper() not in ('X', 'Y', 'Z'):
            if hasattr(Gui, "classic_console"):
                Gui.classic_console.input.setFocus()
                Gui.classic_console.input.insert(char)
            return

        # Native FreeCAD fields
        if isinstance(fw, (QtWidgets.QLineEdit, QtWidgets.QDoubleSpinBox, QtWidgets.QSpinBox)):
            return

        if _handler_active():
            return
            
        if hasattr(Gui, "classic_console") and Gui.classic_console._is_non_edit_command():
            return

        if hasattr(Gui, "classic_console"):
            Gui.classic_console.input.setFocus()
            Gui.classic_console.input.insert(char)

    # Δημιουργία Shortcuts
    for char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
        s = QtGui.QShortcut(QtGui.QKeySequence(char), mw)
        s.activated.connect(lambda c=char: focus_and_type(c))
        Gui.ccad_shortcuts.append(s)

    for key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Space):
        s = QtGui.QShortcut(QtGui.QKeySequence(key), mw)
        s.activated.connect(Gui.classic_console.execute)
        Gui.ccad_shortcuts.append(s)

if __name__ == "__main__":
    setup()
