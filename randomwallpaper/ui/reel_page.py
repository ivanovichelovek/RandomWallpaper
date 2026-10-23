"""The Random tab: a reel of downloaded frames, kept or skipped one at a time.

Downloads run on a QThreadPool, prefetched REEL_AHEAD frames ahead of the one
on screen so the wait is invisible. Nothing is written to SAVE_DIR until Keep
is pressed; Skip and closing the window both just unlink the cached file.

The frame on screen also sets the window's colours (style.theme), and its
own few colours are shown as swatches beside its name.
"""
import http.client
import urllib.error
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRectF, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from .. import core
from ..paths import IS_ANDROID
from . import style
from .style import touch_scroll
from .widgets import label

REEL_AHEAD = core.REEL_AHEAD
MAX_DUPLICATE_RETRIES = core.MAX_DUPLICATE_RETRIES


class _Signals(QObject):
    done = Signal(dict, str)


class _DownloadJob(QRunnable):
    """Runs core.download() off the UI thread."""

    def __init__(self, prefs):
        super().__init__()
        self.prefs = prefs
        self.signals = _Signals()

    @Slot()
    def run(self):
        try:
            frame = core.download(self.prefs)
        except (urllib.error.URLError, http.client.HTTPException,
                OSError, ValueError, core.FetchError) as exc:
            self.signals.done.emit({}, str(exc))
        else:
            self.signals.done.emit(frame, "")


class _Picture(QLabel):
    """The frame, scaled to fit and with its corners rounded; a horizontal
    swipe across it goes to the next or the previous one."""
    swiped = Signal(int)

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        # Ignored, with a token minimum: a QLabel otherwise asks for its
        # pixmap's full size as its minimum, and a 2560×1440 frame shown
        # before the label has been laid out pushes the whole window past the
        # screen — in a tiling compositor, past the tile it was given.
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setMinimumSize(1, 1)
        self._press = None

    def mousePressEvent(self, event):
        self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._press is not None:
            delta = event.position().toPoint() - self._press
            if abs(delta.x()) > 60 and abs(delta.x()) > 2 * abs(delta.y()):
                self.swiped.emit(1 if delta.x() < 0 else -1)
        self._press = None
        super().mouseReleaseEvent(event)


def _rounded(pix, radius):
    if not radius:
        return pix
    out = QPixmap(pix.size())
    out.setDevicePixelRatio(pix.devicePixelRatio())
    out.fill(Qt.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    w = pix.width() / pix.devicePixelRatio()
    h = pix.height() / pix.devicePixelRatio()
    path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pix)
    painter.end()
    return out


