# Build the app for the current platform:
#   uv sync --extra build [--extra macos]
#   uv run pyinstaller packaging/pyinstaller.spec
#
# One spec for all three platforms; what comes out differs by the machine it
# runs on:
#
#   Linux    dist/random-wallpaper/          → packaging/linux/build-appimage.sh
#   Windows  dist/random-wallpaper/          → packaging/windows/installer.iss
#            random-wallpaper.exe (windowed) + random-wallpaper-cli.exe
#   macOS    dist/Random Wallpaper.app       → packaging/macos/build-dmg.sh
#
# onedir, not onefile. A onefile binary unpacks its whole payload — all of Qt
# — into a fresh temporary directory every time it starts, and the timer
# starts it every minute.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(SPECPATH).parent))
from randomwallpaper import __version__  # noqa: E402

block_cipher = None
root = Path(SPECPATH).parent
IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"

a = Analysis(
    # bootstrap.py, not randomwallpaper/__main__.py: PyInstaller runs its
    # entry script as a top-level __main__ outside any package, and
    # __main__.py's `from .cli import main` is a relative import that only
    # resolves inside the randomwallpaper package.
    [str(root / "packaging" / "bootstrap.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / "randomwallpaper" / "resources"), "randomwallpaper/resources")],
    hiddenimports=["randomwallpaper.desktop.linux", "randomwallpaper.desktop.macos",
                   "randomwallpaper.desktop.windows"],
    hookspath=[],
    runtime_hooks=[],
    # Qt modules nothing here imports; left in, they are most of the size.
    excludes=["PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf",
              "PySide6.QtWebEngineCore", "PySide6.Qt3DCore", "tkinter"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

icon = None
if IS_WINDOWS and (root / "packaging" / "windows" / "icon.ico").exists():
    icon = str(root / "packaging" / "windows" / "icon.ico")
if IS_MACOS and (root / "packaging" / "macos" / "icon.icns").exists():
    icon = str(root / "packaging" / "macos" / "icon.icns")

gui = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="random-wallpaper",
    debug=False,
    strip=False,
    upx=False,
    console=False,       # no console window on Windows — this is what the
                         # Start menu and the scheduled task run
    icon=icon,
)
executables = [gui]
if IS_WINDOWS:
    # On Windows a windowed exe has no stdout at all, so --period, --version
    # and friends would print nothing. The console twin shares every file
    # of the build; only the few-hundred-KB launcher differs.
    executables.append(EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="random-wallpaper-cli",
        debug=False, strip=False, upx=False, console=True, icon=icon,
    ))

coll = COLLECT(
    *executables, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False,
    name="random-wallpaper",
)

if IS_MACOS:
    app = BUNDLE(
        coll,
        name="Random Wallpaper.app",
        icon=icon,
        bundle_identifier="dev.ivanc.RandomWallpaper",
        version=__version__,
        info_plist={
            "CFBundleName": "Random Wallpaper",
            "CFBundleDisplayName": "Random Wallpaper",
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSHighResolutionCapable": True,
            # The PySide6 wheel is built for macOS 13 (macosx_13_0).
            "LSMinimumSystemVersion": "13.0",
            # Setting the wallpaper through System Events, when PyObjC is
            # missing, needs this string or macOS refuses outright.
            "NSAppleEventsUsageDescription":
                "Random Wallpaper sets your desktop picture.",
        },
    )
