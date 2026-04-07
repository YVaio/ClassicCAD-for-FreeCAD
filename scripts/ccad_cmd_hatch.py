import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore, QtWidgets
from draftguitools.gui_hatch import Draft_Hatch_TaskPanel

import ccad_cmd_xline
import ccad_layers
import ccad_selection


_HELPER_PREFIX = "CCAD_HatchBase"
_PROP_GROUP = "ClassicCAD"
_HELPER_FLAG_PROP = "CCADIsHatchHelper"
_HELPER_OWNER_PROP = "CCADHelperOwner"
_HATCH_HELPERS_PROP = "CCADHelperBases"


def _msg(console, text, color="#aaa"):
    if console and hasattr(console, "history"):
        console.history.append(f"<span style='color:{color};'>{text}</span>")
    else:
        App.Console.PrintMessage(text + "\n")


def _warn(console, text):
    if console and hasattr(console, "history"):
        console.history.append(f"<span style='color:#ff5555;'>{text}</span>")
    else:
        App.Console.PrintWarning(text + "\n")


def _screen_pos(event):
    return event.position().toPoint() if hasattr(event, "position") else event.pos()


def _snap_coords(pos):
    return [pos.x(), pos.y()]


def _get_3d_point(pos):
    try:
        snapped = Gui.Snapper.snap(_snap_coords(pos))
        if snapped is not None:
            point = snapped[0] if isinstance(snapped, tuple) else snapped
            if point is not None:
                return point
    except Exception:
        pass

    try:
        return Gui.activeView().getPoint(pos.x(), pos.y())
    except Exception:
        return None


def _is_hatch_object(obj):
    proxy = getattr(obj, "Proxy", None)
    if getattr(proxy, "Type", "") == "Hatch":
        return True
    return all(hasattr(obj, name) for name in ("Base", "File", "Pattern", "Scale", "Rotation"))


def _is_helper_object(obj):
    if not obj:
        return False
    if bool(getattr(obj, _HELPER_FLAG_PROP, False)):
        return True
    return bool(getattr(obj, "Name", "").startswith(_HELPER_PREFIX))


def _ensure_property(obj, prop_type, name, description):
    if not obj or hasattr(obj, name):
        return
    try:
        obj.addProperty(prop_type, name, _PROP_GROUP, description)
    except Exception:
        pass


def _mark_helper_object(obj):
    if not obj:
        return
    _ensure_property(obj, "App::PropertyBool", _HELPER_FLAG_PROP, "ClassicCAD hatch helper")
    _ensure_property(obj, "App::PropertyString", _HELPER_OWNER_PROP, "Owning hatch object")
    try:
        setattr(obj, _HELPER_FLAG_PROP, True)
    except Exception:
        pass
    try:
        if not getattr(obj, _HELPER_OWNER_PROP, ""):
            setattr(obj, _HELPER_OWNER_PROP, "")
    except Exception:
        pass


def _helper_names_from_value(value):
    if isinstance(value, str):
        return [name for name in value.split(";") if name]
    try:
        return [str(name) for name in list(value or []) if name]
    except Exception:
        return []


def _helper_names_for_hatch(hatch):
    names = set(_helper_names_from_value(getattr(hatch, _HATCH_HELPERS_PROP, [])))
    base = getattr(hatch, "Base", None)
    if _is_helper_object(base):
        names.add(base.Name)
    return sorted(names)


def _link_helpers_to_hatches(hatches, helper_names):
    names = [name for name in helper_names or [] if name]
    if not names:
        return

    for hatch in hatches or []:
        if not hatch:
            continue
        _ensure_property(hatch, "App::PropertyStringList", _HATCH_HELPERS_PROP, "ClassicCAD hatch helpers")
        try:
            setattr(hatch, _HATCH_HELPERS_PROP, list(names))
        except Exception:
            pass

        doc = getattr(hatch, "Document", None)
        for name in names:
            helper = doc.getObject(name) if doc else None
            if not helper:
                continue
            _mark_helper_object(helper)
            try:
                setattr(helper, _HELPER_OWNER_PROP, hatch.Name)
            except Exception:
                pass
            _hide_helper(helper)


def _iter_selected_objects(selection=None):
    current = list(selection) if selection is not None else list(Gui.Selection.getSelectionEx() or Gui.Selection.getSelection() or [])
    seen = set()
    for item in current:
        obj = getattr(item, "Object", None) or item
        name = getattr(obj, "Name", None)
        if not obj or not name or name in seen:
            continue
        seen.add(name)
        yield obj