class ReelPage(QWidget):
    save_pressed = Signal()
    filters_changed_external = Signal()

    def __init__(self, window):
        super().__init__()
        self.window_ = window
        self.prefs = window.prefs

        self.frames = []
        self.index = 0
        self.inflight = 0
        self.duplicates = 0
        self.error = None
        self.pool = QThreadPool.globalInstance()

        root = QVBoxLayout(self)
        if IS_ANDROID:
            root.setContentsMargins(0, 0, 0, 0)
        else:
            root.setContentsMargins(4, 16, 16, 16)
        root.setSpacing(12)

        # ── the frame ────────────────────────────────────────────────────
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.picture = _Picture()
        self.picture.swiped.connect(lambda d: self.go(self.index + d))
        self.stack.addWidget(self.picture)
        self.message = label("", "placeholder", wrap=True)
        self.message.setAlignment(Qt.AlignCenter)
        self.stack.addWidget(self.message)

        # ── what it is, and what to do with it ───────────────────────────
        bar = QFrame()
        bar.setProperty("class", "card")
        bar_layout = QVBoxLayout(bar)
        bar_layout.setContentsMargins(16, 12, 16, 12)
        bar_layout.setSpacing(10)
        if IS_ANDROID:
            holder = QWidget()
            holder_layout = QVBoxLayout(holder)
            holder_layout.setContentsMargins(12, 0, 12, 10)
            holder_layout.addWidget(bar)
            root.addWidget(holder)
        else:
            root.addWidget(bar)

        info = QHBoxLayout()
        info.setSpacing(10)
        bar_layout.addLayout(info)
        meta = QVBoxLayout()
        meta.setSpacing(2)
        info.addLayout(meta, 1)
        self.frame_name = label("", "title")
        meta.addWidget(self.frame_name)
        self.frame_meta = label("", "mono")
        meta.addWidget(self.frame_meta)
        # A long file name or credit is clipped, not allowed to set the
        # window's minimum width.
        for w in (self.frame_name, self.frame_meta):
            w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            w.setMinimumWidth(1)
        self.swatches = QHBoxLayout()
        self.swatches.setSpacing(4)
        info.addLayout(self.swatches)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        bar_layout.addLayout(buttons)
        self.prev_btn = QPushButton("‹")
        self.prev_btn.setProperty("class", "round")
        self.prev_btn.setToolTip("Previous frame (Left)")
        self.prev_btn.clicked.connect(lambda: self.go(self.index - 1))
        self.delete_btn = QPushButton("Skip")
        self.delete_btn.setProperty("class", "danger")
        self.delete_btn.setToolTip("Throw this one away (D)")
        self.delete_btn.clicked.connect(self.delete)
        self.save_btn = QPushButton("Keep")
        self.save_btn.setProperty("class", "accent")
        self.save_btn.setToolTip(f"Keep it in {core.SAVE_DIR} (S)")
        self.save_btn.clicked.connect(self.save)
        self.next_btn = QPushButton("›")
        self.next_btn.setProperty("class", "round")
        self.next_btn.setToolTip("Next frame (Right)")
        self.next_btn.clicked.connect(lambda: self.go(self.index + 1))
        for w in (self.delete_btn, self.save_btn):
            w.setMinimumHeight(44 if IS_ANDROID else 40)
        buttons.addWidget(self.prev_btn)
        buttons.addWidget(self.delete_btn)
        buttons.addWidget(self.save_btn, 1)
        buttons.addWidget(self.next_btn)
        if IS_ANDROID:
            # A swipe across the picture does what these do.
            self.prev_btn.hide()
            self.next_btn.hide()
            self.delete_btn.setMinimumWidth(96)

        # ── the reel strip: the frames fetched so far ────────────────────
        # Off by default in this layout — ‹ › and a swipe walk the reel —
        # and kept for a window tall enough to want it.
        self.strip_scroll = QScrollArea()
        self.strip_scroll.setWidgetResizable(True)
        self.strip_scroll.setFixedHeight(70)
        self.strip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        touch_scroll(self.strip_scroll)
        self.strip_widget = QWidget()
        self.strip = QHBoxLayout(self.strip_widget)
        self.strip.setContentsMargins(0, 4, 0, 4)
        self.strip.setSpacing(8)
        self.strip.addStretch(1)
        self.strip_scroll.setWidget(self.strip_widget)
        self.strip_scroll.hide()
        root.addWidget(self.strip_scroll)

        self._current_pix = None
        self._shown_path = None
        self.top_up()
        self.sync()

    # ── the reel ─────────────────────────────────────────────────────────
    def top_up(self):
        want = (self.index + 1 + REEL_AHEAD
                - len(self.frames) - self.inflight)
        for _ in range(max(0, want)):
            self.inflight += 1
            job = _DownloadJob(dict(self.prefs))
            job.signals.done.connect(self.arrived)
            self.pool.start(job)

    def arrived(self, frame, error):
        self.inflight -= 1
        if frame:
            if any(f["name"] == frame["name"] for f in self.frames):
                try:
                    Path(frame["path"]).unlink(missing_ok=True)
                except OSError:
                    pass
                self.duplicates += 1
                if self.duplicates <= MAX_DUPLICATE_RETRIES:
                    self.top_up()
                self.sync()
                return
            self.duplicates = 0
            self.frames.append(frame)
            self.error = None
        else:
            self.error = error
        self.sync()

    def current(self):
        return self.frames[self.index] if self.index < len(self.frames) else None

    def go(self, index):
        if 0 <= index < len(self.frames):
            self.index = index
            self.top_up()
            self.sync()

    def retheme(self):
        """New filters arrived (a later launch, or Settings changed). Frames
        already in the reel answer the old filters, so they go."""
        for frame in self.frames:
            try:
                Path(frame["path"]).unlink(missing_ok=True)
            except OSError:
                pass
        self.frames.clear()
        self.index = 0
        self.duplicates = 0
        self.error = None
        self.top_up()
        self.sync()

    def advance(self):
        if self.index >= len(self.frames):
            self.index = max(0, len(self.frames) - 1)
        self.top_up()
        self.sync()

    # ── actions ──────────────────────────────────────────────────────────
    def save(self):
        frame = self.current()
        if not frame:
            return
        core.SAVE_DIR.mkdir(parents=True, exist_ok=True)
        dest = core.unique_path(core.SAVE_DIR, frame["name"], frame["ext"])

        import shutil
        shutil.move(str(frame["path"]), dest)
        self.frames.pop(self.index)

        self.window_.link_into_pictures(dest)
        if self.prefs["set_on_save"]:
            self.window_.apply_wallpaper(dest)
        self.window_.show_toast(f"Saved  {dest}")
        self.advance()

    def delete(self):
        frame = self.current()
        if not frame:
            return
        try:
            Path(frame["path"]).unlink(missing_ok=True)
        except OSError:
            pass
        self.frames.pop(self.index)
        self.window_.show_toast(f"Dropped  {frame['name']}")
        self.advance()

    def filters_changed(self):
        self.top_up()

    # ── rendering ────────────────────────────────────────────────────────
    def sync(self):
        frame = self.current()
        pending = self.inflight > 0

        self.save_btn.setEnabled(frame is not None)
        self.delete_btn.setEnabled(frame is not None)
        self.prev_btn.setEnabled(self.index > 0)
        self.next_btn.setEnabled(self.index + 1 < len(self.frames))

        if frame:
            path = str(frame["path"])
            if path != self._shown_path:
                self._shown_path = path
                pix = QPixmap(path)
                self._current_pix = None if pix.isNull() else pix
                self._show_colours(pix)
            pix = self._current_pix
            if pix is not None:
                self._set_picture(pix)
            self.stack.setCurrentWidget(self.picture)
            self.frame_name.setText(frame["name"])

            w, h = frame.get("width"), frame.get("height")
            if not (w and h) and pix is not None:
                w, h = pix.width(), pix.height()
            bits = []
            if w and h:
                bits.append(f"{w}×{h}")
            bits.append(core.human_size(frame["bytes"]))
            bits.append(f"{self.index + 1}/{len(self.frames)}")
            if frame.get("credit"):
                bits.append(frame["credit"])
            self.frame_meta.setText(f"{frame['source']}  ·  " + "  ·  ".join(bits))
        else:
            self._shown_path = None
            self.frame_name.setText("")
            self.frame_meta.setText("")
            self._show_swatches([])
            self.message.setText(
                "Loading the reel…" if pending
                else self.error or "Nothing left in the reel."
            )
            self.stack.setCurrentWidget(self.message)

        if self.strip_scroll.isVisible():
            self.rebuild_strip()

    def _show_colours(self, pix):
        """The frame's swatches, and the window's colours from it."""
        if pix.isNull():
            self._show_swatches([])
            return
        image = pix.toImage().scaled(64, 64, Qt.IgnoreAspectRatio, Qt.FastTransformation)
        self._show_swatches(style.palette_from_image(image))
        style.theme.set_seed(style.seed_from_image(image))

    def _show_swatches(self, colours):
        while self.swatches.count():
            item = self.swatches.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for colour in colours:
            dot = QLabel()
            dot.setFixedSize(14, 14)
            # Picture colours, not theme ones: the one place a colour is
            # set inline, since it is data rather than look.
            dot.setStyleSheet(f"background:{colour}; border-radius:7px;")
            self.swatches.addWidget(dot)

    def _set_picture(self, pix):
        target = self.picture.size()
        if target.width() <= 10 or target.height() <= 10:
            return          # not laid out yet; resizeEvent comes back to it
        ratio = self.devicePixelRatioF()
        box = target * ratio
        if IS_ANDROID:
            # A phone shows the picture the way it would be a wallpaper:
            # filling the screen, cropped at the sides rather than letterboxed
            # into a strip across the middle.
            scaled = pix.scaled(box, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            scaled = scaled.copy((scaled.width() - box.width()) // 2,
                                 (scaled.height() - box.height()) // 2,
                                 box.width(), box.height())
        else:
            scaled = pix.scaled(box, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        scaled.setDevicePixelRatio(ratio)
        self.picture.setPixmap(_rounded(scaled, 0 if IS_ANDROID else 18))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_pix is not None and self.current():
            self._set_picture(self._current_pix)

    def rebuild_strip(self):
        while self.strip.count() > 1:
            item = self.strip.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for i, frame in enumerate(self.frames):
            btn = QToolButton()
            btn.setToolTip(frame["name"])
            btn.setFixedSize(96, 54)
            btn.setIconSize(btn.size())
            btn.setCheckable(True)
            btn.setChecked(i == self.index)
            btn.clicked.connect(lambda _checked=False, i=i: self.go(i))

            if "thumb" not in frame:
                pix = QPixmap(str(frame["path"]))
                frame["thumb"] = (
                    pix.scaled(96, 54, Qt.KeepAspectRatioByExpanding,
                               Qt.SmoothTransformation)
                    if not pix.isNull() else None
                )
            if frame["thumb"]:
                btn.setIcon(QIcon(frame["thumb"]))
            else:
                btn.setText("?")
            self.strip.insertWidget(self.strip.count() - 1, btn)
