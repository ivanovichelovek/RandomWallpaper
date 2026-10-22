#!/usr/bin/env bash
# The macOS disk image: Random Wallpaper.app next to a link to
# /Applications, to drag it onto.
#
#   uv sync --extra build --extra macos     # PyObjC, or every tick asks
#   uv run packaging/make_icons.py          # the Automation permission
#   iconutil -c icns packaging/macos/icon.iconset -o packaging/macos/icon.icns
#   uv run pyinstaller packaging/pyinstaller.spec
#   packaging/macos/build-dmg.sh            # → dist/installer/*.dmg
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

PY=${PYTHON:-python3}
VERSION=$("$PY" -c 'import randomwallpaper; print(randomwallpaper.__version__)')
APP="dist/Random Wallpaper.app"
[ -d "$APP" ] || { echo "no $APP — run pyinstaller first" >&2; exit 1; }
NAME=$("$PY" -c "from randomwallpaper.update import asset_name
print(asset_name('$VERSION', kind='macos', machine='$(uname -m)'))")

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/image"
ditto "$APP" "$work/image/Random Wallpaper.app"
ln -s /Applications "$work/image/Applications"
cp LICENSE "$work/image/LICENSE"

mkdir -p dist/installer
rm -f "dist/installer/$NAME"
hdiutil create -volname "Random Wallpaper $VERSION" \
    -srcfolder "$work/image" -fs HFS+ -format UDZO -ov \
    "dist/installer/$NAME"
ls -l "dist/installer/$NAME"
