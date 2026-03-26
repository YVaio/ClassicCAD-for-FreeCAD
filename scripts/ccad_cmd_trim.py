"""TRIM, EXTEND, and FILLET commands — AutoCAD-style for FreeCAD.

Uses pure point/vector math instead of BRep section() for reliability
with Draft Wire objects.
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


def _seg_seg_intersect(a1, a2, b1, b2, tol=0.01):
    """2D segment-segment intersection (XY plane).

    Returns the intersection App.Vector or None.
    Both segments must actually cross (within *tol* of each other's span).
    """
    dx1, dy1 = a2.x - a1.x, a2.y - a1.y
    dx2, dy2 = b2.x - b1.x, b2.y - b1.y
    cross = dx1 * dy2 - dy1 * dx2
    if abs(cross) < 1e-12:
        return None
    dpx, dpy = b1.x - a1.x, b1.y - a1.y
    t = (dpx * dy2 - dpy * dx2) / cross
    u = (dpx * dy1 - dpy * dx1) / cross
    if -tol <= t <= 1 + tol and -tol <= u <= 1 + tol:
        z = (a1.z + a2.z + b1.z + b2.z) / 4
        return App.Vector(a1.x + dx1 * t, a1.y + dy1 * t, z)
    return None


def _line_line_intersect_infinite(a1, a2, b1, b2):
    """Intersection of two infinite lines (XY plane). Returns App.Vector or None."""
    dx1, dy1 = a2.x - a1.x, a2.y - a1.y
    dx2, dy2 = b2.x - b1.x, b2.y - b1.y
    cross = dx1 * dy2 - dy1 * dx2
    if abs(cross) < 1e-12:
        return None
    dpx, dpy = b1.x - a1.x, b1.y - a1.y
    t = (dpx * dy2 - dpy * dx2) / cross
    z = (a1.z + a2.z + b1.z + b2.z) / 4
    return App.Vector(a1.x + dx1 * t, a1.y + dy1 * t, z)


def _edge_endpoints(edge):
    """Return (p1, p2) as App.Vectors for an edge."""
    return edge.Vertexes[0].Point, edge.Vertexes[-1].Point


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
    """Collect all edges from visible user objects, excluding *exclude_name*."""
    _SKIP_TYPES = ('App::Origin', 'App::Line', 'App::Plane',
                   'App::DocumentObjectGroup', 'App::Part')
    edges = []
    for obj in doc.Objects:
        if obj.Name == exclude_name:
            continue
        if not hasattr(obj, 'Shape'):
            continue
        if obj.TypeId in _SKIP_TYPES:
            continue
        if hasattr(obj, 'ViewObject') and not obj.ViewObject.Visibility:
            continue
        try:
            if obj.Shape.isNull():
                continue
        except Exception:
            continue
        edges.extend(obj.Shape.Edges)
    return edges


def _set_focus_to_console():
    """Return keyboard focus to the ClassicConsole input."""
    console = getattr(Gui, 'classic_console', None)
    if console and hasattr(console, 'input'):
        console.input.setFocus()


# ─────────────────────────────────────────────
# TRIM / EXTEND handler
# ─────────────────────────────────────────────
class TrimExtendHandler(QtCore.QObject):
    """Interactive handler for AutoCAD-style TRIM and EXTEND."""

    def __init__(self, console, mode, viewport):
        super().__init__()
        self.console = console
        self.mode = mode
        self.viewport = viewport
        Gui.ccad_trim_handler = self
        if self.viewport:
            self.viewport.installEventFilter(self)
        self._msg(f"{mode}: Click on object (ESC to exit)")

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

    def _handle_click(self, pos):
        try:
            view = Gui.ActiveDocument.ActiveView
            info = view.getObjectInfo((pos.x(), pos.y()))
        except Exception as e:
            App.Console.PrintError(f"[CCAD] {self.mode}: getObjectInfo failed: {e}\n")
            return
        if not info:
            App.Console.PrintMessage(f"[CCAD] {self.mode}: No object under cursor at ({pos.x()}, {pos.y()})\n")
            return

        obj_name = info.get('Object', '')
        sub_name = info.get('Component', '')
        click_pt = App.Vector(info['x'], info['y'], info['z'])
        App.Console.PrintMessage(
            f"[CCAD] {self.mode}: Hit obj={obj_name} sub={sub_name} "
            f"pt=({click_pt.x:.2f}, {click_pt.y:.2f}, {click_pt.z:.2f})\n")

        doc = App.ActiveDocument
        obj = doc.getObject(obj_name) if doc else None
        if not obj or not hasattr(obj, 'Shape') or not obj.Shape.Edges:
            App.Console.PrintMessage(f"[CCAD] {self.mode}: Object has no edges\n")
            return

        try:
            if self.mode == 'TRIM':
                self._do_trim(obj, sub_name, click_pt)
            else:
                self._do_extend(obj, sub_name, click_pt)
        except Exception as e:
            App.Console.PrintError(f"[CCAD] {self.mode} error: {e}\n")
            self._msg(f"{self.mode}: Error — see Report View", err=True)

    # ──────────────────────────────────────────
    # TRIM
    # ──────────────────────────────────────────
    def _do_trim(self, obj, sub_name, click_pt):
        doc = App.ActiveDocument
        edge, edge_idx = _find_edge(obj, sub_name, click_pt)
        if edge is None or len(edge.Vertexes) < 2:
            self._msg("TRIM: Could not find edge", err=True)
            return

        ep1, ep2 = _edge_endpoints(edge)
        App.Console.PrintMessage(
            f"[CCAD] TRIM: Edge {edge_idx}: ({ep1.x:.2f},{ep1.y:.2f}) → ({ep2.x:.2f},{ep2.y:.2f})\n")
        cut_edges = _visible_edges_except(doc, obj.Name)
        App.Console.PrintMessage(f"[CCAD] TRIM: {len(cut_edges)} cutting edges found\n")

        # Find all intersection points on this edge using 2D segment math
        int_points = []
        for ce in cut_edges:
            if len(ce.Vertexes) < 2:
                continue
            cp1, cp2 = _edge_endpoints(ce)
            ipt = _seg_seg_intersect(ep1, ep2, cp1, cp2)
            if ipt is not None:
                int_points.append(ipt)
                App.Console.PrintMessage(
                    f"[CCAD] TRIM: Intersection at ({ipt.x:.2f},{ipt.y:.2f})\n")

        if not int_points:
            self._msg("TRIM: No intersections found", err=True)
            App.Console.PrintMessage(
                f"[CCAD] TRIM: No segment-segment intersections among {len(cut_edges)} edges\n")
            return

        # Sort intersections by parameter t along ep1→ep2
        edge_dir = ep2 - ep1
        edge_len2 = edge_dir.x ** 2 + edge_dir.y ** 2
        if edge_len2 < 1e-20:
            return

        def param(pt):
            return ((pt.x - ep1.x) * edge_dir.x +
                    (pt.y - ep1.y) * edge_dir.y) / edge_len2

        click_t = param(click_pt)
        int_ts = sorted(set(round(param(p), 8) for p in int_points))

        lower = [t for t in int_ts if t < click_t - 0.001]
        upper = [t for t in int_ts if t > click_t + 0.001]

        trim_start_t = max(lower) if lower else 0.0
        trim_end_t = min(upper) if upper else 1.0

        # Segments to keep (in t-space: 0 = ep1, 1 = ep2)
        keep = []
        if trim_start_t > 0.001:
            keep.append((0.0, trim_start_t))
        if trim_end_t < 0.999:
            keep.append((trim_end_t, 1.0))

        def t_to_pt(t):
            return App.Vector(ep1.x + edge_dir.x * t,
                              ep1.y + edge_dir.y * t,
                              ep1.z)

        self._apply_trim(obj, edge, edge_idx, keep, t_to_pt, doc)

    def _apply_trim(self, obj, edge, edge_idx, keep, t_to_pt, doc):
        is_xl = ccad_cmd_xline.is_xline(obj)
        is_draft = hasattr(obj, 'Points') and hasattr(obj, 'Proxy') and not is_xl

        if not keep:
            doc.removeObject(obj.Name)
            doc.recompute()
            self._msg("TRIM: Removed", ok=True)
            return

        # XLine → Draft lines
        if is_xl:
            import Draft
            lc = tuple(obj.ViewObject.LineColor[:3]) + (0.0,)
            for s, e in keep:
                w = Draft.make_wire([t_to_pt(s), t_to_pt(e)],
                                   closed=False, face=False)
                w.ViewObject.LineColor = lc
            doc.removeObject(obj.Name)
            doc.recompute()
            self._msg("TRIM: XLine → Line", ok=True)
            return

        # Draft Wire (single edge)
        if is_draft and len(obj.Shape.Edges) == 1:
            if len(keep) == 1:
                obj.Points = [t_to_pt(keep[0][0]), t_to_pt(keep[0][1])]
            else:
                obj.Points = [t_to_pt(keep[0][0]), t_to_pt(keep[0][1])]
                import Draft
                for k in keep[1:]:
                    Draft.make_wire([t_to_pt(k[0]), t_to_pt(k[1])])
            doc.recompute()
            self._msg("TRIM: Done", ok=True)
            return

        # Draft Wire (multi-segment)
        if is_draft and len(obj.Shape.Edges) > 1:
            self._trim_multi_wire(obj, edge_idx, keep, t_to_pt, doc)
            return

        # Generic Part::Feature
        import Part
        new_edges = [Part.makeLine(t_to_pt(s), t_to_pt(e)) for s, e in keep]
        if len(new_edges) == 1:
            obj.Shape = new_edges[0]
        else:
            obj.Shape = new_edges[0]
            for extra in new_edges[1:]:
                n = doc.addObject("Part::Feature", obj.Label)
                n.Shape = extra
        doc.recompute()
        self._msg("TRIM: Done", ok=True)

    def _trim_multi_wire(self, obj, edge_idx, keep, t_to_pt, doc):
        import Draft
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
            if keep[0][0] < 0.001:
                obj.Points = points[:edge_idx + 1] + [t_to_pt(keep[0][1])]
            else:
                obj.Points = [t_to_pt(keep[0][0])] + points[edge_idx + 1:]
        else:
            left = points[:edge_idx + 1] + [t_to_pt(keep[0][1])]
            right = [t_to_pt(keep[1][0])] + points[edge_idx + 1:]
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
        doc = App.ActiveDocument
        edge, edge_idx = _find_edge(obj, sub_name, click_pt)
        if edge is None or len(edge.Vertexes) < 2:
            self._msg("EXTEND: Could not find edge", err=True)
            return

        ep1, ep2 = _edge_endpoints(edge)
        App.Console.PrintMessage(
            f"[CCAD] EXTEND: Edge {edge_idx}: ({ep1.x:.2f},{ep1.y:.2f}) → ({ep2.x:.2f},{ep2.y:.2f})\n")
        d_start = click_pt.distanceToPoint(ep1)
        d_end = click_pt.distanceToPoint(ep2)
        extend_start = d_start < d_end
        App.Console.PrintMessage(
            f"[CCAD] EXTEND: Extending {'start' if extend_start else 'end'} side\n")

        edge_dir = ep2 - ep1
        if edge_dir.Length < 1e-7:
            return
        d = App.Vector(edge_dir)
        d.normalize()

        bnd_edges = _visible_edges_except(doc, obj.Name)
        if not bnd_edges:
            self._msg("EXTEND: No boundaries", err=True)
            return
        App.Console.PrintMessage(f"[CCAD] EXTEND: {len(bnd_edges)} boundary edges\n")

        # Create a very long ray extending from the near endpoint
        BIG = 1e9
        if extend_start:
            ray_a = App.Vector(ep1.x - d.x * BIG, ep1.y - d.y * BIG, ep1.z)
            ray_b = ep1
        else:
            ray_a = ep2
            ray_b = App.Vector(ep2.x + d.x * BIG, ep2.y + d.y * BIG, ep2.z)

        target = ep1 if extend_start else ep2
        best_pt, best_dist = None, float('inf')

        for be in bnd_edges:
            if len(be.Vertexes) < 2:
                continue
            bp1, bp2 = _edge_endpoints(be)
            # The ray must cross the boundary segment (segment tolerance = 0)
            ipt = _seg_seg_intersect(ray_a, ray_b, bp1, bp2, tol=0.0)
            if ipt is None:
                continue
            dist = ipt.distanceToPoint(target)
            if dist < best_dist:
                best_dist = dist
                best_pt = ipt

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
            import Part
            if extend_start:
                obj.Shape = Part.makeLine(best_pt, ep2)
            else:
                obj.Shape = Part.makeLine(ep1, best_pt)

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
        _set_focus_to_console()

    def cleanup(self):
        Gui.ccad_trim_handler = None
        if self.viewport:
            self.viewport.removeEventFilter(self)
        _set_focus_to_console()
        self.deleteLater()


# ─────────────────────────────────────────────
# FILLET handler
# ─────────────────────────────────────────────
_FILLET_PREF = "User parameter:BaseApp/Preferences/Mod/ClassicCAD"


class FilletHandler(QtCore.QObject):
    """Interactive handler for AutoCAD-style FILLET."""
    _radius = None

    def __init__(self, console, viewport):
        super().__init__()
        self.console = console
        self.viewport = viewport
        self.first_obj = None
        self.first_edge = None
        self.first_edge_idx = None
        self.first_click = None
        self._waiting_radius = False
        if FilletHandler._radius is None:
            FilletHandler._radius = App.ParamGet(_FILLET_PREF).GetFloat("FilletRadius", 0.0)
        Gui.ccad_fillet_handler = self
        if self.viewport:
            self.viewport.installEventFilter(self)
        self._show_prompt()

    def _show_prompt(self):
        r = FilletHandler._radius
        self._msg(f"FILLET (R={r:.4f}): Click first edge [R=radius, ESC=exit]")

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.MouseMove:
            return False
        if (event.type() == QtCore.QEvent.MouseButtonPress
                and event.button() == QtCore.Qt.LeftButton):
            if not self._waiting_radius:
                pos = _screen_pos(event)
                self._handle_click(pos)
                return True
        if event.type() == QtCore.QEvent.KeyPress:
            key = event.key()
            if key == QtCore.Qt.Key_Escape:
                self._msg("FILLET: Done")
                self.cleanup()
                return True
            if key == QtCore.Qt.Key_R and not self._waiting_radius:
                self._waiting_radius = True
                self._msg(f"Enter fillet radius <{FilletHandler._radius:.4f}>:")
                _set_focus_to_console()
                return True
        return False

    def _on_input(self):
        """Called by console when user presses Enter/Space during fillet."""
        text = self.console.input.text().strip()
        self.console.input.clear()
        if not text:
            return
        if self._waiting_radius:
            try:
                r = float(text)
                if r < 0:
                    self._msg("Radius must be >= 0", err=True)
                else:
                    FilletHandler._radius = r
                    App.ParamGet(_FILLET_PREF).SetFloat("FilletRadius", r)
                    self._msg(f"Radius set to {r:.4f}", ok=True)
            except ValueError:
                self._msg("Invalid number", err=True)
            self._waiting_radius = False
            self._show_prompt()
            return
        if text.upper() == 'R':
            self._waiting_radius = True
            self._msg(f"Enter fillet radius <{FilletHandler._radius:.4f}>:")
            return

    def _handle_click(self, pos):
        try:
            view = Gui.ActiveDocument.ActiveView
            info = view.getObjectInfo((pos.x(), pos.y()))
        except Exception:
            return
        if not info:
            App.Console.PrintMessage(f"[CCAD] FILLET: No object under cursor\n")
            return
        obj_name = info.get('Object', '')
        sub_name = info.get('Component', '')
        click_pt = App.Vector(info['x'], info['y'], info['z'])
        App.Console.PrintMessage(
            f"[CCAD] FILLET: Hit obj={obj_name} sub={sub_name} "
            f"pt=({click_pt.x:.2f}, {click_pt.y:.2f})\n")
        doc = App.ActiveDocument
        obj = doc.getObject(obj_name) if doc else None
        if not obj or not hasattr(obj, 'Shape') or not obj.Shape.Edges:
            return
        edge, idx = _find_edge(obj, sub_name, click_pt)
        if edge is None:
            App.Console.PrintMessage(f"[CCAD] FILLET: Could not find edge\n")
            return
        if self.first_obj is None:
            self.first_obj = obj
            self.first_edge = edge
            self.first_edge_idx = idx
            self.first_click = click_pt
            self._msg("Click second edge")
        else:
            if obj.Name == self.first_obj.Name and idx == self.first_edge_idx:
                self._msg("Cannot fillet edge with itself", err=True)
                return
            try:
                self._do_fillet(obj, edge, idx, click_pt)
            except Exception as e:
                App.Console.PrintError(f"[CCAD] FILLET error: {e}\n")
                self._msg("FILLET: Error — see Report View", err=True)
            self.first_obj = None
            self.first_edge = None
            self.first_click = None
            self._show_prompt()

    def _do_fillet(self, obj2, edge2, idx2, click2):
        import math
        edge1 = self.first_edge
        obj1 = self.first_obj
        click1 = self.first_click
        doc = App.ActiveDocument
        r = FilletHandler._radius

        if len(edge1.Vertexes) < 2 or len(edge2.Vertexes) < 2:
            self._msg("FILLET: Need line edges", err=True)
            return

        a1, a2 = _edge_endpoints(edge1)
        b1, b2 = _edge_endpoints(edge2)
        int_pt = _line_line_intersect_infinite(a1, a2, b1, b2)
        if int_pt is None:
            self._msg("FILLET: Lines are parallel", err=True)
            return

        if r <= 1e-9:
            self._trim_to_point(obj1, self.first_edge_idx, click1, int_pt)
            self._trim_to_point(obj2, idx2, click2, int_pt)
            doc.recompute()
            self._msg("FILLET: Corner created", ok=True)
        else:
            self._fillet_with_arc(obj1, edge1, self.first_edge_idx, click1,
                                  obj2, edge2, idx2, click2,
                                  int_pt, r)

    def _trim_to_point(self, obj, edge_idx, click_pt, target_pt):
        """Set one endpoint of a Draft wire edge to target_pt, keeping the click side."""
        is_draft = hasattr(obj, 'Points') and hasattr(obj, 'Proxy')
        if not is_draft:
            return
        pts = list(obj.Points)
        if len(pts) < 2:
            return
        if len(pts) == 2:
            d0 = click_pt.distanceToPoint(pts[0])
            d1 = click_pt.distanceToPoint(pts[1])
            if d0 < d1:
                pts[1] = target_pt
            else:
                pts[0] = target_pt
            obj.Points = pts
        elif edge_idx < len(pts) - 1:
            d0 = click_pt.distanceToPoint(pts[edge_idx])
            d1 = click_pt.distanceToPoint(pts[edge_idx + 1])
            if d0 < d1:
                pts[edge_idx + 1] = target_pt
            else:
                pts[edge_idx] = target_pt
            obj.Points = pts

    def _fillet_with_arc(self, obj1, edge1, idx1, click1,
                         obj2, edge2, idx2, click2,
                         int_pt, radius):
        import Part, math
        doc = App.ActiveDocument

        a1, a2 = _edge_endpoints(edge1)
        b1, b2 = _edge_endpoints(edge2)

        def toward_click(p1, p2, click_pt):
            """Unit vector along p1→p2, flipped to point toward click side."""
            d = App.Vector(p2.x - p1.x, p2.y - p1.y, 0)
            if d.Length < 1e-10:
                return None
            d.normalize()
            d0 = click_pt.distanceToPoint(p1)
            d1 = click_pt.distanceToPoint(p2)
            return d if d1 < d0 else d * -1

        t1 = toward_click(a1, a2, click1)
        t2 = toward_click(b1, b2, click2)
        if t1 is None or t2 is None:
            self._msg("FILLET: Cannot determine directions", err=True)
            return

        dot = max(-1.0, min(1.0, t1.dot(t2)))
        angle = math.acos(dot)
        if angle < 1e-6 or abs(angle - math.pi) < 1e-6:
            self._msg("FILLET: Lines are parallel or coincident", err=True)
            return

        half = angle / 2
        tan_dist = radius / math.tan(half)

        T1 = App.Vector(int_pt.x + t1.x * tan_dist,
                        int_pt.y + t1.y * tan_dist, int_pt.z)
        T2 = App.Vector(int_pt.x + t2.x * tan_dist,
                        int_pt.y + t2.y * tan_dist, int_pt.z)

        bisector = App.Vector(t1.x + t2.x, t1.y + t2.y, 0)
        if bisector.Length < 1e-10:
            self._msg("FILLET: Cannot compute fillet center", err=True)
            return
        bisector.normalize()
        center_dist = radius / math.sin(half)
        center = App.Vector(int_pt.x + bisector.x * center_dist,
                            int_pt.y + bisector.y * center_dist, int_pt.z)

        dir_to_int = App.Vector(int_pt.x - center.x, int_pt.y - center.y, 0)
        if dir_to_int.Length < 1e-10:
            self._msg("FILLET: Degenerate geometry", err=True)
            return
        dir_to_int.normalize()
        arc_mid = App.Vector(center.x + dir_to_int.x * radius,
                             center.y + dir_to_int.y * radius, int_pt.z)

        try:
            arc_edge = Part.Arc(T1, arc_mid, T2).toShape()
            arc_obj = doc.addObject("Part::Feature", "Fillet")
            arc_obj.Shape = Part.Wire([arc_edge])
            if hasattr(obj1, 'ViewObject') and hasattr(obj1.ViewObject, 'LineColor'):
                arc_obj.ViewObject.LineColor = obj1.ViewObject.LineColor
        except Exception as e:
            App.Console.PrintError(f"[CCAD] FILLET arc failed: {e}\n")
            self._msg("FILLET: Arc creation failed", err=True)
            return

        self._trim_to_point(obj1, idx1, click1, T1)
        self._trim_to_point(obj2, idx2, click2, T2)
        doc.recompute()
        self._msg("FILLET: Done", ok=True)

    def _msg(self, text, ok=False, err=False):
        if err:
            color = '#ff5555'
        elif ok:
            color = '#55ff55'
        else:
            color = '#aaa'
        self.console.history.append(f"<span style='color:{color};'>{text}</span>")
        _set_focus_to_console()

    def cleanup(self):
        Gui.ccad_fillet_handler = None
        if self.viewport:
            self.viewport.removeEventFilter(self)
        _set_focus_to_console()
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


def run_fillet(console):
    """Launch FILLET."""
    vp = _get_viewport()
    if not vp:
        console.history.append(
            "<span style='color:#ff5555;'>FILLET: No viewport</span>")
        return
    FilletHandler(console, vp)
