"""CHAMFER command — AutoCAD-style chamfer with persistent distance settings."""

import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore
import time

# ── Geometry helpers (shared logic mirrors ccad_cmd_fillet) ──────────────────

def _get_endpoints(obj):
    if hasattr(obj, 'Start') and hasattr(obj, 'End'):
        return obj.Start, obj.End
    if hasattr(obj, 'Points') and len(obj.Points) >= 2:
        return obj.Points[0], obj.Points[-1]
    return None, None

def _set_endpoints(obj, start_pt, end_pt):
    if hasattr(obj, 'Start') and hasattr(obj, 'End'):
        obj.Start = start_pt
        obj.End = end_pt
    elif hasattr(obj, 'Points'):
        pts = list(obj.Points)
        pts[0] = start_pt
        pts[-1] = end_pt
        obj.Points = pts

def _parse_vector(p):
    if p is None:
        return App.Vector(0, 0, 0)
    if hasattr(p, 'x'):
        return p
    if isinstance(p, (tuple, list)) and len(p) >= 3:
        return App.Vector(p[0], p[1], p[2])
    return App.Vector(0, 0, 0)

def _intersect_2d(A, B, C, D):
    x1, y1 = A.x, A.y
    x2, y2 = B.x, B.y
    x3, y3 = C.x, C.y
    x4, y4 = D.x, D.y
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-9:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    return App.Vector(
        x1 + t * (x2 - x1),
        y1 + t * (y2 - y1),
        A.z + t * (B.z - A.z),
    )

def _dist(a, b):
    return (a - b).Length

def _nearest_end(pt, A, B):
    """Return whichever of A or B is closer to pt, and the other."""
    if _dist(pt, A) <= _dist(pt, B):
        return A, B   # nearest, far
    return B, A

def _point_along(near, far, d):
    """Walk distance d from near towards far along the line."""
    seg = far - near
    length = seg.Length
    if length < 1e-9:
        return near
    return near + seg * (d / length)


# ── Handler ──────────────────────────────────────────────────────────────────

