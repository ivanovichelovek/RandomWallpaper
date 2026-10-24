"""The look: the wallpaper picks the colours.

One hue — taken from the picture on screen, or a fixed one — becomes a
small set of tokens (ground, surface, well, border, text, accent …) for a
dark or a light window, and those fill both the stylesheet and the QPalette.
Nothing else in the UI names a colour: pages give widgets an objectName or a
"class" property and the stylesheet below says what that looks like, so a
new hue repaints everything at once.

Qt popups (combo box drop-downs, menus) are top-level windows of their own
and do not inherit a widget's style sheet, so the palette is set
application-wide and the stylesheet addresses `QComboBox QAbstractItemView`
and `QMenu` directly.
"""
import colorsys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import QAbstractButton, QApplication, QCheckBox

from ..paths import IS_ANDROID

# One colour per season and holiday, for the category marks on the Saved tab:
# told apart at a glance, and each one what the category looks like — spring
# green, summer gold, autumn orange, winter ice. They do not follow the tint.
CATEGORY_COLORS = {
    "spring": "#8FD694",
    "summer": "#F2C94C",
    "autumn": "#E8894A",
    "winter": "#8CC8F0",
    "halloween": "#B48CF0",
    "christmas": "#E86A6A",
    "valentine": "#F08CC0",
    "easter": "#C8E07A",
    "shuffle": "#F2D98C",
}

FONTS_DIR = Path(__file__).resolve().parent.parent / "resources" / "fonts"
SANS = "Space Grotesk"
MONO = "DM Mono"

# The fixed colour, and the hue a grey picture falls back to: ember.
DEFAULT_SEED = (22 / 360, 0.75)


