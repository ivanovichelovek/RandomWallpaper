"""The one place the rest of the app asks "what platform is this", so nothing
else has to.

Every function here has the same contract on all three systems:
`set_wallpaper` raises WallpaperError on anything that did not really work,
and `wallpaper_now` returns None for "cannot tell" rather than guessing — the
calendar rotation depends on both of those being true, since it records a
period only when the apply provably succeeded and never latches itself off on
a answer it cannot trust.
"""
import sys

from .common import WallpaperError, custom_command, trash  # noqa: F401

if sys.platform.startswith("win"):
    from . import windows as _backend
elif sys.platform == "darwin":
    from . import macos as _backend
else:
    from . import linux as _backend


def set_wallpaper(path, command=None):
    _backend.set_wallpaper(path, command=custom_command(command))


def can_set_per_output():
    check = getattr(_backend, "can_set_per_output", None)
    return bool(check and check(command=custom_command(None)))


def set_wallpaper_on(output, path):
    """One output only. Raises WallpaperError where the platform has no such
    thing — check can_set_per_output first."""
    setter = getattr(_backend, "set_wallpaper_on", None)
    if setter is None:
        raise WallpaperError("this desktop cannot set a wallpaper per monitor")
    setter(output, path, command=custom_command(None))


def wallpaper_now():
    return _backend.wallpaper_now()


def wallpapers_on_outputs():
    return _backend.wallpapers_on_outputs()


def pictures_dir():
    return _backend.pictures_dir()


def describe_backend():
    return _backend.describe()
