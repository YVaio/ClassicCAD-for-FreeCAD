import FreeCAD as App
import FreeCADGui as Gui
import Draft
from PySide6 import QtCore, QtGui, QtWidgets

class AutoCADLine:
    def __init__(self):
        self.points = []
        self.segments = []
        self.callback = None
        self.key_cb = None
        # Προσθήκη τυπικού widget για το TaskPanel για αποφυγή RuntimeError
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("LINE")

    def GetResources(self):
        return {'Pixmap': 'Draft_Line', 'MenuText': 'Line', 'ToolTip': 'L (Continuous + Undo)'}

    def Activated(self):
        self.points = []
        self.segments = []
        self.callback = Gui.activeView().addEventCallback("MouseButton", self.on_click)
        self.key_cb = Gui.activeView().addEventCallback("Keyboard", self.on_key)
        App.Console.PrintLog("LINE: Specify first point:\n")

    def on_click(self, info):
        if info["button"] == "Left" and info["type"] == "ButtonPress":
            pos = info["cursor"]
            p = App.Vector(pos[0], pos[1], pos[2])
            
            if not self.points:
                self.points.append(p)
                App.Console.PrintLog("LINE: Specify next point:\n")
            else:
                start_p = self.points[-1]
                # Δημιουργία γραμμής μέσω Draft για να είναι συμβατό με το σύστημα
                line = Draft.make_line(start_p, p)
                self.segments.append(line)
                self.points.append(p)
                
                App.ActiveDocument.recompute()
                App.Console.PrintLog(f"LINE: Point specified.\n")
            return True

        if info["button"] == "Right":
            Gui.Control.closeDialog()
            return True

    def on_key(self, info):
        if info["key"] in ["u", "U"] and self.segments:
            last_line = self.segments.pop()
            self.points.pop() 
            App.ActiveDocument.removeObject(last_line.Name)
            App.ActiveDocument.recompute()
            return True
        
        if info["key"] == "Escape":
            Gui.Control.closeDialog()
            return True

    def isAllowedAlterDocument(self):
        return True

    def isAllowedAlterView(self):
        return True

    def Deactivated(self):
        if self.callback:
            Gui.activeView().removeEventCallback("MouseButton", self.callback)
        if self.key_cb:
            Gui.activeView().removeEventCallback("Keyboard", self.key_cb)
        self.points = []
        self.segments = []
        App.Console.PrintLog("LINE: Command finished.\n")

    # Απαραίτητες μέθοδοι για να μην χτυπάει το DraftToolBar
    def accept(self):
        Gui.Control.closeDialog()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True