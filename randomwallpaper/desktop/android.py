"""Setting the wallpaper on Android, through WallpaperManager.

Reached through libjnienv.so's plain JNI when the app has it, else pyjnius. The context is the application's own, from
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


def _shim():
    """libjnienv.so beside main.py (packaging/android/jnienv.c): sets the
    wallpaper with plain JNI, no pyjnius needed."""
    import ctypes
    import os
    root = os.environ.get("ANDROID_ARGUMENT") or os.environ.get("ANDROID_APP_PATH") or ""
    try:
        lib = ctypes.CDLL(str(Path(root) / "libjnienv.so"))
    except OSError:
        return None
    for fn in (lib.rw_set_wallpaper, lib.rw_install_apk):
        fn.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t)
        fn.restype = ctypes.c_int
    lib.rw_schedule_auto.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_size_t)
    lib.rw_schedule_auto.restype = ctypes.c_int
    lib.rw_auto_scheduled.argtypes = (ctypes.c_char_p, ctypes.c_size_t)
    lib.rw_auto_scheduled.restype = ctypes.c_int
    try:
        lib.rw_auto_done.argtypes = (ctypes.c_char_p, ctypes.c_size_t)
        lib.rw_auto_done.restype = ctypes.c_int
        lib.rw_autostart.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_size_t)
        lib.rw_autostart.restype = ctypes.c_int
    except AttributeError:
        pass        # a libjnienv.so from before it had them
    return lib


def schedule_auto(on):
    """The rotation's JobScheduler job (AutoJob.java), on or off. True if it
    is scheduled now."""
    import ctypes
    shim = _shim()
    if shim is None:
        raise OSError("this build cannot schedule the rotation")
    error = ctypes.create_string_buffer(512)
    result = shim.rw_schedule_auto(1 if on else 0, error, len(error))
    if result < 0:
        raise OSError(error.value.decode(errors="replace"))
    return bool(result)


def auto_scheduled():
    import ctypes
    shim = _shim()
    if shim is None:
        return False
    error = ctypes.create_string_buffer(512)
    return shim.rw_auto_scheduled(error, len(error)) == 1


def auto_done():
    """End the rotation's job: AutoJob.done() tells JobScheduler the run is
    over and ends this process. Returns only if it could not be reached."""
    import ctypes
    shim = _shim()
    if shim is None or not hasattr(shim, "rw_auto_done"):
        raise OSError("this build cannot end the rotation's job")
    error = ctypes.create_string_buffer(512)
    shim.rw_auto_done(error, len(error))
    raise OSError(error.value.decode(errors="replace") or "AutoJob.done() returned")


def autostart():
    """Xiaomi's Autostart switch for this app (Autostart.java): True or
    False, or None where there is no such switch or it cannot be read.

    Off, the system will not start the rotation's job with the app closed.
    """
    import ctypes
    shim = _shim()
    if shim is None or not hasattr(shim, "rw_autostart"):
        return None
    error = ctypes.create_string_buffer(512)
    return {1: True, 0: False}.get(shim.rw_autostart(0, error, len(error)))


def open_autostart():
    """Open the screen with that switch. True if one opened."""
    import ctypes
    shim = _shim()
    if shim is None or not hasattr(shim, "rw_autostart"):
        return False
    error = ctypes.create_string_buffer(512)
    return shim.rw_autostart(1, error, len(error)) == 1


def install_apk(path):
    """Hand a downloaded .apk to Android's installer (Installer.java), which
    asks the user to confirm. Raises WallpaperError's parent, OSError, if it
    could not even be handed over."""
    import ctypes
    shim = _shim()
    if shim is None:
        raise OSError("this build cannot install updates itself")
    error = ctypes.create_string_buffer(512)
    if shim.rw_install_apk(str(Path(path)).encode(), error, len(error)) != 0:
        raise OSError(error.value.decode(errors="replace") or "the installer refused it")


def set_wallpaper(path, command=None):
    shim = _shim()
    if shim is not None:
        import ctypes
        error = ctypes.create_string_buffer(512)
        if shim.rw_set_wallpaper(str(Path(path)).encode(), error, len(error)) != 0:
            raise WallpaperError(f"WallpaperManager refused it: "
                                 f"{error.value.decode(errors='replace')}")
        return
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
