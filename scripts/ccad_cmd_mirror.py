import math
import time

import Draft
import FreeCAD as App
import FreeCADGui as Gui
import WorkingPlane

try:
    from PySide6 import QtCore, QtWidgets
except Exception:
    from PySide2 import QtCore, QtWidgets


_TOL = 1e-7
_PREF_GROUP = "User parameter:BaseApp/Preferences/Mod/ClassicCAD"


def _msg(console, text):
    if console and hasattr(console, "history"):
        console.history.append(text)
    else:
        App.Console.PrintMessage(text + "\n")


def _warn(console, text):
    if console and hasattr(console, "history"):
        console.history.append(text)
    else:
        App.Console.PrintWarning(text + "\n")


def _mirror_params():
    return App.ParamGet(_PREF_GROUP)


def _as_list(result):
    if result is None:
        return []
    if isinstance(result, list):
        return result
    return [result]


def _vector(value, fallback=None):
    if value is None:
        return App.Vector(fallback) if fallback is not None else App.Vector()
    return App.Vector(value)


def _normalized(vec, fallback=None):
    result = _vector(vec, fallback)
    if result.Length < _TOL:
        result = _vector(fallback if fallback is not None else App.Vector(0, 0, 1))
    if result.Length >= _TOL:
        result.normalize()
    return result


def _rotation_copy(selection, angle, center, axis, copy=False):
    result = Draft.rotate(selection, angle, center=center, axis=axis, copy=copy)
    objs = _as_list(result)
    if objs:
        return objs
    return [] if copy else list(selection)


def _scale_in_place(selection, scale, center):
    result = Draft.scale(selection, scale, center=center, copy=False)
    objs = _as_list(result)
    return objs or list(selection)


def _plane_alignment(axis):
    z_axis = App.Vector(0, 0, 1)
    axis = _normalized(axis, z_axis)
    rot_axis = axis.cross(z_axis)
    if rot_axis.Length < _TOL:
        if axis.dot(z_axis) < 0:
            return App.Vector(1, 0, 0), 180.0
        return App.Vector(), 0.0
    rot_axis.normalize()
    return rot_axis, math.degrees(axis.getAngle(z_axis))


def _rotate_vector(vec, axis, angle):
    if abs(angle) < 1e-6 or axis.Length < _TOL:
        return App.Vector(vec)
    return App.Rotation(axis, angle).multVec(vec)


def _line_alignment_angle(direction):
    if direction.Length < _TOL:
        return 0.0
    return math.degrees(math.atan2(direction.y, direction.x))


def _mirror_direction(mirror_obj, workplane_axis):
    normal = _normalized(getattr(mirror_obj, "Normal", None), App.Vector())
    if normal.Length < _TOL:
        raise ValueError("mirror plane normal is missing")

    direction = workplane_axis.cross(normal)
    if direction.Length < _TOL:
        raise ValueError("mirror axis could not be reconstructed")
    direction.normalize()
    return direction


def _independent_mirror(source, base, direction, workplane_axis):
    plane_axis, plane_angle = _plane_alignment(workplane_axis)
    copy_axis = plane_axis if plane_axis.Length >= _TOL else workplane_axis

    mirrored = _rotation_copy([source], plane_angle, base, copy_axis, copy=True)
    if not mirrored:
        return []

    aligned_direction = _rotate_vector(direction, plane_axis, plane_angle)
    line_angle = _line_alignment_angle(aligned_direction)

    if abs(line_angle) >= 1e-6:
        mirrored = _rotation_copy(mirrored, -line_angle, base, App.Vector(0, 0, 1), copy=False)

    mirrored = _scale_in_place(mirrored, App.Vector(1, -1, 1), base)

    if abs(line_angle) >= 1e-6:
        mirrored = _rotation_copy(mirrored, line_angle, base, App.Vector(0, 0, 1), copy=False)

    if abs(plane_angle) >= 1e-6:
        mirrored = _rotation_copy(mirrored, -plane_angle, base, plane_axis, copy=False)

    return mirrored


