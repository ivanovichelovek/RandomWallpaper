"""Setting the wallpaper on Android, through WallpaperManager.

Reached through pyjnius. The context is the application's own, from
ActivityThread rather than the activity class: pyjnius looks classes up with
the system class loader on any thread but the main one, and the app's own
classes are not there — a set from a worker thread could not even find them.
"""
from pathlib import Path

from .common import WallpaperError


def _manager():
    try:
        from jnius import autoclass
    except ImportError as exc:
        raise WallpaperError("pyjnius is missing from this build") from exc
    app = autoclass("android.app.ActivityThread").currentApplication()
    if app is None:
        raise WallpaperError("no Android context to set the wallpaper from")
    return autoclass, autoclass("android.app.WallpaperManager").getInstance(app)


def set_wallpaper(path, command=None):
    autoclass, manager = _manager()
    # A stream rather than a Bitmap: WallpaperManager decodes and scales it
    # itself, without a 4K image held whole in this process's heap.
    stream = autoclass("java.io.FileInputStream")(str(Path(path)))
    try:
        manager.setStream(stream)
    except Exception as exc:
        raise WallpaperError(f"WallpaperManager refused it: {exc}") from exc
    finally:
        stream.close()


def wallpaper_now():
    # Android gives no path back for the current wallpaper.
    return None


def wallpapers_on_outputs():
    return {}


def describe():
    return "WallpaperManager"


def pictures_dir():
    # Inside the app's own files: the gallery cannot see it, but nothing
    # here needs a storage permission either.
    import os
    return Path(os.environ.get("ANDROID_PRIVATE") or Path.home()) / "Pictures"