def _selection_records():
    records = []
    try:
        for rec in Gui.Selection.getSelectionEx() or []:
            obj_name = getattr(rec, "ObjectName", "")
            if obj_name:
                records.append((getattr(rec, "DocumentName", ""), obj_name))
    except Exception:
        pass
    return records


def _restore_selection(records):
    blocker = getattr(Gui, "ccad_auto_blocker", None)
    if blocker:
        blocker._opening_grips = True

    try:
        Gui.Selection.clearSelection()
    except Exception:
        pass

    doc = App.ActiveDocument
    for doc_name, obj_name in records or []:
        try:
            target_doc = App.getDocument(doc_name) if doc_name else doc
        except Exception:
            target_doc = doc
        if target_doc and target_doc.getObject(obj_name):
            try:
                Gui.Selection.addSelection(doc_name or target_doc.Name, obj_name)
            except Exception:
                pass

    if blocker:
        blocker._opening_grips = False


def _close_edit_grips_preserve_selection():
    records = _selection_records()
    active_cmd = getattr(App, "activeDraftCommand", None)
    cls_name = active_cmd.__class__.__name__ if active_cmd else ""
    if "Edit" not in cls_name:
        return

    blocker = getattr(Gui, "ccad_auto_blocker", None)
    if blocker:
        blocker._opening_grips = True
        blocker._gripped_objects = []
        blocker._suppress_until = max(getattr(blocker, "_suppress_until", 0.0), time.time() + 0.35)

    try:
        Gui.Control.closeDialog()
    except Exception:
        pass

    _restore_selection(records)


def _iter_visible_shape_objects(doc):
    for obj in getattr(doc, "Objects", []) or []:
        try:
            if _is_helper_object(obj) or _is_hatch_object(obj) or ccad_cmd_xline.is_xline(obj):
                continue
            if not hasattr(obj, "ViewObject") or not obj.ViewObject.Visibility:
                continue
            if not hasattr(obj, "Shape") or obj.Shape.isNull():
                continue
            yield obj
        except Exception:
            pass


def _is_planar_face(face):
    try:
        return bool(face and face.findPlane())
    except Exception:
        return False


def _planar_faces_from_shape(shape):
    faces = []
    for face in getattr(shape, "Faces", []) or []:
        if _is_planar_face(face):
            try:
                faces.append(face.copy())
            except Exception:
                faces.append(face)
    return faces


def _closed_wires_from_edges(edges):
    import Part

    if not edges:
        return []

    try:
        groups = Part.sortEdges(edges)
    except Exception:
        groups = [edges]

    wires = []
    for group in groups or []:
        if not group:
            continue
        try:
            wire = Part.Wire(group)
        except Exception:
            continue
        try:
            if wire.isClosed():
                wires.append(wire)
        except Exception:
            pass
    return wires


def _faces_from_wires(wires):
    import Part

    if not wires:
        return []

    for maker in ("Part::FaceMakerBullseye", "Part::FaceMakerCheese", "Part::FaceMakerSimple"):
        try:
            result = Part.makeFace(wires, maker)
        except Exception:
            continue

        faces = list(getattr(result, "Faces", []) or [])
        if not faces and getattr(result, "ShapeType", "") == "Face":
            faces = [result]

        planar = [face.copy() if hasattr(face, "copy") else face for face in faces if _is_planar_face(face)]
        if planar:
            return planar

    faces = []
    for wire in wires:
        try:
            face = Part.Face(wire)
        except Exception:
            continue
        if _is_planar_face(face):
            faces.append(face.copy() if hasattr(face, "copy") else face)
    return faces


def _faces_from_edges(edges):
    return _faces_from_wires(_closed_wires_from_edges(edges))


def _preferred_layer(source_objects):
    doc = App.ActiveDocument
    for obj in source_objects or []:
        if not obj:
            continue
        try:
            layer = ccad_layers.get_object_layer(obj)
        except Exception:
            layer = None
        if layer:
            return layer
    try:
        return ccad_layers.get_active_layer(doc)
    except Exception:
        return None


def _assign_layer(obj, layer):
    if not obj or not layer:
        return False
    try:
        return bool(ccad_layers.assign_to_layer(obj, layer))
    except Exception:
        return False


