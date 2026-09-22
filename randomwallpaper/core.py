"""A reel of random wallpapers: keep the ones you want, drop the rest.

This is the platform-independent half of the app — themes, the calendar,
preferences, the two image sources, and the calendar rotation. It has no
import on Qt or on any particular desktop: everything that has to speak to
one OS or the other goes through `randomwallpaper.desktop`, and everything
above this module is UI.

Downloads land in a cache directory and are only ever moved into SAVE_DIR when
you press Save, under a name that does not exist yet. Delete unlinks the cached
file and touches nothing else, so no wallpaper you already kept can be damaged
by anything this app does.

A reel can be narrowed to a theme — a season or a holiday — and `--auto` turns
that into a rotation that follows the calendar on its own: the season when it
begins, the holiday from a week before it to a week after, the season again
once that week is over. It decides purely from the date and from the period it
last acted on, never from what is currently on screen, so a wallpaper you set
by hand yourself is left alone until the next boundary.
"""
import hashlib
import http.client
import json
import os
import random
import shutil
import string
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

from . import desktop
from .paths import (
    API_CACHE_DIR, AUTO_DIR, CACHE_DIR, CONFIG_DIR, CONFIG_FILE, SAVE_DIR,
    STATE_DIR, STATE_FILE,
)

API_CACHE_TTL = 24 * 60 * 60   # Both APIs are asked for a random page or a
                               # random seed, so an identical URL is the rare
                               # case; this only spares them a repeat of the
                               # handful of requests that really are identical
                               # — konachan's tag counts, above all.
AUTO_KEEP = 4          # past periods' wallpapers kept before pruning

# Konachan rejects the default urllib agent.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)

TIMEOUT = 30
REEL_AHEAD = 6          # frames kept downloaded ahead of the current one
# A themed pool can be small — wallhaven has under a hundred Easter wallpapers
# — and then two random picks land on the same image often enough to notice.
# Duplicates are dropped and refetched, but only so many times before the reel
# is simply allowed to stay short: past this, the pool really is exhausted.
MAX_DUPLICATE_RETRIES = 10
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")

ORIENTATIONS = [
    ("Any", "any"),
    ("Landscape", "landscape"),
    ("Portrait", "portrait"),
]

MINIMUMS = [
    ("Any size", ""),
    ("1920×1080", "1920x1080"),
    ("2560×1440", "2560x1440"),
    ("3840×2160", "3840x2160"),
]

DEFAULTS = {
    "source": "konachan",
    "theme": "all",
    "orientation": "any",
    "minimum": "1920x1080",
    "wallhaven_general": True,
    "wallhaven_anime": True,
    "wallhaven_people": False,
    "wallhaven_apikey": "",
    "set_on_save": True,
    "auto_enabled": True,
    "easter": "orthodox",
}

# ── themes ──────────────────────────────────────────────────────────────────
# A theme is a season or a holiday, and each source is told about it in its own
# language: konachan by a tag, wallhaven by a search query.
#
# Every entry below was checked against the live APIs rather than guessed, and
# a source only gets a term here if it really has images under it. Konachan has
# no `easter` tag and no `new_year` tag at all — both return zero posts — so
# those sit as None and download() borrows wallhaven for them; asking konachan
# would return an empty reel forever with no way for the user to tell why.
#
# Skipped on the same evidence: 8 марта, 23 февраля and 9 мая have no tag on
# konachan and nothing findable on wallhaven, so a "theme" for them would just
# be the unfiltered catalogue wearing a holiday label.
THEMES = [
    # key          label                    konachan tag  wallhaven queries
    ("all",        "Everything",            None,         []),
    ("spring",     "Spring",                "spring",     ["spring"]),
    ("summer",     "Summer",                "summer",     ["summer"]),
    ("autumn",     "Autumn",                "autumn",     ["autumn"]),
    ("winter",     "Winter",                "winter",     ["winter"]),
    ("halloween",  "Halloween",             "halloween",  ["halloween"]),
    # One theme for the whole winter-holiday stretch: konachan files New Year
    # art under `christmas` too, and the pictures are interchangeable anyway.
    ("christmas",  "Christmas / New Year",  "christmas",  ["christmas", "new year"]),
    ("valentine",  "Valentine's Day",       "valentine",  ["valentine"]),
    ("easter",     "Easter",                None,         ["easter", "easter eggs"]),
]

