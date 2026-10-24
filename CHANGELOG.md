# Changelog

Each release's section is published as its GitHub release text, and is what
the app shows when it offers that update.

## 1.4.1

- Android: the Settings tab fits the phone's width. Rows that do not fit
  side by side stack, and nothing scrolls sideways any more.
- Android: Theme, Orientation and Minimum resolution in Settings no longer
  crash the app. Their lists open as a sheet inside the app.
- A fresh install no longer changes the wallpaper by itself. Changing it
  automatically is off until you switch it on in Settings.
- The update offer now shows what changed — every release since the one
  you have, not only the latest.
- The Saved tab can show only the wallpapers pinned to one season or
  holiday, or only the shuffle set. The list says how many each one holds.
- The whole app works from the keyboard:
  - Tab reaches every control, and a ring shows where the focus is. A mouse
    click leaves no ring behind.
  - The arrow keys pick an option in a row of choices. In the Saved grid
    they move between pictures.
  - Enter presses the focused button.
  - Ctrl+F or / jumps to the Saved search.
  - F1 or ? lists every shortcut. "Show shortcuts" in Settings does too.
- The keys for the Random tab (S, Space, Enter, the arrows, N, P) work only
  on that tab, so they no longer take keys away from the other two.

## 1.4.0

- **Android.** Random Wallpaper is now an Android app. The release has an
  APK for phones (arm64) and one for emulators (x86_64).
  - It sets the home and lock screen wallpaper.
  - It changes the wallpaper on schedule even while the app is closed.
  - It updates itself from inside the app.
- **A new look.**
  - The colours come from the wallpaper on screen.
  - The sections are in a rail at the side, or along the bottom on a phone.
  - Light and dark themes, following the system or set by hand.
  - New built-in fonts.
- **Settings regrouped.**
  - How the wallpaper changes by itself (by the calendar, or a shuffle of
    starred pictures) is chosen from two cards.
  - Settings now say when the next change is due. A "Change now" button is
    next to that.
  - The screens setting and the minimum resolution are still there, under
    their own headings.
