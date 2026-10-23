#!/usr/bin/env bash
# The Android app: a debug .apk, through pyside6-android-deploy.
#
#   ANDROID_SDK=… ANDROID_NDK=… WHEELS=dir-with-the-two-android-wheels \
#       packaging/android/build-apk.sh          # → dist/android/*.apk
#
# Needs a Linux host with JDK 17+, Python 3.10+ with PySide6 (the same
# version as the wheels) and buildozer. See .github/workflows/android.yml.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
repo=$PWD

PY=${PYTHON:-python3}
VERSION=$("$PY" -c 'import randomwallpaper; print(randomwallpaper.__version__)')
pyside=$(find "$WHEELS" -maxdepth 1 -iname 'pyside6-*android*.whl' | head -n1)
shiboken=$(find "$WHEELS" -maxdepth 1 -iname 'shiboken6-*android*.whl' | head -n1)
[ -n "$pyside" ] && [ -n "$shiboken" ] || { echo "no Android wheels in $WHEELS" >&2; exit 1; }
echo "Random Wallpaper $VERSION with $(basename "$pyside")"

# The deploy tool packages everything under the directory main.py is in, so
# that directory holds the app and nothing else.
stage=${STAGE:-$repo/build/android/app}
rm -rf "$stage"
mkdir -p "$stage"
cp packaging/android/main.py packaging/android/auto.py "$stage/"
cp -r randomwallpaper "$stage/"
find "$stage" -name __pycache__ -prune -exec rm -rf {} +
cp packaging/macos/icon.iconset/icon_512x512.png "$stage/icon.png" 2>/dev/null || true

# The JNIEnv getter pyjnius needs under the Qt bootstrap (see jnienv.c),
# built for the same ABI as the app.
case "${ARCH:-x86_64}" in
    x86_64) triple=x86_64-linux-android ;;
    aarch64) triple=aarch64-linux-android ;;
esac
"$ANDROID_NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/${triple}28-clang" \
    -shared -fPIC -O2 -Wl,-z,max-page-size=16384 -Wl,-z,global \
    -Wl,-soname,libjnienv.so \
    -o "$stage/libjnienv.so" packaging/android/jnienv.c -ldl

# python-for-android at the commit the deploy tool pins, with one line more
# in the Qt bootstrap's manifest: the rotation's JobService (AutoJob.java),
# which needs BIND_JOB_SERVICE and a process of its own — the template has
# no place to add an element inside <application>.
P4A_COMMIT=$("$PY" - <<'PYEOF'
import sys
from pathlib import Path
import PySide6
sys.path.insert(0, str(Path(PySide6.__file__).parent / "scripts"))
from deploy_lib.android import buildozer
print(buildozer.P4A_COMMIT)
PYEOF
)
P4A_DIR=${P4A_DIR:-$HOME/p4a-$P4A_COMMIT}
if [ ! -d "$P4A_DIR/.git" ]; then
    git clone -q https://github.com/kivy/python-for-android.git "$P4A_DIR"
fi
git -C "$P4A_DIR" checkout -q --force "$P4A_COMMIT"
manifest="$P4A_DIR/pythonforandroid/bootstraps/qt/build/templates/AndroidManifest.tmpl.xml"
grep -q AutoJob "$manifest" || sed -i 's|^\(\s*\)</application>|\1<service android:name="dev.ivanc.randomwallpaper.AutoJob" android:permission="android.permission.BIND_JOB_SERVICE" android:process=":auto" android:exported="false" />\n\1</application>|' "$manifest"
grep -q AutoJob "$manifest" || { echo "could not add the job service to $manifest" >&2; exit 1; }
export P4A_DIR

cd "$stage"
RW_VERSION=$VERSION "$PY" "$repo/packaging/android/deploy.py" \
    --name RandomWallpaper \
    --wheel-pyside "$pyside" --wheel-shiboken "$shiboken" \
    --ndk-path "$ANDROID_NDK" --sdk-path "$ANDROID_SDK" \
    --extra-modules Network,Svg \
    --force --verbose

# The tool prints its own failures and still exits 0.
apk=$(ls "$stage"/*.apk 2>/dev/null | head -n1 || true)
[ -n "$apk" ] || { echo "no .apk came out" >&2; exit 1; }
mkdir -p "$repo/dist/android"
NAME=$("$PY" -c "from randomwallpaper.update import asset_name
print(asset_name('$VERSION', kind='android', machine='${ARCH:-x86_64}'))")
if [ "${RW_BUILD_MODE:-debug}" = release ]; then
    # Signed with the one key every release is signed with, or Android will
    # not install the next version over this one. KEYSTORE is the file,
    # KEYSTORE_PASSWORD and KEY_ALIAS its password and key.
    tools=$(ls -d "$ANDROID_SDK"/build-tools/* | sort -V | tail -n1)
    "$tools/zipalign" -p -f 4 "$apk" "$stage/aligned.apk"
    "$tools/apksigner" sign --ks "$KEYSTORE" --ks-pass env:KEYSTORE_PASSWORD \
        --ks-key-alias "$KEY_ALIAS" --key-pass env:KEYSTORE_PASSWORD \
        --out "$repo/dist/android/$NAME" "$stage/aligned.apk"
    "$tools/apksigner" verify --print-certs "$repo/dist/android/$NAME" | head -n 3
else
    cp "$apk" "$repo/dist/android/${NAME%.apk}-debug.apk"
fi
ls -l "$repo/dist/android"
