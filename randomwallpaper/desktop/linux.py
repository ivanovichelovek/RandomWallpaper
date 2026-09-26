"""Setting and reading the wallpaper on Linux and the other free desktops.

There is no such thing as "the Linux way" to set a wallpaper: a Wayland
compositor has its own daemon, GNOME has a GSettings key, KDE has a helper
binary, XFCE has one property per monitor, and X11 has half a dozen small
programs. So this is a probe rather than a call — the backends that could work
on this session, in the order that is most likely to be the one the user
actually runs, each tried until one succeeds.

The probe is also the answer to the original app being wired to a single
shell (`noctalia msg wallpaper-set`): that stays first, because it is still
the right answer on the desktop this came from, but it is no longer the only
one.
"""
import os
import re
from pathlib import Path

from .common import WallpaperError, have, run, run_template

CONFIG_KEY_HINT = "wallpaper_command"


def _session():
    return (os.environ.get("XDG_CURRENT_DESKTOP", "")
            + ":" + os.environ.get("XDG_SESSION_DESKTOP", "")
            + ":" + os.environ.get("DESKTOP_SESSION", "")).lower()


def _uri(path):
    return Path(path).resolve().as_uri()


# ── individual backends ─────────────────────────────────────────────────────
# Each is (name, available(), set(path), get() -> Path | None). `get` may be
# None where the desktop has no way to answer; a backend that cannot be read
# is still perfectly good at being written to.
def _noctalia_set(path):
    run(["noctalia", "msg", "wallpaper-set", str(path)])


def _noctalia_get():
    out = run(["noctalia", "msg", "wallpaper-get"], check=False).stdout.strip()
    return Path(out) if out else None


def _swww_set(path):
    run(["swww", "img", str(path)])


def _swww_get():
    out = run(["swww", "query"], check=False).stdout
    match = re.search(r"image:\s*(\S.*)$", out, re.MULTILINE)
    return Path(match.group(1).strip()) if match else None


def _hyprpaper_set(path):
    run(["hyprctl", "hyprpaper", "preload", str(path)])
    # The empty monitor name means "every monitor", which is what a single
    # wallpaper choice means here.
    run(["hyprctl", "hyprpaper", "wallpaper", f",{path}"])


def _gsettings_set(path):
    uri = _uri(path)
    schema = "org.gnome.desktop.background"
    run(["gsettings", "set", schema, "picture-uri", uri])
    # picture-uri-dark as well, or the wallpaper changes only in the light
    # theme and GNOME in its default dark mode looks like nothing happened.
    run(["gsettings", "set", schema, "picture-uri-dark", uri], check=False)
    run(["gsettings", "set", schema, "picture-options", "zoom"], check=False)


def _gsettings_get():
    out = run(["gsettings", "get", "org.gnome.desktop.background", "picture-uri"],
              check=False).stdout.strip().strip("'\"")
    if out.startswith("file://"):
        from urllib.parse import unquote, urlparse
        return Path(unquote(urlparse(out).path))
    return None


def _cinnamon_set(path):
    run(["gsettings", "set", "org.cinnamon.desktop.background",
         "picture-uri", _uri(path)])


def _mate_set(path):
    run(["gsettings", "set", "org.mate.background", "picture-filename", str(path)])


def _plasma_set(path):
    run(["plasma-apply-wallpaperimage", str(path)], timeout=30)


def _xfce_props():
    out = run(["xfconf-query", "-c", "xfce4-desktop", "-l"], check=False).stdout
    return [line.strip() for line in out.splitlines()
            if line.strip().endswith("last-image")]


def _xfce_set(path):
    props = _xfce_props()
    if not props:
        raise WallpaperError("xfce4-desktop has no last-image property to set")
    for prop in props:
        run(["xfconf-query", "-c", "xfce4-desktop", "-p", prop,
             "-s", str(path)], check=False)


def _xfce_get():
    props = _xfce_props()
    if not props:
        return None
    out = run(["xfconf-query", "-c", "xfce4-desktop", "-p", props[0]],
              check=False).stdout.strip()
    return Path(out) if out else None