class _MirrorSession(QtCore.QObject):
    def __init__(self, console=None):
        parent = Gui.getMainWindow() if hasattr(Gui, "getMainWindow") else None
        super().__init__(parent)
        self.console = console
        self.doc = App.ActiveDocument
        self.known_names = set(obj.Name for obj in self.doc.Objects) if self.doc else set()
        self.pending_names = []
        self.last_active = time.time()
        self.keep_original = _mirror_params().GetBool("MirrorKeepOriginal", True)
        self._copy_option_initialized = False
        workplane = WorkingPlane.get_working_plane(update=False)
        self.workplane_axis = _normalized(getattr(workplane, "axis", None), App.Vector(0, 0, 1))
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(120)

    def stop(self):
        try:
            self.timer.stop()
        except Exception:
            pass
        if getattr(Gui, "ccad_mirror_session", None) is self:
            Gui.ccad_mirror_session = None

    def _mirror_is_active(self):
        cmd = getattr(App, "activeDraftCommand", None)
        feature_name = getattr(cmd, "featureName", "") if cmd else ""
        class_name = getattr(getattr(cmd, "__class__", None), "__name__", "") if cmd else ""
        if feature_name == "Mirror" or class_name == "Mirror":
            self._sync_copy_option()
            self.last_active = time.time()
            return True

        toolbar = getattr(Gui, "draftToolBar", None)
        source_cmd = getattr(toolbar, "sourceCmd", None) if toolbar else None
        if getattr(source_cmd, "featureName", "") == "Mirror":
            self._sync_copy_option()
            self.last_active = time.time()
            return True
        return False

    def _sync_copy_option(self):
        toolbar = getattr(Gui, "draftToolBar", None)
        checkbox = getattr(toolbar, "isCopy", None) if toolbar else None
        if not checkbox:
            return

        source_cmd = getattr(toolbar, "sourceCmd", None) if toolbar else None
        if source_cmd and not hasattr(source_cmd, "set_ghosts"):
            try:
                source_cmd.set_ghosts = lambda: None
            except Exception:
                pass

        try:
            checkbox.show()
            checkbox.setText("Copy source")
            checkbox.setToolTip(
                "If checked, keeps the original object; otherwise the original is deleted after mirroring."
            )
            if not self._copy_option_initialized:
                blocked = checkbox.blockSignals(True)
                checkbox.setChecked(bool(self.keep_original))
                checkbox.blockSignals(blocked)
                self._copy_option_initialized = True
            self.keep_original = bool(checkbox.isChecked())
            _mirror_params().SetBool("MirrorKeepOriginal", self.keep_original)
        except Exception:
            pass

    def _collect_pending(self):
        if not self.doc:
            return []
        pending = []
        for obj in self.doc.Objects:
            if obj.Name in self.known_names:
                continue
            self.known_names.add(obj.Name)
            if getattr(obj, "TypeId", "") == "Part::Mirroring":
                pending.append(obj.Name)
        return pending

    def _replace_pending(self):
        if not self.doc:
            return

        pending = []
        seen = set()
        for name in self.pending_names:
            if name not in seen:
                pending.append(name)
                seen.add(name)
        self.pending_names = []
        if not pending:
            return

        created_names = []
        deleted_sources = set()
        transaction_open = False
        try:
            if hasattr(self.doc, "openTransaction"):
                self.doc.openTransaction("ClassicCAD Mirror")
                transaction_open = True

            for name in pending:
                mirror_obj = self.doc.getObject(name)
                if not mirror_obj or getattr(mirror_obj, "TypeId", "") != "Part::Mirroring":
                    continue

                source = getattr(mirror_obj, "Source", None)
                if source is None:
                    _warn(self.console, "MIRROR: skipped mirrored object without source")
                    continue

                try:
                    base = _vector(getattr(mirror_obj, "Base", None), App.Vector())
                    direction = _mirror_direction(mirror_obj, self.workplane_axis)
                    mirrored = _independent_mirror(source, base, direction, self.workplane_axis)
                except Exception as exc:
                    _warn(self.console, f"MIRROR: could not create independent copy for {mirror_obj.Label} ({exc})")
                    continue

                if not mirrored:
                    _warn(self.console, f"MIRROR: no independent copy created for {mirror_obj.Label}")
                    continue

                for obj in mirrored:
                    if obj and getattr(obj, "Name", None):
                        created_names.append(obj.Name)

                try:
                    self.doc.removeObject(mirror_obj.Name)
                except Exception as exc:
                    _warn(self.console, f"MIRROR: created copy but could not remove linked mirror {mirror_obj.Label} ({exc})")

                if not self.keep_original:
                    source_name = getattr(source, "Name", None)
                    if source_name and source_name not in deleted_sources:
                        try:
                            if self.doc.getObject(source_name):
                                self.doc.removeObject(source_name)
                            deleted_sources.add(source_name)
                        except Exception as exc:
                            _warn(self.console, f"MIRROR: could not delete source object {source.Label} ({exc})")
        finally:
            if transaction_open and hasattr(self.doc, "commitTransaction"):
                try:
                    self.doc.commitTransaction()
                except Exception:
                    pass

        try:
            self.doc.recompute()
        except Exception:
            pass

        if created_names:
            try:
                Gui.Selection.clearSelection()
                for name in created_names:
                    Gui.Selection.addSelection(self.doc.Name, name)
            except Exception:
                pass
            suffix = "copy" if len(created_names) == 1 else "copies"
            _msg(self.console, f"MIRROR: created {len(created_names)} independent mirrored {suffix}")

    def _poll(self):
        if App.ActiveDocument is not self.doc:
            self.stop()
            return

        self.pending_names.extend(self._collect_pending())
        if self._mirror_is_active():
            return

        idle = time.time() - self.last_active
        if self.pending_names and idle >= 0.35:
            self._replace_pending()
            self.stop()
            return

        if not self.pending_names and idle >= 1.0:
            self.stop()


def _stop_session():
    session = getattr(Gui, "ccad_mirror_session", None)
    if session and hasattr(session, "stop"):
        try:
            session.stop()
        except Exception:
            pass


def run(console=None):
    _stop_session()
    Gui.ccad_mirror_session = _MirrorSession(console=console)

    try:
        Gui.getMainWindow().setFocus()
    except Exception:
        pass

    try:
        Gui.runCommand("Draft_Mirror", 0)
    except TypeError:
        Gui.runCommand("Draft_Mirror")
    except Exception as exc:
        _stop_session()
        _warn(console, f"MIRROR: could not start Draft Mirror ({exc})")
        return

    _msg(console, "MIRROR: Draft Mirror started (independent mirrored copies)")


def tear_down():
    _stop_session()