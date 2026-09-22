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
    [str(root / "randomwallpaper" / "__main__.py")],
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
    icon=str(root / "randomwallpaper" / "resources" / "icon.svg")
         if sys.platform == "win32" else None,
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
