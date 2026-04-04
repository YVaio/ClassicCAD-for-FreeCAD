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


def _line_parameter(a, b, p):
    dx = b.x - a.x
    dy = b.y - a.y
    dz = b.z - a.z
    denom = dx * dx + dy * dy + dz * dz
    if denom < 1e-12:
        return 0.0
    return ((p.x - a.x) * dx + (p.y - a.y) * dy + (p.z - a.z) * dz) / denom


def _boundary_key(obj_name, subname):
    return (str(obj_name), _edge_index(subname))


def _find_best_intersection(doc, target_name, target_sub, target_info, pick_world, boundaries, mode):
    if not doc or not boundaries:
        return None

    a_world = target_info['a_world']
    b_world = target_info['b_world']
    end_index = _choose_endpoint(a_world, b_world, pick_world, a_world)
    target_key = _boundary_key(target_name, target_sub)
    best_score = None
    best_point = None
    eps = 1e-6

    for boundary in boundaries:
        obj_name = boundary['obj_name']
        subname = boundary['sub']
        if _boundary_key(obj_name, subname) == target_key:
            continue

        obj = doc.getObject(obj_name)
        if not obj:
            continue

        boundary_seg = _get_boundary_segment(obj, subname)
        if not boundary_seg:
            continue

        intersection = intersect_2d(a_world, b_world, boundary_seg[0], boundary_seg[1])
        if not intersection:
            continue

        t = _line_parameter(a_world, b_world, intersection)
        if mode == 'TRIM':
            if end_index == 0:
                if not (eps < t <= 1.0 + eps):
                    continue
                score = abs(t)
            else:
                if not (-eps <= t < 1.0 - eps):
                    continue
                score = abs(1.0 - t)
        else:
            if end_index == 0:
                if not (t < -eps):
                    continue
                score = abs(t)
            else:
                if not (t > 1.0 + eps):
                    continue
                score = abs(t - 1.0)

        if best_score is None or score < best_score:
            best_score = score
            best_point = intersection

    return best_point


class TrimExtendHandler:
    def __init__(self, console, mode):
        self.console = console
        self.mode = (mode or 'TRIM').upper()
        self.step = 0
        self.boundaries = []
        self.last_sel_time = time.time()
        self._txn_open = False

        preselected = []
        try:
            preselected = list(Gui.Selection.getSelectionEx())
        except Exception:
            preselected = []

        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)
        Gui.ccad_trim_handler = self

        if preselected:
            for sel in preselected:
                obj_name = getattr(sel, 'ObjectName', None)
                if not obj_name:
                    continue
                subnames = list(getattr(sel, 'SubElementNames', []) or ['Edge1'])
                for subname in subnames:
                    if 'Edge' in str(subname):
                        self._add_boundary(obj_name, str(subname), silent=True)
            if self.boundaries:
                self.console.history.append(
                    f"<span style='color:#aaa;'>{self.mode}: {len(self.boundaries)} cutting edge(s) preselected. Press Enter to continue or select more.</span>"
                )

        self._prompt()

    def _prompt(self):
        if self.step == 0:
            count = len(self.boundaries)
            suffix = f" ({count} selected)" if count else ""
            self.console.history.append(
                f"<span style='color:#aaa;'>{self.mode}: Select cutting edges{suffix}. Press Enter when done or Esc to cancel.</span>"
            )
        elif self.step == 1:
            verb = 'trim' if self.mode == 'TRIM' else 'extend'
            self.console.history.append(
                f"<span style='color:#aaa;'>{self.mode}: Select object to {verb}. Click more objects to continue; press Enter or Esc to finish.</span>"
            )

    def _add_boundary(self, obj_name, subname, silent=False):
        key = _boundary_key(obj_name, subname)
        for boundary in self.boundaries:
            if _boundary_key(boundary['obj_name'], boundary['sub']) == key:
                return False

        self.boundaries.append({'obj_name': obj_name, 'sub': subname})
        if not silent:
            self.console.history.append(
                f"<span style='color:#55ff55;'>{self.mode}: Cutting edge added ({len(self.boundaries)} total).</span>"
            )
        return True

    def _on_input(self):
        text = self.console.input.text().strip().upper()
        self.console.input.clear()

        if text in ('C', 'CANCEL'):
            self.console.history.append(
                f"<span style='color:#aaa;'>{self.mode}: Cancelled</span>"
            )
            self.cleanup()
            return True

        if self.step == 0:
            if text == '':
                if not self.boundaries:
                    self.console.history.append(
                        f"<span style='color:#ff5555;'>{self.mode}: Select at least one cutting edge first.</span>"
                    )
                else:
                    self.step = 1
                    try:
                        Gui.Selection.clearSelection()
                    except Exception:
                        pass
                    self._prompt()
                return True
            return False

        if self.step == 1 and text == '':
            self.console.history.append(
                f"<span style='color:#aaa;'>{self.mode}: Finished</span>"
            )
            self.cleanup()
            return True

        return False

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
            self._add_boundary(obj_name, subname)
            return

        if self.step == 1:
            QtCore.QTimer.singleShot(
                40,
                lambda name=obj_name, edge=subname, picked=pick: self._execute_target(name, edge, picked),
            )
            try:
                Gui.Selection.clearSelection()
            except Exception:
                pass

    def removeSelection(self, doc, obj_name, sub):
        pass

    def setSelection(self, doc):
        pass

    def clearSelection(self, doc):
        pass

    def _execute_target(self, target_name, target_sub, target_pick):
        doc = App.ActiveDocument
        target = doc.getObject(target_name) if doc else None

        if not target or not self.boundaries:
            self.console.history.append(
                f"<span style='color:#ff5555;'>{self.mode}: Invalid selection.</span>"
            )
            return

        target_info = _get_target_info(target, target_sub)
        if not target_info:
            self.console.history.append(
                f"<span style='color:#ff5555;'>{self.mode}: Only lines and wires are supported.</span>"
            )
            return

        intersection = _find_best_intersection(
            doc,
            target_name,
            target_sub,
            target_info,
            target_pick,
            self.boundaries,
            self.mode,
        )
        if not intersection:
            self.console.history.append(
                f"<span style='color:#ff5555;'>{self.mode}: No valid cutting edge found for that side.</span>"
            )
            return

        try:
            self._open_transaction('Trim/extend')
            _apply_target_point(target, target_info, intersection, target_pick)
            doc.recompute()
            self._commit_transaction()
            self.console.history.append(
                f"<span style='color:#55ff55;'>{self.mode}: Done</span>"
            )
        except Exception as exc:
            self._abort_transaction()
            self.console.history.append(
                f"<span style='color:#ff5555;'>{self.mode} Error: {str(exc)}</span>"
            )

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