import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore, QtGui, QtWidgets

def setup():
    # Περιμένουμε 5 δευτερόλεπτα για να έχει φορτώσει πλήρως το Draft
    QtCore.QTimer.singleShot(5000, apply_autocad_hard_patch)

def apply_autocad_hard_patch():
    try:
        import DraftGui
        if not hasattr(DraftGui, "sniffer"):
            return

        # Ρύθμιση παραμέτρων για το χρώμα
        param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
        param.SetUnsigned("SnapGuiColor", 65280) # Pure Green
        param.SetInt("SnapSize", 12)
        param.SetInt("SnapStyle", 0) # Classic

        # ΟΡΙΣΜΟΣ ΤΩΝ ΣΧΗΜΑΤΩΝ (Drawing Logic)
        def draw_autocad_snap(symbol, color, size, painter):
            painter.setPen(QtGui.QPen(QtGui.QColor(0, 255, 0), 2)) # Πράσινο πενάκι
            painter.setBrush(QtCore.Qt.NoBrush)
            
            s = size / 2
            if symbol == "Endpoint":
                # Τετράγωνο
                painter.drawRect(QtCore.QRectF(-s, -s, size, size))
            elif symbol == "Midpoint":
                # Τρίγωνο
                path = QtGui.QPainterPath()
                path.moveTo(0, -s)
                path.lineTo(s, s)
                path.lineTo(-s, s)
                path.closeSubpath()
                painter.drawPath(path)
            elif symbol == "Center":
                # Κύκλος
                painter.drawEllipse(QtCore.QPointF(0, 0), s, s)
            else:
                # Για τα υπόλοιπα, άσε το default αν θες, ή βάλε πάλι σχήματα
                painter.drawRect(QtCore.QRectF(-s/2, -s/2, s, s))

        # PATCHING: Αντικατάσταση της εσωτερικής συνάρτησης του Sniffer
        # Αυτό αναγκάζει το FreeCAD να καλεί τη δική ΜΑΣ ζωγραφική
        if hasattr(DraftGui.sniffer, "drawSymbol"):
            DraftGui.sniffer.drawSymbol = draw_autocad_snap
            
        App.Console.PrintLog("ClassicCAD: Snap drawing logic OVERRIDDEN (AutoCAD Style).\n")
        
    except Exception as e:
        App.Console.PrintError(f"Snap Hard Patch Error: {str(e)}\n")

if __name__ == "__main__":
    setup()