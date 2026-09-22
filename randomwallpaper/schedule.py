"""Installing and removing the calendar rotation's own timer.

Three platforms, three schedulers, one idea: run `random-wallpaper --auto`
about once an hour and once more right at midnight, catching up a missed tick
if the machine was asleep or off. Nothing here is required for the app to
work — the window always works without it — it only wires up the unattended
half.
"""
import sys
from pathlib import Path

from .paths import APP_ID, IS_LINUX, IS_MACOS, IS_WINDOWS

LAUNCH_AGENT_LABEL = "dev.ivanc.RandomWallpaper.auto"


def _executable():
    """The command a scheduled run should invoke.

    Prefers the installed console-script entry point; falls back to `python -m
    randomwallpaper` for a run from source, e.g. a git checkout with no
    `pip install -e .` done yet.
    """
    import shutil
    exe = shutil.which("random-wallpaper")
    if exe:
        return [exe]
    return [sys.executable, "-m", "randomwallpaper"]


# ── Linux: a systemd --user unit, same shape as the original ────────────────
def _linux_unit_dir():
    import os
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd" / "user"


def install_linux():
    exe = " ".join(_executable())
    unit_dir = _linux_unit_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)

    (unit_dir / "random-wallpaper-auto.service").write_text(f"""\
[Unit]
Description=Set the wallpaper the calendar calls for
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=oneshot
ExecStart={exe} --auto
SuccessExitStatus=0 1
""")
    (unit_dir / "random-wallpaper-auto.timer").write_text("""\
[Unit]
Description=Hourly check for the wallpaper the calendar calls for

[Timer]
OnStartupSec=2min
OnCalendar=hourly
OnCalendar=*-*-* 00:00:00
Persistent=true
AccuracySec=1min

[Install]
WantedBy=timers.target
""")
    from .desktop.common import run
    run(["systemctl", "--user", "daemon-reload"], check=False)
    run(["systemctl", "--user", "enable", "--now",
         "random-wallpaper-auto.timer"], check=False)
    return unit_dir


def uninstall_linux():
    from .desktop.common import run
    run(["systemctl", "--user", "disable", "--now",
         "random-wallpaper-auto.timer"], check=False)
    unit_dir = _linux_unit_dir()
    for name in ("random-wallpaper-auto.service", "random-wallpaper-auto.timer"):
        (unit_dir / name).unlink(missing_ok=True)
    run(["systemctl", "--user", "daemon-reload"], check=False)


# ── macOS: a LaunchAgent ─────────────────────────────────────────────────────
def _launch_agent_path():
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"


def install_macos():
    exe = _executable()
    args = "\n".join(f"        <string>{a}</string>" for a in exe + ["--auto"])
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCH_AGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{args}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StartInterval</key>
    <integer>3600</integer>
    <key>StandardOutPath</key>
    <string>/tmp/random-wallpaper-auto.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/random-wallpaper-auto.log</string>
</dict>
</plist>
"""
    path = _launch_agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plist)
    from .desktop.common import run
    run(["launchctl", "unload", str(path)], check=False)
    run(["launchctl", "load", "-w", str(path)], check=False)
    return path


def uninstall_macos():
    path = _launch_agent_path()
    from .desktop.common import run
    run(["launchctl", "unload", str(path)], check=False)
    path.unlink(missing_ok=True)


# ── Windows: Task Scheduler ──────────────────────────────────────────────────
TASK_NAME = "RandomWallpaperAuto"


def install_windows():
    exe = _executable()
    program, *rest = exe
    args = " ".join(rest + ["--auto"])
    from .desktop.common import run
    # /RL LIMITED: no elevation needed, this only ever touches the user's own
    # wallpaper. /SC HOURLY repeats from creation time; a genuinely missed
    # tick (the machine was asleep or off) is picked up at the next hourly
    # firing rather than being caught up immediately the way the Linux
    # timer's Persistent=true is — schtasks has no direct equivalent, and
    # --auto's own idempotence (it acts at most once per period) means the
    # worst case is a boundary noticed an hour late, not skipped outright.
    run(["schtasks", "/Create", "/TN", TASK_NAME, "/TR",
         f'"{program}" {args}'.strip(), "/SC", "HOURLY", "/RL", "LIMITED", "/F"])
    return TASK_NAME


def uninstall_windows():
    from .desktop.common import run
    run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], check=False)


def install():
    if IS_LINUX:
        return install_linux()
    if IS_MACOS:
        return install_macos()
    if IS_WINDOWS:
        return install_windows()
    raise RuntimeError("unsupported platform")


def uninstall():
    if IS_LINUX:
        return uninstall_linux()
    if IS_MACOS:
        return uninstall_macos()
    if IS_WINDOWS:
        return uninstall_windows()
    raise RuntimeError("unsupported platform")
