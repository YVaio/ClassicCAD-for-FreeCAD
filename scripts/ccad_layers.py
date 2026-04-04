import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore, QtGui
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
    if not doc:
        return None

    try:
        toolbar = getattr(Gui, 'draftToolBar', None)
        autogroup = getattr(toolbar, 'autogroup', None) if toolbar else None
        if autogroup:
            layer = doc.getObject(autogroup)
            if layer and _is_layer_container(layer):
                return layer
    except Exception:
        pass

    param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
    layer_name = param.GetString("CurrentLayer", "")
    if layer_name:
        layer = doc.getObject(layer_name)
        if layer and _is_layer_container(layer):
            return layer

    return next((o for o in doc.Objects if o.Label == "0" or o.Name == "Layer0"), None)


def get_object_layer(obj):
    if not obj or not hasattr(obj, "InList"):
        return None
    for parent in obj.InList:
        if _is_layer_container(parent):
            return parent
    return None


def _layer_add_object(layer, obj):
    if not layer or not obj or not hasattr(layer, "Group"):
        return False

    try:
        if hasattr(layer, "addObject"):
            layer.addObject(obj)
            return True
    except Exception:
        pass

    try:
        proxy = getattr(layer, "Proxy", None)
        if proxy and hasattr(proxy, "addObject"):
            proxy.addObject(layer, obj)
            return True
    except Exception:
        pass

    try:
        group = list(getattr(layer, "Group", []) or [])
        if obj not in group:
            group.append(obj)
            layer.Group = group
        return True
    except Exception:
        return False


def _layer_remove_object(layer, obj):
    if not layer or not obj or not hasattr(layer, "Group"):
        return False

    try:
        if hasattr(layer, "removeObject"):
            layer.removeObject(obj)
            return True
    except Exception:
        pass

    try:
        proxy = getattr(layer, "Proxy", None)
        if proxy and hasattr(proxy, "removeObject"):
            proxy.removeObject(layer, obj)
            return True
    except Exception:
        pass

    try:
        group = list(getattr(layer, "Group", []) or [])
        if obj in group:
            group.remove(obj)
            layer.Group = group
        return True
    except Exception:
        return False


def assign_to_layer(obj, layer=None):
    if not obj:
        return False
    doc = getattr(obj, "Document", None) or App.ActiveDocument
    if not doc:
        return False

    target_layer = layer or get_object_layer(obj) or get_active_layer(doc)
    if not target_layer or not hasattr(target_layer, "Group"):
        return False

    for parent in list(getattr(obj, "InList", [])):
        if parent != target_layer and _is_layer_container(parent):
            _layer_remove_object(parent, obj)

    if obj not in list(getattr(target_layer, "Group", []) or []):
        return _layer_add_object(target_layer, obj)
    return True


def _safe_rgb(value, default=(1.0, 1.0, 1.0)):
    try:
        vals = list(value)
        if len(vals) >= 3:
            return (float(vals[0]), float(vals[1]), float(vals[2]))
    except Exception:
        pass
    return default


def _safe_rgba(value, default=(1.0, 1.0, 1.0, 0.0)):
    rgb = _safe_rgb(value, default[:3])
    alpha = default[3] if len(default) >= 4 else 0.0
    try:
        vals = list(value)
        if len(vals) >= 4:
            alpha = float(vals[3])
    except Exception:
        pass
    return (rgb[0], rgb[1], rgb[2], alpha)


def _to_rgba_param(value, default=(1.0, 1.0, 1.0)):
    rgb = _safe_rgb(value, default)
    try:
        from draftutils import utils
        color = QtGui.QColor(
            int(max(0.0, min(1.0, rgb[0])) * 255),
            int(max(0.0, min(1.0, rgb[1])) * 255),
            int(max(0.0, min(1.0, rgb[2])) * 255),
            255,
        )
        return utils.argb_to_rgba(color.rgba())
    except Exception:
        return 0xFFFFFFFF


def _style_index(value, options, default=0):
    try:
        return list(options).index(value)
    except Exception:
        try:
            return int(value)
        except Exception:
            return default


