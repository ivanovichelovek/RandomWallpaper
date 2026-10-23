#!/usr/bin/env bash
# Install the .apk on the running emulator, start it in tour mode and keep
# what it shows: the app's own grabs of each tab (shots/app-*.png), the
# phone's screen at the same moments (shots/screen-*.png), and the logcat.
#
#   packaging/android/tour.sh <apk> <output dir>
set -u
APK=$1 OUT=$2
PKG=${PACKAGE:-dev.ivanc.randomwallpaper}
mkdir -p "$OUT"
adb logcat -c
adb logcat -v time > "$OUT/logcat.txt" &
logcat=$!

adb install -r -g "$APK"
# run-as: the app's private directory, which a debug build lets in.
adb shell run-as "$PKG" sh -c "'mkdir -p files && touch files/tour && rm -rf files/shots'"
adb shell am start -n "$PKG/org.kivy.android.PythonActivity"

seen=""
for _ in $(seq 1 120); do
    sleep 2
    names=$(adb shell run-as "$PKG" ls files/shots 2>/dev/null | tr -d '\r')
    for f in $names; do
        case " $seen " in *" $f "*) continue ;; esac
        seen="$seen $f"
        [ "$f" = done ] && continue
        name=${f%.png}
        adb exec-out screencap -p > "$OUT/screen-$name.png"
        adb exec-out run-as "$PKG" cat "files/shots/$f" > "$OUT/app-$name.png"
        echo "got $name"
    done
    case " $seen " in *" done "*) break ;; esac
    if ! adb shell pidof "$PKG" >/dev/null; then
        echo "the app is not running"
        adb exec-out screencap -p > "$OUT/screen-exit.png"
        break
    fi
done
adb exec-out screencap -p > "$OUT/screen-last.png"
kill "$logcat" 2>/dev/null
grep -E "python|Python|rw-tour|Traceback|Error" "$OUT/logcat.txt" | tail -n 200
ls -l "$OUT"
