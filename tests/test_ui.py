# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
Window tests: all three tabs, and both records reaching the screen.

Runs against a sandboxed copy of the records, so it never writes to the real
ones. Seeded with copies of whatever is really there so the assertions stay
meaningful.
"""
import os
import shutil
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

_real = {"LOCALAPPDATA": os.environ.get("LOCALAPPDATA"),
         "APPDATA": os.environ.get("APPDATA")}
_box = tempfile.mkdtemp(prefix="swui-")
for _var, _sub in (("LOCALAPPDATA", "local"), ("APPDATA", "roaming")):
    _dir = os.path.join(_box, _sub)
    os.makedirs(os.path.join(_dir, "SystemWatch"), exist_ok=True)
    for _name in ("device-history.jsonl", "activity-history.jsonl"):
        _src = os.path.join(_real[_var] or "", "SystemWatch", _name)
        if os.path.exists(_src):
            shutil.copy2(_src, os.path.join(_dir, "SystemWatch", _name))
    os.environ[_var] = _dir

from PyQt5.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

import history  # noqa: E402
import ui as uimod  # noqa: E402
from translations import ERROR, INFO, WARN  # noqa: E402

FAILS = []


def check(name, cond, note=""):
    print(f"  [{'ok ' if cond else 'FAIL'}] {name}" + (f"  ({note})" if note else ""))
    if not cond:
        FAILS.append(name)


def run(name, fn):
    try:
        fn()
        check(name, True)
    except Exception:
        check(name, False)
        traceback.print_exc()


def main():
    devices, dstat = history.load()
    acts, astat = history.load_activity()
    print(f"sandbox: {len(devices)} device entries ({dstat}), "
          f"{len(acts)} activity entries ({astat})")

    print("\n=== window opens ===")
    window = uimod.MainWindow(start_hidden=True)
    check("three tabs", window.tabs.count() == 3,
          " | ".join(window.tabs.tabText(i) for i in range(3)))
    # Qt returns the mnemonic-escaped form here; "&&" displays as one "&".
    shown = [window.tabs.tabText(i).replace("&&", "&") for i in range(3)]
    check("tab names readable",
          shown == ["Live events", "Devices & Network", "Programs & Files"],
          " | ".join(shown))

    print("\n=== both records reach the main list ===")
    rows = [window.model.event_at(i) for i in range(window.model.rowCount())]
    dev_rows = [r for r in rows if r.get("provider") == "Device recorder"]
    act_rows = [r for r in rows if r.get("provider") == "Activity recorder"]
    check("every device entry shown", len(dev_rows) == len(devices),
          f"{len(dev_rows)}/{len(devices)}")
    check("every activity entry shown", len(act_rows) == len(acts),
          f"{len(act_rows)}/{len(acts)}")
    for r in act_rows[:3]:
        print(f"      {r['time'].strftime('%d %b %H:%M')}  {r['title']}")

    print("\n=== recorded rows are never folded together ===")
    before = window.model.rowCount()
    history.append_activity("program", "dup.exe", r"C:\dup.exe")
    history.append_activity("program", "dup.exe", r"C:\dup.exe")
    fresh = window._new_activity_events()
    window.model.add_events(fresh)
    check("two identical launches stay two rows",
          window.model.rowCount() == before + 2,
          f"{window.model.rowCount() - before} added")

    print("\n=== survives the chatter filter ===")
    window.proxy.set_hide_noisy(True)
    visible = 0
    for row in range(window.proxy.rowCount()):
        src = window.proxy.mapToSource(window.proxy.index(row, 0))
        ev = window.model.event_at(src.row())
        if ev and ev.get("provider") in ("Device recorder", "Activity recorder"):
            visible += 1
    check("recorded rows still visible", visible == len(dev_rows) + len(act_rows) + 2,
          f"{visible} visible")

    print("\n=== no duplicates on a re-read ===")
    window._history_sig = None
    window._activity_sig = None
    check("device re-read adds nothing", not window._new_record_events())
    check("activity re-read adds nothing", not window._new_activity_events())

    print("\n=== panels render ===")
    run("devices panel", window.device_panel.refresh)
    run("programs panel", window.activity_panel.refresh)
    html_text = window.activity_panel.view.toHtml()
    check("programs section present", "PROGRAMS OPENED" in html_text)
    check("files section present", "FILES OPENED" in html_text)
    check("honest scope note present",
          "Administrator" in html_text and "does not appear here" in html_text)
    check("headline counts something",
          "recorded" in window.activity_panel.headline.text(),
          window.activity_panel.headline.text())

    print("\n=== detail pane wording for recorded rows ===")
    if act_rows:
        detail = window._detail_html(act_rows[0])
        check("does not blame Windows for silence",
              "Windows did not supply" not in detail)
        check("no unfilled placeholders", "{" not in detail.split("style=")[0])

    print("\n=== copying an event, and hostile text ===")
    if act_rows:
        text = uimod.event_as_text(act_rows[0])
        check("copy text leads with the title",
              text.startswith(act_rows[0]["title"]))
        check("copy text carries the event ID", "Event ID" in text)
    # Device names come from USB descriptors and file names from whoever
    # named the file - both attacker-controlled. They must render as text.
    hostile = dict(act_rows[0]) if act_rows else None
    if hostile:
        hostile["title"] = '<img src="x"><a href="file:///C:/">click</a>'
        hostile["meaning"] = "<script>alert(1)</script>"
        page = window._detail_html(hostile)
        check("markup in a title is escaped", "<img" not in page
              and "&lt;img" in page)
        check("markup in a meaning is escaped", "<script>" not in page)
    check("detail pane will not follow links",
          not window.detail.openLinks())

    print("\n=== layout and shortcuts ===")
    window._remember_layout()
    check("geometry captured as hex", bool(window.cfg["geometry"])
          and all(c in "0123456789abcdef" for c in window.cfg["geometry"]))
    run("restore layout", window._restore_layout)
    run("refresh current tab", window._refresh_current)
    run("focus search", window._focus_search)

    print("\n=== controls still work ===")
    run("pause", window.toggle_pause)
    run("resume", window.toggle_pause)
    run("severity filter", lambda: window.proxy.set_severities({ERROR, WARN, INFO}))
    run("search", lambda: window.proxy.set_text("dup"))
    run("clear search", lambda: window.proxy.set_text(""))
    run("stats", window._update_stats)
    run("status text", window._update_status_text)
    run("clear view", window._clear_view)
    run("quit", window.quit_app)

    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL UI TESTS PASSED")
    return 0


try:
    code = main()
finally:
    for _var in ("LOCALAPPDATA", "APPDATA"):
        os.environ[_var] = _real[_var] or ""
    shutil.rmtree(_box, ignore_errors=True)
os._exit(code)
