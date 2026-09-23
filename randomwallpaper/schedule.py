"""Installing and removing the calendar rotation's own timer.

Three platforms, three schedulers, one idea: run `random-wallpaper --auto
--quiet` at login and then every minute, catching up a missed tick if the
machine was asleep or off. Every minute because the tick is what decides
when the wallpaper changes — at midnight, every so often, or at set times of
day (core.current_slot) — and a timer that only knew about one of those
would have to be rewritten every time the setting changed. A tick with
nothing to do reads two small files and exits, in about a tenth of a second.

  Linux    systemd --user timer: OnStartupSec, minutely, Persistent=true
  macOS    LaunchAgent: RunAtLoad, StartInterval 60, StartCalendarInterval
           00:00 — launchd fires a calendar interval missed in sleep on wake
  Windows  Task Scheduler: at logon, on unlock, daily from 00:00 repeating
           every minute, StartWhenAvailable — a tick missed while off runs as
           soon as the machine is back

TIMER_VERSION is stamped into what gets installed, so a timer from an older
version — the hourly one — is recognised and replaced rather than silently
capping a wallpaper meant to change every 15 minutes at once an hour.

Nothing here is required for the app to work — the window always works
without it — it only wires up the unattended half.
"""
import os
import sys
from pathlib import Path

from .paths import APP_ID, IS_LINUX, IS_MACOS, IS_WINDOWS

LAUNCH_AGENT_LABEL = "dev.ivanc.RandomWallpaper.auto"
TIMER_VERSION = 2
MARKER = f"random-wallpaper-timer v{TIMER_VERSION}"
TICK_ARGS = ["--auto", "--quiet"]


def _executable():
    """The command a scheduled run should invoke.

    A frozen build (PyInstaller's .exe or .app) is its own entry point:
    nothing is on PATH, and `-m randomwallpaper` means nothing to it. On
    Windows the windowed entry point is preferred, because the console one
    flashes a console over the desktop every hour; --auto has nothing to show
    anyway, and print() to pythonw's missing stdout is a silent no-op. Last
    comes `python -m randomwallpaper`, for a run from a git checkout with no
    entry points installed yet.
    """
    import shutil
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        # The Windows build has a console twin for the command line; the
        # timer runs the windowed one whichever of the two installed it.
        if exe.stem.endswith("-cli"):
            windowed = exe.with_name(exe.stem[:-4] + exe.suffix)
            if windowed.exists():
                return [str(windowed)]
        return [str(exe)]
    if IS_WINDOWS:
        exe = shutil.which("random-wallpaper-gui")
        if exe:
            return [exe]
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if pythonw.exists():
            return [str(pythonw), "-m", "randomwallpaper"]
    exe = shutil.which("random-wallpaper")
    if exe:
        return [exe]
    return [sys.executable, "-m", "randomwallpaper"]


def _workdir():
    """Where a scheduled run starts: the directory holding the package, so
    the `-m randomwallpaper` fallback resolves even from an uninstalled
    checkout. launchd and Task Scheduler would otherwise start it in / and
    System32.

    Not in a frozen build: a onefile binary's __file__ is under its own
    temporary extraction directory, gone the moment the process that
    installed the timer exits — and a start-in directory that does not exist
    is a task Task Scheduler refuses to start. The binary's own folder
    outlives it.
    """
    if getattr(sys, "frozen", False):
        return str(Path(_executable()[0]).resolve().parent)
    return str(Path(__file__).resolve().parent.parent)


# ── Linux: a systemd --user unit, same shape as the original ────────────────
def _linux_unit_dir():
    import os
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd" / "user"


def linux_units(exe):
    """The service and the timer, as text."""
    # ConditionPathExists: uninstalling the package cannot reach a user's
    # own timer, and without this the tick would fail every minute against a
    # program that is gone. With it, systemd skips the tick quietly.
    service = f"""\
# {MARKER}
[Unit]
Description=Set the wallpaper the calendar calls for
After=graphical-session.target
PartOf=graphical-session.target
ConditionPathExists={exe[0]}

[Service]
Type=oneshot
ExecStart={" ".join(list(exe) + TICK_ARGS)}
SuccessExitStatus=0 1
"""
    # AccuracySec=1s: the default minute of slack would let "07:30" land at
    # 07:31.
    timer = f"""\
# {MARKER}
[Unit]
Description=Minutely check for the wallpaper the calendar calls for

[Timer]
OnStartupSec=1min
OnCalendar=minutely
Persistent=true
AccuracySec=1s

[Install]
WantedBy=timers.target
"""
    return service, timer


def install_linux():
    service, timer = linux_units(_executable())
    unit_dir = _linux_unit_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / "random-wallpaper-auto.service").write_text(service)
    (unit_dir / "random-wallpaper-auto.timer").write_text(timer)
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


