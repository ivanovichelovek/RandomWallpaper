"""The rotation while the app is closed: `random-wallpaper --auto --quiet`.

AutoJob.java starts this every 15 minutes or so, in a process of its own
with no Qt in it. main.py's top half — HOME, the CA bundle, the JNI helper —
is what this needs as well; its window part only runs as __main__.

It must not end the way a script does. python-for-android finalizes Python
and calls exit() after it, and exit() with the Java VM running crashed the
process before the job was marked finished. So the job is ended from here,
and the process with it.
"""
import os

try:
    import main  # noqa: F401  (the environment, as the app sets it up)
    from randomwallpaper import core

    lines = []
    status = core.run_auto(core.load_prefs(), log=lines.append, quiet=True)
    # Where logcat can see it: what the run did, if anything.
    print(f"rw-auto: {status} {lines[-1] if lines else ''}", flush=True)
except BaseException:
    import traceback
    print("rw-auto: failed\n" + traceback.format_exc(), flush=True)
finally:
    try:
        from randomwallpaper.desktop import android
        android.auto_done()             # does not return when it works
    except BaseException as exc:
        print(f"rw-auto: could not end the job: {exc}", flush=True)
    os._exit(0)
