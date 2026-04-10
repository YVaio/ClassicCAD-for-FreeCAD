import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore, QtGui, QtWidgets
import Draft


_PATCHED_ORIGINALS = {}


def _is_restoring_state(obj=None, doc=None):
    try:
        if obj and hasattr(obj, "isRestoring") and obj.isRestoring():
            return True
    except Exception:
        pass
    try:
        if hasattr(App, "isRestoring") and App.isRestoring():
            return True
    except Exception:
        pass
    return False

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
    if not obj:
        return None

    try:
        from draftobjects.layer import get_layer as draft_get_layer

        layer = draft_get_layer(obj)
        if layer and _is_layer_container(layer):
            return layer
    except Exception:
        pass

    doc = getattr(obj, "Document", None) or App.ActiveDocument
    if doc:
        try:
            for candidate in doc.Objects:
                if _is_layer_container(candidate) and obj in list(getattr(candidate, "Group", []) or []):
                    return candidate
        except Exception:
            pass

    if hasattr(obj, "InList"):
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

    seen = set()
    all_parents = list(getattr(obj, "InList", []))
    try:
        all_parents.extend([candidate for candidate in doc.Objects if _is_layer_container(candidate)])
    except Exception:
        pass

    for parent in all_parents:
        parent_name = getattr(parent, 'Name', None)
        if not parent_name or parent_name in seen:
            continue
        seen.add(parent_name)
        if parent != target_layer and _is_layer_container(parent):
            _layer_remove_object(parent, obj)

    if obj not in list(getattr(target_layer, "Group", []) or []):
        return _layer_add_object(target_layer, obj)
    return True


def _console_message(text, color="#aaa"):
    console = getattr(Gui, "classic_console", None)
    if console and hasattr(console, "history"):
        console.history.append(f"<span style='color:{color};'>{text}</span>")
        console.history.moveCursor(QtGui.QTextCursor.End)
    else:
        App.Console.PrintMessage(text + "\n")


def _console_warning(text):
    console = getattr(Gui, "classic_console", None)
    if console and hasattr(console, "history"):
        console.history.append(f"<span style='color:#ff5555;'>{text}</span>")
        console.history.moveCursor(QtGui.QTextCursor.End)
    else:
        App.Console.PrintWarning(text + "\n")


def _screen_pos(event):
    return event.position().toPoint() if hasattr(event, "position") else event.pos()


def _get_viewport():
    sel_logic = getattr(Gui, 'ccad_sel_logic', None)
    if sel_logic and getattr(sel_logic, 'viewport', None):
        return sel_logic.viewport

    mw = Gui.getMainWindow()
    if mw:
        for widget in mw.findChildren(QtWidgets.QWidget):
            try:
                if "View3DInventor" in widget.metaObject().className() and widget.isVisible():
                    return widget
            except Exception:
                pass
    return None


def _pick_view_object(pos):
    try:
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else Gui.activeView()
    except Exception:
        view = None
    if not view:
        return None

    try:
        info = view.getObjectInfo((pos.x(), pos.y()))
    except Exception:
        info = None
    if not isinstance(info, dict):
        return None

    obj_name = info.get("Object")
    doc = App.ActiveDocument
    if not doc or not obj_name:
        return None
    try:
        return doc.getObject(obj_name)
    except Exception:
        return None


def _layer_is_visible(layer):
    if not layer:
        return False
    try:
        vobj = getattr(layer, "ViewObject", None)
        if vobj and hasattr(vobj, "Visibility"):
            return bool(vobj.Visibility)
    except Exception:
        pass
    try:
        if hasattr(layer, "Visibility"):
            return bool(layer.Visibility)
    except Exception:
        pass
    return True


def _set_layer_visibility(layer, visible):
    if not layer:
        return False

    changed = False
    bool_visible = bool(visible)

    try:
        vobj = getattr(layer, "ViewObject", None)
        if vobj and hasattr(vobj, "Visibility") and bool(vobj.Visibility) != bool_visible:
            vobj.Visibility = bool_visible
            changed = True
    except Exception:
        pass

    try:
        if hasattr(layer, "Visibility") and bool(layer.Visibility) != bool_visible:
            layer.Visibility = bool_visible
            changed = True
    except Exception:
        pass

    return changed


