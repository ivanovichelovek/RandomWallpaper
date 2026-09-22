"""Setting and reading the wallpaper on macOS.

Two routes, and the order is about permissions rather than taste.

PyObjC talks to NSWorkspace inside this process: it needs no entitlement, it
covers every attached screen, and reading the current wallpaper back through
it asks nobody for anything. AppleScript is the fallback for an install
without PyObjC, and it is a fallback rather than the primary because driving
System Events needs an Automation grant the user has to approve in System
Settings — a dialog the rotation, which runs from a timer with nobody
watching, cannot answer.
"""
from pathlib import Path

from .common import WallpaperError, run, run_template


def _workspace():
    """NSWorkspace and NSScreen, or None when PyObjC is not installed."""
    try:
        from AppKit import NSScreen, NSWorkspace
        from Foundation import NSURL
    except ImportError:
        return None
    return NSWorkspace, NSScreen, NSURL


def _set_native(path):
    parts = _workspace()
    if parts is None:
        return False
    NSWorkspace, NSScreen, NSURL = parts
    url = NSURL.fileURLWithPath_(str(Path(path).resolve()))
    workspace = NSWorkspace.sharedWorkspace()
    screens = list(NSScreen.screens() or [])
    if not screens:
        raise WallpaperError("no screen to set a wallpaper on")
    errors = []
    for screen in screens:
        ok, error = workspace.setDesktopImageURL_forScreen_options_error_(
            url, screen, {}, None)
        if not ok:
            errors.append(str(error))
    if errors:
        raise WallpaperError("; ".join(errors))
    return True


def _set_applescript(path):
    # POSIX file, not a plain string: a path with a space in it is otherwise
    # read as an HFS path and silently does nothing.
    script = (
        'tell application "System Events" to tell every desktop '
        f'to set picture to POSIX file "{Path(path).resolve()}"'
    )
    run(["osascript", "-e", script], timeout=20)


def set_wallpaper(path, command=None):
    if command:
        run_template(command, path)
        return
    try:
        if _set_native(path):
            return
    except WallpaperError:
        raise
    except Exception as exc:                # a PyObjC bridge failure
        raise WallpaperError(f"NSWorkspace: {exc}") from exc
    _set_applescript(path)


def wallpaper_now():
    """The wallpaper on screen, or None when nothing can say.

    None is "do not know" and never "none is set" — a machine without PyObjC
    and without the Automation grant answers None forever, and that has to
    read as the rotation having nothing to compare against rather than as the
    user having chosen a wallpaper by hand.
    """
    parts = _workspace()
    if parts is not None:
        NSWorkspace, NSScreen, _NSURL = parts
        try:
            screens = list(NSScreen.screens() or [])
            if screens:
                url = NSWorkspace.sharedWorkspace().desktopImageURLForScreen_(screens[0])
                if url is not None and url.path():
                    return Path(str(url.path()))
        except Exception:
            pass
    try:
        out = run(["osascript", "-e",
                   'tell application "System Events" to get POSIX path of '
                   '(get picture of current desktop)'],
                  timeout=20, check=False).stdout.strip()
    except OSError:
        return None
    return Path(out) if out else None


def describe():
    return "NSWorkspace" if _workspace() else "AppleScript (System Events)"


def pictures_dir():
    return Path.home() / "Pictures"
