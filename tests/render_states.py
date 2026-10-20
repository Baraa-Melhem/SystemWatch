# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
Render the UI states that only appear after an interaction.

Empty search results, the paused header and the settings dialog cannot be
reached by opening the window and taking a screenshot, and driving them with
synthetic mouse clicks is flaky. This builds the real widgets, puts them in
the state, and grabs them straight off Qt's backing store.

    python tests/render_states.py [output-dir]

Read-only: it renders widgets and writes PNGs to the output directory. The
records are sandboxed so nothing here can touch the real ones.
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

_real = {"LOCALAPPDATA": os.environ.get("LOCALAPPDATA"),
         "APPDATA": os.environ.get("APPDATA")}
_box = tempfile.mkdtemp(prefix="swrender-")
for _var, _sub in (("LOCALAPPDATA", "local"), ("APPDATA", "roaming")):
    _dir = os.path.join(_box, _sub)
    os.makedirs(os.path.join(_dir, "SystemWatch"), exist_ok=True)
    for _name in ("device-history.jsonl", "activity-history.jsonl"):
        _src = os.path.join(_real[_var] or "", "SystemWatch", _name)
        if os.path.exists(_src):
            shutil.copy2(_src, os.path.join(_dir, "SystemWatch", _name))
    os.environ[_var] = _dir

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

import ui as uimod  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "_render")
os.makedirs(OUT, exist_ok=True)


def shot(widget, name):
    path = os.path.join(OUT, name + ".png")
    widget.grab().save(path)
    print(f"  {name:24} {widget.width()}x{widget.height()}  -> {path}")


def main():
    window = uimod.MainWindow(start_hidden=True)
    window.resize(1160, 760)
    window.show()
    app.processEvents()
    for _ in range(4):
        window._drain()
        app.processEvents()

    print("states:")

    # 1. A search with no matches.
    window.search.setText("zzzznothingmatchesthis")
    app.processEvents()
    shot(window, "empty_no_match")

    # 2. Every severity switched off -> guarded, so filter by chatter only.
    window.search.setText("")
    window.proxy.set_severities({uimod.ERROR})
    window._update_status_text()
    app.processEvents()
    shot(window, "empty_filtered_out")

    # 3. Paused: grey pill, and Resume becomes the accent button.
    window.proxy.set_severities({uimod.ERROR, uimod.WARN, uimod.INFO})
    window.toggle_pause()
    app.processEvents()
    shot(window, "paused")
    window.toggle_pause()
    app.processEvents()

    # 4. An error-severity detail pane. The wash and rail for ERROR are
    #    otherwise unreachable on a healthy machine.
    from datetime import datetime
    window.model.add_events([{
        "channel": "Application",
        "provider": "Application Error",
        "event_id": 1000,
        "level": 2,
        "record_id": "99999",
        "computer": "DESKTOP-DEMO",
        "time": datetime.now(),
        "fields": {},
        "message": (
            "Faulting application name: example.exe, version 1.0.0.0, "
            "faulting module name: ntdll.dll, exception code: 0xc0000374."
        ),
        "raw_level_severity": "error",
        "title": "A program crashed",
        "meaning": (
            "example.exe stopped working and Windows closed it. The fault "
            "was inside ntdll.dll, which usually points at memory "
            "corruption in the program itself rather than at Windows."
        ),
        "action": (
            "Reopen the program. If it keeps crashing, update it or "
            "reinstall it."
        ),
        "severity": uimod.ERROR,
        "noisy": False,
        "known": True,
        "kind": "",
    }])
    window._update_counters()
    window.proxy.set_severities({uimod.ERROR})
    app.processEvents()
    window.table.selectRow(0)
    window._on_select()
    app.processEvents()
    shot(window, "detail_error")
    window.proxy.set_severities({uimod.ERROR, uimod.WARN, uimod.INFO})
    app.processEvents()

    # 5. The settings dialog. The stylesheet is application-wide, so a
    #    parentless dialog picks it up like the real one does.
    dialog = uimod.SettingsDialog(window.cfg, window.access, None)
    dialog.show()
    app.processEvents()
    shot(dialog, "settings")
    dialog.close()

    # 6. First-run welcome and About. Shown, not exec'd - exec_ would wait
    #    for a click that never comes.
    for name, made in (("welcome", uimod.welcome_dialog(window.cfg)),
                       ("about", uimod.about_dialog())):
        made.show()
        app.processEvents()
        shot(made, name)
        made.close()

    # 7. The row context menu.
    window.tabs.setCurrentIndex(0)
    window.table.selectRow(0)
    app.processEvents()

    # 8. Programs & Files with recording switched off.
    window.cfg["record_activity"] = False
    uimod.save_config(window.cfg)
    window.tabs.setCurrentIndex(2)
    window.activity_panel.refresh()
    app.processEvents()
    shot(window, "activity_off")

    window.hide()
    window.tray.hide()
    print("done")
    return 0


try:
    code = main()
finally:
    for _var in ("LOCALAPPDATA", "APPDATA"):
        os.environ[_var] = _real[_var] or ""
    shutil.rmtree(_box, ignore_errors=True)
os._exit(code)