def _set_current_layer(layer):
    if not layer:
        return False

    doc = getattr(layer, "Document", None) or App.ActiveDocument
    if not doc:
        return False

    try:
        param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
        param.SetString("CurrentLayer", layer.Name)
    except Exception:
        pass

    toolbar = getattr(Gui, 'draftToolBar', None)
    if toolbar:
        try:
            if hasattr(toolbar, 'setAutoGroup'):
                toolbar.setAutoGroup(layer.Name)
            elif hasattr(toolbar, 'autogroup'):
                toolbar.autogroup = layer.Name
        except Exception:
            pass

    sync_style_to_active_layer(doc, layer)
    sync_layer_dropdown_to_selection(doc)
    return True


def _activate_fallback_layer(doc, hidden_layer=None):
    if not doc:
        return None

    hidden_name = getattr(hidden_layer, "Name", "") if hidden_layer else ""
    for candidate in doc.Objects:
        if not _is_layer_container(candidate):
            continue
        if getattr(candidate, "Name", "") == hidden_name:
            continue
        if _layer_is_visible(candidate):
            if _set_current_layer(candidate):
                return candidate

    ensure_layer_0(doc, force_active=True)
    fallback = get_active_layer(doc)
    if fallback and getattr(fallback, "Name", "") != hidden_name:
        return fallback
    return None


def _hide_layer(layer):
    if not layer:
        return False

    doc = getattr(layer, "Document", None) or App.ActiveDocument
    if not doc:
        return False

    if not _layer_is_visible(layer):
        return False

    active_layer = get_active_layer(doc)
    if active_layer and getattr(active_layer, "Name", "") == getattr(layer, "Name", ""):
        fallback_layer = _activate_fallback_layer(doc, hidden_layer=layer)
        if not fallback_layer:
            _console_warning(f"LAYOFF: Cannot turn off current layer '{layer.Label}'.")
            return False

    changed = _set_layer_visibility(layer, False)
    if changed:
        try:
            doc.recompute()
        except Exception:
            pass
        sync_layer_dropdown_to_selection(doc)
    return changed


def _finalize_transaction(doc, changed):
    if not doc:
        return
    try:
        if changed:
            doc.commitTransaction()
        elif hasattr(doc, "abortTransaction"):
            doc.abortTransaction()
        else:
            doc.commitTransaction()
    except Exception:
        pass


def _off_layers_for_objects(objects):
    doc = App.ActiveDocument
    if not doc:
        return False

    layers = []
    seen = set()
    for obj in objects or []:
        if not obj or _is_layer_container(obj):
            continue
        layer = get_object_layer(obj)
        name = getattr(layer, "Name", "") if layer else ""
        if not name or name in seen:
            continue
        seen.add(name)
        layers.append(layer)

    if not layers:
        _console_warning("LAYOFF: No layer-backed object selected.")
        return False

    changed = False
    try:
        doc.openTransaction("Layer Off")
    except Exception:
        pass

    try:
        for layer in layers:
            if _hide_layer(layer):
                changed = True
                _console_message(f"LAYOFF: Layer '{layer.Label}' hidden.", color="#55ff55")
    finally:
        _finalize_transaction(doc, changed)

    try:
        Gui.Selection.clearSelection()
    except Exception:
        pass
    return changed


class LayerOffPickHandler(QtCore.QObject):
    def __init__(self, viewport):
        super().__init__()
        self.viewport = viewport
        Gui.ccad_layoff_handler = self
        if self.viewport:
            self.viewport.installEventFilter(self)
            try:
                self.viewport.setFocus()
            except Exception:
                pass
        _console_message("LAYOFF: Click an object to turn its layer off, or press Esc.")

    def cleanup(self, cancelled=False):
        if getattr(self, "viewport", None):
            try:
                self.viewport.removeEventFilter(self)
            except Exception:
                pass
        self.viewport = None
        if getattr(Gui, 'ccad_layoff_handler', None) is self:
            Gui.ccad_layoff_handler = None
        if cancelled:
            _console_message("LAYOFF cancelled.")

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Escape:
            self.cleanup(cancelled=True)
            return True

        if event.type() != QtCore.QEvent.MouseButtonPress or event.button() != QtCore.Qt.LeftButton:
            return False

        target = _pick_view_object(_screen_pos(event))
        if not target or _is_layer_container(target):
            return True

        _off_layers_for_objects([target])
        return True


