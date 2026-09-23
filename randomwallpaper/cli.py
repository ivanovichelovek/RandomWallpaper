"""Command-line entry point, shared by the console script and the GUI one.

Every launch — a terminal run, a scheduled tick, a Start-menu shortcut, a
second invocation while the window is already open — lands here first.
"""
import sys
from datetime import date

from . import core
from .paths import CACHE_DIR


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="random-wallpaper",
        description="A reel of random wallpapers: keep the ones you want, drop the rest.",
    )
    parser.add_argument("--source", choices=[s[1] for s in core.SOURCES],
                        help="override the saved source for this run")
    parser.add_argument("--theme", choices=[t[0] for t in core.THEMES] + ["now"],
                        help="override the saved theme for this run; 'now' is "
                             "whichever season or holiday today falls in")
    parser.add_argument("--orientation", choices=[o[1] for o in core.ORIENTATIONS],
                        help="override the saved orientation for this run")
    parser.add_argument("--auto", action="store_true",
                        help="no window: set the wallpaper the calendar calls "
                             "for, if it is not already set, then exit")
    parser.add_argument("--force", action="store_true",
                        help="with --auto, act even on a period already "
                             "applied and even when the rotation is switched off")
    parser.add_argument("--quiet", action="store_true",
                        help="with --auto, print only when something "
                             "changes or fails — what the timer runs")
    parser.add_argument("--auto-on", action="store_true",
                        help="switch the rotation back on and put this "
                             "period's wallpaper up straight away")
    parser.add_argument("--auto-off", action="store_true",
                        help="switch the rotation off; nothing changes the "
                             "wallpaper again until you switch it back on")
    parser.add_argument("--auto-toggle", action="store_true",
                        help="the one to bind to a key: off if it is on, on "
                             "and applied if it is off")
    parser.add_argument("--period", action="store_true",
                        help="print the period today falls in and exit")
    parser.add_argument("--install-timer", action="store_true",
                        help="install the platform's scheduled task/timer "
                             "for the calendar rotation")
    parser.add_argument("--uninstall-timer", action="store_true",
                        help="remove the scheduled task/timer")
    parser.add_argument("--version", action="store_true",
                        help="print the version and how this copy was "
                             "installed, and exit")
    parser.add_argument("--update", action="store_true",
                        help="install the latest release, if it is newer "
                             "(packaged builds only)")
    parser.add_argument("--backend", action="store_true",
                        help="print which wallpaper backend this platform "
                             "will use, and exit")
    return parser


def apply_overrides(prefs, args):
    """The filters a command line asks for, folded into prefs in place.

    Shared by the process that starts the window and by the one that hands its
    arguments to an already-running window, so `--theme spring` means the same
    thing either way.
    """
    if args.source:
        prefs["source"] = args.source
    if args.theme:
        # "now" is resolved to a real theme here and never stored as itself: a
        # config saying "now" would quietly turn every future run of the window
        # into a second rotation, which is what --auto is for.
        prefs["theme"] = (core.current_period(date.today(), prefs["easter"])[0]
                          if args.theme == "now" else args.theme)
    if args.orientation:
        prefs["orientation"] = args.orientation
    return any((args.source, args.theme, args.orientation))


def main(argv=None):
    prefs = core.load_prefs()
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    apply_overrides(prefs, args)

    if args.period:
        theme, period = core.current_period(date.today(), prefs["easter"])
        print(f"{period}\t{core.theme_label(theme)}"
              f"\t{'on' if prefs['auto_enabled'] else 'off'}")
        return 0

    if args.version:
        from . import __version__, update
        print(f"random-wallpaper {__version__} ({update.describe_install()})")
        return 0

    if args.update:
        from . import __version__, update
        try:
            release, newer = update.check()
            if not newer:
                print(f"{__version__} is the latest")
                return 0
            print(update.apply(release))
        except update.UpdateError as exc:
            print(f"not updated: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.backend:
        from . import desktop
        print(desktop.describe_backend())
        return 0

    if args.install_timer:
        from . import schedule
        where = schedule.install()
        print(f"installed — {where}")
        return 0

    if args.uninstall_timer:
        from . import schedule
        schedule.uninstall()
        print("removed")
        return 0

    # Everything below this line that does not draw a window runs before Qt
    # is ever asked for one. The timer, the login spawn and the keybinds all
    # land here, and none of them has a display to draw on.
    if args.auto_off:
        core.set_auto_enabled(prefs, False)
        print("automatic rotation off — nothing will change the wallpaper")
        return 0

    if args.auto_on:
        return core.resume_auto(prefs)

    if args.auto_toggle:
        if prefs["auto_enabled"]:
            core.set_auto_enabled(prefs, False)
            print("automatic rotation off — nothing will change the wallpaper")
            return 0
        return core.resume_auto(prefs)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if args.auto:
        # No pruning here: the timer ticks every minute, and a tidy-up that
        # often has no business near a window's cache.
        return core.run_auto(prefs, force=args.force, quiet=args.quiet)

    core.prune_cache()

    from .ui.app import run_app
    return run_app(prefs, args)


if __name__ == "__main__":
    sys.exit(main())
