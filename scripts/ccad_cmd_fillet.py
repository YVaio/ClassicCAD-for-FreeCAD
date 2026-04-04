"""FILLET command — AutoCAD-style fillet with persistent radius and custom solver."""

import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore
import time

# --- ΜΑΘΗΜΑΤΙΚΟΣ SOLVER ΓΙΑ TRIM/EXTEND (RADIUS = 0) ---

def get_endpoints(obj):
    if hasattr(obj, 'Start') and hasattr(obj, 'End'):
        return obj.Start, obj.End
    elif hasattr(obj, 'Points') and len(obj.Points) >= 2:
        return obj.Points[0], obj.Points[-1]
    return None, None

def set_endpoints(obj, start_pt, end_pt):
    if hasattr(obj, 'Start') and hasattr(obj, 'End'):
        obj.Start = start_pt
        obj.End = end_pt
    elif hasattr(obj, 'Points'):
        pts = list(obj.Points)
        pts[0] = start_pt
        pts[-1] = end_pt
        obj.Points = pts

def intersect_2d(A, B, C, D):
    x1, y1 = A.x, A.y
    x2, y2 = B.x, B.y
    x3, y3 = C.x, C.y
    x4, y4 = D.x, D.y

    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-6:
        return None # Παράλληλες γραμμές

    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    px = x1 + t * (x2 - x1)
    py = y1 + t * (y2 - y1)
    pz = A.z + t * (B.z - A.z)
    return App.Vector(px, py, pz)

def dist_point_to_segment(p, v, w):
    l2 = (v.x - w.x)**2 + (v.y - w.y)**2 + (v.z - w.z)**2
    if l2 == 0:
        return p.distanceToPoint(v)
    t = ((p.x - v.x)*(w.x - v.x) + (p.y - v.y)*(w.y - v.y) + (p.z - v.z)*(w.z - v.z)) / l2
    t = max(0.0, min(1.0, t))
    proj = App.Vector(v.x + t*(w.x - v.x), v.y + t*(w.y - v.y), v.z + t*(w.z - v.z))
    return p.distanceToPoint(proj)

def parse_vector(p):
    if p is None:
        return App.Vector(0, 0, 0)
    if hasattr(p, 'x'):
        return p
    if isinstance(p, (tuple, list)) and len(p) >= 3:
        return App.Vector(p[0], p[1], p[2])
    return App.Vector(0, 0, 0)

# --------------------------------------------------------