# ── the calendar ────────────────────────────────────────────────────────────
# Meteorological seasons — whole months, northern hemisphere — because that is
# what "лето началось" means in conversation, and because an astronomical
# boundary that moves by a day each year buys nothing for a wallpaper.
SEASON_BY_MONTH = {
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "autumn", 10: "autumn", 11: "autumn",
    12: "winter", 1: "winter", 2: "winter",
}

HOLIDAY_WINDOW = 7     # days of lead-in before a holiday and of afterglow after


class FetchError(Exception):
    """Anything that means "no usable image this time" — always shown to the
    user verbatim, never swallowed."""


def theme_entry(key):
    for entry in THEMES:
        if entry[0] == key:
            return entry
    return THEMES[0]          # an unknown theme is no theme, not an error


def theme_index(key):
    for i, entry in enumerate(THEMES):
        if entry[0] == key:
            return i
    return 0


def theme_label(key):
    return theme_entry(key)[1]


def theme_key(prefs):
    """The theme actually in force, normalised through THEMES.

    Everything that acts on a theme goes through here rather than reading
    prefs["theme"] raw, so a key this version does not know — a config written
    by a later one, or a theme since dropped — degrades to "all" everywhere at
    once instead of being no-theme in one place and an impossible fetch in the
    next.
    """
    return theme_entry(prefs.get("theme", "all"))[0]


def theme_pool(theme):
    """The directory holding the wallpapers chosen for this category.

    One per category, named after it, directly under SAVE_DIR — so choosing
    what Halloween looks like is dropping files into ~/random_wallpaper/
    halloween, with a file manager or with the Pin button, and looking at what
    you chose is opening that folder. No index, no database: the directory
    listing is the setting.
    """
    return SAVE_DIR / theme


def pool_images(theme):
    """What has been chosen for this category, oldest name first."""
    if theme == "all":
        return []          # "everything" is the absence of a category
    try:
        return sorted(p for p in theme_pool(theme).iterdir()
                      if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    except OSError:
        return []          # no directory yet is simply nothing chosen


def source_serves(source, theme):
    """Whether this source has anything at all under this theme.

    Not a filter question — a catalogue one. "all" is served by everyone; the
    rest depend on the terms in THEMES, and a source with none would return an
    empty reel rather than a narrower one.
    """
    key, _, konachan_tag, wallhaven_queries = theme_entry(theme)
    if key == "all":
        return True
    return bool(konachan_tag) if source == "konachan" else bool(wallhaven_queries)


def easter_sunday(year, rite="orthodox"):
    """Easter is the only holiday here that moves, and it moves differently for
    the two rites — up to five weeks apart, as in 2024 (31 March / 5 May).

    Western: the anonymous Gregorian computus. Orthodox: the Julian computus,
    then the 13-day offset that converts a Julian date to a Gregorian one for
    every year from 1900 to 2099 — which outlives any machine this runs on.
    """
    if rite == "western":
        a = year % 19
        b, c = divmod(year, 100)
        d, e = divmod(b, 4)
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i, k = divmod(c, 4)
        l = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l) // 451
        month, day = divmod(h + l - 7 * m + 114, 31)
        return date(year, month, day + 1)

    d = (19 * (year % 19) + 15) % 30
    e = (2 * (year % 4) + 4 * (year % 7) - d + 34) % 7
    month, day = divmod(d + e + 114, 31)
    return date(year, month, day + 1) + timedelta(days=13)


def holiday_spans(year, rite="orthodox"):
    """The holidays anchored in `year`, each as the stretch it actually covers.

    A span rather than a single day, because the winter one is not a day: the
    25th, New Year's Eve and the Orthodox Christmas on the 7th sit inside two
    weeks that want the same wallpapers. Note it ends in `year + 1` — the
    caller has to consider the previous year's spans as well, which is why
    current_period() sweeps three years.
    """
    easter = easter_sunday(year, rite)
    return [
        ("valentine", date(year, 2, 14), date(year, 2, 14)),
        ("easter", easter, easter),
        ("halloween", date(year, 10, 31), date(year, 10, 31)),
        ("christmas", date(year, 12, 25), date(year + 1, 1, 7)),
    ]


def season_period(day):
    """The season and the year that names this occurrence of it. Winter is the
    awkward one: December belongs to the winter that January and February will
    finish, so all three report the December year."""
    key = SEASON_BY_MONTH[day.month]
    year = day.year - 1 if key == "winter" and day.month != 12 else day.year
    return key, f"{key}-{year}"


