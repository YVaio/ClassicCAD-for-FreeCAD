"""Custom TRIM and EXTEND commands."""

import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore


def parse_vector(p):
    if p is None:
        return App.Vector(0, 0, 0)
    if hasattr(p, 'x') and hasattr(p, 'y'):
        try:
            return App.Vector(float(p.x), float(p.y), float(getattr(p, 'z', 0.0)))
        except Exception:
            return p
    if isinstance(p, (tuple, list)) and len(p) >= 2:
        z = p[2] if len(p) >= 3 else 0.0
        return App.Vector(float(p[0]), float(p[1]), float(z))
    return App.Vector(0, 0, 0)


def intersect_2d(a, b, c, d):
    x1, y1 = a.x, a.y
    x2, y2 = b.x, b.y
    x3, y3 = c.x, c.y
    x4, y4 = d.x, d.y

    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-9:
        return None

    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    return App.Vector(
        x1 + t * (x2 - x1),
        y1 + t * (y2 - y1),
        a.z + t * (b.z - a.z),
    )


def _edge_index(subname):
    if isinstance(subname, str) and subname.startswith('Edge'):
        try:
            return max(0, int(subname[4:]) - 1)
        except Exception:
            return 0
    return 0


def _to_world(obj, vec):
    try:
        if hasattr(obj, 'Placement') and obj.Placement:
            return obj.Placement.multVec(vec)
    except Exception:
        pass
    return vec


def _to_local(obj, vec):
    try:
        if hasattr(obj, 'Placement') and obj.Placement:
            return obj.Placement.inverse().multVec(vec)
    except Exception:
        pass
    return vec


def _get_points_target_info(obj, subname):
    points = list(getattr(obj, 'Points', []) or [])
    if len(points) < 2:
        return None

    idx = min(max(_edge_index(subname), 0), len(points) - 2)
    a_local = points[idx]
    b_local = points[idx + 1]
    return {
        'kind': 'points',
        'edge_index': idx,
        'a_world': _to_world(obj, a_local),
        'b_world': _to_world(obj, b_local),
    }


def _get_target_info(obj, subname):
    if hasattr(obj, 'Points'):
        info = _get_points_target_info(obj, subname)
        if info:
            return info

    if hasattr(obj, 'Start') and hasattr(obj, 'End'):
        return {
            'kind': 'start_end',
            'a_world': _to_world(obj, obj.Start),
            'b_world': _to_world(obj, obj.End),
        }

    if all(hasattr(obj, name) for name in ('X1', 'Y1', 'Z1', 'X2', 'Y2', 'Z2')):
        a = App.Vector(obj.X1, obj.Y1, obj.Z1)
        b = App.Vector(obj.X2, obj.Y2, obj.Z2)
        return {
            'kind': 'xyz_line',
            'a_world': _to_world(obj, a),
            'b_world': _to_world(obj, b),
        }

    return None


def _get_boundary_segment(obj, subname):
    info = _get_target_info(obj, subname)
    if info:
        return info['a_world'], info['b_world']

    try:
        edges = obj.Shape.Edges
        if not edges:
            return None
        idx = min(max(_edge_index(subname), 0), len(edges) - 1)
        edge = edges[idx]
        return _to_world(obj, edge.Vertexes[0].Point), _to_world(obj, edge.Vertexes[-1].Point)
    except Exception:
        return None


def _choose_endpoint(a_world, b_world, pick_world, intersection):
    try:
        if pick_world and pick_world.distanceToPoint(App.Vector(0, 0, 0)) > 1e-9:
            da = pick_world.distanceToPoint(a_world)
            db = pick_world.distanceToPoint(b_world)
            return 0 if da <= db else 1
    except Exception:
        pass

    da = intersection.distanceToPoint(a_world)
    db = intersection.distanceToPoint(b_world)
    return 0 if da <= db else 1


def _apply_target_point(obj, info, new_world_point, pick_world):
    end_index = _choose_endpoint(info['a_world'], info['b_world'], pick_world, new_world_point)
    new_local = _to_local(obj, new_world_point)

    if info['kind'] == 'points':
        pts = list(obj.Points)
        idx = info['edge_index']
        if end_index == 0:
            pts[idx] = new_local
        else:
            pts[idx + 1] = new_local
        obj.Points = pts
        return

    if info['kind'] == 'start_end':
        if end_index == 0:
            obj.Start = new_local
        else:
            obj.End = new_local
        return

    if info['kind'] == 'xyz_line':
        if end_index == 0:
            obj.X1, obj.Y1, obj.Z1 = new_local.x, new_local.y, new_local.z
        else:
            obj.X2, obj.Y2, obj.Z2 = new_local.x, new_local.y, new_local.z