def _feh_set(path):
    run(["feh", "--no-fehbg", "--bg-fill", str(path)])


def _xwallpaper_set(path):
    run(["xwallpaper", "--zoom", str(path)])


def _nitrogen_set(path):
    run(["nitrogen", "--set-zoom-fill", "--save", str(path)])


def _wayland():
    return bool(os.environ.get("WAYLAND_DISPLAY"))


def _x11():
    return bool(os.environ.get("DISPLAY"))


BACKENDS = [
    # name            available()                                       set            get
    ("noctalia",      lambda: have("noctalia"),                         _noctalia_set, _noctalia_get),
    ("swww",          lambda: have("swww") and _wayland(),              _swww_set,     _swww_get),
    ("hyprpaper",     lambda: have("hyprctl")
                              and bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")),
                                                                        _hyprpaper_set, None),
    ("gnome",         lambda: have("gsettings")
                              and any(d in _session() for d in
                                      ("gnome", "unity", "pantheon", "budgie")),
                                                                        _gsettings_set, _gsettings_get),
    ("cinnamon",      lambda: have("gsettings") and "cinnamon" in _session(),
                                                                        _cinnamon_set, None),
    ("mate",          lambda: have("gsettings") and "mate" in _session(),
                                                                        _mate_set,     None),
    ("plasma",        lambda: have("plasma-apply-wallpaperimage"),      _plasma_set,   None),
    ("xfce",          lambda: have("xfconf-query") and "xfce" in _session(),
                                                                        _xfce_set,     _xfce_get),
    # The X11 programs last: they work under any window manager, which also
    # means they will happily "succeed" on a desktop that ignores them.
    ("feh",           lambda: have("feh") and _x11(),                   _feh_set,      None),
    ("xwallpaper",    lambda: have("xwallpaper") and _x11(),            _xwallpaper_set, None),
    ("nitrogen",      lambda: have("nitrogen") and _x11(),              _nitrogen_set, None),
    # No session check: gsettings with a GNOME schema is still the right
    # answer on a bare window manager running GNOME's components.
    ("gsettings",     lambda: have("gsettings"),                        _gsettings_set, _gsettings_get),
]


def available():
    """The backends this session could use, best first."""
    found = []
    for name, is_available, setter, getter in BACKENDS:
        try:
            if is_available():
                found.append((name, setter, getter))
        except OSError:
            continue
    return found


def describe():
    names = [name for name, _, _ in available()]
    return ", ".join(names) if names else "none found"


def set_wallpaper(path, command=None):
    if command:
        run_template(command, path)
        return
    failures = []
    for name, setter, _ in available():
        try:
            setter(path)
            return
        except WallpaperError as exc:
            failures.append(f"{name}: {exc}")
    if not failures:
        raise WallpaperError(
            "no way to set the wallpaper was found on this session — install "
            "one of swww, hyprpaper, feh, xwallpaper, nitrogen, or set "
            f"{CONFIG_KEY_HINT} in the config to your own command"
        )
    raise WallpaperError("; ".join(failures))


def wallpaper_now():
    """The wallpaper on screen, or None when nothing here can say.

    None means "do not know", never "none is set": every caller treats it as a
    reason to do nothing, which is what keeps a compositor that cannot be
    queried from looking exactly like the user choosing a wallpaper by hand.

    Only the first backend is asked — the one set_wallpaper writes to. When it
    has no answer, falling through to the next one is asking a desktop that
    is not drawing the wallpaper: right after a resume from sleep, or at login
    before the shell is up, Noctalia does not answer yet, and gsettings still
    holds GNOME's default Adwaita picture. That read as a wallpaper set by
    hand and switched the rotation off.
    """
    found = available()
    if not found:
        return None
    _, _, getter = found[0]
    if getter is None:
        return None
    try:
        return getter() or None
    except OSError:
        return None


def pictures_dir():
    try:
        out = run(["xdg-user-dir", "PICTURES"], timeout=5, check=False).stdout.strip()
    except OSError:
        out = ""
    return Path(out) if out else Path.home() / "Pictures"
