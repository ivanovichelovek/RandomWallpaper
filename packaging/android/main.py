"""The Android entry point: pyside6-android-deploy wants a main.py.

The window only — there is no command line on a phone. The rest of what
cli.main() does before opening it (prefs, the cache, pruning) happens here
the same way.
"""
import os
import sys
from pathlib import Path

# Nothing sets HOME for an app's process, and Path.home() falls back to a
# password-database entry Android does not have.
os.environ.setdefault("HOME", os.environ.get("ANDROID_PRIVATE", "/data/local/tmp"))



def _trust_android_cas():
    """Point Python's TLS at certificates it can find.

    The OpenSSL python-for-android builds looks for a CA bundle in a path
    that does not exist on a phone, so every HTTPS request failed its
    certificate check. Android keeps its own CAs as hashed PEM files — the
    layout OpenSSL's capath reads — and certifi is the fallback.
    """
    import ssl
    system = "/system/etc/security/cacerts"
    cafile = None
    try:
        import certifi
        cafile = certifi.where()
    except ImportError:
        pass

    def context(*args, **kwargs):
        ctx = ssl.create_default_context(*args, **kwargs)
        if os.path.isdir(system):
            ctx.load_verify_locations(capath=system)
        if cafile:
            ctx.load_verify_locations(cafile=cafile)
        return ctx

    ssl._create_default_https_context = context


_trust_android_cas()

from randomwallpaper import core  # noqa: E402
from randomwallpaper.paths import CACHE_DIR  # noqa: E402


# ── the screenshot tour ─────────────────────────────────────────────────────
# .github/workflows/android.yml drops this file into the app's directory with
# `run-as` before starting it; the app then walks its own tabs, saving each
# as Qt drew it, while the workflow takes the phone's screen alongside.
PRIVATE = Path(os.environ.get("ANDROID_PRIVATE") or Path.home())
TOUR_MARKER = PRIVATE / "tour"
SHOTS = PRIVATE / "shots"


def seed_library():
    """A few kept wallpapers, so the Downloaded tab is not empty."""
    import shutil
    prefs = dict(core.load_prefs(), theme="autumn", source="konachan")
    for _ in range(3):
        try:
            frame = core.download(prefs)
        except Exception as exc:
            print(f"rw-tour: download failed: {exc}", flush=True)
            continue
        core.SAVE_DIR.mkdir(parents=True, exist_ok=True)
        dest = core.unique_path(core.SAVE_DIR, frame["name"], frame["ext"])
        shutil.move(str(frame["path"]), dest)


def tour(win):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QScrollArea
    SHOTS.mkdir(parents=True, exist_ok=True)

    def settings_to(fraction):
        def go():
            win.show_tab(2)
            area = win.settings.findChild(QScrollArea)
            bar = area.verticalScrollBar()
            bar.setValue(int(bar.maximum() * fraction))
        return go

    steps = [
        ("random", lambda: win.show_tab(0)),
        ("downloaded", lambda: win.show_tab(1)),
        ("settings-top", settings_to(0)),
        ("settings-middle", settings_to(0.5)),
        ("settings-bottom", settings_to(1)),
    ]

    def step(i):
        if i == len(steps):
            (SHOTS / "done").write_text("")
            print("rw-tour: done", flush=True)
            return
        name, show = steps[i]
        show()

        def grab():
            win.grab().save(str(SHOTS / f"{name}.png"))
            print(f"rw-tour: {name}", flush=True)
            QTimer.singleShot(6000, lambda: step(i + 1))
        QTimer.singleShot(3000, grab)

    # Time for the reel to fetch its first frames.
    QTimer.singleShot(25000, lambda: step(0))


def main():
    prefs = core.load_prefs()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    core.prune_cache()
    touring = TOUR_MARKER.exists()
    if touring:
        seed_library()
    from randomwallpaper.ui.app import run_app
    return run_app(prefs, None, on_shown=tour if touring else None)


if __name__ == "__main__":
    sys.exit(main())
