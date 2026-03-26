"""ClassicCAD Status Bar — Draggable toolbar with ORTHO / OSNAP toggles.

Standard QToolBar using QActions so the buttons look and behave like the
built-in FreeCAD snap toolbar — checkable icon-style buttons that can be
dragged to any toolbar area.
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtWidgets, QtCore, QtGui


class ClassicStatusBar(QtWidgets.QToolBar):
    def __init__(self, parent_mw):
        super().__init__("ClassicCAD Drawing Aids", parent_mw)
        self.setObjectName("ClassicCADStatusBar")
        self.setMovable(True)
        self.setFloatable(True)
        self.setIconSize(QtCore.QSize(24, 24))

        # ── ORTHO action ──
        self.ortho_act = QtGui.QAction("ORTHO", self)
        self.ortho_act.setCheckable(True)
        self.ortho_act.setToolTip("Toggle Ortho mode (F8)")
        self.ortho_act.setIcon(self._text_icon("O", False))
        self.ortho_act.toggled.connect(self._on_ortho)
        self.addAction(self.ortho_act)

        # ── OSNAP action (hidden — kept for sync_osnap API) ──
        self.osnap_act = QtGui.QAction("OSNAP", self)
        self.osnap_act.setCheckable(True)
        self.osnap_act.setToolTip("Toggle Object Snap (F3)")
        self.osnap_act.setIcon(self._text_icon("S", False))
        self.osnap_act.setChecked(self._get_osnap_state())
        self._update_icon(self.osnap_act)
        self.osnap_act.toggled.connect(self._on_osnap)
        # Not added to toolbar — hidden per user request

        parent_mw.addToolBar(QtCore.Qt.TopToolBarArea, self)

    # ── icon helper ──

    @staticmethod
    def _text_icon(letter, on):
        """Create a small icon with a letter, coloured by state."""
        px = QtGui.QPixmap(24, 24)
        px.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(px)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        if on:
            p.setBrush(QtGui.QColor("#005f87"))
            p.setPen(QtGui.QPen(QtGui.QColor("#0af"), 1.5))
        else:
            p.setBrush(QtGui.QColor("#2a2a2a"))
            p.setPen(QtGui.QPen(QtGui.QColor("#555"), 1))
        p.drawRoundedRect(1, 1, 22, 22, 4, 4)
        font = QtGui.QFont("Consolas", 13, QtGui.QFont.Bold)
        p.setFont(font)
        p.setPen(QtGui.QColor("#fff") if on else QtGui.QColor("#666"))
        p.drawText(QtCore.QRect(0, 0, 24, 24), QtCore.Qt.AlignCenter, letter)
        p.end()
        return QtGui.QIcon(px)

    def _update_icon(self, action):
        letter = "O" if action is self.ortho_act else "S"
        action.setIcon(self._text_icon(letter, action.isChecked()))

    # ── ORTHO ──

    def _on_ortho(self, checked):
        self._update_icon(self.ortho_act)
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
        if self.ortho_act.isChecked() != on:
            self.ortho_act.blockSignals(True)
            self.ortho_act.setChecked(on)
            self.ortho_act.blockSignals(False)
        self._update_icon(self.ortho_act)

    # ── OSNAP ──

    def _on_osnap(self, checked):
        self._update_icon(self.osnap_act)
        dt = getattr(Gui, 'ccad_draft_tools', None)
        if dt:
            # Only toggle if state differs
            if self._get_osnap_state() != checked:
                dt.toggle_osnap()
        else:
            Gui.runCommand('Draft_Snap_Lock', 0)

    def sync_osnap(self):
        on = self._get_osnap_state()
        if self.osnap_act.isChecked() != on:
            self.osnap_act.blockSignals(True)
            self.osnap_act.setChecked(on)
            self.osnap_act.blockSignals(False)
        self._update_icon(self.osnap_act)

    @staticmethod
    def _get_osnap_state():
        try:
            p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
            return p.GetBool("Snap")
        except Exception:
            return False


def setup():
    mw = Gui.getMainWindow()
    if not mw:
        return
    # Cleanup old instance
    if hasattr(Gui, 'ccad_status_bar'):
        try:
            mw.removeToolBar(Gui.ccad_status_bar)
            Gui.ccad_status_bar.deleteLater()
        except Exception:
            pass
    Gui.ccad_status_bar = ClassicStatusBar(mw)
