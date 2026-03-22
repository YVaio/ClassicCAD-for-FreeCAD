import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore

class LayerManager:
    @staticmethod
    def ensure_layer_zero(doc):
        """Δημιουργεί το Layer 0 αν δεν υπάρχει"""
        if not doc: return
        
        # Έλεγχος αν υπάρχει ήδη layer με label "0"
        exists = False
        for obj in doc.Objects:
            if obj.Label == "0":
                exists = True
                break
        
        if not exists:
            try:
                import Draft
                # Δημιουργία layer
                l0 = Draft.make_layer(name="Layer0")
                l0.Label = "0"
                # Λευκό χρώμα στο ViewObject (RGB 1,1,1)
                if hasattr(l0, "ViewObject"):
                    l0.ViewObject.LineColor = (1.0, 1.0, 1.0)
                doc.recompute()
                print("ClassicCAD: Layer '0' created.")
            except Exception as e:
                print(f"ClassicCAD: Failed to create Layer 0: {e}")

class DocumentObserver:
    """Παρατηρητής για νέα έγγραφα"""
    def slotCreatedDocument(self, doc):
        # Καθυστέρηση 2 δευτερολέπτων για να προλάβει να φορτώσει το Draft module
        QtCore.QTimer.singleShot(2000, lambda: LayerManager.ensure_layer_zero(doc))

def setup():
    """Αρχικοποίηση του module"""
    # Σύνδεση του Observer
    if not hasattr(Gui, "ccad_layer_observer"):
        Gui.ccad_layer_observer = DocumentObserver()
        App.addDocumentObserver(Gui.ccad_layer_observer)
    
    # Έλεγχος για το τρέχον ανοιχτό έγγραφο
    if App.ActiveDocument:
        LayerManager.ensure_layer_zero(App.ActiveDocument)

    print("ClassicCAD: Layer 0 Basic Initialization Active.")

if __name__ == "__main__":
    setup()