#!/usr/bin/env bash
# Install the package for the current user and register the desktop entry.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

python3 -m pip install --user -e .

share="${XDG_DATA_HOME:-$HOME/.local/share}"
mkdir -p "$share/applications" "$share/icons/hicolor/scalable/apps"
install -m644 packaging/linux/dev.ivanc.RandomWallpaper.desktop "$share/applications/"
install -m644 randomwallpaper/resources/icon.svg \
    "$share/icons/hicolor/scalable/apps/dev.ivanc.RandomWallpaper.svg"

command -v update-desktop-database >/dev/null && update-desktop-database "$share/applications" || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache "$share/icons/hicolor" || true

echo "Installed. Run 'random-wallpaper' or 'random-wallpaper --install-timer' for the calendar rotation."
