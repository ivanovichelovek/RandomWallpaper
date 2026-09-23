#!/usr/bin/env python3
"""Screenshots of every tab on whatever desktop this runs on.

    uv run tests/screenshots.py OUTPUT_DIR

Not a test: a way to *see* the app on a system nobody here sits in front of.
.github/workflows/screenshots.yml runs it on the Windows and macOS runners,
with each platform's own Qt plugin (not offscreen), so fonts, scaling and the
native window frame are the real ones.

For each tab, at the default size and at a small one, it saves the window as
Qt draws it (win-*.png) and the whole screen around it (screen-*.png) — the
second is where the title bar and the desktop show, and it can come out
blank where the OS withholds screen capture.

A few real frames are downloaded and one is pinned, so the reel and the
Downloaded tab show content rather than their empty states. $HOME and the
XDG dirs point at a scratch directory; on Windows and macOS the app's own
config lives under the runner's profile, which is thrown away anyway.
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "screenshots").resolve()
OUT.mkdir(parents=True, exist_ok=True)

scratch = Path(tempfile.mkdtemp(prefix="rw-shots-"))
os.environ["RANDOM_WALLPAPER_DIR"] = str(scratch / "random_wallpaper")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from randomwallpaper import core  # noqa: E402
from randomwallpaper.ui import style  # noqa: E402
from randomwallpaper.ui.window import Reel  # noqa: E402

# Keep the desktop's own wallpaper alone: this is for looking, not setting.
core.set_wallpaper = lambda path: None


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def seed_library():
    """Three kept wallpapers, one pinned to autumn and one to halloween."""
    prefs = dict(core.load_prefs(), theme="autumn", source="konachan")
    kept = []
    for _ in range(3):
        try:
            frame = core.download(prefs)
        except Exception as exc:          # network on a runner: best effort
            print(f"download failed: {exc}")
            continue
        core.SAVE_DIR.mkdir(parents=True, exist_ok=True)
        dest = core.unique_path(core.SAVE_DIR, frame["name"], frame["ext"])
        shutil.move(str(frame["path"]), dest)
        kept.append(dest)
    for path, theme in zip(kept, ("autumn", "halloween")):
        pool = core.theme_pool(theme)
        pool.mkdir(parents=True, exist_ok=True)
        os.link(path, pool / path.name)
    print(f"seeded {len(kept)} wallpapers")


def main():
    seed_library()
    app = QApplication(sys.argv[:1])
    style.apply(app)
    prefs = core.load_prefs()
    prefs["theme"] = "autumn"
    win = Reel(app, prefs)
    win.move(40, 40)
    win.show()
    win.raise_()
    win.activateWindow()
    print(f"platform: {app.platformName()}, "
          f"screen: {app.primaryScreen().size().toTuple()} "
          f"@ {app.primaryScreen().devicePixelRatio()}x")

    # Give the reel time to download its first frames.
    pump(app, 25)

    for size_name, size in (("default", None), ("small", (700, 600))):
        if size:
            win.resize(*size)
        for index, tab in enumerate(("random", "downloaded", "settings")):
            win.show_tab(index)
            pump(app, 3)
            win.grab().save(str(OUT / f"win-{size_name}-{tab}.png"))
            app.primaryScreen().grabWindow(0).save(
                str(OUT / f"screen-{size_name}-{tab}.png"))
            print(f"saved {size_name}/{tab}")

    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