def LAYOFF():
    doc = App.ActiveDocument
    if not doc:
        _console_warning("LAYOFF: No active document.")
        return False

    try:
        selected = [obj for obj in Gui.Selection.getSelection() if not _is_layer_container(obj)]
    except Exception:
        selected = []

    if selected:
        return _off_layers_for_objects(selected)

    handler = getattr(Gui, 'ccad_layoff_handler', None)
    if handler:
        handler.cleanup(cancelled=True)

    viewport = _get_viewport()
    if not viewport:
        _console_warning("LAYOFF: 3D view not available.")
        return False

    try:
        Gui.getMainWindow().setFocus()
    except Exception:
        pass
    LayerOffPickHandler(viewport)
    return True


def LAYON():
    doc = App.ActiveDocument
    if not doc:
        _console_warning("LAYON: No active document.")
        return False

    handler = getattr(Gui, 'ccad_layoff_handler', None)
    if handler:
        handler.cleanup(cancelled=True)

    layers = [obj for obj in doc.Objects if _is_layer_container(obj)]
    if not layers:
        _console_warning("LAYON: No layers found.")
        return False

    changed = False
    try:
        doc.openTransaction("Layer On")
    except Exception:
        pass

    try:
        for layer in layers:
            if _set_layer_visibility(layer, True):
                changed = True
    finally:
        _finalize_transaction(doc, changed)

    try:
        doc.recompute()
    except Exception:
        pass

    active_layer = get_active_layer(doc)
    if not active_layer or not _layer_is_visible(active_layer):
        _activate_fallback_layer(doc)
    else:
        sync_style_to_active_layer(doc, active_layer)
        sync_layer_dropdown_to_selection(doc)

    _console_message("LAYON: All layers restored.", color="#55ff55")
    return True


# ──────────────────────────────────────────────────────────
# LAYISO / LAYUNISO  (AutoCAD layer isolation)
# ──────────────────────────────────────────────────────────

def LAYISO():
    """Hide every layer except those containing the selected objects."""
    doc = App.ActiveDocument
    if not doc:
        _console_warning("LAYISO: No active document.")
        return False

    try:
        selected = [o for o in Gui.Selection.getSelection() if not _is_layer_container(o)]
    except Exception:
        selected = []

    if not selected:
        _console_warning("LAYISO: Select at least one object first.")
        return False

    # Collect layers to keep visible
    keep = set()
    for obj in selected:
        layer = get_object_layer(obj)
        if layer:
            keep.add(layer.Name)

    if not keep:
        _console_warning("LAYISO: Selected objects are not on any named layer.")
        return False

    all_layers = [o for o in doc.Objects if _is_layer_container(o)]

    # Save current visibility state so LAYUNISO can restore it
    saved = {layer.Name: _layer_is_visible(layer) for layer in all_layers}
    Gui.ccad_layiso_saved = saved

    changed = False
    try:
        doc.openTransaction("Layer Isolate")
    except Exception:
        pass

    try:
        for layer in all_layers:
            want = layer.Name in keep
            if _set_layer_visibility(layer, want):
                changed = True
    finally:
        _finalize_transaction(doc, changed)

    try:
        doc.recompute()
    except Exception:
        pass

    sync_layer_dropdown_to_selection(doc)

    kept_labels = [l.Label for l in all_layers if l.Name in keep]
    _console_message(
        "LAYISO: Isolated layer(s): " + ", ".join(kept_labels) + ".",
        color="#55ff55",
    )
    return True


def LAYUNISO():
    """Restore layer visibility saved by the last LAYISO call."""
    doc = App.ActiveDocument
    if not doc:
        _console_warning("LAYUNISO: No active document.")
        return False

    saved = getattr(Gui, "ccad_layiso_saved", None)
    if not saved:
        _console_warning("LAYUNISO: No isolated state to restore (run LAYISO first).")
        return False

    changed = False
    try:
        doc.openTransaction("Layer Unisolate")
    except Exception:
        pass

    try:
        for layer in [o for o in doc.Objects if _is_layer_container(o)]:
            want = saved.get(layer.Name, True)
            if _set_layer_visibility(layer, want):
                changed = True
    finally:
        _finalize_transaction(doc, changed)

    Gui.ccad_layiso_saved = None

    try:
        doc.recompute()
    except Exception:
        pass

    sync_layer_dropdown_to_selection(doc)
    _console_message("LAYUNISO: Layer visibility restored.", color="#55ff55")
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


