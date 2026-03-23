import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore, QtGui

class EnvironmentManager:
    @staticmethod
    def sync_color_with_active_layer():
        """Απόλυτος συγχρονισμός χρώματος με το Active Layer μέσω παραμέτρων συστήματος"""
        try:
            import Draft
            active_layer = Draft.get_active_layer()
            if not active_layer or not hasattr(active_layer, "ViewObject"):
                return

            # Λήψη χρώματος από το Layer
            l_color = active_layer.ViewObject.LineColor 
            
            # Μετατροπή σε 32-bit Integer (RGBA) για το FreeCAD
            r = int(l_color[0] * 255)
            g = int(l_color[1] * 255)
            b = int(l_color[2] * 255)
            # Alpha 255 για να μην είναι "αχνό"
            ui_color = (r << 24) | (g << 16) | (b << 8) | 255

            # 1. Ενημέρωση των Preferences που διαβάζει το Coin3D για το Rubberband
            view_p = App.ParamGet("User parameter:BaseApp/Preferences/View")
            view_p.SetUnsigned("RubberBandColor", ui_color)
            
            # 2. Ενημέρωση των Preferences του Draft
            draft_p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
            draft_p.SetUnsigned("DefaultLineColor", ui_color)
            draft_p.SetUnsigned("SnapGuiColor", ui_color)
            
            # 3. Ενημέρωση του Sniffer αν είναι ήδη ενεργό
            import DraftGui
            if hasattr(DraftGui, "sniffer") and DraftGui.sniffer:
                DraftGui.sniffer.set_color(l_color)
                    
        except:
            pass

class LayerColorObserver(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(EnvironmentManager.sync_color_with_active_layer)
        self.timer.start(500)

def setup():
    # Διόρθωση του NameError: Ορίζουμε την κλάση πριν τη χρησιμοποιήσουμε
    if hasattr(Gui, "ccad_env_observer"):
        try:
            Gui.ccad_env_observer.timer.stop()
            Gui.ccad_env_observer.deleteLater()
        except: pass

    Gui.ccad_env_observer = LayerColorObserver()
    
    # Επιβολή αλλαγής χρώματος τώρα
    EnvironmentManager.sync_color_with_active_layer()
    App.Console.PrintLog("ClassicCAD Environment: Visual Sync Fixed.\n")