def launch_agent_plist(exe, workdir, log):
    """The LaunchAgent, as bytes. plistlib rather than a template, so a path
    with an ampersand in it is escaped instead of breaking the XML."""
    import plistlib
    return plistlib.dumps({
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": list(exe) + TICK_ARGS,
        "WorkingDirectory": workdir,
        # Only in a logged-in GUI session: there is no desktop to set a
        # wallpaper on anywhere else.
        "LimitLoadToSessionType": "Aqua",
        "RunAtLoad": True,
        "StartInterval": 60,
        # Unlike StartInterval, a calendar interval that fell while the Mac
        # was asleep is run on wake — this is Persistent=true's counterpart.
        "StartCalendarInterval": {"Hour": 0, "Minute": 0},
        "ProcessType": "Background",
        "StandardOutPath": log,
        "StandardErrorPath": log,
    })


def install_macos():
    from .update import macos_bundle, macos_misplaced
    bundle = macos_bundle() if getattr(sys, "frozen", False) else None
    problem = bundle and macos_misplaced(bundle)
    if problem:
        raise RuntimeError(f"not scheduling it: {problem}")
    path = _launch_agent_path()
    log = Path.home() / "Library" / "Logs" / "random-wallpaper-auto.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(launch_agent_plist(_executable(), _workdir(), str(log)))

    from .desktop.common import run
    # bootstrap/bootout are the current launchctl verbs; load/unload are the
    # deprecated ones every macOS still answers, kept as the fallback.
    domain = f"gui/{os.getuid()}"
    run(["launchctl", "bootout", domain, str(path)], check=False)
    if run(["launchctl", "bootstrap", domain, str(path)], check=False).returncode:
        run(["launchctl", "unload", str(path)], check=False)
        run(["launchctl", "load", "-w", str(path)])
    return path


def uninstall_macos():
    path = _launch_agent_path()
    from .desktop.common import run
    run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)], check=False)
    run(["launchctl", "unload", str(path)], check=False)
    path.unlink(missing_ok=True)


# ── Windows: Task Scheduler ──────────────────────────────────────────────────
TASK_NAME = "RandomWallpaperAuto"
TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"


def _windows_user():
    domain = os.environ.get("USERDOMAIN")
    import getpass
    user = getpass.getuser()
    return f"{domain}\\{user}" if domain else user


def task_xml(exe, workdir, user, today):
    """The scheduled task, as the XML `schtasks /Create /XML` takes.

    XML rather than /SC flags, because the flags give one trigger per task
    and this needs four:

    * daily at 00:00, repeating every minute for the rest of the day — the
      shortest repetition Task Scheduler has. No time zone on the boundary,
      so it is local midnight and follows DST;
    * at logon, and on unlock — waking from sleep lands on the lock screen,
      so unlock is the wake-up tick.

    StartWhenAvailable is Persistent=true's counterpart: a tick that fell
    while the machine was off or asleep runs as soon as it can. The battery
    settings are spelled out because Task Scheduler's defaults are to skip
    a start on battery, which would have a laptop quietly miss every
    midnight it spent unplugged. The logon and unlock triggers carry the
    user explicitly: without one they mean any user, which needs admin.
    InteractiveToken with LeastPrivilege is "only while this user is logged
    on, unelevated" — the wallpaper belongs to that session and no other.
    """
    import subprocess
    import xml.etree.ElementTree as ET

    def sub(parent, tag, text=None, **attrs):
        el = ET.SubElement(parent, f"{{{TASK_NS}}}{tag}", attrs)
        if text is not None:
            el.text = text
        return el

    program, *rest = exe
    ET.register_namespace("", TASK_NS)
    task = ET.Element(f"{{{TASK_NS}}}Task", version="1.2")

    info = sub(task, "RegistrationInfo")
    sub(info, "Author", user)
    sub(info, "Description", "Set the wallpaper the calendar calls for "
                             f"(random-wallpaper --auto) [{MARKER}]")

    triggers = sub(task, "Triggers")
    daily = sub(triggers, "CalendarTrigger")
    rep = sub(daily, "Repetition")
    sub(rep, "Interval", "PT1M")
    sub(rep, "Duration", "P1D")
    sub(rep, "StopAtDurationEnd", "false")
    sub(daily, "StartBoundary", f"{today.isoformat()}T00:00:00")
    sub(daily, "Enabled", "true")
    sub(sub(daily, "ScheduleByDay"), "DaysInterval", "1")

    logon = sub(triggers, "LogonTrigger")
    sub(logon, "Enabled", "true")
    sub(logon, "UserId", user)
    sub(logon, "Delay", "PT1M")

    unlock = sub(triggers, "SessionStateChangeTrigger")
    sub(unlock, "Enabled", "true")
    sub(unlock, "StateChange", "SessionUnlock")
    sub(unlock, "UserId", user)
    sub(unlock, "Delay", "PT30S")

    principal = sub(sub(task, "Principals"), "Principal", id="Author")
    sub(principal, "UserId", user)
    sub(principal, "LogonType", "InteractiveToken")
    sub(principal, "RunLevel", "LeastPrivilege")

    settings = sub(task, "Settings")
    sub(settings, "MultipleInstancesPolicy", "IgnoreNew")
    sub(settings, "DisallowStartIfOnBatteries", "false")
    sub(settings, "StopIfGoingOnBatteries", "false")
    sub(settings, "AllowHardTerminate", "true")
    sub(settings, "StartWhenAvailable", "true")
    sub(settings, "RunOnlyIfNetworkAvailable", "false")
    idle = sub(settings, "IdleSettings")
    sub(idle, "StopOnIdleEnd", "false")
    sub(idle, "RestartOnIdle", "false")
    sub(settings, "AllowStartOnDemand", "true")
    sub(settings, "Enabled", "true")
    sub(settings, "Hidden", "false")
    sub(settings, "RunOnlyIfIdle", "false")
    sub(settings, "WakeToRun", "false")
    sub(settings, "ExecutionTimeLimit", "PT10M")
    sub(settings, "Priority", "7")

    action = sub(sub(task, "Actions", Context="Author"), "Exec")
    sub(action, "Command", program)
    sub(action, "Arguments", subprocess.list2cmdline(rest + TICK_ARGS))
    sub(action, "WorkingDirectory", workdir)

    return ('<?xml version="1.0" encoding="UTF-16"?>\n'
            + ET.tostring(task, encoding="unicode"))


