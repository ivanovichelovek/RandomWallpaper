"""Setting and reading the wallpaper on Windows.

One call does both directions: SystemParametersInfoW with action 20
(SPI_SETDESKWALLPAPER) or 0x73 (SPI_GETDESKWALLPAPER) is the same API every
Windows version back to 95 answers, so there is no probe here the way there is
on Linux — just the one call, checked for the BOOL it is documented to return
rather than trusted to have worked.

SPI_SETDESKWALLPAPER only accepts BMP on old versions and otherwise whatever
codec Windows' own image decoder understands (JPEG and PNG both work since
XP), applied with SPIF_UPDATEINIFILE | SPIF_SENDCHANGE so it survives a
restart and repaints every monitor at once.
"""
import ctypes
from pathlib import Path

from .common import WallpaperError, run_template

SPI_SETDESKWALLPAPER = 0x0014
SPI_GETDESKWALLPAPER = 0x0073
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02

# use_last_error=True is what makes ctypes.get_last_error() actually reflect
# this call. Without it, SetLastError's value is whatever the last *unrelated*
# Win32 call in the process happened to leave behind — usually 0, "the
# operation completed successfully" — and a genuine failure to set the
# wallpaper would surface to the user as exactly that string.
_user32 = ctypes.WinDLL("user32", use_last_error=True) if hasattr(ctypes, "WinDLL") else None


def set_wallpaper(path, command=None):
    if command:
        run_template(command, path)
        return
    resolved = str(Path(path).resolve())
    ok = _user32.SystemParametersInfoW(
        SPI_SETDESKWALLPAPER, 0, resolved, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE,
    )
    # The call returns a BOOL; a 0 means it refused (an unreadable path, or an
    # image format the shell's decoder does not accept) and must not be read
    # as success — the rotation records a period only when this really worked.
    if not ok:
        raise WallpaperError(
            ctypes.WinError(ctypes.get_last_error()).strerror
            or "SystemParametersInfoW refused the wallpaper"
        )


def wallpaper_now():
    """The wallpaper on screen, or None when it cannot be read back.

    The buffer SystemParametersInfoW fills is MAX_PATH, which is what every
    Windows API in this family promises and no more; a wallpaper style that
    tiles or spans monitors does not change what this call reports, since
    Windows still tracks one source image underneath it.

    One exception, and it matters: Windows commonly answers with a re-encoded
    copy under `...\\Microsoft\\Windows\\Themes\\TranscodedWallpaper` rather
    than the path that was actually set — not a different wallpaper chosen by
    a person, just Windows' own cache. Read literally, that path would never
    `samefile()` the one the rotation recorded, and the very next tick would
    read it as a hand-set wallpaper and switch the rotation off for good, one
    tick after it first worked. None is the right answer here, the same as
    for any other "cannot really say" case.
    """
    buf = ctypes.create_unicode_buffer(260)
    ok = _user32.SystemParametersInfoW(SPI_GETDESKWALLPAPER, len(buf), buf, 0)
    if not ok or not buf.value:
        return None
    path = Path(buf.value)
    if "microsoft\\windows\\themes" in str(path).lower():
        return None
    return path



def wallpapers_on_outputs():
    """Per-output wallpapers are not read here: {} is "cannot tell apart"."""
    return {}


def describe():
    return "SystemParametersInfoW"


def pictures_dir():
    # SHGetKnownFolderPath would follow a redirected Pictures library; this is
    # the value that folder redirection almost always still resolves to, and
    # it needs no extra dependency.
    import os
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Pictures"
