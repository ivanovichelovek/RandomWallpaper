"""Pieces every backend needs, and the one error type they all raise."""
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")

# A subclass of OSError on purpose: the rotation and both buttons already
# catch OSError around setting a wallpaper, and a failure to set one is a
# failure of the same kind however the platform reports it. What must never
# happen is a backend that fails quietly — run_auto records the period only
# when the apply succeeded, so a silent no-op would skip a season for a year.
class WallpaperError(OSError):
    """The wallpaper was not set, and here is what the platform said."""


def have(program):
    return shutil.which(program) is not None


def run(argv, timeout=15, check=True):
    """A subprocess with no console window on Windows and no inherited stdio.

    CREATE_NO_WINDOW matters for the GUI entry point: without it every probe
    of a helper program flashes a console over the window.
    """
    kwargs = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = 0x08000000      # CREATE_NO_WINDOW
    try:
        done = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, **kwargs)
    except (OSError, subprocess.SubprocessError) as exc:
        raise WallpaperError(f"{argv[0]}: {exc}") from exc
    if check and done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip().splitlines()
        raise WallpaperError(
            f"{argv[0]} exited {done.returncode}"
            + (f": {detail[-1]}" if detail else "")
        )
    return done


def run_template(command, path):
    """A user's own command, from prefs or RANDOM_WALLPAPER_SET_COMMAND.

    `{path}` is where the file goes; a command without it gets the file
    appended, so both `swww img {path}` and `swww img` behave.
    """
    argv = shlex.split(command, posix=not IS_WINDOWS)
    if not argv:
        raise WallpaperError("empty wallpaper command")
    filled = [arg.replace("{path}", str(path)) for arg in argv]
    if not any("{path}" in arg for arg in argv):
        filled.append(str(path))
    run(filled)


def custom_command(command=None):
    """The command to use instead of any detected backend, if there is one."""
    return (command or os.environ.get("RANDOM_WALLPAPER_SET_COMMAND", "")).strip()


def fallback_trash(path):
    try:
        Path(path).unlink()
        return True
    except OSError:
        return False


def trash(path):
    """Move a file to the platform's trash, falling back to unlinking it.

    Deleting wallpapers is the one irreversible thing this app does, and it
    had no business being irreversible: a mis-click in a grid is cheap to make
    and was impossible to undo. Send2Trash speaks Gio/XDG on Linux, Finder's
    trash on macOS and the Recycle Bin on Windows, so "it goes to the trash"
    is true everywhere rather than on the desktop it was written for.
    """
    try:
        from send2trash import send2trash
    except ImportError:
        return fallback_trash(path)
    try:
        send2trash(str(path))
        return True
    except Exception:
        # No trash on this filesystem, or it is full. Removing the file is
        # still what was asked for.
        return fallback_trash(path)