def _selection_layer_signature(doc=None):
    doc = doc or App.ActiveDocument
    try:
        selected = Gui.Selection.getSelection()
    except Exception:
        selected = []

    sig = []
    for obj in selected:
        try:
            if doc and getattr(obj, 'Document', None) != doc:
                continue
            layer = get_object_layer(obj)
            sig.append(getattr(layer, 'Name', '__NONE__'))
        except Exception:
            sig.append('__ERR__')
    return tuple(sorted(sig))


def sync_layer_dropdown_to_selection(doc=None):
    doc = doc or App.ActiveDocument
    toolbar = getattr(Gui, 'draftToolBar', None)
    button = getattr(toolbar, 'autoGroupButton', None) if toolbar else None
    if not doc or not toolbar or button is None:
        return

    try:
        selection = [obj for obj in Gui.Selection.getSelection() if getattr(obj, 'Document', None) == doc]
    except Exception:
        selection = []

    unique_layers = []
    for obj in selection:
        layer = get_object_layer(obj)
        if layer and _is_layer_container(layer):
            if all(getattr(existing, 'Name', None) != getattr(layer, 'Name', None) for existing in unique_layers):
                unique_layers.append(layer)

    try:
        if not selection:
            active = get_active_layer(doc)
            if active and _is_layer_container(active):
                button.setText(active.Label)
                if hasattr(active, 'ViewObject') and active.ViewObject:
                    button.setIcon(active.ViewObject.Icon)
                button.setToolTip('Autogroup: ' + active.Label)
                button.setDown(False)
            return

        if len(unique_layers) == 1:
            layer = unique_layers[0]
            button.setText(layer.Label)
            if hasattr(layer, 'ViewObject') and layer.ViewObject:
                button.setIcon(layer.ViewObject.Icon)
            button.setToolTip('Selection layer: ' + layer.Label)
            button.setDown(False)
        elif len(unique_layers) > 1:
            button.setText('Varies')
            button.setIcon(QtGui.QIcon.fromTheme('Draft_AutoGroup_off', QtGui.QIcon(':/icons/button_invalid.svg')))
            button.setToolTip('Selection spans multiple layers')
            button.setDown(False)
        else:
            button.setText('')
            button.setIcon(QtGui.QIcon.fromTheme('Draft_AutoGroup_off', QtGui.QIcon(':/icons/button_invalid.svg')))
            button.setToolTip('Selection has no assigned layer')
            button.setDown(False)
    except Exception:
        pass


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
            if 'draftToolBar.setAutoGroup' not in _PATCHED_ORIGINALS:
                _PATCHED_ORIGINALS['draftToolBar.setAutoGroup'] = tb_cls.setAutoGroup
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
            if 'Draft_SetStyle.Activated' not in _PATCHED_ORIGINALS:
                _PATCHED_ORIGINALS['Draft_SetStyle.Activated'] = gui_setstyle.Draft_SetStyle.Activated
            orig_activated = gui_setstyle.Draft_SetStyle.Activated
            def patched_activated(self, *args, **kwargs):
                if Gui.Control.activeDialog():
                    Gui.Control.closeDialog()
                sync_style_to_active_layer(App.ActiveDocument)
                return orig_activated(self, *args, **kwargs)
            gui_setstyle.Draft_SetStyle.Activated = patched_activated
            gui_setstyle.Draft_SetStyle._ccad_patched = True

        if hasattr(gui_setstyle, "Draft_SetStyle_TaskPanel") and not hasattr(gui_setstyle.Draft_SetStyle_TaskPanel, "_ccad_patched"):
            if 'Draft_SetStyle_TaskPanel.__init__' not in _PATCHED_ORIGINALS:
                _PATCHED_ORIGINALS['Draft_SetStyle_TaskPanel.__init__'] = gui_setstyle.Draft_SetStyle_TaskPanel.__init__
            if 'Draft_SetStyle_TaskPanel.loadDefaults' not in _PATCHED_ORIGINALS:
                _PATCHED_ORIGINALS['Draft_SetStyle_TaskPanel.loadDefaults'] = gui_setstyle.Draft_SetStyle_TaskPanel.loadDefaults
            if 'Draft_SetStyle_TaskPanel.accept' not in _PATCHED_ORIGINALS:
                _PATCHED_ORIGINALS['Draft_SetStyle_TaskPanel.accept'] = gui_setstyle.Draft_SetStyle_TaskPanel.accept
            if 'Draft_SetStyle_TaskPanel.reject' not in _PATCHED_ORIGINALS:
                _PATCHED_ORIGINALS['Draft_SetStyle_TaskPanel.reject'] = gui_setstyle.Draft_SetStyle_TaskPanel.reject
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
            if 'SetAutoGroup.proceed' not in _PATCHED_ORIGINALS:
                _PATCHED_ORIGINALS['SetAutoGroup.proceed'] = gui_groups.SetAutoGroup.proceed
            orig_proceed = gui_groups.SetAutoGroup.proceed

            def patched_proceed(self, option):
                doc = getattr(self, 'doc', None) or App.ActiveDocument
                toolbar = getattr(Gui, 'draftToolBar', None)
                preserved_active_name = getattr(toolbar, 'autogroup', None) if toolbar else None

                try:
                    if hasattr(self, 'ui') and self.ui:
                        self.ui.sourceCmd = None
                except Exception:
                    pass

                selection = []
                try:
                    selection = [
                        obj for obj in Gui.Selection.getSelection()
                        if getattr(obj, 'Document', None) == doc and not _is_layer_container(obj)
                    ]
                except Exception:
                    selection = []

                def _restore_active_layer():
                    if not toolbar:
                        return
                    try:
                        toolbar.setAutoGroup(preserved_active_name)
                    except Exception:
                        pass

                if selection and option == self.labels[0]:
                    changed = False
                    try:
                        if doc:
                            doc.openTransaction("Remove from layer")
                        for obj in selection:
                            current = get_object_layer(obj)
                            if current:
                                _layer_remove_object(current, obj)
                                changed = True
                        if doc:
                            if changed:
                                doc.commitTransaction()
                                doc.recompute()
                            elif hasattr(doc, 'abortTransaction'):
                                doc.abortTransaction()
                    except Exception:
                        pass
                    _restore_active_layer()
                    QtCore.QTimer.singleShot(0, lambda d=doc: sync_style_to_active_layer(d))
                    QtCore.QTimer.singleShot(0, lambda d=doc: sync_layer_dropdown_to_selection(d))
                    return None

                if selection and doc and option not in (self.labels[0], self.labels[-1]):
                    try:
                        i = self.labels.index(option)
                        target_name = self.names[i] if i < len(self.names) else None
                        target_layer = doc.getObject(target_name) if target_name else None
                    except Exception:
                        target_layer = None

                    if target_layer and _is_layer_container(target_layer):
                        try:
                            changed = False
                            doc.openTransaction("Assign to layer")
                            for obj in selection:
                                changed = assign_to_layer(obj, target_layer) or changed
                            if changed:
                                doc.commitTransaction()
                                doc.recompute()
                            elif hasattr(doc, 'abortTransaction'):
                                doc.abortTransaction()
                        except Exception:
                            pass
                        _restore_active_layer()
                        QtCore.QTimer.singleShot(0, lambda d=doc: sync_style_to_active_layer(d))
                        QtCore.QTimer.singleShot(0, lambda d=doc: sync_layer_dropdown_to_selection(d))
                        QtCore.QTimer.singleShot(150, lambda d=doc: sync_style_to_active_layer(d))
                        QtCore.QTimer.singleShot(150, lambda d=doc: sync_layer_dropdown_to_selection(d))
                        return None

                result = orig_proceed(self, option)

                if selection and doc:
                    try:
                        target_layer = get_active_layer(doc)
                        if target_layer and _is_layer_container(target_layer):
                            changed = False
                            doc.openTransaction("Assign to layer")
                            for obj in selection:
                                changed = assign_to_layer(obj, target_layer) or changed
                            if changed:
                                doc.commitTransaction()
                                doc.recompute()
                            elif hasattr(doc, 'abortTransaction'):
                                doc.abortTransaction()
                    except Exception:
                        pass
                    _restore_active_layer()

                QtCore.QTimer.singleShot(0, lambda d=doc: sync_style_to_active_layer(d))
                QtCore.QTimer.singleShot(0, lambda d=doc: sync_layer_dropdown_to_selection(d))
                QtCore.QTimer.singleShot(150, lambda d=doc: sync_style_to_active_layer(d))
                QtCore.QTimer.singleShot(150, lambda d=doc: sync_layer_dropdown_to_selection(d))
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
        self._last_selection_signature = None
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
        selection_signature = _selection_layer_signature(doc)

        if (
            doc_name == self._last_doc
            and layer_name == self._last_layer
            and signature == self._last_signature
            and selection_signature == self._last_selection_signature
        ):
            return

        self._last_doc = doc_name
        self._last_layer = layer_name
        self._last_signature = signature
        self._last_selection_signature = selection_signature
        sync_style_to_active_layer(doc, layer)
        sync_layer_dropdown_to_selection(doc)


