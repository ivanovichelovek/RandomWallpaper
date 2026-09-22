"""Where this app keeps things, on each of the three systems.

Everything here is decided at import time, so a test — or a portable install —
can point HOME and the XDG variables somewhere else and have the whole app
follow, exactly as the single-file Linux version did.

One directory is deliberately *not* platform-idiomatic: SAVE_DIR. What you
keep lives in ~/random_wallpaper on every system, one known place, so a
keybind, a terminal run and a file manager always agree on where your
wallpapers are. The machine-managed directories — cache, config, state — do
follow each platform's convention, because nobody opens those by hand.
"""
import os
import sys
from pathlib import Path

APP_NAME = "random-wallpaper"
APP_ID = "dev.ivanc.RandomWallpaper"

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
IS_LINUX = not IS_WINDOWS and not IS_MACOS


def _dirs():
    """cache, config and state, from platformdirs when it is installed.

    The fallback is not a nicety: it keeps the core importable — and the test
    suite runnable — on a bare interpreter with nothing pip-installed, which
    is how the calendar logic gets exercised in CI before any wheel exists.
    """
    try:
        import platformdirs
    except ImportError:
        home = Path.home()
        if IS_WINDOWS:
            base = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
            return (base / APP_NAME / "Cache",
                    base / APP_NAME / "Config",
                    base / APP_NAME / "State")
        if IS_MACOS:
            return (home / "Library" / "Caches" / APP_NAME,
                    home / "Library" / "Application Support" / APP_NAME,
                    home / "Library" / "Application Support" / APP_NAME / "state")
        xdg = lambda var, default: Path(os.environ.get(var) or home / default)
        return (xdg("XDG_CACHE_HOME", ".cache") / APP_NAME,
                xdg("XDG_CONFIG_HOME", ".config") / APP_NAME,
                xdg("XDG_STATE_HOME", ".local/state") / APP_NAME)

    return (Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False)),
            Path(platformdirs.user_config_dir(APP_NAME, appauthor=False)),
            Path(platformdirs.user_state_dir(APP_NAME, appauthor=False)))


CACHE_DIR, CONFIG_DIR, STATE_DIR = _dirs()

# An escape hatch for a machine where the home directory is not the right
# place — a network home, a Windows profile on a small system drive.
SAVE_DIR = Path(os.environ.get("RANDOM_WALLPAPER_DIR")
                or Path.home() / "random_wallpaper")

# API answers, kept apart from the pending downloads so pruning one cannot
# touch the other.
API_CACHE_DIR = CACHE_DIR / "api"
CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_FILE = STATE_DIR / "auto.json"
AUTO_DIR = STATE_DIR / "wallpapers"
