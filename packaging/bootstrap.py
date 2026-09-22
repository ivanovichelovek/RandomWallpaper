"""PyInstaller's entry script.

Not randomwallpaper/__main__.py: PyInstaller runs its entry script as a
top-level module named __main__, outside any package — so __main__.py's own
`from .cli import main` (a relative import, valid only inside the
randomwallpaper package) fails at startup with "attempted relative import
with no known parent package". This script imports randomwallpaper as an
ordinary installed package instead, which is what actually works in a
PyInstaller build; python -m randomwallpaper (a real run from source) keeps
using __main__.py as before, where the relative import is correct.
"""
import sys

from randomwallpaper.cli import main

if __name__ == "__main__":
    sys.exit(main())
