"""Updating an installed build to the latest GitHub release.

Only the installed builds update themselves, each through the installer
its platform uses for everything else:

  linux     the new package — .pkg.tar.zst, .deb or .rpm, whichever format
            installed this one — goes through the package manager that owns
            it, via pkexec, which asks for the password; with no polkit agent
            to ask, the verified download is kept and the command to run is
            shown instead;
  windows   the new installer is run silently over the old install, which
            closes the app, replaces it and starts it again;
  macos     the new .pkg is opened in macOS's own Installer, which puts the
            app in /Applications (asking for the password that takes) and
            starts it again from the package's postinstall script.

A run from source — a git checkout, `uv tool install`, `pip install` — is
updated by whatever installed it, and is only told so.

Nothing is replaced until the download has been checked against the
release's SHA256SUMS; any failure before the swap leaves the install exactly
as it was.
"""
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from . import __version__

REPO = "ivanovichelovek/RandomWallpaper"
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
USER_AGENT = f"RandomWallpaper/{__version__} (+https://github.com/{REPO})"
TIMEOUT = 30


class UpdateError(Exception):
    """Why an update could not go ahead — shown to the user verbatim."""


# ── what is running ─────────────────────────────────────────────────────────
def parse_version(text):
    """"v1.2.3" / "1.2.3" → (1, 2, 3). Compared as integers, so 1.10 > 1.9."""
    text = text.strip().lstrip("vV")
    parts = text.split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        raise UpdateError(f"not a version: {text!r}") from None


def macos_bundle():
    """The .app this is running from, or None."""
    exe = Path(sys.executable).resolve()
    for parent in exe.parents:
        if parent.suffix == ".app":
            return parent
    return None


LINUX_PREFIX = Path("/opt/random-wallpaper")

# The package manager that owns a file, how to ask it, and how to install a
# package file with it. Asked in this order; the first that claims the
# executable is the one that installed it — an Arch box with dpkg installed
# for some other reason must still get the pacman package.
PACKAGE_MANAGERS = [
    ("pacman", ["pacman", "-Qo"], ["pacman", "-U", "--noconfirm"]),
    ("deb", ["dpkg", "-S"], ["apt-get", "install", "-y"]),
    ("rpm", ["rpm", "-qf"], None),     # dnf / zypper / rpm, chosen below
]


def linux_package_format(exe=None):
    """"pacman", "deb" or "rpm" — whichever package owns this install."""
    exe = str(exe or Path(sys.executable).resolve())
    for fmt, ask, _ in PACKAGE_MANAGERS:
        if not shutil.which(ask[0]):
            continue
        try:
            done = subprocess.run(ask + [exe], capture_output=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0:
            return fmt
    return None


def install_kind():
    """"linux", "windows", "macos" or "source"."""
    if not getattr(sys, "frozen", False):
        return "source"
    if sys.platform.startswith("linux"):
        exe = Path(sys.executable).resolve()
        return "linux" if LINUX_PREFIX in exe.parents else "source"
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin" and macos_bundle():
        return "macos"
    return "source"


def macos_misplaced(bundle):
    """Why this .app cannot be scheduled or updated where it is, or None.

    Run straight from the disk image, or from a download macOS has
    translocated to a random read-only path, the bundle's path is gone the
    moment the image is ejected or the app quits — a timer pointed there
    never fires again, and an update has nothing to replace.
    """
    text = str(bundle)
    if text.startswith("/Volumes/"):
        return "running from the disk image — drag it to Applications first"
    if "/AppTranslocation/" in text:
        return ("macOS is running it from a quarantine copy — move it to "
                "Applications, then open it from there")
    return None


def describe_install():
    kind = install_kind()
    return {
        "linux": "Linux package",
        "windows": "Windows app",
        "macos": "macOS app",
        "source": ("standalone build" if getattr(sys, "frozen", False)
                   else "run from source"),
    }[kind]


# ── what is on offer ────────────────────────────────────────────────────────
def asset_name(version, kind=None, machine=None, fmt=None):
    """The release asset this kind of install updates from.

    The one place these names are spelled: the release workflow names what
    it builds by calling this, so the two cannot drift apart.
    """
    kind = kind or install_kind()
    machine = (machine or platform.machine()).lower()
    if kind == "linux":
        fmt = fmt or linux_package_format()
        if fmt == "pacman":
            return f"random-wallpaper-{version}-1-x86_64.pkg.tar.zst"
        if fmt == "deb":
            return f"random-wallpaper_{version}_amd64.deb"
        if fmt == "rpm":
            return f"random-wallpaper-{version}-1.x86_64.rpm"
        return None
    if kind == "windows":
        return f"RandomWallpaper-{version}-windows-x64-setup.exe"
    if kind == "macos":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
        return f"RandomWallpaper-{version}-macos-{arch}.pkg"
    return None


def _get(url, accept="application/json"):
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": accept,
    })
    return urllib.request.urlopen(request, timeout=TIMEOUT)


