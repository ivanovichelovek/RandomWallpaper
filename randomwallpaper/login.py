"""Opening the window when you sign in to Windows.

Not the rotation: that has its own scheduled task (schedule.py), which runs
at logon whether or not this is on. This is only the reel, there on the
screen after sign-in for someone who wants to start the day swiping.

A value under HKCU's Run key, the same one Task Manager's Startup tab lists:
per user, no administrator, and a person who switches it off there is
answered rather than overruled. Task Manager does not delete the value to do
that — it writes a flag beside it under Explorer\\StartupApproved — so the
flag is read too, or Settings would show "on" for an entry Windows skips.

The registry is the only record of whether it is on. A pref would disagree
with Task Manager the first time someone used it.
"""
import subprocess

from .paths import IS_WINDOWS

VALUE_NAME = "RandomWallpaper"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"


def available():
    return IS_WINDOWS


def command():
    """The Run value's data: the windowed app, quoted. The same program the
    scheduled task runs, so it is never the console twin, and a console
    never flashes up at sign-in."""
    from .schedule import _executable
    return subprocess.list2cmdline(_executable())


def approved(data):
    """Whether a StartupApproved flag lets the entry run. The first byte is
    2 when it is switched on in Task Manager and 3 when it is off; an odd
    one is off, as Explorer reads it. No flag at all is on."""
    return not data or not data[0] & 1


def _read(key_path):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            return winreg.QueryValueEx(key, VALUE_NAME)[0]
    except OSError:
        return None


def _delete(key_path):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass


def status():
    """"on", "off", or "outdated": on, but starting another copy of the app
    — one installed somewhere else, or since moved."""
    if not available():
        return "off"
    value = _read(RUN_KEY)
    if not value or not approved(_read(APPROVED_KEY)):
        return "off"
    return "on" if value == command() else "outdated"


def enable():
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
    # Switched off in Task Manager before: switching it on here is the
    # newer word, and without clearing the flag it would do nothing.
    _delete(APPROVED_KEY)


def disable():
    _delete(RUN_KEY)
    _delete(APPROVED_KEY)