class TrimExtendHandler:
    def __init__(self, console, mode):
        self.console = console
        self.mode = (mode or 'TRIM').upper()
        self.step = 0
        self.target_name = None
        self.target_sub = None
        self.target_pick = None
        self.boundary_name = None
        self.boundary_sub = None
        self.last_sel_time = time.time()
        self._txn_open = False

        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)
        Gui.ccad_trim_handler = self
        self._prompt()

    def _prompt(self):
        if self.step == 0:
            verb = 'trim' if self.mode == 'TRIM' else 'extend'
            self.console.history.append(
                f"<span style='color:#aaa;'>{self.mode}: Select object to {verb}.</span>"
            )
        elif self.step == 1:
            self.console.history.append(
                f"<span style='color:#aaa;'>{self.mode}: Select cutting boundary.</span>"
            )

    def _open_transaction(self, name='Trim/extend'):
        doc = App.ActiveDocument
        if doc and not self._txn_open:
            try:
                doc.openTransaction(name)
                self._txn_open = True
            except Exception:
                self._txn_open = False

    def _commit_transaction(self):
        doc = App.ActiveDocument
        if doc and self._txn_open:
            try:
                doc.commitTransaction()
            except Exception:
                pass
        self._txn_open = False

    def _abort_transaction(self):
        doc = App.ActiveDocument
        if doc and self._txn_open:
            try:
                doc.abortTransaction()
            except Exception:
                pass
        self._txn_open = False

    def addSelection(self, doc, obj_name, sub, pnt):
        now = time.time()
        if now - self.last_sel_time < 0.20:
            return
        self.last_sel_time = now

        subname = sub if sub and 'Edge' in sub else 'Edge1'
        pick = parse_vector(pnt)

        if self.step == 0:
            self.target_name = obj_name
            self.target_sub = subname
            self.target_pick = pick
            self.step = 1
            Gui.Selection.clearSelection()
            self._prompt()
            return

        if self.step == 1:
            if obj_name == self.target_name and subname == self.target_sub:
                Gui.Selection.clearSelection()
                return

            self.boundary_name = obj_name
            self.boundary_sub = subname
            Gui.Selection.clearSelection()
            self.step = 2
            QtCore.QTimer.singleShot(40, self._execute)

    def removeSelection(self, doc, obj_name, sub):
        pass

    def setSelection(self, doc):
        pass

    def clearSelection(self, doc):
        pass

    def _execute(self):
        target = App.ActiveDocument.getObject(self.target_name) if App.ActiveDocument else None
        boundary = App.ActiveDocument.getObject(self.boundary_name) if App.ActiveDocument else None

        self.cleanup(clear_selection=False)

        if not target or not boundary:
            self.console.history.append(
                f"<span style='color:#ff5555;'>{self.mode}: Invalid selection.</span>"
            )
            return

        target_info = _get_target_info(target, self.target_sub)
        boundary_seg = _get_boundary_segment(boundary, self.boundary_sub)

        if not target_info or not boundary_seg:
            self.console.history.append(
                f"<span style='color:#ff5555;'>{self.mode}: Only lines and wires are supported.</span>"
            )
            return

        intersection = intersect_2d(
            target_info['a_world'],
            target_info['b_world'],
            boundary_seg[0],
            boundary_seg[1],
        )
        if not intersection:
            self.console.history.append(
                f"<span style='color:#ff5555;'>{self.mode}: Objects are parallel or do not intersect.</span>"
            )
            return

        try:
            self._open_transaction('Trim/extend')
            _apply_target_point(target, target_info, intersection, self.target_pick)
            App.ActiveDocument.recompute()
            self._commit_transaction()
            self.console.history.append(
                f"<span style='color:#55ff55;'>{self.mode}: Done</span>"
            )
        except Exception as exc:
            self._abort_transaction()
            self.console.history.append(
                f"<span style='color:#ff5555;'>{self.mode} Error: {str(exc)}</span>"
            )
        finally:
            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass

    def cleanup(self, clear_selection=True):
        try:
            Gui.Selection.removeObserver(self)
        except Exception:
            pass
        self._abort_transaction()
        if clear_selection:
            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass
        Gui.ccad_trim_handler = None

    def _cleanup(self):
        self.cleanup()


def run(console, mode):
    if hasattr(Gui, 'ccad_trim_handler') and Gui.ccad_trim_handler:
        try:
            Gui.ccad_trim_handler.cleanup()
        except Exception:
            pass
    TrimExtendHandler(console, mode)