def _hide_helper(obj):
    _mark_helper_object(obj)
    try:
        if hasattr(obj, "ViewObject") and obj.ViewObject:
            obj.ViewObject.Visibility = False
            if hasattr(obj.ViewObject, "Transparency"):
                obj.ViewObject.Transparency = 100
            if hasattr(obj.ViewObject, "Selectable"):
                obj.ViewObject.Selectable = False
    except Exception:
        pass


def _create_helper_base(faces, source_objects):
    import Part

    doc = App.ActiveDocument
    if not doc or not faces:
        return None, [], _preferred_layer(source_objects)

    helper_name = doc.getUniqueObjectName(_HELPER_PREFIX)
    helper = doc.addObject("Part::Feature", helper_name)
    helper.Label = "Hatch Boundary"
    _mark_helper_object(helper)
    try:
        setattr(helper, _HELPER_OWNER_PROP, "")
    except Exception:
        pass

    if len(faces) == 1:
        helper.Shape = faces[0].copy() if hasattr(faces[0], "copy") else faces[0]
    else:
        helper.Shape = Part.makeCompound([face.copy() if hasattr(face, "copy") else face for face in faces])

    layer = _preferred_layer(source_objects)
    _assign_layer(helper, layer)
    doc.recompute()
    _hide_helper(helper)
    return helper, [helper.Name], layer


def _can_use_object_directly(obj):
    try:
        if not obj or not obj.isDerivedFrom("Part::Feature"):
            return False
    except Exception:
        return False

    shape = getattr(obj, "Shape", None)
    if not shape or shape.isNull():
        return False

    planar_faces = _planar_faces_from_shape(shape)
    return len(getattr(shape, "Faces", []) or []) == 1 and len(planar_faces) == 1


def _collect_faces_from_objects(objects):
    faces = []
    loose_edges = []

    for obj in objects or []:
        shape = getattr(obj, "Shape", None)
        if not shape or shape.isNull():
            continue

        planar = _planar_faces_from_shape(shape)
        if planar:
            faces.extend(planar)
        else:
            loose_edges.extend(list(getattr(shape, "Edges", []) or []))

    if loose_edges:
        faces.extend(_faces_from_edges(loose_edges))

    return faces


def _build_base_from_objects(objects):
    source_objects = [obj for obj in objects or [] if obj]
    if not source_objects:
        return None, [], None, "HATCH: Select closed objects or boundaries first."

    if len(source_objects) == 1 and _can_use_object_directly(source_objects[0]):
        return source_objects[0], [], _preferred_layer(source_objects), None

    faces = _collect_faces_from_objects(source_objects)
    if not faces:
        return None, [], None, "HATCH: Selected objects do not form a closed planar boundary."

    helper, helper_names, layer = _create_helper_base(faces, source_objects)
    if not helper:
        return None, [], layer, "HATCH: Could not prepare a hatch boundary."

    return helper, helper_names, layer, None


def _project_point_to_face(face, point):
    try:
        plane = face.findPlane()
    except Exception:
        plane = None
    if not plane:
        return point

    origin = getattr(plane, "Position", None)
    axis = getattr(plane, "Axis", None) or getattr(plane, "Normal", None)
    if origin is None or axis is None:
        return point

    normal = App.Vector(axis)
    if normal.Length < 1e-9:
        return point
    normal.normalize()
    distance = (point - App.Vector(origin)).dot(normal)
    return point - (normal * distance)


def _face_contains_point(face, point):
    test_point = _project_point_to_face(face, point)
    for tol in (0.01, 0.1):
        try:
            if face.isInside(test_point, tol, True):
                return True
        except Exception:
            pass
    return False


def _point_face_candidates(doc):
    candidates = []
    objects = list(_iter_visible_shape_objects(doc))
    all_edges = []

    for obj in objects:
        planar = _planar_faces_from_shape(obj.Shape)
        if planar:
            for face in planar:
                candidates.append((face, obj))
        all_edges.extend(list(getattr(obj.Shape, "Edges", []) or []))

    for face in _faces_from_edges(all_edges):
        candidates.append((face, None))

    for face in _void_faces_from_objects(objects):
        candidates.append((face, None))

    return candidates