def install_windows():
    import tempfile
    from datetime import date
    from .desktop.common import run

    xml = task_xml(_executable(), _workdir(), _windows_user(), date.today())
    # schtasks reads the file as UTF-16, BOM and all, matching the declaration.
    fd, tmp = tempfile.mkstemp(suffix=".xml")
    try:
        with os.fdopen(fd, "w", encoding="utf-16") as fh:
            fh.write(xml)
        run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", tmp, "/F"])
    finally:
        Path(tmp).unlink(missing_ok=True)
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


def status():
    """What is installed: "missing", "current", "outdated" — ours, but from
    an older version or running a different copy of the app — or "foreign".

    A different copy is outdated too: moving from a `uv tool` install to the
    AppImage, say, would otherwise leave the timer running the old one while
    Settings reported it as up to date.

    Foreign is a symlink: a timer managed from somewhere else, a dotfiles
    repository most likely, which writing through would change behind its
    owner's back. Windows has no such case; the task name is this app's.
    """
    exe = _executable()
    if IS_LINUX:
        path = _linux_unit_dir() / "random-wallpaper-auto.timer"
        service = path.with_suffix(".service")
        if path.is_symlink():
            return "foreign"
        if not path.exists():
            return "missing"
        try:
            current = (MARKER in path.read_text()
                       and service.read_text() == linux_units(exe)[0])
        except OSError:
            return "outdated"
        return "current" if current else "outdated"
    if IS_MACOS:
        import plistlib
        path = _launch_agent_path()
        if path.is_symlink():
            return "foreign"
        if not path.exists():
            return "missing"
        try:
            agent = plistlib.loads(path.read_bytes())
        except Exception:
            return "outdated"
        return ("current" if agent.get("StartInterval") == 60
                and agent.get("ProgramArguments") == list(exe) + TICK_ARGS
                else "outdated")
    if IS_WINDOWS:
        import subprocess
        # Bytes, not text: what schtasks writes to a pipe is in the console's
        # code page, or UTF-16, depending on the Windows version. The marker
        # is ASCII, so it is looked for in both spellings instead; the
        # program path may not be, so it is compared case-insensitively in
        # whichever spelling decodes.
        try:
            done = subprocess.run(
                ["schtasks", "/Query", "/TN", TASK_NAME, "/XML"],
                capture_output=True, timeout=15, creationflags=0x08000000)
        except (OSError, subprocess.SubprocessError):
            return "missing"
        if done.returncode:
            return "missing"
        raw = done.stdout
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in raw[:200]:
            text = raw.decode("utf-16", "ignore")
        else:
            import locale
            text = raw.decode(locale.getpreferredencoding(False), "ignore")
        from xml.sax.saxutils import escape
        found = MARKER in text and escape(exe[0]).lower() in text.lower()
        return "current" if found else "outdated"
    return "foreign"


def is_installed():
    return status() != "missing"


def ensure_installed():
    """Install the timer if there is none, or replace one of ours from an
    older version. True if it wrote anything.

    What the Settings checkbox calls: ticking "change the wallpaper by
    itself" should be all it takes on every platform, not only where someone
    thought to run --install-timer. A foreign timer is left exactly as it is.
    """
    if status() in ("current", "foreign"):
        return False
    install()
    return True
