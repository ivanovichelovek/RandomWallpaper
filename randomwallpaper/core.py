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

# Danbooru sits behind Cloudflare, which turns away a browser's User-Agent
# coming from something that is plainly not a browser (403, the API and the
# image CDN alike) and lets an honest one through, as its API terms ask.
HONEST_HOSTS = ("donmai.us", "safebooru.org")


def _agent(url):
    host = urllib.parse.urlparse(url).hostname or ""
    if any(host == h or host.endswith("." + h) for h in HONEST_HOSTS):
        from . import __version__
        return (f"RandomWallpaper/{__version__} "
                f"(+https://github.com/ivanovichelovek/RandomWallpaper)")
    return USER_AGENT


TIMEOUT = 30
REEL_AHEAD = 6          # frames kept downloaded ahead of the current one
REEL_BEHIND = 8         # frames kept behind it, when reel_forget is on
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
    # The Random tab forgets frames more than REEL_BEHIND behind the one
    # showing, files and all, so a long session does not fill the cache.
    "reel_forget": True,
    # Off until someone turns it on: a fresh install never changes the
    # wallpaper by itself before it has been asked to.
    "auto_enabled": False,
    "easter": "orthodox",
    # When, inside a period, the rotation draws a new wallpaper. "midnight"
    # is the original behaviour; the other two are for a wallpaper that
    # changes through the day. See current_slot().
    "change_mode": "midnight",
    "change_every": 60,            # minutes, for "every"
    "change_times": ["07:00", "19:00"],   # local HH:MM, for "times"
    # What the rotation draws from: the calendar's season or holiday, or the
    # wallpapers put in the shuffle set, whatever the date. See rotation().
    "rotation": "calendar",
    # Several monitors: one wallpaper on all of them, a monitor plugged in
    # taking the main one's ("sync"), or each its own ("separate"). See
    # screens_mode(). The main one is named here, "" meaning the built-in
    # panel, or failing that the first output the desktop lists.
    "screens": "sync",
    "primary_output": "",
    # Ask GitHub for a newer release each time the window opens, and offer
    # to install it. Installed builds only; see ui.settings_page.
    "check_updates": True,
    # Whether the Windows app has asked, once, to open at sign-in. Only that
    # it asked: whether it opens is the registry's to say (see login.py).
    "login_asked": False,
    # The window's colours: taken from the wallpaper on screen, or one fixed
    # hue; and dark, light, or whatever the system is set to. See ui.style.
    "colors": "wallpaper",
    "appearance": "system",
}

SCREEN_MODES = [
    ("Same on every screen", "sync"),
    ("Each screen its own", "separate"),
]

ROTATIONS = [
    ("Follow the calendar", "calendar"),
    ("Shuffle my picks", "shuffle"),
]
# The shuffle set is a category like the seasons — a directory under SAVE_DIR
# filled from the Saved tab — but not a theme: nothing is downloaded for
# it and the calendar never lands on it.
SHUFFLE = "shuffle"

CHANGE_MODES = [
    ("At midnight", "midnight"),
    ("Every…", "every"),
    ("At set times", "times"),
]
# The floor on "every". With nothing pinned each change is a download, and a
# wallpaper a minute would be a request a minute against someone else's API.
MIN_CHANGE_EVERY = 15
# After a failed download, scheduled ticks leave the network alone this long.
# The timer ticks every minute, and a download can hang for a minute and a
# half before it gives up — without a pause an outage would be retried back
# to back.
FAILED_BACKOFF = timedelta(minutes=10)
# A stranger on screen has to still be there this long after it was first
# seen before the rotation switches itself off. Just under a minute, so the
# next minutely tick confirms it — but not the tick a few seconds later that
# a wake from sleep lines up right behind the catch-up one.
HAND_SET_CONFIRM = timedelta(seconds=50)

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

# The two boorus (Danbooru, Safebooru) file the same occasions under the same
# tag names, counted against both on 24 Oct 2026: thousands of safe posts
# each, Easter the smallest at ~800. Christmas / New Year asks either tag.
BOORU_TAGS = {
    "spring": ["spring_(season)"],
    "summer": ["summer"],
    "autumn": ["autumn"],
    "winter": ["winter"],
    "halloween": ["halloween"],
    "christmas": ["christmas", "new_year"],
    "valentine": ["valentine"],
    "easter": ["easter"],
}
BOORUS = ("danbooru", "safebooru")

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
    if key == SHUFFLE:
        return "Shuffle"
    return theme_entry(key)[1]


def pin_categories():
    """Everything a wallpaper can be pinned to: every theme but "all", in
    calendar order, then the shuffle set."""
    return [key for key, *_ in THEMES if key != "all"] + [SHUFFLE]