def _get_layer_style_preset(layer):
    if not layer:
        return None
    vobj = getattr(layer, "ViewObject", None)
    if not vobj:
        return None

    try:
        from draftutils import utils
        draw_styles = list(getattr(utils, "DRAW_STYLES", []))
        display_modes = list(getattr(utils, "DISPLAY_MODES", []))
    except Exception:
        draw_styles = ["Solid", "Dashed", "Dotted", "Dashdot"]
        display_modes = ["Flat Lines", "Wireframe", "Shaded"]

    line_color_rgb = _safe_rgb(getattr(vobj, "LineColor", (1.0, 1.0, 1.0)))
    shape_color_rgb = _safe_rgb(getattr(vobj, "ShapeColor", line_color_rgb))
    point_color_rgb = _safe_rgb(getattr(vobj, "PointColor", line_color_rgb))
    ambient_color_rgb = _safe_rgb(getattr(vobj, "AmbientColor", shape_color_rgb))
    emissive_color_rgb = _safe_rgb(getattr(vobj, "EmissiveColor", (0.0, 0.0, 0.0)))
    specular_color_rgb = _safe_rgb(getattr(vobj, "SpecularColor", shape_color_rgb))

    material = getattr(vobj, "ShapeMaterial", None)
    if material:
        ambient_color_rgb = _safe_rgb(getattr(material, "AmbientColor", ambient_color_rgb), ambient_color_rgb)
        emissive_color_rgb = _safe_rgb(getattr(material, "EmissiveColor", emissive_color_rgb), emissive_color_rgb)
        specular_color_rgb = _safe_rgb(getattr(material, "SpecularColor", specular_color_rgb), specular_color_rgb)

    line_color = _to_rgba_param(line_color_rgb)
    shape_color = _to_rgba_param(shape_color_rgb)
    point_color = _to_rgba_param(point_color_rgb)
    ambient_color = _to_rgba_param(ambient_color_rgb)
    emissive_color = _to_rgba_param(emissive_color_rgb, (0.0, 0.0, 0.0))
    specular_color = _to_rgba_param(specular_color_rgb)

    line_width = float(getattr(vobj, "LineWidth", 1.0) or 1.0)
    point_size = float(getattr(vobj, "PointSize", max(line_width, 1.0)) or max(line_width, 1.0))
    transparency = int(getattr(vobj, "Transparency", 0) or 0)

    shininess = getattr(vobj, "ShapeShininess", None)
    if shininess is None and material:
        try:
            shininess = float(material.Shininess) * 100.0
        except Exception:
            shininess = 90.0
    try:
        shininess = int(round(float(shininess)))
    except Exception:
        shininess = 90

    draw_style = _style_index(getattr(vobj, "DrawStyle", "Solid"), draw_styles, 0)
    display_mode = _style_index(getattr(vobj, "DisplayMode", "Flat Lines"), display_modes, 0)

    return {
        "ShapeColor": shape_color,
        "AmbientColor": ambient_color,
        "EmissiveColor": emissive_color,
        "SpecularColor": specular_color,
        "Transparency": transparency,
        "Shininess": max(0, min(100, shininess)),
        "LineColor": line_color,
        "LineWidth": int(round(line_width)),
        "PointColor": point_color,
        "PointSize": int(round(point_size)),
        "DrawStyle": draw_style,
        "DisplayMode": display_mode,
        "TextColor": line_color,
        "AnnoLineColor": line_color,
        "AnnoLineWidth": int(round(line_width)),
    }


def _layer_style_signature(layer):
    preset = _get_layer_style_preset(layer)
    if not preset:
        return None
    sig = []
    for key in (
        "ShapeColor", "AmbientColor", "EmissiveColor", "SpecularColor",
        "Transparency", "Shininess", "LineColor", "LineWidth",
        "PointColor", "PointSize", "DrawStyle", "DisplayMode"
    ):
        value = preset.get(key)
        if isinstance(value, (tuple, list)):
            sig.append(tuple(round(float(v), 6) for v in value))
        else:
            sig.append(value)
    return tuple(sig)