def ensure_layer_0(doc, force_active=False):
    if not doc:
        return

    l0 = next((o for o in doc.Objects if o.Label == "0" or o.Name == "Layer0"), None)

    if not l0:
        try:
            l0 = Draft.make_layer(name="Layer0")
            l0.Label = "0"
            doc.recompute()
        except Exception:
            return

    if l0 and hasattr(l0, "ViewObject") and l0.ViewObject:
        l0.ViewObject.LineColor = (1.0, 1.0, 1.0)
        if hasattr(l0.ViewObject, "LineWidth"):
            l0.ViewObject.LineWidth = 1.0

    toolbar_layer = None
    param_layer = None
    try:
        toolbar = getattr(Gui, 'draftToolBar', None)
        autogroup = getattr(toolbar, 'autogroup', None) if toolbar else None
        if autogroup:
            toolbar_layer = doc.getObject(autogroup)
    except Exception:
        toolbar_layer = None

    try:
        p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
        param_name = p.GetString("CurrentLayer", "")
        if param_name:
            param_layer = doc.getObject(param_name)
    except Exception:
        param_layer = None

    current_layer = toolbar_layer if _is_layer_container(toolbar_layer) else None
    if not current_layer and _is_layer_container(param_layer):
        current_layer = param_layer

    if force_active or not current_layer:
        current_layer = l0
        try:
            p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
            p.SetString("CurrentLayer", l0.Name)
        except Exception:
            pass

        if hasattr(Gui, 'draftToolBar'):
            try:
                if hasattr(Gui.draftToolBar, 'setAutoGroup'):
                    Gui.draftToolBar.setAutoGroup(l0.Name)
                elif hasattr(Gui.draftToolBar, 'autogroup'):
                    Gui.draftToolBar.autogroup = l0.Name
            except Exception:
                pass

    sync_style_to_active_layer(doc, current_layer or l0)
    sync_layer_dropdown_to_selection(doc)