class FilletHandler:
    def __init__(self, console):
        self.console = console
        self.step = 0
        self._waiting_radius = False
        self._txn_open = False
        
        self.obj1 = None
        self.sub1 = None
        self.pnt1 = None
        
        self.obj2 = None
        self.sub2 = None
        self.pnt2 = None
        
        self.last_sel_time = time.time()
        
        if not hasattr(Gui, 'ccad_fillet_radius'):
            Gui.ccad_fillet_radius = 0.0
            
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)
        self._prompt()
        Gui.ccad_fillet_handler = self
        
    def _prompt(self):
        if self.step == 0:
            self.console.history.append(f"<span style='color:#aaa;'>FILLET: Select first object or [<span style='color:#6af;'>R</span>adius] (Current={Gui.ccad_fillet_radius}):</span>")
        elif self.step == 1:
            self.console.history.append("<span style='color:#aaa;'>FILLET: Select second object:</span>")

    def _open_transaction(self, name="Fillet"):
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
        if self._waiting_radius:
            Gui.Selection.clearSelection()
            return

        now = time.time()
        if now - self.last_sel_time < 0.2:
            return
        self.last_sel_time = now

        vec_pnt = parse_vector(pnt)

        if self.step == 0:
            self.obj1 = obj_name
            self.sub1 = sub if sub and "Edge" in sub else "Edge1"
            self.pnt1 = vec_pnt
            self.step = 1
            self._prompt()
            Gui.Selection.clearSelection()
            
        elif self.step == 1:
            if obj_name == self.obj1 and self.sub1 == (sub if sub and "Edge" in sub else "Edge1"):
                Gui.Selection.clearSelection()
                return
                
            self.obj2 = obj_name
            self.sub2 = sub if sub and "Edge" in sub else "Edge1"
            self.pnt2 = vec_pnt
            
            self.step = 2
            Gui.Selection.clearSelection()
            
            # ΔΙΑΦΥΓΗ ΑΠΟ ΤΟΝ OBSERVER
            QtCore.QTimer.singleShot(50, self._execute)
            
    def removeSelection(self, doc, obj_name, sub): pass
    def setSelection(self, doc): pass
    def clearSelection(self, doc): pass
        
    def _on_input(self):
        text = self.console.input.text().strip().upper()
        if self.step == 0 and text == 'R':
            self.console.history.append("<span style='color:#aaa;'>FILLET: Specify fillet radius:</span>")
            self._waiting_radius = True
            self.console.input.clear()
            return True
        elif self._waiting_radius:
            try:
                val = float(text)
                Gui.ccad_fillet_radius = val
                self.console.history.append(f"<span style='color:#55ff55;'>Radius set to {val}</span>")
                self._waiting_radius = False
                self._prompt()
                self.console.input.clear()
            except ValueError:
                self.console.history.append("<span style='color:#ff5555;'>Invalid number. Specify fillet radius:</span>")
                self.console.input.clear()
            return True
        return False
        
    def _execute(self):
        self.cleanup()
        
        o1 = App.ActiveDocument.getObject(self.obj1)
        o2 = App.ActiveDocument.getObject(self.obj2)
        
        if not o1 or not o2:
            self.console.history.append("<span style='color:#ff5555;'>FILLET: Invalid selection</span>")
            return
            
        A1, B1 = get_endpoints(o1)
        A2, B2 = get_endpoints(o2)
        
        if not A1 or not A2:
            self.console.history.append("<span style='color:#ff5555;'>FILLET Error: Can only fillet lines or wires.</span>")
            return
            
        I = intersect_2d(A1, B1, A2, B2)
        if not I:
            self.console.history.append("<span style='color:#ff5555;'>FILLET Error: Lines are parallel.</span>")
            return
            
        try:
            self._open_transaction("Fillet")

            dist1_A = dist_point_to_segment(self.pnt1, A1, I)
            dist1_B = dist_point_to_segment(self.pnt1, B1, I)
            if dist1_A <= dist1_B:
                set_endpoints(o1, A1, I)
            else:
                set_endpoints(o1, I, B1)
                
            dist2_A = dist_point_to_segment(self.pnt2, A2, I)
            dist2_B = dist_point_to_segment(self.pnt2, B2, I)
            if dist2_A <= dist2_B:
                set_endpoints(o2, A2, I)
            else:
                set_endpoints(o2, I, B2)
                
            App.ActiveDocument.recompute()
            self._commit_transaction()
        except Exception as exc:
            self._abort_transaction()
            self.console.history.append(f"<span style='color:#ff5555;'>FILLET Error: {str(exc)}</span>")
            return
        
        if Gui.ccad_fillet_radius > 0.0:
            # Δίνουμε 50ms στο FreeCAD να ενημερώσει το 3D View με τις ενωμένες γραμμές
            QtCore.QTimer.singleShot(50, self._apply_radius)
        else:
            self.console.history.append("<span style='color:#55ff55;'>FILLET: Done</span>")
            
    def _apply_radius(self):
        try:
            Gui.Selection.clearSelection()
            # Επιλέγουμε τις γραμμές ξανά, οι οποίες πλέον ακουμπάνε τέλεια.
            Gui.Selection.addSelection(App.ActiveDocument.Name, self.obj1, self.sub1)
            Gui.Selection.addSelection(App.ActiveDocument.Name, self.obj2, self.sub2)
            
            # Καρφώνουμε το Radius στα Settings
            App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft").SetFloat("filletRadius", Gui.ccad_fillet_radius)
            
            # Τρέχουμε το Native Command του FreeCAD. Θα δουλέψει ακαριαία χωρίς Task Panel.
            Gui.runCommand("Draft_Fillet")
            
            self.console.history.append("<span style='color:#55ff55;'>FILLET: Done</span>")
        except Exception as e:
            self.console.history.append(f"<span style='color:#ff5555;'>FILLET Arc Error: {str(e)}</span>")
        finally:
            QtCore.QTimer.singleShot(100, Gui.Selection.clearSelection)

    def cleanup(self):
        try:
            Gui.Selection.removeObserver(self)
        except:
            pass
        self._abort_transaction()
        Gui.Selection.clearSelection()
        Gui.ccad_fillet_handler = None

def run(console):
    if hasattr(Gui, 'ccad_fillet_handler') and Gui.ccad_fillet_handler:
        Gui.ccad_fillet_handler.cleanup()
    FilletHandler(console)