def sync_style_to_active_layer(doc=None, layer=None):
    doc = doc or App.ActiveDocument
    if not doc:
        return None

    layer = layer or get_active_layer(doc)
    preset = _get_layer_style_preset(layer)
    if not preset:
        return None

    try:
        from draftutils import params, utils

        params.set_param_view("DefaultShapeColor", preset["ShapeColor"])
        params.set_param_view("DefaultAmbientColor", preset["AmbientColor"])
        params.set_param_view("DefaultEmissiveColor", preset["EmissiveColor"])
        params.set_param_view("DefaultSpecularColor", preset["SpecularColor"])
        params.set_param_view("DefaultShapeTransparency", int(preset["Transparency"]))
        params.set_param_view("DefaultShapeShininess", int(preset["Shininess"]))
        params.set_param_view("DefaultShapeLineColor", preset["LineColor"])
        params.set_param_view("DefaultShapeLineWidth", int(preset["LineWidth"]))
        params.set_param_view("DefaultShapeVertexColor", preset["PointColor"])
        params.set_param_view("DefaultShapePointSize", int(preset["PointSize"]))
        params.set_param("DefaultDrawStyle", int(preset["DrawStyle"]))
        params.set_param("DefaultDisplayMode", int(preset["DisplayMode"]))
        params.set_param("DefaultTextColor", preset["TextColor"])
        params.set_param("DefaultAnnoLineColor", preset["AnnoLineColor"])
        params.set_param("DefaultAnnoLineWidth", int(preset["AnnoLineWidth"]))

        view_param = App.ParamGet("User parameter:BaseApp/Preferences/View")
        view_param.SetUnsigned("DefaultShapeColor", int(preset["ShapeColor"]))
        view_param.SetUnsigned("DefaultAmbientColor", int(preset["AmbientColor"]))
        view_param.SetUnsigned("DefaultEmissiveColor", int(preset["EmissiveColor"]))
        view_param.SetUnsigned("DefaultSpecularColor", int(preset["SpecularColor"]))
        view_param.SetInt("DefaultShapeTransparency", int(preset["Transparency"]))
        view_param.SetInt("DefaultShapeShininess", int(preset["Shininess"]))
        view_param.SetUnsigned("DefaultShapeLineColor", int(preset["LineColor"]))
        view_param.SetInt("DefaultShapeLineWidth", int(preset["LineWidth"]))
        view_param.SetUnsigned("DefaultShapeVertexColor", int(preset["PointColor"]))
        view_param.SetInt("DefaultShapePointSize", int(preset["PointSize"]))

        draft_param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
        draft_param.SetInt("DefaultDrawStyle", int(preset["DrawStyle"]))
        draft_param.SetInt("DefaultDisplayMode", int(preset["DisplayMode"]))
        draft_param.SetUnsigned("DefaultTextColor", int(preset["TextColor"]))
        draft_param.SetUnsigned("DefaultAnnoLineColor", int(preset["AnnoLineColor"]))
        draft_param.SetInt("DefaultAnnoLineWidth", int(preset["AnnoLineWidth"]))

        toolbar = getattr(Gui, 'draftToolBar', None)
        if toolbar:
            try:
                toolbar.color = QtGui.QColor(utils.rgba_to_argb(int(preset["LineColor"])))
                toolbar.facecolor = QtGui.QColor(utils.rgba_to_argb(int(preset["ShapeColor"])))
                toolbar.linewidth = int(preset["LineWidth"])
            except Exception:
                pass
            if hasattr(toolbar, 'setStyleButton'):
                toolbar.setStyleButton()
    except Exception:
        return None

    for panel in (getattr(Gui, 'ccad_style_task_panel', None), getattr(Gui.Control, 'activeDialog', lambda: None)()):
        try:
            if panel and hasattr(panel, 'setValues') and hasattr(panel, 'form'):
                form = getattr(panel, 'form', None)
                if form and hasattr(form, 'LineColor') and hasattr(form, 'ShapeColor'):
                    panel.setValues(preset)
        except Exception:
            pass

    return preset


