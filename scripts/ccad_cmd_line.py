import FreeCAD as App
import FreeCADGui as Gui
import Draft
from PySide6 import QtCore, QtGui

class AutoCADLine:
    def __init__(self):
        self.points = []
        self.segments = []
        self.callback = None
        self.key_cb = None

    def GetResources(self):
        return {'Pixmap': 'Draft_Line', 'MenuText': 'Line', 'ToolTip': 'L (Continuous + Undo)'}

    def Activated(self):
        self.points = []
        self.segments = []
        # Ενεργοποίηση των callbacks για ποντίκι και πληκτρολόγιο
        self.callback = Gui.activeView().addEventCallback("MouseButton", self.on_click)
        self.key_cb = Gui.activeView().addEventCallback("Keyboard", self.on_key)
        App.Console.PrintLog("LINE: Specify first point:\n")

    def on_click(self, info):
        # Έλεγχος για αριστερό κλικ
        if info["button"] == "Left" and info["type"] == "ButtonPress":
            pos = info["cursor"]
            p = App.Vector(pos[0], pos[1], pos[2])
            
            if not self.points:
                # Πρώτο σημείο της αλυσίδας
                self.points.append(p)
                App.Console.PrintLog("LINE: Specify next point:\n")
            else:
                # Δημιουργία γραμμής από το προηγούμενο σημείο στο νέο
                start_p = self.points[-1]
                line = Draft.make_line(start_p, p)
                self.segments.append(line)
                
                # ΚΡΙΣΙΜΟ: Το σημείο p γίνεται ΑΜΕΣΩΣ το επόμενο σημείο εκκίνησης
                self.points.append(p)
                
                App.ActiveDocument.recompute()
                App.Console.PrintLog(f"LINE: Point specified. Continuous mode active.\n")
            return True

        # Δεξί κλικ = Enter/Ολοκλήρωση
        if info["button"] == "Right":
            Gui.Control.closeDialog()
            return True

    def on_key(self, info):
        # Λειτουργία Undo με το πλήκτρο U
        if info["key"] in ["u", "U"] and self.segments:
            last_line = self.segments.pop()
            self.points.pop() # Αφαιρούμε το τελευταίο σημείο για να γυρίσουμε πίσω
            App.ActiveDocument.removeObject(last_line.Name)
            App.ActiveDocument.recompute()
            App.Console.PrintLog("LINE: Undo segment. Back to previous point.\n")
            return True
        
        # Escape για ακύρωση
        if info["key"] == "Escape":
            Gui.Control.closeDialog()
            return True

    def Deactivated(self):
        if self.callback:
            Gui.activeView().removeEventCallback("MouseButton", self.callback)
        if self.key_cb:
            Gui.activeView().removeEventCallback("Keyboard", self.key_cb)
        self.points = []
        self.segments = []
        App.Console.PrintLog("LINE: Command finished.\n")

def setup():
    Gui.addCommand('L', AutoCADLine())