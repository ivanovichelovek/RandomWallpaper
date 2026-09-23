#!/usr/bin/env python3
"""Render resources/icon.svg into the icon formats the installers need.

  packaging/windows/icon.ico            16–256 px, PNG-compressed entries
  packaging/macos/icon.iconset/         the PNG set `iconutil -c icns` takes
  packaging/linux/icons/<n>x<n>.png     for the hicolor theme next to the SVG

Qt draws the SVG, so this needs nothing the app does not already depend on,
and runs the same on all three CI runners. Generated, not committed: the SVG
stays the one source.
"""
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "randomwallpaper" / "resources" / "icon.svg"


def render(renderer, size):
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()
    return image


def png_bytes(image):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def write_ico(path, images):
    """An .ico of PNG entries — valid since Vista, and all the installer and
    the Start menu read."""
    blobs = [(size, png_bytes(img)) for size, img in images]
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries, payload = b"", b""
    for size, blob in blobs:
        side = 0 if size >= 256 else size       # 0 means 256 in an ICONDIR
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32,
                               len(blob), offset + len(payload))
        payload += blob
    path.write_bytes(header + entries + payload)


def main():
    app = QGuiApplication(sys.argv[:1])  # noqa: F841 — Qt needs one to paint
    renderer = QSvgRenderer(str(SVG))
    if not renderer.isValid():
        print(f"cannot read {SVG}", file=sys.stderr)
        return 1

    ico = ROOT / "packaging" / "windows" / "icon.ico"
    ico.parent.mkdir(parents=True, exist_ok=True)
    write_ico(ico, [(n, render(renderer, n)) for n in (16, 24, 32, 48, 64, 128, 256)])

    iconset = ROOT / "packaging" / "macos" / "icon.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    for n in (16, 32, 128, 256, 512):
        render(renderer, n).save(str(iconset / f"icon_{n}x{n}.png"))
        render(renderer, n * 2).save(str(iconset / f"icon_{n}x{n}@2x.png"))

    linux = ROOT / "packaging" / "linux" / "icons"
    linux.mkdir(parents=True, exist_ok=True)
    for n in (48, 128, 256):
        render(renderer, n).save(str(linux / f"{n}x{n}.png"))

    print(f"wrote {ico}, {iconset}, {linux}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
