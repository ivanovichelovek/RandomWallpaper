#!/usr/bin/env python3
"""Hand the generated timer to the platform's own scheduler, and take it back.

tests/test_core.py checks what the LaunchAgent and the scheduled task *say*;
this checks that launchd and Task Scheduler *accept* it — the half no amount
of parsing on Linux can prove. Nothing is left registered afterwards, and
nothing runs: the plist is only linted, never loaded (RunAtLoad would set a
real wallpaper), and the task is registered under a throwaway name and
deleted before any of its triggers can fire.

On Linux there is nothing to do: systemd units are plain text that
systemd-analyze would only lint, and CI runners have no user session.
"""
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from randomwallpaper import schedule  # noqa: E402


def main():
    exe = schedule._executable()
    with tempfile.TemporaryDirectory() as tmp:
        if sys.platform == "darwin":
            path = Path(tmp) / "agent.plist"
            path.write_bytes(schedule.launch_agent_plist(
                exe, schedule._workdir(), str(Path(tmp) / "log")))
            subprocess.run(["plutil", "-lint", str(path)], check=True)
        elif sys.platform.startswith("win"):
            path = Path(tmp) / "task.xml"
            path.write_text(schedule.task_xml(exe, schedule._workdir(),
                                              schedule._windows_user(),
                                              date.today()),
                            encoding="utf-16")
            name = f"RandomWallpaperCI{os.getpid()}"
            subprocess.run(["schtasks", "/Create", "/TN", name, "/XML",
                            str(path), "/F"], check=True)
            try:
                subprocess.run(["schtasks", "/Query", "/TN", name, "/XML"],
                               check=True)
            finally:
                subprocess.run(["schtasks", "/Delete", "/TN", name, "/F"],
                               check=True)
        else:
            print("nothing to register on this platform")
            return 0
    print("scheduler accepted the timer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
