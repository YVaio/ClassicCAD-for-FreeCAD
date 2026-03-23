import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore
import Draft

def get_active_layer(doc):
    """Βρίσκει το ενεργό layer ή επιστρέφει το Layer 0 ως προεπιλογή"""
    param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
    layer_name = param.GetString("CurrentLayer", "")
    
    if layer_name:
        layer = doc.getObject(layer_name)
        if layer: return layer
        
    # Αν δεν υπάρχει ενεργό, ψάχνουμε το Layer "0"
    return next((o for o in doc.Objects if o.Label == "0" or o.Name == "Layer0"), None)

class LayerZeroManager:
    @staticmethod
    def ensure_layer_zero_and_activate(doc):
        if not doc: return
            
        # Πιο ευρύς έλεγχος για να μην δημιουργεί διπλά layers
        l0 = None
        for o in doc.Objects:
            if o.Label == "0" or o.Name == "Layer0":
                l0 = o
                break
        
        if not l0:
            try:
                l0 = Draft.make_layer(name="Layer0")
                l0.Label = "0"
                if hasattr(l0, "ViewObject") and l0.ViewObject:
                    l0.ViewObject.LineColor = (1.0, 1.0, 1.0)
                    l0.ViewObject.LineWidth = 2.0
                doc.recompute()
                App.Console.PrintLog("ClassicCAD: Layer '0' created.\n")
            except Exception as e:
                App.Console.PrintError(f"ClassicCAD: Error creating Layer 0: {e}\n")
                return

        if l0:
            try:
                param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
                param.SetString("CurrentLayer", l0.Name)
                if hasattr(Gui, "draftToolBar") and hasattr(Gui.draftToolBar, "layerUI"):
                    Gui.draftToolBar.layerUI.update()
            except: pass

class DocumentObserver:
    def slotCreatedDocument(self, doc):
        QtCore.QTimer.singleShot(2000, lambda: LayerZeroManager.ensure_layer_zero_and_activate(doc))

    def slotCreatedObject(self, obj):
        if not obj or not hasattr(obj, "Name"):
            return
            
        # Αγνοούμε τη δημιουργία του ίδιου του layer ή άλλων groups για να μην έχουμε λούπες
        if obj.Label == "0" or obj.Name.startswith("Layer") or "Group" in obj.TypeId:
            return
            
        obj_name = obj.Name
        QtCore.QTimer.singleShot(500, lambda: self.move_to_active_layer(obj_name))

    def move_to_active_layer(self, obj_name):
        doc = App.ActiveDocument
        if not doc: return
        obj = doc.getObject(obj_name)
        if not obj: return
        
        # Έλεγχος αν το αντικείμενο ανήκει ήδη σε κάτι (π.χ. σε Group/Layer)
        if hasattr(obj, "InList") and any(hasattr(p, "Group") for p in obj.InList):
            return

        active_layer = get_active_layer(doc)
        if active_layer and hasattr(active_layer, "addObject"):
            try:
                active_layer.addObject(obj)
            except Exception as e:
                pass

def setup():
    if hasattr(Gui, "ccad_layer_observer"):
        try:
            App.removeDocumentObserver(Gui.ccad_layer_observer)
            del Gui.ccad_layer_observer
        except: pass

    mw = Gui.getMainWindow()
    if mw:
        old_tb = mw.findChild(QtCore.QObject, "ClassicCADLayerToolbar")
        if old_tb:
            mw.removeToolBar(old_tb)
            old_tb.deleteLater()

    Gui.ccad_layer_observer = DocumentObserver()
    App.addDocumentObserver(Gui.ccad_layer_observer)

    if App.ActiveDocument:
        QtCore.QTimer.singleShot(500, lambda: LayerZeroManager.ensure_layer_zero_and_activate(App.ActiveDocument))

    print("ClassicCAD: Smart Auto-Grouping to Active Layer Loaded.")

if __name__ == "__main__":
    setup()