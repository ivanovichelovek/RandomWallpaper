#!/usr/bin/env bash
# The macOS installer package: Random Wallpaper.app into /Applications, in
# macOS's own Installer.
#
#   uv sync --extra build --extra macos     # PyObjC, or every tick asks
#   uv run packaging/make_icons.py          # the Automation permission
#   iconutil -c icns packaging/macos/icon.iconset -o packaging/macos/icon.icns
#   uv run pyinstaller packaging/pyinstaller.spec
#   packaging/macos/build-pkg.sh            # → dist/installer/*.pkg
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
mkdir -p "$work/root"
ditto "$APP" "$work/root/Random Wallpaper.app"

# Not relocatable. By default Installer looks for any copy of the same
# bundle id already on the disk — a build folder, a download — and
# "upgrades" that copy where it lies instead of writing /Applications.
pkgbuild --analyze --root "$work/root" "$work/component.plist"
plutil -replace 0.BundleIsRelocatable -bool NO "$work/component.plist"

pkgbuild --root "$work/root" \
    --component-plist "$work/component.plist" \
    --install-location /Applications \
    --scripts packaging/macos/scripts \
    --identifier dev.ivanc.RandomWallpaper \
    --version "$VERSION" \
    "$work/component.pkg"

# A product archive around it: a titled Installer window with the licence,
# and the minimum macOS the build runs on.
cat > "$work/distribution.xml" <<XML
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
    <title>Random Wallpaper $VERSION</title>
    <license file="LICENSE"/>
    <options customize="never" require-scripts="false" hostArchitectures="$(uname -m)"/>
    <volume-check><allowed-os-versions><os-version min="13.0"/></allowed-os-versions></volume-check>
    <choices-outline><line choice="default"><line choice="app"/></line></choices-outline>
    <choice id="default"/>
    <choice id="app" visible="false"><pkg-ref id="dev.ivanc.RandomWallpaper"/></choice>
    <pkg-ref id="dev.ivanc.RandomWallpaper" version="$VERSION" onConclusion="none">component.pkg</pkg-ref>
</installer-gui-script>
XML
mkdir -p "$work/resources"
cp LICENSE "$work/resources/LICENSE"

mkdir -p dist/installer
productbuild --distribution "$work/distribution.xml" \
    --resources "$work/resources" \
    --package-path "$work" \
    "dist/installer/$NAME"
ls -l "dist/installer/$NAME"
