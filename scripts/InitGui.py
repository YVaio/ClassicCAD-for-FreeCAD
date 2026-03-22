import FreeCAD as App
import FreeCADGui as Gui
import os, sys

class ClassicCADGlobal:
    def __init__(self):
        # Κάνουμε το import εδώ τοπικά για την αρχικοποίηση
        from PySide6 import QtCore
        QtCore.QTimer.singleShot(3000, self.inject_system)

    def inject_system(self):
        try:
            import ccad_console
            import ccad_cursor
            import ccad_selection
            import ccad_draft_tools
            import ccad_layers
            import ccad_snaps
            import ccad_cmd_line # Το σωστό όνομα αρχείου
            
            # Εκτέλεση setup
            ccad_console.setup()
            ccad_cursor.setup()
            ccad_selection.setup()
            ccad_draft_tools.setup()
            ccad_layers.setup()
            ccad_snaps.setup()
            ccad_cmd_line.setup()
            
            App.Console.PrintLog("ClassicCAD Global: System Attached Successfully.\n")
        except Exception as e:
            App.Console.PrintError(f"ClassicCAD Global Error: {str(e)}\n")

# Έλεγχος και δημιουργία του instance
if not hasattr(Gui, "ccad_global_active"):
    Gui.ccad_global_active = ClassicCADGlobal()

# --- ΔΙΟΡΘΩΣΗ ΓΙΑ ΤΟ ΣΦΑΛΜΑ ΣΤΟ ΤΕΛΟΣ ---
# Αντί για QtCore.QTimer, καλούμε απευθείας από τη βιβλιοθήκη
from PySide6 import QtCore
# Αν για κάποιο λόγο θέλεις να τρέξεις κάτι εδώ, χρησιμοποίησε το QtCore.