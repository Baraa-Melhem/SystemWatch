# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
SystemWatch - a read-only, low-overhead Windows event monitor.

    pythonw main.py           open the window
    pythonw main.py --tray    start hidden in the notification area

This program only ever reads from the Windows Event Log. See the module
docstring in watcher.py for exactly which API calls that involves and why
they cannot modify anything.
"""

import os
import sys
import warnings

warnings.filterwarnings("ignore")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMessageBox

# High-DPI attributes must be set before the QApplication exists.
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


GUI_MUTEX = "SystemWatchWindowInstance"
SHOW_EVENT = "SystemWatchWindowShow"


def _claim_window():
    """
    Returns (handle, already_running).

    Launching SystemWatch twice used to leave two windows running - one of
    them hidden in the tray, quietly showing whatever it had loaded when it
    started. Closing "the program" then reopened a third, while the stale one
    kept its tray icon. Claiming a named mutex makes the second launch hand
    over to the first instead.
    """
    import win32api
    import win32event
    import winerror

    handle = win32event.CreateMutex(None, False, GUI_MUTEX)
    return handle, win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS


def _wake_existing_window():
    """Ask the already-running copy to show itself."""
    import win32api
    import win32event

    try:
        event = win32event.OpenEvent(
            win32event.EVENT_MODIFY_STATE, False, SHOW_EVENT
        )
    except Exception:
        return False
    if not event:
        return False
    win32event.SetEvent(event)
    win32api.CloseHandle(event)
    return True


ERROR_LOG_MAX = 256 * 1024


def _install_error_log():
    """
    Keep the app alive through a bug, and leave a note about it.

    PyQt5 aborts the whole process when an exception escapes a slot, and the
    packaged exe has no console - so without this a single bad click would
    close SystemWatch with no message and no trace. Instead the traceback is
    appended to error.log beside the settings (capped, oldest half dropped)
    and the window carries on.
    """
    import traceback
    from datetime import datetime

    import config

    def hook(kind, value, tb):
        try:
            path = os.path.join(config.folder(), "error.log")
            if os.path.exists(path) and os.path.getsize(path) > ERROR_LOG_MAX:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    keep = fh.read()[-ERROR_LOG_MAX // 2:]
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(keep)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"\n--- {datetime.now():%Y-%m-%d %H:%M:%S}\n")
                fh.write("".join(traceback.format_exception(kind, value, tb)))
        except Exception:
            pass

    sys.excepthook = hook


def main():
    _install_error_log()
    guard, already_running = _claim_window()
    if already_running:
        _wake_existing_window()
        return

    app = QApplication(sys.argv)
    app.setApplicationName("SystemWatch")
    from version import __version__
    app.setApplicationVersion(__version__)
    # Hiding the window must not end the process - the tray icon lives on.
    app.setQuitOnLastWindowClosed(False)

    from PyQt5.QtWidgets import QSystemTrayIcon

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.warning(
            None,
            "SystemWatch",
            "Windows is not offering a notification area right now, so the "
            "tray icon will be unavailable. The window itself still works.",
        )

    from ui import MainWindow

    start_hidden = "--tray" in sys.argv
    window = MainWindow(start_hidden=start_hidden)
    app.window = window  # keep a reference alive

    if start_hidden:
        window.tray.showMessage(
            "SystemWatch is running",
            "Monitoring quietly in the background. Click the shield icon to "
            "open it, or right-click to pause or quit.",
            QSystemTrayIcon.Information,
            4000,
        )

    app._instance_guard = guard   # keep the claim alive for the session
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
