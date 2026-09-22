"""The Qt application: single-instance, and argument forwarding to a window
that is already open.

GTK's Gio.Application gave the original this for free through
HANDLES_COMMAND_LINE. Qt has no equivalent, so it is built here on
QLocalServer/QLocalSocket: the first launch opens a local socket named after
the app id; a second launch finds it, writes its argv as JSON, and exits —
the first process reads it back and calls retheme() on the window that is
already open, exactly as `random-wallpaper --theme now` did against a
running instance in the original.
"""
import json
import sys

from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from .. import core
from ..paths import APP_ID
from . import style
from .window import Reel

ICON_PATH = Path(__file__).resolve().parent.parent / "resources" / "icon.svg"

SOCKET_NAME = APP_ID + ".single-instance"


class _InstanceBridge(QObject):
    args_received = Signal(list)


def _try_forward(argv):
    """True if another instance is already running and has taken the args."""
    socket = QLocalSocket()
    socket.connectToServer(SOCKET_NAME)
    if not socket.waitForConnected(200):
        return False
    socket.write(json.dumps(argv).encode("utf-8"))
    socket.flush()
    socket.waitForBytesWritten(1000)
    socket.disconnectFromServer()
    return True


def run_app(prefs, args):
    # Forward to a window that is already open, the way a second launch of
    # `random-wallpaper --theme now` should retheme the reel on screen rather
    # than doing nothing while an unrelated process exits quietly.
    if _try_forward(sys.argv[1:]):
        return 0

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Random Wallpaper")
    app.setOrganizationName("ivanovichchelovek")
    app.setDesktopFileName(APP_ID)
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    style.apply(app)

    server = QLocalServer()
    # A stale socket file from a crashed instance would otherwise make every
    # later launch believe a window is already open, and nothing would ever
    # appear again until the file was removed by hand.
    QLocalServer.removeServer(SOCKET_NAME)
    server.listen(SOCKET_NAME)

    win = Reel(app, prefs)

    def handle_new_connection():
        conn = server.nextPendingConnection()
        if conn is None:
            return

        def read():
            data = bytes(conn.readAll())
            conn.disconnectFromServer()
            try:
                argv = json.loads(data.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return
            from ..cli import apply_overrides, build_parser
            parsed = build_parser().parse_args(argv)
            changed = apply_overrides(prefs, parsed)
            win.show()
            win.raise_()
            win.activateWindow()
            if changed:
                win.retheme()

        conn.readyRead.connect(read)

    server.newConnection.connect(handle_new_connection)

    win.show()
    return app.exec()
