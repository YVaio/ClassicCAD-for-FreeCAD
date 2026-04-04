import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore
import Draft

def _is_layer_container(obj):
    if not obj:
        return False
    type_id = getattr(obj, "TypeId", "") or ""
    name = getattr(obj, "Name", "") or ""
    label = getattr(obj, "Label", "") or ""
    return hasattr(obj, "Group") and (
        "Layer" in type_id or name.startswith("Layer") or label == "0"
    )


def get_active_layer(doc):
    param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
    layer_name = param.GetString("CurrentLayer", "")
    if layer_name:
        layer = doc.getObject(layer_name)
        if layer:
            return layer
    return next((o for o in doc.Objects if o.Label == "0" or o.Name == "Layer0"), None)


def get_object_layer(obj):
    if not obj or not hasattr(obj, "InList"):
        return None
    for parent in obj.InList:
        if _is_layer_container(parent):
            return parent
    return None


def assign_to_layer(obj, layer=None):
    if not obj:
        return False
    doc = getattr(obj, "Document", None) or App.ActiveDocument
    if not doc:
        return False

    target_layer = layer or get_object_layer(obj) or get_active_layer(doc)
    if not target_layer or not hasattr(target_layer, "addObject"):
        return False

    for parent in list(getattr(obj, "InList", [])):
        if parent != target_layer and _is_layer_container(parent) and hasattr(parent, "removeObject"):
            try:
                parent.removeObject(obj)
            except Exception:
                pass

    if obj not in getattr(target_layer, "Group", []):
        try:
            target_layer.addObject(obj)
        except Exception:
            return False
    return True

def ensure_layer_0(doc):
    if not doc: return
    l0 = next((o for o in doc.Objects if o.Label == "0" or o.Name == "Layer0"), None)
    
    if not l0:
        try:
            l0 = Draft.make_layer(name="Layer0")
            l0.Label = "0"
            doc.recompute()
        except Exception: return

    # Επιβολή 1px πάχους στο Layer 0 & λευκό χρώμα
    if l0 and hasattr(l0, "ViewObject") and l0.ViewObject:
        l0.ViewObject.LineColor = (1.0, 1.0, 1.0)
        if hasattr(l0.ViewObject, "LineWidth"):
            l0.ViewObject.LineWidth = 1.0

    # Ενεργοποίηση και ενημέρωση UI
    p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
    p.SetString("CurrentLayer", l0.Name)
    
    if hasattr(Gui, 'draftToolBar'):
        try:
            if hasattr(Gui.draftToolBar, 'setAutoGroup'): 
                Gui.draftToolBar.setAutoGroup(l0.Name)
            elif hasattr(Gui.draftToolBar, 'autogroup'): 
                Gui.draftToolBar.autogroup = l0.Name
        except Exception: pass

class DocumentObserver:
    def slotCreatedDocument(self, doc):
        QtCore.QTimer.singleShot(500, lambda: ensure_layer_0(doc))

    def slotActivateDocument(self, doc_ptr):
        # Στο 1.1 το slot δίνει το ίδιο το object, όχι το όνομα
        try:
            doc = doc_ptr if not isinstance(doc_ptr, str) else App.getDocument(doc_ptr)
            if doc: ensure_layer_0(doc)
        except Exception: pass

    def slotCreatedObject(self, obj):
        if not obj or not hasattr(obj, "Name"): return

        # Επιβολή 1px σε οποιοδήποτε νέο Layer δημιουργείται
        if obj.TypeId == "App::DocumentObjectGroup" or "Layer" in obj.TypeId or obj.Name.startswith("Layer"):
            def set_lw(name):
                o = App.ActiveDocument.getObject(name)
                if o and hasattr(o, "ViewObject") and o.ViewObject:
                    if hasattr(o.ViewObject, "LineWidth"):
                        o.ViewObject.LineWidth = 1.0
            QtCore.QTimer.singleShot(200, lambda n=obj.Name: set_lw(n))
            return

        if obj.Label == "0" or obj.Name.startswith("Layer") or "Group" in obj.TypeId: return
        if obj.TypeId in ('App::Origin', 'App::Line', 'App::Plane'): return

        obj_name = obj.Name
        # Re-apply after a few delays so generated child wires inherit the correct layer.
        for delay in (150, 500, 1000):
            QtCore.QTimer.singleShot(delay, lambda n=obj_name: self.move_to_active_layer(n))

    def move_to_active_layer(self, obj_name):
        doc = App.ActiveDocument
        if not doc: return
        obj = doc.getObject(obj_name)
        if not obj: return

        target_layer = get_object_layer(obj) or get_active_layer(doc)
        if not target_layer or not hasattr(target_layer, "Group"): return

        # Keep the object's existing layer if it already has one; otherwise use the active layer.
        objects_to_move = [obj]
        if hasattr(obj, "OutList"):
            for child in obj.OutList:
                if child and child.TypeId not in ('App::Origin', 'App::Plane', 'App::Line'):
                    objects_to_move.append(child)

        for item in objects_to_move:
            item_layer = get_object_layer(item) or target_layer
            assign_to_layer(item, item_layer)

def setup():
    if hasattr(Gui, "ccad_layer_observer"):
        try:
            App.removeDocumentObserver(Gui.ccad_layer_observer)
            del Gui.ccad_layer_observer
        except: pass

    Gui.ccad_layer_observer = DocumentObserver()
    App.addDocumentObserver(Gui.ccad_layer_observer)

    # Patch για το Task Dialog Crash
    try:
        from draftguitools import gui_setstyle
        if hasattr(gui_setstyle, "Draft_SetStyle") and not hasattr(gui_setstyle.Draft_SetStyle, "_ccad_patched"):
            orig_activated = gui_setstyle.Draft_SetStyle.Activated
            def patched_activated(self, *args, **kwargs):
                if Gui.Control.activeDialog():
                    Gui.Control.closeDialog()
                return orig_activated(self, *args, **kwargs)
            gui_setstyle.Draft_SetStyle.Activated = patched_activated
            gui_setstyle.Draft_SetStyle._ccad_patched = True
    except Exception: pass

    # Εκκίνηση: Εξασφάλιση Layer 0 με καθυστέρηση για να είναι έτοιμο το UI
    if App.ActiveDocument:
        QtCore.QTimer.singleShot(1000, lambda: ensure_layer_0(App.ActiveDocument))

setup()

if __name__ == "__main__":
    setup()