def rotation(prefs):
    """"calendar" or "shuffle" — anything else, a config from a later version
    say, is the calendar, which is what the rotation always was."""
    value = prefs.get("rotation", "calendar")
    return value if value in {key for _, key in ROTATIONS} else "calendar"


def screens_mode(prefs):
    """"sync" or "separate" — "separate" only where the desktop can set a
    wallpaper per output, since anywhere else it could not be kept."""
    value = prefs.get("screens", "sync")
    if value == "separate" and can_set_per_output():
        return "separate"
    return "sync"


# Connector prefixes of a laptop's own panel: the screen that is there
# whatever gets plugged in, and so the natural one to copy from.
BUILT_IN = ("eDP", "LVDS", "DSI")


def primary_output(prefs, outputs):
    """The output the others follow, among `outputs` (in the desktop's own
    order). None when there is none to name."""
    names = list(outputs)
    chosen = prefs.get("primary_output") or ""
    if chosen in names:
        return chosen
    for name in names:
        if name.startswith(BUILT_IN):
            return name
    return names[0] if names else None


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
    if source in BOORUS:
        return bool(BOORU_TAGS.get(key))
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
    req = urllib.request.Request(url, headers={"User-Agent": _agent(url)})
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
    """The minimum as (width, height), turned to stand upright for portrait:
    1920×1080 means a picture at least 1080 wide and 1920 tall then, not
    one that is somehow 1920 wide and still taller than it is wide."""
    if not prefs["minimum"]:
        return 0, 0
    w, _, h = prefs["minimum"].partition("x")
    w, h = int(w), int(h)
    if prefs.get("orientation") == "portrait":
        return min(w, h), max(w, h)
    return w, h


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

    post = random.choice(_unseen(usable, lambda p: f"konachan-{p.get('id', 'x')}"))
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
        params["atleast"] = "%dx%d" % _min_size(prefs)
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

    post = random.choice(_unseen(posts, lambda p: f"wallhaven-{p.get('id', 'x')}"))
    return {
        "url": post["path"],
        "name": f"wallhaven-{post.get('id', 'x')}",
        "width": post.get("dimension_x"),
        "height": post.get("dimension_y"),
        "credit": post.get("uploader", {}).get("username") or "wallhaven.cc",
        "source": "Wallhaven",
    }


# ── not the same picture twice ──────────────────────────────────────────────
# Every frame's name (konachan-123, danbooru-456 …) once it is downloaded, the
# newest last. A source's candidates that are in here are passed over while
# there are others, so a small pool — five portrait Halloween pictures on
# wallhaven — goes round all five before it repeats one, instead of drawing
# at random each time. The GUI, the rotation and Android's background job all
# write it, so it is replaced whole, never edited in place.
SEEN_FILE = STATE_DIR / "seen.json"
SEEN_KEEP = 300


def seen_names():
    try:
        names = json.loads(SEEN_FILE.read_text())
        return names if isinstance(names, list) else []
    except (OSError, ValueError):
        return []


def remember_seen(name):
    names = [n for n in seen_names() if n != name] + [name]
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=STATE_DIR, suffix=".part")
        with os.fdopen(fd, "w") as fh:
            json.dump(names[-SEEN_KEEP:], fh)
        os.replace(tmp, SEEN_FILE)
    except OSError:
        pass          # a repeat now and then is not worth failing a frame over


def _unseen(candidates, name_of):
    """The candidates not shown yet — or, when every one has been, all of
    them: a repeat beats an empty reel."""
    seen = set(seen_names())
    fresh = [c for c in candidates if name_of(c) not in seen]
    return fresh or candidates


# ── the boorus: Danbooru and Safebooru ──────────────────────────────────────
# Image boards of anime art, millions of posts, far deeper than the two
# wallpaper sites — 5732 portrait Halloween pictures on Danbooru at 1080×1920
# and up, where wallhaven has five. They are illustrations, not wallpapers
# picked for a screen, so comics and pages of text are passed over by tag.
BOORU_EXTS = {"jpg", "jpeg", "png", "webp"}       # no gif, video or ugoira zip
BOORU_MAX_BYTES = 25_000_000      # a 5400×9600 original is no phone's wallpaper
BOORU_SKIP_TAGS = {"comic", "4koma", "text_focus", "character_sheet",
                   "multiple_views", "reference_sheet"}

DANBOORU_HOST = "danbooru.donmai.us"
SAFEBOORU_HOST = "safebooru.org"


def _booru_theme_tag(prefs):
    theme = theme_key(prefs)
    if theme == "all":
        return None
    return random.choice(BOORU_TAGS[theme])


def _booru_wordy(tags):
    return bool(BOORU_SKIP_TAGS & set(tags.split()))