class DocumentObserver:
    def slotCreatedDocument(self, doc):
        QtCore.QTimer.singleShot(500, lambda d=doc: ensure_layer_0(d, force_active=True))

    def slotActivateDocument(self, doc_ptr):
        try:
            doc = doc_ptr if not isinstance(doc_ptr, str) else App.getDocument(doc_ptr)
            if doc:
                delay = 750 if _is_restoring_state(doc=doc) else 0
                QtCore.QTimer.singleShot(delay, lambda d=doc: ensure_layer_0(d, force_active=True))
        except Exception:
            pass

    def slotCreatedObject(self, obj):
        if not obj or not hasattr(obj, "Name"):
            return

        doc = getattr(obj, "Document", None)
        if not doc or _is_restoring_state(obj, doc):
            return

        if obj.TypeId == "App::DocumentObjectGroup" or "Layer" in obj.TypeId or obj.Name.startswith("Layer"):
            def set_lw(doc_name, name):
                d = App.getDocument(doc_name) if doc_name else None
                o = d.getObject(name) if d else None
                if o and hasattr(o, "ViewObject") and o.ViewObject and hasattr(o.ViewObject, "LineWidth"):
                    o.ViewObject.LineWidth = 1.0

            QtCore.QTimer.singleShot(200, lambda dn=doc.Name, n=obj.Name: set_lw(dn, n))
            return

        if obj.Label == "0" or obj.Name.startswith("Layer") or "Group" in obj.TypeId:
            return
        if obj.TypeId in ('App::Origin', 'App::Line', 'App::Plane'):
            return

        obj_name = obj.Name
        doc_name = doc.Name
        for delay in (150, 500, 1000):
            QtCore.QTimer.singleShot(delay, lambda dn=doc_name, n=obj_name: self.move_to_active_layer(dn, n))

    def move_to_active_layer(self, doc_name, obj_name):
        doc = App.getDocument(doc_name) if doc_name else App.ActiveDocument
        if not doc or _is_restoring_state(doc=doc):
            return

        obj = doc.getObject(obj_name)
        if not obj or _is_restoring_state(obj, doc):
            return

        active_layer = get_active_layer(doc)
        target_layer = get_object_layer(obj) or active_layer
        if not target_layer or not hasattr(target_layer, "Group"):
            return

        objects_to_move = [obj]
        if hasattr(obj, "OutList"):
            for child in obj.OutList:
                if child and child.TypeId not in ('App::Origin', 'App::Plane', 'App::Line'):
                    objects_to_move.append(child)

        for item in objects_to_move:
            item_layer = get_object_layer(item)
            if item_layer and hasattr(item_layer, "Group"):
                _layer_add_object(item_layer, item)
            elif active_layer and hasattr(active_layer, "Group"):
                assign_to_layer(item, active_layer)


