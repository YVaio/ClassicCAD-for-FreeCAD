"""XLINE command — AutoCAD-style construction lines for FreeCAD.

Creates a Draft Wire with very long length (±1e6 mm from midpoint).
First click sets the midpoint, second click sets direction.

Sub-options (typed in console while handler is active):
  H — Horizontal through a point
  V — Vertical through a point
  A — At a specific angle through a point
  B — Bisect: angle bisector between two lines
  O — Offset: parallel copy of an existing line
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore

BIG = 1e6  # half-length from midpoint


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _screen_pos(event):
    return event.position().toPoint() if hasattr(event, 'position') else event.pos()


def _snap_coords(pos):
    return [pos.x(), pos.y()]


def get_3d_point(pos, lastpoint=None):
    """3D point from snapper (preferred) or plain view projection."""
    try:
        result = Gui.Snapper.snap(_snap_coords(pos), lastpoint=lastpoint)
        if result is not None:
            pt = result[0] if isinstance(result, tuple) else result
            if pt is not None:
                return pt
    except Exception:
        pass
    try:
        return Gui.activeView().getPoint(pos.x(), pos.y())
    except Exception:
        return None


def is_xline(obj):
    """Return True if *obj* is an XLine (Draft Wire labelled 'XLine')."""
    return (hasattr(obj, 'Label') and obj.Label.startswith('XLine')
            and hasattr(obj, 'Points'))


def _make_xline(midpoint, direction):
    """Create a Draft Wire named XLine through *midpoint* in *direction*."""
    import Draft
    d = App.Vector(direction)
    if d.Length < 1e-7:
        return None
    d.normalize()
    p1 = midpoint - d * BIG
    p2 = midpoint + d * BIG
    wire = Draft.make_wire([p1, p2], closed=False, face=False)
    wire.Label = "XLine"
    App.ActiveDocument.recompute()
    return wire


# ─────────────────────────────────────────────
# Interactive pick handler
# ─────────────────────────────────────────────
class XlinePickHandler(QtCore.QObject):
    """Viewport event filter for interactive XLINE creation.

    Modes:
      None  — two-point (midpoint + direction)
      'H'   — horizontal through one point
      'V'   — vertical through one point
      'A'   — angle mode: user types angle, then clicks point
      'B'   — bisect: click two lines
      'O'   — offset: click a line, then side
    """

    def __init__(self, console, viewport):
        super().__init__()
        self.console = console
        self.mode = None
        self.midpoint = None
        self.viewport = viewport
        self.angle = None           # for Angle mode
        self._bisect_edge1 = None   # for Bisect mode
        self._offset_obj = None     # for Offset mode
        Gui.ccad_xline_handler = self
        if self.viewport:
            self.viewport.installEventFilter(self)
        # Hook console input for sub-option entry
        self.console.input.returnPressed.disconnect()
        self.console.input.returnPressed.connect(self._on_input)

    # ── events ────────────────────────────────

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.MouseMove:
            pos = _screen_pos(event)
            try:
                Gui.Snapper.snap(_snap_coords(pos), lastpoint=self.midpoint)
            except Exception:
                pass
            return False

        if (event.type() == QtCore.QEvent.MouseButtonPress
                and event.button() == QtCore.Qt.LeftButton):
            pos = _screen_pos(event)
            point = get_3d_point(pos, self.midpoint)
            if point is None:
                return True
            return self._handle_point(point, pos)

        if (event.type() == QtCore.QEvent.KeyPress
                and event.key() == QtCore.Qt.Key_Escape):
            self._msg("XLINE: Cancelled")
            self.cleanup()
            return True

        return False

    # ── console input handler ─────────────────

    def _on_input(self):
        text = self.console.input.text().strip().upper()
        self.console.input.clear()

        if not text:
            return

        # Sub-option selection (only when no clicks yet)
        if self.midpoint is None and self.mode is None:
            if text == 'H':
                self.mode = 'H'
                self._msg("XLINE Horizontal: Click a point")
                return
            elif text == 'V':
                self.mode = 'V'
                self._msg("XLINE Vertical: Click a point")
                return
            elif text == 'A':
                self.mode = 'A'
                self._msg("XLINE Angle: Enter angle (degrees)")
                return
            elif text == 'B':
                self.mode = 'B'
                self._msg("XLINE Bisect: Click first line")
                return
            elif text == 'O':
                self.mode = 'O'
                self._msg("XLINE Offset: Click a line to offset")
                return

        # Angle mode: user types the angle value
        if self.mode == 'A' and self.angle is None:
            try:
                import math
                self.angle = math.radians(float(text))
                self._msg(f"XLINE Angle {text}°: Click a point")
            except ValueError:
                self._msg("XLINE: Invalid angle", err=True)
            return

    # ── point logic ───────────────────────────

    def _handle_point(self, point, pos=None):
        # ── Horizontal ──
        if self.mode == 'H':
            _make_xline(point, App.Vector(1, 0, 0))
            self._msg("XLINE H: Done", ok=True)
            self.cleanup()
            return True

        # ── Vertical ──
        if self.mode == 'V':
            _make_xline(point, App.Vector(0, 1, 0))
            self._msg("XLINE V: Done", ok=True)
            self.cleanup()
            return True

        # ── Angle ──
        if self.mode == 'A':
            if self.angle is None:
                self._msg("XLINE: Enter angle first", err=True)
                return True
            import math
            d = App.Vector(math.cos(self.angle), math.sin(self.angle), 0)
            _make_xline(point, d)
            self._msg("XLINE Angle: Done", ok=True)
            self.cleanup()
            return True

        # ── Bisect ──
        if self.mode == 'B':
            return self._handle_bisect(point, pos)

        # ── Offset ──
        if self.mode == 'O':
            return self._handle_offset(point, pos)

        # ── Default: midpoint + direction ──
        if self.midpoint is None:
            self.midpoint = point
            self._msg("XLINE: Click direction point")
            return True

        d = point - self.midpoint
        if d.Length < 0.001:
            return True
        _make_xline(self.midpoint, d)
        self._msg("XLINE: Done", ok=True)
        self.cleanup()
        return True

    # ── Bisect logic ──────────────────────────

    def _handle_bisect(self, point, pos):
        try:
            view = Gui.ActiveDocument.ActiveView
            info = view.getObjectInfo((pos.x(), pos.y())) if pos else None
        except Exception:
            info = None

        if not info:
            self._msg("XLINE Bisect: Click on a line", err=True)
            return True

        doc = App.ActiveDocument
        obj = doc.getObject(info.get('Object', '')) if doc else None
        if not obj or not hasattr(obj, 'Shape') or not obj.Shape.Edges:
            self._msg("XLINE Bisect: Not a valid edge", err=True)
            return True

        edge = obj.Shape.Edges[0]
        try:
            d = App.Vector(edge.Curve.Direction)
        except AttributeError:
            verts = edge.Vertexes
            if len(verts) >= 2:
                d = verts[-1].Point - verts[0].Point
                d.normalize()
            else:
                return True

        if self._bisect_edge1 is None:
            self._bisect_edge1 = d
            self._msg("XLINE Bisect: Click second line")
            return True

        # Compute bisector direction
        d1 = self._bisect_edge1
        d2 = d
        bisect = (d1 + d2)
        if bisect.Length < 1e-7:
            bisect = App.Vector(-d1.y, d1.x, 0)  # perpendicular if parallel
        click_pt = App.Vector(info['x'], info['y'], info['z'])
        _make_xline(click_pt, bisect)
        self._msg("XLINE Bisect: Done", ok=True)
        self.cleanup()
        return True

    # ── Offset logic ──────────────────────────

    def _handle_offset(self, point, pos):
        try:
            view = Gui.ActiveDocument.ActiveView
            info = view.getObjectInfo((pos.x(), pos.y())) if pos else None
        except Exception:
            info = None

        if self._offset_obj is None:
            if not info:
                self._msg("XLINE Offset: Click on a line", err=True)
                return True
            doc = App.ActiveDocument
            obj = doc.getObject(info.get('Object', '')) if doc else None
            if not obj or not hasattr(obj, 'Shape') or not obj.Shape.Edges:
                self._msg("XLINE Offset: Not a valid edge", err=True)
                return True
            self._offset_obj = obj
            self._msg("XLINE Offset: Click side to place")
            return True

        # Second click: compute offset
        edge = self._offset_obj.Shape.Edges[0]
        try:
            d = App.Vector(edge.Curve.Direction)
        except AttributeError:
            verts = edge.Vertexes
            if len(verts) >= 2:
                d = verts[-1].Point - verts[0].Point
                d.normalize()
            else:
                self.cleanup()
                return True

        # Project click onto perpendicular to get offset point
        edge_start = edge.Vertexes[0].Point
        _make_xline(point, d)
        self._msg("XLINE Offset: Done", ok=True)
        self.cleanup()
        return True

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
        try:
            Gui.Snapper.off()
        except Exception:
            pass
        Gui.ccad_xline_handler = None
        if self.viewport:
            self.viewport.removeEventFilter(self)
        # Restore console input connection
        try:
            self.console.input.returnPressed.disconnect()
        except Exception:
            pass
        self.console.input.returnPressed.connect(self.console.execute)
        self.deleteLater()


# ─────────────────────────────────────────────
# Console entry-point
# ─────────────────────────────────────────────
def run(console, option=None):
    """Launch the XLINE interactive handler with options prompt.

    *option* can be None (interactive), 'H' (horizontal) or 'V' (vertical).
    """
    vp = _get_viewport()
    if not vp:
        console.history.append(
            "<span style='color:#ff5555;'>XLINE: No viewport</span>")
        return
    console.history.append(
        "<span style='color:#aaa;'>Specify Xline location or "
        "[<span style='color:#6af;'>B</span>isect "
        "<span style='color:#6af;'>H</span>orizontal "
        "<span style='color:#6af;'>V</span>ertical "
        "<span style='color:#6af;'>A</span>ngle "
        "<span style='color:#6af;'>O</span>ffset]:</span>")
    handler = XlinePickHandler(console, vp)
    if option in ('H', 'V'):
        handler.mode = option
        label = 'Horizontal' if option == 'H' else 'Vertical'
        handler._msg(f"XLINE {label}: Click a point")


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