def latest_release(url=None):
    """{"version", "tag", "url", "assets": {name: download_url}}.

    /releases/latest already leaves out drafts and pre-releases.
    RANDOM_WALLPAPER_RELEASES_URL points it at a stand-in feed, which is how
    the update path is tested without publishing anything.
    """
    url = url or os.environ.get("RANDOM_WALLPAPER_RELEASES_URL") or RELEASES_URL
    import urllib.error
    try:
        with _get(url) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            # What GitHub answers for a repository with no release yet.
            raise UpdateError("no release has been published yet") from exc
        raise UpdateError(f"the release feed answered {exc.code}") from exc
    except (OSError, ValueError) as exc:
        raise UpdateError(f"could not reach the release feed: {exc}") from exc
    tag = data.get("tag_name") or ""
    return {
        "version": ".".join(str(n) for n in parse_version(tag)),
        "tag": tag,
        "url": data.get("html_url") or f"https://github.com/{REPO}/releases",
        "assets": {a["name"]: a["browser_download_url"]
                   for a in data.get("assets", [])
                   if "name" in a and "browser_download_url" in a},
    }


def check(url=None):
    """(release, newer) — `newer` is whether it beats the running version."""
    release = latest_release(url)
    return release, parse_version(release["version"]) > parse_version(__version__)


# ── fetching it ─────────────────────────────────────────────────────────────
def parse_sums(text):
    """SHA256SUMS as {file name: hex digest}. Accepts `sha256sum` output in
    both its text and binary (`*name`) forms."""
    sums = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            sums[parts[1].lstrip("*").strip()] = parts[0].lower()
    return sums


def download(release, name, directory, progress=None):
    """The asset, downloaded into `directory` and verified. Returns its path.

    Into `directory` rather than /tmp so that the final os.replace is a
    rename on one filesystem — atomic, never a half-copied binary.
    """
    assets = release["assets"]
    if name not in assets:
        raise UpdateError(f"release {release['tag']} has no {name}")
    if "SHA256SUMS" not in assets:
        raise UpdateError(f"release {release['tag']} has no SHA256SUMS to "
                          f"check the download against")
    try:
        with _get(assets["SHA256SUMS"], accept="application/octet-stream") as r:
            sums = parse_sums(r.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise UpdateError(f"could not fetch SHA256SUMS: {exc}") from exc
    expected = sums.get(name)
    if not expected:
        raise UpdateError(f"SHA256SUMS does not list {name}")

    fd, tmp = tempfile.mkstemp(prefix=".update-", suffix=".part", dir=directory)
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as out, \
                _get(assets[name], accept="application/octet-stream") as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = response.read(1 << 16)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if digest.hexdigest() != expected:
            raise UpdateError(f"{name} does not match its checksum — not "
                              f"installing it")
    except BaseException as exc:
        Path(tmp).unlink(missing_ok=True)
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError(f"download failed: {exc}") from exc
    return Path(tmp)


# ── putting it in place ─────────────────────────────────────────────────────
def _detached(argv):
    """Start argv in its own session, outliving this process."""
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL, "close_fds": True}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = 0x00000008 | 0x00000200   # DETACHED | NEW_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(argv, **kwargs)


def _relaunch_after_exit(command):
    """Start `command` once this process has gone.

    Not straight away: a new window started while this one is still open
    finds this one's single-instance socket, hands its arguments over and
    exits — and then this one quits, leaving nothing running at all.
    """
    import shlex
    script = (f"while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.2; done; "
              f"exec {shlex.join(command)}")
    _detached(["/bin/sh", "-c", script])