# ── tokens ──────────────────────────────────────────────────────────────────
def _hsl(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return "#{:02X}{:02X}{:02X}".format(round(r * 255), round(g * 255), round(b * 255))


def tokens(seed=DEFAULT_SEED, dark=True):
    """The colours for one hue. Lightness is fixed per token and saturation
    clamped, whatever the picture: a neon or a grey wallpaper still gives
    text that reads on its ground."""
    h, s = seed
    tint = min(s, 0.6)          # how much of the hue the neutrals carry
    if dark:
        return {
            "bg": _hsl(h, tint * 0.45, 0.085),
            "surface": _hsl(h, tint * 0.42, 0.135),
            "well": _hsl(h, tint * 0.38, 0.185),
            "border": _hsl(h, tint * 0.32, 0.22),
            "fg": _hsl(h, tint * 0.55, 0.94),
            "dim": _hsl(h, tint * 0.22, 0.72),
            "faint": _hsl(h, tint * 0.18, 0.42),
            "accent": _hsl(h, max(0.5, min(s, 0.85)), 0.70),
            "accentText": _hsl(h, max(0.5, min(s, 0.85)), 0.80),
            "accentSoft": _hsl(h, tint * 0.6, 0.20),
            "onAccent": _hsl(h, 0.6, 0.10),
            "danger": "#FF9C8A",
            "dangerSoft": "#3A1F22",
            "shadow": "#000000",
        }
    return {
        "bg": _hsl(h, tint * 0.75, 0.965),
        "surface": "#FFFFFF",
        "well": _hsl(h, tint * 0.65, 0.92),
        "border": _hsl(h, tint * 0.5, 0.86),
        "fg": _hsl(h, tint * 0.55, 0.12),
        "dim": _hsl(h, tint * 0.2, 0.38),
        "faint": _hsl(h, tint * 0.15, 0.62),
        "accent": _hsl(h, max(0.5, min(s, 0.8)), 0.42),
        "accentText": _hsl(h, max(0.5, min(s, 0.8)), 0.33),
        "accentSoft": _hsl(h, max(0.45, min(s, 0.8)), 0.91),
        "onAccent": "#FFFFFF",
        "danger": "#B3261E",
        "dangerSoft": "#FBE4E1",
        "shadow": "#000000",
    }


def seed_from_image(image):
    """The hue (and how colourful it is) of a QImage, as (h, s) in 0–1.

    The most colourful hue rather than the average: an average of a blue sky
    and an orange street is a muddy grey nobody sees in the picture. Hues are
    binned and each pixel votes with its saturation × value, so dark and
    washed-out pixels count for little. A picture with nothing colourful in
    it falls back to the default hue, barely saturated.
    """
    if image is None or image.isNull():
        return DEFAULT_SEED
    small = image.scaled(32, 32, Qt.IgnoreAspectRatio, Qt.FastTransformation)
    bins = [0.0] * 36
    sats = [0.0] * 36
    for y in range(small.height()):
        for x in range(small.width()):
            c = small.pixelColor(x, y)
            h, s, v = c.hsvHueF(), c.hsvSaturationF(), c.valueF()
            if h < 0 or s < 0.12 or v < 0.15:
                continue
            weight = s * v
            k = int(h * 36) % 36
            bins[k] += weight
            sats[k] += s * weight
    total = sum(bins)
    if total < 4:                       # a grey, black or white picture
        return (DEFAULT_SEED[0], 0.12)
    best = max(range(36), key=lambda k: bins[k] + 0.5 * (bins[k - 1] + bins[(k + 1) % 36]))
    return ((best + 0.5) / 36, sats[best] / bins[best] if bins[best] else 0.5)


def palette_from_image(image, count=5):
    """The few colours that make up a picture, most of it first — the
    swatches shown beside a frame's name."""
    if image is None or image.isNull():
        return []
    small = image.scaled(24, 24, Qt.IgnoreAspectRatio, Qt.FastTransformation)
    buckets = {}
    for y in range(small.height()):
        for x in range(small.width()):
            c = small.pixelColor(x, y)
            # 4 levels a channel: near colours fall in one bucket.
            key = (c.red() // 64, c.green() // 64, c.blue() // 64)
            sums = buckets.setdefault(key, [0, 0, 0, 0])
            sums[0] += c.red()
            sums[1] += c.green()
            sums[2] += c.blue()
            sums[3] += 1
    top = sorted(buckets.values(), key=lambda v: -v[3])[:count]
    return ["#{:02X}{:02X}{:02X}".format(r // n, g // n, b // n) for r, g, b, n in top]


# ── the stylesheet ──────────────────────────────────────────────────────────
def build_qss(t, sans=SANS, mono=MONO):
    base = "15px" if IS_ANDROID else "13px"
    return f"""
QWidget {{
    color: {t['fg']};
    font-family: "{sans}";
    font-size: {base};
}}
QMainWindow, #root, QDialog {{ background: {t['bg']}; }}
QScrollArea, QScrollArea > QWidget > QWidget, QStackedWidget {{ background: transparent; }}
QToolTip {{ background: {t['surface']}; color: {t['fg']}; border: 1px solid {t['border']}; padding: 4px 6px; }}

/* ── navigation ── */
#rail, #bottomNav {{ background: {t['bg']}; }}
#bottomNav {{ border-top: 1px solid {t['border']}; }}
QToolButton.nav {{
    background: transparent;
    color: {t['dim']};
    border: 2px solid transparent;
    border-radius: 24px;
    padding: 0;
}}
QToolButton.nav:hover {{ background: {t['well']}; }}
QToolButton.nav:checked {{ background: {t['accentSoft']}; color: {t['accentText']}; }}
QToolButton.navBottom {{
    background: transparent;
    color: {t['dim']};
    border: 2px solid transparent;
    border-radius: 14px;
    padding: 4px 0;
    font-size: 12px;
}}
QToolButton.navBottom:checked {{ color: {t['accentText']}; font-weight: 600; }}

/* ── text ── */
.h1 {{ font-size: 24px; font-weight: 700; }}
.h2 {{ font-size: 16px; font-weight: 700; }}
.title {{ font-size: 14px; font-weight: 600; }}
.help {{ color: {t['dim']}; font-size: 12px; }}
.mono {{ font-family: "{mono}"; font-size: 11px; color: {t['dim']}; }}
.strong {{ font-weight: 600; }}
.error {{ color: {t['danger']}; font-size: 12px; }}
.accentText {{ color: {t['accentText']}; font-weight: 600; }}
.placeholder {{ color: {t['faint']}; font-size: 14px; }}

/* ── surfaces ── */
QFrame.card {{ background: {t['surface']}; border-radius: 18px; }}
QFrame.card QLabel, QFrame.card QCheckBox, QFrame.card QRadioButton {{ background: transparent; }}
QFrame.note {{ background: {t['accentSoft']}; border-radius: 14px; }}
QFrame.note QLabel {{ background: transparent; }}
QFrame.rule {{ background: {t['border']}; border: none; max-height: 1px; min-height: 1px; }}
QFrame.picture {{ background: {t['surface']}; border-radius: 20px; }}
#pill {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 24px; }}
#pill QLabel {{ background: transparent; }}
#confirm {{ background: {t['dangerSoft']}; border: 1px solid {t['danger']}; border-radius: 18px; }}
#confirm QLabel {{ background: transparent; }}
#toast {{
    background: {t['surface']};
    color: {t['fg']};
    border: 1px solid {t['border']};
    border-radius: 14px;
    padding: 10px 16px;
    font-size: 12px;
}}

/* ── buttons ── */
QPushButton {{
    background: {t['well']};
    color: {t['fg']};
    border: 2px solid transparent;
    border-radius: 14px;
    padding: 6px 14px;
    min-height: 20px;
    font-weight: 600;
}}
QPushButton:hover {{ background: {t['border']}; }}
QPushButton:disabled {{ color: {t['faint']}; background: {t['well']}; }}
QPushButton:focus {{ outline: none; }}
QPushButton.accent {{ background: {t['accent']}; color: {t['onAccent']}; font-weight: 700; }}
QPushButton.accent:hover {{ background: {t['accentText']}; }}
QPushButton.accent:disabled {{ background: {t['well']}; color: {t['faint']}; }}
QPushButton.danger {{ color: {t['danger']}; }}
QPushButton.danger:disabled {{ color: {t['faint']}; }}
QPushButton.round {{ border-radius: 20px; padding: 0; min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; font-size: 18px; }}
QPushButton.flat {{ background: transparent; }}
QPushButton.flat:hover {{ background: {t['well']}; }}
QPushButton::menu-indicator {{ width: 0; image: none; }}

/* a segmented control: checkable buttons in a pill */
QFrame.segmented {{ background: {t['well']}; border-radius: 15px; }}
QPushButton.seg {{
    background: transparent;
    color: {t['dim']};
    border-radius: 12px;
    padding: 3px 10px;
    min-height: 18px;
    font-weight: 500;
}}
QPushButton.seg:hover {{ color: {t['fg']}; }}
QPushButton.seg:checked {{ background: {t['surface']}; color: {t['fg']}; font-weight: 700; }}
QFrame.segmented[strong="true"] QPushButton.seg:checked {{ background: {t['accent']}; color: {t['onAccent']}; }}

/* where the keyboard is: see FocusRing */
QPushButton[kbfocus="true"], QToolButton[kbfocus="true"] {{ border-color: {t['fg']}; }}
QRadioButton[kbfocus="true"]::indicator, QCheckBox[kbfocus="true"]::indicator {{ border-color: {t['fg']}; }}
QFrame.choice[kbfocus="true"] {{ border-color: {t['fg']}; }}

/* a radio card: the whole card is the choice */
QFrame.choice {{ background: transparent; border: 2px solid {t['border']}; border-radius: 14px; }}
QFrame.choice[checked="true"] {{ background: {t['accentSoft']}; border-color: {t['accent']}; }}
QFrame.choice QLabel, QFrame.choice QRadioButton {{ background: transparent; }}

/* ── inputs ── */
QLineEdit, QSpinBox {{
    background: {t['well']};
    color: {t['fg']};
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 7px 10px;
    selection-background-color: {t['accent']};
    selection-color: {t['onAccent']};
}}
QLineEdit:focus, QSpinBox:focus {{ border-color: {t['accent']}; }}
QTextBrowser {{
    background: {t['well']}; color: {t['fg']};
    border: 1px solid transparent; border-radius: 12px; padding: 6px 10px;
}}
QTextBrowser:focus {{ border-color: {t['accent']}; }}
QLineEdit#search {{ border-radius: 16px; padding: 7px 14px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
QComboBox {{
    background: {t['well']};
    color: {t['fg']};
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 7px 12px;
    font-weight: 600;
}}
QComboBox:focus {{ border-color: {t['accent']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {t['surface']};
    color: {t['fg']};
    border: 1px solid {t['border']};
    border-radius: 10px;
    padding: 4px;
    selection-background-color: {t['accentSoft']};
    selection-color: {t['fg']};
    outline: none;
}}
QCheckBox, QRadioButton {{ color: {t['fg']}; spacing: 10px; }}
QRadioButton::indicator, QCheckBox::indicator {{
    width: 16px; height: 16px;
    background: {t['well']};
    border: 2px solid {t['faint']};
}}
QRadioButton::indicator {{ border-radius: 10px; }}
QCheckBox::indicator {{ border-radius: 5px; }}
QRadioButton::indicator:checked, QCheckBox::indicator:checked {{
    background: {t['accent']};
    border-color: {t['accent']};
}}

/* ── lists and scrolling ── */
QListWidget#library {{ background: transparent; border: none; outline: none; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QAbstractScrollArea::corner {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 3px; min-height: 28px; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px 4px; }}
QScrollBar::handle:horizontal {{ background: {t['border']}; border-radius: 3px; min-width: 28px; }}

QMenu {{
    background: {t['surface']};
    color: {t['fg']};
    border: 1px solid {t['border']};
    border-radius: 12px;
    padding: 6px;
}}
QMenu::item {{ padding: 8px 14px; border-radius: 8px; }}
QMenu::item:selected {{ background: {t['well']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 8px; }}
"""


def build_palette(t):
    p = QPalette()
    for group in (QPalette.Active, QPalette.Inactive):
        p.setColor(group, QPalette.Window, QColor(t["bg"]))
        p.setColor(group, QPalette.WindowText, QColor(t["fg"]))
        p.setColor(group, QPalette.Base, QColor(t["well"]))
        p.setColor(group, QPalette.AlternateBase, QColor(t["surface"]))
        p.setColor(group, QPalette.Text, QColor(t["fg"]))
        p.setColor(group, QPalette.Button, QColor(t["well"]))
        p.setColor(group, QPalette.ButtonText, QColor(t["fg"]))
        p.setColor(group, QPalette.ToolTipBase, QColor(t["surface"]))
        p.setColor(group, QPalette.ToolTipText, QColor(t["fg"]))
        p.setColor(group, QPalette.Highlight, QColor(t["accent"]))
        p.setColor(group, QPalette.HighlightedText, QColor(t["onAccent"]))
        p.setColor(group, QPalette.PlaceholderText, QColor(t["dim"]))
        p.setColor(group, QPalette.BrightText, QColor(t["danger"]))
        # The bevel shades. Unset, Fusion derives them from its light default
        # and draws near-white lines wherever the stylesheet says nothing.
        p.setColor(group, QPalette.Light, QColor(t["border"]))
        p.setColor(group, QPalette.Midlight, QColor(t["border"]))
        p.setColor(group, QPalette.Mid, QColor(t["well"]))
        p.setColor(group, QPalette.Dark, QColor(t["bg"]))
        p.setColor(group, QPalette.Shadow, QColor(t["shadow"]))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        p.setColor(QPalette.Disabled, role, QColor(t["faint"]))
    return p


# ── applying it ─────────────────────────────────────────────────────────────
class Theme:
    """What is applied now, so a new frame only repaints when it is really a
    different colour — setStyleSheet repolishes every widget there is."""

    def __init__(self):
        self.app = None
        self.prefs = None
        self.seed = DEFAULT_SEED
        self.applied = None
        self.t = tokens()
        self.listeners = []

    def dark(self):
        mode = (self.prefs or {}).get("appearance", "system")
        if mode in ("dark", "light"):
            return mode == "dark"
        try:
            return self.app.styleHints().colorScheme() != Qt.ColorScheme.Light
        except AttributeError:
            return True

    def apply(self, force=False):
        if self.app is None:
            return
        use_wallpaper = (self.prefs or {}).get("colors", "wallpaper") == "wallpaper"
        seed = self.seed if use_wallpaper else DEFAULT_SEED
        key = (round(seed[0] * 36) % 36, round(seed[1] * 5), self.dark())
        if key == self.applied and not force:
            return
        self.applied = key
        self.t = tokens(seed, dark=key[2])
        if IS_ANDROID:
            # On Android Qt paints the status and navigation bars from the
            # colour scheme it is told the app uses; left to follow the
            # system, a dark window under a light system got white bars.
            mode = (self.prefs or {}).get("appearance", "system")
            try:
                hints = self.app.styleHints()
                hints.setColorScheme(Qt.ColorScheme.Unknown if mode == "system"
                                     else Qt.ColorScheme.Dark if key[2]
                                     else Qt.ColorScheme.Light)
            except AttributeError:
                pass
        self.app.setPalette(build_palette(self.t))
        self.app.setStyleSheet(build_qss(self.t, _fonts["sans"], _fonts["mono"]))
        for listener in list(self.listeners):
            listener(self.t)

    def set_seed(self, seed):
        self.seed = seed
        self.apply()


theme = Theme()
_fonts = {"sans": SANS, "mono": MONO}


def token(name):
    return theme.t[name]


def _load_fonts():
    """The bundled families, else whatever is installed."""
    from PySide6.QtGui import QFont, QFontDatabase
    loaded = set()
    for path in sorted(FONTS_DIR.glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id >= 0:
            loaded.update(QFontDatabase.applicationFontFamilies(font_id))
    if SANS not in loaded:
        _fonts["sans"] = QFontDatabase.systemFont(QFontDatabase.GeneralFont).family()
    if MONO not in loaded:
        _fonts["mono"] = QFontDatabase.systemFont(QFontDatabase.FixedFont).family()
    QFont.insertSubstitution("monospace", _fonts["mono"])


def apply(app, prefs=None):
    """Fonts, stylesheet and palette for `app`, from `prefs`' appearance
    and colours. theme.apply(force=True) again after either changes."""
    _load_fonts()
    theme.app = app
    theme.prefs = prefs
    theme.applied = None
    theme.apply()
    if not hasattr(app, "_focus_ring"):
        app._focus_ring = FocusRing(app)
    try:
        app.styleHints().colorSchemeChanged.connect(lambda *_: theme.apply())
    except AttributeError:
        pass


# ── the keyboard ────────────────────────────────────────────────────────────
class FocusRing(QObject):
    """Where the focus is, shown only to someone using the keyboard — what a
    browser's :focus-visible does.

    A ring after every click on a button is noise, so the ring appears once
    Tab or an arrow key is pressed and goes away at the next mouse press or
    touch. The focused widget gets the property kbfocus=true, which the
    stylesheet draws; a radio inside a choice card marks the card, since its
    own circle is all it has.

    Enter (or Return) on a focused button presses it, as Space does: outside
    a dialog Qt gives a plain button no default action for Enter.
    """
    KEYS = {Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Left, Qt.Key_Right, Qt.Key_Up,
            Qt.Key_Down, Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp, Qt.Key_PageDown}

    def __init__(self, app):
        super().__init__(app)
        self.keyboard = False
        self.marked = []
        app.installEventFilter(self)
        app.focusChanged.connect(lambda *_: self.mark())

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.KeyPress:
            if event.key() in self.KEYS and not self.keyboard:
                self.keyboard = True
                self.mark()
            if (event.key() in (Qt.Key_Return, Qt.Key_Enter)
                    and isinstance(watched, QAbstractButton)
                    and watched is QApplication.focusWidget()
                    and watched.isEnabled() and not event.isAutoRepeat()):
                self.keyboard = True
                watched.animateClick()
                return True
        elif kind in (QEvent.MouseButtonPress, QEvent.TouchBegin) and self.keyboard:
            self.keyboard = False
            self.mark()
        return False

    def mark(self):
        for widget in self.marked:
            try:
                _set_ring(widget, False)
            except RuntimeError:            # deleted since
                pass
        self.marked = []
        focus = QApplication.focusWidget()
        if not self.keyboard or focus is None:
            return
        self.marked = [focus]
        card = focus.parentWidget()
        if card is not None and card.property("class") == "choice":
            self.marked.append(card)
        for widget in self.marked:
            _set_ring(widget, True)


def _set_ring(widget, on):
    if bool(widget.property("kbfocus")) == on:
        return
    widget.setProperty("kbfocus", on)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


# ── controls Qt does not have ───────────────────────────────────────────────
class Switch(QCheckBox):
    """A toggle switch: a checkbox drawn as a pill with a knob, in the
    palette's accent when on."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self):
        return QSize(50, 32)

    def minimumSizeHint(self):
        return self.sizeHint()

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(3, (self.height() - 26) / 2, 44, 26)
        on = self.isChecked()
        pal = self.palette()
        if self.property("kbfocus"):
            p.setPen(QPen(pal.color(QPalette.WindowText), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 15, 15)
        track = QColor(pal.color(QPalette.Highlight) if on else pal.color(QPalette.Mid))
        if not self.isEnabled():
            track.setAlpha(110)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, 13, 13)
        p.setBrush(pal.color(QPalette.HighlightedText) if on
                   else pal.color(QPalette.PlaceholderText))
        d = 20
        x = r.right() - d - 3 if on else r.left() + 3
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))
        p.end()


def touch_scroll(area):
    """Let a finger drag `area` (a QAbstractScrollArea) on a touch screen.

    QtWidgets scroll by scroll bar and wheel only; a drag on the content
    selects or does nothing. QScroller turns a press-and-move into kinetic
    scrolling, which is the only way to scroll on a phone.
    """
    if not IS_ANDROID:
        return
    from PySide6.QtWidgets import QScroller
    QScroller.grabGesture(area.viewport(), QScroller.LeftMouseButtonGesture)
