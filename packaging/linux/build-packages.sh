#!/usr/bin/env bash
# Build the three Linux packages from a PyInstaller onedir build.
#
#   uv run pyinstaller packaging/pyinstaller.spec
#   packaging/linux/build-packages.sh            # → dist/packages/
#
# Needs nfpm on PATH (https://nfpm.goreleaser.com). Each package is named by
# randomwallpaper.update.asset_name(), the same function the in-app updater
# uses to find it in a release — so the names cannot drift apart.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

PY=${PYTHON:-python3}
export VERSION=$("$PY" -c 'import randomwallpaper; print(randomwallpaper.__version__)')
[ -x dist/random-wallpaper/random-wallpaper ] || {
    echo "no dist/random-wallpaper — run pyinstaller first" >&2; exit 1; }
[ -f packaging/linux/icons/48x48.png ] || "$PY" packaging/make_icons.py

# A fixed path: nfpm reads its file list from nfpm.yaml, which does not
# expand variables in `src`.
STAGE=build/package-stage
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -a dist/random-wallpaper "$STAGE/"
# The launcher entry for a packaged install: the /usr/bin link, not the
# source install's random-wallpaper-gui entry point.
sed -e 's|^Exec=random-wallpaper-gui|Exec=/usr/bin/random-wallpaper|' \
    -e 's|^Exec=random-wallpaper |Exec=/usr/bin/random-wallpaper |' \
    packaging/linux/dev.ivanc.RandomWallpaper.desktop > "$STAGE/dev.ivanc.RandomWallpaper.desktop"

out=dist/packages
mkdir -p "$out"
for fmt in archlinux deb rpm; do
    case $fmt in archlinux) key=pacman ;; *) key=$fmt ;; esac
    name=$("$PY" -c "from randomwallpaper.update import asset_name
print(asset_name('$VERSION', kind='linux', machine='x86_64', fmt='$key'))")
    nfpm package --config packaging/linux/nfpm.yaml --packager "$fmt" \
        --target "$out/$name"
done
ls -l "$out"
