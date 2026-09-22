# Random Wallpaper

A reel of random wallpapers: keep the ones you want, drop the rest.

One frame is on screen at a time. **Save** keeps it and (optionally) puts it
on the desktop; **Delete** throws it away. Neither closes the window — the
reel just advances, with the next frame already prefetched so the wait is
invisible. A **Downloaded** tab lists everything you have kept, lets you set
one as the wallpaper directly, and lets you *pin* wallpapers to a season or a
holiday. A **Settings** tab holds the filters and an optional calendar
rotation that changes the wallpaper on its own — the season when it begins, a
holiday for the week around it, back to the season once that week is over.

This is a standalone, cross-platform rewrite of a single-file Linux/GTK tool.
It runs unmodified on **Linux, macOS, and Windows** — same reel, same
calendar logic, same file layout — with only the one part that has to differ
by platform (how the desktop wallpaper actually gets set) written three
times, once per OS.

## Install

Requires Python 3.9+.

```bash
git clone https://github.com/ivanovichelovek/RandomWallpaper.git
cd RandomWallpaper
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install .
```

This installs two commands:

* `random-wallpaper` — a console entry point. `--auto`, `--period` and the
  other non-windowed modes print to stdout; also opens the window with no
  arguments.
* `random-wallpaper-gui` — the same program, built as a **windowed** entry
  point (on Windows, this is the one that does not flash a console).

Launch the window with either one:

```bash
random-wallpaper
```

### Linux desktop integration

```bash
packaging/linux/install.sh
```

installs a `.desktop` file and icon so the app shows up in your application
launcher, with quick actions for "From Konachan", "From Wallhaven" and
"Browse what the calendar calls for now".

### Standalone binaries

`pip install .[build]` then `pyinstaller packaging/pyinstaller.spec` builds a
single-file/app-bundle binary for whichever platform you run it on (see
`packaging/pyinstaller.spec`).

## The calendar rotation

`random-wallpaper --auto` is one tick: it sets the wallpaper the calendar
calls for right now, if it has not already, then exits. It is meant to run
from a scheduler, and the app can install one for you:

```bash
random-wallpaper --install-timer      # Linux: a systemd --user timer
                                       # macOS: a LaunchAgent
                                       # Windows: a Task Scheduler task
random-wallpaper --uninstall-timer    # remove it again
```

The rotation is careful about one thing above all: **a wallpaper you set by
hand — from this app or from anywhere else — is never overwritten.** The next
tick notices the desktop no longer shows what the rotation last put there,
and switches itself off rather than taking your choice away. Turn it back on
from Settings, or with `random-wallpaper --auto-on`; `--auto-toggle` is the
one to bind to a key.

Useful flags:

```
--period            print today's period and exit
--theme now         open the window pre-filtered to today's season/holiday
--auto --force      apply even if already applied / rotation is off
--backend           print which platform backend will be used to set the wallpaper
```

## Where things live

* `~/random_wallpaper/` — what you have kept (`Save`), on every platform.
  Fixed on purpose: a keybind, a terminal run and a file manager should all
  agree on where your wallpapers are, regardless of each OS's own
  Pictures/Documents convention. Override with `RANDOM_WALLPAPER_DIR`.
* `~/random_wallpaper/<season-or-holiday>/` — wallpapers *pinned* to a
  category from the Downloaded tab. What is in here wins over a download when
  that category's turn comes around; several pinned wallpapers take turns, a
  fresh one drawn each midnight.
* Cache, config and rotation state live in each platform's normal place
  (`platformdirs`: XDG dirs on Linux, `~/Library/...` on macOS,
  `%LOCALAPPDATA%` on Windows).

## Sources

[Konachan](https://konachan.net) (anime art, safe-rated only) and
[Wallhaven](https://wallhaven.cc) (general/anime/people, your choice). A
Wallhaven API key is optional — it only lifts Wallhaven's own rate limit —
and is read from `WALLHAVEN_API_KEY` first, the Settings field second.

## Setting the wallpaper, per platform

* **Linux**: probes for a compositor/DE integration in this order —
  [Noctalia](https://github.com/noctalia-dev/noctalia-shell), swww,
  hyprpaper, GNOME/Cinnamon/MATE (via `gsettings`), KDE Plasma
  (`plasma-apply-wallpaperimage`), XFCE (`xfconf-query`), then the X11-only
  `feh` / `xwallpaper` / `nitrogen`. None found? Set
  `RANDOM_WALLPAPER_SET_COMMAND="your-command {path}"` in the environment.
* **macOS**: `NSWorkspace` via PyObjC when `pip install .[macos]` is used
  (no permission prompt); falls back to AppleScript/System Events otherwise
  (needs an Automation grant, requested the first time it runs).
* **Windows**: `SystemParametersInfoW`, the same API every version of
  Windows since 95 answers.

> **Tested on Linux.** The macOS and Windows backends are written against
> each platform's documented API and exercised by the automated test suite
> wherever that logic is pure Python, but this rewrite was done on Linux —
> the macOS/Windows code paths themselves have not been run on those
> platforms. If something does not work there, please open an issue.

## Development

```bash
pip install -e .
python tests/test_core.py     # the calendar/file-handling suite (needs network
                               # for two live download checks; everything else
                               # runs offline)
```

`randomwallpaper/core.py` holds everything platform-independent — themes, the
calendar, preferences, the two sources, the rotation. `randomwallpaper/
desktop/` is the one place that knows which OS it's on. `randomwallpaper/ui/`
is the PySide6 (Qt) interface.

## Credits

A cross-platform rewrite of a Linux/GTK tool originally built for a niri +
Noctalia desktop, where it replaced a shell script that downloaded straight
over a single wallpaper file, no way to keep one you liked without racing to
copy it out by hand.
