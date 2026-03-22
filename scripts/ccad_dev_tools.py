import importlib
import sys
import FreeCAD as App
import FreeCADGui as Gui

def reload_classic_cad():
    App.Console.PrintLog("\n" + "="*20 + " RELOAD " + "="*20 + "\n")
    
    # Παίρνουμε τη λίστα από το Instance που ζει στο Gui
    instance = getattr(Gui, "ccad_global_active", None)
    if not instance:
        App.Console.PrintError("Global system instance not found.\n")
        return
        
    modules = getattr(instance, "active_modules", [])
    
    for mod_name in modules:
        if mod_name == "ccad_dev_tools": continue
        try:
            if mod_name in sys.modules:
                reloaded = importlib.reload(sys.modules[mod_name])
                if hasattr(reloaded, "setup"):
                    reloaded.setup()
                App.Console.PrintLog(f"OK: {mod_name}\n")
        except Exception as e:
            App.Console.PrintError(f"ERR: {mod_name} -> {str(e)}\n")
            
    App.Console.PrintLog("="*48 + "\n")