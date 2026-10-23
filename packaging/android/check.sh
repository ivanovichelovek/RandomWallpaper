#!/usr/bin/env bash
# Install a release .apk on the running emulator, start it, and fail if it
# does not stay up: the check release.yml runs before publishing one.
#
#   packaging/android/check.sh <apk> <output dir>
set -u
APK=$1 OUT=$2
PKG=${PACKAGE:-dev.ivanc.randomwallpaper}
mkdir -p "$OUT"
sleep 30        # the launcher, busy after boot (see tour.sh)
adb shell settings put global hide_error_dialogs 1 >/dev/null 2>&1
adb logcat -c
adb logcat -v time > "$OUT/logcat.txt" &
logcat=$!
fail=0
adb install -r "$APK" || { echo "::error::the .apk did not install"; exit 1; }
adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null
sleep 60        # unpacking Python and the first frames
adb exec-out screencap -p > "$OUT/screen.png"
if ! adb shell pidof "$PKG" >/dev/null; then
    echo "::error::the app is not running a minute after it was started"
    fail=1
fi
kill "$logcat" 2>/dev/null
if grep -q "rw-crash" "$OUT/logcat.txt"; then
    echo "::error::the app reported a crash"
    grep -A20 "rw-crash" "$OUT/logcat.txt" | grep python | head -n 30
    fail=1
fi
grep -E "I/python" "$OUT/logcat.txt" | grep -v extracting | tail -n 20
exit $fail
