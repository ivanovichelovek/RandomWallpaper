"""The rotation while the app is closed: `random-wallpaper --auto --quiet`.

AutoJob.java starts this every 15 minutes or so, in a process of its own
with no Qt in it. main.py's top half — HOME, the CA bundle, the JNI helper —
is what this needs as well; its window part only runs as __main__.
"""
import main  # noqa: F401  (the environment, as the app sets it up)
from randomwallpaper import core

lines = []
status = core.run_auto(core.load_prefs(), log=lines.append, quiet=True)
# Where logcat can see it: what the run did, if anything.
print(f"rw-auto: {status} {lines[-1] if lines else ''}", flush=True)
