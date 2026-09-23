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
    QLineEdit, QPushButton, QRadioButton, QScrollArea, QSpinBox, QVBoxLayout,
    QWidget,
)

from .. import __version__, core, schedule, update


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
        # Everything here wraps; sideways scrolling would only ever mean
        # something failed to.
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
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
        # The same form everywhere. Left to the platform, macOS right-aligns
        # the labels, keeps each field at its size hint and centres the lot.
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)
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
        self._bad_times = None

        # Short, with the explanation in a label of its own: QCheckBox has no
        # word wrap, and one long line set the whole tab's minimum width —
        # in a narrow tile or a small floating window, the card ran off the
        # right edge behind a horizontal scroll bar.
        self.auto = QCheckBox("Change the wallpaper by itself")
        self.auto.setChecked(prefs["auto_enabled"])
        self._suppress_auto = False
        self.auto.toggled.connect(self.apply)
        auto.addWidget(self.auto)
        auto_about = QLabel("With the season or the holiday, and inside each "
                            "one as often as set below.")
        auto_about.setWordWrap(True)
        auto_about.setStyleSheet("color:#8B90A8; font-size:12px;")
        auto.addWidget(auto_about)

        self.auto_status = QLabel()
        self.auto_status.setWordWrap(True)
        self.auto_status.setStyleSheet("color:#8B90A8; font-family:monospace; font-size:11px;")
        auto.addWidget(self.auto_status)

        # ── how often, inside a period ──
        # A new season or holiday always changes the wallpaper at once; this
        # is how often it changes again while the period lasts.
        often = QHBoxLayout()
        auto.addLayout(often)
        often.addWidget(_eyebrow("CHANGE"))
        self.change_mode = self._combo([m[0] for m in core.CHANGE_MODES])
        self.change_mode.setCurrentIndex(
            self._pos(core.CHANGE_MODES, prefs["change_mode"]))
        often.addWidget(self.change_mode)

        self.every = QSpinBox()
        self.every_unit = self._combo(["minutes", "hours"])
        minutes = max(core.MIN_CHANGE_EVERY, int(prefs["change_every"]))
        in_hours = minutes % 60 == 0
        self.every_unit.setCurrentIndex(1 if in_hours else 0)
        self._set_every_range()
        self.every.setValue(minutes // 60 if in_hours else minutes)
        often.addWidget(self.every)
        often.addWidget(self.every_unit)

        self.times = QLineEdit(core.format_times(
            core.parse_times(prefs["change_times"])
            if self._times_ok(prefs["change_times"]) else [(0, 0)]))
        self.times.setPlaceholderText("07:00, 13:30, 19:00")
        often.addWidget(self.times, 1)
        often.addStretch(1)

        self.change_hint = QLabel()
        self.change_hint.setWordWrap(True)
        self.change_hint.setStyleSheet("color:#8B90A8; font-size:11px;")
        auto.addWidget(self.change_hint)

        self.change_mode.currentIndexChanged.connect(self.apply)
        self.every.valueChanged.connect(self.apply)
        self.every_unit.currentIndexChanged.connect(self._every_unit_changed)
        self.times.editingFinished.connect(self.apply)
        self._show_change_widgets()

        # The rotation only runs while the window is closed if something runs
        # it: a systemd timer, a LaunchAgent or a scheduled task. Hidden until
        # a check finds none — that check is a subprocess on Windows, so it
        # runs off the UI thread.
        timer_row = QHBoxLayout()
        auto.addLayout(timer_row)
        self.timer_status = QLabel(
            "Nothing is scheduled to run it while this window is closed."
        )
        self.timer_status.setWordWrap(True)
        self.timer_status.setStyleSheet("color:#E0A458; font-size:11px;")
        self.timer_button = QPushButton("Schedule it")
        self.timer_button.clicked.connect(self.install_timer)
        timer_row.addWidget(self.timer_status, 1)
        timer_row.addWidget(self.timer_button)
        self.timer_status.hide()
        self.timer_button.hide()

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

        # ── the app itself ───────────────────────────────────────────────
        app_card, app = _card()
        root_layout.addWidget(app_card)
        app.addWidget(_eyebrow("APP"))
        row = QHBoxLayout()
        app.addLayout(row)
        self.version_label = QLabel(
            f"Random Wallpaper {__version__}  ·  {update.describe_install()}")
        self.version_label.setWordWrap(True)
        row.addWidget(self.version_label, 1)
        self.update_button = QPushButton("Check for updates")
        self.update_button.clicked.connect(self.update_clicked)
        row.addWidget(self.update_button)
        self.update_status = QLabel()
        self.update_status.setWordWrap(True)
        self.update_status.setStyleSheet("color:#8B90A8; font-size:11px;")
        self.update_status.hide()
        app.addWidget(self.update_status)
        self._release = None
        if update.install_kind() == "source":
            # Nothing here can replace a git checkout or a uv/pip install;
            # checking still says whether there is something newer.
            self.update_button.setToolTip(
                "Installed from source — update with git pull or "
                "uv tool upgrade randomwallpaper")

        root_layout.addStretch(1)
        self.refresh_hint()
        self.check_timer()

    @staticmethod
    def _times_ok(value):
        try:
            core.parse_times(value)
            return True
        except ValueError:
            return False

    def _set_every_range(self):
        if self.every_unit.currentIndex() == 1:
            self.every.setRange(1, 24)
            self.every.setSingleStep(1)
        else:
            self.every.setRange(core.MIN_CHANGE_EVERY, 720)
            self.every.setSingleStep(5)

    def _every_unit_changed(self):
        # Keep the same length of time where the other unit can say it:
        # 120 minutes becomes 2 hours, 3 hours becomes 180 minutes.
        minutes = self._every_minutes(unit_flipped=True)
        self.every.blockSignals(True)
        self._set_every_range()
        hours = self.every_unit.currentIndex() == 1
        self.every.setValue(max(1, round(minutes / 60)) if hours else minutes)
        self.every.blockSignals(False)
        self.apply()

    def _every_minutes(self, unit_flipped=False):
        hours = self.every_unit.currentIndex() == 1
        if unit_flipped:
            hours = not hours       # the value still counts in the old unit
        return self.every.value() * 60 if hours else self.every.value()

    def _show_change_widgets(self):
        mode = core.CHANGE_MODES[self.change_mode.currentIndex()][1]
        self.every.setVisible(mode == "every")
        self.every_unit.setVisible(mode == "every")
        self.times.setVisible(mode == "times")

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

        how = core.describe_change(self.prefs)
        if self.prefs["change_mode"] == "midnight":
            self.change_hint.setText(
                "A new wallpaper each midnight, drawn from what is pinned to "
                "the season or holiday. With nothing pinned, one download "
                "stays up for the whole period.")
        else:
            self.change_hint.setText(
                f"A new wallpaper {how}: drawn from what is pinned to the "
                f"season or holiday, or — with nothing pinned — a fresh "
                f"download each time.")
        if self._bad_times:
            self.change_hint.setText(
                f"{self._bad_times} — use 24-hour times separated by commas, "
                f"like 07:00, 19:30. Still changing {how}.")
            self.change_hint.setStyleSheet("color:#E06C6C; font-size:11px;")
        else:
            self.change_hint.setStyleSheet("color:#8B90A8; font-size:11px;")

        chosen = len(core.pool_images(theme))
        if theme == "all":
            self.pool_status.setText(
                "Pick a season or holiday above to see what is chosen for it."
            )
        elif chosen:
            self.pool_status.setText(
                (f"1 wallpaper chosen for {core.theme_label(theme)} — it "
                 f"stays up for the whole period. Pin another and they take "
                 f"turns, a fresh one {how}.  {core.theme_pool(theme)}"
                 if chosen == 1 else
                 f"{chosen} wallpapers chosen for {core.theme_label(theme)} "
                 f"— a different one {how}, nothing is "
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
        mode_before = self.prefs["change_mode"]
        # A time list that does not parse is shown as an error and not saved:
        # the rotation keeps the last one that did.
        times = self.prefs["change_times"]
        try:
            times = [f"{h:02d}:{m:02d}" for h, m in core.parse_times(self.times.text())]
            self._bad_times = None
        except ValueError as exc:
            self._bad_times = str(exc)
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
            "change_mode": core.CHANGE_MODES[self.change_mode.currentIndex()][1],
            "change_every": self._every_minutes(),
            "change_times": times,
        })
        core.save_prefs(self.prefs)
        self._show_change_widgets()
        if self.prefs["change_mode"] != mode_before:
            self.check_timer()      # a foreign timer only matters off midnight
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
            lines, problem = [], None
            core.resume_auto(prefs, log=lines.append)
            # Ticking the box is also consent to the timer that keeps it going
            # with the window closed; without one, "by itself" would mean
            # "while this window happens to be open". After the resume, not
            # before: registering a timer can tick it at once (RunAtLoad,
            # StartWhenAvailable), and an unforced tick racing ahead of the
            # forced one would find a hand-set wallpaper still up and latch
            # the rotation straight back off.
            try:
                schedule.ensure_installed()
            except Exception as exc:
                problem = f"could not schedule the rotation: {exc}"
            said = lines[-1] if lines else ""
            if problem:
                said = f"{problem} · {said}" if said else problem
            win.post_to_ui(lambda: win.show_toast(said))
            win.post_to_ui(self.check_timer)

        threading.Thread(target=work, daemon=True).start()

    def check_timer(self):
        def work():
            try:
                state = schedule.status()
            except Exception:
                state = "current"     # unknown: say nothing rather than nag
            self.win.post_to_ui(lambda: self._show_timer(state))

        threading.Thread(target=work, daemon=True).start()

    def _show_timer(self, state):
        midnight = self.prefs["change_mode"] == "midnight"
        text, button = None, None
        if state == "missing":
            text = "Nothing is scheduled to run it while this window is closed."
            button = "Schedule it"
        elif state == "outdated":
            text = ("The installed timer runs another copy of the app, or "
                    "is from an older version — update it to run this one.")
            button = "Update it"
        elif state == "foreign" and not midnight:
            # Not ours to rewrite, so the most this can do is say what it
            # needs to be for changes through the day to land on time.
            text = ("The timer is managed outside this app. For changes "
                    "through the day it needs to run `random-wallpaper --auto "
                    "--quiet` every minute.")
        self.timer_status.setVisible(text is not None)
        self.timer_button.setVisible(button is not None)
        if text:
            self.timer_status.setText(text)
        if button:
            self.timer_button.setText(button)

    # ── updating the app ────────────────────────────────────────────────
    def _say_update(self, text):
        self.update_status.setText(text)
        self.update_status.setVisible(bool(text))

    def update_clicked(self):
        if self._release is None:
            self.check_update()
        else:
            self.install_update()

    def check_update(self):
        win = self.win
        self.update_button.setEnabled(False)
        self._say_update("checking…")

        def work():
            try:
                release, newer = update.check()
                error = None
            except update.UpdateError as exc:
                release, newer, error = None, False, str(exc)

            def done():
                self.update_button.setEnabled(True)
                if error:
                    self._say_update(error)
                elif not newer:
                    self._say_update(f"{__version__} is the latest version.")
                elif update.install_kind() == "source":
                    self._say_update(
                        f"{release['version']} is out — this copy runs from "
                        f"source, so update it the way it was installed: "
                        f"git pull, or uv tool upgrade randomwallpaper.")
                else:
                    self._release = release
                    self.update_button.setText(f"Update to {release['version']}")
                    self._say_update(f"{release['version']} is available — "
                                     f"{release['url']}")
            win.post_to_ui(done)

        threading.Thread(target=work, daemon=True).start()

    def install_update(self):
        win = self.win
        release = self._release
        self.update_button.setEnabled(False)
        self._say_update(f"downloading {release['version']}…")

        shown = [-1]

        def progress(done_bytes, total):
            pct = done_bytes * 100 // total if total else -1
            if pct != shown[0]:          # once per percent, not per chunk
                shown[0] = pct
                win.post_to_ui(lambda: self._say_update(
                    f"downloading {release['version']}… {pct}%"))

        def work():
            try:
                message, ok = update.apply(release, progress=progress), True
            except update.UpdateError as exc:
                message, ok = str(exc), False

            def done():
                self._say_update(message)
                if ok:
                    # The new version starts once this one is gone: the
                    # installer, or the helper apply() left, waits for it.
                    win.close()
                    from PySide6.QtWidgets import QApplication
                    QApplication.instance().quit()
                else:
                    self.update_button.setEnabled(True)
            win.post_to_ui(done)

        threading.Thread(target=work, daemon=True).start()

    def install_timer(self):
        win = self.win
        self.timer_button.setEnabled(False)

        def work():
            try:
                schedule.ensure_installed()
                msg = "scheduled — checked at login and every minute"
            except Exception as exc:
                msg = f"could not schedule the rotation: {exc}"

            def done():
                self.timer_button.setEnabled(True)
                win.show_toast(msg)
                self.check_timer()
            win.post_to_ui(done)

        threading.Thread(target=work, daemon=True).start()
