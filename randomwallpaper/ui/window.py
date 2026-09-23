"""The main window: three tabs (Random / Downloaded / Settings), a toast, and
the keyboard shortcuts shared across all of them.
"""
import os
import subprocess

from PySide6.QtCore import QEvent, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QComboBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QTabWidget, QVBoxLayout, QWidget,
)

from .. import core
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


class Reel(QMainWindow):
    _posted = Signal(object)

    def __init__(self, app, prefs):
        super().__init__()
        # Connected before any page exists: the Settings tab starts a worker
        # in its constructor, and that worker's answer comes back this way.
        # A bound method rather than a lambda, so the window is the receiver
        # and the call is queued onto its thread from whichever one emitted.
        self._posted.connect(self._run_posted)
        self.app = app
        self.prefs = prefs
        self.setWindowTitle("Random Wallpaper")
        # The size it was designed at, but never more than the screen can
        # show: 1000×760 on a 1024×768 laptop puts the reel strip under the
        # taskbar and the frame counter past the right edge.
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        room = screen.availableGeometry() if screen else None
        width, height = 1000, 760
        if room is not None:
            width = min(width, int(room.width() * 0.92))
            height = min(height, int(room.height() * 0.92))
        self.resize(width, height)

        central = QWidget()
        central.setObjectName("reelRoot")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── top bar ──────────────────────────────────────────────────────
        top = QWidget()
        top.setObjectName("topbar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(14, 8, 14, 8)
        top_layout.setSpacing(12)
        root.addWidget(top)

        wordmark = QLabel("RANDOM WALLPAPER")
        wordmark.setObjectName("wordmark")
        top_layout.addWidget(wordmark)

        self.filter_summary = QLabel()
        self.filter_summary.setStyleSheet("color:#8B90A8; font-family:monospace; font-size:11px;")
        top_layout.addWidget(self.filter_summary, 1)

        self.position = QLabel()
        self.position.setStyleSheet("color:#8B90A8; font-family:monospace; font-size:11px;")
        top_layout.addWidget(self.position)

        # ── tabs ─────────────────────────────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        # documentMode draws a base line under the tabs in the palette's
        # light colour — pure white under Fusion, a hairline across the top
        # of a dark window. The top bar already draws the border that belongs
        # there.
        self.tabs.tabBar().setDrawBase(False)
        # macOS sizes tabs by its own metrics, not the stylesheet's padding,
        # and then elides the labels to fit: "Rand…", "Downloa…".
        self.tabs.tabBar().setElideMode(Qt.ElideNone)
        self.tabs.tabBar().setExpanding(False)
        root.addWidget(self.tabs, 1)

        self.reel_page = ReelPage(self)
        self.tabs.addTab(self.reel_page, "Random")
        self.library = LibraryPage(self)
        self.tabs.addTab(self.library, "Downloaded")
        self.settings = SettingsPage(self, prefs)
        self.settings.changed.connect(self.filters_changed)
        self.tabs.addTab(self.settings, "Settings")
        self.tabs.currentChanged.connect(self.on_tab_changed)

        # ── toast ────────────────────────────────────────────────────────
        self.toast = QLabel()
        self.toast.setObjectName("toast")
        self.toast.setAlignment(Qt.AlignCenter)
        self.toast.hide()
        self._toast_container = QWidget()
        tc_layout = QHBoxLayout(self._toast_container)
        tc_layout.setContentsMargins(0, 0, 0, 10)
        tc_layout.addStretch(1)
        tc_layout.addWidget(self.toast)
        tc_layout.addStretch(1)
        root.addWidget(self._toast_container)
        self.toast_timer = QTimer(self)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.timeout.connect(self.hide_toast)

        self._install_shortcuts()
        self.refresh_summary()
        self.on_tab_changed(0)

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

    def set_and_latch(self, path, failure="could not set it"):
        try:
            core.set_wallpaper(path)
        except (subprocess.SubprocessError, OSError) as exc:
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
        self.set_and_latch(path, failure="Saved, but could not set it")

    # ── chrome ───────────────────────────────────────────────────────────
    def filters_changed(self):
        self.refresh_summary()
        self.reel_page.filters_changed()

    def show_tab(self, index):
        self.tabs.setCurrentIndex(index)

    def on_tab_changed(self, index):
        name = ("reel", "library", "settings")[index] if index < 3 else "reel"
        self.filter_summary.setVisible(name == "reel")
        self.position.setVisible(name == "reel")
        if name == "library":
            self.library.reload()
        elif name == "settings":
            self.settings.refresh_hint()

    def set_position(self, text):
        self.position.setText(text)

    def refresh_summary(self):
        bits = [core.SOURCES[core.source_index(core.effective_source(self.prefs))][0].upper()]
        theme = core.theme_key(self.prefs)
        if theme != "all":
            bits.append(core.theme_label(theme).upper())
        orientation = dict((v, k) for k, v in core.ORIENTATIONS)[self.prefs["orientation"]]
        bits.append(orientation.upper())
        bits.append(dict((v, k) for k, v in core.MINIMUMS)[self.prefs["minimum"]].upper())
        if self.prefs["source"] == "wallhaven":
            cats = [name for name, key in (("GENERAL", "wallhaven_general"),
                                           ("ANIME", "wallhaven_anime"),
                                           ("PEOPLE", "wallhaven_people"))
                    if self.prefs[key]]
            bits.append("+".join(cats) or "NO CATEGORIES")
        self.filter_summary.setText("  ·  ".join(bits))

    def retheme(self):
        self.refresh_summary()
        self.reel_page.retheme()

    def show_toast(self, text):
        self.toast.setText(text)
        self.toast.show()
        self.toast_timer.start(4000)

    def hide_toast(self):
        self.toast.hide()

    # ── input ────────────────────────────────────────────────────────────
    def _install_shortcuts(self):
        self._contextual_shortcuts = []
        for i, key in enumerate((Qt.Key_1, Qt.Key_2, Qt.Key_3)):
            self._bind(key, lambda i=i: self.show_tab(i))
        self._bind(Qt.Key_Comma, lambda: self.show_tab(2))
        self._bind(Qt.Key_F2, lambda: self.show_tab(2))
        self._bind(Qt.Key_Q, self.close)
        self._bind(Qt.Key_Escape, self._escape)

        self._bind(Qt.Key_S, self._save)
        self._bind(Qt.Key_Return, self._save, contextual=True)
        self._bind(Qt.Key_D, self._delete)
        self._bind(Qt.Key_Delete, self._delete)
        self._bind(Qt.Key_Right, lambda: self._nav(1))
        self._bind(Qt.Key_N, lambda: self._nav(1))
        self._bind(Qt.Key_Space, lambda: self._nav(1), contextual=True)
        self._bind(Qt.Key_Left, lambda: self._nav(-1))
        self._bind(Qt.Key_P, lambda: self._nav(-1))

        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_focus_changed)

    def _bind(self, key, handler, contextual=False):
        sc = QShortcut(QKeySequence(key), self)
        sc.setContext(Qt.ApplicationShortcut)
        sc.activated.connect(lambda: self._dispatch(handler))
        if contextual:
            self._contextual_shortcuts.append(sc)
        twin = _CYRILLIC_TWINS.get(key)
        if twin:
            sc2 = QShortcut(QKeySequence(twin), self)
            sc2.setContext(Qt.ApplicationShortcut)
            sc2.activated.connect(lambda: self._dispatch(handler))
            if contextual:
                self._contextual_shortcuts.append(sc2)

    def _dispatch(self, handler):
        # A QLineEdit already claims every ordinary key for itself before a
        # global QShortcut ever sees it (Qt's own ShortcutOverride handling),
        # so typing "s" in the API-key box safely types "s" and never reaches
        # here. Space and Return are the ones Qt does *not* protect this way
        # — a QShortcut for either steals the key before a focused button or
        # checkbox can react to it — and those are handled by disabling their
        # shortcuts outright while such a widget has focus; see
        # _on_focus_changed.
        handler()

    def _on_focus_changed(self, _old, new):
        """Space and Return are ordinary activation keys for a button, a
        checkbox, a combo box — and a global QShortcut for either steals the
        key before the focused widget's own handling ever runs. Disabling
        those two shortcuts while such a widget has focus is what lets Tab
        and Space still operate the Settings tab's controls, and what keeps
        this from regressing the original's "Space picks a tile" behaviour
        once a button below the grid has focus.
        """
        interactive = isinstance(new, (QAbstractButton, QComboBox))
        for sc in self._contextual_shortcuts:
            sc.setEnabled(not interactive)

    def _save(self):
        if self.tabs.currentIndex() == 0:
            self.reel_page.save()

    def _delete(self):
        if self.tabs.currentIndex() == 0:
            self.reel_page.delete()
        elif self.tabs.currentIndex() == 1:
            self.library.delete_selected()

    def _nav(self, direction):
        if self.tabs.currentIndex() != 0:
            return
        page = self.reel_page
        page.go(page.index + direction)

    def _escape(self):
        if self.tabs.currentIndex() == 1 and self.library.footer.currentIndex() == 1:
            self.library.cancel_delete()
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
