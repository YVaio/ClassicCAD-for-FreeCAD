"""ClassicCAD Status Bar — ORTHO toggle next to Snap Lock in the status bar.

Finds the Draft Snap toolbar and inserts an ORTHO button right after
the Snap Lock action, styled to match the existing toolbar icons.
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtWidgets, QtCore, QtGui


class ClassicStatusBar(QtCore.QObject):
    """Manages the ORTHO button next to the Snap Lock button."""

    def __init__(self, parent_mw):
        super().__init__(parent_mw)
        self.mw = parent_mw
        self.ortho_btn = None
        self._retries = 0
        self._try_insert()

    def _try_insert(self):
        """Insert ORTHO into the draft_snap_widget toolbar (lives inside the status bar)."""
        target_tb = self.mw.findChild(QtWidgets.QToolBar, 'draft_snap_widget')
        grid_act = None
        if target_tb:
            for act in target_tb.actions():
                if act.objectName() == 'Draft_ToggleGrid':
                    grid_act = act
                    break

        if target_tb:
            if self.ortho_btn is None:
                sz = target_tb.iconSize()
                self.ortho_btn = QtGui.QAction(self.mw)
                self.ortho_btn.setCheckable(True)
                import ccad_draft_tools
                saved = ccad_draft_tools.ClassicDraftTools._ortho_enabled
                self.ortho_btn.setChecked(saved)
                self.ortho_btn.setToolTip("Toggle Ortho mode (F8)")
                self.ortho_btn.setIcon(self._make_icon(saved, sz.width()))
                self.ortho_btn.toggled.connect(self._on_ortho)
                self._icon_sz = sz.width()

            # Insert right after the grid button (first action found)
            actions = target_tb.actions()
            if self.ortho_btn not in actions:
                # Find the action after grid_act
                after = None
                for i, a in enumerate(actions):
                    if a is grid_act and i + 1 < len(actions):
                        after = actions[i + 1]
                        break
                if after:
                    target_tb.insertAction(after, self.ortho_btn)
                else:
                    target_tb.addAction(self.ortho_btn)
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

    def _icon_size(self):
        return getattr(self, '_icon_sz', 24)

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

    # ── OSNAP (API kept for sync calls) ──

    def sync_osnap(self):
        pass


def setup():
    mw = Gui.getMainWindow()
    if not mw:
        return
    # Cleanup old instance
    if hasattr(Gui, 'ccad_status_bar'):
        try:
            old = Gui.ccad_status_bar
            if hasattr(old, 'ortho_btn') and old.ortho_btn:
                # Remove the action from any toolbar it was inserted into
                for tb in mw.findChildren(QtWidgets.QToolBar):
                    if old.ortho_btn in tb.actions():
                        tb.removeAction(old.ortho_btn)
                        break
            old.deleteLater()
        except Exception:
            pass
    Gui.ccad_status_bar = ClassicStatusBar(mw)