class ChamferHandler:
    def __init__(self, console):
        self.console = console
        self.step = 0
        self._waiting_dist = None   # 'D1' or 'D2'
        self._txn_open = False

        self.obj1 = None
        self.sub1 = None
        self.pnt1 = None

        self.obj2 = None
        self.sub2 = None
        self.pnt2 = None

        self.last_sel_time = 0.0
        self._last_sel_key = None

        if not hasattr(Gui, 'ccad_chamfer_d1'):
            Gui.ccad_chamfer_d1 = 0.0
        if not hasattr(Gui, 'ccad_chamfer_d2'):
            Gui.ccad_chamfer_d2 = 0.0

        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)
        Gui.ccad_chamfer_handler = self
        self._prompt()

    # ── prompts ──

    def _d_str(self):
        d1, d2 = Gui.ccad_chamfer_d1, Gui.ccad_chamfer_d2
        if d1 == d2:
            return f"{d1}"
        return f"D1={d1}, D2={d2}"

    def _prompt(self):
        if self.step == 0:
            self.console.history.append(
                f"<span style='color:#aaa;'>CHAMFER: Select first line or "
                f"[<span style='color:#6af;'>D</span>istance] ({self._d_str()}):</span>"
            )
        elif self.step == 1:
            self.console.history.append(
                "<span style='color:#aaa;'>CHAMFER: Select second line:</span>"
            )

    # ── transaction helpers ──

    def _open_transaction(self, name="Chamfer"):
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

    # ── selection observer ──

    def addSelection(self, doc, obj_name, sub, pnt):
        if self._waiting_dist:
            Gui.Selection.clearSelection()
            return

        subname = sub if sub and "Edge" in sub else "Edge1"
        now = time.time()
        sel_key = (str(obj_name), str(subname), int(self.step))
        if self._last_sel_key == sel_key and (now - self.last_sel_time) < 0.15:
            return
        self.last_sel_time = now
        self._last_sel_key = sel_key

        vec_pnt = _parse_vector(pnt)

        if self.step == 0:
            self.obj1 = obj_name
            self.sub1 = subname
            self.pnt1 = vec_pnt
            self.step = 1
            self._prompt()
            Gui.Selection.clearSelection()

        elif self.step == 1:
            if obj_name == self.obj1 and self.sub1 == subname:
                Gui.Selection.clearSelection()
                return
            self.obj2 = obj_name
            self.sub2 = subname
            self.pnt2 = vec_pnt
            self.step = 2
            Gui.Selection.clearSelection()
            QtCore.QTimer.singleShot(50, self._execute)

    def removeSelection(self, doc, obj_name, sub):
        pass

    def setSelection(self, doc):
        pass

    def clearSelection(self, doc):
        pass

    # ── console input handling (called by console on Enter) ──

    def _on_input(self):
        text = self.console.input.text().strip().upper()
        if self.step == 0 and text == 'D':
            self.console.history.append(
                f"<span style='color:#aaa;'>CHAMFER: Specify first chamfer distance"
                f" &lt;{Gui.ccad_chamfer_d1}&gt;:</span>"
            )
            self._waiting_dist = 'D1'
            self.console.input.clear()
            return True

        if self._waiting_dist == 'D1':
            try:
                val = float(text) if text else Gui.ccad_chamfer_d1
                Gui.ccad_chamfer_d1 = val
                self._waiting_dist = 'D2'
                self.console.history.append(
                    f"<span style='color:#aaa;'>CHAMFER: Specify second chamfer distance"
                    f" &lt;{val}&gt;:</span>"
                )
            except ValueError:
                self.console.history.append(
                    "<span style='color:#ff5555;'>Invalid number. Enter first chamfer distance:</span>"
                )
            self.console.input.clear()
            return True

        if self._waiting_dist == 'D2':
            try:
                val = float(text) if text else Gui.ccad_chamfer_d1
                Gui.ccad_chamfer_d2 = val
                self.console.history.append(
                    f"<span style='color:#55ff55;'>Distances set to {Gui.ccad_chamfer_d1} / {val}</span>"
                )
            except ValueError:
                self.console.history.append(
                    "<span style='color:#ff5555;'>Invalid number. Enter second chamfer distance:</span>"
                )
                self.console.input.clear()
                return True
            self._waiting_dist = None
            self._prompt()
            self.console.input.clear()
            return True

        return False

    # ── chamfer execution ──

    def _execute(self):
        self.cleanup()

        doc = App.ActiveDocument
        if not doc:
            return

        o1 = doc.getObject(self.obj1)
        o2 = doc.getObject(self.obj2)
        if not o1 or not o2:
            self.console.history.append(
                "<span style='color:#ff5555;'>CHAMFER: Invalid selection.</span>"
            )
            return

        A1, B1 = _get_endpoints(o1)
        A2, B2 = _get_endpoints(o2)
        if not A1 or not A2:
            self.console.history.append(
                "<span style='color:#ff5555;'>CHAMFER Error: Can only chamfer lines or wires.</span>"
            )
            return

        I = _intersect_2d(A1, B1, A2, B2)
        if not I:
            self.console.history.append(
                "<span style='color:#ff5555;'>CHAMFER Error: Lines are parallel.</span>"
            )
            return

        d1 = Gui.ccad_chamfer_d1
        d2 = Gui.ccad_chamfer_d2

        if d1 <= 0.0 and d2 <= 0.0:
            # Zero-distance chamfer → sharp corner (same as FILLET 0)
            near1, far1 = _nearest_end(I, A1, B1)
            near2, far2 = _nearest_end(I, A2, B2)
            try:
                self._open_transaction("Chamfer")
                _set_endpoints(o1, I, far1)
                _set_endpoints(o2, I, far2)
                doc.recompute()
                self._commit_transaction()
            except Exception as exc:
                self._abort_transaction()
                self.console.history.append(
                    f"<span style='color:#ff5555;'>CHAMFER Error: {exc}</span>"
                )
                return
            self.console.history.append(
                "<span style='color:#55ff55;'>CHAMFER: Done (sharp corner).</span>"
            )
            return

        # Walk each line back from the intersection by its chamfer distance
        near1, far1 = _nearest_end(I, A1, B1)
        near2, far2 = _nearest_end(I, A2, B2)

        # Check that the lines are long enough
        len1 = _dist(A1, B1)
        len2 = _dist(A2, B2)
        if d1 > len1 or d2 > len2:
            self.console.history.append(
                "<span style='color:#ff5555;'>CHAMFER Error: Chamfer distance exceeds line length.</span>"
            )
            return

        # Trim points: walk d1 from intersection along line 1, d2 along line 2
        p1 = _point_along(near1, far1, d1)
        p2 = _point_along(near2, far2, d2)

        try:
            import Draft
            import ccad_layers

            self._open_transaction("Chamfer")

            # Trim line 1: keep the far portion, set its near endpoint to p1
            _set_endpoints(o1, p1, far1)
            # Trim line 2: keep the far portion
            _set_endpoints(o2, p2, far2)

            # Add chamfer line between the two trim points
            chamfer_line = Draft.make_wire([p1, p2], closed=False)
            layer = (
                ccad_layers.get_object_layer(o1)
                or ccad_layers.get_object_layer(o2)
                or ccad_layers.get_active_layer(doc)
            )
            if layer:
                ccad_layers.assign_to_layer(chamfer_line, layer)

            # Copy line colour / weight from the first source object
            if (
                chamfer_line
                and hasattr(o1, 'ViewObject') and o1.ViewObject
                and hasattr(chamfer_line, 'ViewObject') and chamfer_line.ViewObject
            ):
                for attr in ('LineColor', 'LineWidth'):
                    try:
                        setattr(chamfer_line.ViewObject, attr, getattr(o1.ViewObject, attr))
                    except Exception:
                        pass

            doc.recompute()
            self._commit_transaction()
        except Exception as exc:
            self._abort_transaction()
            self.console.history.append(
                f"<span style='color:#ff5555;'>CHAMFER Error: {exc}</span>"
            )
            return

        self.console.history.append(
            f"<span style='color:#55ff55;'>CHAMFER: Done (D1={d1}, D2={d2}).</span>"
        )

    def cleanup(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception:
            pass
        self._abort_transaction()
        Gui.Selection.clearSelection()
        if getattr(Gui, 'ccad_chamfer_handler', None) is self:
            Gui.ccad_chamfer_handler = None


def run(console):
    if hasattr(Gui, 'ccad_chamfer_handler') and Gui.ccad_chamfer_handler:
        Gui.ccad_chamfer_handler.cleanup()
    ChamferHandler(console)
