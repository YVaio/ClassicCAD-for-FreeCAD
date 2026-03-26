"""TRIM and EXTEND commands — AutoCAD-style for FreeCAD.

TRIM:
  All visible objects are implicit cutting edges.
  Click on a segment to remove the portion between intersections.
  Continues accepting clicks until ESC.

EXTEND:
  All visible objects are implicit boundary edges.
  Click near the endpoint you want to extend.
  Extends the edge to the nearest boundary intersection.
  Continues accepting clicks until ESC.
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore
import ccad_cmd_xline


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _screen_pos(event):
    return event.position().toPoint() if hasattr(event, 'position') else event.pos()


def _get_viewport():
    from PySide6 import QtWidgets
    if hasattr(Gui, 'ccad_sel_logic') and Gui.ccad_sel_logic:
        return Gui.ccad_sel_logic.viewport
    mw = Gui.getMainWindow()
    if mw:
        for w in mw.findChildren(QtWidgets.QWidget):
            if "View3DInventor" in w.metaObject().className() and w.isVisible():
                return w
    return None


def _find_edge(obj, sub_name, click_pt):
    """Return (edge, index) for the clicked edge."""
    import Part
    if sub_name and sub_name.startswith('Edge'):
        try:
            idx = int(sub_name[4:]) - 1
            if 0 <= idx < len(obj.Shape.Edges):
                return obj.Shape.Edges[idx], idx
        except ValueError:
            pass
    best, best_idx, best_d = None, 0, float('inf')
    for i, e in enumerate(obj.Shape.Edges):
        try:
            d = e.distToShape(Part.Vertex(click_pt))[0]
            if d < best_d:
                best, best_idx, best_d = e, i, d
        except Exception:
            pass
    return best, best_idx


def _visible_edges_except(doc, exclude_name):
    """Collect all edges from visible objects, excluding *exclude_name*."""
    edges = []
    for obj in doc.Objects:
        if obj.Name == exclude_name or not hasattr(obj, 'Shape'):
            continue
        if hasattr(obj, 'ViewObject') and not obj.ViewObject.Visibility:
            continue
        edges.extend(obj.Shape.Edges)
    return edges


# ─────────────────────────────────────────────
# TRIM / EXTEND handler
# ─────────────────────────────────────────────
class TrimExtendHandler(QtCore.QObject):
    """Interactive handler for AutoCAD-style TRIM and EXTEND."""

    def __init__(self, console, mode, viewport):
        super().__init__()
        self.console = console
        self.mode = mode  # 'TRIM' or 'EXTEND'
        self.viewport = viewport
        Gui.ccad_trim_handler = self
        if self.viewport:
            self.viewport.installEventFilter(self)
        self._msg(f"{mode}: Click on object (ESC to exit)")

    # ── events ────────────────────────────────

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.MouseMove:
            return False

        if (event.type() == QtCore.QEvent.MouseButtonPress
                and event.button() == QtCore.Qt.LeftButton):
            pos = _screen_pos(event)
            self._handle_click(pos)
            return True

        if (event.type() == QtCore.QEvent.KeyPress
                and event.key() == QtCore.Qt.Key_Escape):
            self._msg(f"{self.mode}: Done")
            self.cleanup()
            return True

        return False

    # ── click dispatch ────────────────────────

    def _handle_click(self, pos):
        try:
            view = Gui.ActiveDocument.ActiveView
            info = view.getObjectInfo((pos.x(), pos.y()))
        except Exception:
            return
        if not info:
            return

        obj_name = info.get('Object', '')
        sub_name = info.get('Component', '')
        click_pt = App.Vector(info['x'], info['y'], info['z'])

        doc = App.ActiveDocument
        obj = doc.getObject(obj_name) if doc else None
        if not obj or not hasattr(obj, 'Shape') or not obj.Shape.Edges:
            return

        if self.mode == 'TRIM':
            self._do_trim(obj, sub_name, click_pt)
        else:
            self._do_extend(obj, sub_name, click_pt)

    # ──────────────────────────────────────────
    # TRIM
    # ──────────────────────────────────────────
    def _do_trim(self, obj, sub_name, click_pt):
        import Part
        doc = App.ActiveDocument

        edge, edge_idx = _find_edge(obj, sub_name, click_pt)
        if edge is None:
            return

        cut_edges = _visible_edges_except(doc, obj.Name)

        # Find intersections on the clicked edge
        int_points = []
        for ce in cut_edges:
            try:
                section = edge.section(ce)
                for v in section.Vertexes:
                    int_points.append(v.Point)
            except Exception:
                pass

        if not int_points:
            self._msg("TRIM: No intersections", err=True)
            return

        first = edge.FirstParameter
        last = edge.LastParameter
        param_click = edge.Curve.parameter(click_pt)

        int_params = set()
        for pt in int_points:
            try:
                p = edge.Curve.parameter(pt)
                if first - 0.01 <= p <= last + 0.01:
                    int_params.add(round(p, 6))
            except Exception:
                pass
        int_params = sorted(int_params)

        if not int_params:
            self._msg("TRIM: No intersections on edge", err=True)
            return

        lower = [p for p in int_params if p < param_click - 0.001]
        upper = [p for p in int_params if p > param_click + 0.001]

        trim_start = max(lower) if lower else first
        trim_end = min(upper) if upper else last

        keep = []
        if abs(trim_start - first) > 0.001:
            keep.append((first, trim_start))
        if abs(trim_end - last) > 0.001:
            keep.append((trim_end, last))

        self._apply_trim(obj, edge, edge_idx, keep)

    def _apply_trim(self, obj, edge, edge_idx, keep):
        import Part
        doc = App.ActiveDocument

        if not keep:
            doc.removeObject(obj.Name)
            doc.recompute()
            self._msg("TRIM: Removed", ok=True)
            return

        is_xl = ccad_cmd_xline.is_xline(obj)
        is_draft = hasattr(obj, 'Points') and hasattr(obj, 'Proxy') and not is_xl

        # ── XLine → regular Draft line(s) ──
        if is_xl:
            import Draft
            lc = tuple(obj.ViewObject.LineColor[:3]) + (0.0,)
            for s, e in keep:
                p1, p2 = edge.Curve.value(s), edge.Curve.value(e)
                w = Draft.make_wire([p1, p2], closed=False, face=False)
                w.ViewObject.LineColor = lc
            doc.removeObject(obj.Name)
            doc.recompute()
            self._msg("TRIM: XLine → Line", ok=True)
            return

        # ── Draft Wire (single segment) ──
        if is_draft and len(obj.Shape.Edges) == 1:
            if len(keep) == 1:
                obj.Points = [edge.Curve.value(keep[0][0]),
                              edge.Curve.value(keep[0][1])]
            else:
                obj.Points = [edge.Curve.value(keep[0][0]),
                              edge.Curve.value(keep[0][1])]
                import Draft
                for k in keep[1:]:
                    Draft.make_wire([edge.Curve.value(k[0]),
                                    edge.Curve.value(k[1])])
            doc.recompute()
            self._msg("TRIM: Done", ok=True)
            return

        # ── Draft Wire (multi-segment) ──
        if is_draft and len(obj.Shape.Edges) > 1:
            self._trim_draft_wire(obj, edge, edge_idx, keep)
            return

        # ── Generic Part::Feature ──
        new_edges = [edge.Curve.toShape(s, e) for s, e in keep]
        if len(new_edges) == 1:
            obj.Shape = new_edges[0]
        else:
            obj.Shape = new_edges[0]
            for extra in new_edges[1:]:
                n = doc.addObject("Part::Feature", obj.Label)
                n.Shape = extra
        doc.recompute()
        self._msg("TRIM: Done", ok=True)

    def _trim_draft_wire(self, obj, edge, edge_idx, keep):
        import Draft
        doc = App.ActiveDocument
        points = list(obj.Points)

        if edge_idx >= len(points) - 1:
            return

        if not keep:
            left = points[:edge_idx + 1]
            right = points[edge_idx + 1:]
            if len(left) >= 2:
                obj.Points = left
            else:
                doc.removeObject(obj.Name)
            if len(right) >= 2:
                Draft.make_wire(right)

        elif len(keep) == 1:
            at_start = abs(keep[0][0] - edge.FirstParameter) < 0.001
            if at_start:
                new_pt = edge.Curve.value(keep[0][1])
                obj.Points = points[:edge_idx + 1] + [new_pt]
            else:
                new_pt = edge.Curve.value(keep[0][0])
                obj.Points = [new_pt] + points[edge_idx + 1:]
        else:
            p1_end = edge.Curve.value(keep[0][1])
            p2_start = edge.Curve.value(keep[1][0])
            left = points[:edge_idx + 1] + [p1_end]
            right = [p2_start] + points[edge_idx + 1:]
            if len(left) >= 2:
                obj.Points = left
            if len(right) >= 2:
                Draft.make_wire(right)

        doc.recompute()
        self._msg("TRIM: Done", ok=True)

    # ──────────────────────────────────────────
    # EXTEND
    # ──────────────────────────────────────────
    def _do_extend(self, obj, sub_name, click_pt):
        import Part
        doc = App.ActiveDocument

        edge, edge_idx = _find_edge(obj, sub_name, click_pt)
        if edge is None:
            return

        if len(edge.Vertexes) < 2:
            return

        p_start = edge.Vertexes[0].Point
        p_end = edge.Vertexes[-1].Point
        extend_start = click_pt.distanceToPoint(p_start) < click_pt.distanceToPoint(p_end)

        try:
            d = App.Vector(edge.Curve.Direction)
        except AttributeError:
            d = p_end - p_start
            if d.Length < 1e-7:
                return
            d.normalize()

        bnd_edges = _visible_edges_except(doc, obj.Name)
        if not bnd_edges:
            self._msg("EXTEND: No boundaries", err=True)
            return

        BIG = 1e9
        if extend_start:
            ext = Part.makeLine(p_start - d * BIG, p_end)
        else:
            ext = Part.makeLine(p_start, p_end + d * BIG)

        target = p_start if extend_start else p_end
        best_pt, best_dist = None, float('inf')

        for be in bnd_edges:
            try:
                section = ext.section(be)
                for v in section.Vertexes:
                    pt = v.Point
                    vec = pt - target
                    if extend_start and vec.dot(d) > 0:
                        continue
                    if not extend_start and vec.dot(d) < 0:
                        continue
                    dist = pt.distanceToPoint(target)
                    if dist < best_dist:
                        best_dist = dist
                        best_pt = pt
            except Exception:
                pass

        if best_pt is None:
            self._msg("EXTEND: No boundary found", err=True)
            return

        is_draft = hasattr(obj, 'Points') and hasattr(obj, 'Proxy')
        if is_draft:
            pts = list(obj.Points)
            if extend_start and edge_idx < len(pts):
                pts[edge_idx] = best_pt
            elif not extend_start and edge_idx + 1 < len(pts):
                pts[edge_idx + 1] = best_pt
            obj.Points = pts
        else:
            if extend_start:
                obj.Shape = Part.makeLine(best_pt, p_end)
            else:
                obj.Shape = Part.makeLine(p_start, best_pt)

        doc.recompute()
        self._msg("EXTEND: Done", ok=True)

    # ── helpers ───────────────────────────────

    def _msg(self, text, ok=False, err=False):
        if err:
            color = '#ff5555'
        elif ok:
            color = '#55ff55'
        else:
            color = '#aaa'
        self.console.history.append(f"<span style='color:{color};'>{text}</span>")

    def cleanup(self):
        Gui.ccad_trim_handler = None
        if self.viewport:
            self.viewport.removeEventFilter(self)
        self.deleteLater()


# ─────────────────────────────────────────────
# Console entry-points
# ─────────────────────────────────────────────
def run(console, mode):
    """Launch TRIM or EXTEND.  *mode*: 'TRIM' or 'EXTEND'."""
    vp = _get_viewport()
    if not vp:
        console.history.append(
            f"<span style='color:#ff5555;'>{mode}: No viewport</span>")
        return
    TrimExtendHandler(console, mode, vp)
