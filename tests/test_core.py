#!/usr/bin/env python3
"""Exercise randomwallpaper's file handling, calendar logic and filters.

Run it directly: tests/test_core.py — no pytest needed, though it also works
under one.

Ported from the original single-file Linux app's tests/test-random-wallpaper
.py, with one change beyond the import: rw.pictures_wallpapers() now goes
through randomwallpaper.desktop, which asks the platform rather than assuming
Noctalia, so the mock shell in the rotation section patches
randomwallpaper.core.set_wallpaper / wallpaper_now directly rather than a
single hardcoded backend.

The point is the promises the app makes. Two of them:

  * accepting a wallpaper must never destroy one already saved — so the
    collision branch of unique_path() and the "delete touches only the pending
    file" property are asserted;
  * the calendar rotation must act once per period and must never undo a
    wallpaper set by hand — so the period boundaries are walked day by day and
    the state file is checked for exactly that.

The calendar half is pure arithmetic and runs offline. The rest needs network:
it does one real download per source.

$HOME and the XDG variables are redirected before the app module is imported,
because SAVE_DIR and CONFIG_FILE are computed at import time. Nothing under
the real home is read or written.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

FAKE = Path(tempfile.mkdtemp(prefix="random-wallpaper-test-"))
(FAKE / "Pictures" / "Wallpapers").mkdir(parents=True)
os.environ["HOME"] = str(FAKE)
os.environ["USERPROFILE"] = str(FAKE)
os.environ["XDG_CACHE_HOME"] = str(FAKE / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(FAKE / ".config")
os.environ["XDG_STATE_HOME"] = str(FAKE / ".local" / "state")
# platformdirs' own escape hatch for exactly this: on Windows it resolves
# %APPDATA%/%LOCALAPPDATA% via SHGetKnownFolderPath, which ignores HOME and
# USERPROFILE entirely — without these, CONFIG_DIR/CACHE_DIR/STATE_DIR would
# quietly point at the *real* per-user profile on the machine running the
# test, sandboxed by nothing.
os.environ["WIN_PD_OVERRIDE_APPDATA"] = str(FAKE / "AppData" / "Roaming")
os.environ["WIN_PD_OVERRIDE_LOCAL_APPDATA"] = str(FAKE / "AppData" / "Local")
os.environ.pop("WALLHAVEN_API_KEY", None)
os.environ.pop("RANDOM_WALLPAPER_DIR", None)
os.environ.pop("RANDOM_WALLPAPER_SET_COMMAND", None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import randomwallpaper.core as rw  # noqa: E402
from randomwallpaper.ui.library_page import LibraryPage  # noqa: E402

ok = fail = 0


def check(label, cond):
    global ok, fail
    print(("PASS  " if cond else "FAIL  ") + label)
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)


# ── paths ───────────────────────────────────────────────────────────────────
check("SAVE_DIR follows HOME", rw.SAVE_DIR == FAKE / "random_wallpaper")
check("SAVE_DIR does not exist yet", not rw.SAVE_DIR.exists())
# CONFIG_FILE's parent is platformdirs' own answer, and that answer is
# deliberately not the same shape on every OS: XDG_CONFIG_HOME on Linux,
# but platformdirs ignores it on Windows and macOS in favour of each
# platform's own convention (%LOCALAPPDATA%, ~/Library/Application Support).
# The one thing every platform agrees on is that it is *somewhere under FAKE*
# — the point being tested is that $HOME redirection reached CONFIG_FILE at
# all, not which subdirectory convention answered it.
check("CONFIG_FILE is config.json under FAKE, wherever platformdirs put it",
      rw.CONFIG_FILE.name == "config.json" and FAKE in rw.CONFIG_FILE.parents)

# ── preferences round-trip ──────────────────────────────────────────────────
check("defaults load when no config exists", rw.load_prefs() == rw.DEFAULTS)
prefs = rw.load_prefs()
prefs["orientation"] = "portrait"
prefs["wallhaven_apikey"] = "secret-key"
rw.save_prefs(prefs)
check("prefs round-trip", rw.load_prefs()["orientation"] == "portrait")
# chmod(0o600) is a real permission narrowing on POSIX (Linux, macOS) but
# not on Windows: os.chmod() there can only toggle the read-only attribute,
# so st_mode never reflects Unix-style bits — an NTFS file protected by the
# user's own ACL (the actual mechanism there) can still report 0o666. The
# call is still made unconditionally in save_prefs() since it costs nothing
# and helps everywhere it can; only the assertion is platform-specific.
if os.name == "posix":
    check("config is 0600 — it can hold an API key",
          oct(rw.CONFIG_FILE.stat().st_mode & 0o777) == "0o600")
else:
    check("config.chmod(0o600) did not raise on Windows", True)
check("config keeps every key", "source" in json.loads(rw.CONFIG_FILE.read_text()))
check("config key used when env is unset", rw.wallhaven_key(prefs) == "secret-key")
os.environ["WALLHAVEN_API_KEY"] = "env-key"
check("WALLHAVEN_API_KEY overrides config", rw.wallhaven_key(prefs) == "env-key")
del os.environ["WALLHAVEN_API_KEY"]
rw.CONFIG_FILE.unlink()

# ── ratings are gone: a config written by an older version must not revive
# them, and nothing may read prefs["rating"] any more ────────────────────────
check("no rating in defaults", "rating" not in rw.DEFAULTS)
rw.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
rw.CONFIG_FILE.write_text(json.dumps({"rating": "nsfw", "orientation": "portrait"}))
stale = rw.load_prefs()
check("old rating dropped on load", "rating" not in stale)
check("other keys of an old config survive", stale["orientation"] == "portrait")
rw.CONFIG_FILE.unlink()

# ── filters ─────────────────────────────────────────────────────────────────
land = dict(rw.DEFAULTS, orientation="landscape", minimum="1920x1080")
port = dict(rw.DEFAULTS, orientation="portrait", minimum="1920x1080")
anysize = dict(rw.DEFAULTS, orientation="any", minimum="")

check("landscape rejects a portrait image", not rw._fits(land, 1080, 1920))
check("landscape accepts a wide image", rw._fits(land, 2560, 1440))
check("portrait rejects a wide image", not rw._fits(port, 2560, 1440))
check("minimum size rejects a small image", not rw._fits(land, 1280, 720))
check("Any size accepts a small image", rw._fits(anysize, 640, 480))
check("unknown dimensions pass through", rw._fits(land, None, None))

try:
    rw.pick_wallhaven(dict(rw.DEFAULTS, wallhaven_general=False,
                           wallhaven_anime=False, wallhaven_people=False))
    check("all categories off raises", False)
except rw.FetchError:
    check("all categories off raises", True)


# ── pixabay is gone, and an old config naming it must not resurrect it ──────
check("two sources only", [k for _, k, _ in rw.SOURCES] == ["konachan", "wallhaven"])
check("no pixabay key in defaults", "pixabay_apikey" not in rw.DEFAULTS)
rw.CONFIG_FILE.write_text(json.dumps({"source": "pixabay", "pixabay_apikey": "k"}))
revived = rw.load_prefs()
check("old pixabay key dropped on load", "pixabay_apikey" not in revived)
check("a config naming pixabay still resolves to a real source",
      rw.effective_source(revived) in ("konachan", "wallhaven"))
rw.CONFIG_FILE.unlink()

# ── themes ──────────────────────────────────────────────────────────────────
# Every theme the user can pick has to be reachable from somewhere; a theme
# neither source serves would be a dropdown entry that can only ever fail.
for key, label, ktag, wq in rw.THEMES:
    check(f"theme {key} is served by some source",
          any(rw.source_serves(src, key) for _, src, _ in rw.SOURCES))

check("all themes the user asked for are present",
      {"all", "summer", "autumn", "winter", "spring", "halloween",
       "christmas", "valentine", "easter"} == {t[0] for t in rw.THEMES})

# konachan has no easter tag — checked against the live tag index, not assumed
# — so the theme has to come from wallhaven instead of coming back empty.
check("konachan does not claim easter", not rw.source_serves("konachan", "easter"))
check("easter falls through to wallhaven",
      rw.effective_source(dict(rw.DEFAULTS, source="konachan", theme="easter"))
      == "wallhaven")
check("a theme konachan does serve stays on konachan",
      rw.effective_source(dict(rw.DEFAULTS, source="konachan", theme="winter"))
      == "konachan")
try:
    rw.pick_konachan(dict(rw.DEFAULTS, theme="easter"))
    check("konachan says why it cannot serve easter", False)
except rw.FetchError as exc:
    check("konachan says why it cannot serve easter", "wallhaven" in str(exc))

# An unknown theme must degrade to "all" everywhere at once, or the source
# that serves "no theme" and the fetch that demands a tag disagree forever.
future = dict(rw.DEFAULTS, theme="midsummer-2099")
check("an unknown theme reads as all", rw.theme_key(future) == "all")
check("an unknown theme is still servable", rw.source_serves("konachan", "midsummer-2099"))

# ── the calendar: seasons ───────────────────────────────────────────────────
from datetime import date, timedelta

SEASON_THEMES = {"spring", "summer", "autumn", "winter"}


def period(day, rite="orthodox"):
    return rw.current_period(day, rite)

check("Mar 1 starts spring", period(date(2026, 3, 1)) == ("spring", "spring-2026"))
check("May 31 is still spring", period(date(2026, 5, 31)) == ("spring", "spring-2026"))
check("Jun 1 starts summer", period(date(2026, 6, 1)) == ("summer", "summer-2026"))
check("Aug 31 is still summer", period(date(2026, 8, 31)) == ("summer", "summer-2026"))
check("Sep 1 starts autumn", period(date(2026, 9, 1)) == ("autumn", "autumn-2026"))
check("Nov 30 is still autumn", period(date(2026, 11, 30)) == ("autumn", "autumn-2026"))
check("Dec 1 starts winter", period(date(2026, 12, 1)) == ("winter", "winter-2026"))
check("a leap day is winter", period(date(2028, 2, 29))[0] == "winter")

# Winter is the season that spans the new year, so February must report the
# December that began it — otherwise the period id flips at midnight on Jan 1
# and the rotation fetches a second winter wallpaper for no reason.
check("January belongs to December's winter",
      period(date(2027, 1, 20)) == ("winter", "winter-2026"))
check("February belongs to December's winter",
      period(date(2027, 2, 28)) == ("winter", "winter-2026"))
check("Dec 31 and Jan 1 are the same winter",
      period(date(2026, 12, 3))[1] == period(date(2027, 1, 20))[1])

# ── the calendar: holiday windows ───────────────────────────────────────────
# A week before, through the day, through a week after — then back to the
# season. That is requirements 2 and 3, and the ±8 day checks are the ones
# that would catch an off-by-one in either direction.
halloween = date(2026, 10, 31)
check("8 days before halloween is still autumn",
      period(halloween - timedelta(days=8))[0] == "autumn")
check("7 days before halloween switches over",
      period(halloween - timedelta(days=7)) == ("halloween", "halloween-2026"))
check("halloween itself", period(halloween) == ("halloween", "halloween-2026"))
check("7 days after halloween is still halloween",
      period(halloween + timedelta(days=7))[0] == "halloween")
check("8 days after halloween is autumn again",
      period(halloween + timedelta(days=8))[0] == "autumn")

valentine = date(2027, 2, 14)
check("valentine's window opens", period(valentine - timedelta(days=7))[0] == "valentine")
check("valentine's window closes to winter",
      period(valentine + timedelta(days=8)) == ("winter", "winter-2026"))

# The winter holidays are one span, Dec 25 to Jan 7, so the window runs from
# Dec 18 to Jan 14 and New Year's Eve is inside it rather than between two.
check("Dec 17 is plain winter", period(date(2026, 12, 17))[0] == "winter")
check("Dec 18 opens the christmas window",
      period(date(2026, 12, 18)) == ("christmas", "christmas-2026"))
check("New Year's Eve is christmas", period(date(2026, 12, 31))[0] == "christmas")
check("Orthodox christmas is inside the same span",
      period(date(2027, 1, 7)) == ("christmas", "christmas-2026"))
check("Jan 14 is the last christmas day", period(date(2027, 1, 14))[0] == "christmas")
check("Jan 15 is winter again", period(date(2027, 1, 15))[0] == "winter")
check("the christmas id names the year it began",
      period(date(2027, 1, 2))[1] == "christmas-2026")

# ── the calendar: easter, the one that moves ────────────────────────────────
# Cross-checked against published tables, not recalled: 2025 is the year both
# rites coincide, 2024 the year they are five weeks apart.
check("western easter 2024", rw.easter_sunday(2024, "western") == date(2024, 3, 31))
check("western easter 2025", rw.easter_sunday(2025, "western") == date(2025, 4, 20))
check("western easter 2026", rw.easter_sunday(2026, "western") == date(2026, 4, 5))
check("western easter 2027", rw.easter_sunday(2027, "western") == date(2027, 3, 28))
check("orthodox easter 2024", rw.easter_sunday(2024, "orthodox") == date(2024, 5, 5))
check("orthodox easter 2025", rw.easter_sunday(2025, "orthodox") == date(2025, 4, 20))
check("orthodox easter 2026", rw.easter_sunday(2026, "orthodox") == date(2026, 4, 12))
check("orthodox easter 2027", rw.easter_sunday(2027, "orthodox") == date(2027, 5, 2))
check("the rites agree in 2025",
      rw.easter_sunday(2025, "western") == rw.easter_sunday(2025, "orthodox"))
check("orthodox easter 2027 is a period",
      period(date(2027, 5, 2), "orthodox") == ("easter", "easter-2027"))
check("the same day is plain spring on the western calendar",
      period(date(2027, 5, 2), "western")[0] == "spring")

# ── the calendar: the ids are what make it fire once a year ─────────────────
check("next year's halloween is a different period",
      period(date(2026, 10, 31))[1] != period(date(2027, 10, 31))[1])
check("but the same theme", period(date(2026, 10, 31))[0] == period(date(2027, 10, 31))[0])

# Walk four years a day at a time and record every switch. A season is
# interrupted by the holidays inside it and then resumes — winter-2026 runs
# christmas, back to winter, valentine, back to winter — and it resumes under
# the *same* id on purpose: that is requirement 3, and it is what makes the
# return trip reuse the wallpaper already downloaded instead of fetching a
# second winter.
seen, order, day = {}, [], date(2025, 1, 1)
while day < date(2029, 1, 1):
    theme, pid = period(day)
    if not order or order[-1] != pid:
        order.append(pid)
    seen.setdefault(pid, theme)
    day += timedelta(days=1)

check("every period id names its own theme",
      all(pid.startswith(theme + "-") for pid, theme in seen.items()))
check("four years produce every theme but 'all'",
      set(seen.values()) == {t[0] for t in rw.THEMES} - {"all"})
# Seasons follow seasons (spring into summer), but a holiday is always
# reached from a season and left back into one — two holidays running would
# mean one window swallowing another, and the ±7 days deciding it silently.
check("a holiday is always entered from a season and left into one",
      all(seen[a] in SEASON_THEMES or seen[b] in SEASON_THEMES
          for a, b in zip(order, order[1:])))
check("a holiday is never entered twice",
      len([p for p in order if seen[p] not in SEASON_THEMES])
      == len({p for p in order if seen[p] not in SEASON_THEMES}))
check("winter 2026 resumes under its own id after every holiday in it",
      [p for p in order if p == "winter-2026"] == ["winter-2026"] * 3)
check("each season is entered once a year",
      len([p for p in order if p == "summer-2026"]) == 1)

# ── the rotation acts once, and never undoes a wallpaper set by hand ────────
# The two calls run_auto makes outside the process are setting the wallpaper
# and asking what the wallpaper is. Standing a tiny fake shell in for both is
# what makes the tick testable offline — and it has to be both: with only
# set_wallpaper stubbed, the tick's check for a hand-picked wallpaper would
# ask the real Noctalia, get the real desktop's wallpaper, and latch itself
# off in the middle of every test below.
applied = []
screen = []          # what the fake shell is currently showing
real_set_wallpaper, real_wallpaper_now = rw.set_wallpaper, rw.wallpaper_now


def fake_set(path):
    applied.append(Path(path))
    screen[:] = [Path(path)]


def fake_get():
    return screen[0] if screen else None


rw.set_wallpaper, rw.wallpaper_now = fake_set, fake_get

auto_prefs = dict(rw.DEFAULTS, theme="all")
theme_now, period_now = rw.current_period(date.today(), auto_prefs["easter"])

# A wallpaper already in place for today's period: no download, no network.
rw.AUTO_DIR.mkdir(parents=True, exist_ok=True)
prepared = rw.AUTO_DIR / f"{period_now}.jpg"
prepared.write_bytes(b"not really a jpeg")
check("the period's wallpaper is found without downloading",
      rw.period_wallpaper(period_now) == prepared)

lines = []
check("first tick applies", rw.run_auto(auto_prefs, log=lines.append) == 0)
check("first tick set the wallpaper", applied == [prepared])
check("first tick recorded the period", rw.load_state()["period"] == period_now)
check("first tick recorded the theme", rw.load_state()["theme"] == theme_now)

check("second tick is a no-op", rw.run_auto(auto_prefs, log=lines.append) == 0)
check("second tick set nothing", len(applied) == 1)
check("--force acts anyway", rw.run_auto(auto_prefs, force=True, log=lines.append) == 0)
check("--force set it again", len(applied) == 2)

# ── the latch ───────────────────────────────────────────────────────────────
# "When I set my own wallpaper the rotation switches itself off, and nothing
# changes the wallpaper again until I switch it back on." Everything in this
# block is that sentence.
state_before = rw.STATE_FILE.read_text()
unrelated = rw.SAVE_DIR / "something-i-picked-myself.jpg"
rw.SAVE_DIR.mkdir(parents=True, exist_ok=True)
unrelated.write_bytes(b"mine")
rw.set_wallpaper(unrelated)          # a wallpaper chosen from anywhere at all
check("a hand-set wallpaper leaves the rotation's own record alone",
      rw.STATE_FILE.read_text() == state_before)

before_count = len(applied)
check("the next tick notices and switches the rotation off",
      rw.run_auto(auto_prefs, log=lines.append) == 0
      and auto_prefs["auto_enabled"] is False)
check("the tick that noticed changed no wallpaper", len(applied) == before_count)
check("the hand-set wallpaper is the one still on screen", fake_get() == unrelated)
check("and every later tick keeps its hands off",
      rw.run_auto(auto_prefs, log=lines.append) == 0
      and len(applied) == before_count and fake_get() == unrelated)
check("the latch is written through, not just held in memory",
      json.loads(rw.CONFIG_FILE.read_text())["auto_enabled"] is False)

# Turning it back on is the consent the latch was waiting for, so it applies
# at once instead of waiting for the next boundary.
check("resuming reports success", rw.resume_auto(auto_prefs, log=lines.append) == 0)
check("resuming switches it back on", auto_prefs["auto_enabled"] is True)
check("resuming puts the period's wallpaper up straight away",
      len(applied) == before_count + 1 and fake_get() == prepared)
check("resuming keeps the recorded period rather than clearing it",
      rw.load_state()["period"] == period_now)

# An unreachable shell answers "do not know", and that must never be read as
# a hand-set wallpaper — one restart of Noctalia would otherwise disable the
# rotation for good, with nothing on screen to explain why.
rw.wallpaper_now = lambda: None
check("an unreachable shell does not latch",
      rw.run_auto(auto_prefs, log=lines.append) == 0
      and auto_prefs["auto_enabled"] is True)
rw.wallpaper_now = fake_get

# The hardlink every save makes into ~/Pictures/Wallpapers means one image
# answers to two paths. Noctalia reporting the other one is not a stranger.
twin = rw.pictures_wallpapers() / "twin-of-the-applied-one.jpg"
twin.parent.mkdir(parents=True, exist_ok=True)
twin.unlink(missing_ok=True)
os.link(prepared, twin)
screen[:] = [twin]
check("the same file under its other name is not a hand-set wallpaper",
      not rw.wallpaper_was_changed_by_hand(rw.load_state()))
screen[:] = [prepared]

# Switched off, the tick is inert but still knows what day it is.
off = dict(auto_prefs, auto_enabled=False)
rw.STATE_FILE.unlink()
check("a disabled rotation applies nothing",
      rw.run_auto(off, log=lines.append) == 0 and len(applied) == before_count + 1)
check("a disabled rotation records nothing", not rw.STATE_FILE.exists())
check("--force overrides being switched off",
      rw.run_auto(off, force=True, log=lines.append) == 0
      and len(applied) == before_count + 2)

# A tick that cannot reach the shell must not record the period, or the season
# it failed to apply is skipped until next year.
rw.STATE_FILE.unlink()
auto_prefs["auto_enabled"] = True
def refuse(path):
    raise OSError("noctalia is not running")
rw.set_wallpaper = refuse
check("a failed apply reports failure", rw.run_auto(auto_prefs, log=lines.append) == 1)
check("a failed apply records nothing", not rw.STATE_FILE.exists())
check("but keeps the file for the retry", prepared.exists())
rw.set_wallpaper = fake_set
check("the retry succeeds", rw.run_auto(auto_prefs, log=lines.append) == 0)
check("the retry recorded the period", rw.load_state()["period"] == period_now)

# ── per-category pools ──────────────────────────────────────────────────────
# "For each category let me choose which wallpapers get set when its turn
# comes." A directory per category; what is in it wins over downloading.
check("a category with nothing chosen has an empty pool",
      rw.pool_images("halloween") == [])
check("the pool directory is named after the category",
      rw.theme_pool("halloween") == rw.SAVE_DIR / "halloween")
check("'all' is not a category and never has a pool", rw.pool_images("all") == [])

pool = rw.theme_pool("halloween"); pool.mkdir(parents=True, exist_ok=True)
mine = pool / "the-one-i-want.jpg"; mine.write_bytes(b"pumpkin")
(pool / "notes.txt").write_bytes(b"not an image")
check("only images count as chosen", rw.pool_images("halloween") == [mine])

chosen = rw.fetch_for_period(dict(rw.DEFAULTS), "halloween", "halloween-2026")
check("a category's turn uses what was chosen, not a download", chosen == mine)
check("and downloads nothing into the rotation's own directory",
      not list(rw.AUTO_DIR.glob("halloween-2026.*")))

second = pool / "and-this-one-too.png"; second.write_bytes(b"bats")
picks = {rw.fetch_for_period(dict(rw.DEFAULTS), "halloween", "halloween-2026")
         for _ in range(40)}
check("with several chosen, it draws from all of them", picks == {mine, second})

# A pool is the user's own directory; the pruning of downloaded wallpapers
# must not reach into it.
rw.prune_auto(keep=0)
check("pruning downloads never touches a category's pool",
      mine.exists() and second.exists())

# The rotation's files are its own: SAVE_DIR is what the user chose to keep.
check("auto wallpapers live outside SAVE_DIR",
      rw.SAVE_DIR not in rw.AUTO_DIR.parents and rw.AUTO_DIR != rw.SAVE_DIR)
check("the tick added nothing to SAVE_DIR",
      [p.name for p in rw.SAVE_DIR.iterdir() if p.is_file()] == [unrelated.name])

# ── the library listing ─────────────────────────────────────────────────────
# What the Downloaded tab shows. scan() is a staticmethod precisely so this
# can be checked without a window.
scan = LibraryPage.scan

kept = rw.SAVE_DIR / "kept-one.png"; kept.write_bytes(b"x")
listed = dict(scan())
check("a kept wallpaper is listed", kept in listed)
check("and carries no category yet", listed[kept] == set())

# Pinning hardlinks it into the category. The same picture under two names is
# one wallpaper, not two, or pinning would look like it duplicated the file.
hpool = rw.theme_pool("halloween"); hpool.mkdir(parents=True, exist_ok=True)
os.link(kept, hpool / "kept-one.png")
listed = dict(scan())
check("pinning does not add a second tile",
      [p for p in listed if p.name == "kept-one.png"] == [kept])
check("the tile is tagged with its category", listed[kept] == {"halloween"})

wpool = rw.theme_pool("winter"); wpool.mkdir(parents=True, exist_ok=True)
os.link(kept, wpool / "kept-one.png")
listed = dict(scan())
check("a wallpaper can belong to several categories",
      listed[kept] == {"halloween", "winter"})

# Only SAVE_DIR's own files and the eight category directories. A stray tree
# under SAVE_DIR is not a wallpaper collection.
stray = rw.SAVE_DIR / "Pictures" / "Wallpapers"
stray.mkdir(parents=True, exist_ok=True)
(stray / "not-mine.png").write_bytes(b"x")
check("a stray subdirectory is not scanned",
      not any("not-mine" in p.name for p in dict(scan())))
(rw.SAVE_DIR / "notes.txt").write_bytes(b"x")
check("non-images are not listed",
      not any(p.suffix == ".txt" for p in dict(scan())))


# Old periods are pruned, recent ones kept so a revisit costs no download.
# The applied one is spared whatever its age — and age alone would pick it,
# because it is the oldest file here by the time the newer ones are written.
# Deleting it would not self-correct: the state file still names its period as
# applied, so no tick refetches it and the wallpaper on screen is a file that
# is gone.
os.utime(prepared, (0, 0))
for i in range(rw.AUTO_KEEP + 3):
    (rw.AUTO_DIR / f"winter-20{10 + i}.jpg").write_bytes(b"old")
rw.prune_auto()
check("prune keeps AUTO_KEEP wallpapers besides the applied one",
      len(list(rw.AUTO_DIR.glob("*"))) == rw.AUTO_KEEP + 1)
check("prune never deletes the wallpaper currently applied", prepared.exists())
check("the applied wallpaper is the oldest file, so age alone would have taken it",
      prepared == min(rw.AUTO_DIR.glob("*"), key=lambda f: f.stat().st_mtime))
check("the state still points at a file that exists",
      Path(rw.load_state()["path"]).exists())

rw.set_wallpaper, rw.wallpaper_now = real_set_wallpaper, real_wallpaper_now

# ── API answers are cached for a day ────────────────────────────────────────
import time as _time

feed = "https://konachan.net/post.json?tags=rating%3Asafe&limit=1&page=1"
first = rw._get_json(feed)
check("a live answer came back", isinstance(first, list))
slot = next(rw.API_CACHE_DIR.glob("*.json"))
check("API answer cached on disk", slot.is_file())
slot.write_text(json.dumps({"marker": "from-cache"}))
check("a cached answer is served without a request",
      rw._get_json(feed) == {"marker": "from-cache"})
check("an expired entry is refetched",
      rw._get_json(feed, ttl=0) != {"marker": "from-cache"})
_time.sleep(0)
os.utime(slot, (0, 0))
rw.prune_cache()
check("prune drops expired API answers", not slot.exists())
check("the URL is never written to disk — it carries the key",
      all("key=" not in p.read_text() for p in rw.API_CACHE_DIR.glob("*.json")))

# ── a real download per source, then the save path ──────────────────────────
saved = []
for label, key, _ in rw.SOURCES:
    frame = rw.download(dict(rw.DEFAULTS, source=key))
    cached = frame["path"]
    check(f"{label}: download landed in cache",
          cached.exists() and cached.parent == rw.CACHE_DIR)
    check(f"{label}: honours the size filter",
          rw._fits(rw.DEFAULTS, frame.get("width"), frame.get("height")))

    rw.SAVE_DIR.mkdir(parents=True, exist_ok=True)
    dest = rw.unique_path(rw.SAVE_DIR, frame["name"], frame["ext"])
    shutil.move(str(cached), dest)
    saved.append(dest)
    check(f"{label}: saved file intact", dest.stat().st_size == frame["bytes"])
    check(f"{label}: cache file gone after save", not cached.exists())

check("SAVE_DIR created on demand", rw.SAVE_DIR.is_dir())

# ── wallhaven works without a key; the key only lifts the rate limit ────────
anon = rw.pick_wallhaven(dict(rw.DEFAULTS, source="wallhaven", wallhaven_apikey=""))
check("wallhaven works without a key", anon["url"].startswith("http"))

# ── collision branch: the whole point ───────────────────────────────────────
precious = rw.SAVE_DIR / "konachan-1.jpg"
precious.write_bytes(b"PRECIOUS")
p2 = rw.unique_path(rw.SAVE_DIR, "konachan-1", ".jpg"); p2.write_bytes(b"second")
p3 = rw.unique_path(rw.SAVE_DIR, "konachan-1", ".jpg"); p3.write_bytes(b"third")
check("collision -> -2", p2.name == "konachan-1-2.jpg")
check("collision -> -3", p3.name == "konachan-1-3.jpg")
check("earlier file untouched", precious.read_bytes() == b"PRECIOUS")

# ── hardlink into Pictures/Wallpapers ───────────────────────────────────────
pics = rw.pictures_wallpapers()
pics.mkdir(parents=True, exist_ok=True)
link = rw.unique_path(pics, saved[0].stem, saved[0].suffix)
os.link(saved[0], link)
check("hardlink shares the inode", link.stat().st_ino == saved[0].stat().st_ino)

# ── delete removes only the pending download ────────────────────────────────
before = sorted(p.name for p in rw.SAVE_DIR.iterdir())
doomed = rw.download(dict(rw.DEFAULTS))
doomed["path"].unlink()
check("delete removed the pending file", not doomed["path"].exists())
check("delete kept every saved file",
      sorted(p.name for p in rw.SAVE_DIR.iterdir()) == before)

# ── cache prune ─────────────────────────────────────────────────────────────
orphan = rw.CACHE_DIR / "pending-orphan.jpg"; orphan.write_bytes(b"x")
keep = rw.CACHE_DIR / "keepme.txt"; keep.write_bytes(b"x")
rw.prune_cache()
check("prune removed the orphan", not orphan.exists())
check("prune left unrelated files", keep.exists())

# ── the nightly re-draw ─────────────────────────────────────────────────────
# Inside one period, a category with several wallpapers pinned to it draws a
# fresh one each midnight. run_auto takes `today` so this needs no clock.
rw.set_wallpaper, rw.wallpaper_now = fake_set, fake_get   # the fake shell again


def same(a, b):
    try:
        return a.samefile(b)
    except OSError:
        return False

draw_prefs = dict(rw.DEFAULTS, theme="all", auto_enabled=True)
day1 = date(2026, 12, 26)          # inside christmas-2026
day2 = date(2026, 12, 27)
theme1, period1 = rw.current_period(day1, "orthodox")
check("the test days are one period", period1 == rw.current_period(day2, "orthodox")[1])

xmas = rw.theme_pool(theme1); xmas.mkdir(parents=True, exist_ok=True)
for f in xmas.iterdir():
    f.unlink()
pinned = []
for n in range(4):
    f = xmas / f"pinned-{n}.png"; f.write_bytes(bytes([n]))
    pinned.append(f)

rw.STATE_FILE.unlink(missing_ok=True)
applied.clear(); screen.clear()
check("first tick of the period applies",
      rw.run_auto(draw_prefs, log=lines.append, today=day1) == 0
      and len(applied) == 1)
check("it applied something pinned to the category", applied[-1] in pinned)
check("the day is recorded", rw.load_state()["day"] == day1.isoformat())

check("a second tick the same day does nothing",
      rw.run_auto(draw_prefs, log=lines.append, today=day1) == 0
      and len(applied) == 1)

first = applied[-1]
check("the next day draws again",
      rw.run_auto(draw_prefs, log=lines.append, today=day2) == 0
      and len(applied) == 2)
check("and draws a different one", applied[-1] != first)
check("the period is unchanged by a re-draw",
      rw.load_state()["period"] == period1)
check("the new day is recorded", rw.load_state()["day"] == day2.isoformat())
check("a second tick on the new day does nothing",
      rw.run_auto(draw_prefs, log=lines.append, today=day2) == 0
      and len(applied) == 2)

# Over many days every pinned wallpaper should come up, and never twice in a
# row — with four pinned, "random" that repeats is indistinguishable from a
# rotation that is not happening.
seen, previous, last_day = set(), applied[-1], day2
repeats = 0
for i in range(3, 16):
    day = date(2026, 12, 26) + timedelta(days=i)
    if rw.current_period(day, "orthodox")[1] != period1:
        break
    last_day = day
    rw.run_auto(draw_prefs, log=lines.append, today=day)
    if applied[-1] == previous:
        repeats += 1
    previous = applied[-1]
    seen.add(applied[-1])
check("every pinned wallpaper comes up over the period", seen == set(pinned))
check("and never the same one two nights running", repeats == 0)

# Deleting the wallpaper that is currently up — from the Downloaded tab, or
# with a file manager — is tidying up, not choosing a different wallpaper. The
# rotation must draw again rather than switch itself off.
live = Path(rw.load_state()["path"])
live.unlink()
before = len(applied)
check("a deleted wallpaper is not read as a hand-set one",
      not rw.wallpaper_was_changed_by_hand(rw.load_state()))
check("the rotation replaces it instead of stopping",
      rw.run_auto(draw_prefs, log=lines.append, today=last_day) == 0
      and len(applied) == before + 1
      and draw_prefs["auto_enabled"] is True)
check("and the replacement is one that still exists", applied[-1].exists())

# One pinned wallpaper is nothing to draw between: the day is recorded so the
# question is not re-asked every hour, but the wallpaper is left alone.
for f in pinned:
    if f.exists() and not same(f, applied[-1]):
        f.unlink()
before = len(applied)
check("a single pinned wallpaper is not redrawn",
      rw.run_auto(draw_prefs, log=lines.append,
                  today=last_day + timedelta(days=1)) == 0
      and len(applied) == before)
check("but the day is still recorded",
      rw.load_state()["day"] == (last_day + timedelta(days=1)).isoformat())

# The latch outranks the nightly draw: a wallpaper set by hand stops it.
screen[:] = [unrelated]
check("a hand-set wallpaper stops the nightly draw too",
      rw.run_auto(draw_prefs, log=lines.append,
                  today=last_day + timedelta(days=2)) == 0
      and len(applied) == before
      and draw_prefs["auto_enabled"] is False)

shutil.rmtree(FAKE, ignore_errors=True)
print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