def _void_faces_from_objects(objects):
    import Part

    planar_faces = []
    bounds = []
    for obj in objects or []:
        shape = getattr(obj, "Shape", None)
        if not shape or shape.isNull():
            continue
        planar_faces.extend(_planar_faces_from_shape(shape))
        bbox = getattr(shape, "BoundBox", None)
        if bbox:
            bounds.append(bbox)

    if not planar_faces or not bounds:
        return []

    min_x = min(bbox.XMin for bbox in bounds)
    min_y = min(bbox.YMin for bbox in bounds)
    max_x = max(bbox.XMax for bbox in bounds)
    max_y = max(bbox.YMax for bbox in bounds)
    min_z = min(bbox.ZMin for bbox in bounds)
    span = max(max_x - min_x, max_y - min_y, 1.0)
    pad = (span * 0.05) + 1.0

    try:
        outer_wire = Part.makePolygon([
            App.Vector(min_x - pad, min_y - pad, min_z),
            App.Vector(max_x + pad, min_y - pad, min_z),
            App.Vector(max_x + pad, max_y + pad, min_z),
            App.Vector(min_x - pad, max_y + pad, min_z),
            App.Vector(min_x - pad, min_y - pad, min_z),
        ])
        outer_face = Part.Face(outer_wire)
        occupancy = Part.makeCompound([
            face.copy() if hasattr(face, "copy") else face for face in planar_faces
        ])
        cut_shape = outer_face.cut(occupancy)
    except Exception:
        return []

    faces = _planar_faces_from_shape(cut_shape)
    cut_edges = list(getattr(cut_shape, "Edges", []) or [])
    if cut_edges:
        faces.extend(_faces_from_edges(cut_edges))
    return faces


def _build_base_from_point(point):
    doc = App.ActiveDocument
    if not doc:
        return None, [], None, "HATCH: No active document."

    best = None
    for face, source in _point_face_candidates(doc):
        if not _face_contains_point(face, point):
            continue
        area = abs(float(getattr(face, "Area", 0.0) or 0.0))
        score = area if area > 0.0 else 1e30
        if best is None or score < best[0]:
            best = (score, face, source)

    if best is None:
        return None, [], None, "HATCH: Could not find a closed boundary at that point."

    _score, face, source = best
    if source and _can_use_object_directly(source):
        return source, [], _preferred_layer([source]), None

    helper, helper_names, layer = _create_helper_base([face], [source] if source else [])
    if not helper:
        return None, [], layer, "HATCH: Could not prepare a hatch boundary from that point."

    return helper, helper_names, layer, None


def _delete_objects(names):
    doc = App.ActiveDocument
    if not doc:
        return
    for name in names or []:
        try:
            if doc.getObject(name):
                doc.removeObject(name)
        except Exception:
            pass
    try:
        doc.recompute()
    except Exception:
        pass


def cleanup_orphan_helpers(doc=None):
    try:
        docs = [doc] if doc else list((App.listDocuments() or {}).values())
    except Exception:
        docs = [doc] if doc else [getattr(App, "ActiveDocument", None)]

    for target in [item for item in docs if item]:
        referenced = set()
        for obj in getattr(target, "Objects", []) or []:
            if not _is_hatch_object(obj):
                continue
            referenced.update(_helper_names_for_hatch(obj))

        stale = []
        for obj in getattr(target, "Objects", []) or []:
            if not _is_helper_object(obj):
                continue
            _hide_helper(obj)
            if obj.Name not in referenced:
                stale.append(obj.Name)

        if not stale:
            continue

        for name in stale:
            try:
                if target.getObject(name):
                    target.removeObject(name)
            except Exception:
                pass

        try:
            target.recompute()
        except Exception:
            pass


class _HatchHelperObserver(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self._doc_names = set()
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._flush)

    def _schedule(self, doc=None):
        doc_name = getattr(doc, "Name", "") or getattr(getattr(App, "ActiveDocument", None), "Name", "")
        if doc_name:
            self._doc_names.add(doc_name)
        self._timer.start(120)

    def _flush(self):
        docs = []
        for doc_name in list(self._doc_names):
            try:
                target = App.getDocument(doc_name)
            except Exception:
                target = None
            if target:
                docs.append(target)
        self._doc_names.clear()
        if not docs and getattr(App, "ActiveDocument", None):
            docs = [App.ActiveDocument]
        for doc in docs:
            cleanup_orphan_helpers(doc)

    def slotCreatedObject(self, obj):
        if _is_helper_object(obj):
            _hide_helper(obj)
            return
        if _is_hatch_object(obj):
            self._schedule(getattr(obj, "Document", None))

    def slotDeletedObject(self, obj):
        self._schedule(getattr(obj, "Document", None))

    def slotChangedObject(self, obj, prop):
        if _is_helper_object(obj):
            if prop == "Visibility":
                _hide_helper(obj)
            return
        if prop in ("Base", _HATCH_HELPERS_PROP, "Visibility") and _is_hatch_object(obj):
            self._schedule(getattr(obj, "Document", None))


