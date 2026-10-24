"""Small building blocks the pages share: cards, labels by role, a segmented
control and a radio card. Each only sets an objectName or a "class"
property; what that looks like is in style.py.
"""
from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QBoxLayout, QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel,
    QPushButton, QRadioButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ..paths import IS_ANDROID


def repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def label(text="", cls=None, wrap=None):
    """A QLabel in a role. On a phone every one wraps unless told not to:
    a line wider than the screen widens the whole page with it."""
    w = QLabel(text)
    if cls:
        w.setProperty("class", cls)
    w.setWordWrap(IS_ANDROID if wrap is None else wrap)
    return w


def card(spacing=12, margins=(18, 16, 18, 16)):
    """A rounded surface, and the column inside it."""
    frame = QFrame()
    frame.setProperty("class", "card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return frame, layout


def rule():
    line = QFrame()
    line.setProperty("class", "rule")
    return line


def titled(title, help_text=None):
    """A setting's name with one line on what it does, as a column."""
    box = QWidget()
    column = QVBoxLayout(box)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(2)
    column.addWidget(label(title, "strong", wrap=True))
    helper = None
    if help_text is not None:
        helper = label(help_text, "help", wrap=True)
        column.addWidget(helper)
    return box, helper


class Row(QWidget):
    """A setting row: what it is on the left, its control on the right — or
    the control under it, when the two do not fit side by side."""

    def __init__(self, left, right, stretch_left=True):
        super().__init__()
        self.left, self.right = left, right
        self.box = QBoxLayout(QBoxLayout.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(12)
        if isinstance(left, QLabel):
            left.setWordWrap(True)      # a narrow screen wraps it, never widens
        self.box.addWidget(left, 1 if stretch_left else 0)
        self.box.addWidget(right, 0, Qt.AlignVCenter)

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QSize(max(self.left.minimumSizeHint().width(),
                         self.right.minimumSizeHint().width()), hint.height())

    def resizeEvent(self, event):
        # Side by side while the left keeps a fair share next to the control.
        need = self.right.sizeHint().width() + self.box.spacing() + 120
        across = event.size().width() >= need
        direction = QBoxLayout.LeftToRight if across else QBoxLayout.TopToBottom
        if self.box.direction() != direction:
            self.box.setDirection(direction)
            self.box.setAlignment(self.right, Qt.AlignVCenter if across else Qt.AlignLeft)
            QTimer.singleShot(0, self.updateGeometry)
        super().resizeEvent(event)


def row(left, right, stretch_left=True):
    return Row(left, right, stretch_left)


class Segmented(QFrame):
    """Checkable buttons in a pill, one of them on: a segmented control.

    `options` is [(label, key)]; `value()` and `set_value()` speak keys, and
    `changed(key)` fires when the user picks another one.
    """
    changed = Signal(str)
    # The QComboBox names too, so a combo can be swapped for one of these
    # without touching the code that reads it.
    currentIndexChanged = Signal(int)

    def __init__(self, options, strong=False, expand=False):
        super().__init__()
        self.setProperty("class", "segmented")
        self.setProperty("strong", strong)
        layout = QBoxLayout(QBoxLayout.LeftToRight, self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self.box = layout
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        for text, key in options:
            button = QPushButton(text)
            button.setProperty("class", "seg")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            self.group.addButton(button)
            self.buttons[key] = button
            layout.addWidget(button, 1 if expand else 0)
            button.clicked.connect(lambda _=False, k=key: self._picked(k))
            button.installEventFilter(self)
        self.keys = [key for _, key in options]
        if self.keys:
            self.buttons[self.keys[0]].setChecked(True)

    # Side by side when they fit, one above the other when they do not — a
    # phone in portrait has no room for "Once a day · Every few hours · At
    # set times" in a row, and a row that does not fit widens the whole page.
    def _row_width(self):
        m = self.box.contentsMargins()
        return (sum(b.sizeHint().width() for b in self.buttons.values())
                + self.box.spacing() * (len(self.buttons) - 1) + m.left() + m.right())

    def sizeHint(self):
        # What it would like is always the row, so a layout that can give
        # the room gets it back side by side after a narrow spell.
        return QSize(self._row_width(), super().sizeHint().height())

    def minimumSizeHint(self):
        m = self.box.contentsMargins()
        widest = max((b.minimumSizeHint().width() for b in self.buttons.values()), default=0)
        return QSize(widest + m.left() + m.right(), super().minimumSizeHint().height())

    def resizeEvent(self, event):
        across = event.size().width() >= self._row_width()
        direction = QBoxLayout.LeftToRight if across else QBoxLayout.TopToBottom
        if self.box.direction() != direction:
            self.box.setDirection(direction)
            self.setProperty("stacked", not across)
            repolish(self)
            QTimer.singleShot(0, self.updateGeometry)
        super().resizeEvent(event)

    def eventFilter(self, watched, event):
        # The arrow keys pick the option beside the current one, as they do
        # in a row of radio buttons; Home and End the first and the last.
        if event.type() == QEvent.KeyPress and watched in self.buttons.values():
            step = {Qt.Key_Left: -1, Qt.Key_Up: -1, Qt.Key_Right: 1,
                    Qt.Key_Down: 1}.get(event.key())
            at = self.currentIndex()
            if step is not None:
                to = max(0, min(len(self.keys) - 1, at + step))
            elif event.key() == Qt.Key_Home:
                to = 0
            elif event.key() == Qt.Key_End:
                to = len(self.keys) - 1
            else:
                return False
            button = self.buttons[self.keys[to]]
            button.setFocus(Qt.TabFocusReason)
            if to != at:
                button.setChecked(True)
                self._picked(self.keys[to])
            return True
        return super().eventFilter(watched, event)

    def _picked(self, key):
        self.changed.emit(key)
        self.currentIndexChanged.emit(self.keys.index(key))

    def currentIndex(self):
        return self.keys.index(self.value())

    def setCurrentIndex(self, index):
        if 0 <= index < len(self.keys):
            self.buttons[self.keys[index]].setChecked(True)

    def value(self):
        for key, button in self.buttons.items():
            if button.isChecked():
                return key
        return next(iter(self.buttons))

    def set_value(self, key):
        button = self.buttons.get(key)
        if button is not None:
            button.setChecked(True)


class Choice(QFrame):
    """A radio card: a title, a line on what it means, and room below for
    whatever describes its state. A press anywhere on it picks it."""
    toggled = Signal(bool)

    def __init__(self, title, text, group_name=None):
        super().__init__()
        self.setProperty("class", "choice")
        self.setCursor(Qt.PointingHandCursor)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.radio = QRadioButton()
        self.radio.setText("")
        head.addWidget(self.radio, 0, Qt.AlignTop)
        head.addWidget(label(title, "title", wrap=True), 1)
        outer.addLayout(head)
        self.text = label(text, "help", wrap=True)
        outer.addWidget(self.text)
        self.extra = QVBoxLayout()
        self.extra.setSpacing(6)
        outer.addLayout(self.extra)
        self.radio.toggled.connect(self._toggled)
        self.radio.installEventFilter(self)

    def eventFilter(self, watched, event):
        # Each card's radio has a parent of its own, so Qt's arrow keys —
        # which only move between radios sharing one — need doing here:
        # through the QButtonGroup the cards were put in.
        group = self.radio.group()
        if (watched is self.radio and group is not None
                and event.type() == QEvent.KeyPress):
            step = {Qt.Key_Left: -1, Qt.Key_Up: -1, Qt.Key_Right: 1,
                    Qt.Key_Down: 1}.get(event.key())
            if step is not None:
                radios = [b for b in group.buttons() if b is self.radio
                          or (b.isEnabled() and b.isVisibleTo(self.window()))]
                to = radios[(radios.index(self.radio) + step) % len(radios)]
                to.setFocus(Qt.TabFocusReason)
                to.click()
                return True
        return super().eventFilter(watched, event)

    def _toggled(self, on):
        self.setProperty("checked", on)
        repolish(self)
        self.toggled.emit(on)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.radio.setChecked(True)
        super().mousePressEvent(event)

    def isChecked(self):
        return self.radio.isChecked()

    def setChecked(self, on):
        self.radio.setChecked(on)
        self.setProperty("checked", on)
        repolish(self)


class Picker(QComboBox):
    """A combo box. On a phone its list opens as a Sheet inside the window
    rather than as Qt's popup — see Sheet for why."""

    def __init__(self):
        super().__init__()
        if IS_ANDROID:
            # As narrow as the screen needs: the longest entry does not
            # set the width.
            self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            self.setMinimumContentsLength(8)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.sheet = None

    def showPopup(self):
        if not IS_ANDROID:
            super().showPopup()
            return
        if self.sheet is not None:
            return
        self.sheet = Sheet.choose(
            self.window(),
            [(self.itemIcon(i), self.itemText(i)) for i in range(self.count())],
            self.currentIndex(), self._picked)
        self.sheet.destroyed.connect(lambda *_: setattr(self, "sheet", None))

    def _picked(self, index):
        if index != self.currentIndex():
            self.setCurrentIndex(index)
            self.activated.emit(index)


class Sheet(QFrame):
    """A card at the bottom of the window over a dimmed rest of it — what a
    phone uses for menus, pickers and questions.

    On Android every Qt popup (a combo box's list, a QMenu, a QDialog, a
    tooltip) is a window of its own with its own GL surface, and creating
    one aborts the app on real phones ("Failed to acquire deadlock protector
    for QAndroidPlatformOpenGLWindow::eglSurface()"). A Sheet is a child of
    the window it covers, so nothing new is created. A tap on the dimmed
    part, Back or Esc closes it.
    """

    def __init__(self, host):
        super().__init__(host)
        self.on_close = None
        self.setObjectName("sheetShade")
        self.setGeometry(host.rect())
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addStretch(1)
        self.panel = QFrame()
        self.panel.setObjectName("sheet")
        outer.addWidget(self.panel)
        self.body = QVBoxLayout(self.panel)
        self.body.setContentsMargins(8, 10, 8, 10)
        self.body.setSpacing(6)
        host.installEventFilter(self)

    def present(self):
        self.show()
        self.raise_()
        self.setFocus()
        return self

    def scrolling(self, content, most=0.7):
        """`content` in a scroll area as tall as it needs, up to `most` of
        the window."""
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroller.setFrameShape(QFrame.NoFrame)
        scroller.setWidget(content)
        from .style import touch_scroll
        touch_scroll(scroller)
        want = content.sizeHint().height() + 4
        scroller.setFixedHeight(min(want, int(self.parentWidget().height() * most)))
        self.body.addWidget(scroller)
        return scroller

    @classmethod
    def choose(cls, host, entries, current, picked, title=None):
        """A list of (icon, text) to pick one of; picked(index) after."""
        sheet = cls(host)
        if title:
            sheet.body.addWidget(label(title, "strong"))
        listing = QWidget()
        items = QVBoxLayout(listing)
        items.setContentsMargins(0, 0, 0, 0)
        items.setSpacing(2)
        for i, (icon, text) in enumerate(entries):
            button = QPushButton(icon, text) if icon is not None else QPushButton(text)
            button.setProperty("class", "sheetItem")
            button.setCheckable(True)
            button.setChecked(i == current)
            button.clicked.connect(lambda _=False, i=i: sheet.close_sheet(lambda: picked(i)))
            items.addWidget(button)
        sheet.scrolling(listing)
        return sheet.present()

    def close_sheet(self, then=None):
        self.hide()
        self.parentWidget().removeEventFilter(self)
        if self.on_close is not None:
            self.on_close()
        QTimer.singleShot(0, self.deleteLater)
        if then is not None:
            QTimer.singleShot(0, then)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize:
            self.setGeometry(watched.rect())
        return False

    def mousePressEvent(self, event):
        if not self.panel.geometry().contains(event.position().toPoint()):
            self.close_sheet()          # a tap outside the card

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_Back):
            self.close_sheet()
            return
        super().keyPressEvent(event)
