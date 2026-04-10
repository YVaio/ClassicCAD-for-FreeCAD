import importlib
import sys
import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtWidgets, QtCore


def _is_techdraw_page(obj):
    return bool(obj) and hasattr(obj, "isDerivedFrom") and obj.isDerivedFrom("TechDraw::DrawPage")


def _is_techdraw_view(obj):
    return bool(obj) and hasattr(obj, "isDerivedFrom") and obj.isDerivedFrom("TechDraw::DrawView")


def _is_techdraw_object(obj):
    type_id = getattr(obj, "TypeId", "")
    return isinstance(type_id, str) and type_id.startswith("TechDraw::")


def _page_from_object(obj):
    if _is_techdraw_page(obj):
        return obj
    if _is_techdraw_view(obj) and hasattr(obj, "findParentPage"):
        try:
            return obj.findParentPage()
        except Exception:
            return None
    return None


def _selected_techdraw_pages():
    pages = []
    try:
        for obj in Gui.Selection.getSelection():
            page = _page_from_object(obj)
            if page and page not in pages:
                pages.append(page)
    except Exception:
        pass
    return pages


def _active_mdi_title():
    try:
        main_window = Gui.getMainWindow()
        if not main_window:
            return ""
        for mdi_area in main_window.findChildren(QtWidgets.QMdiArea):
            sub_window = mdi_area.activeSubWindow()
            if sub_window:
                return (sub_window.windowTitle() or "").strip()
    except Exception:
        pass
    return ""


def _page_names(page):
    names = []
    for attr in ("Label", "Name"):
        value = getattr(page, attr, "")
        if isinstance(value, str):
            value = value.strip()
            if value and value not in names:
                names.append(value)
    if hasattr(page, "getNameInDocument"):
        try:
            value = page.getNameInDocument()
            if value and value not in names:
                names.append(value)
        except Exception:
            pass
    return names


def _pages_matching_active_window(doc):
    title = _active_mdi_title()
    if not title:
        return []

    pages = []
    lowered_title = title.casefold()
    for obj in doc.Objects:
        if not _is_techdraw_page(obj):
            continue
        names = _page_names(obj)
        if any(name.casefold() == lowered_title or name.casefold() in lowered_title for name in names):
            pages.append(obj)
    return pages


def _visible_techdraw_pages(doc):
    pages = []
    for obj in doc.Objects:
        if not _is_techdraw_page(obj):
            continue
        view_object = getattr(obj, "ViewObject", None)
        if view_object and getattr(view_object, "Visibility", False):
            pages.append(obj)
    return pages


def _resolve_regen_pages(doc):
    pages = _pages_matching_active_window(doc)
    if pages:
        return pages

    return []


def _redraw_techdraw_page_if_needed(doc):
    pages = _resolve_regen_pages(doc)
    if not pages:
        return False

    try:
        Gui.runCommand("TechDraw_RedrawPage", 0)
        Gui.updateGui()
        labels = ", ".join(page.Label or page.Name for page in pages)
        App.Console.PrintLog(f"REGEN: Redrew TechDraw page: {labels}\n")
    except Exception as exc:
        App.Console.PrintWarning(f"REGEN: TechDraw page redraw skipped: {exc}\n")
    return True

