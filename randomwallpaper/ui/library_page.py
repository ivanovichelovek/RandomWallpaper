"""The Downloaded tab: everything you have kept, and what to do with it.

Two actions: put one up now, and say which season or holiday it belongs to.
Selection is multiple because pinning a handful at once is the normal way to
fill a category; setting a wallpaper is not, so that button asks for exactly
one.
"""
import hashlib
import os
import shutil
from pathlib import Path

from PySide6.QtCore import (
    QEvent, QObject, QRunnable, QSize, Qt, QThreadPool, Signal, Slot,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QIcon, QImage, QImageReader, QPainter, QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu,
    QPushButton, QStackedWidget, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from .. import core
from .style import CATEGORY_COLORS, FG_DIM
from ..paths import CACHE_DIR

THUMB_W, THUMB_H = 220, 124
THUMB_DIR = CACHE_DIR / "thumbs"


def _thumb_key(path):
    """Changes whenever the file does: path, size and mtime."""
    info = path.stat()
    raw = f"v2|{path}|{info.st_size}|{info.st_mtime_ns}".encode()
    return hashlib.sha1(raw).hexdigest()


def make_thumb(path):
    """A THUMB_W×THUMB_H QImage of `path`, centre-cropped, or None.

    QImage, not QPixmap: this runs on a worker thread, and a QPixmap belongs
    to the UI thread. Decoded at the size it is shown, not at full size and
    then scaled — for a JPEG, libjpeg does that in a fraction of the time, and
    a 4K frame decoded whole to make a 220-pixel tile is what used to freeze
    the tab. The result is cached on disk, keyed by the file's size and
    mtime, so the next visit reads a few kilobytes instead.
    """
    try:
        key = _thumb_key(path)
    except OSError:
        return None
    cached = THUMB_DIR / f"{key}.jpg"
    if cached.exists():
        image = QImage(str(cached))
        if not image.isNull():
            return image

    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and size.width() > 0 and size.height() > 0:
        scale = max(THUMB_W / size.width(), THUMB_H / size.height())
        if scale < 1:
            reader.setScaledSize(QSize(max(1, round(size.width() * scale)),
                                       max(1, round(size.height() * scale))))
    image = reader.read()
    if image.isNull():
        return None
    image = image.scaled(THUMB_W, THUMB_H, Qt.KeepAspectRatioByExpanding,
                         Qt.SmoothTransformation)
    # Cropped to exactly the tile, centred. Left at whatever the aspect ratio
    # gave, a taller picture's icon eats the room under it that the name and
    # its categories need, and Qt elides the whole label to fit.
    image = image.copy((image.width() - THUMB_W) // 2,
                       (image.height() - THUMB_H) // 2, THUMB_W, THUMB_H)
    try:
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        image.save(str(cached), "JPG", 85)
    except OSError:
        pass
    return image


CATEGORIES_ROLE = Qt.UserRole + 1
# The stylesheet's item margin + border + padding, on each side.
ITEM_INSET = 4 + 1 + 6


class _TileDelegate(QStyledItemDelegate):
    """The tile as Qt draws it — frame, picture, name — plus the categories
    underneath as coloured tags. A list item's text is one colour, and a
    category is what these tags are for telling apart at a glance."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.text = ""        # drawn in paint(), at a fixed place

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        # The name, a fixed gap under the picture. Left to Qt, a one-line
        # name is centred in all the room below the picture, which is also
        # where the tags go.
        name_font = QFont(option.font)
        name_fm = QFontMetrics(name_font)
        top = option.rect.top() + ITEM_INSET + THUMB_H + 6
        name_rect = option.rect.adjusted(ITEM_INSET, 0, -ITEM_INSET, 0)
        name_rect.setTop(top)
        name_rect.setHeight(name_fm.height())
        painter.setFont(name_font)
        painter.setPen(option.palette.color(option.palette.ColorRole.Text))
        painter.drawText(name_rect, Qt.AlignHCenter | Qt.AlignVCenter,
                         name_fm.elidedText(str(index.data(Qt.DisplayRole) or ""),
                                            Qt.ElideMiddle, name_rect.width()))

        categories = index.data(CATEGORIES_ROLE) or []
        if not categories:
            painter.restore()
            return
        font = QFont(option.font)
        # Pixels, not points: the stylesheet may have set the font in either,
        # and a point size of -1 is what the other one reads as.
        font.setPixelSize(max(10, round(QFontMetrics(option.font).height() * 0.72)))
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        fm = QFontMetrics(font)

        pad_x, gap = 8, 5
        height = fm.height() + 4
        area = option.rect.adjusted(ITEM_INSET, 0, -ITEM_INSET, -ITEM_INSET)
        widths = [fm.horizontalAdvance(core.theme_label(c)) + 2 * pad_x
                  for c in categories]
        # As many as fit on the line; the rest become "+N".
        shown, used = [], 0
        for i, (category, width) in enumerate(zip(categories, widths)):
            rest = len(categories) - i - 1
            more = fm.horizontalAdvance(f"+{rest}") + gap if rest else 0
            if used + width + more > area.width() and shown:
                break
            shown.append((category, width))
            used += width + gap
        hidden = len(categories) - len(shown)
        total = used - gap + (fm.horizontalAdvance(f"+{hidden}") + gap if hidden else 0)

        x = area.left() + max(0, (area.width() - total) // 2)
        y = name_rect.bottom() + 5
        for category, width in shown:
            color = QColor(CATEGORY_COLORS.get(category, FG_DIM))
            tint = QColor(color)
            tint.setAlpha(64)
            painter.setPen(Qt.NoPen)
            painter.setBrush(tint)
            painter.drawRoundedRect(x, y, width, height, height / 2, height / 2)
            painter.setPen(color)
            painter.drawText(x, y, width, height, Qt.AlignCenter,
                             core.theme_label(category))
            x += width + gap
        if hidden:
            painter.setPen(QColor(FG_DIM))
            painter.drawText(x, y, area.right() - x, height,
                             Qt.AlignLeft | Qt.AlignVCenter, f"+{hidden}")
        painter.restore()


class _ThumbSignals(QObject):
    ready = Signal(str, object)


class _ThumbJob(QRunnable):
    def __init__(self, path, signals):
        super().__init__()
        self.path = path
        self.signals = signals

    @Slot()
    def run(self):
        self.signals.ready.emit(str(self.path), make_thumb(self.path))


class LibraryPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.entries = []      # [(path, {categories})]
        self.pending_delete = []
        # Its own pool: the global one also runs the reel's downloads, and a
        # tile should not wait behind a 30-second network timeout.
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max(2, min(4, os.cpu_count() or 2)))
        self.thumb_signals = _ThumbSignals()
        self.thumb_signals.ready.connect(self._thumb_ready)
        self.thumbs = {}        # path -> QPixmap, for this session
        self.items = {}         # path -> QListWidgetItem, current listing

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
        self.list.setItemDelegate(_TileDelegate(self.list))
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
        self.pool.clear()       # tiles queued for a listing about to go away
        self.list.clear()
        self.items = {}
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

        # Room for two lines under the picture — the name and its
        # categories — plus the item's padding, border and margin from the
        # stylesheet (6 + 1 + 4 on each side). Short of that, Qt elides the
        # name to make the categories fit, or the other way round.
        line = self.list.fontMetrics().lineSpacing()
        tile = QSize(THUMB_W + 24, THUMB_H + 2 * line + 38)
        for path, categories in self.entries:
            # In calendar order, not alphabetical: THEMES is spring → easter.
            ordered = [key for key, *_ in core.THEMES if key in categories]
            tag = "  ".join(core.theme_label(c) for c in ordered)
            item = QListWidgetItem(path.stem)
            item.setSizeHint(tile)
            item.setData(Qt.UserRole, str(path))
            item.setData(CATEGORIES_ROLE, ordered)
            item.setToolTip(str(path) + ("\n" + tag if tag else ""))
            self.list.addItem(item)
            self.items[str(path)] = item
            known = self.thumbs.get(str(path))
            if known is not None:
                item.setIcon(QIcon(known))
            else:
                self.pool.start(_ThumbJob(path, self.thumb_signals))

        self.sync()

    def _thumb_ready(self, path_str, image):
        if image is None:
            return
        pix = QPixmap.fromImage(image)
        self.thumbs[path_str] = pix
        item = self.items.get(path_str)
        if item is not None:
            item.setIcon(QIcon(pix))

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

    @staticmethod
    def _dot(category):
        """The category's colour as a menu icon — the same one its tags use."""
        pix = QPixmap(12, 12)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(CATEGORY_COLORS.get(category, FG_DIM)))
        painter.drawEllipse(1, 1, 10, 10)
        painter.end()
        return QIcon(pix)

    def refresh_pin_menu(self):
        self.pin_menu.clear()
        for key, label, _, _ in core.THEMES:
            if key == "all":
                continue
            count = len(core.pool_images(key))
            text = f"{label}   {count}" if count else label
            action = self.pin_menu.addAction(self._dot(key), text)
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
