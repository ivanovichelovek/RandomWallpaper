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


def _load_jni_shim():
    """Make pyjnius loadable: its jnius.so wants WebView_AndroidGetJNIEnv,
    which the Qt bootstrap does not provide. libjnienv.so (jnienv.c) does,
    and loaded RTLD_GLOBAL it is there when jnius.so is resolved."""
    import ctypes
    shim = Path(__file__).resolve().with_name("libjnienv.so")
    try:
        ctypes.CDLL(str(shim), mode=ctypes.RTLD_GLOBAL)
    except OSError as exc:
        print(f"jni shim: {exc}", flush=True)


_load_jni_shim()


def _paint_system_bars(_tokens=None):
    """Paint the status and navigation bars the window's own colour, with
    dark icons on a light window and light ones on a dark.

    Qt leaves the bars as the system theme has them, white under a dark
    window. Window colours belong to Android's UI thread, so the change goes
    there as a Runnable. This runs on Qt's main thread, which Java started,
    so pyjnius can see the app's own classes from here. Registered with the
    theme, it follows every tint and appearance change; and it runs again
    whenever the app comes back to the front, since a recreated activity's
    window starts with the default bars.
    """
    try:
        from jnius import PythonJavaClass, autoclass, java_method
    except Exception as exc:
        print(f"system bars: no pyjnius: {exc!r}", flush=True)
        return
    from randomwallpaper.ui import style
    argb = 0xFF000000 | int(style.token("bg").lstrip("#"), 16)
    color = argb - (1 << 32)
    light = not style.theme.dark()

    class Paint(PythonJavaClass):
        __javainterfaces__ = ["java/lang/Runnable"]
        __javacontext__ = "app"

        @java_method("()V")
        def run(self):
            try:
                window = activity.getWindow()
                window.setStatusBarColor(color)
                window.setNavigationBarColor(color)
                # Under a transparent bar what shows is the decor view's
                # own background, which the light default theme left white.
                window.getDecorView().setBackgroundColor(color)
                if hasattr(window, "setNavigationBarContrastEnforced"):
                    window.setNavigationBarContrastEnforced(False)
                # Dark icons on a light bar (API 30+): the status bar's clock
                # and the navigation handle would be white on white.
                controller = window.getInsetsController()
                if controller is not None:
                    flags = 8 | 16      # APPEARANCE_LIGHT_STATUS_BARS | _NAVIGATION_BARS
                    controller.setSystemBarsAppearance(flags if light else 0, flags)
                print(f"system bars: painted {'light' if light else 'dark'}", flush=True)
            except Exception as exc:
                print(f"system bars: {exc}", flush=True)

    try:
        activity = autoclass("dev.ivanc.randomwallpaper.WallpaperActivity").mActivity
        _paint_system_bars.paint = Paint()       # kept alive until it has run
        activity.runOnUiThread(_paint_system_bars.paint)
    except Exception as exc:
        print(f"system bars: {exc}", flush=True)


def _follow_system_bars(app):
    from PySide6.QtCore import Qt
    from randomwallpaper.ui import style
    style.theme.listeners.append(_paint_system_bars)
    app.applicationStateChanged.connect(
        lambda state: _paint_system_bars() if state == Qt.ApplicationActive else None)
    _paint_system_bars()


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
    """A few kept wallpapers, so the Saved tab is not empty."""
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
        ("saved", lambda: win.show_tab(1)),
        # One tile picked: the actions enabled, the selection drawn.
        ("saved-picked", lambda: win.library.list.setCurrentRow(0)),
        # Put that one up through WallpaperManager, and say how it went.
        ("set-wallpaper", lambda: set_picked()),
        ("settings-top", settings_to(0)),
        ("settings-middle", settings_to(0.5)),
        ("settings-bottom", settings_to(1)),
        # The same in the other appearance.
        ("other-random", lambda: (flip(), win.show_tab(0))),
        ("other-saved", lambda: win.show_tab(1)),
        ("other-settings", settings_to(0)),
        # The in-app update's last step, on the build itself: Android's
        # "update this app?" screen should be on top for the screenshot.
        ("update-installer", lambda: try_installer()),
    ]

    def try_installer():
        from randomwallpaper.desktop import android
        apk = PRIVATE / "update-test.apk"
        if not apk.exists():
            print("rw-tour: installer NOT tried: no update-test.apk", flush=True)
            return
        try:
            android.install_apk(apk)
            print("rw-tour: installer started", flush=True)
        except Exception as exc:
            print(f"rw-tour: installer NOT started: {exc!r}", flush=True)

    def set_picked():
        chosen = win.library.selected() or [p for p, _ in win.library.entries]
        if not chosen:
            print("rw-tour: wallpaper NOT set: nothing saved", flush=True)
            return
        try:
            if not win.library.selected():
                win.library.list.setCurrentRow(0)
            win.library.set_as_wallpaper()
            print(f"rw-tour: wallpaper set {chosen[0].name}", flush=True)
        except Exception as exc:
            print(f"rw-tour: wallpaper NOT set: {exc!r}", flush=True)

    def flip():
        from randomwallpaper.ui import style
        dark = style.theme.dark()
        win.prefs["appearance"] = "light" if dark else "dark"
        style.theme.apply(force=True)

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

    def shown(win):
        from PySide6.QtCore import QTimer
        _follow_system_bars(win.app)
        # Again once Qt has finished setting its window up, which may
        # repaint the bars after the first call.
        QTimer.singleShot(1500, _paint_system_bars)
        if touring:
            tour(win)
    return run_app(prefs, None, on_shown=shown)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        # stderr does not reach logcat; stdout does.
        import traceback
        print("rw-crash:\n" + traceback.format_exc(), flush=True)
        raise
