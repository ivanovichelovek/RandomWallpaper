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

Download the installer for your system from the
[latest release](https://github.com/ivanovichelovek/RandomWallpaper/releases/latest):

| System | File | What it does |
|---|---|---|
| Windows 10/11 | `RandomWallpaper-<version>-windows-x64-setup.exe` | Installs for your user, no administrator needed, into `%LOCALAPPDATA%\Programs\Random Wallpaper`, with a Start-menu entry and an uninstaller under *Apps* |
| macOS 13+ (Apple silicon) | `RandomWallpaper-<version>-macos-arm64.pkg` | Opens in macOS's Installer and puts *Random Wallpaper* in /Applications |
| Arch Linux | `random-wallpaper-<version>-1-x86_64.pkg.tar.zst` | `sudo pacman -U random-wallpaper-*.pkg.tar.zst` |
| Debian / Ubuntu | `random-wallpaper_<version>_amd64.deb` | `sudo apt install ./random-wallpaper_*.deb` |
| Fedora / openSUSE | `random-wallpaper-<version>-1.x86_64.rpm` | `sudo dnf install ./random-wallpaper-*.rpm` (or `zypper install`) |

The Linux packages put the app in `/opt/random-wallpaper`, the command at
`/usr/bin/random-wallpaper`, and the launcher entry and icons where the
desktop finds them; remove them with the same package manager.

The builds are not code-signed. The first time, Windows SmartScreen says
*Windows protected your PC* — **More info → Run anyway**; macOS says the
package is from an unidentified developer — open **System Settings → Privacy
& Security** and click **Open Anyway**. Neither asks again for that version.

### Updating

**Settings → App → Check for updates** looks at the latest GitHub release,
and **Update to x.y.z** installs it the way the platform installs anything,
then brings the app back as the new version:

* **Windows** runs the new installer silently over the old one;
* **macOS** opens the new package in Installer, which asks for your password;
* **Linux** hands the new package to the package manager that installed the
  current one (pacman, apt or dnf/zypper) through `pkexec`, which asks for
  your password. With no polkit agent running, the download is kept and the
  `sudo …` command to finish it is shown instead.

Every download is checked against the release's `SHA256SUMS` before anything
is replaced. `random-wallpaper --update` does the same from a terminal, and
`random-wallpaper --version` says which version and kind of install is
running.

### From source

Uses [uv](https://docs.astral.sh/uv/) — it resolves against the committed
`uv.lock`, so every install gets the exact versions this was tested against,
and manages its own Python download if `requires-python` (3.9+) isn't already
on the machine.

```bash
git clone https://github.com/ivanovichelovek/RandomWallpaper.git
cd RandomWallpaper
uv sync
uv run random-wallpaper
```

This installs two commands into `.venv/`: `random-wallpaper`, a console
entry point, and `random-wallpaper-gui`, a windowed one (on Windows, the one
that does not flash a console). `packaging/linux/install.sh` adds the
launcher entry and icon for a source install on Linux. A source install does
not update itself — `git pull`, or `uv tool upgrade randomwallpaper`.

### Building the installers

`.github/workflows/release.yml` builds all of them, installs each on its own
runner and starts it, then publishes them with `SHA256SUMS` as a GitHub
release:

```bash
# bump __version__ in randomwallpaper/__init__.py and version in pyproject.toml
git tag v1.2.0 && git push origin v1.2.0
```

The tag must match `__version__`, or the workflow stops before publishing.
Actions → *release* → *Run workflow* builds and tests them without
publishing anything. By hand, per platform:

```bash
uv sync --extra build                      # macOS: also --extra macos
uv run packaging/make_icons.py
uv run pyinstaller packaging/pyinstaller.spec
packaging/linux/build-packages.sh          # needs nfpm      → dist/packages/
iscc /DAppVersion=1.2.0 packaging\windows\installer.iss   # → dist/installer/
packaging/macos/build-pkg.sh               # after iconutil  → dist/installer/
```

Only an Apple-silicon macOS package is built; an Intel one would need an
Intel macOS runner.

## The calendar rotation

`random-wallpaper --auto` is one tick: it sets the wallpaper the calendar
calls for right now, if it has not already, then exits. It is meant to run
from a scheduler, and the app installs one for you. Ticking **Change the
wallpaper by itself** in Settings does it (so does the **Schedule it** button
that shows up there when no timer is found), or from a terminal:

```bash
random-wallpaper --install-timer
random-wallpaper --uninstall-timer    # remove it again
```

### How often

A new season or holiday always changes the wallpaper straight away. How often
it changes *inside* one is the **Change** setting under the checkbox:

* **At midnight** (the default) — a new wallpaper each midnight, drawn from
  what is pinned to the season or holiday. With nothing pinned, one download
  stays up for the whole period.
* **Every…** N minutes or hours (15 minutes at the least), counted from
  midnight — every 90 minutes is 00:00, 01:30, 03:00…
* **At set times** — a list like `07:00, 13:30, 19:00`.

In the last two, several pinned wallpapers take turns; one pinned wallpaper
stays up; with nothing pinned, **every change is a fresh download**. A failed
download is not retried for 10 minutes.

### The timer

It is the same timer on every platform: `random-wallpaper --auto --quiet` at
login and then every minute, which is what lets any of the settings above
land on time without the timer ever being rewritten. A tick with nothing to
do takes about a tenth of a second and, with `--quiet`, prints nothing. A tick
missed while the machine was asleep or off runs as soon as it is back.

| | scheduler | triggers |
|---|---|---|
| Linux | systemd `--user` timer | 1 min after startup, `minutely` with `AccuracySec=1s`, `Persistent=true` |
| macOS | LaunchAgent (`~/Library/LaunchAgents/dev.ivanc.RandomWallpaper.auto.plist`) | at login, every 60 s, 00:00 (launchd runs a midnight missed in sleep on wake); log in `~/Library/Logs/random-wallpaper-auto.log` |
| Windows | Task Scheduler task `RandomWallpaperAuto` | at logon, on unlock, daily from 00:00 repeating every minute, runs a missed start as soon as possible, on battery too; no console window |

An hourly timer from an older version is recognised, and Settings offers to
**Update it**. A timer that is a symlink — managed from a dotfiles repository,
say — is never rewritten by the Settings tab; if the Change setting needs more
than it does, Settings says so. `--install-timer` always rewrites it.

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
* **macOS**: `NSWorkspace` via PyObjC when installed with the `macos` extra
  (`uv sync --extra macos`; it's marker-gated so it only actually installs
  there) — no permission prompt; falls back to AppleScript/System Events
  otherwise (needs an Automation grant, requested the first time it runs).
* **Windows**: `SystemParametersInfoW`, the same API every version of
  Windows since 95 answers.

> **Tested on Linux.** The macOS and Windows backends are written against
> each platform's documented API and exercised by the automated test suite
> wherever that logic is pure Python, but this rewrite was done on Linux —
> the macOS/Windows code paths themselves have not been run on those
> platforms. If something does not work there, please open an issue.

## Development

```bash
uv sync --extra macos --extra build   # everything, including the optional extras
uv run tests/test_core.py     # the calendar/file-handling suite (needs network
                               # for two live download checks; everything else
                               # runs offline)
uv run tests/smoke_ui.py      # headless Qt window construction, all three tabs
uv run tests/check_scheduler.py  # macOS/Windows: the OS scheduler accepts the timer
```

`.github/workflows/test.yml` runs both on `ubuntu-latest`, `macos-latest` and
`windows-latest` on every push, using the same `uv sync --locked` — that's the
real cross-platform check, since development itself happens on Linux alone.

`randomwallpaper/core.py` holds everything platform-independent — themes, the
calendar, preferences, the two sources, the rotation. `randomwallpaper/
desktop/` is the one place that knows which OS it's on. `randomwallpaper/ui/`
is the PySide6 (Qt) interface.

## Credits

A cross-platform rewrite of a Linux/GTK tool originally built for a niri +
Noctalia desktop, where it replaced a shell script that downloaded straight
over a single wallpaper file, no way to keep one you liked without racing to
copy it out by hand.
