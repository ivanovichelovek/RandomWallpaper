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
from pathlib import Path

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

# One colour per season and holiday, for the category tags on the Downloaded
# tab: told apart at a glance, and each one what the category looks like —
# spring green, summer gold, autumn orange, winter ice. Bright enough to read
# on the near-black tiles, drawn over a dim tint of themselves.
CATEGORY_COLORS = {
    "spring": "#8FD694",
    "summer": "#F2C94C",
    "autumn": "#E8894A",
    "winter": "#8CC8F0",
    "halloween": "#B48CF0",
    "christmas": "#E86A6A",
    "valentine": "#F08CC0",
    "easter": "#C8E07A",
}

MONO_FONT = '"JetBrains Mono", "Consolas", "DejaVu Sans Mono", monospace'
SANS_FONT = '"Segoe UI", "Noto Sans", "Helvetica Neue", sans-serif'

# Stylesheet url()s want a path; forward slashes work on Windows too.
RESOURCES = (Path(__file__).resolve().parent.parent / "resources").as_posix()

QSS = f"""
/* Colour and type for everything, but a background only where one is
   meant: the window, the bars, the cards, the stage, the controls. A
   background on every QWidget painted each layout box and label in the
   window's colour over whatever it sat on — a lighter rectangle around the
   perforations on the darker stage, a darker one behind each label on a
   lighter card. */
QWidget {{
    color: {FG};
    font-family: {SANS_FONT};
    font-size: 13px;
}}
QMainWindow, #reelRoot, QDialog {{ background: {BG}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
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
/* The ‹ › frame buttons are QToolButtons; unstyled, Windows and macOS draw
   them as light native squares on the dark bar. */
QToolButton.icon {{
    background: {BG_BTN};
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 4px 10px;
    font-size: 15px;
}}
QToolButton.icon:hover {{ background: {BG_BTN_HOVER}; border-color: {BORDER_HOVER}; }}
QToolButton.icon:disabled {{ color: {FG_DISABLED}; background: #141622; border-color: {BG_BTN}; }}

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

QLineEdit, QSpinBox {{
    background: {BG_STAGE};
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 8px;
}}
QLineEdit:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QSpinBox::up-button, QSpinBox::down-button {{
    background: {BG_BTN}; border: none; width: 16px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {BG_BTN_HOVER}; }}
QSpinBox::up-arrow {{ image: url({RESOURCES}/arrow-up.svg); width: 8px; height: 5px; }}
QSpinBox::down-arrow {{ image: url({RESOURCES}/arrow-down.svg); width: 8px; height: 5px; }}

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

/* Text sitting on a card or a bar shows the card or bar through it. The
   QWidget rule above gives every widget the window's background, and on a
   lighter card that drew a dark box behind each label and check box. Named
   by type, not "#card QWidget": an id selector would outrank, and flatten,
   the buttons' and inputs' own backgrounds. */
#card QLabel, #card QCheckBox, #card QRadioButton,
#bottombar QLabel, #topbar QLabel, #confirm QLabel,
QWidget#barMeta {{ background: transparent; }}
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
/* The step arrows at the ends of a scroll bar. Styling the bar and its
   handle but not these leaves Fusion to draw them: a small white-edged box
   under every bar. The bars here are thin enough to do without them. */
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0; height: 0; border: none; background: none;
}}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QAbstractScrollArea::corner {{ background: transparent; border: none; }}
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


MONO_CANDIDATES = ["JetBrains Mono", "Cascadia Mono", "Consolas", "SF Mono",
                   "Menlo", "DejaVu Sans Mono", "Liberation Mono"]
SANS_CANDIDATES = ["Segoe UI", "Noto Sans", "Helvetica Neue", "Cantarell"]


def _first_installed(candidates, fallback):
    from PySide6.QtGui import QFontDatabase
    installed = set(QFontDatabase.families())
    for family in candidates:
        if family in installed:
            return family
    return QFontDatabase.systemFont(fallback).family()


def apply(app):
    """The stylesheet and palette, with the fonts this machine actually has.

    A stylesheet's font-family list is not a fallback chain in Qt: it takes
    the first name, and when that is not installed — JetBrains Mono on a
    stock Windows or Mac — it falls straight back to the default sans. So
    the families are chosen here, from what is installed, and "monospace"
    (which the inline styles use, and which only fontconfig knows) is
    mapped onto the same choice.
    """
    from PySide6.QtGui import QFont, QFontDatabase
    mono = _first_installed(MONO_CANDIDATES, QFontDatabase.FixedFont)
    sans = _first_installed(SANS_CANDIDATES, QFontDatabase.GeneralFont)
    QFont.insertSubstitution("monospace", mono)
    app.setStyleSheet(QSS.replace(MONO_FONT, f'"{mono}"')
                         .replace(SANS_FONT, f'"{sans}"'))
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
    # The bevel shades. Unset, Fusion derives them from its light default
    # and draws near-white lines — under the tabs, around frames — wherever
    # the stylesheet does not say otherwise.
    palette.setColor(QPalette.Light, QColor(BORDER_HOVER))
    palette.setColor(QPalette.Midlight, QColor(BORDER))
    palette.setColor(QPalette.Mid, QColor(BORDER))
    palette.setColor(QPalette.Dark, QColor(BG_STAGE))
    palette.setColor(QPalette.Shadow, QColor("#000000"))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(FG_DISABLED))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(FG_DISABLED))
    app.setPalette(palette)
