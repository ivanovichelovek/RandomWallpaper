# Build a standalone binary for the current platform:
#   pip install .[build]
#   pyinstaller packaging/pyinstaller.spec
#
# One spec for all three platforms; PyInstaller itself resolves the
# platform-specific bits (the .exe suffix, the .app bundle) from the machine
# it runs on, which is why this is not three separate spec files.
import sys
from pathlib import Path

block_cipher = None
root = Path(SPECPATH).parent

a = Analysis(
    # bootstrap.py, not randomwallpaper/__main__.py: PyInstaller runs its
    # entry script as a top-level __main__ outside any package, and
    # __main__.py's `from .cli import main` is a relative import that only
    # resolves inside the randomwallpaper package — it fails at startup in a
    # built binary with "attempted relative import with no known parent
    # package". bootstrap.py imports randomwallpaper as an ordinary package
    # instead, which is what a frozen build actually needs.
    [str(root / "packaging" / "bootstrap.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / "randomwallpaper" / "resources"), "randomwallpaper/resources")],
    hiddenimports=["randomwallpaper.desktop.linux", "randomwallpaper.desktop.macos",
                   "randomwallpaper.desktop.windows"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas,
    name="random-wallpaper",
    debug=False,
    strip=False,
    upx=True,
    console=False,             # the GUI build; a console build is the pip
                                # console-script entry point instead
    # No icon here on purpose: PyInstaller's EXE/BUNDLE icon= wants a native
    # format per platform (.ico on Windows, .icns on macOS) and the project
    # only ships resources/icon.svg. Passing the SVG straight through fails
    # the build rather than degrading gracefully. Convert it once — e.g.
    # `magick icon.svg -define icon:auto-resize=256,128,64,48,32,16 icon.ico`
    # and the macOS equivalent via `iconutil` — and point `icon=` at that
    # file if a polished app icon is wanted.
    icon=None,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="Random Wallpaper.app",
        icon=None,          # provide an .icns here for a polished bundle
        bundle_identifier="dev.ivanc.RandomWallpaper",
        info_plist={
            "CFBundleName": "Random Wallpaper",
            "CFBundleShortVersionString": "1.0.0",
            "NSHighResolutionCapable": True,
        },
    )
