"""The main window: a rail of three sections (Random / Saved / Settings) —
a bottom bar on a phone — a toast, and the keyboard shortcuts shared across
all of them. The operating system draws the title bar; nothing here does.
"""
import os
import subprocess

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QAbstractSpinBox, QApplication,
    QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QRadioButton, QStackedWidget,
    QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from .. import core
from ..paths import IS_ANDROID
from . import style
from .library_page import LibraryPage
from .reel_page import ReelPage
from .settings_page import SettingsPage

# A keyboard layout other than Latin (Cyrillic, Greek, …) sends a different
# keyval for the same physical key, and every mnemonic here — S for save, D
# for delete — is English. Binding both the Qt key and its usual Cyrillic
# neighbour keeps the shortcuts alive while typing in a non-Latin layout,
# without building a full scancode-translation table the way X11 needed.
_CYRILLIC_TWINS = {
    Qt.Key_S: "Ы",   # Ы sits where S does on a ЙЦУКЕН keyboard
    Qt.Key_D: "В",   # В
    Qt.Key_N: "Т",   # Т
    Qt.Key_P: "З",   # З
    Qt.Key_Q: "Й",   # Й
    Qt.Key_A: "Ф",   # Ф
}

# What F1 lists. Keep it in step with Reel._install_shortcuts.
KEYS = [
    ("Anywhere", [
        ("1  2  3", "Random, Saved, Settings"),
        ("Tab  Shift+Tab", "Move between controls"),
        ("Space  Enter", "Press the focused button"),
        ("Arrows", "Pick in a row of choices; move between saved pictures"),
        ("Ctrl+F  /", "Search the saved pictures"),
        ("F1  ?", "This list"),
        ("Esc  Q", "Quit (Esc leaves the search box first)"),
    ]),
    ("Random", [
        ("S  Enter", "Keep this one"),
        ("D  Delete", "Skip it"),
        ("Right  N  Space", "Next"),
        ("Left  P", "Previous"),
    ]),
    ("Saved", [
        ("Space", "Pick or unpick the tile"),
        ("Enter", "Set it as the wallpaper"),
        ("Ctrl+A", "Pick all"),
        ("D  Delete", "Delete the picked ones"),
    ]),
]

# The three sections: their names, and their icons as stroke SVG drawn in
# whatever colour the theme gives the button.
SECTIONS = ["Random", "Saved", "Settings"]
_ICONS = {
    "Random": '<path d="M16 3h5v5M4 20L21 3M21 16v5h-5M15 15l6 6M4 4l5 5"/>',
    "Saved": ('<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/>'
              '<rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>'),
    "Settings": ('<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/>'
                 '<circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>'),
    "prev": '<path d="M15 5l-7 7 7 7"/>',
    "next": '<path d="M9 5l7 7-7 7"/>',
}


def _svg_icon(name, off, on, size=22):
    from PySide6.QtSvg import QSvgRenderer
    icon = QIcon()
    for color, state in ((off, QIcon.Off), (on, QIcon.On)):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
               f'stroke="{color}" stroke-width="1.8" stroke-linecap="round" '
               f'stroke-linejoin="round">{_ICONS[name]}</svg>')
        renderer = QSvgRenderer(QByteArray(svg.encode()))
        for scale in (1, 2, 3):
            pix = QPixmap(size * scale, size * scale)
            pix.fill(Qt.transparent)
            painter = QPainter(pix)
            renderer.render(painter)
            painter.end()
            pix.setDevicePixelRatio(scale)
            icon.addPixmap(pix, QIcon.Normal, state)
    return icon


