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
    core.wallpapers_on_outputs = lambda: {}

    from PySide6.QtWidgets import QApplication

    from randomwallpaper.ui import style
    from randomwallpaper.ui.window import Reel

    app = QApplication.instance() or QApplication([])
    style.apply(app)
    prefs = core.load_prefs()

    win = Reel(app, prefs)
    check("window constructs", win is not None)

    tabs = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    check("three tabs present", tabs == ["Random", "Downloaded", "Settings"])

    for i in range(win.tabs.count()):
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