def _draft_hatch_names(doc, baseobj=None):
    names = set()
    for obj in getattr(doc, "Objects", []) or []:
        if not _is_hatch_object(obj):
            continue
        if baseobj is not None and getattr(obj, "Base", None) != baseobj:
            continue
        names.add(obj.Name)
    return names


class _ClassicCADHatchTaskPanel(Draft_Hatch_TaskPanel):
    def __init__(self, baseobj, helper_names=None, layer=None):
        super().__init__(baseobj)
        self._helper_names = list(helper_names or [])
        self._layer = layer
        self._accepted = False
        self._before = _draft_hatch_names(baseobj.Document, baseobj)

    def accept(self):
        self._accepted = True
        super().accept()

        created = []
        doc = getattr(self.baseobj, "Document", None)
        if doc:
            after = _draft_hatch_names(doc, self.baseobj)
            created = [doc.getObject(name) for name in sorted(after - self._before) if doc.getObject(name)]

        if created:
            for hatch in created:
                _assign_layer(hatch, self._layer)
            _link_helpers_to_hatches(created, self._helper_names)
            cleanup_orphan_helpers(doc)
        elif self._helper_names:
            _delete_objects(self._helper_names)

        return True

    def reject(self):
        result = super().reject()
        if not self._accepted and self._helper_names:
            _delete_objects(self._helper_names)
        else:
            cleanup_orphan_helpers(getattr(self.baseobj, "Document", None))
        return result


class HatchHandler(QtCore.QObject):
    def __init__(self, console, viewport):
        super().__init__(viewport)
        self.console = console
        self.viewport = viewport
        self.mode = "select" if Gui.Selection.getSelection() else "point"
        self._saved_suppress_until = 0.0

        Gui.ccad_hatch_handler = self
        self._suspend_auto_grips(True)
        if self.viewport:
            self.viewport.installEventFilter(self)
        self._prompt()

    def _suspend_auto_grips(self, enabled):
        blocker = getattr(Gui, "ccad_auto_blocker", None)
        if not blocker:
            return
        if enabled:
            self._saved_suppress_until = getattr(blocker, "_suppress_until", 0.0)
            blocker._suppress_until = max(self._saved_suppress_until, time.time() + 3600.0)
        else:
            blocker._suppress_until = max(self._saved_suppress_until, time.time() + 0.2)

    def _prompt(self):
        if self.mode == "select":
            count = len(Gui.Selection.getSelection())
            suffix = f" ({count} selected)" if count else ""
            _msg(
                self.console,
                f"HATCH: Select objects{suffix} and press Enter. Type P for internal point or Esc to cancel.",
            )
        else:
            _msg(
                self.console,
                "HATCH: Click an internal point. Type S for object selection or Esc to cancel.",
            )

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.MouseMove and self.mode == "point":
            try:
                Gui.Snapper.snap(_snap_coords(_screen_pos(event)))
            except Exception:
                pass
            return False

        if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            if self.mode != "point":
                return False

            point = _get_3d_point(_screen_pos(event))
            if point is None:
                _warn(self.console, "HATCH: Could not resolve the clicked point.")
                return True

            self._launch_from_point(point)
            return True

        if event.type() == QtCore.QEvent.KeyPress:
            if event.key() == QtCore.Qt.Key_Escape:
                ccad_selection.force_cancel_interaction(console=self.console, clear_console_input=True, log=True)
                return True

            if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and self.mode == "select":
                self._launch_from_selection()
                return True

        return False

    def _on_input(self):
        text = self.console.input.text().strip().upper()
        self.console.input.clear()

        if text in ("C", "CANCEL"):
            ccad_selection.force_cancel_interaction(console=self.console, clear_console_input=True, log=True)
            return True

        if text in ("S", "SELECT", "OBJECT", "OBJECTS"):
            self.mode = "select"
            self._prompt()
            return True

        if text in ("P", "POINT", "PICK", "PICKPOINT", "PICKPOINTS"):
            self.mode = "point"
            self._prompt()
            return True

        if text == "":
            if self.mode == "select":
                self._launch_from_selection()
            else:
                self._prompt()
            return True

        _warn(self.console, "HATCH: Use Enter, S, P, or Esc.")
        return True

    def _launch_from_selection(self):
        objects = list(_iter_selected_objects())
        baseobj, helper_names, layer, error = _build_base_from_objects(objects)
        if error:
            _warn(self.console, error)
            return False
        return self._show_task_panel(baseobj, helper_names, layer)

    def _launch_from_point(self, point):
        baseobj, helper_names, layer, error = _build_base_from_point(point)
        if error:
            _warn(self.console, error)
            return False
        return self._show_task_panel(baseobj, helper_names, layer)

    def _show_task_panel(self, baseobj, helper_names, layer):
        try:
            panel = _ClassicCADHatchTaskPanel(baseobj, helper_names=helper_names, layer=layer)
            task = Gui.Control.showDialog(panel)
            if task:
                try:
                    task.setDocumentName(Gui.ActiveDocument.Document.Name)
                except Exception:
                    pass
                try:
                    task.setAutoCloseOnDeletedDocument(True)
                except Exception:
                    pass
        except Exception as exc:
            _delete_objects(helper_names)
            _warn(self.console, f"HATCH: Could not open the Draft hatch panel ({exc})")
            return False

        _msg(self.console, "HATCH: Adjust pattern settings and confirm.", color="#55ff55")
        self.cleanup(clear_selection=False)
        return True

    def cleanup(self, clear_selection=False):
        if self.viewport:
            try:
                self.viewport.removeEventFilter(self)
            except Exception:
                pass
        self._suspend_auto_grips(False)
        Gui.ccad_hatch_handler = None
        if clear_selection:
            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass

    def _cleanup(self, cancelled=False):
        self.cleanup(clear_selection=bool(cancelled))