def tear_down():
    layoff_handler = getattr(Gui, 'ccad_layoff_handler', None)
    if layoff_handler:
        try:
            layoff_handler.cleanup(cancelled=True)
        except Exception:
            pass

    if hasattr(Gui, "ccad_layer_observer"):
        try:
            App.removeDocumentObserver(Gui.ccad_layer_observer)
        except Exception:
            pass
        try:
            del Gui.ccad_layer_observer
        except Exception:
            pass

    if hasattr(Gui, "ccad_layer_style_watcher"):
        try:
            Gui.ccad_layer_style_watcher.timer.stop()
            Gui.ccad_layer_style_watcher.deleteLater()
        except Exception:
            pass
        try:
            del Gui.ccad_layer_style_watcher
        except Exception:
            pass

    try:
        from draftguitools import gui_setstyle, gui_groups

        toolbar = getattr(Gui, 'draftToolBar', None)
        tb_cls = toolbar.__class__ if toolbar else None
        if tb_cls and 'draftToolBar.setAutoGroup' in _PATCHED_ORIGINALS:
            tb_cls.setAutoGroup = _PATCHED_ORIGINALS['draftToolBar.setAutoGroup']
            if hasattr(tb_cls, '_ccad_layer_sync_patched'):
                delattr(tb_cls, '_ccad_layer_sync_patched')

        if hasattr(gui_setstyle, 'Draft_SetStyle') and 'Draft_SetStyle.Activated' in _PATCHED_ORIGINALS:
            gui_setstyle.Draft_SetStyle.Activated = _PATCHED_ORIGINALS['Draft_SetStyle.Activated']
            if hasattr(gui_setstyle.Draft_SetStyle, '_ccad_patched'):
                delattr(gui_setstyle.Draft_SetStyle, '_ccad_patched')

        if hasattr(gui_setstyle, 'Draft_SetStyle_TaskPanel'):
            panel_cls = gui_setstyle.Draft_SetStyle_TaskPanel
            for key, attr in (
                ('Draft_SetStyle_TaskPanel.__init__', '__init__'),
                ('Draft_SetStyle_TaskPanel.loadDefaults', 'loadDefaults'),
                ('Draft_SetStyle_TaskPanel.accept', 'accept'),
                ('Draft_SetStyle_TaskPanel.reject', 'reject'),
            ):
                if key in _PATCHED_ORIGINALS:
                    setattr(panel_cls, attr, _PATCHED_ORIGINALS[key])
            if hasattr(panel_cls, '_ccad_patched'):
                delattr(panel_cls, '_ccad_patched')

        if hasattr(gui_groups, 'SetAutoGroup') and 'SetAutoGroup.proceed' in _PATCHED_ORIGINALS:
            gui_groups.SetAutoGroup.proceed = _PATCHED_ORIGINALS['SetAutoGroup.proceed']
            if hasattr(gui_groups.SetAutoGroup, '_ccad_layer_sync_patched'):
                delattr(gui_groups.SetAutoGroup, '_ccad_layer_sync_patched')
    except Exception:
        pass

    _PATCHED_ORIGINALS.clear()
    if hasattr(Gui, 'ccad_style_task_panel'):
        Gui.ccad_style_task_panel = None

def setup():
    tear_down()

    Gui.ccad_layer_observer = DocumentObserver()
    App.addDocumentObserver(Gui.ccad_layer_observer)
    Gui.ccad_layer_style_watcher = LayerStyleWatcher(Gui.getMainWindow())
    _patch_runtime_hooks()

    # Εκκίνηση: Εξασφάλιση και ενεργοποίηση του Layer 0 με καθυστέρηση για να είναι έτοιμο το UI
    if App.ActiveDocument:
        QtCore.QTimer.singleShot(1000, lambda: ensure_layer_0(App.ActiveDocument, force_active=True))

setup()

if __name__ == "__main__":
    setup()