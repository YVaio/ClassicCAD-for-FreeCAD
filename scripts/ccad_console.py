import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtWidgets, QtCore, QtGui
import ccad_layers 

class ClassicConsole(QtWidgets.QDockWidget):
    def __init__(self, parent_mw):
        super().__init__(parent_mw)
        self.setObjectName("ClassicConsole")
        self.setWindowTitle("COMMAND LINE")
        self.setTitleBarWidget(QtWidgets.QWidget()) 
        
        # 1. ΠΡΟΤΕΡΑΙΟΤΗΤΕΣ (Aliases)
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
            'LO': 'LAYOFF',
            'LN': 'LAYON',
            'RR': 'RELOAD',
        }

        # 2. ΠΛΗΡΕΙΣ ΕΝΤΟΛΕΣ
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
            'TRIM': 'Draft_Trim',
            'EXTEND': 'Draft_Stretch',
            'OFFSET': 'Draft_Offset',
            'FILLET': 'Draft_Fillet',
            'ARRAY': 'Draft_Array',
            'ERASE': 'Std_Delete',
            'EXPLODE': 'Draft_Explode',
            'JOIN': 'Draft_Join',
            'HATCH': 'Draft_Hatch',
            'LAYOFF': 'LAYOFF',
            'LAYON': 'LAYON',
            'RELOAD': lambda: App.RR(),
        }
        
        self.last_command = None 
        
        self.main_widget = QtWidgets.QWidget()
        self.layout = QtWidgets.QVBoxLayout(self.main_widget)
        self.layout.setContentsMargins(2,2,2,2); self.layout.setSpacing(0)
        
        self.history = QtWidgets.QTextEdit(); self.history.setReadOnly(True)
        self.history.setStyleSheet("background:#0c0c0c; color:#aaa; font-family:'Consolas'; border:none; font-size:11px;")
        
        self.input = QtWidgets.QLineEdit()
        self.input.setStyleSheet("background:#1e1e1e; color:#fff; border:1px solid #333; font-family:'Consolas'; padding:4px; font-size:12px;")
        
        # 3. Δημιουργία Λίστας Search
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

    def execute_draft_command(self, command_name):
        try:
            Gui.activateWorkbench("DraftWorkbench")
            Gui.runCommand(command_name)
        except Exception as e:
            self.history.append(f"<span style='color:red;'>Error: {str(e)}</span>")

    def check_space(self, text):
        if text.endswith(" "):
            self.execute()

    def execute(self, force_repeat=False):
        raw_text = self.input.text().strip().upper()
        
        # --- NEA ΛΟΓΙΚΗ AUTO-COMPLETE ---
        if not raw_text:
            if force_repeat and self.last_command:
                raw_text = self.last_command
            else: return
        else:
            # Αν αυτό που έγραψε ο χρήστης ΔΕΝ είναι ακριβώς εντολή ή alias, 
            # τράβα την πρώτη πρόταση από τον completer
            if raw_text not in self.shortcuts and raw_text not in self.commands:
                # Επιβάλλουμε στον completer να βρει την τρέχουσα πρόταση για το κείμενο
                self.completer.setCompletionPrefix(raw_text)
                if self.completer.completionCount() > 0:
                    raw_text = self.completer.currentCompletion().upper()

        # Καθαρισμός από παρενθέσεις π.χ. "L (LINE)" -> "L"
        clean_input = raw_text.split(' ')[0]

        # Μετατροπή Alias σε Full Command Name
        cmd_name = self.shortcuts.get(clean_input, clean_input)
        
        # Μετατροπή Full Name σε FreeCAD Command
        freecad_cmd = self.commands.get(cmd_name)

        if freecad_cmd:
            self.history.append(f"<span style='color:#55ff55;'>&gt; {cmd_name}</span>")
            self.last_command = clean_input
            self.input.clear()
            
            try:
                if freecad_cmd in ['LAYOFF', 'LAYON']:
                    if freecad_cmd == 'LAYOFF': ccad_layers.LAYOFF()
                    else: ccad_layers.LAYON()
                else:
                    Gui.getMainWindow().setFocus()
                    Gui.runCommand(freecad_cmd)
            except:
                self.history.append("<span style='color:red;'>Command execution failed</span>")
        else:
            if clean_input:
                self.history.append(f"<span style='color:#ff5555;'>Unknown command: {clean_input}</span>")
            self.input.clear()
        
        self.history.moveCursor(QtGui.QTextCursor.End)

    def is_draft_active(self):
        try:
            active_dlg = Gui.Control.activeDialog()
            return active_dlg is not None and active_dlg is not False
        except: return False

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.KeyPress:
            fw = QtWidgets.QApplication.focusWidget()
            is_input = isinstance(fw, (QtWidgets.QLineEdit, QtWidgets.QDoubleSpinBox, QtWidgets.QSpinBox))
            
            if event.key() == QtCore.Qt.Key_Escape:
                if self.input.hasFocus() and self.input.text():
                    self.input.clear()
                    return True

            if event.key() in [QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Space]:
                if is_input and fw != self.input:
                    return False 
                
                if fw == self.input: 
                    return False
                
                if self.is_draft_active():
                    enter_evt = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Return, QtCore.Qt.NoModifier)
                    QtWidgets.QApplication.postEvent(QtWidgets.QApplication.focusWidget(), enter_evt)
                    return True
                
                self.execute(force_repeat=True)
                return True
        return False

def setup():
    mw = Gui.getMainWindow()
    if not mw: return
    
    for child in mw.findChildren(QtWidgets.QDockWidget):
        if child.objectName() == "ClassicConsole": 
            QtWidgets.QApplication.instance().removeEventFilter(child)
            child.deleteLater()
            
    Gui.classic_console = ClassicConsole(mw)
    mw.addDockWidget(QtCore.Qt.BottomDockWidgetArea, Gui.classic_console)
    
    QtWidgets.QApplication.instance().installEventFilter(Gui.classic_console)
    
    if hasattr(Gui, "ccad_shortcuts"):
        for s in Gui.ccad_shortcuts: s.deleteLater()
    Gui.ccad_shortcuts = []
    
    def focus_and_type(char):
        fw = QtWidgets.QApplication.focusWidget()
        if isinstance(fw, (QtWidgets.QLineEdit, QtWidgets.QDoubleSpinBox, QtWidgets.QSpinBox)):
            return

        if hasattr(Gui, "classic_console") and not Gui.classic_console.is_draft_active():
            if not Gui.Control.activeDialog():
                Gui.classic_console.input.setFocus()
                Gui.classic_console.input.insert(char)

    for char in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
        s = QtGui.QShortcut(QtGui.QKeySequence(char), mw)
        s.activated.connect(lambda c=char: focus_and_type(c))
        Gui.ccad_shortcuts.append(s)

if __name__ == "__main__":
    setup()