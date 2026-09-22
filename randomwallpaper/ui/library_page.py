"""The Downloaded tab: everything you have kept, and what to do with it.

Two actions: put one up now, and say which season or holiday it belongs to.
Selection is multiple because pinning a handful at once is the normal way to
fill a category; setting a wallpaper is not, so that button asks for exactly
one.
"""
import os
import shutil
from pathlib import Path

from PySide6.QtCore import (
    QEvent, QObject, QRunnable, QSize, Qt, QThreadPool, Signal, Slot,
)
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import core

THUMB_W, THUMB_H = 220, 124


class _ThumbSignals(QObject):
    ready = Signal(str, object)


class _ThumbJob(QRunnable):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.signals = _ThumbSignals()

    @Slot()
    def run(self):
        pix = QPixmap(str(self.path))
        if not pix.isNull():
            pix = pix.scaled(THUMB_W, THUMB_H, Qt.KeepAspectRatioByExpanding,
                             Qt.SmoothTransformation)
        else:
            pix = None
        self.signals.ready.emit(str(self.path), pix)


class LibraryPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.entries = []      # [(path, {categories})]
        self.pending_delete = []
        self.pool = QThreadPool.globalInstance()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.list = QListWidget()
        self.list.setObjectName("library")
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setIconSize(QSize(THUMB_W, THUMB_H))
        self.list.setSpacing(6)
        self.list.setWordWrap(True)
        self.list.itemSelectionChanged.connect(self.sync)
        # Space toggling the current tile's pick state, the way it did in the
        # original, needs an event filter: focus lives on the list itself
        # (QListWidget consumes its own key events before they would ever
        # reach LibraryPage.keyPressEvent), and Qt's own binding for Space in
        # an item view does not double as multi-select in IconMode.
        self.list.installEventFilter(self)
        root.addWidget(self.list, 1)

        self.empty = QLabel()
        self.empty.setProperty("class", "placeholder")
        self.empty.setStyleSheet("color:#4C5170; font-size:13px;")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setVisible(False)
        root.addWidget(self.empty, 1)

        self.footer = QStackedWidget()
        root.addWidget(self.footer)

        bottom = QWidget()
        bottom.setObjectName("bottombar")
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(14, 8, 14, 8)
        bl.setSpacing(12)
        self.footer.addWidget(bottom)

        self.count = QLabel()
        self.count.setProperty("class", "mono")
        self.count.setStyleSheet("color:#8B90A8; font-family:monospace; font-size:11px;")
        bl.addWidget(self.count, 1)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setProperty("class", "danger")
        self.delete_btn.setToolTip("Delete the selected wallpapers from disk (Del)")
        self.delete_btn.clicked.connect(self.delete_selected)
        bl.addWidget(self.delete_btn)

        self.pin_btn = QPushButton("Pin to…")
        self.pin_btn.setToolTip("Use the selected wallpapers for a season or holiday")
        self.pin_menu = QMenu(self.pin_btn)
        self.pin_menu.aboutToShow.connect(self.refresh_pin_menu)
        self.pin_btn.setMenu(self.pin_menu)
        bl.addWidget(self.pin_btn)

        self.set_btn = QPushButton("Set as wallpaper")
        self.set_btn.setProperty("class", "accent")
        self.set_btn.setToolTip("Put this one on the desktop now")
        self.set_btn.clicked.connect(self.set_as_wallpaper)
        bl.addWidget(self.set_btn)

        confirm = QWidget()
        confirm.setObjectName("confirm")
        cl = QHBoxLayout(confirm)
        cl.setContentsMargins(14, 10, 14, 10)
        cl.setSpacing(12)
        self.footer.addWidget(confirm)

        self.confirm_label = QLabel()
        self.confirm_label.setObjectName("confirmText")
        self.confirm_label.setWordWrap(True)
        cl.addWidget(self.confirm_label, 1)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.cancel_delete)
        cl.addWidget(cancel_btn)

        confirm_btn = QPushButton("Delete")
        confirm_btn.setProperty("class", "danger")
        confirm_btn.clicked.connect(self.do_delete)
        cl.addWidget(confirm_btn)

        self.sync()

    # ── what is on disk ─────────────────────────────────────────────────────
    @staticmethod
    def scan():
        """Saved wallpapers, and which categories each one is in.

        Keyed by (device, inode), not by path: pinning hardlinks the file
        into the category's directory, so the same picture is reachable under
        two names — group them by inode and it appears once, not twice.
        """
        found = {}

        def add(path, category=None):
            if path.suffix.lower() not in core.IMAGE_EXTS or not path.is_file():
                return
            try:
                info = path.stat()
            except OSError:
                return
            entry = found.setdefault((info.st_dev, info.st_ino), [path, set()])
            if len(path.parts) < len(entry[0].parts):
                entry[0] = path
            if category:
                entry[1].add(category)

        try:
            for path in core.SAVE_DIR.iterdir():
                if path.is_file():
                    add(path)
        except OSError:
            pass
        for key, _, _, _ in core.THEMES:
            if key == "all":
                continue
            for path in core.pool_images(key):
                add(path, key)
        return sorted(((path, categories) for path, categories in found.values()),
                      key=lambda pair: pair[0].name.lower())

    def reload(self):
        self.list.clear()
        self.entries = self.scan()

        self.empty.setVisible(not self.entries)
        self.list.setVisible(bool(self.entries))
        if not self.entries:
            self.empty.setText(
                f"Nothing kept yet. Press Save on the Random tab and it lands "
                f"in {core.SAVE_DIR}."
            )
            self.sync()
            return

        for path, categories in self.entries:
            text = path.stem
            tag = "  ".join(core.theme_label(c) for c in sorted(categories))
            label = text + ("\n" + tag if tag else "")
            item = QListWidgetItem(label)
            item.setSizeHint(QSize(THUMB_W + 20, THUMB_H + 50))
            item.setData(Qt.UserRole, str(path))
            self.list.addItem(item)
            job = _ThumbJob(path)
            job.signals.ready.connect(self._thumb_ready)
            self.pool.start(job)

        self.sync()

    def _thumb_ready(self, path_str, pix):
        if pix is None:
            return
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.UserRole) == path_str:
                item.setIcon(QIcon(pix))
                break

    # ── selection ────────────────────────────────────────────────────────
    def selected(self):
        return [Path(item.data(Qt.UserRole)) for item in self.list.selectedItems()]

    def sync(self):
        chosen = self.selected()
        self.set_btn.setEnabled(len(chosen) == 1)
        self.pin_btn.setEnabled(bool(chosen))
        self.delete_btn.setEnabled(bool(chosen))
        total = len(self.entries)
        if chosen:
            self.count.setText(f"{len(chosen)} of {total} selected")
        else:
            self.count.setText(f"{total} kept  ·  click to pick")

    def eventFilter(self, watched, event):
        if watched is self.list and event.type() == QEvent.KeyPress \
                and event.key() == Qt.Key_Space and not self.asking():
            item = self.list.currentItem()
            if item is not None:
                item.setSelected(not item.isSelected())
            return True
        return super().eventFilter(watched, event)

    def asking(self):
        return self.footer.currentIndex() == 1

    def keyPressEvent(self, event):
        key = event.key()
        if self.footer.currentIndex() == 1:
            if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                self.do_delete()
                return
            if key == Qt.Key_Escape:
                self.cancel_delete()
                return
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selected()
            return
        if key == Qt.Key_A and event.modifiers() & Qt.ControlModifier:
            self.list.selectAll()
            return
        super().keyPressEvent(event)

    # ── actions ──────────────────────────────────────────────────────────
    def set_as_wallpaper(self):
        chosen = self.selected()
        if len(chosen) != 1:
            return
        if self.win.set_and_latch(chosen[0], failure="Could not set it"):
            self.win.show_toast(f"Wallpaper set  {chosen[0].name}")

    def links_of(self, path):
        """Every name this app gave the same image — SAVE_DIR, the platform's
        Pictures wallpapers folder, and every category pool. Deleting a
        wallpaper means the wallpaper is gone everywhere this app put it."""
        places = [core.SAVE_DIR, core.pictures_wallpapers()]
        places += [core.theme_pool(key) for key, _, _, _ in core.THEMES if key != "all"]
        found = []
        for directory in places:
            try:
                entries = list(directory.iterdir())
            except OSError:
                continue
            for other in entries:
                if other.is_file() and self._same(other, path):
                    found.append(other)
        seen, unique = set(), []
        for item in found:
            if str(item) not in seen:
                seen.add(str(item))
                unique.append(item)
        return unique

    def delete_selected(self):
        chosen = self.selected()
        if not chosen:
            return
        self.pending_delete = [(path, self.links_of(path)) for path in chosen]
        extra = sum(len(links) for _, links in self.pending_delete) - len(chosen)

        if len(chosen) == 1:
            text = f"Delete {chosen[0].name}?"
        else:
            text = f"Delete these {len(chosen)} wallpapers?"
        if extra > 0:
            text += (f"  {extra} more copy goes too" if extra == 1 else
                     f"  {extra} more copies go too")
            text += (" — the same picture is hardlinked into "
                     "Pictures/Wallpapers and into every category it is "
                     "pinned to.")
        text += "  They go to the trash."
        self.confirm_label.setText(text)
        self.footer.setCurrentIndex(1)

    def cancel_delete(self):
        self.pending_delete = []
        self.footer.setCurrentIndex(0)

    def do_delete(self):
        pending, self.pending_delete = self.pending_delete, []
        self.footer.setCurrentIndex(0)

        wallpapers = removed = failed = 0
        for _, links in pending:
            wallpapers += 1
            for path in links:
                if core.trash(path):
                    removed += 1
                else:
                    failed += 1
        if failed:
            self.win.show_toast(f"Deleted {removed}, could not delete {failed}")
        else:
            self.win.show_toast(
                f"Deleted {wallpapers} wallpaper"
                f"{'' if wallpapers == 1 else 's'}"
                + (f" ({removed} files)" if removed != wallpapers else ""))
        self.reload()

    def refresh_pin_menu(self):
        self.pin_menu.clear()
        for key, label, _, _ in core.THEMES:
            if key == "all":
                continue
            count = len(core.pool_images(key))
            text = f"{label}   {count}" if count else label
            action = self.pin_menu.addAction(text)
            action.triggered.connect(lambda _checked=False, k=key: self.pin(k))

    def pin(self, theme):
        chosen = self.selected()
        if not chosen:
            return

        directory = core.theme_pool(theme)
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.win.show_toast(f"Could not make {directory}: {exc}")
            return

        added = skipped = 0
        for path in chosen:
            if any(self._same(path, existing) for existing in core.pool_images(theme)):
                skipped += 1
                continue
            dest = core.unique_path(directory, path.stem, path.suffix)
            try:
                os.link(path, dest)
            except OSError:
                try:
                    shutil.copy2(path, dest)
                except OSError as exc:
                    self.win.show_toast(f"Could not pin {path.name}: {exc}")
                    continue
            added += 1

        label = core.theme_label(theme)
        if added and skipped:
            self.win.show_toast(
                f"Pinned {added} to {label}, {skipped} already there "
                f"— {len(core.pool_images(theme))} chosen for it now")
        elif added:
            self.win.show_toast(
                f"Pinned {added} to {label} "
                f"— {len(core.pool_images(theme))} chosen for it now")
        else:
            self.win.show_toast(f"Already pinned to {label}")
        self.reload()

    @staticmethod
    def _same(a, b):
        try:
            return Path(a).samefile(b)
        except OSError:
            return False
