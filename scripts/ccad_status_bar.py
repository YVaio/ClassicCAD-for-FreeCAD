"""ClassicCAD Status Bar — ORTHO toggle next to Snap Lock in the status bar.

Finds the Draft Snap toolbar and inserts an ORTHO button right after
the Snap Lock action, styled to match the existing toolbar icons.
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtWidgets, QtCore, QtGui


class ClassicStatusBar(QtCore.QObject):
    """Manages ClassicCAD additions to the Draft snap toolbar."""

    def __init__(self, parent_mw):
        super().__init__(parent_mw)
        self.mw = parent_mw
        self.ortho_btn = None
        self.tangent_btn = None
        self._retries = 0
        self._try_insert()

    def _find_target_toolbar(self):
        toolbars = self.mw.findChildren(QtWidgets.QToolBar, 'draft_snap_widget')
        if not toolbars:
            return None

        status_bar = self.mw.statusBar()
        expected_names = {
            'Draft_Snap_Lock',
            'Draft_Snap_Endpoint',
            'Draft_Snap_Midpoint',
            'Draft_Snap_Center',
            'Draft_Snap_Angle',
            'Draft_Snap_Intersection',
            'Draft_Snap_Perpendicular',
            'Draft_Snap_Extension',
            'Draft_Snap_Parallel',
            'Draft_Snap_Special',
            'Draft_Snap_Near',
            'Draft_Snap_Ortho',
            'Draft_ToggleGrid',
        }

        def score(toolbar):
            try:
                action_names = {act.objectName() for act in toolbar.actions() if act is not None}
            except Exception:
                action_names = set()

            total = len(action_names)
            total += 10 * len(expected_names.intersection(action_names))
            try:
                if toolbar.isVisible():
                    total += 50
            except Exception:
                pass
            try:
                if status_bar and (toolbar is status_bar or status_bar.isAncestorOf(toolbar)):
                    total += 100
            except Exception:
                pass
            try:
                if status_bar and toolbar.isVisible():
                    toolbar_center = toolbar.mapToGlobal(toolbar.rect().center())
                    status_center = status_bar.mapToGlobal(status_bar.rect().center())
                    total -= min(200, abs(toolbar_center.y() - status_center.y()))
            except Exception:
                pass
            return total

        return max(toolbars, key=score)

    def _remove_duplicate_action(self, object_name, keep_action, target_tb):
        for toolbar in self.mw.findChildren(QtWidgets.QToolBar):
            for action in list(toolbar.actions()):
                try:
                    same_named = bool(object_name and action.objectName() == object_name)
                except Exception:
                    same_named = False
                same_action = action is keep_action
                if same_named or same_action:
                    if action is keep_action and toolbar is target_tb:
                        continue
                    try:
                        toolbar.removeAction(action)
                    except Exception:
                        pass

    def _remove_duplicate_tangent_menu_entries(self):
        for menu in self.mw.findChildren(QtWidgets.QMenu):
            for action in list(menu.actions()):
                try:
                    is_tangent = action.objectName() == 'CCAD_Snap_Tangent_MenuAction'
                except Exception:
                    is_tangent = False
                if not is_tangent:
                    continue
                try:
                    menu.removeAction(action)
                except Exception:
                    pass

    def _try_insert(self):
        """Insert ORTHO into the draft_snap_widget toolbar (lives inside the status bar)."""
        target_tb = self._find_target_toolbar()
        grid_act = None
        dimensions_act = None
        if target_tb:
            for act in target_tb.actions():
                if act.objectName() == 'Draft_ToggleGrid':
                    grid_act = act
                elif act.objectName() == 'Draft_Snap_Dimensions':
                    dimensions_act = act

        if target_tb:
            if self.ortho_btn is None:
                sz = target_tb.iconSize()
                self.ortho_btn = QtGui.QAction(self.mw)
                self.ortho_btn.setObjectName('CCAD_Snap_Ortho')
                self.ortho_btn.setCheckable(True)
                import ccad_draft_tools
                saved = ccad_draft_tools.ClassicDraftTools._ortho_enabled
                self.ortho_btn.setChecked(saved)
                self.ortho_btn.setToolTip("Toggle Ortho mode (F8)")
                self.ortho_btn.setIcon(self._make_icon(saved, sz.width()))
                self.ortho_btn.toggled.connect(self._on_ortho)
                self._icon_sz = sz.width()

            if self.tangent_btn is None:
                import ccad_draft_tools
                tangent_on = ccad_draft_tools.ClassicDraftTools._tangent_enabled
                self.tangent_btn = QtGui.QAction(self.mw)
                self.tangent_btn.setObjectName('CCAD_Snap_Tangent')
                self.tangent_btn.setCheckable(True)
                self.tangent_btn.setChecked(tangent_on)
                self.tangent_btn.setText("Tangent")
                self.tangent_btn.setToolTip("Toggle Tangent snap")
                self.tangent_btn.setIcon(self._make_tangent_icon(tangent_on, getattr(self, '_icon_sz', 16)))
                self.tangent_btn.toggled.connect(self._on_tangent)

            self._remove_duplicate_tangent_menu_entries()
            self._remove_duplicate_action('CCAD_Snap_Ortho', self.ortho_btn, target_tb)
            self._remove_duplicate_action('CCAD_Snap_Tangent', self.tangent_btn, target_tb)

            # Insert ORTHO right after the grid button.
            actions = target_tb.actions()
            if self.ortho_btn not in actions:
                after = None
                for i, a in enumerate(actions):
                    if a is grid_act and i + 1 < len(actions):
                        after = actions[i + 1]
                        break
                if after:
                    target_tb.insertAction(after, self.ortho_btn)
                else:
                    target_tb.addAction(self.ortho_btn)

            actions = target_tb.actions()
            if self.tangent_btn not in actions:
                if dimensions_act is not None:
                    target_tb.insertAction(dimensions_act, self.tangent_btn)
                else:
                    target_tb.addAction(self.tangent_btn)

            tool = getattr(Gui, 'ccad_draft_tools', None)
            if tool and hasattr(tool, 'rebind_osnap_lock_actions'):
                tool.rebind_osnap_lock_actions()

            self._sync_tangent_button_state()
            return

        # Not found yet — retry
        self._retries += 1
        if self._retries < 20:
            QtCore.QTimer.singleShot(500, self._try_insert)

    @staticmethod
    def _make_icon(on, size=24):
        """Create a frameless L-shape icon matching the snap bar line style."""
        px = QtGui.QPixmap(size, size)
        px.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(px)
        p.setRenderHint(QtGui.QPainter.Antialiasing)

        # Simple L-shape lines, no background
        s = size
        lw = max(2.0, s / 10)
        color = QtGui.QColor(0, 200, 255) if on else QtGui.QColor(160, 160, 160)
        pen = QtGui.QPen(color, lw, QtCore.Qt.SolidLine,
                         QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
        p.setPen(pen)
        x1 = int(s * 0.28)
        y1 = int(s * 0.15)
        y2 = int(s * 0.80)
        x2 = int(s * 0.80)
        p.drawLine(x1, y1, x1, y2)
        p.drawLine(x1, y2, x2, y2)

        p.end()
        return QtGui.QIcon(px)

    @staticmethod
    def _make_tangent_icon(on, size=24):
        px = QtGui.QPixmap(size, size)
        px.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(px)
        p.setRenderHint(QtGui.QPainter.Antialiasing)

        s = float(size)
        lw = max(2.0, s / 12.0)
        color = QtGui.QColor(0, 200, 255) if on else QtGui.QColor(160, 160, 160)
        pen = QtGui.QPen(color, lw, QtCore.Qt.SolidLine,
                         QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)

        rect = QtCore.QRectF(s * 0.28, s * 0.34, s * 0.34, s * 0.34)
        p.drawEllipse(rect)
        line_y = rect.top()
        p.drawLine(QtCore.QPointF(rect.left() - s * 0.12, line_y), QtCore.QPointF(rect.right() + s * 0.12, line_y))

        p.end()
        return QtGui.QIcon(px)

    def _icon_size(self):
        return getattr(self, '_icon_sz', 24)

    def _osnap_is_enabled(self):
        try:
            snapper = getattr(Gui, 'Snapper', None)
            if snapper and hasattr(snapper, 'isEnabled'):
                return bool(snapper.isEnabled('Lock'))
        except Exception:
            pass

        try:
            import ccad_draft_tools
            return bool(ccad_draft_tools.ClassicDraftTools._osnap_enabled)
        except Exception:
            return True

    def _sync_tangent_button_state(self):
        if not self.tangent_btn:
            return

        import ccad_draft_tools
        tangent_on = bool(ccad_draft_tools.ClassicDraftTools._tangent_enabled)
        osnap_on = self._osnap_is_enabled()

        if self.tangent_btn.isChecked() != tangent_on:
            self.tangent_btn.blockSignals(True)
            self.tangent_btn.setChecked(tangent_on)
            self.tangent_btn.blockSignals(False)

        self.tangent_btn.setEnabled(osnap_on)
        self.tangent_btn.setIcon(self._make_tangent_icon(tangent_on and osnap_on, self._icon_size()))

    # ── ORTHO ──

    def _on_ortho(self, checked):
        self.ortho_btn.setIcon(self._make_icon(checked, self._icon_size()))
        dt = getattr(Gui, 'ccad_draft_tools', None)
        if dt:
            import ccad_draft_tools
            if ccad_draft_tools.ClassicDraftTools._ortho_enabled != checked:
                dt.toggle_ortho()
        else:
            import ccad_draft_tools
            ccad_draft_tools.ClassicDraftTools._ortho_enabled = checked

    def sync_ortho(self):
        import ccad_draft_tools
        on = ccad_draft_tools.ClassicDraftTools._ortho_enabled
        if self.ortho_btn.isChecked() != on:
            self.ortho_btn.blockSignals(True)
            self.ortho_btn.setChecked(on)
            self.ortho_btn.blockSignals(False)
        self.ortho_btn.setIcon(self._make_icon(on, self._icon_size()))

    # ── TANGENT ──

    def _on_tangent(self, checked):
        import ccad_draft_tools
        ccad_draft_tools.ClassicDraftTools._tangent_enabled = bool(checked)
        App.ParamGet("User parameter:BaseApp/Preferences/Mod/ClassicCAD").SetBool("TangentEnabled", bool(checked))
        self._sync_tangent_button_state()

    def sync_tangent(self):
        self._sync_tangent_button_state()

    # ── OSNAP (API kept for sync calls) ──

    def sync_osnap(self):
        self._sync_tangent_button_state()


def setup():
    mw = Gui.getMainWindow()
    if not mw:
        return
    # Cleanup old instance
    if hasattr(Gui, 'ccad_status_bar'):
        try:
            old = Gui.ccad_status_bar
            for action_name in ('ortho_btn', 'tangent_btn'):
                action = getattr(old, action_name, None)
                if action:
                    for menu in mw.findChildren(QtWidgets.QMenu):
                        if action in menu.actions():
                            menu.removeAction(action)
                    for tb in mw.findChildren(QtWidgets.QToolBar):
                        if action in tb.actions():
                            tb.removeAction(action)
            for menu in mw.findChildren(QtWidgets.QMenu):
                for action in list(menu.actions()):
                    if action.objectName() == 'CCAD_Snap_Tangent_MenuAction':
                        menu.removeAction(action)
            old.deleteLater()
        except Exception:
            pass
    Gui.ccad_status_bar = ClassicStatusBar(mw)