def current_period(day=None, rite="orthodox"):
    """Which theme `day` belongs to, and the id naming this occurrence of it.

    A holiday outranks the season it falls in, from HOLIDAY_WINDOW days before
    its span to the same number after — that is requirements 2 and 3 in one
    comparison. Everything else is the season, which is requirement 1, and the
    fallback that requirement 3 falls back *to*.

    The id carries the year the period began ("winter-2026", "christmas-2026"),
    so next year's Halloween is a different period from this year's and fires
    again instead of looking already applied.
    """
    day = day or date.today()
    best = None
    # Three years, because a span can start in the previous one (Christmas
    # reaching into January) or in the next (its lead-in starting in December).
    for year in (day.year - 1, day.year, day.year + 1):
        for key, start, end in holiday_spans(year, rite):
            if not (start - timedelta(days=HOLIDAY_WINDOW)
                    <= day <= end + timedelta(days=HOLIDAY_WINDOW)):
                continue
            # Distance to the holiday itself, so overlapping windows are
            # settled by which holiday is nearer rather than by list order.
            if start <= day <= end:
                distance = 0
            else:
                distance = min(abs((day - start).days), abs((day - end).days))
            if best is None or distance < best[0]:
                best = (distance, key, f"{key}-{start.year}")
    if best:
        return best[1], best[2]
    return season_period(day)


# ── preferences ─────────────────────────────────────────────────────────────
def load_prefs():
    prefs = dict(DEFAULTS)
    try:
        stored = json.loads(CONFIG_FILE.read_text())
    except (OSError, ValueError):
        return prefs
    # Only known keys: a config written by an older version still carries
    # "rating", which nothing reads any more.
    prefs.update({k: v for k, v in stored.items() if k in DEFAULTS})
    return prefs


def save_prefs(prefs):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(prefs, indent=2, sort_keys=True) + "\n")
        CONFIG_FILE.chmod(0o600)   # it can hold a wallhaven API key
    except OSError:
        pass


def wallhaven_key(prefs):
    """Environment first, so the key can live outside a config file."""
    return os.environ.get("WALLHAVEN_API_KEY", "").strip() or prefs["wallhaven_apikey"].strip()


# ── sources ─────────────────────────────────────────────────────────────────
def _get(url, attempts=3):
    """Konachan serves originals, some of them 30 MB, and truncates the response
    often enough that a single try is not good enough — IncompleteRead on the
    last few hundred KB. Retry before surfacing it."""
    last = None
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read()
        except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
            last = exc
    raise last


def _get_json(url, ttl=API_CACHE_TTL):
    """Answers are cached on disk by URL for a day.

    This is safe only because no two requests for images share a URL: konachan
    is asked for a random page and wallhaven for a random seed. Drop either and
    the cache turns into a bug — the same 24 wallpapers, all day. What it is
    really for is the requests that *are* repeats, konachan's tag counts above
    all, which are asked for on every themed fetch and change by the week.

    Only the parsed answer is stored, never the URL: it carries the API key.
    """
    slot = API_CACHE_DIR / (hashlib.sha256(url.encode()).hexdigest() + ".json")
    try:
        # max(0, ...): a file just written can report an mtime a hair ahead
        # of time.time() — clock/filesystem timestamp rounding, seen in
        # practice on Windows CI runners — which would otherwise make age
        # negative and "age < ttl" true for *any* ttl, including 0. Clamping
        # age at 0 is what keeps ttl=0 actually mean "always stale" rather
        # than occasionally serving a cache entry that is seconds old.
        age = max(0.0, time.time() - slot.stat().st_mtime)
        if age < ttl:
            return json.loads(slot.read_text())
    except (OSError, ValueError):
        pass          # missing, unreadable or half-written: just fetch it

    parsed = json.loads(_get(url))
    try:
        API_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=API_CACHE_DIR, suffix=".part")
        with os.fdopen(fd, "w") as fh:
            json.dump(parsed, fh)
        os.replace(tmp, slot)          # atomic: a reader never sees a partial
    except (OSError, ValueError):
        pass          # an uncacheable answer is still a usable one
    return parsed


def _min_size(prefs):
    if not prefs["minimum"]:
        return 0, 0
    w, _, h = prefs["minimum"].partition("x")
    return int(w), int(h)