def apply(release, progress=None):
    """Download, verify and install `release`. Returns a message.

    On success the caller should quit promptly: every path relaunches the
    new version only after this process is gone.
    """
    kind = install_kind()
    name = asset_name(release["version"], kind)
    if kind == "linux" and name is None:
        raise UpdateError("no package manager claims this install — update it "
                          "the way it was installed")
    if kind == "source":
        raise UpdateError("this copy runs from source — update it the way it "
                          "was installed (git pull, or uv tool upgrade "
                          "randomwallpaper)")

    if kind == "linux":
        return _apply_linux(release, name, progress)

    if kind == "windows":
        new = download(release, name, tempfile.gettempdir(), progress)
        setup = new.with_suffix(".exe")
        os.replace(new, setup)
        # The installer closes this app (CloseApplications), replaces it and
        # starts it again from its [Run] section; /VERYSILENT still runs
        # post-install entries that are not marked skipifsilent.
        _detached([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                   "/CLOSEAPPLICATIONS"])
        return f"installing {release['version']} — the app restarts by itself"

    # macOS: the same installer package a first install uses. /Applications
    # is not writable without an administrator's password, and Installer is
    # the one thing on a Mac that is meant to ask for it.
    bundle = macos_bundle()
    problem = macos_misplaced(bundle)
    if problem:
        raise UpdateError(problem)
    new = download(release, name, tempfile.gettempdir(), progress)
    package = new.with_name(name)
    os.replace(new, package)
    _detached(["open", str(package)])
    return (f"opening the {release['version']} installer — the app starts "
            f"again when it finishes")


# ── Linux, through the package manager ──────────────────────────────────────
def linux_install_command(fmt, package):
    """The root command that installs `package` (an absolute path)."""
    # abspath, not resolve(): absolute is what apt needs, and there is no
    # reason to trade the path the package was saved under for its target.
    package = os.path.abspath(package)
    if fmt == "pacman":
        return ["pacman", "-U", "--noconfirm", package]
    if fmt == "deb":
        # apt-get, not dpkg -i: it pulls in whatever a new version depends on.
        # The path must be absolute, or apt reads it as a package name.
        return ["apt-get", "install", "-y", package]
    for tool, cmd in (("dnf", ["dnf", "install", "-y"]),
                      ("zypper", ["zypper", "--non-interactive", "install",
                                  "--allow-unsigned-rpm"]),
                      ("rpm", ["rpm", "-U"])):
        if shutil.which(tool):
            return cmd + [package]
    return ["rpm", "-U", package]


def _apply_linux(release, name, progress):
    fmt = linux_package_format()
    directory = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") \
        / "random-wallpaper" / "updates"
    directory.mkdir(parents=True, exist_ok=True)
    new = download(release, name, directory, progress)
    package = directory / name
    os.replace(new, package)
    command = linux_install_command(fmt, package)

    manual = f"sudo {' '.join(command)}"
    if not shutil.which("pkexec"):
        raise UpdateError(f"downloaded and verified; install it with: {manual}")
    try:
        # pkexec, not sudo: sudo needs a terminal to ask on, and this is a
        # window. It asks through the desktop's polkit agent instead.
        done = subprocess.run(["pkexec"] + command, capture_output=True,
                              text=True, timeout=900)
    except (OSError, subprocess.SubprocessError) as exc:
        raise UpdateError(f"{exc} — install it with: {manual}") from exc
    if done.returncode == 126:
        raise UpdateError("the password prompt was dismissed — nothing changed")
    if done.returncode == 127:
        raise UpdateError(f"no polkit agent to ask for the password — "
                          f"install it with: {manual}")
    if done.returncode:
        detail = (done.stderr or done.stdout).strip().splitlines()
        raise UpdateError(f"{command[0]} failed"
                          + (f": {detail[-1]}" if detail else "")
                          + f" — or run: {manual}")
    package.unlink(missing_ok=True)
    # The package manager has just replaced this process's own files. Quit
    # without importing anything else, and come back as the new version.
    _relaunch_after_exit([str(Path(sys.executable).resolve())])
    return f"updated to {release['version']} — restarting"
