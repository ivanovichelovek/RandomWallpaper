#!/bin/bash
# Install the .pkg with macOS's Installer, check that the app landed in
# /Applications and works — including the timer — then take it back out.
#
#   check_macos.sh <version> <path to .pkg>
#
# Needs sudo without a password, as GitHub's macOS runners have. Failures
# are also GitHub ::error:: annotations.
set -u
VERSION=$1 PKG=$2
APP="/Applications/Random Wallpaper.app"
BIN="$APP/Contents/MacOS/random-wallpaper"
LABEL=dev.ivanc.RandomWallpaper.auto
failures=0

fail() { echo "::error::$1"; echo "FAIL  $1"; failures=$((failures + 1)); }
pass() { echo "PASS  $1"; }
check() { local label=$1; shift; if "$@" >/dev/null 2>&1; then pass "$label"; else fail "$label"; fi; }

echo "== install $PKG"
if ! sudo installer -pkg "$PKG" -target /; then fail "Installer refused the package"; exit 1; fi

# In /Applications, not "upgraded" in place wherever the build left a copy
# of the same bundle id — what a relocatable component would do.
check "the app is in /Applications" test -x "$BIN"
plist_version=$(plutil -extract CFBundleShortVersionString raw "$APP/Contents/Info.plist" 2>/dev/null)
[ "$plist_version" = "$VERSION" ] && pass "Info.plist says $VERSION" \
    || fail "Info.plist says '$plist_version', wanted $VERSION"
check "Installer recorded the package" sh -c "pkgutil --pkg-info dev.ivanc.RandomWallpaper | grep -q 'version: $VERSION'"

out=$("$BIN" --version 2>&1)
[ "$out" = "random-wallpaper $VERSION (macOS app)" ] && pass "--version: $out" \
    || fail "--version said: $out (wanted $VERSION, macOS app)"
check "--period runs" "$BIN" --period
backend=$("$BIN" --backend 2>&1)
# PyObjC in the bundle: without it every minute tick goes through System
# Events and asks for the Automation permission from a background agent.
[ "$backend" = "NSWorkspace" ] && pass "sets the wallpaper through NSWorkspace" \
    || fail "wallpaper backend is '$backend' — PyObjC is missing from the bundle"

# The window, for real: the runner has a GUI session.
"$BIN" >/tmp/window.log 2>&1 &
pid=$!
sleep 8
if kill -0 "$pid" 2>/dev/null; then
    pass "the window starts and stays up"
    kill "$pid"; wait "$pid" 2>/dev/null
else
    wait "$pid"; fail "the window exited with $?: $(tail -n 3 /tmp/window.log | tr '\n' ' ')"
fi

echo "== timer"
if "$BIN" --install-timer; then
    agent=~/Library/LaunchAgents/$LABEL.plist
    check "the LaunchAgent is written" test -f "$agent"
    check "it runs the installed app" sh -c "plutil -extract ProgramArguments.0 raw '$agent' | grep -qx '$BIN'"
    check "launchd has loaded it" launchctl print "gui/$(id -u)/$LABEL"
    "$BIN" --uninstall-timer
    check "--uninstall-timer takes it out again" sh -c "[ ! -e '$agent' ]"
else
    fail "--install-timer failed"
fi

echo "== remove"
sudo rm -rf "$APP" && sudo pkgutil --forget dev.ivanc.RandomWallpaper >/dev/null
echo "== $failures failed"
[ "$failures" -eq 0 ]