def REGEN():
    """Εντολή REGEN: Δυναμική εξομάλυνση και επαναϋπολογισμός σύνθετης γεωμετρίας (Splines, Beziers, κλπ)."""
    try:
        doc = App.ActiveDocument
        if not doc: return
        view = Gui.activeView()

        # Υπολογισμός Camera Height για Orthographic
        visible_height = 100
        if view and hasattr(view, "getCameraNode"):
            try:
                camera = view.getCameraNode()
                if hasattr(camera, "height"):
                    visible_height = camera.height.getValue()
            except Exception:
                pass

        # Δυναμικό Deviation βάσει zoom (όσο πιο κοντά, τόσο πιο μικρό deviation = πιο ομαλό)
        dynamic_deviation = visible_height * 0.001
        if dynamic_deviation < 0.0005: dynamic_deviation = 0.0005

        if _redraw_techdraw_page_if_needed(doc):
            App.Console.PrintLog(f"REGEN: Done. Active TechDraw page redrawn.\n")
            return

        # Τύποι που αγνοούμε (απλές γραμμές και σημεία) για ταχύτητα
        simple_types = ('Part::Line', 'App::Origin', 'App::Plane')
        recompute_targets = []

        for obj in doc.Objects:
            if _is_techdraw_object(obj):
                continue

            # 1. Έλεγχος αν το αντικείμενο έχει Shape (άρα είναι γεωμετρία)
            if hasattr(obj, "Shape"):
                
                # 2. Αν δεν είναι απλή γραμμή, το μαρκάρουμε για πλήρη αναγέννηση
                # Αυτό επιβάλλει στις Splines/Beziers να ξαναφτιάξουν το πλέγμα τους
                if obj.TypeId not in simple_types:
                    obj.touch()
                    recompute_targets.append(obj)

                # 3. Ρύθμιση Deviation στο ViewObject για οπτική εξομάλυνση
                if hasattr(obj, 'ViewObject') and obj.ViewObject:
                    vo = obj.ViewObject
                    if hasattr(vo, "Deviation"):
                        vo.Deviation = dynamic_deviation
                    if hasattr(vo, "AngularDeflection"):
                        vo.AngularDeflection = dynamic_deviation * 10
        
        # 4. Επαναϋπολογισμός μόνο των 3D/model objects του ενεργού view.
        if recompute_targets:
            doc.recompute(recompute_targets)
        Gui.updateGui()
        App.Console.PrintLog(f"REGEN: Done. Complex geometry smoothed (Deviation: {dynamic_deviation:.4f})\n")
    except Exception as e:
        App.Console.PrintError(f"REGEN Error: {str(e)}\n")

def reload_classic_cad():
    """Πλήρες Reload του συστήματος ClassicCAD (Global Mode)"""
    App.Console.PrintLog("\n" + "#"*30 + "\n")
    App.Console.PrintLog("  CLASSIC CAD: DEEP RESET...\n")
    App.Console.PrintLog("#"*30 + "\n")
    
    # Η λίστα των modules
    modules_to_reload = [
        "ccad_cmd_xline",
        "ccad_cmd_trim",
        "ccad_cmd_join",
        "ccad_cmd_spline",
        "ccad_cmd_fillet",
        "ccad_console",
        "ccad_cursor",
        "ccad_selection",
        "ccad_draft_tools",
        "ccad_layers",
        "ccad_status_bar",
        "ccad_dev_tools" # Must be last
    ]

    # 1. ΚΑΘΑΡΙΣΜΟΣ EVENT FILTERS (Πριν το tear_down)
    app = QtWidgets.QApplication.instance()
    if hasattr(Gui, "classic_console"):
        try:
            app.removeEventFilter(Gui.classic_console)
            App.Console.PrintLog("EventFilter removed from Console.\n")
        except: pass

    # 2. TEAR DOWN (Με ανάποδη σειρά)
    for mod_name in reversed(modules_to_reload):
        if mod_name in sys.modules and mod_name != "ccad_dev_tools":
            mod = sys.modules[mod_name]
            if hasattr(mod, "tear_down"):
                try:
                    mod.tear_down()
                    App.Console.PrintLog(f"Cleaned: {mod_name}\n")
                except Exception as e:
                    App.Console.PrintLog(f"Skip Cleanup {mod_name}: {e}\n")

    # 3. RELOAD ΚΑΙ SETUP
    for mod_name in modules_to_reload:
        try:
            # ΕΙΔΙΚΟΣ ΧΕΙΡΙΣΜΟΣ ΓΙΑ ΤΟ DEV TOOLS
            if mod_name == "ccad_dev_tools":
                # Δεν κάνουμε setup εδώ, γιατί θα ξανακαλούσε την reload_classic_cad
                importlib.reload(sys.modules[mod_name])
                App.Console.PrintLog("Reloaded: ccad_dev_tools (self)\n")
                continue

            if mod_name in sys.modules:
                reloaded = importlib.reload(sys.modules[mod_name])
                if hasattr(reloaded, "setup"):
                    reloaded.setup()
                App.Console.PrintLog(f"Reloaded & Setup: {mod_name}\n")
            else:
                importlib.import_module(mod_name)
                App.Console.PrintLog(f"Imported: {mod_name}\n")
        except Exception as e:
            App.Console.PrintError(f"Failed {mod_name}: {str(e)}\n")

    App.Console.PrintLog("#"*30 + "\n")

def setup():
    """Προαιρετικό setup για το dev_tools"""
    pass

def tear_down():
    """Καθαρισμός πριν το reload"""
    pass