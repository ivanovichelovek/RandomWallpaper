"""The look: a contact sheet on a light table.

Near-black with a blue bias, hairline borders instead of shadows, one warm
accent, monospace for anything numeric — the same palette the GTK version
used, carried over to Qt style sheets and an explicit QPalette.

Qt popups (combo box drop-downs, menus) are top-level windows of their own
and do not inherit a widget's style sheet the way a GTK popover inherits from
its parent's CSS provider, so the palette below is set application-wide and
the stylesheet below addresses `QComboBox QAbstractItemView` directly rather
than relying on inheritance.
"""
from PySide6.QtGui import QColor, QPalette

BG = "#0E0F16"
BG_STAGE = "#0A0B10"
BG_BAR = "#171925"
BG_CARD = "#171925"
BG_BTN = "#1E2130"
BG_BTN_HOVER = "#262A3D"
BORDER = "#262A3D"
BORDER_HOVER = "#39405C"
FG = "#E6E7F0"
FG_DIM = "#8B90A8"
FG_DISABLED = "#4C5170"
ACCENT = "#F2D98C"
ACCENT_HOVER = "#F7E4A8"
ACCENT_ACTIVE = "#D9C079"
DANGER = "#E06C6C"
DANGER_BG = "#33202A"
DANGER_BORDER = "#6B3A44"

MONO_FONT = '"JetBrains Mono", "Consolas", "DejaVu Sans Mono", monospace'
SANS_FONT = '"Segoe UI", "Noto Sans", "Helvetica Neue", sans-serif'

QSS = f"""
QWidget {{
    background: {BG};
    color: {FG};
    font-family: {SANS_FONT};
    font-size: 13px;
}}
#topbar, #bottombar {{
    background: {BG_BAR};
    border: 0px solid {BORDER};
}}
#topbar {{ border-bottom: 1px solid {BORDER}; }}
#bottombar {{ border-top: 1px solid {BORDER}; }}

#wordmark {{
    font-family: {MONO_FONT};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
    color: {ACCENT};
}}
.eyebrow {{
    font-family: {MONO_FONT};
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1.6px;
    color: {FG_DIM};
}}
.mono {{
    font-family: {MONO_FONT};
    font-size: 11px;
    color: {FG_DIM};
}}
#frameName {{
    font-family: {MONO_FONT};
    font-size: 13px;
    color: {FG};
}}

#stage {{ background: {BG_STAGE}; }}

QTabWidget::pane {{ border: 0; background: transparent; }}
QTabBar::tab {{
    background: transparent;
    color: {FG_DIM};
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 6px 16px;
    margin: 2px;
    font-size: 12px;
}}
QTabBar::tab:hover {{ background: {BG_BTN_HOVER}; color: {FG}; }}
QTabBar::tab:selected {{
    background: {BG_BTN_HOVER};
    border-color: {BORDER_HOVER};
    color: {ACCENT};
    font-weight: 700;
}}

#library {{ background: {BG_STAGE}; }}
QListWidget#library {{
    border: none;
}}
QListWidget#library::item {{
    padding: 6px;
    border: 1px solid {BORDER};
    border-radius: 5px;
    background: #14151F;
    margin: 4px;
}}
QListWidget#library::item:hover {{ border-color: {BORDER_HOVER}; }}
QListWidget#library::item:selected {{
    border-color: {ACCENT};
    background: #1E2130;
    color: {FG};
}}

#confirm {{
    background: {DANGER_BG};
    border-top: 1px solid {DANGER_BORDER};
    border-bottom: 1px solid {DANGER_BORDER};
}}
#confirmText {{ color: {FG}; font-size: 12px; }}

#tileTags {{
    font-family: {MONO_FONT};
    font-size: 10px;
    color: {ACCENT};
}}

QPushButton {{
    background: {BG_BTN};
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 7px 16px;
    font-size: 13px;
}}
QPushButton:hover {{ background: {BG_BTN_HOVER}; border-color: {BORDER_HOVER}; }}
QPushButton:pressed {{ background: {BG_BAR}; }}
QPushButton:disabled {{ color: {FG_DISABLED}; border-color: {BG_BTN}; background: #141622; }}
QPushButton:focus {{ outline: none; border: 1px solid {ACCENT}; }}

QPushButton.accent {{
    background: {ACCENT};
    color: #14151F;
    border-color: {ACCENT};
    font-weight: 700;
}}
QPushButton.accent:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton.accent:pressed {{ background: {ACCENT_ACTIVE}; }}
QPushButton.accent:disabled {{ background: #141622; color: {FG_DISABLED}; border-color: {BG_BTN}; }}

QPushButton.danger {{ color: {DANGER}; border-color: {DANGER_BORDER}; }}
QPushButton.danger:hover {{ background: {DANGER_BG}; border-color: {DANGER_BORDER}; }}

QPushButton.icon {{ padding: 6px 12px; font-size: 15px; }}

#reel {{ background: {BG_STAGE}; border-top: 1px solid {BORDER}; }}
QToolButton.reelFrame {{
    border: 1px solid {BORDER};
    border-radius: 3px;
    background: #14151F;
    padding: 0;
}}
QToolButton.reelFrame:hover {{ border-color: {BORDER_HOVER}; }}
QToolButton.reelFrame[current="true"] {{ border-color: {ACCENT}; border-width: 2px; }}
.perf {{ background: {FG_DIM}; border-radius: 1px; }}

#toast {{
    background: {BG_BTN_HOVER};
    color: {FG};
    border: 1px solid {BORDER_HOVER};
    border-radius: 5px;
    padding: 9px 14px;
    font-size: 12px;
}}
.hint {{ color: {DANGER}; font-size: 12px; }}
.placeholder {{ color: {FG_DISABLED}; font-size: 13px; }}

#card {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}

QLineEdit {{
    background: {BG_STAGE};
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 8px;
}}
QLineEdit:focus {{ border-color: {ACCENT}; }}

QComboBox {{
    background: {BG_BTN};
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 8px;
}}
QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {BG_CARD};
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    selection-background-color: {ACCENT};
    selection-color: #14151F;
    outline: none;
}}

QCheckBox, QRadioButton {{ color: {FG}; font-size: 13px; spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px; height: 14px;
    background: {BG_STAGE};
    border: 1px solid {BORDER_HOVER};
}}
QRadioButton::indicator {{ border-radius: 7px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {BORDER_HOVER}; border-radius: 5px; min-height: 24px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_HOVER}; border-radius: 5px; min-width: 24px; }}

QMenu {{
    background: {BG_CARD};
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{ padding: 7px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {BG_BTN_HOVER}; }}
"""


def apply(app):
    app.setStyleSheet(QSS)
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BG))
    palette.setColor(QPalette.WindowText, QColor(FG))
    palette.setColor(QPalette.Base, QColor(BG_STAGE))
    palette.setColor(QPalette.AlternateBase, QColor(BG_CARD))
    palette.setColor(QPalette.Text, QColor(FG))
    palette.setColor(QPalette.Button, QColor(BG_BTN))
    palette.setColor(QPalette.ButtonText, QColor(FG))
    palette.setColor(QPalette.ToolTipBase, QColor(BG_CARD))
    palette.setColor(QPalette.ToolTipText, QColor(FG))
    palette.setColor(QPalette.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor("#14151F"))
    palette.setColor(QPalette.PlaceholderText, QColor(FG_DISABLED))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(FG_DISABLED))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(FG_DISABLED))
    app.setPalette(palette)
