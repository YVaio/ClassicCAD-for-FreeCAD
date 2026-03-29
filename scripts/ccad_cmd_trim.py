"""TRIM and EXTEND commands."""

import FreeCADGui as Gui

def run(console, mode):
    # TRIM ή EXTEND
    if mode == 'TRIM':
        console.history.append("<span style='color:#aaa;'>TRIM: Select edge to trim, then select boundary.</span>")
    else:
        console.history.append("<span style='color:#aaa;'>EXTEND: Select edge to extend, then select boundary.</span>")
        
    Gui.runCommand("Draft_Trimex")