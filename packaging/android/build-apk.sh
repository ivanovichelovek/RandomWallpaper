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
cp packaging/android/main.py "$stage/"
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
    -shared -fPIC -O2 -Wl,-z,max-page-size=16384 \
    -o "$stage/libjnienv.so" packaging/android/jnienv.c -ldl

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
cp "$apk" "$repo/dist/android/RandomWallpaper-$VERSION-android-${ARCH:-x86_64}-debug.apk"
ls -l "$repo/dist/android"