def _patch_runtime_hooks():
    try:
        toolbar = getattr(Gui, 'draftToolBar', None)
        tb_cls = toolbar.__class__ if toolbar else None
        if tb_cls and hasattr(tb_cls, 'setAutoGroup') and not hasattr(tb_cls, '_ccad_layer_sync_patched'):
            orig_set_auto_group = tb_cls.setAutoGroup

            def patched_set_auto_group(self, value=None):
                result = orig_set_auto_group(self, value)
                try:
                    doc = App.ActiveDocument
                    layer = doc.getObject(value) if doc and value else None
                    param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
                    param.SetString("CurrentLayer", getattr(layer, 'Name', '') if layer and _is_layer_container(layer) else '')
                    sync_style_to_active_layer(doc, layer if layer and _is_layer_container(layer) else None)
                except Exception:
                    pass
                return result

            tb_cls.setAutoGroup = patched_set_auto_group
            tb_cls._ccad_layer_sync_patched = True
    except Exception:
        pass

    try:
        from draftguitools import gui_setstyle
        if hasattr(gui_setstyle, "Draft_SetStyle") and not hasattr(gui_setstyle.Draft_SetStyle, "_ccad_patched"):
            orig_activated = gui_setstyle.Draft_SetStyle.Activated
            def patched_activated(self, *args, **kwargs):
                if Gui.Control.activeDialog():
                    Gui.Control.closeDialog()
                sync_style_to_active_layer(App.ActiveDocument)
                return orig_activated(self, *args, **kwargs)
            gui_setstyle.Draft_SetStyle.Activated = patched_activated
            gui_setstyle.Draft_SetStyle._ccad_patched = True

        if hasattr(gui_setstyle, "Draft_SetStyle_TaskPanel") and not hasattr(gui_setstyle.Draft_SetStyle_TaskPanel, "_ccad_patched"):
            orig_panel_init = gui_setstyle.Draft_SetStyle_TaskPanel.__init__
            orig_load_defaults = gui_setstyle.Draft_SetStyle_TaskPanel.loadDefaults
            orig_accept = gui_setstyle.Draft_SetStyle_TaskPanel.accept
            orig_reject = gui_setstyle.Draft_SetStyle_TaskPanel.reject

            def patched_panel_init(self, *args, **kwargs):
                orig_panel_init(self, *args, **kwargs)
                Gui.ccad_style_task_panel = self
                try:
                    preset = sync_style_to_active_layer(App.ActiveDocument)
                    if preset and hasattr(self, 'setValues'):
                        self.setValues(preset)
                except Exception:
                    pass

            def patched_load_defaults(self, *args, **kwargs):
                result = orig_load_defaults(self, *args, **kwargs)
                try:
                    preset = sync_style_to_active_layer(App.ActiveDocument)
                    if preset and hasattr(self, 'setValues'):
                        self.setValues(preset)
                except Exception:
                    pass
                return result

            def patched_accept(self, *args, **kwargs):
                try:
                    return orig_accept(self, *args, **kwargs)
                finally:
                    if getattr(Gui, 'ccad_style_task_panel', None) is self:
                        Gui.ccad_style_task_panel = None

            def patched_reject(self, *args, **kwargs):
                try:
                    return orig_reject(self, *args, **kwargs)
                finally:
                    if getattr(Gui, 'ccad_style_task_panel', None) is self:
                        Gui.ccad_style_task_panel = None

            gui_setstyle.Draft_SetStyle_TaskPanel.__init__ = patched_panel_init
            gui_setstyle.Draft_SetStyle_TaskPanel.loadDefaults = patched_load_defaults
            gui_setstyle.Draft_SetStyle_TaskPanel.accept = patched_accept
            gui_setstyle.Draft_SetStyle_TaskPanel.reject = patched_reject
            gui_setstyle.Draft_SetStyle_TaskPanel._ccad_patched = True
    except Exception:
        pass

    try:
        from draftguitools import gui_groups
        if hasattr(gui_groups, 'SetAutoGroup') and not hasattr(gui_groups.SetAutoGroup, '_ccad_layer_sync_patched'):
            orig_proceed = gui_groups.SetAutoGroup.proceed

            def patched_proceed(self, option):
                result = orig_proceed(self, option)
                QtCore.QTimer.singleShot(0, lambda: sync_style_to_active_layer(App.ActiveDocument))
                QtCore.QTimer.singleShot(150, lambda: sync_style_to_active_layer(App.ActiveDocument))
                return result

            gui_groups.SetAutoGroup.proceed = patched_proceed
            gui_groups.SetAutoGroup._ccad_layer_sync_patched = True
    except Exception:
        pass


class LayerStyleWatcher(QtCore.QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_doc = None
        self._last_layer = None
        self._last_signature = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.sync_if_needed)
        self.timer.start()
        QtCore.QTimer.singleShot(0, self.sync_if_needed)

    def sync_if_needed(self):
        _patch_runtime_hooks()
        doc = App.ActiveDocument
        doc_name = getattr(doc, "Name", None)
        layer = get_active_layer(doc) if doc else None
        layer_name = getattr(layer, "Name", None)
        signature = _layer_style_signature(layer)

        if doc_name == self._last_doc and layer_name == self._last_layer and signature == self._last_signature:
            return

        self._last_doc = doc_name
        self._last_layer = layer_name
        self._last_signature = signature
        sync_style_to_active_layer(doc, layer)


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

    sync_style_to_active_layer(doc, l0)

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

    if hasattr(Gui, "ccad_layer_style_watcher"):
        try:
            Gui.ccad_layer_style_watcher.timer.stop()
            Gui.ccad_layer_style_watcher.deleteLater()
        except Exception:
            pass
        del Gui.ccad_layer_style_watcher

    Gui.ccad_layer_observer = DocumentObserver()
    App.addDocumentObserver(Gui.ccad_layer_observer)
    Gui.ccad_layer_style_watcher = LayerStyleWatcher(Gui.getMainWindow())
    _patch_runtime_hooks()

    # Εκκίνηση: Εξασφάλιση Layer 0 με καθυστέρηση για να είναι έτοιμο το UI
    if App.ActiveDocument:
        QtCore.QTimer.singleShot(1000, lambda: ensure_layer_0(App.ActiveDocument))

setup()

if __name__ == "__main__":
    setup()