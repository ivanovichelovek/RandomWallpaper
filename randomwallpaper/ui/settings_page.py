"""The Settings tab.

Every control here writes the config the moment it changes — there is no Done
button, because there is nothing to dismiss; leaving the tab is just
switching to another one.
"""
import os
import threading
from datetime import date, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QBoxLayout, QButtonGroup, QCheckBox, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton, QScrollArea,
    QSpinBox, QVBoxLayout, QWidget,
)

from .. import __version__, core, schedule, update
from ..paths import IS_ANDROID
from .style import Switch, theme as look, touch_scroll
from .widgets import Choice, Segmented, card, label, repolish, row, rule, titled


class _Columns(QWidget):
    """Two columns side by side, or one above the other when there is not
    room for both — a narrow window, a tile, a phone."""

    def __init__(self, breakpoint=860):
        super().__init__()
        self.breakpoint = breakpoint
        self.box = QBoxLayout(QBoxLayout.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(16)
        self.left = QVBoxLayout()
        self.left.setSpacing(16)
        self.right = QVBoxLayout()
        self.right.setSpacing(16)
        self.box.addLayout(self.left, 5)
        self.box.addLayout(self.right, 4)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        wide = event.size().width() >= self.breakpoint
        direction = QBoxLayout.LeftToRight if wide else QBoxLayout.TopToBottom
        if self.box.direction() != direction:
            self.box.setDirection(direction)
            for column in (self.left, self.right):
                column.setStretch(column.count() - 1, 1 if wide else 0)


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
        touch_scroll(scroller)
        outer.addWidget(scroller)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        if IS_ANDROID:
            root_layout.setContentsMargins(12, 14, 12, 14)
        else:
            root_layout.setContentsMargins(4, 16, 16, 16)
        root_layout.setSpacing(14)
        scroller.setWidget(root)
        root_layout.addWidget(label("Settings", "h1"))
        columns = _Columns()
        root_layout.addWidget(columns)
        self._bad_times = None

        # ══ left: changing the wallpaper ════════════════════════════════
        auto_card, auto = card(spacing=14)
        columns.left.addWidget(auto_card)
        # Nothing runs the rotation on a phone while the app is closed —
        # no systemd, launchd or Task Scheduler — so there is nothing here
        # to switch on.
        auto_card.setVisible(not IS_ANDROID)

        head, self.auto_about = titled(
            "Change the wallpaper by itself",
            "Puts up a new wallpaper on its own, even while this window is "
            "closed. Off: it only changes when you press Keep or Set.")
        head.layout().itemAt(0).widget().setProperty("class", "h2")
        self.auto = Switch()
        self.auto.setChecked(prefs["auto_enabled"])
        self._suppress_auto = False
        self.auto.toggled.connect(self.apply)
        auto.addWidget(row(head, self.auto))

        # ── where it comes from ──
        auto.addWidget(label("Where the new wallpaper comes from", "strong"))
        choices = QHBoxLayout() if not IS_ANDROID else QVBoxLayout()
        choices.setSpacing(10)
        auto.addLayout(choices)
        self.rotation_group = QButtonGroup(self)
        self.rotation_buttons = {}
        self.rotation_cards = {}
        texts = {
            "calendar": ("The season or holiday",
                         "Autumn, Halloween, Christmas… as the date comes. Uses "
                         "the wallpapers pinned there; with none, downloads "
                         "one that fits."),
            core.SHUFFLE: ("My shuffle set ★",
                           "The wallpapers you starred on the Saved tab, "
                           "whatever the date. Nothing is downloaded."),
        }
        for _, key in core.ROTATIONS:
            title, text = texts[key]
            choice = Choice(title, text)
            choice.setChecked(core.rotation(prefs) == key)
            self.rotation_group.addButton(choice.radio)
            self.rotation_buttons[key] = choice.radio
            self.rotation_cards[key] = choice
            choices.addWidget(choice, 1)
        self.rotation_group.buttonToggled.connect(self._rotation_toggled)
        self.calendar_state = label("", "mono", wrap=True)
        self.rotation_cards["calendar"].extra.addWidget(self.calendar_state)
        self.shuffle_state = label("", "mono", wrap=True)
        self.rotation_cards[core.SHUFFLE].extra.addWidget(self.shuffle_state)

        # Easter: only the calendar has an Easter to date.
        self.rite_row = QWidget()
        rite = QHBoxLayout(self.rite_row)
        rite.setContentsMargins(0, 4, 0, 0)
        rite.setSpacing(10)
        rite.addWidget(label("Easter dates", "help"))
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
        self.rotation_cards["calendar"].extra.addWidget(self.rite_row)
        auto.addWidget(label("Pin wallpapers to a season or holiday, or star "
                             "them for the shuffle set, on the Saved tab.",
                             "help", wrap=True))

        # ── how often ──
        auto.addWidget(label("How often", "strong"))
        self.change_mode = Segmented(
            [("Once a day", "midnight"), ("Every few hours", "every"),
             ("At set times", "times")], strong=True, expand=True)
        self.change_mode.setCurrentIndex(
            self._pos(core.CHANGE_MODES, prefs["change_mode"]))
        auto.addWidget(self.change_mode)
        often = QHBoxLayout()
        often.setSpacing(8)
        auto.addLayout(often)
        self.every_label = label("Every", "help")
        often.addWidget(self.every_label)
        self.every = QSpinBox()
        self.every.setButtonSymbols(QSpinBox.NoButtons)
        self.every.setAlignment(Qt.AlignCenter)
        self.every.setMinimumWidth(64)
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
        self.change_hint = label("", "help", wrap=True)
        auto.addWidget(self.change_hint)

        self.change_mode.currentIndexChanged.connect(self.apply)
        self.every.valueChanged.connect(self.apply)
        self.every_unit.currentIndexChanged.connect(self._every_unit_changed)
        self.times.editingFinished.connect(self.apply)
        self._show_change_widgets()

        # ── what happens next ──
        note = QFrame()
        note.setProperty("class", "note")
        note_layout = QHBoxLayout(note)
        note_layout.setContentsMargins(14, 10, 10, 10)
        note_layout.setSpacing(10)
        next_text = QVBoxLayout()
        next_text.setSpacing(2)
        self.next_label = label("", "accentText", wrap=True)
        next_text.addWidget(self.next_label)
        self.auto_status = label("", "mono", wrap=True)
        next_text.addWidget(self.auto_status)
        note_layout.addLayout(next_text, 1)
        self.change_now = QPushButton("Change now")
        self.change_now.setProperty("class", "accent")
        self.change_now.clicked.connect(lambda: self.retick(force=True))
        note_layout.addWidget(self.change_now, 0, Qt.AlignVCenter)
        auto.addWidget(note)

        # The rotation only runs while the window is closed if something runs
        # it: a systemd timer, a LaunchAgent or a scheduled task. Hidden until
        # a check finds none — that check is a subprocess on Windows, so it
        # runs off the UI thread.
        timer_row = QHBoxLayout()
        auto.addLayout(timer_row)
        self.timer_status = label(
            "Nothing is scheduled to run it while this window is closed.",
            "error", wrap=True)
        self.timer_button = QPushButton("Schedule it")
        self.timer_button.clicked.connect(self.install_timer)
        timer_row.addWidget(self.timer_status, 1)
        timer_row.addWidget(self.timer_button)
        self.timer_status.hide()
        self.timer_button.hide()

        # ══ right: the reel ══════════════════════════════════════════════
        reel_card, reel = card()
        columns.right.addWidget(reel_card)
        reel.addWidget(label("The reel", "h2"))
        reel.addWidget(label("What new downloads on the Random tab can be. "
                             "Saved wallpapers are not touched.", "help", wrap=True))

        self.source = Segmented([(name, key) for name, key, _ in core.SOURCES])
        self.source.setCurrentIndex(core.source_index(prefs["source"]))
        self.source.currentIndexChanged.connect(self.apply)
        reel.addWidget(row(label("Source", "strong"), self.source))
        self.source_hint = label("", "help", wrap=True)
        reel.addWidget(self.source_hint)

        # Wallhaven's own filters, shown only while it is the source.
        self.wallhaven_card = QWidget()
        wh = QVBoxLayout(self.wallhaven_card)
        wh.setContentsMargins(0, 0, 0, 0)
        wh.setSpacing(8)
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
        self.apikey = QLineEdit(prefs["wallhaven_apikey"])
        self.apikey.setPlaceholderText("API key — not needed for these filters")
        self.apikey.setEchoMode(QLineEdit.Password)
        self.apikey.textChanged.connect(self.apply)
        wh.addWidget(self.apikey)
        if os.environ.get("WALLHAVEN_API_KEY", "").strip():
            self.apikey.setEnabled(False)
            self.apikey.setPlaceholderText("taken from WALLHAVEN_API_KEY")
        reel.addWidget(self.wallhaven_card)

        self.theme = self._combo([t[1] for t in core.THEMES])
        self.theme.setCurrentIndex(core.theme_index(prefs["theme"]))
        self.theme.currentIndexChanged.connect(self.apply)
        theme_box, _ = titled("Theme", "A season, holiday or mood — or anything.")
        reel.addWidget(row(theme_box, self.theme))
        self.pool_status = label("", "mono", wrap=True)
        reel.addWidget(self.pool_status)

        reel.addWidget(rule())
        shape_box, _ = titled("Shape & size",
                              "Pictures smaller than the minimum are skipped.")
        reel.addWidget(shape_box)
        shape = QGridLayout()
        shape.setHorizontalSpacing(10)
        shape.setVerticalSpacing(4)
        reel.addLayout(shape)
        self.orientation = self._combo([o[0] for o in core.ORIENTATIONS])
        self.orientation.setCurrentIndex(
            self._pos(core.ORIENTATIONS, prefs["orientation"]))
        self.orientation.currentIndexChanged.connect(self.apply)
        self.minimum = self._combo([m[0] for m in core.MINIMUMS])
        self.minimum.setCurrentIndex(self._pos(core.MINIMUMS, prefs["minimum"]))
        self.minimum.currentIndexChanged.connect(self.apply)
        shape.addWidget(label("Orientation", "help"), 0, 0)
        shape.addWidget(label("Minimum resolution", "help"), 0, 1)
        shape.addWidget(self.orientation, 1, 0)
        shape.addWidget(self.minimum, 1, 1)

        # ══ right: screens ═══════════════════════════════════════════════
        screens_card, screens = card(spacing=10)
        columns.right.addWidget(screens_card)
        screens_card.setVisible(not IS_ANDROID)     # one screen, always
        screens.addWidget(label("Screens", "h2"))
        self.screens_count = label("", "help", wrap=True)
        screens.addWidget(self.screens_count)
        modes = QHBoxLayout()
        modes.setSpacing(8)
        screens.addLayout(modes)
        self.screens_group = QButtonGroup(self)
        self.screens_buttons = {}
        screen_texts = {"sync": "One wallpaper everywhere",
                        "separate": "A different one per screen"}
        for title, key in core.SCREEN_MODES:
            choice = Choice(title, screen_texts.get(key, ""))
            choice.setChecked(core.screens_mode(prefs) == key)
            self.screens_group.addButton(choice.radio)
            self.screens_buttons[key] = choice.radio
            modes.addWidget(choice, 1)
        self.screens_group.buttonToggled.connect(self._screens_toggled)

        self.main_output = self._combo([])
        self.main_output.currentIndexChanged.connect(self.apply)
        main_box, _ = titled("Main screen",
                             "A screen plugged in later copies its wallpaper.")
        self.main_row = row(main_box, self.main_output)
        screens.addWidget(self.main_row)
        self.fill_outputs()
        self.screens_about = label("", "help", wrap=True)
        screens.addWidget(self.screens_about)
        if not core.can_set_per_output():
            # Nothing here can tell one monitor's wallpaper from another's.
            for w in (*self.screens_buttons.values(), self.main_output):
                w.setEnabled(False)

        # ══ right: look & app ════════════════════════════════════════════
        app_card, app = card(spacing=10)
        columns.right.addWidget(app_card)
        app.addWidget(label("Look & app", "h2"))
        self.colors = Segmented([("From wallpaper", "wallpaper"), ("Fixed", "fixed")])
        self.colors.set_value(prefs.get("colors", "wallpaper"))
        self.colors.changed.connect(self._look_changed)
        colors_box, _ = titled("Colours", "From the wallpaper on screen, or one that stays.")
        app.addWidget(row(colors_box, self.colors))
        self.appearance = Segmented([("System", "system"), ("Dark", "dark"), ("Light", "light")])
        self.appearance.set_value(prefs.get("appearance", "system"))
        self.appearance.changed.connect(self._look_changed)
        app.addWidget(row(label("Appearance", "strong"), self.appearance))
        app.addWidget(rule())
        self.version_label = label(
            f"Random Wallpaper {__version__}  ·  {update.describe_install()}",
            "strong", wrap=True)
        self.update_button = QPushButton("Check for updates")
        self.update_button.clicked.connect(self.update_clicked)
        app.addWidget(row(self.version_label, self.update_button))
        self.update_status = label("", "help", wrap=True)
        self.update_status.hide()
        app.addWidget(self.update_status)
        self.check_updates = Switch()
        self.check_updates.setChecked(prefs["check_updates"])
        self.check_updates.toggled.connect(self.apply)
        app.addWidget(row(label("Look for updates when the app opens"), self.check_updates))
        self._release = None
        if update.install_kind() == "source":
            # Nothing here can replace a git checkout or a uv/pip install;
            # checking still says whether there is something newer.
            self.update_button.setToolTip(
                "Installed from source — update with git pull or "
                "uv tool upgrade randomwallpaper")

        for column in (columns.left, columns.right):
            column.addStretch(1)
        root_layout.addStretch(1)
        self.refresh_hint()
        if not IS_ANDROID:
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

    def _rotation(self):
        for key, button in self.rotation_buttons.items():
            if button.isChecked():
                return key
        return "calendar"

    def _rotation_toggled(self, button, checked):
        if not checked:
            return          # the other half of the same switch
        if (button is self.rotation_buttons[core.SHUFFLE]
                and self.prefs["change_mode"] == "midnight"):
            # Shuffling is for a wallpaper that changes through the day, so
            # it starts at once an hour. Through the widgets, which apply()
            # reads the prefs back from; the Change row can still say
            # otherwise afterwards.
            for w in (self.change_mode, self.every, self.every_unit):
                w.blockSignals(True)
            self.change_mode.setCurrentIndex(self._pos(core.CHANGE_MODES, "every"))
            self.every_unit.setCurrentIndex(1)
            self._set_every_range()
            self.every.setValue(1)
            for w in (self.change_mode, self.every, self.every_unit):
                w.blockSignals(False)
        self.apply()

    def _screens(self):
        for key, button in self.screens_buttons.items():
            if button.isChecked():
                return key
        return "sync"

    def fill_outputs(self):
        """The main-screen choices: automatic, then each monitor there now —
        and the one chosen before, even unplugged, so it is not lost."""
        names = list(core.wallpapers_on_outputs())
        chosen = self.prefs.get("primary_output") or ""
        if chosen and chosen not in names:
            names.append(chosen)
        auto = core.primary_output(dict(self.prefs, primary_output=""),
                                   core.wallpapers_on_outputs())
        self.main_output.blockSignals(True)
        self.main_output.clear()
        self.main_output.addItem(f"Automatic — {auto}" if auto else "Automatic", "")
        for name in names:
            self.main_output.addItem(name, name)
        self.main_output.setCurrentIndex(max(0, self.main_output.findData(chosen)))
        self.main_output.blockSignals(False)

    def _screens_toggled(self, button, checked):
        if not checked:
            return          # the other half of the same switch
        self.apply()
        # A new arrangement is due now, not at the next slot. With the
        # rotation on, a forced tick draws it — and gets past the latch, which
        # would otherwise read the switch itself as a hand-set wallpaper.
        # With it off, the same everywhere means copying the main one across.
        if self.prefs["auto_enabled"]:
            self.retick(force=True)
        elif self.prefs["screens"] == "sync":
            prefs, win = dict(self.prefs), self.win

            def work():
                lines = []
                core.match_main_output(prefs, log=lines.append)
                if lines:
                    win.post_to_ui(lambda: win.show_toast(lines[-1]))

            threading.Thread(target=work, daemon=True).start()

    def _show_change_widgets(self):
        mode = core.CHANGE_MODES[self.change_mode.currentIndex()][1]
        self.every.setVisible(mode == "every")
        self.every_unit.setVisible(mode == "every")
        self.every_label.setVisible(mode == "every")
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

        shuffling = core.rotation(self.prefs) == core.SHUFFLE
        self.rite_row.setVisible(not shuffling)
        how = core.describe_change(self.prefs)
        state = core.load_state()
        if shuffling:
            picks = len(core.pool_images(core.SHUFFLE))
            self.auto_about.setText(
                f"A random one of the wallpapers marked ★ on the Saved "
                f"tab, {how}, whatever the date.")
            if not picks:
                status = ("nothing marked ★ yet — select some on the "
                          "Saved tab and press ★ Shuffle")
            elif not self.prefs["auto_enabled"]:
                status = f"off — {picks} marked ★"
            elif state.get("period") == core.SHUFFLE:
                status = f"{picks} marked ★ · changed {state.get('applied_at', '?')}"
            else:
                status = f"{picks} marked ★ · not applied yet"
        else:
            self.auto_about.setText("With the season or the holiday, and "
                                    "inside each one as often as set below.")
            theme_now, period = core.current_period(date.today(), self.prefs["easter"])
            if not self.prefs["auto_enabled"]:
                status = f"off — today would be {core.theme_label(theme_now)}"
            elif state.get("period") == period:
                status = f"{period} applied {state.get('applied_at', '?')}"
            else:
                status = f"{period} — {core.theme_label(theme_now)}, not applied yet"
        self.auto_status.setText(status)

        if not core.can_set_per_output():
            about = ("This desktop keeps one wallpaper for every screen, so "
                     "they are always the same.")
        elif core.screens_mode(self.prefs) == "separate":
            about = ("Every screen keeps its own: the rotation draws a "
                     "different one for each, Set as wallpaper asks which, and "
                     "a monitor plugged in keeps the one it had.")
        else:
            about = ("A monitor plugged in takes the main screen's wallpaper "
                     "within a minute, rotation on or off.")
        self.main_row.setVisible(core.screens_mode(self.prefs) == "sync")
        self.screens_about.setText(about)

        if shuffling:
            self.change_hint.setText(
                "One marked ★ stays up; with several, they take turns at "
                "random, never the same one twice in a row. Nothing is "
                "downloaded.")
        elif self.prefs["change_mode"] == "midnight":
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
        self.change_hint.setProperty("class", "error" if self._bad_times else "help")
        repolish(self.change_hint)
        self._refresh_next(shuffling, state)

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
                f"downloads one. Pin some on the Saved tab, or put files "
                f"in {core.theme_pool(theme)}"
            )

    def _refresh_next(self, shuffling, state):
        """The cards' state lines and the note under How often: when the
        wallpaper changes next, and to what."""
        today = date.today()
        theme_now, _period = core.current_period(today, self.prefs["easter"])
        pinned = len(core.pool_images(theme_now))
        self.calendar_state.setText(
            f"Now: {core.theme_label(theme_now)} · "
            + (f"{pinned} pinned" if pinned else "nothing pinned — downloads"))
        picks = len(core.pool_images(core.SHUFFLE))
        self.shuffle_state.setText(f"{picks} starred" if picks else "nothing starred yet")

        if not self.prefs["auto_enabled"]:
            self.next_label.setText("Off — the wallpaper stays as it is")
            self.change_now.setEnabled(False)
            return
        self.change_now.setEnabled(True)
        when = core.next_change(self.prefs, datetime.now())
        day = ("today" if when.date() == today else
               "tomorrow" if (when.date() - today).days == 1 else
               when.strftime("%a %d %b"))
        at = f"{day} at {when:%H:%M}"
        if shuffling:
            what = (f"one of your {picks} starred wallpapers" if picks
                    else "nothing yet — star some on the Saved tab")
        else:
            what = (f"one of your {pinned} {core.theme_label(theme_now)} wallpapers"
                    if pinned else f"a fresh {core.theme_label(theme_now)} download")
        self.next_label.setText(f"Next change {at} — {what}")

        names = list(core.wallpapers_on_outputs()) if not IS_ANDROID else []
        if len(names) > 1:
            self.screens_count.setText(f"{len(names)} connected: {', '.join(names)}.")
        elif names:
            self.screens_count.setText(f"1 connected: {names[0]}.")
        else:
            self.screens_count.setText("")

    def _look_changed(self, _key=None):
        self.prefs["colors"] = self.colors.value()
        self.prefs["appearance"] = self.appearance.value()
        core.save_prefs(self.prefs)
        look.apply(force=True)

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
        rotation_before = core.rotation(self.prefs)
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
            "rotation": self._rotation(),
            "screens": self._screens(),
            "primary_output": self.main_output.currentData() or "",
            "check_updates": self.check_updates.isChecked(),
            "colors": self.colors.value(),
            "appearance": self.appearance.value(),
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
        elif self.auto.isChecked() and self.prefs["rotation"] != rotation_before:
            # A different thing to draw from is a different wallpaper due now,
            # not at the next tick of a timer that may not be running.
            self.retick()

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

    def retick(self, force=False):
        prefs = dict(self.prefs)
        win = self.win

        def work():
            lines = []
            core.run_auto(prefs, log=lines.append, quiet=True, force=force)
            if lines:
                win.post_to_ui(lambda: win.show_toast(lines[-1]))
            win.post_to_ui(self.refresh_hint)

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

    def check_at_start(self):
        """Quietly ask for a newer release; offer it if there is one.

        Nothing is said when there is not, or when the feed cannot be
        reached — the window has only just opened. A run from source is not
        asked at all: there is nothing here that could update it.
        """
        if not self.prefs["check_updates"] or update.install_kind() == "source":
            return
        win = self.win

        def work():
            try:
                release, newer = update.check()
            except update.UpdateError:
                return
            if newer:
                win.post_to_ui(lambda: self._offer(release))

        threading.Thread(target=work, daemon=True).start()

    def _offer(self, release):
        if self._release is not None:
            return                  # already offered, or found by the button
        self._release = release
        self.update_button.setText(f"Update to {release['version']}")
        self._say_update(f"{release['version']} is available — {release['url']}")
        box = QMessageBox(self.win)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("Update available")
        box.setText(f"Random Wallpaper {release['version']} is available — "
                    f"this is {__version__}.")
        box.setInformativeText("Install it now? The app restarts when it is "
                               "done. Checking at startup can be turned off "
                               "in Settings.")
        install = box.addButton("Update", QMessageBox.AcceptRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.setDefaultButton(install)
        box.exec()
        if box.clickedButton() is install:
            self.win.show_tab(2)
            self.install_update()

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
                if ok and IS_ANDROID:
                    # Android's installer asks the user, and answers this
                    # app: it has to still be running to show that screen.
                    # Installing replaces it when the user confirms.
                    self.update_button.setEnabled(True)
                elif ok:
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
