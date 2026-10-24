"""The Saved tab: everything you have kept, and what to do with it.

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
    QEvent, QObject, QRectF, QRunnable, QSize, Qt, QThreadPool, Signal, Slot,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QIcon, QImage, QImageReader, QPainter,
    QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QPushButton, QStackedWidget,
    QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from .. import core
from . import style
from .style import CATEGORY_COLORS, touch_scroll
from .widgets import label
from ..paths import CACHE_DIR, IS_ANDROID

# Smaller on a phone, so two tiles share its width rather than one sitting
# beside an empty column.
THUMB_W, THUMB_H = (160, 90) if IS_ANDROID else (220, 124)
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
TILE_GAP = 6        # around each picture, inside its cell
RADIUS = 12


class _TileDelegate(QStyledItemDelegate):
    """A tile is its picture: rounded, with a dot per category it is pinned
    to, a ★ when it is in the shuffle set, and a ring in the accent when it
    is picked. The name is in the tooltip; on a grid of wallpapers the
    pictures are what tells them apart."""

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect.adjusted(TILE_GAP, TILE_GAP, -TILE_GAP, -TILE_GAP)
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS, RADIUS)

        icon = index.data(Qt.DecorationRole)
        if isinstance(icon, QIcon) and not icon.isNull():
            pix = icon.pixmap(rect.size())
            painter.setClipPath(path)
            painter.drawPixmap(rect, pix)
            painter.setClipping(False)
        else:
            painter.fillPath(path, QColor(style.token("well")))

        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        if selected:
            painter.setPen(QPen(QColor(style.token("accent")), 3))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), RADIUS + 1, RADIUS + 1)
        if (option.state & QStyle.State_HasFocus
                and self.parent().property("kbfocus")):
            # The keyboard's tile, picked or not: see style.FocusRing.
            painter.setPen(QPen(QColor(style.token("fg")), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-4, -4, 4, 4), RADIUS + 4, RADIUS + 4)
        elif hover and not selected:
            painter.setPen(QPen(QColor(style.token("border")), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect, RADIUS, RADIUS)

        categories = index.data(CATEGORIES_ROLE) or []
        if core.SHUFFLE in categories:
            badge = rect.adjusted(rect.width() - 30, 6, -6, 0)
            badge.setHeight(24)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, 150))
            painter.drawEllipse(badge)
            star = QFont(option.font)
            star.setPixelSize(14)
            painter.setFont(star)
            painter.setPen(QColor(CATEGORY_COLORS[core.SHUFFLE]))
            painter.drawText(badge, Qt.AlignCenter, "★")
        dots = [c for c in categories if c != core.SHUFFLE]
        if dots:
            x, y = rect.left() + 8, rect.bottom() - 18
            back = QRectF(x - 4, y - 4, 14 * len(dots) + 4, 18)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, 140))
            painter.drawRoundedRect(back, 9, 9)
            for category in dots:
                painter.setBrush(QColor(CATEGORY_COLORS.get(category, "#999999")))
                painter.drawEllipse(QRectF(x, y, 10, 10))
                x += 14
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
        if IS_ANDROID:
            root.setContentsMargins(12, 12, 12, 10)
        else:
            root.setContentsMargins(4, 16, 16, 16)
        root.setSpacing(12)

        # ── heading, search and what to show ─────────────────────────────
        head = QHBoxLayout()
        head.setSpacing(10)
        root.addLayout(head)
        head.addWidget(label("Saved", "h1"))
        self.total = label("", "mono")
        head.addWidget(self.total, 0, Qt.AlignBottom)
        head.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Search by name")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        if IS_ANDROID:
            root.addWidget(self.search)
        else:
            self.search.setMaximumWidth(260)
            head.addWidget(self.search, 1)
        # Everything, or only what is pinned to one category: the shuffle
        # set, a season, a holiday — each with how many it holds.
        self.show_only = QComboBox()
        self.show_only.setToolTip("Show every wallpaper, or only the ones in "
                                  "the shuffle set or pinned to a season or holiday")
        self.show_only.addItem("All", None)
        self.show_only.addItem(self._dot(core.SHUFFLE), "★ Shuffle", core.SHUFFLE)
        for key in core.pin_categories():
            if key != core.SHUFFLE:
                self.show_only.addItem(self._dot(key), core.theme_label(key), key)
        self.show_only.currentIndexChanged.connect(self.apply_filter)
        head.addWidget(self.show_only)

        self.list = QListWidget()
        self.list.setObjectName("library")
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setIconSize(QSize(THUMB_W, THUMB_H))
        self.list.setSpacing(0)
        self.list.setMouseTracking(True)
        self.list.setItemDelegate(_TileDelegate(self.list))
        self.list.itemSelectionChanged.connect(self.sync)
        # Space toggling the current tile's pick state, the way it did in the
        # original, needs an event filter: focus lives on the list itself
        # (QListWidget consumes its own key events before they would ever
        # reach LibraryPage.keyPressEvent), and Qt's own binding for Space in
        # an item view does not double as multi-select in IconMode.
        self.list.installEventFilter(self)
        touch_scroll(self.list)
        root.addWidget(self.list, 1)

        self.empty = label("", "placeholder", wrap=True)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setVisible(False)
        root.addWidget(self.empty, 1)

        # ── what to do with the ones picked ──────────────────────────────
        self.footer = QStackedWidget()
        root.addWidget(self.footer)

        bottom = QWidget()
        self.footer.addWidget(bottom)
        bottom_row = QHBoxLayout(bottom)
        bottom_row.setContentsMargins(0, 0, 0, 0)
        pill = QFrame()
        pill.setObjectName("pill")
        if IS_ANDROID:
            # Five controls in one row are twice a phone's width: the count
            # on top and the four actions two by two below.
            bottom_row.addWidget(pill, 1)
            stack = QVBoxLayout(pill)
            stack.setContentsMargins(12, 10, 12, 10)
            stack.setSpacing(8)
            bl = QHBoxLayout()
            stack.addLayout(bl)
            actions = QGridLayout()
            actions.setSpacing(8)
            stack.addLayout(actions)
        else:
            bottom_row.addStretch(1)
            bottom_row.addWidget(pill)
            bottom_row.addStretch(1)
            bl = QHBoxLayout(pill)
            bl.setContentsMargins(16, 6, 6, 6)
            bl.setSpacing(4)
            actions = None

        def add_action(button, row, column):
            if actions is None:
                bl.addWidget(button)
            else:
                button.setMinimumHeight(44)
                actions.addWidget(button, row, column)

        self.count = label("", "strong")
        bl.addWidget(self.count, 1)
        bl.addSpacing(6)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setProperty("class", "danger flat" if not IS_ANDROID else "danger")
        self.delete_btn.setToolTip("Delete the selected wallpapers from disk (Del)")
        self.delete_btn.clicked.connect(self.delete_selected)
        add_action(self.delete_btn, 0, 0)

        self.pin_btn = QPushButton("Pin to…")
        if not IS_ANDROID:
            self.pin_btn.setProperty("class", "flat")
        self.pin_btn.setToolTip("Use the selected wallpapers for a season or holiday")
        self.pin_menu = QMenu(self.pin_btn)
        self.pin_menu.aboutToShow.connect(self.refresh_pin_menu)
        self.pin_btn.setMenu(self.pin_menu)
        add_action(self.pin_btn, 0, 1)

        self.shuffle_btn = QPushButton("★ Shuffle")
        if not IS_ANDROID:
            self.shuffle_btn.setProperty("class", "flat")
        self.shuffle_btn.clicked.connect(self.toggle_shuffle)
        add_action(self.shuffle_btn, 1, 0)

        self.set_btn = QPushButton("Set as wallpaper")
        self.set_btn.setProperty("class", "accent")
        self.set_btn.setToolTip("Put this one up now")
        self.set_btn.clicked.connect(self.set_as_wallpaper)
        add_action(self.set_btn, 1, 1)
        # Each screen its own: the button opens a choice of screen instead.
        self.screen_menu = QMenu(self)
        self.screen_menu.aboutToShow.connect(self.refresh_screen_menu)
        self.actions = [self.delete_btn, self.pin_btn, self.shuffle_btn, self.set_btn]

        confirm = QFrame()
        confirm.setObjectName("confirm")
        cl = QHBoxLayout(confirm)
        cl.setContentsMargins(16, 10, 10, 10)
        cl.setSpacing(10)
        self.footer.addWidget(confirm)

        self.confirm_label = label("", None, wrap=True)
        cl.addWidget(self.confirm_label, 1)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.cancel_delete)
        cl.addWidget(cancel_btn)

        confirm_btn = QPushButton("Delete")
        confirm_btn.setProperty("class", "accent")
        confirm_btn.clicked.connect(self.do_delete)
        cl.addWidget(confirm_btn)

        self.sync()

    def _fit_tiles(self):
        """As many columns as fit, each as wide as the room allows — on a
        phone two tiles fill its width rather than leaving a gap at the
        right."""
        # The list's own width less a scroll bar's, whether one shows yet or
        # not: the grid is laid out before the bar decides to appear.
        # Qt's icon view wraps a row a little before it is quite full, so
        # some slack beyond the scroll bar too.
        room = self.list.width() - self.list.verticalScrollBar().sizeHint().width() - 24
        if room <= 0:
            return
        least = THUMB_W + 2 * TILE_GAP
        columns = max(2 if IS_ANDROID else 1, room // least)
        width = room // columns
        height = round((width - 2 * TILE_GAP) * THUMB_H / THUMB_W) + 2 * TILE_GAP
        size = QSize(width, height)
        if self.list.gridSize() != size:
            self.list.setGridSize(size)
        for item in self.items.values():
            if item.sizeHint() != size:
                item.setSizeHint(size)

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
        for key in core.pin_categories():
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
                f"Nothing kept yet. Press Keep on the Random tab and it lands "
                f"in {core.SAVE_DIR}."
            )
            self.sync()
            return

        # Room for two lines under the picture — the name and its
        # categories — plus the item's padding, border and margin from the
        # stylesheet (6 + 1 + 4 on each side). Short of that, Qt elides the
        # name to make the categories fit, or the other way round.
        tile = QSize(THUMB_W + 2 * TILE_GAP, THUMB_H + 2 * TILE_GAP)
        for path, categories in self.entries:
            # In calendar order, not alphabetical: spring → easter, shuffle.
            ordered = [key for key in core.pin_categories() if key in categories]
            tag = "  ".join(core.theme_label(c) for c in ordered)
            item = QListWidgetItem(path.stem)
            item.setData(Qt.UserRole + 2, path.stem.lower())
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

        self._fit_tiles()
        self.apply_filter()

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

    def in_shuffle(self, path):
        item = self.items.get(str(path))
        return item is not None and core.SHUFFLE in (item.data(CATEGORIES_ROLE) or [])

    def apply_filter(self):
        only = self.show_only.currentData()
        words = self.search.text().strip().lower().split()
        for item in self.items.values():
            name = item.data(Qt.UserRole + 2) or ""
            hide = ((only and only not in (item.data(CATEGORIES_ROLE) or []))
                    or any(w not in name for w in words))
            item.setHidden(hide)
            if hide:
                item.setSelected(False)
        if self.entries:
            # Nothing left to show is said, not left as a blank grid.
            shown = any(not item.isHidden() for item in self.items.values())
            self.list.setVisible(shown)
            self.empty.setVisible(not shown)
            if not shown and words:
                self.empty.setText("Nothing saved matches that name.")
            elif not shown:
                self.empty.setText(
                    "Nothing in the shuffle set yet: pick some under All and "
                    "press ★ Shuffle." if only == core.SHUFFLE else
                    f"Nothing pinned to {core.theme_label(only)} yet: pick "
                    f"some under All, then Pin to… → {core.theme_label(only)}.")
        self.sync()

    def sync(self):
        chosen = self.selected()
        self.set_btn.setEnabled(len(chosen) == 1)
        separate = core.screens_mode(self.win.prefs) == "separate"
        if separate != (self.set_btn.menu() is not None):
            self.set_btn.setMenu(self.screen_menu if separate else None)
        self.pin_btn.setEnabled(bool(chosen))
        self.delete_btn.setEnabled(bool(chosen))
        self.shuffle_btn.setEnabled(bool(chosen))
        # One button both ways: a selection already all in the set can only
        # mean taking it out.
        leaving = bool(chosen) and all(self.in_shuffle(p) for p in chosen)
        self.shuffle_btn.setText("Remove from ★" if leaving else "★ Shuffle")
        self.shuffle_btn.setToolTip(
            "Take the selected wallpapers out of the shuffle set" if leaving else
            "Add the selected wallpapers to the shuffle set — the rotation "
            "draws from it when set to Shuffle my picks")
        for i in range(1, self.show_only.count()):
            key = self.show_only.itemData(i)
            name = "★ Shuffle" if key == core.SHUFFLE else core.theme_label(key)
            held = sum(key in cats for _, cats in self.entries)
            self.show_only.setItemText(i, f"{name}   {held}" if held else name)
        total = len(self.entries)
        self.total.setText(str(total) if total else "")
        if chosen:
            self.count.setText(f"{len(chosen)} picked")
        else:
            self.count.setText(f"{'Tap' if IS_ANDROID else 'Click'} to pick"
                               if total else "")
        if not IS_ANDROID:
            # The bar is a hint until something is picked, then the actions.
            for button in self.actions:
                button.setVisible(bool(chosen))

    def eventFilter(self, watched, event):
        if watched is self.list and event.type() == QEvent.Resize:
            # The list's own new width, which the page's resize precedes.
            self._fit_tiles()
        if watched is self.list and event.type() == QEvent.KeyPress \
                and event.key() == Qt.Key_Space and not self.asking():
            item = self.list.currentItem()
            if item is not None:
                item.setSelected(not item.isSelected())
            return True
        if watched is self.list and event.type() == QEvent.KeyPress \
                and event.key() in (Qt.Key_Return, Qt.Key_Enter) and not self.asking():
            # Enter sets the tile as the wallpaper — the picked ones, or the
            # one the keyboard is on; with screens of their own, the menu
            # asking which one opens.
            item = self.list.currentItem()
            if item is not None and not self.list.selectedItems():
                item.setSelected(True)
            if self.set_btn.isEnabled():
                if self.set_btn.menu() is not None:
                    self.set_btn.showMenu()
                else:
                    self.set_as_wallpaper()
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
    def set_as_wallpaper(self, output=None):
        chosen = self.selected()
        if len(chosen) != 1:
            return
        if self.win.set_and_latch(chosen[0], failure="Could not set it",
                                  output=output):
            where = f" on {output}" if output else ""
            self.win.show_toast(f"Wallpaper set{where}  {chosen[0].name}")

    def refresh_screen_menu(self):
        self.screen_menu.clear()
        here = self.win.this_output()
        for name in core.wallpapers_on_outputs():
            text = f"{name}  — this screen" if name == here else name
            action = self.screen_menu.addAction(text)
            action.triggered.connect(lambda _=False, n=name: self.set_as_wallpaper(n))
        self.screen_menu.addSeparator()
        every = self.screen_menu.addAction("Every screen")
        every.triggered.connect(lambda _=False: self.set_as_wallpaper())

    def links_of(self, path):
        """Every name this app gave the same image — SAVE_DIR, the platform's
        Pictures wallpapers folder, and every category pool. Deleting a
        wallpaper means the wallpaper is gone everywhere this app put it."""
        places = [core.SAVE_DIR, core.pictures_wallpapers()]
        places += [core.theme_pool(key) for key in core.pin_categories()]
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
        painter.setBrush(QColor(CATEGORY_COLORS.get(category, "#999999")))
        painter.drawEllipse(1, 1, 10, 10)
        painter.end()
        return QIcon(pix)

    def refresh_pin_menu(self):
        self.pin_menu.clear()
        for key in core.pin_categories():
            if key == core.SHUFFLE:
                continue        # it has a button of its own
            label = core.theme_label(key)
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

    def toggle_shuffle(self):
        chosen = self.selected()
        if not chosen:
            return
        if not all(self.in_shuffle(p) for p in chosen):
            self.pin(core.SHUFFLE)
            return
        # Out of the set is out of its directory only. A name there that is
        # also the picture's only one — a file dropped straight into the
        # folder — goes to the trash rather than away for good.
        removed = 0
        for path in chosen:
            for pinned in core.pool_images(core.SHUFFLE):
                if not self._same(path, pinned):
                    continue
                try:
                    if pinned.stat().st_nlink > 1:
                        pinned.unlink()
                    elif not core.trash(pinned):
                        continue
                    removed += 1
                except OSError:
                    pass
        self.win.show_toast(
            f"Removed {removed} from Shuffle "
            f"— {len(core.pool_images(core.SHUFFLE))} in it now")
        self.reload()

    @staticmethod
    def _same(a, b):
        try:
            return Path(a).samefile(b)
        except OSError:
            return False
