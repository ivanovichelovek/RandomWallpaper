#!/usr/bin/env python3
"""pyside6-android-deploy, with the buildozer.spec it writes adjusted.

    python deploy.py <pyside6-android-deploy arguments>

The tool hardcodes the requirements (python3, shiboken6, PySide6), the
permissions (whatever the Qt modules declare) and a package id made from the
title, and deletes any buildozer.spec it finds before it starts — so the
changes go in right after it has written its own, in the same process.
"""
import os
import runpy
import sys
from pathlib import Path

import PySide6

SCRIPTS = Path(PySide6.__file__).parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from deploy_lib.android import buildozer  # noqa: E402

# pyjnius: WallpaperManager. The rest are pure Python, pip-installed by p4a.
EXTRA_REQUIREMENTS = ["pyjnius", "certifi", "platformdirs"]
EXTRA_PERMISSIONS = ["INTERNET", "SET_WALLPAPER"]

_written = buildozer.BuildozerConfig.__init__


def _adjusted(self, spec_file, pysidedeploy_config):
    _written(self, spec_file, pysidedeploy_config)
    requirements = self.get_value("app", "requirements").split(",")
    self.set_value("app", "requirements",
                   ",".join(requirements + EXTRA_REQUIREMENTS))
    permissions = [p.strip() for p in
                   (self.get_value("app", "android.permissions") or "").split(",")
                   if p.strip()]
    permissions += [p for p in EXTRA_PERMISSIONS
                    if p not in permissions
                    and f"android.permission.{p}" not in permissions]
    self.set_value("app", "android.permissions", ", ".join(permissions))
    self.set_value("app", "package.domain", "dev.ivanc")
    self.set_value("app", "package.name", "randomwallpaper")
    self.set_value("app", "title", "Random Wallpaper")
    self.set_value("app", "version", os.environ.get("RW_VERSION", "0.0.0"))
    self.set_value("app", "orientation", "portrait")
    # A release build is an .apk too, not the .aab buildozer makes by
    # default: it is installed straight from the GitHub release.
    self.set_value("app", "android.release_artifact", "apk")
    # The bundled fonts, icons and licences: by default buildozer packages
    # code and a few image types only, and the app fell back to Roboto.
    exts = self.get_value("app", "source.include_exts") or "py"
    extra = [e for e in ("ttf", "svg", "txt", "png", "so") if e not in exts.split(",")]
    self.set_value("app", "source.include_exts", ",".join([exts] + extra))
    # Material's dark theme: dark system bars around a dark window. The
    # default, Theme.NoTitleBar, draws a white navigation bar under it.
    self.set_value("app", "android.apptheme", "@android:style/Theme.Material.NoActionBar")
    # The activity: PythonActivity, kept alive across the recreate that
    # setting a wallpaper causes (java/…/WallpaperActivity.java).
    java = Path(__file__).resolve().parent / "java"
    self.set_value("app", "android.add_src", str(java))
    self.set_value("app", "android.entrypoint", "dev.ivanc.randomwallpaper.WallpaperActivity")
    # The SDK packages are installed already; nothing to prompt for.
    self.set_value("app", "android.accept_sdk_license", "True")
    self.set_value("app", "android.skip_update", "True")
    if Path("icon.png").exists():
        self.set_value("app", "icon.filename", str(Path("icon.png").resolve()))
    self.update_config()
    print("[deploy.py] buildozer.spec:", flush=True)
    print(Path(spec_file).read_text(), flush=True)


buildozer.BuildozerConfig.__init__ = _adjusted


# Qt plugins: the tool keeps only those the Qt modules declare, which on
# Android is the platform plugin alone — no image formats beyond PNG, so
# every JPEG frame decoded to nothing. These folders are added whole, from
# whatever the wheel carries.
EXTRA_PLUGIN_FOLDERS = ("imageformats", "iconengines")

from deploy_lib.android import android_config  # noqa: E402

_configured = android_config.AndroidConfig.__init__


def _with_plugins(self, *args, **kwargs):
    _configured(self, *args, **kwargs)
    import re
    import zipfile
    if not self.wheel_pyside:
        return
    # Named as the tool names them: "imageformats_qjpeg" for
    # plugins/imageformats/libplugins_imageformats_qjpeg_<arch>.so.
    pattern = re.compile(r"/plugins/(?:%s)/libplugins_(.+)_%s\.so$"
                         % ("|".join(EXTRA_PLUGIN_FOLDERS), self.arch))
    found = []
    with zipfile.ZipFile(self.wheel_pyside) as wheel:
        for name in wheel.namelist():
            match = pattern.search(name)
            if match:
                found.append(match.group(1))
    plugins = list(self.qt_plugins)
    plugins += [p for p in sorted(found) if p not in plugins]
    self.qt_plugins = plugins
    print(f"[deploy.py] Qt plugins: {plugins}", flush=True)


android_config.AndroidConfig.__init__ = _with_plugins

# debug (the default: debuggable, so the tour can read the app's files) or
# release (unsigned here; build-apk.sh signs it).
_plugins_then_mode = android_config.AndroidConfig.__init__


def _with_mode(self, *args, **kwargs):
    _plugins_then_mode(self, *args, **kwargs)
    self._mode = os.environ.get("RW_BUILD_MODE", "debug")


android_config.AndroidConfig.__init__ = _with_mode

sys.argv = [str(SCRIPTS / "android_deploy.py")] + sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
