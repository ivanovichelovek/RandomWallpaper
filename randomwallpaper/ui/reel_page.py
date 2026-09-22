"""The Random tab: a reel of downloaded frames, kept or dropped one at a time.

Downloads run on a QThreadPool, prefetched REEL_AHEAD frames ahead of the one
on screen so the wait is invisible. Nothing is written to SAVE_DIR until Save
is pressed; Delete and closing the window both just unlink the cached file.
"""
import http.client
import urllib.error
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from .. import core

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


def _perforations():
    box = QWidget()
    box.setFixedWidth(14)
    layout = QVBoxLayout(box)
    layout.setAlignment(Qt.AlignCenter)
    layout.setSpacing(8)
    for _ in range(3):
        hole = QFrame()
        hole.setProperty("class", "perf")
        hole.setFixedSize(5, 5)
        hole.setStyleSheet("background:#8B90A8; border-radius:1px;")
        layout.addWidget(hole)
    return box


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
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── stage ─────────────────────────────────────────────────────────
        stage = QWidget()
        stage.setObjectName("stage")
        stage_layout = QHBoxLayout(stage)
        stage_layout.setContentsMargins(10, 10, 10, 10)
        stage_layout.setSpacing(10)
        root.addWidget(stage, 1)

        stage_layout.addWidget(_perforations())

        self.stack = QStackedWidget()
        stage_layout.addWidget(self.stack, 1)

        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignCenter)
        self.picture.setScaledContents(False)
        self.stack.addWidget(self.picture)

        self.message = QLabel()
        self.message.setProperty("class", "placeholder")
        self.message.setStyleSheet("color:#4C5170; font-size:13px;")
        self.message.setAlignment(Qt.AlignCenter)
        self.message.setWordWrap(True)
        self.stack.addWidget(self.message)

        stage_layout.addWidget(_perforations())

        # ── bottom bar ────────────────────────────────────────────────────
        bottom = QWidget()
        bottom.setObjectName("bottombar")
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(14, 8, 14, 8)
        bottom_layout.setSpacing(12)
        root.addWidget(bottom)

        meta = QVBoxLayout()
        meta.setSpacing(2)
        meta_widget = QWidget()
        meta_widget.setLayout(meta)
        bottom_layout.addWidget(meta_widget, 1)

        self.frame_name = QLabel()
        self.frame_name.setObjectName("frameName")
        meta.addWidget(self.frame_name)

        self.frame_meta = QLabel()
        self.frame_meta.setProperty("class", "mono")
        self.frame_meta.setStyleSheet("color:#8B90A8; font-family:monospace; font-size:11px;")
        meta.addWidget(self.frame_meta)

        self.prev_btn = QToolButton()
        self.prev_btn.setText("‹")
        self.prev_btn.setProperty("class", "icon")
        self.prev_btn.setToolTip("Previous frame (Left)")
        self.prev_btn.clicked.connect(lambda: self.go(self.index - 1))
        bottom_layout.addWidget(self.prev_btn)

        self.next_btn = QToolButton()
        self.next_btn.setText("›")
        self.next_btn.setProperty("class", "icon")
        self.next_btn.setToolTip("Next frame (Right)")
        self.next_btn.clicked.connect(lambda: self.go(self.index + 1))
        bottom_layout.addWidget(self.next_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setProperty("class", "danger")
        self.delete_btn.setToolTip("Throw this one away (D)")
        self.delete_btn.clicked.connect(self.delete)
        bottom_layout.addWidget(self.delete_btn)

        self.save_btn = QPushButton("Save")
        self.save_btn.setProperty("class", "accent")
        self.save_btn.setToolTip(f"Keep it in {core.SAVE_DIR} (S)")
        self.save_btn.clicked.connect(self.save)
        bottom_layout.addWidget(self.save_btn)

        # ── reel strip ────────────────────────────────────────────────────
        strip_scroll = QScrollArea()
        strip_scroll.setObjectName("reel")
        strip_scroll.setWidgetResizable(True)
        strip_scroll.setFixedHeight(78)
        strip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        strip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(strip_scroll)

        self.strip_widget = QWidget()
        self.strip = QHBoxLayout(self.strip_widget)
        self.strip.setContentsMargins(10, 8, 10, 8)
        self.strip.setSpacing(8)
        self.strip.addStretch(1)
        strip_scroll.setWidget(self.strip_widget)

        self._refresh_style_targets()
        self.top_up()
        self.sync()

    def _refresh_style_targets(self):
        for w in (self.delete_btn,):
            w.style().unpolish(w)
            w.style().polish(w)

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
            self.window_.set_position(f"{self.index + 1}/{len(self.frames)}")
            pix = QPixmap(str(frame["path"]))
            if not pix.isNull():
                self._set_picture(pix)
            self.stack.setCurrentWidget(self.picture)
            self.frame_name.setText(frame["name"])

            w, h = frame.get("width"), frame.get("height")
            if not (w and h) and not pix.isNull():
                w, h = pix.width(), pix.height()
            bits = [frame["source"]]
            if w and h:
                bits.append(f"{w}×{h}")
            bits.append(core.human_size(frame["bytes"]))
            if frame.get("credit"):
                bits.append(frame["credit"])
            self.frame_meta.setText("  ·  ".join(bits))
        else:
            self.window_.set_position("")
            self.frame_name.setText("")
            self.frame_meta.setText("")
            self.message.setText(
                "Loading the reel…" if pending
                else self.error or "Nothing left in the reel."
            )
            self.stack.setCurrentWidget(self.message)

        self.rebuild_strip()

    def _set_picture(self, pix):
        self._current_pix = pix
        target = self.picture.size()
        if target.width() > 10 and target.height() > 10:
            scaled = pix.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            scaled = pix
        self.picture.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_current_pix", None) is not None and self.current():
            self._set_picture(self._current_pix)

    def rebuild_strip(self):
        while self.strip.count() > 1:
            item = self.strip.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for i, frame in enumerate(self.frames):
            btn = QToolButton()
            btn.setProperty("class", "reelFrame")
            btn.setProperty("current", i == self.index)
            btn.setToolTip(frame["name"])
            btn.setFixedSize(96, 54)
            btn.setIconSize(btn.size())
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
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            self.strip.insertWidget(self.strip.count() - 1, btn)
