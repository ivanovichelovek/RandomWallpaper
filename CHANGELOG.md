# Changelog

Each release's section is published as its GitHub release text, and is what
the app shows when it offers that update.

## 1.5.0

- Two new sources, both of anime art with millions of pictures:
  - **Danbooru**, general (safe) rating only. Season or holiday,
    orientation and size are all filtered on its server.
  - **Safebooru**, a board of safe posts only.

  Comics and pages of text are skipped on both, as are very long or very
  wide images. For a Halloween portrait at 1080×1920 or more, Danbooru has
  thousands of pictures where Wallhaven has five.
- Konachan with Portrait now takes its pictures from Danbooru.
- No more repeats while there is something new: the app remembers the last
  300 pictures it showed, on every source. A small pool goes round all of
  them before one comes back.
- Random sources are no longer answered from the day-long cache.
- Skip no longer shows "Dropped …": the next picture coming up says enough.
  Other messages now show at the top and let taps through, so they never
  cover Skip, Keep or Set.
- The Random tab forgets pictures more than 8 behind the one you are on,
  files and all, so a long session does not fill the cache. Settings →
  The reel → "Forget pictures far behind" switches it off.
- Swiping through the Random tab no longer stutters. The app recolours
  itself after the picture's colours once you stop, not on every picture
  on the way.
- Android: Keep (or Set) no longer throws away the pictures already
  downloaded on the Random tab. Setting a wallpaper makes Android restart
  the app, and the reel now comes back as it was.

## 1.4.2

- Portrait works. The minimum resolution now turns upright with it, so
  1920×1080 means 1080 wide and 1920 tall. Konachan has no portrait
  pictures at all, so with Portrait the pictures come from Wallhaven, and
  Settings says so.
- Android: every tab fits screens down to 240 dp wide, and landscape too.
  Saved's buttons stack when two by two does not fit, and Theme no longer
  shows a cut-off name in landscape.
- Android 1.4.0 crashed at start as soon as a newer version was out: its
  update offer opened a window of its own. 1.4.1 fixed that. If you still
  have 1.4.0, install the 1.4.1 or later APK by hand once.

## 1.4.1

- Android: the Settings tab fits the phone's width. Rows that do not fit
  side by side stack, and nothing scrolls sideways any more.
- Android: lists, menus and the update offer no longer crash the app on a
  real phone. Theme, Orientation, Minimum resolution, Pin to… and the
  update offer open as a sheet inside the app.
- Android: "Every" shows its number again and is picked from a list.
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
