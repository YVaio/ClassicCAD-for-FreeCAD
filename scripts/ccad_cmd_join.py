"""JOIN command — AutoCAD-style wire joining for FreeCAD.

Collects all vertex points from selected lines/wires in order and
creates a single Draft Wire, removing the originals.
"""

import FreeCAD as App
import FreeCADGui as Gui


def _collect_points(objects):
    """Return an ordered list of points from lines/wires, chaining endpoints."""
    import Part
    edges = []
    for obj in objects:
        if hasattr(obj, 'Shape') and obj.Shape.Edges:
            for e in obj.Shape.Edges:
                edges.append(e)
    if not edges:
        return []

    # Build chains: pick first edge, then find adjacent edges
    remaining = list(edges)
    chain = remaining.pop(0)
    points = [chain.Vertexes[0].Point, chain.Vertexes[-1].Point]

    changed = True
    while remaining and changed:
        changed = False
        for i, e in enumerate(remaining):
            ep0, ep1 = e.Vertexes[0].Point, e.Vertexes[-1].Point
            tol = 0.01
            if points[-1].distanceToPoint(ep0) < tol:
                points.append(ep1)
                remaining.pop(i)
                changed = True
                break
            elif points[-1].distanceToPoint(ep1) < tol:
                points.append(ep0)
                remaining.pop(i)
                changed = True
                break
            elif points[0].distanceToPoint(ep1) < tol:
                points.insert(0, ep0)
                remaining.pop(i)
                changed = True
                break
            elif points[0].distanceToPoint(ep0) < tol:
                points.insert(0, ep1)
                remaining.pop(i)
                changed = True
                break
    return points


def run(console):
    """Execute JOIN on the current selection."""
    try:
        import Draft
        sel = Gui.Selection.getSelection()
        if not sel:
            console.history.append(
                "<span style='color:#ff5555;'>JOIN: No objects selected</span>")
            return

        if hasattr(App, 'activeDraftCommand') and App.activeDraftCommand:
            try:
                Gui.Control.closeDialog()
            except Exception:
                pass

        blocker = getattr(Gui, 'ccad_auto_blocker', None)
        if blocker:
            blocker._opening_grips = True
            blocker._gripped_objects = []
        pickadd = getattr(Gui, 'ccad_pickadd_filter', None)
        if pickadd:
            pickadd._escaping = True
            pickadd.previous_selection = []

        points = _collect_points(sel)
        if len(points) < 2:
            console.history.append(
                "<span style='color:#ff5555;'>JOIN: Not enough connected edges</span>")
            if blocker:
                blocker._opening_grips = False
            if pickadd:
                pickadd._escaping = False
            return

        doc = App.ActiveDocument
        # Capture visual properties from first object
        lc = None
        for obj in sel:
            if hasattr(obj, 'ViewObject') and hasattr(obj.ViewObject, 'LineColor'):
                lc = tuple(obj.ViewObject.LineColor[:3]) + (0.0,)
                break

        # Remove originals
        names_to_remove = [obj.Name for obj in sel]
        for n in names_to_remove:
            if doc.getObject(n):
                doc.removeObject(n)

        # Check if closed
        closed = points[0].distanceToPoint(points[-1]) < 0.01
        if closed and len(points) > 2:
            points = points[:-1]

        wire = Draft.make_wire(points, closed=closed, face=False)
        if lc and hasattr(wire, 'ViewObject'):
            wire.ViewObject.LineColor = lc
        doc.recompute()

        Gui.Selection.clearSelection()
        if blocker:
            blocker._opening_grips = False
        if pickadd:
            pickadd._escaping = False

        console.history.append("<span style='color:#55ff55;'>JOIN: Done</span>")

    except Exception as e:
        console.history.append(
            f"<span style='color:red;'>JOIN failed: {str(e)}</span>")
        blocker = getattr(Gui, 'ccad_auto_blocker', None)
        if blocker:
            blocker._opening_grips = False
        pickadd = getattr(Gui, 'ccad_pickadd_filter', None)
        if pickadd:
            pickadd._escaping = False