def _screen_shaped(width, height):
    """Not a long scroll or a banner: a board has both, and a 4227×12096
    page cropped to a screen is a sliver of it."""
    if not (width and height):
        return True
    return 0.4 <= width / height <= 2.6


DANBOORU_PAGES = 200     # deeper than this an untagged search times out


def pick_danbooru(prefs):
    """Danbooru's safe-for-work rating (general) and its filters by ratio,
    size and random order all run on the server, and no key is needed.

    Without an account a search may hold only two ordinary tags, and
    order:random is one, so a theme leaves no room for -comic: comics are
    filtered here, by the post's tags. The rating, ratio and size metatags
    do not count. Random order over the whole catalogue times out on the
    server, so with no theme a random page of the newest is asked instead —
    200 pages of 40 is a pool of 8000.
    """
    theme_tag = _booru_theme_tag(prefs)
    tags = [theme_tag, "order:random"] if theme_tag else ["-comic"]
    tags.append("rating:g")
    if prefs["orientation"] == "landscape":
        tags.append("ratio:>1")
    elif prefs["orientation"] == "portrait":
        tags.append("ratio:<1")
    min_w, min_h = _min_size(prefs)
    if min_w:
        tags += [f"width:>={min_w}", f"height:>={min_h}"]
    base = (f"https://{DANBOORU_HOST}/posts.json?limit=40&tags="
            + urllib.parse.quote(" ".join(tags)))
    # A random page, then a shallower one should the database time out.
    attempts = ([base] if theme_tag else
                [f"{base}&page={random.randint(1, DANBOORU_PAGES)}",
                 f"{base}&page={random.randint(1, 20)}"])
    posts, problem = None, None
    for url in attempts:
        try:
            # ttl=0: order:random is the same URL every time, only the
            # answer is random — a cached one would be the same 40 all day.
            posts = _get_json(url, ttl=0)
            break
        except urllib.error.HTTPError as exc:
            problem = FetchError(f"danbooru answered {exc.code}")
        except (OSError, ValueError) as exc:
            problem = FetchError(f"could not reach danbooru: {exc}")
    if posts is None:
        raise problem
    if not isinstance(posts, list):
        raise FetchError(f"danbooru: {posts.get('message') if isinstance(posts, dict) else posts}")

    usable = [p for p in posts
              if p.get("file_url") and p.get("file_ext") in BOORU_EXTS
              and (p.get("file_size") or 0) <= BOORU_MAX_BYTES
              and p.get("rating") == "g"
              and not _booru_wordy(p.get("tag_string", ""))
              and _fits(prefs, p.get("image_width"), p.get("image_height"))
              and _screen_shaped(p.get("image_width"), p.get("image_height"))]
    if not usable:
        raise FetchError("danbooru had nothing that fits these filters this time — try again")
    post = random.choice(_unseen(usable, lambda p: f"danbooru-{p.get('id')}"))
    artist = (post.get("tag_string_artist") or "").split()
    return {
        "url": post["file_url"],
        "name": f"danbooru-{post.get('id', 'x')}",
        "width": post.get("image_width"),
        "height": post.get("image_height"),
        "credit": artist[0].replace("_", " ") if artist else DANBOORU_HOST,
        "source": "Danbooru",
    }


def pick_safebooru(prefs):
    """Safebooru is Gelbooru's safe-only board. Size and random order are
    filtered on the server; orientation is not, so that is checked here.
    An empty search answers with an empty body, not with []."""
    tags = [t for t in (_booru_theme_tag(prefs), "-comic", "sort:random") if t]
    min_w, min_h = _min_size(prefs)
    if min_w:
        tags += [f"width:>={min_w}", f"height:>={min_h}"]
    url = (f"https://{SAFEBOORU_HOST}/index.php?page=dapi&s=post&q=index&json=1"
           f"&limit=100&tags=" + urllib.parse.quote(" ".join(tags)))
    try:
        raw = _get(url)      # not _get_json: random order, nothing to cache
        posts = json.loads(raw) if raw.strip() else []
    except urllib.error.HTTPError as exc:
        raise FetchError(f"safebooru answered {exc.code}") from exc
    except (OSError, ValueError) as exc:
        raise FetchError(f"could not reach safebooru: {exc}") from exc
    if isinstance(posts, dict):
        posts = posts.get("post") or []

    def ext(p):
        return Path(p.get("image") or p.get("file_url") or "").suffix.lower().lstrip(".")

    usable = [p for p in posts
              if p.get("file_url") and ext(p) in BOORU_EXTS
              and p.get("rating") in ("general", "safe")
              and not _booru_wordy(p.get("tags", ""))
              and _fits(prefs, p.get("width"), p.get("height"))
              and _screen_shaped(p.get("width"), p.get("height"))]
    if not usable:
        raise FetchError("safebooru had nothing that fits these filters this time — try again")
    post = random.choice(_unseen(usable, lambda p: f"safebooru-{p.get('id')}"))
    return {
        "url": post["file_url"],
        "name": f"safebooru-{post.get('id', 'x')}",
        "width": post.get("width"),
        "height": post.get("height"),
        "credit": SAFEBOORU_HOST,
        "source": "Safebooru",
    }