def _fits(prefs, width, height):
    if not (width and height):
        return True          # unknown dimensions: let it through, judge by eye
    min_w, min_h = _min_size(prefs)
    if width < min_w or height < min_h:
        return False
    if prefs["orientation"] == "landscape" and width < height:
        return False
    if prefs["orientation"] == "portrait" and height < width:
        return False
    return True


KONACHAN_HOST = "konachan.net"
KONACHAN_PER_PAGE = 40
KONACHAN_MAX_PAGE = 200     # the untagged catalogue is far deeper than this;
                            # 200 pages of 40 is already a pool of 8000


def _konachan_pages(tag):
    """How many pages a tag actually has, so the random jump lands on one.

    Without this the themed reel breaks in the most confusing way possible: a
    fixed 1..200 jump over `christmas`, which is 90 pages, comes back empty
    three times in four, and over a thinner tag almost always. The count comes
    from the tag index and is cached for the day like every other answer — it
    moves by a handful of posts a week.
    """
    if not tag:
        return KONACHAN_MAX_PAGE
    url = (f"https://{KONACHAN_HOST}/tag.json?"
           + urllib.parse.urlencode({"name": tag, "order": "count", "limit": 50}))
    try:
        # A pattern match, not a lookup: `christmas` also returns
        # `guilty_crown_lost_christmas`. Only the exact name counts.
        count = next(t["count"] for t in _get_json(url) if t.get("name") == tag)
    except (StopIteration, ValueError, KeyError, TypeError,
            urllib.error.URLError, http.client.HTTPException, OSError):
        return 1          # unknown depth: page 1 always exists
    return max(1, min(KONACHAN_MAX_PAGE, -(-count // KONACHAN_PER_PAGE)))


def pick_konachan(prefs):
    """konachan.net indexes safe posts only, which is the whole catalogue this
    app offers — .com and the ratings above Safe are deliberately not wired up.

    The API has no random endpoint, so we jump to a random page and filter
    locally — hence limit=40 rather than 1.
    """
    theme = theme_key(prefs)
    tag = theme_entry(theme)[2]
    if theme != "all" and not tag:
        raise FetchError(
            f"konachan has no {theme_label(theme)} posts — that theme is "
            "wallhaven's"
        )

    # rating:safe stays in front of the theme tag, never instead of it.
    tags = f"rating:safe {tag}" if tag else "rating:safe"

    def fetch(page):
        return _get_json(
            f"https://{KONACHAN_HOST}/post.json?tags={urllib.parse.quote(tags)}"
            f"&limit={KONACHAN_PER_PAGE}&page={page}"
        )

    pages = _konachan_pages(tag)
    # Two tries at a page worth using. The last page of a tag is a partial one
    # — `winter` ends on three posts — and under a size filter a partial page
    # is very often a page with nothing on it. Page 1 is full by construction
    # and is the page a non-empty tag is guaranteed to still have, so it is
    # what the second try falls back to.
    attempts = [random.randint(1, pages)]
    if pages > 1:
        attempts.append(1)

    page = attempts[0]
    posts = usable = []
    for page in attempts:
        posts = fetch(page)
        usable = [p for p in posts if p.get("file_url")
                  and _fits(prefs, p.get("width"), p.get("height"))]
        if usable:
            break

    if not posts:
        raise FetchError(f"konachan page {page} came back empty — try again")
    if not usable:
        raise FetchError(
            f"none of the {len(posts)} posts on page {page} match the size and "
            "orientation filters"
        )

    post = random.choice(usable)
    file_url = post["file_url"]
    if file_url.startswith("//"):
        file_url = "https:" + file_url
    return {
        "url": file_url,
        "name": f"konachan-{post.get('id', 'x')}",
        "width": post.get("width"),
        "height": post.get("height"),
        "credit": post.get("author") or KONACHAN_HOST,
        "source": "Konachan",
    }


def pick_wallhaven(prefs):
    categories = "".join(
        "1" if prefs[k] else "0"
        for k in ("wallhaven_general", "wallhaven_anime", "wallhaven_people")
    )
    if categories == "000":
        raise FetchError("every wallhaven category is switched off")

    key = wallhaven_key(prefs)

    params = {
        "sorting": "random",
        "purity": "100",
        "categories": categories,
        # sorting=random is seeded server-side, and without a seed of our own
        # the URL is byte-identical from one run to the next — which _get_json
        # would then answer out of the day-old cache, pinning the reel to the
        # same 24 wallpapers until tomorrow. A fresh seed makes every request a
        # distinct URL, so the cache can only ever help and never repeat us.
        "seed": "".join(random.choices(string.ascii_letters + string.digits, k=8)),
    }
    queries = theme_entry(theme_key(prefs))[3]
    if queries:
        # Several per theme where the site files the same occasion under more
        # than one word — "christmas" and "new year" are different pictures.
        params["q"] = random.choice(queries)
    if prefs["minimum"]:
        params["atleast"] = prefs["minimum"]
    if prefs["orientation"] == "landscape":
        params["ratios"] = "16x9,16x10,21x9"
    elif prefs["orientation"] == "portrait":
        params["ratios"] = "9x16,10x16,9x18"
    if key:
        params["apikey"] = key

    url = "https://wallhaven.cc/api/v1/search?" + urllib.parse.urlencode(params)
    posts = _get_json(url).get("data") or []
    posts = [p for p in posts if p.get("path")]
    if not posts:
        theme = theme_key(prefs)
        if theme != "all":
            raise FetchError(
                f"wallhaven has no {theme_label(theme)} wallpaper at this size "
                "— the themed pools are small, try Any size"
            )
        raise FetchError("wallhaven returned nothing for these filters")

    post = random.choice(posts)
    return {
        "url": post["path"],
        "name": f"wallhaven-{post.get('id', 'x')}",
        "width": post.get("dimension_x"),
        "height": post.get("dimension_y"),
        "credit": post.get("uploader", {}).get("username") or "wallhaven.cc",
        "source": "Wallhaven",
    }


# The osu! seasonal-backgrounds endpoint the old shell script used now answers
# 403 — it went behind OAuth — so wallhaven takes its place as second source.
# Pixabay was the third and is gone: two catalogues that both answer a themed
# query are worth more than a third that answers none of them.
SOURCES = [
    ("Konachan", "konachan", pick_konachan),
    ("Wallhaven", "wallhaven", pick_wallhaven),
]


def source_index(name):
    for i, (_, key, _) in enumerate(SOURCES):
        if key == name:
            return i
    return 0


def source_key(name):
    """The name normalised to one that exists. A config left over from when
    there was a third source still says "pixabay"; every caller has to agree
    on what that means now, and index 0 is what source_index() already gives
    them."""
    return SOURCES[source_index(name)][1]


def effective_source(prefs):
    """The source a fetch will really use.

    Normally the one you chose. The exception is a theme the chosen source has
    nothing under — Easter on konachan — where borrowing the other one beats
    handing back an empty reel, and beats it especially for --auto, which has
    nobody to tell. Nothing is hidden by this: every frame names its source.
    """
    chosen = source_key(prefs["source"])
    theme = theme_key(prefs)
    if source_serves(chosen, theme):
        return chosen
    return next((key for _, key, _ in SOURCES if source_serves(key, theme)),
                chosen)


def download(prefs):
    """Runs off the main thread. Returns a frame: metadata plus a cached file."""
    meta = SOURCES[source_index(effective_source(prefs))][2](prefs)

    ext = Path(urllib.parse.urlparse(meta["url"]).path).suffix.lower()
    if ext not in IMAGE_EXTS:
        ext = ".jpg"

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, prefix="pending-", suffix=ext)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(_get(meta["url"]))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise

    meta["path"] = Path(tmp)
    meta["ext"] = ext
    meta["bytes"] = meta["path"].stat().st_size
    return meta


# ── files ───────────────────────────────────────────────────────────────────
def pictures_wallpapers():
    """The desktop's own wallpaper picker often scans this directory too, so
    saved images are hardlinked into it as well as kept in SAVE_DIR."""
    return desktop.pictures_dir() / "Wallpapers"


def prune_cache():
    """Drop downloads orphaned by a crash or a kill — they were never accepted,
    so nothing references them."""
    for stale in CACHE_DIR.glob("pending-*"):
        try:
            stale.unlink()
        except OSError:
            pass

    cutoff = time.time() - API_CACHE_TTL
    for stale in API_CACHE_DIR.glob("*"):
        try:
            if stale.stat().st_mtime < cutoff:
                stale.unlink()
        except OSError:
            pass


def human_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def unique_path(directory, stem, ext):
    """A name that does not exist yet. This is what makes Save non-destructive:
    we never open an existing file for writing."""
    candidate = directory / f"{stem}{ext}"
    n = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{n}{ext}"
        n += 1
    return candidate


def trash(path):
    return desktop.trash(path)


def set_wallpaper(path):
    """Hand the file to the platform. Raises on failure, and both callers care:
    Save has already succeeded by the time it gets here and must not report
    otherwise, and the rotation must not record a period it did not manage to
    apply — an unreachable desktop is a reason to try again next hour, not a
    reason to skip the season.

    One argument, deliberately: the rotation's test suite replaces this name
    wholesale with a fake shell, and a fake has to answer to the same call
    shape the real one does. A user's own command — for a session none of the
    built-in backends recognise — goes through RANDOM_WALLPAPER_SET_COMMAND
    instead, which `desktop.set_wallpaper` already reads.
    """
    desktop.set_wallpaper(path)


def same_file(a, b):
    """Whether two paths are the same file, hardlinks included."""
    try:
        return Path(a).samefile(b)
    except OSError:
        return False


def wallpaper_now():
    """The wallpaper on screen, or None when the platform cannot say.

    None means "do not know", never "none is set" — and every caller has to
    treat it as a reason to do nothing. Read it the other way and one restart
    of the shell looks exactly like the user choosing a wallpaper by hand.
    """
    try:
        return desktop.wallpaper_now()
    except OSError:
        return None


def wallpaper_was_changed_by_hand(state):
    """Is what is on screen something other than the file the rotation put
    there?

    Compared with samefile rather than by string: every saved wallpaper is
    also hardlinked into the Pictures wallpapers folder, so the same image
    legitimately answers to two paths and a string compare would read one of
    them as a stranger's.
    """
    ours = state.get("path")
    if not ours:
        return False          # nothing applied yet: nothing to contradict
    if not Path(ours).exists():
        # Our own file was deleted — from the Downloaded tab, or with a file
        # manager. That is not someone choosing a different wallpaper, and
        # reading it as one would switch the rotation off for the ordinary act
        # of tidying up. run_auto notices the gap separately and draws again.
        return False
    current = wallpaper_now()
    if current is None:
        return False          # unknown, and unknown is never grounds to latch
    try:
        return not current.samefile(ours)
    except OSError:
        return True


def set_auto_enabled(prefs, enabled):
    """Flip the rotation and write it through, so the next tick — a different
    process entirely — sees the same answer."""
    prefs["auto_enabled"] = enabled
    save_prefs(prefs)


# ── the calendar rotation ───────────────────────────────────────────────────
# What makes this safe to run from a timer, from login, and by hand at the same
# time is that it compares one thing only: today's period id against the last
# period id it acted on. It never asks what wallpaper is currently set.
#
# That is deliberate, and it is what keeps requirement 4 — a wallpaper you
# picked yourself, from this app or from anywhere else, is not "wrong" and is
# not corrected. The rotation simply has nothing to say until the calendar
# moves on, and then it says it once.
def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=STATE_DIR, suffix=".part")
    with os.fdopen(fd, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
    os.replace(tmp, STATE_FILE)    # atomic: a tick killed mid-write leaves
                                   # the previous period, never half of one


def period_wallpaper(period):
    """The file already downloaded for this period, if there is one."""
    for candidate in sorted(AUTO_DIR.glob(f"{period}.*")):
        if candidate.suffix.lower() in IMAGE_EXTS:
            return candidate
    return None


def prune_auto(keep=AUTO_KEEP):
    """Old periods' wallpapers. Kept a few deep rather than deleted on sight,
    so a period revisited within the same rotation — the season resuming after
    the holiday inside it — does not mean downloading it again.

    The wallpaper currently applied is never a candidate, whatever its age.
    Age alone would eventually pick it: a winter with Christmas and Valentine's
    inside it visits four periods, and a handful of --force runs adds more. And
    deleting it is not a self-correcting mistake — the state file still names
    that period as applied, so no tick will fetch it again until the calendar
    moves on, and the wallpaper on screen is a file that no longer exists.
    """
    spared = {load_state().get("path")}
    files = [p for p in AUTO_DIR.glob("*") if str(p) not in spared]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in files[keep:]:
        try:
            stale.unlink()
        except OSError:
            pass


def fetch_for_period(prefs, theme, period, avoid=None):
    """The wallpaper for this period, downloaded if it is not here yet.

    Downloading first and applying second is the order that matters: a failed
    download must leave the state file alone, so the next tick retries instead
    of recording a period it never showed.

    `avoid` is the wallpaper already up. On the nightly re-draw it is excluded
    from the draw, so a pool of two really does alternate instead of showing
    the same picture two nights running half the time.
    """
    # What you chose for this category wins over anything downloadable, and it
    # is the whole reason the pool exists: the point of picking the Halloween
    # wallpapers yourself is not being given a different one.
    chosen = pool_images(theme)
    if chosen:
        if avoid is not None and len(chosen) > 1:
            others = [p for p in chosen if not same_file(p, avoid)]
            chosen = others or chosen
        return random.choice(chosen)

    existing = period_wallpaper(period)
    if existing:
        return existing

    frame = download(dict(prefs, theme=theme))
    AUTO_DIR.mkdir(parents=True, exist_ok=True)
    dest = AUTO_DIR / f"{period}{frame['ext']}"
    shutil.move(str(frame["path"]), dest)
    prune_auto()
    return dest


def run_auto(prefs, force=False, log=print, today=None):
    """One tick of the rotation. Returns a process exit code.

    Idempotent by construction: run it every hour, or twice in a second, and
    it acts at most once per period and once per day. That is what lets a
    scheduled task and a login spawn both be enabled without them fighting.

    Two things make it act. A new period is the obvious one — the season
    turned, or a holiday came within its week. The other is a new day inside
    the same period: when the category has more than one wallpaper pinned to
    it, one of them is drawn afresh each midnight, so a fortnight of Christmas
    is not a fortnight of the same picture.
    """
    today = today or date.today()
    theme, period = current_period(today, prefs["easter"])
    state = load_state()

    # The latch, and the reason the rotation can be left switched on without
    # ever taking a wallpaper away from you: anything on screen that is not
    # what this tick last put there was put there by a person, and a person
    # outranks the calendar. The rotation switches itself off and says so,
    # rather than waiting for the next boundary to overwrite the choice.
    #
    # --force is how you say "yes, I mean it" — it is what --auto-on uses to
    # resume, and it is deliberately the only way past this.
    if prefs["auto_enabled"] and not force and wallpaper_was_changed_by_hand(state):
        set_auto_enabled(prefs, False)
        log("a wallpaper was set by hand — automatic rotation switched off. "
            "Turn it back on in Settings, or with --auto-on.")
        return 0

    if not prefs["auto_enabled"] and not force:
        log(f"automatic rotation is off (today is {period})")
        return 0

    stamp = today.isoformat()
    # A recorded wallpaper that no longer exists is a reason to act whatever
    # the calendar says: the file was deleted and the desktop is showing
    # something the rotation no longer has any claim on.
    gone = bool(state.get("path")) and not Path(state["path"]).exists()

    if state.get("period") == period and not force and not gone:
        # Same period. The only reason left to act is the nightly re-draw, and
        # only when the category holds more than one wallpaper — with nothing
        # pinned, or one thing pinned, there is nothing to draw between and
        # redrawing would just set the same file again every midnight.
        if state.get("day") == stamp:
            log(f"already on {period} — nothing to do")
            return 0
        if len(pool_images(theme)) < 2:
            # Record the day anyway, or every tick for the rest of it asks the
            # same question and answers it the same way.
            state["day"] = stamp
            save_state(state)
            log(f"{period}: nothing pinned to draw between — keeping it")
            return 0

    try:
        path = fetch_for_period(prefs, theme, period,
                                avoid=state.get("path") if not force else None)
    except (urllib.error.URLError, http.client.HTTPException, OSError,
            ValueError, FetchError) as exc:
        log(f"no {theme_label(theme)} wallpaper this time: {exc}")
        return 1

    try:
        set_wallpaper(path)
    except (subprocess.SubprocessError, OSError) as exc:
        # The file is kept — fetch_for_period() will find it next tick — but
        # the period is not recorded, so the next tick does try again.
        log(f"downloaded {path.name} but could not set it: {exc}")
        return 1

    save_state({
        "period": period,
        "day": stamp,
        "theme": theme,
        "path": str(path),
        "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    log(f"{period}: {theme_label(theme)} — {path}")
    return 0


def resume_auto(prefs, log=print):
    """Switch the rotation back on and put the period's wallpaper up at once.

    force=True rather than clearing the recorded period: the record is what
    makes a retry idempotent, and throwing it away to trigger one apply would
    trade that away for nothing. It also walks straight past the latch, which
    is right — turning the switch back on *is* the consent the latch waits for.
    """
    set_auto_enabled(prefs, True)
    return run_auto(prefs, force=True, log=log)
