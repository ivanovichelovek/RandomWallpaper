"""Small building blocks the pages share: cards, labels by role, a segmented
control and a radio card. Each only sets an objectName or a "class"
property; what that looks like is in style.py.
"""
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QRadioButton,
    QVBoxLayout, QWidget,
)


def repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def label(text="", cls=None, wrap=False):
    w = QLabel(text)
    if cls:
        w.setProperty("class", cls)
    w.setWordWrap(wrap)
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
    column.addWidget(label(title, "strong"))
    helper = None
    if help_text is not None:
        helper = label(help_text, "help", wrap=True)
        column.addWidget(helper)
    return box, helper


def row(left, right, stretch_left=True):
    """A setting row: what it is on the left, its control on the right."""
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    layout.addWidget(left, 1 if stretch_left else 0)
    layout.addWidget(right, 0, Qt.AlignVCenter)
    return box


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
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
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
