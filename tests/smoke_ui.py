#!/usr/bin/env python3
"""Construct the main window with no real network or desktop calls, on
whichever platform this runs on.

This is what `tests/test_core.py` cannot cover: it never imports
`randomwallpaper.ui`, so a platform-specific import error (an AppKit bridge
missing on macOS, a ctypes call that only resolves on Windows) or a Qt
widget-construction bug would otherwise go unnoticed until someone actually
opened the window on that OS. Run under Qt's `offscreen` platform plugin, so
it needs no display — that plugin ships with Qt on Linux, macOS and Windows
alike, which is what makes this runnable in CI on all three.

Network and the real desktop are both stubbed: `core.download` never reaches
Konachan/Wallhaven, and `core.set_wallpaper` / `wallpaper_now` never touch
whatever desktop this happens to run on — a CI runner's session is not one to
experiment on, and neither is a developer's.
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FAKE = Path(tempfile.mkdtemp(prefix="random-wallpaper-smoke-"))
(FAKE / "Pictures").mkdir(parents=True, exist_ok=True)
os.environ["HOME"] = str(FAKE)
os.environ["USERPROFILE"] = str(FAKE)
os.environ["XDG_CACHE_HOME"] = str(FAKE / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(FAKE / ".config")
os.environ["XDG_STATE_HOME"] = str(FAKE / ".local" / "state")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ok = fail = 0


def check(label, cond):
    global ok, fail
    print(("PASS  " if cond else "FAIL  ") + label)
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)


def main():
    from randomwallpaper import core

    # Never let a frame's prefetch reach the network in CI, or on a
    # developer's machine that just happens to run this by hand.
    core.download = lambda prefs: (_ for _ in ()).throw(
        core.FetchError("smoke test: network disabled"))
    core.set_wallpaper = lambda path: None
    core.wallpaper_now = lambda: None
    core.wallpapers_on_outputs = lambda: {"eDP-1": Path("/x.jpg"), "DP-1": Path("/y.jpg")}
    core.set_wallpaper_on = lambda output, path: None
    core.can_set_per_output = lambda: True

    from PySide6.QtWidgets import QApplication

    from randomwallpaper.ui import style
    from randomwallpaper.ui.window import Reel

    app = QApplication.instance() or QApplication([])
    prefs = core.load_prefs()
    style.apply(app, prefs)

    win = Reel(app, prefs)
    check("window constructs", win is not None)

    from randomwallpaper.ui.window import SECTIONS
    check("three sections present", SECTIONS == ["Random", "Saved", "Settings"]
          and win.pages.count() == 3)

    for i in range(win.pages.count()):
        win.show_tab(i)
        app.processEvents()
    check("every tab can be shown without raising", True)

    win.show()
    app.processEvents()
    check("window shows without raising", True)

    # Workers hand their results back with post_to_ui; it has to land on the
    # UI thread, or every widget it touches is touched from the wrong one.
    import threading
    import time
    hit = []
    threading.Thread(target=lambda: win.post_to_ui(
        lambda: hit.append(threading.current_thread() is threading.main_thread())
    )).start()
    deadline = time.time() + 2
    while not hit and time.time() < deadline:
        app.processEvents()
    check("post_to_ui runs on the UI thread", hit == [True])

    # Each screen its own: Set as wallpaper becomes a choice of screen.
    win.settings.fill_outputs()
    check("the main-screen choice lists the monitors",
          [win.settings.main_output.itemData(i)
           for i in range(win.settings.main_output.count())] == ["", "eDP-1", "DP-1"])
    win.settings.screens_buttons["separate"].setChecked(True)
    app.processEvents()
    check("the choice is saved", core.load_prefs()["screens"] == "separate")
    win.show_tab(1)
    win.library.sync()
    check("Set as wallpaper asks which screen",
          win.library.set_btn.menu() is win.library.screen_menu)
    win.library.refresh_screen_menu()
    check("one entry per screen, and every screen",
          [a.text() for a in win.library.screen_menu.actions() if a.text()][-1]
          == "Every screen")

    # ── the keyboard ─────────────────────────────────────────────────────
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtTest import QTest

    def key(k, mods=Qt.NoModifier):
        QTest.keyClick(app.focusWidget() or win, k, mods)
        app.processEvents()

    core.SAVE_DIR.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        image = QImage(64, 36, QImage.Format_RGB32)
        image.fill(QColor(40 * i, 90, 140))
        image.save(str(core.SAVE_DIR / f"tile-{i}.png"))
    win.show_tab(1)
    app.processEvents()
    tiles = win.library.list
    tiles.setFocus(Qt.TabFocusReason)
    tiles.setCurrentRow(0)
    key(Qt.Key_Right)
    check("Right moves to the next saved tile", tiles.currentRow() == 1)
    check("the Random tab's keys are off on another tab",
          not any(sc.isEnabled() for sc, groups in win._shortcuts if "reel" in groups))

    tiles.clearSelection()
    tiles.item(2).setSelected(True)
    win.library.pin("halloween")
    win.library.reload()
    show = win.library.show_only
    show.setCurrentIndex(show.findData("halloween"))
    app.processEvents()
    check("the Saved tab can show just what is pinned to one holiday",
          [tiles.item(i).isHidden() for i in range(tiles.count())] == [True, True, False])
    show.setCurrentIndex(0)

    win.show_tab(2)
    app.processEvents()
    seg = win.settings.appearance
    before = seg.value()
    seg.buttons[before].setFocus(Qt.TabFocusReason)
    key(Qt.Key_Right if before != "light" else Qt.Key_Left)
    check("an arrow key picks the next option of a segmented control",
          seg.value() != before and core.load_prefs()["appearance"] == seg.value())
    seg.set_value(before)

    spin = win.settings.every
    spin.show()
    spin.setFocus(Qt.TabFocusReason)
    spin.selectAll()
    key(Qt.Key_1)
    check("a digit typed in the spin box stays there", win.current_tab() == 2)

    radios = win.settings.screens_group.buttons()
    first = next(r for r in radios if r.isChecked())
    first.setFocus(Qt.TabFocusReason)
    key(Qt.Key_Down)
    check("an arrow key moves between the choice cards", not first.isChecked())
    first.click()

    hits = []
    button = win.settings.change_now
    button.clicked.connect(lambda *_: hits.append(1))
    button.setFocus(Qt.TabFocusReason)
    key(Qt.Key_Return)
    QTest.qWait(300)
    check("Enter presses the focused button", hits == [1])
    check("and the focus ring shows where it is", button.property("kbfocus") is True)

    QTest.keyClick(win, Qt.Key_F, Qt.ControlModifier)
    app.processEvents()
    check("Ctrl+F goes to the Saved search",
          win.current_tab() == 1 and app.focusWidget() is win.library.search)
    key(Qt.Key_Escape)
    check("Esc leaves the search box, not the app",
          win.isVisible() and app.focusWidget() is tiles)

    win.close()
    check("window closes without raising", True)

    from randomwallpaper import desktop
    check("desktop backend resolves to something nameable",
          isinstance(desktop.describe_backend(), str))

    import shutil
    shutil.rmtree(FAKE, ignore_errors=True)

    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
