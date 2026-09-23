#!/bin/sh
# Refresh the launcher and icon caches, where the desktop has them. Neither
# is required — a missing tool only means the menu picks the entry up at the
# next login instead of now.
command -v update-desktop-database >/dev/null 2>&1 \
    && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 \
    && gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
exit 0
