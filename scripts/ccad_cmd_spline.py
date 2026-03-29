"""SPLINE command — AutoCAD-style spline tool with CV/Fit sub-options."""

import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore

class SplineHandler(QtCore.QObject):
    def __init__(self, console, mode='FIT'):
        super().__init__()
        self.console = console
        self.mode = mode
        
        # Εκκίνηση της σωστής εντολής του FreeCAD
        self._start_cmd()
        
        # Timer που ελέγχει πότε ο χρήστης τελειώνει το σχέδιο ή πατάει ESC
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.check_active)
        self.timer.start(500)

    def _start_cmd(self):
        # Κλείσιμο τυχόν ενεργού Draft εργαλείου για καθαρή εναλλαγή
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            
        if self.mode == 'FIT':
            self.console.history.append(
                "<span style='color:#aaa;'>SPLINE: Specify first point or [<span style='color:#6af;'>CV</span>]:</span>"
            )
            Gui.runCommand("Draft_BSpline")
        else:
            self.console.history.append(
                "<span style='color:#aaa;'>SPLINE: Specify first point or [<span style='color:#6af;'>F</span>it]:</span>"
            )
            Gui.runCommand("Draft_BezCurve")

    def _on_input(self):
        """Επιστρέφει True αν διαχειρίστηκε την είσοδο, False για να την αφήσει στην κονσόλα."""
        text = self.console.input.text().strip().upper()
        
        if self.mode == 'FIT' and text == 'CV':
            self.mode = 'CV'
            self.console.input.clear()
            self._start_cmd()
            return True
            
        elif self.mode == 'CV' and text in ('F', 'FIT'):
            self.mode = 'FIT'
            self.console.input.clear()
            self._start_cmd()
            return True
            
        return False

    def check_active(self):
        # Αν η εντολή σχεδίασης έκλεισε (ολοκλήρωση γραμμής ή ESC)
        cmd = getattr(App, 'activeDraftCommand', None)
        if not cmd:
            self.cleanup()

    def cleanup(self):
        self.timer.stop()
        if getattr(Gui, 'ccad_spline_handler', None) == self:
            Gui.ccad_spline_handler = None
        self.deleteLater()


def run(console):
    """Εκκινεί τον Spline Handler."""
    # Αν τρέχει ήδη προηγούμενος handler, τον κλείνουμε
    if hasattr(Gui, 'ccad_spline_handler') and Gui.ccad_spline_handler:
        Gui.ccad_spline_handler.cleanup()
        
    Gui.ccad_spline_handler = SplineHandler(console, mode='FIT')
    console.input.clear()