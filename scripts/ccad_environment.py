import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore, QtWidgets

class ClassicThemes:
    # Τα χρώματα από την εικόνα σου (AutoCAD 2024 style)
    COLORS = {
        "viewport_bg": "rgb(33, 40, 48)",
        "panel_bg": "#1c2026",      # Σκούρο ανθρακί για Panels/Ribbons
        "toolbar_bg": "#252930",    # Ελαφρώς πιο ανοιχτό για Toolbars
        "text_color": "#d1d1d1",    # Ανοιχτό γκρι κείμενο
        "accent": "#1b73e8",        # AutoCAD Blue για highlights
        "border": "#353a42"         # Διαχωριστικές γραμμές
    }

    @staticmethod
    def get_stylesheet():
        """Το 'μαγικό' CSS που αλλάζει όλο το UI του FreeCAD"""
        c = ClassicThemes.COLORS
        return f"""
            QMainWindow, QDialog, QDockWidget, QAbstractItemView, QListView, QTreeView {{
                background-color: {c['panel_bg']};
                color: {c['text_color']};
                border: none;
            }}
            QToolBar {{
                background-color: {c['toolbar_bg']};
                border-bottom: 1px solid {c['border']};
                spacing: 4px;
                padding: 2px;
            }}
            QToolButton:hover {{
                background-color: {c['border']};
                border: 1px solid {c['accent']};
            }}
            QMenuBar {{
                background-color: {c['panel_bg']};
                border-bottom: 1px solid {c['border']};
            }}
            QMenuBar::item:selected {{
                background-color: {c['accent']};
            }}
            QTabBar::tab {{
                background-color: {c['toolbar_bg']};
                color: {c['text_color']};
                padding: 6px 12px;
                border-right: 1px solid {c['border']};
            }}
            QTabBar::tab:selected {{
                background-color: {c['viewport_bg']};
                border-bottom: 2px solid {c['accent']};
            }}
            QHeaderView::section {{
                background-color: {c['toolbar_bg']};
                color: {c['text_color']};
                border: 1px solid {c['border']};
            }}
            QLineEdit, QTextEdit {{
                background-color: #0c0c0c;
                color: #2ecc71; /* Command line green */
                border: 1px solid {c['border']};
            }}
        """

    @staticmethod
    def apply_dark():
        # 1. Επιβολή 3D Viewport (RGB 33, 40, 48)
        # Υπολογισμός unsigned int για το FreeCAD
        bg_val = 556282111 
        v_s = App.ParamGet("User parameter:BaseApp/Preferences/View")
        v_s.SetUnsigned("BackgroundColor", bg_val)
        v_s.SetUnsigned("BackgroundColor2", bg_val)
        v_s.SetUnsigned("BackgroundColor3", bg_val)
        v_s.SetUnsigned("BackgroundColor4", bg_val)
        v_s.SetBool("UseGradient", False)
        v_s.SetInt("PickSize", 7)

        # 2. Επιβολή Grid
        d_s = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
        d_s.SetBool("Grid", True)
        d_s.SetFloat("GridSpacing", 10.0)
        d_s.SetInt("GridSize", 100)
        d_s.SetUnsigned("GridColor", 842150655) # Dark Grey

        # 3. Εφαρμογή Stylesheet σε ΟΛΟ το παράθυρο
        mw = Gui.getMainWindow()
        if mw:
            mw.setStyleSheet(ClassicThemes.get_stylesheet())
        
        Gui.updateGui()
        print("ClassicCAD: Dark Environment (AutoCAD Style) applied.")

def setup():
    # Καθυστέρηση μισού δευτερολέπτου για να προλάβει να ανοίξει το main window
    QtCore.QTimer.singleShot(500, ClassicThemes.apply_dark)

if __name__ == "__main__":
    setup()