# The osu! seasonal-backgrounds endpoint the old shell script used now answers
# 403 — it went behind OAuth — so wallhaven takes its place as second source.
# Pixabay was the third and is gone: two catalogues that both answer a themed
# query are worth more than a third that answers none of them.
SOURCES = [
    ("Konachan", "konachan", pick_konachan),
    ("Wallhaven", "wallhaven", pick_wallhaven),
    ("Danbooru", "danbooru", pick_danbooru),
    ("Safebooru", "safebooru", pick_safebooru),
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
    if chosen == "konachan" and prefs.get("orientation") == "portrait":
        # konachan is a desktop-wallpaper board: in samples of hundreds of
        # its posts not one stood upright, so a portrait reel from it is an
        # empty reel. Danbooru has thousands even under a holiday's tag.
        return "danbooru"
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
    remember_seen(meta["name"])
    return meta


# ── files ───────────────────────────────────────────────────────────────────
def pictures_wallpapers():
    """The desktop's own wallpaper picker often scans this directory too, so
    saved images are hardlinked into it as well as kept in SAVE_DIR."""
    return desktop.pictures_dir() / "Wallpapers"


PENDING_MAX_AGE = 24 * 60 * 60


def prune_cache(now=None):
    """Drop downloads orphaned by a crash or a kill — they were never accepted,
    so nothing references them.

    Only old ones. A pending file this young may well be a frame waiting in a
    window that is open right now — every launch runs this, the one that
    only hands its arguments to that window included — and deleting it
    leaves the reel pointing at a file that is gone.
    """
    cutoff = (now or time.time()) - PENDING_MAX_AGE
    for stale in CACHE_DIR.glob("pending-*"):
        try:
            if stale.stat().st_mtime < cutoff:
                stale.unlink()
        except OSError:
            pass

    cutoff = (now or time.time()) - API_CACHE_TTL
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


def link_into(src, dest):
    """Give `src` a second name, `dest`: a hardlink, else a relative symlink,
    else — only where neither can be made — a copy.

    Android allows an app no hardlinks at all, even inside its own files;
    a copy there made a starred wallpaper show twice on the Saved tab, once
    with its star and once without. A symlink is the same picture to
    everything that reads it — stat, samefile, opening it.
    """
    try:
        os.link(src, dest)
        return
    except OSError:
        pass
    try:
        os.symlink(os.path.relpath(src, dest.parent), dest)
        return
    except OSError:
        pass
    shutil.copy2(src, dest)


def dedupe_pools():
    """Turn the copies an earlier pin left in the category directories back
    into links to the same picture in SAVE_DIR. The number replaced.

    Only byte-for-byte copies of a file kept in SAVE_DIR itself; a file that
    was dropped into a category directory and is nowhere else stays as it is.
    """
    import filecmp
    try:
        kept = [p for p in SAVE_DIR.iterdir()
                if p.is_file() and not p.is_symlink()]
    except OSError:
        return 0
    by_size = {}
    for path in kept:
        try:
            by_size.setdefault(path.stat().st_size, []).append(path)
        except OSError:
            pass
    replaced = 0
    for key in pin_categories():
        for pinned in pool_images(key):
            try:
                if pinned.is_symlink() or pinned.stat().st_nlink > 1:
                    continue
                size = pinned.stat().st_size
                original = next((p for p in by_size.get(size, [])
                                 if filecmp.cmp(p, pinned, shallow=False)), None)
                if original is None:
                    continue
                # Made beside it and renamed over it: the picture is never
                # missing from the category, not even for a moment.
                spare = pinned.with_name(f".{pinned.name}.link")
                spare.unlink(missing_ok=True)
                link_into(original, spare)
                if not spare.is_symlink() and spare.stat().st_nlink == 1:
                    spare.unlink()      # only a copy again: nothing gained
                    continue
                os.replace(spare, pinned)
                replaced += 1
            except OSError:
                continue
    return replaced


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


def can_set_per_output():
    try:
        return desktop.can_set_per_output()
    except OSError:
        return False


def set_wallpaper_on(output, path):
    """One output only — the others keep what they show. Raises like
    set_wallpaper; two arguments, and the tests stand a fake in for it too."""
    desktop.set_wallpaper_on(output, path)


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


def wallpapers_on_outputs():
    """{output: wallpaper} where the platform keeps one per output and can
    say so; {} otherwise, which leaves wallpaper_now's one answer standing."""
    try:
        return desktop.wallpapers_on_outputs()
    except OSError:
        return {}


def outputs_behind(state, outputs):
    """The outputs that came back with an old wallpaper.

    A monitor unplugged while the wallpaper changed keeps the one it had, and
    shows it again when it is plugged back in. An output the last tick did not
    see is one of those, whatever it shows — nobody picked a wallpaper for a
    monitor that was not there. So is one showing a file that is gone.
    """
    ours = state.get("path")
    if not ours or not Path(ours).exists():
        return []
    seen = set(state.get("outputs", []))
    return sorted(name for name, path in outputs.items()
                  if not same_file(path, ours)
                  and (name not in seen or not Path(path).exists()))


def changed_by_hand_per_output(state, outputs):
    """The latch's question with each screen on its own: is any output the
    last tick saw showing something other than what the rotation put on it?

    An output the rotation never drew for — plugged in since, or everything
    from before "each screen its own" was switched on — has nothing to
    contradict, and so is no answer either way.
    """
    ours = state.get("paths") or {}
    seen = set(state.get("outputs", []))
    for name, path in outputs.items():
        mine = ours.get(name)
        if (mine and name in seen and Path(mine).exists()
                and not same_file(path, mine)):
            return True
    return False


def wallpaper_was_changed_by_hand(state, outputs=None):
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
        # Our own file was deleted — from the Saved tab, or with a file
        # manager. That is not someone choosing a different wallpaper, and
        # reading it as one would switch the rotation off for the ordinary act
        # of tidying up. run_auto notices the gap separately and draws again.
        return False
    # One output that was there last tick and now shows something else is
    # as much a choice as the whole desktop changing; a monitor just plugged
    # in is not (outputs_behind).
    if outputs is None:
        outputs = wallpapers_on_outputs()
    behind = outputs_behind(state, outputs)
    if any(name not in behind and not same_file(path, ours)
           for name, path in outputs.items()):
        return True
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


# ── how often inside a period ───────────────────────────────────────────────
def parse_times(value):
    """"07:00, 19:30" — or a list of such strings — as sorted (hour, minute)
    pairs. Raises ValueError on anything that is not a time of day, so a
    typo in Settings is refused rather than saved."""
    items = value.replace(";", ",").split(",") if isinstance(value, str) else value
    times = set()
    for item in items:
        item = str(item).strip()
        if not item:
            continue
        hour, sep, minute = item.partition(":")
        if not sep or not hour.isdigit() or not minute.isdigit() or len(minute) != 2:
            raise ValueError(f"not a time of day: {item!r}")
        h, m = int(hour), int(minute)
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError(f"not a time of day: {item!r}")
        times.add((h, m))
    if not times:
        raise ValueError("no times given")
    return sorted(times)


def format_times(times):
    return ", ".join(f"{h:02d}:{m:02d}" for h, m in times)


def describe_change(prefs):
    """"each midnight", "every 2 h", "at 07:00, 19:00" — for the hints."""
    mode = prefs.get("change_mode", "midnight")
    if mode == "every":
        try:
            n = max(MIN_CHANGE_EVERY, int(prefs.get("change_every", 60)))
        except (TypeError, ValueError):
            n = 60
        return f"every {n // 60} h" if n % 60 == 0 else f"every {n} min"
    if mode == "times":
        try:
            return "at " + format_times(parse_times(prefs.get("change_times", [])))
        except ValueError:
            pass
    return "each midnight"


def current_slot(prefs, now):
    """Which stretch of time `now` falls in, as a string that changes exactly
    when the wallpaper is due to.

    * midnight — the date, which is what the state file always recorded as
      "day", so an existing state file reads as already up to date;
    * every — the start of the current n-minute block, counted from local
      midnight. Anchored to the day rather than to the last change, so an
      interval that does not divide 24 hours restarts at midnight instead of
      drifting, and a tick that ran late does not push every later one back;
    * times — the latest listed time already passed, yesterday's last one
      before today's first.

    Settings that cannot be read fall back to midnight rather than to
    changing on every tick.
    """
    mode = prefs.get("change_mode", "midnight")
    if mode == "every":
        try:
            n = max(MIN_CHANGE_EVERY, int(prefs.get("change_every", 60)))
        except (TypeError, ValueError):
            n = 60
        start = (now.hour * 60 + now.minute) // n * n
        return f"{now.date().isoformat()}T{start // 60:02d}:{start % 60:02d}"
    if mode == "times":
        try:
            times = parse_times(prefs.get("change_times", []))
        except ValueError:
            return now.date().isoformat()
        passed = [t for t in times if t <= (now.hour, now.minute)]
        day = now.date() if passed else now.date() - timedelta(days=1)
        h, m = max(passed) if passed else times[-1]
        return f"{day.isoformat()}T{h:02d}:{m:02d}"
    return now.date().isoformat()


def next_change(prefs, now):
    """When the slot current_slot() is in ends: the next time the rotation
    is due to put up a new wallpaper, as a naive local datetime."""
    mode = prefs.get("change_mode", "midnight")
    midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    if mode == "every":
        try:
            n = max(MIN_CHANGE_EVERY, int(prefs.get("change_every", 60)))
        except (TypeError, ValueError):
            n = 60
        start = (now.hour * 60 + now.minute) // n * n + n
        nxt = datetime.combine(now.date(), datetime.min.time()) + timedelta(minutes=start)
        return min(nxt, midnight)
    if mode == "times":
        try:
            times = parse_times(prefs.get("change_times", []))
        except ValueError:
            return midnight
        later = [t for t in times if t > (now.hour, now.minute)]
        day = now.date() if later else now.date() + timedelta(days=1)
        h, m = min(later) if later else times[0]
        return datetime.combine(day, datetime.min.time()) + timedelta(hours=h, minutes=m)
    return midnight


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
    state = load_state()
    spared = {state.get("path"), *(state.get("paths") or {}).values()}
    files = [p for p in AUTO_DIR.glob("*") if str(p) not in spared]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in files[keep:]:
        try:
            stale.unlink()
        except OSError:
            pass


def fetch_for_period(prefs, theme, period, avoid=None, fresh=None, tag=None):
    """The wallpaper for this period, downloaded if it is not here yet.

    Downloading first and applying second is the order that matters: a failed
    download must leave the state file alone, so the next tick retries instead
    of recording a period it never showed.

    `avoid` is the wallpaper already up. On the nightly re-draw it is excluded
    from the draw, so a pool of two really does alternate instead of showing
    the same picture two nights running half the time.

    `fresh` names a download that must be new — a change through the day,
    with nothing pinned, is a different picture each time rather than the
    period's one file set again. It is the slot, so each gets its own file.

    `tag` is the output a draw is for, with each screen its own: a download
    named for it, so two monitors are not handed the same file, and `avoid`
    then lists everything already drawn for the others too.
    """
    avoid = [] if avoid is None else [avoid] if isinstance(avoid, (str, Path)) else list(avoid)
    # What you chose for this category wins over anything downloadable, and it
    # is the whole reason the pool exists: the point of picking the Halloween
    # wallpapers yourself is not being given a different one.
    chosen = pool_images(theme)
    if chosen:
        if avoid and len(chosen) > 1:
            others = [p for p in chosen
                      if not any(same_file(p, a) for a in avoid)]
            chosen = others or chosen
        return random.choice(chosen)

    # No colon in the name: the slot is "…T07:00", and Windows refuses it.
    # Looked for before downloading either way: a slot whose apply failed
    # retries with the file it already has, not with a second download.
    stem = period if fresh is None else f"{period}_{fresh.replace(':', '')}"
    if tag:
        stem = f"{stem}@{tag}"
    existing = period_wallpaper(stem)
    if existing:
        return existing

    frame = download(dict(prefs, theme=theme))
    AUTO_DIR.mkdir(parents=True, exist_ok=True)
    dest = AUTO_DIR / f"{stem}{frame['ext']}"
    shutil.move(str(frame["path"]), dest)
    prune_auto()
    return dest


def sync_new_outputs(prefs, state, outputs, log=print):
    """A monitor plugged in shows the main one's wallpaper — whatever that
    is, the rotation's or one set by hand, and with the rotation on or off.

    New means not there at the last tick (state["outputs"]). With no last
    tick to compare with — the very first, or one right after a wake that
    got no answer — nothing is new, rather than everything. `outputs` is
    updated in place with what each output shows now. Returns the outputs
    that could not be brought in line, for the next tick to try again.
    """
    seen = state.get("outputs")
    if not outputs or not seen:
        return []
    new = [name for name in outputs if name not in seen]
    # Copied from a screen that was already there: one being plugged in
    # with it is the very one with nothing worth copying yet.
    main = primary_output(prefs, {n: p for n, p in outputs.items() if n in seen})
    if not new or main is None or not Path(outputs[main]).exists():
        return []
    source = outputs[main]
    failed = []
    for name in new:
        if same_file(outputs[name], source):
            continue
        try:
            set_wallpaper_on(name, source)
        except (subprocess.SubprocessError, OSError) as exc:
            log(f"{name}: plugged in, but could not give it {main}'s "
                f"wallpaper: {exc}")
            failed.append(name)
            continue
        outputs[name] = Path(source)
        log(f"{name}: plugged in — the same wallpaper as {main}")
    return failed


def match_main_output(prefs, log=print):
    """Every output showing what the main one does, now — the switch to the
    same on every screen, with no rotation to redraw it. Returns how many
    were changed."""
    outputs = wallpapers_on_outputs()
    main = primary_output(prefs, outputs)
    if main is None or not Path(outputs[main]).exists():
        return 0
    changed = 0
    for name, path in outputs.items():
        if name == main or same_file(path, outputs[main]):
            continue
        try:
            set_wallpaper_on(name, outputs[main])
            changed += 1
        except (subprocess.SubprocessError, OSError) as exc:
            log(f"{name}: could not give it {main}'s wallpaper: {exc}")
    if changed:
        log(f"every screen now shows {main}'s wallpaper")
    return changed


def run_auto(prefs, force=False, log=print, today=None, now=None, quiet=False):
    """One tick of the rotation. Returns a process exit code.

    Idempotent by construction: run it every minute, or twice in a second,
    and it acts at most once per period and once per slot. That is what lets
    a scheduled task and a login spawn both be enabled without them fighting.

    Two things make it act. A new period is the obvious one — the season
    turned, or a holiday came within its week. The other is a new slot inside
    the same period (current_slot): by default a new day, when one of the
    wallpapers pinned to the category is drawn afresh, so a fortnight of
    Christmas is not a fortnight of the same picture. Set to change every so
    often or at set times, a slot is shorter, and with nothing pinned each
    change is a new download.

    `quiet` drops the lines a tick that does nothing would print. The timer
    passes it: at one tick a minute, "nothing to do" is 1440 log lines a day.
    """
    if now is None:
        now = datetime.combine(today, datetime.min.time()) if today else datetime.now()
    today = now.date()
    note = (lambda _msg: None) if quiet else log
    shuffling = rotation(prefs) == SHUFFLE
    # Shuffling, the period is the shuffle set itself: it never ends, so the
    # slot alone moves it on — and switching modes, either way, is a period
    # other than the one recorded, so it applies at once.
    theme, period = ((SHUFFLE, SHUFFLE) if shuffling
                     else current_period(today, prefs["easter"]))
    slot = current_slot(prefs, now)
    through_the_day = prefs.get("change_mode", "midnight") != "midnight"
    state = load_state()

    # The latch, and the reason the rotation can be left switched on without
    # ever taking a wallpaper away from you: anything on screen that is not
    # what this tick last put there was put there by a person, and a person
    # outranks the calendar. The rotation switches itself off and says so,
    # rather than waiting for the next boundary to overwrite the choice.
    #
    # --force is how you say "yes, I mean it" — it is what --auto-on uses to
    # resume, and it is deliberately the only way past this.
    #
    # Seen once is not enough. Right after a wake from sleep or a login the
    # desktop can answer with something it is not showing — a shell not up
    # yet, a default picture — and that single wrong answer used to switch
    # the rotation off for good. So the first sighting is only noted, nothing
    # is changed on screen, and it takes a stranger still there a tick later
    # to latch.
    #
    # Before any of it, and whether the rotation is on or not: a monitor
    # just plugged in takes the main one's wallpaper, with every screen
    # showing the same (sync_new_outputs). With each its own, it keeps
    # whatever it had.
    separate = screens_mode(prefs) == "separate"
    outputs = wallpapers_on_outputs()
    unsynced = [] if separate else sync_new_outputs(prefs, state, outputs, log)
    behind = []
    if prefs["auto_enabled"] and not force:
        if (changed_by_hand_per_output(state, outputs) if separate
                else wallpaper_was_changed_by_hand(state, outputs)):
            try:
                since = now - datetime.fromisoformat(state["stranger_since"])
            except (KeyError, TypeError, ValueError):
                since = None
            if since is None or since < timedelta(0):
                state["stranger_since"] = now.isoformat(timespec="seconds")
                save_state(state)
                log("the wallpaper on screen is not the one the rotation set — "
                    "checking again before switching the rotation off")
                return 0
            if since < HAND_SET_CONFIRM:
                note("still waiting to confirm a wallpaper set by hand")
                return 0
            del state["stranger_since"]
            save_state(state)
            set_auto_enabled(prefs, False)
            log("a wallpaper was set by hand — automatic rotation switched off. "
                "Turn it back on in Settings, or with --auto-on.")
            return 0
        if state.pop("stranger_since", None) is not None:
            save_state(state)       # a false alarm, or no answer: start over

        # With each screen its own, one showing something old is just that
        # screen's own wallpaper, until its next draw.
        behind = [] if separate else outputs_behind(state, outputs)
        if behind:
            # Put without a connector, it reaches every output there now.
            try:
                set_wallpaper(state["path"])
                log(f"{', '.join(behind)}: caught up with {Path(state['path']).name}")
                behind = []
            except (subprocess.SubprocessError, OSError) as exc:
                log(f"could not bring {', '.join(behind)} up to date: {exc}")
    # Remembered only from a real answer: an empty one right after a wake
    # would make every output look newly plugged in on the next tick. And
    # not an output still behind: remembered, its old wallpaper would read
    # as one set by hand, when the next tick should just try again.
    seen = sorted(name for name in outputs
                  if name not in behind and name not in unsynced)
    if seen and state.get("outputs") != seen:
        state["outputs"] = seen
        save_state(state)

    if not prefs["auto_enabled"] and not force:
        note(f"automatic rotation is off (today is {period})")
        return 0

    if shuffling and not pool_images(SHUFFLE):
        # Nothing to shuffle is nothing to do. Not a download: a set of your
        # own picks is the whole point, and "all" would quietly stand in.
        note(f"nothing in the shuffle set yet — add some on the Saved "
             f"tab, or put files in {theme_pool(SHUFFLE)}")
        return 0

    stamp = today.isoformat()
    # A recorded wallpaper that no longer exists is a reason to act whatever
    # the calendar says: the file was deleted and the desktop is showing
    # something the rotation no longer has any claim on.
    gone = bool(state.get("path")) and not Path(state["path"]).exists()

    if state.get("period") == period and not force and not gone:
        # Same period. The only reason left to act is a new slot. A state file
        # from before slots existed recorded only the day, which is exactly
        # the midnight slot — so it reads as up to date, not as due.
        if state.get("slot", state.get("day")) == slot:
            note(f"already on {period} — nothing to do")
            return 0
        pinned = pool_images(theme)
        # With one wallpaper pinned and already up there is nothing to draw
        # between, and redrawing would just set the same file again — but if
        # it was pinned since, the next slot is when it takes over. With none,
        # midnight keeps the period's download; through the day, that is
        # what a fresh download is for.
        single_up = (len(pinned) == 1 and state.get("path")
                     and same_file(pinned[0], state["path"]))
        if single_up or (not pinned and not through_the_day):
            # Record the slot anyway, or every tick for the rest of it asks
            # the same question and answers it the same way.
            state["day"], state["slot"] = stamp, slot
            save_state(state)
            note(f"{period}: nothing pinned to draw between — keeping it")
            return 0

    failed_at = state.get("failed_at")
    if failed_at and not force:
        try:
            since = now - datetime.fromisoformat(failed_at)
        except (TypeError, ValueError):
            since = FAILED_BACKOFF
        if timedelta(0) <= since < FAILED_BACKOFF:
            note(f"last download failed at {failed_at} — waiting before the next")
            return 0

    # Each screen its own: a draw per output, none repeating another's or
    # what that output had, where the pool is deep enough for that.
    targets = list(outputs) if separate else []
    if separate and not targets:
        note("cannot tell the monitors apart right now — trying again next tick")
        return 1
    drawn = {}
    try:
        if targets:
            had = state.get("paths") or {}
            for name in targets:
                avoid = [] if force else [p for p in (had.get(name),) if p]
                drawn[name] = fetch_for_period(
                    prefs, theme, period, avoid=avoid + list(drawn.values()),
                    fresh=slot if through_the_day else None, tag=name)
            path = drawn[primary_output(prefs, outputs)]
        else:
            path = fetch_for_period(prefs, theme, period,
                                    avoid=state.get("path") if not force else None,
                                    fresh=slot if through_the_day else None)
    except (urllib.error.URLError, http.client.HTTPException, OSError,
            ValueError, FetchError) as exc:
        state["failed_at"] = now.isoformat(timespec="seconds")
        save_state(state)
        log(f"no {theme_label(theme)} wallpaper this time: {exc}")
        return 1

    try:
        if drawn:
            # The main one last: the desktop's colours follow whichever
            # wallpaper was set most recently, and they should be its.
            main = primary_output(prefs, outputs)
            for name in sorted(drawn, key=lambda n: n == main):
                set_wallpaper_on(name, drawn[name])
        else:
            set_wallpaper(path)
    except (subprocess.SubprocessError, OSError) as exc:
        # The file is kept — fetch_for_period() will find it next tick — but
        # the period is not recorded, so the next tick does try again.
        log(f"downloaded {path.name} but could not set it: {exc}")
        return 1

    save_state({
        "period": period,
        "day": stamp,
        "slot": slot,
        "theme": theme,
        "path": str(path),
        "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        # Kept across the apply: a monitor that was already there is not
        # "just plugged in" because the wallpaper changed.
        **({"outputs": state["outputs"]} if state.get("outputs") else {}),
        **({"paths": {name: str(file) for name, file in drawn.items()}}
           if drawn else {}),
    })
    if drawn:
        for name, file in drawn.items():
            log(f"{period}: {theme_label(theme)} — {name}: {file}")
    else:
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
