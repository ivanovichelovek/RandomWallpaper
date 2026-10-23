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

# A freshly booted emulator's launcher is often still busy, and its "isn't
# responding" dialog then sits over every screenshot: give it time, and
# keep system dialogs closed.
sleep 30
adb shell settings put global hide_error_dialogs 1 >/dev/null 2>&1
adb shell settings put secure anr_show_background 0 >/dev/null 2>&1
close_dialogs() { adb shell am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS >/dev/null 2>&1; }
adb install -r -g "$APK"
# run-as: the app's private directory, which a debug build lets in.
adb shell run-as "$PKG" sh -c "'mkdir -p files && touch files/tour && rm -rf files/shots'"
# The .apk itself, for the tour's last step to hand to the installer.
adb push "$APK" /data/local/tmp/rw-update.apk >/dev/null
adb shell run-as "$PKG" cp /data/local/tmp/rw-update.apk files/update-test.apk
adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null

seen=""
for _ in $(seq 1 240); do
    sleep 2
    names=$(adb shell run-as "$PKG" ls files/shots 2>/dev/null | tr -d '\r')
    for f in $names; do
        case " $seen " in *" $f "*) continue ;; esac
        seen="$seen $f"
        [ "$f" = done ] && continue
        name=${f%.png}
        close_dialogs
        adb exec-out screencap -p > "$OUT/screen-$name.png"
        adb exec-out run-as "$PKG" cat "files/shots/$f" > "$OUT/app-$name.png"
        echo "got $name"
    done
    case " $seen " in *" done "*) break ;; esac
    # The emulator itself sometimes restarts under the app; a check can
    # also just miss. Three misses in a row and it is gone: start it once
    # more before giving up.
    if adb shell pidof "$PKG" >/dev/null; then
        misses=0
    else
        misses=$((${misses:-0} + 1))
        if [ "$misses" -ge 3 ]; then
            adb exec-out screencap -p > "$OUT/screen-exit-$((${restarts:-0} + 1)).png"
            if [ "${restarts:-0}" -ge 1 ]; then
                echo "the app is not running"
                break
            fi
            restarts=$((${restarts:-0} + 1))
            echo "the app is gone — starting it again"
            adb wait-for-device
            adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null
            misses=0
        fi
    fi
done
adb exec-out screencap -p > "$OUT/screen-last.png"
kill "$logcat" 2>/dev/null
grep -E "python|Python|rw-tour|Traceback|Error" "$OUT/logcat.txt" | tail -n 200
ls -l "$OUT"