class Reel(QMainWindow):
    _posted = Signal(object)

    def __init__(self, app, prefs):
        super().__init__()
        # Connected before any page exists: the Settings page starts a worker
        # in its constructor, and that worker's answer comes back this way.
        # A bound method rather than a lambda, so the window is the receiver
        # and the call is queued onto its thread from whichever one emitted.
        self._posted.connect(self._run_posted)
        self.app = app
        self.prefs = prefs
        self.setWindowTitle("Random Wallpaper")
        # The size it was designed at, but never more than the screen can
        # show: 1000×760 on a 1024×768 laptop puts the bottom of the page
        # under the taskbar.
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        room = screen.availableGeometry() if screen else None
        width, height = 1000, 760
        if room is not None:
            width = min(width, int(room.width() * 0.92))
            height = min(height, int(room.height() * 0.92))
        self.resize(width, height)

        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        self.pages = QStackedWidget()
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = []
        nav = QWidget()
        if IS_ANDROID:
            # A phone: the sections along the bottom, under the thumb.
            nav.setObjectName("bottomNav")
            nav_layout = QHBoxLayout(nav)
            nav_layout.setContentsMargins(8, 6, 8, 10)
            nav_layout.setSpacing(0)
        else:
            nav.setObjectName("rail")
            nav.setFixedWidth(68)
            nav_layout = QVBoxLayout(nav)
            nav_layout.setContentsMargins(10, 14, 10, 14)
            nav_layout.setSpacing(6)
        for i, name in enumerate(SECTIONS):
            button = QToolButton()
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(f"{name}  ({i + 1})")
            if IS_ANDROID:
                button.setProperty("class", "navBottom")
                button.setText(name)
                button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                button.setIconSize(QSize(22, 22))
                button.setMinimumHeight(56)
                nav_layout.addWidget(button, 1)
            else:
                button.setProperty("class", "nav")
                button.setFixedSize(48, 48)
                button.setIconSize(QSize(22, 22))
                nav_layout.addWidget(button, 0, Qt.AlignHCenter)
            button.clicked.connect(lambda _=False, i=i: self.show_tab(i))
            self.nav_group.addButton(button, i)
            self.nav_buttons.append(button)
        if IS_ANDROID:
            body.addWidget(self.pages, 1)
            outer.addWidget(nav)
        else:
            nav_layout.addStretch(1)
            body.addWidget(nav)
            body.addWidget(self.pages, 1)
        self._paint_icons(style.theme.t)
        style.theme.listeners.append(self._paint_icons)

        self.reel_page = ReelPage(self)
        self.pages.addWidget(self.reel_page)
        self.library = LibraryPage(self)
        self.pages.addWidget(self.library)
        self.settings = SettingsPage(self, prefs)
        self.settings.changed.connect(self.filters_changed)
        self.pages.addWidget(self.settings)
        self._paint_icons(style.theme.t)

        # ── toast: floats over the page, near the bottom ────────────────
        self.toast = QLabel(central)
        self.toast.setObjectName("toast")
        self.toast.setAlignment(Qt.AlignCenter)
        self.toast.setWordWrap(True)
        self.toast.hide()
        self.toast_timer = QTimer(self)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.timeout.connect(self.hide_toast)

        self._install_shortcuts()
        self.show_tab(0)
        if IS_ANDROID:
            self._resume_after_restart()

    def _paint_icons(self, t):
        for name, button in zip(SECTIONS, self.nav_buttons):
            button.setIcon(_svg_icon(name, t["dim"], t["accentText"]))
        page = getattr(self, "reel_page", None)
        if page is not None:
            for name, button in (("prev", page.prev_btn), ("next", page.next_btn)):
                button.setText("")
                button.setIcon(_svg_icon(name, t["fg"], t["fg"], size=18))
                button.setIconSize(QSize(18, 18))

    # ── cross-thread hand-off ───────────────────────────────────────────
    @Slot(object)
    def _run_posted(self, fn):
        fn()

    def post_to_ui(self, fn):
        """Run fn on the UI thread; callable from any thread.

        A signal, not QTimer.singleShot: a timer started on a worker thread
        belongs to that thread, which has no event loop, so it never fires.
        A signal emitted there to this window, which lives on the UI thread,
        is queued across automatically.
        """
        self._posted.emit(fn)

    # ── links / apply / latch (shared by reel and library) ─────────────
    def link_into_pictures(self, saved):
        """Hardlink the saved file into the platform's Pictures/Wallpapers
        folder, so it shows up in the desktop's own wallpaper picker too."""
        try:
            directory = core.pictures_wallpapers()
            directory.mkdir(parents=True, exist_ok=True)
            link = core.unique_path(directory, saved.stem, saved.suffix)
            try:
                os.link(saved, link)
            except OSError:
                try:
                    link.symlink_to(saved)
                except OSError:
                    import shutil
                    shutil.copy2(saved, link)
        except OSError as exc:
            self.show_toast(f"Saved, but not linked into Pictures: {exc}")

    def this_output(self):
        """The monitor this window is on, by the name the desktop uses for
        it — or None where the two do not agree on one."""
        screen = self.screen()
        name = screen.name() if screen else ""
        return name if name in core.wallpapers_on_outputs() else None

    # ── surviving Qt's restart on Android ───────────────────────────────
    # Setting a wallpaper on Android 12+ re-themes the system from its
    # colours and recreates the activity, and Qt answers that by restarting
    # the whole app (QtActivityBase: "no reliable way to keep the app
    # running … in case of an Activity only restart"). So where the user was
    # is written down first, and a launch within a minute picks it up again.
    RESUME_FILE = core.CACHE_DIR / "resume.json"

    def _remember_for_restart(self, message):
        import json
        import time
        try:
            core.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self.RESUME_FILE.write_text(json.dumps(
                {"at": time.time(), "tab": self.current_tab(), "toast": message}))
        except OSError:
            pass

    def _resume_after_restart(self):
        import json
        import time
        try:
            note = json.loads(self.RESUME_FILE.read_text())
            self.RESUME_FILE.unlink()
        except (OSError, ValueError):
            return
        if time.time() - note.get("at", 0) > 60:
            return
        self.show_tab(int(note.get("tab", 0)))
        if note.get("toast"):
            QTimer.singleShot(300, lambda: self.show_toast(note["toast"]))

    def set_and_latch(self, path, failure="could not set it", output=None):
        if IS_ANDROID:
            self._remember_for_restart(f"Wallpaper set  {getattr(path, 'name', path)}")
        try:
            if output:
                core.set_wallpaper_on(output, path)
            else:
                core.set_wallpaper(path)
        except (subprocess.SubprocessError, OSError) as exc:
            if IS_ANDROID:
                try:
                    self.RESUME_FILE.unlink()
                except OSError:
                    pass
            self.show_toast(f"{failure}: {exc}")
            return False

        if self.prefs["auto_enabled"]:
            core.set_auto_enabled(self.prefs, False)
            self.settings.sync_auto()
            self.show_toast(
                "Automatic rotation switched off — this wallpaper is "
                "yours until you turn it back on in Settings."
            )
        return True

    def apply_wallpaper(self, path):
        # Each screen its own: saved from the reel, it goes on the screen the
        # reel is on — the one being looked at while choosing it.
        output = (self.this_output()
                  if core.screens_mode(self.prefs) == "separate" else None)
        self.set_and_latch(path, failure="Saved, but could not set it",
                           output=output)

    # ── chrome ───────────────────────────────────────────────────────────
    def filters_changed(self):
        self.reel_page.filters_changed()

    def current_tab(self):
        return self.pages.currentIndex()

    def show_tab(self, index):
        self.pages.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        self._refresh_shortcuts()
        if index == 1:
            self.library.reload()
        elif index == 2:
            self.settings.fill_outputs()     # monitors come and go
            self.settings.refresh_hint()

    def retheme(self):
        self.reel_page.retheme()

    def show_toast(self, text):
        self.toast.setText(text)
        self._place_toast()
        self.toast.show()
        self.toast.raise_()
        self.toast_timer.start(4000)

    def _place_toast(self):
        area = self.centralWidget().rect()
        width = min(520, area.width() - 32)
        self.toast.setFixedWidth(width)
        self.toast.adjustSize()
        bottom = 96 if IS_ANDROID else 24
        self.toast.move((area.width() - width) // 2 + (0 if IS_ANDROID else 34),
                        area.height() - self.toast.height() - bottom)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.toast.isVisible():
            self._place_toast()

    def hide_toast(self):
        self.toast.hide()

    # ── input ────────────────────────────────────────────────────────────
    def _install_shortcuts(self):
        # (shortcut, groups): "reel" is on only while the Random tab is the
        # one showing, so its keys are left to the other tabs; "activation"
        # (Space, Return) and "arrow" give way to a focused control that
        # uses those keys itself. See _refresh_shortcuts.
        self._shortcuts = []
        for i, key in enumerate((Qt.Key_1, Qt.Key_2, Qt.Key_3)):
            self._bind(key, lambda i=i: self.show_tab(i), "typing")
        self._bind(Qt.Key_Comma, lambda: self.show_tab(2), "typing")
        self._bind(Qt.Key_F2, lambda: self.show_tab(2))
        self._bind(Qt.Key_Q, self.close)
        self._bind(Qt.Key_Escape, self._escape)
        self._bind(Qt.Key_F1, self.show_keys)
        self._bind("?", self.show_keys, "typing")
        self._bind("Ctrl+F", self._find)
        self._bind("/", self._find, "typing")

        self._bind(Qt.Key_S, self._save, "reel")
        self._bind(Qt.Key_Return, self._save, "reel", "activation")
        self._bind(Qt.Key_D, self._delete)
        self._bind(Qt.Key_Delete, self._delete)
        self._bind(Qt.Key_Right, lambda: self._nav(1), "reel", "arrow")
        self._bind(Qt.Key_N, lambda: self._nav(1), "reel")
        self._bind(Qt.Key_Space, lambda: self._nav(1), "reel", "activation")
        self._bind(Qt.Key_Left, lambda: self._nav(-1), "reel", "arrow")
        self._bind(Qt.Key_P, lambda: self._nav(-1), "reel")

        app = QApplication.instance()
        if app is not None:
            # A bound slot, so it goes with the window instead of outliving it.
            app.focusChanged.connect(self._refresh_shortcuts)
        self._refresh_shortcuts()

    def _bind(self, key, handler, *groups):
        keys = [key]
        twin = _CYRILLIC_TWINS.get(key)
        if twin:
            keys.append(twin)
        for k in keys:
            sc = QShortcut(QKeySequence(k), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(handler)
            self._shortcuts.append((sc, set(groups)))

    @Slot()
    def _refresh_shortcuts(self, *_):
        """Which shortcuts are live, for the tab showing and the focus.

        A QLineEdit already claims every ordinary key for itself before a
        global QShortcut sees it (Qt's ShortcutOverride), so typing "s" in
        the search box types "s". Nothing else is protected that way:
        Space and Return would never reach a focused button or checkbox, the
        arrows never reach a segmented control, a combo box or the Saved
        grid, and digits never reach the spin box — so those shortcuts are
        switched off while such a widget has the focus.
        """
        if not hasattr(self, "_shortcuts"):
            return
        focus = QApplication.focusWidget()
        activation = isinstance(focus, (QAbstractButton, QComboBox))
        arrow = (isinstance(focus, (QComboBox, QAbstractSpinBox, QAbstractItemView,
                                    QTextEdit, QRadioButton, QLineEdit))
                 or (isinstance(focus, QAbstractButton)
                     and focus.property("class") == "seg"))
        typing = isinstance(focus, (QAbstractSpinBox, QLineEdit, QTextEdit))
        on_reel = self.current_tab() == 0
        for sc, groups in self._shortcuts:
            sc.setEnabled(not ("reel" in groups and not on_reel)
                          and not ("activation" in groups and activation)
                          and not ("arrow" in groups and arrow)
                          and not ("typing" in groups and typing))

    def _find(self):
        self.show_tab(1)
        self.library.search.setFocus(Qt.ShortcutFocusReason)
        self.library.search.selectAll()

    def show_keys(self):
        """F1 or ?: every shortcut, in one place."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Keyboard shortcuts")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 16)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        row = 0
        for heading, keys in KEYS:
            title = QLabel(heading)
            title.setProperty("class", "h2")
            grid.addWidget(title, row, 0, 1, 2)
            row += 1
            for combo, what in keys:
                key = QLabel(combo)
                key.setProperty("class", "mono")
                grid.addWidget(key, row, 0, Qt.AlignTop)
                text = QLabel(what)
                text.setWordWrap(True)
                grid.addWidget(text, row, 1)
                row += 1
        layout.addLayout(grid)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _save(self):
        if self.current_tab() == 0:
            self.reel_page.save()

    def _delete(self):
        if self.current_tab() == 0:
            self.reel_page.delete()
        elif self.current_tab() == 1:
            self.library.delete_selected()

    def _nav(self, direction):
        if self.current_tab() != 0:
            return
        page = self.reel_page
        page.go(page.index + direction)

    def _escape(self):
        if self.current_tab() == 1 and self.library.asking():
            self.library.cancel_delete()
            return
        focus = QApplication.focusWidget()
        if focus is self.library.search:
            # Out of the search box: clear it first, then back to the tiles.
            if focus.text():
                focus.clear()
            else:
                self.library.list.setFocus(Qt.OtherFocusReason)
            return
        self.close()

    def closeEvent(self, event):
        for frame in self.reel_page.frames:
            try:
                frame["path"].unlink(missing_ok=True)
            except OSError:
                pass
        self.reel_page.frames.clear()
        super().closeEvent(event)
