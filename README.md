# Random Wallpaper

A reel of random wallpapers from Konachan and Wallhaven: **Save** keeps one
(and optionally sets it), **Delete** drops it, the next one is already
prefetched. Kept wallpapers can be pinned to a season or holiday, and an
optional calendar rotation changes the wallpaper on its own. Linux, macOS,
Windows.

## Install

From the [latest release](https://github.com/ivanovichelovek/RandomWallpaper/releases/latest):

| System | File | Install |
|---|---|---|
| Windows 10/11 | `RandomWallpaper-<version>-windows-x64-setup.exe` | run it (per-user, no admin) |
| macOS 13+ (Apple silicon) | `RandomWallpaper-<version>-macos-arm64.dmg` | open it, drag the app to Applications |
| Arch Linux | `random-wallpaper-<version>-1-x86_64.pkg.tar.zst` | `sudo pacman -U random-wallpaper-*.pkg.tar.zst` |
| Debian / Ubuntu | `random-wallpaper_<version>_amd64.deb` | `sudo apt install ./random-wallpaper_*.deb` |
| Fedora / openSUSE | `random-wallpaper-<version>-1.x86_64.rpm` | `sudo dnf install ./random-wallpaper-*.rpm` |

Builds are unsigned: on Windows click **More info → Run anyway**; on macOS
**System Settings → Privacy & Security → Open Anyway**.

**Updating:** the app checks for a new release when it opens and offers to
install it (Settings → App → Check for updates at startup turns that off);
or Settings → App → Check for updates, or `random-wallpaper --update`. Downloads are verified against `SHA256SUMS`.

### From source

```bash
git clone https://github.com/ivanovichelovek/RandomWallpaper.git
cd RandomWallpaper
uv sync
uv run random-wallpaper
```

`packaging/linux/install.sh` adds the launcher entry and icon on Linux.

## Calendar rotation

Enable **Change the wallpaper by itself** in Settings, or:

```bash
random-wallpaper --install-timer
random-wallpaper --uninstall-timer
```

This installs a per-minute timer (systemd user timer / LaunchAgent / Task
Scheduler) running `random-wallpaper --auto --quiet`. A new season or holiday
changes the wallpaper immediately; within one, the **Change** setting picks
*at midnight*, *every N minutes/hours* (min. 15 min) or *at set times*.
Pinned wallpapers take turns; with nothing pinned, a fresh one is downloaded.

**Shuffle my picks** (Settings → Rotation) ignores the calendar: mark
wallpapers with **★ Shuffle** on the Downloaded tab, and a random one of them
goes up every hour (or as set in **Change**).

**Screens** (Settings) — with several monitors: *Same on every screen*
gives a monitor you plug in the main screen's wallpaper (rotation on or off);
*Each screen its own* draws a different one per monitor, and **Set as
wallpaper** asks which screen. Per-screen wallpapers need Noctalia.

Setting a wallpaper by hand turns the rotation off. Turn it back on in
Settings or with `--auto-on`; `--auto-toggle` is handy for a keybind.

```
--period            print today's period
--theme now         open filtered to today's season/holiday
--auto --force      apply even if already applied / rotation is off
--backend           print the wallpaper backend in use
--version           print version and install type
```

## Files

* `~/random_wallpaper/` — saved wallpapers (override with `RANDOM_WALLPAPER_DIR`)
* `~/random_wallpaper/<season-or-holiday>/` — pinned wallpapers
* `~/random_wallpaper/shuffle/` — the ★ shuffle set
* Cache, config and state — platform defaults via `platformdirs`

A Wallhaven API key is optional; it is read from `WALLHAVEN_API_KEY`, then
from Settings.

## Wallpaper backends

* **Linux**: Noctalia, swww, hyprpaper, GNOME/Cinnamon/MATE, KDE Plasma,
  XFCE, then `feh` / `xwallpaper` / `nitrogen`. Otherwise set
  `RANDOM_WALLPAPER_SET_COMMAND="your-command {path}"`.
* **macOS**: `NSWorkspace` (with `--extra macos`), else AppleScript.
* **Windows**: `SystemParametersInfoW`.

Developed on Linux; if something breaks on macOS or Windows, please open an
issue.

## Development

```bash
uv sync --extra macos --extra build
uv run tests/test_core.py
uv run tests/smoke_ui.py
uv run tests/check_scheduler.py   # macOS/Windows
```

Release: bump `__version__` in `randomwallpaper/__init__.py` and `version` in
`pyproject.toml`, then `git tag vX.Y.Z && git push origin vX.Y.Z` —
`.github/workflows/release.yml` builds, tests and publishes the installers.
