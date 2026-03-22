import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore, QtGui, QtWidgets

class ClassicDraftTools(QtCore.QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ortho_enabled = False
        self.mw = Gui.getMainWindow()
        
        # Shortcuts
        self.f3 = QtGui.QShortcut(QtGui.QKeySequence("F3"), self.mw)
        self.f3.setContext(QtCore.Qt.ApplicationShortcut)
        self.f3.activated.connect(self.toggle_osnap)
        
        self.f8 = QtGui.QShortcut(QtGui.QKeySequence("F8"), self.mw)
        self.f8.setContext(QtCore.Qt.ApplicationShortcut)
        self.f8.activated.connect(self.toggle_ortho)

        # Timer για το Ortho (Επιβολή κάθε 20ms)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.enforce_ortho)
        self.timer.start(20)

    def print_msg(self, text):
        if hasattr(Gui, "classic_console") and hasattr(Gui.classic_console, "history"):
            try:
                clean = text.replace("<", "&lt;").replace(">", "&gt;")
                msg = f"<span style='color:#aaaaaa; font-family:Consolas;'>{clean}</span>"
                Gui.classic_console.history.append(msg)
            except: pass

    def toggle_osnap(self):
        try:
            # Τρέχει την εντολή snap lock
            Gui.runCommand('Draft_Snap_Lock', 0)
            Gui.updateGui()
            
            # Διάβασμα κατάστασης
            p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
            # Στο 1.1 το 'Snap' είναι True όταν οι έλξεις είναι ΟΝ
            state = "ON" if p.GetBool("Snap") else "OFF"
            self.print_msg(f"< OSNAP {state} >")
        except:
            self.print_msg("< OSNAP TOGGLED >")

    def toggle_ortho(self):
        self.ortho_enabled = not self.ortho_enabled
        state = "ON" if self.ortho_enabled else "OFF"
        self.print_msg(f"< ORTHO {state} >")

    def enforce_ortho(self):
        if not self.ortho_enabled: return
        try:
            import DraftGui
            if hasattr(DraftGui, "sniffer") and DraftGui.sniffer and DraftGui.sniffer.active():
                # Επιβολή Ortho (αντίστοιχο του Shift)
                DraftGui.sniffer.constrain = True
        except: pass

def setup():
    """Απαραίτητη συνάρτηση για το ClassicCAD loader"""
    mw = Gui.getMainWindow()
    if not mw: return
    
    # Καθαρισμός παλιών
    if hasattr(Gui, "ccad_draft_tools"):
        try:
            Gui.ccad_draft_tools.timer.stop()
            Gui.ccad_draft_tools.f3.deleteLater()
            Gui.ccad_draft_tools.f8.deleteLater()
            Gui.ccad_draft_tools.deleteLater()
        except: pass
        del Gui.ccad_draft_tools

    Gui.ccad_draft_tools = ClassicDraftTools(mw)

if __name__ == "__main__":
    setup()