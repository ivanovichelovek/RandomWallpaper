#!/bin/sh
# Install a Linux package the way a user would, check that everything landed
# where it should and runs, then remove it and check nothing is left.
#
#   check_linux.sh <version> "<install command>" "<remove command>"
#
# Run as root in a clean container (release.yml does, per distribution).
# Each failure is also printed as a GitHub ::error:: annotation, so the
# reason shows up on the run summary — and through the public API — without
# anyone having to open the log.
set -u
VERSION=$1 INSTALL=$2 REMOVE=$3
APP=/opt/random-wallpaper
failures=0

fail() { echo "::error::$1"; echo "FAIL  $1"; failures=$((failures + 1)); }
pass() { echo "PASS  $1"; }
check() { label=$1; shift; if "$@" >/dev/null 2>&1; then pass "$label"; else fail "$label"; fi; }

echo "== install: $INSTALL"
if ! sh -c "$INSTALL"; then fail "package manager refused the package: $INSTALL"; exit 1; fi

check "the app is in $APP" test -x "$APP/random-wallpaper"
check "/usr/bin/random-wallpaper points at it" \
    sh -c "[ \"\$(readlink -f /usr/bin/random-wallpaper)\" = \"$APP/random-wallpaper\" ]"
check "the launcher entry is installed" test -f /usr/share/applications/dev.ivanc.RandomWallpaper.desktop
check "the launcher entry runs the packaged command" \
    grep -q '^Exec=/usr/bin/random-wallpaper$' /usr/share/applications/dev.ivanc.RandomWallpaper.desktop
check "the scalable icon is installed" test -f /usr/share/icons/hicolor/scalable/apps/dev.ivanc.RandomWallpaper.svg
check "the licence is installed" test -f /usr/share/licenses/random-wallpaper/LICENSE

out=$(random-wallpaper --version 2>&1)
if [ "$out" = "random-wallpaper $VERSION (Linux package)" ]; then
    pass "--version: $out"
else
    fail "--version said: $out (wanted $VERSION, Linux package)"
fi
check "--period runs" random-wallpaper --period

# Every Qt plugin that decides whether a window can open at all must find
# its system libraries; the package's depends are what provide them.
cd "$APP/_internal/PySide6/Qt/plugins" || exit 1
missing=$(for f in platforms/*.so wayland-*/*.so xcbglintegrations/*.so; do
    [ -f "$f" ] || continue
    LD_LIBRARY_PATH="$APP/_internal:$APP/_internal/PySide6/Qt/lib" ldd "$f" \
        | sed -n "s|^\s*\(\S*\) => not found|$f needs \1|p"
done | sort -u)
if [ -z "$missing" ]; then
    pass "every platform plugin resolves its libraries"
else
    echo "$missing" | while read -r line; do fail "unresolved: $line"; done
    failures=$((failures + 1))
fi
cd /

# The window itself, headless: still running after 8 s means it started.
rc=0
QT_QPA_PLATFORM=offscreen timeout 8 random-wallpaper >/tmp/window.log 2>&1 || rc=$?
if [ "$rc" -eq 124 ]; then
    pass "the window starts and stays up"
else
    fail "the window exited with $rc: $(tail -n 3 /tmp/window.log | tr '\n' ' ')"
fi

echo "== remove: $REMOVE"
if sh -c "$REMOVE"; then
    check "removing it takes $APP with it" sh -c "[ ! -e $APP ]"
    check "and /usr/bin/random-wallpaper" sh -c "[ ! -e /usr/bin/random-wallpaper ] && [ ! -L /usr/bin/random-wallpaper ]"
    check "and the launcher entry" sh -c "[ ! -e /usr/share/applications/dev.ivanc.RandomWallpaper.desktop ]"
else
    fail "package manager could not remove it: $REMOVE"
fi

echo "== $failures failed"
[ "$failures" -eq 0 ]
