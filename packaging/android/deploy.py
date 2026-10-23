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
    if Path("icon.png").exists():
        self.set_value("app", "icon.filename", str(Path("icon.png").resolve()))
    self.update_config()
    print("[deploy.py] buildozer.spec:", flush=True)
    print(Path(spec_file).read_text(), flush=True)


buildozer.BuildozerConfig.__init__ = _adjusted

sys.argv = [str(SCRIPTS / "android_deploy.py")] + sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