def run(console):
    cleanup_orphan_helpers(getattr(App, "ActiveDocument", None))

    existing = getattr(Gui, "ccad_hatch_handler", None)
    if existing:
        try:
            existing.cleanup()
        except Exception:
            pass

    active_cmd = getattr(App, "activeDraftCommand", None)
    cls_name = active_cmd.__class__.__name__ if active_cmd else ""
    other_interaction = False
    try:
        other_interaction = bool(Gui.Control.activeDialog())
    except Exception:
        other_interaction = False
    if hasattr(Gui, "ccad_sel_logic") and Gui.ccad_sel_logic:
        other_interaction = other_interaction or bool(getattr(Gui.ccad_sel_logic, "state", 0) == 1)
    if "Edit" in cls_name:
        _close_edit_grips_preserve_selection()
    elif active_cmd or other_interaction:
        ccad_selection.force_cancel_interaction(console=console, clear_console_input=False)

    viewport = getattr(getattr(Gui, "ccad_sel_logic", None), "viewport", None)
    if viewport is None:
        try:
            mw = Gui.getMainWindow()
            viewport = next(
                (
                    widget
                    for widget in mw.findChildren(QtWidgets.QWidget)
                    if "View3DInventor" in widget.metaObject().className() and widget.isVisible()
                ),
                None,
            )
        except Exception:
            viewport = None

    if viewport is None:
        _warn(console, "HATCH: No active 3D viewport found.")
        return

    HatchHandler(console, viewport)


def setup():
    observer = getattr(Gui, "ccad_hatch_helper_observer", None)
    if observer:
        try:
            App.removeDocumentObserver(observer)
        except Exception:
            pass

    Gui.ccad_hatch_helper_observer = _HatchHelperObserver()
    App.addDocumentObserver(Gui.ccad_hatch_helper_observer)
    QtCore.QTimer.singleShot(0, cleanup_orphan_helpers)


def tear_down():
    observer = getattr(Gui, "ccad_hatch_helper_observer", None)
    if not observer:
        return
    try:
        App.removeDocumentObserver(observer)
    except Exception:
        pass
    try:
        observer.deleteLater()
    except Exception:
        pass
    try:
        del Gui.ccad_hatch_helper_observer
    except Exception:
        pass