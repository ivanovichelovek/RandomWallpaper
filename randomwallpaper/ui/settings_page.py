"""The Settings tab.

Every control here writes the config the moment it changes — there is no Done
button, because there is nothing to dismiss; leaving the tab is just
switching to another one.
"""
import os
import threading
from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QRadioButton, QScrollArea, QVBoxLayout, QWidget,
)

from .. import core


def _eyebrow(text):
    label = QLabel(text)
    label.setStyleSheet(
        "font-family: monospace; font-size:9px; font-weight:700; "
        "letter-spacing:1.6px; color:#8B90A8;"
    )
    return label


def _card():
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(8)
    return frame, layout


class SettingsPage(QWidget):
    changed = Signal()

    def __init__(self, win, prefs):
        super().__init__()
        self.win = win
        self.prefs = prefs

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        outer.addWidget(scroller)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(14)
        scroller.setWidget(root)

        # ── filters card ─────────────────────────────────────────────────
        card, card_layout = _card()
        root_layout.addWidget(card)
        form = QFormLayout()
        form.setSpacing(10)
        card_layout.addLayout(form)

        self.source = self._combo([s[0] for s in core.SOURCES])
        self.source.setCurrentIndex(core.source_index(prefs["source"]))
        self.source.currentIndexChanged.connect(self.apply)
        form.addRow(_eyebrow("SOURCE"), self.source)

        self.theme = self._combo([t[1] for t in core.THEMES])
        self.theme.setCurrentIndex(core.theme_index(prefs["theme"]))
        self.theme.currentIndexChanged.connect(self.apply)
        form.addRow(_eyebrow("THEME"), self.theme)

        self.orientation = self._combo([o[0] for o in core.ORIENTATIONS])
        self.orientation.setCurrentIndex(
            self._pos(core.ORIENTATIONS, prefs["orientation"]))
        self.orientation.currentIndexChanged.connect(self.apply)
        form.addRow(_eyebrow("ORIENTATION"), self.orientation)

        self.minimum = self._combo([m[0] for m in core.MINIMUMS])
        self.minimum.setCurrentIndex(self._pos(core.MINIMUMS, prefs["minimum"]))
        self.minimum.currentIndexChanged.connect(self.apply)
        form.addRow(_eyebrow("MINIMUM SIZE"), self.minimum)

        self.source_hint = QLabel()
        self.source_hint.setWordWrap(True)
        self.source_hint.setStyleSheet("color:#E06C6C; font-size:12px;")
        card_layout.addWidget(self.source_hint)

        self.pool_status = QLabel()
        self.pool_status.setWordWrap(True)
        self.pool_status.setStyleSheet("color:#8B90A8; font-family:monospace; font-size:11px;")
        card_layout.addWidget(self.pool_status)

        # ── wallhaven-only card ──────────────────────────────────────────
        self.wallhaven_card, wh = _card()
        root_layout.addWidget(self.wallhaven_card)
        wh.addWidget(_eyebrow("WALLHAVEN CATEGORIES"))

        cats = QHBoxLayout()
        wh.addLayout(cats)
        self.cat_general = QCheckBox("General")
        self.cat_general.setChecked(prefs["wallhaven_general"])
        self.cat_anime = QCheckBox("Anime")
        self.cat_anime.setChecked(prefs["wallhaven_anime"])
        self.cat_people = QCheckBox("People")
        self.cat_people.setChecked(prefs["wallhaven_people"])
        for c in (self.cat_general, self.cat_anime, self.cat_people):
            c.toggled.connect(self.apply)
            cats.addWidget(c)
        cats.addStretch(1)

        wh.addWidget(_eyebrow("API KEY — NOT NEEDED FOR THESE FILTERS"))
        self.apikey = QLineEdit(prefs["wallhaven_apikey"])
        self.apikey.setPlaceholderText("wallhaven.cc/settings/account")
        self.apikey.setEchoMode(QLineEdit.Password)
        self.apikey.textChanged.connect(self.apply)
        wh.addWidget(self.apikey)

        if os.environ.get("WALLHAVEN_API_KEY", "").strip():
            self.apikey.setEnabled(False)
            self.apikey.setPlaceholderText("taken from WALLHAVEN_API_KEY")

        # ── the calendar rotation ────────────────────────────────────────
        auto_card, auto = _card()
        root_layout.addWidget(auto_card)
        auto.addWidget(_eyebrow("FOLLOW THE CALENDAR"))

        self.auto = QCheckBox(
            "Change the wallpaper by itself: with the season or the "
            "holiday, and each midnight among what is pinned to it"
        )
        # QCheckBox has no setWordWrap; a QSS max-width plus the app's own
        # word-wrap-capable QLabel would be the fix for a truly long label,
        # but this one fits comfortably at the window's default width.
        self.auto.setChecked(prefs["auto_enabled"])
        self._suppress_auto = False
        self.auto.toggled.connect(self.apply)
        auto.addWidget(self.auto)

        self.auto_status = QLabel()
        self.auto_status.setWordWrap(True)
        self.auto_status.setStyleSheet("color:#8B90A8; font-family:monospace; font-size:11px;")
        auto.addWidget(self.auto_status)

        rite = QHBoxLayout()
        auto.addLayout(rite)
        rite.addWidget(_eyebrow("EASTER"))
        self.easter_group = QButtonGroup(self)
        self.easter_orthodox = QRadioButton("Orthodox")
        self.easter_orthodox.setChecked(prefs["easter"] != "western")
        self.easter_western = QRadioButton("Western")
        self.easter_western.setChecked(prefs["easter"] == "western")
        self.easter_group.addButton(self.easter_orthodox)
        self.easter_group.addButton(self.easter_western)
        self.easter_western.toggled.connect(lambda *_: self.apply())
        rite.addWidget(self.easter_orthodox)
        rite.addWidget(self.easter_western)
        rite.addStretch(1)

        root_layout.addStretch(1)
        self.refresh_hint()

    @staticmethod
    def _combo(options):
        from PySide6.QtWidgets import QComboBox
        combo = QComboBox()
        combo.addItems(options)
        return combo

    @staticmethod
    def _pos(table, value):
        for i, (_, key) in enumerate(table):
            if key == value:
                return i
        return 0

    def refresh_hint(self):
        source = core.SOURCES[self.source.currentIndex()][1]
        theme = core.THEMES[self.theme.currentIndex()][0]
        self.wallhaven_card.setVisible(source == "wallhaven")

        if source == "konachan":
            hint = ("Anime art, safe posts only. No server-side size filter, so "
                    "40 candidates are fetched and one that fits is picked.")
        else:
            hint = ("Mixed; untick Anime below for photographs only. Filters "
                    "apply server-side.")
        if not core.source_serves(source, theme):
            other = next(label for label, key, _ in core.SOURCES
                         if core.source_serves(key, theme))
            hint += (f"  {core.theme_label(theme)} is not in this catalogue at "
                     f"all, so those frames come from {other}.")
        self.source_hint.setText(hint)

        theme_now, period = core.current_period(date.today(), self.prefs["easter"])
        state = core.load_state()
        if not self.prefs["auto_enabled"]:
            status = f"off — today would be {core.theme_label(theme_now)}"
        elif state.get("period") == period:
            status = f"{period} applied {state.get('applied_at', '?')}"
        else:
            status = f"{period} — {core.theme_label(theme_now)}, not applied yet"
        self.auto_status.setText(status)

        chosen = len(core.pool_images(theme))
        if theme == "all":
            self.pool_status.setText(
                "Pick a season or holiday above to see what is chosen for it."
            )
        elif chosen:
            self.pool_status.setText(
                (f"1 wallpaper chosen for {core.theme_label(theme)} — it "
                 f"stays up for the whole period. Pin another and they take "
                 f"turns, a fresh one each midnight.  {core.theme_pool(theme)}"
                 if chosen == 1 else
                 f"{chosen} wallpapers chosen for {core.theme_label(theme)} "
                 f"— a different one each midnight, nothing is "
                 f"downloaded.  {core.theme_pool(theme)}")
            )
        else:
            self.pool_status.setText(
                f"Nothing chosen for {core.theme_label(theme)} yet, so its turn "
                f"downloads one. Pin some on the Downloaded tab, or put files "
                f"in {core.theme_pool(theme)}"
            )

    def sync_auto(self):
        """Pull the checkbox back in line when something else switched the
        rotation off — setting a wallpaper from the reel or the library does,
        and the tab it happened on is not this one."""
        if self.auto.isChecked() != self.prefs["auto_enabled"]:
            self._suppress_auto = True
            self.auto.setChecked(self.prefs["auto_enabled"])
            self._suppress_auto = False
        self.refresh_hint()

    def apply(self):
        if self._suppress_auto:
            return
        was_on = self.prefs["auto_enabled"]
        self.prefs.update({
            "source": core.SOURCES[self.source.currentIndex()][1],
            "theme": core.THEMES[self.theme.currentIndex()][0],
            "orientation": core.ORIENTATIONS[self.orientation.currentIndex()][1],
            "minimum": core.MINIMUMS[self.minimum.currentIndex()][1],
            "wallhaven_general": self.cat_general.isChecked(),
            "wallhaven_anime": self.cat_anime.isChecked(),
            "wallhaven_people": self.cat_people.isChecked(),
            "wallhaven_apikey": self.apikey.text(),
            "auto_enabled": self.auto.isChecked(),
            "easter": "western" if self.easter_western.isChecked() else "orthodox",
        })
        core.save_prefs(self.prefs)
        self.refresh_hint()
        self.changed.emit()

        # Ticking the box back on is the consent the latch was waiting for, so
        # the calendar's answer goes up now rather than at the next hourly
        # tick — otherwise the switch appears to do nothing for up to an hour.
        if self.auto.isChecked() and not was_on:
            self.resume()

    def resume(self):
        prefs = dict(self.prefs)
        win = self.win

        def work():
            lines = []
            core.resume_auto(prefs, log=lines.append)
            win.post_to_ui(lambda: win.show_toast(lines[-1] if lines else ""))

        threading.Thread(target=work, daemon=True).start()
