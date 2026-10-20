# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
Tests for the programs-and-files watcher.

The important one is the GIL check: ReadDirectoryChangesW blocks, and a
blocking call that does NOT release the interpreter lock would freeze the
whole program. That exact failure has already bitten this project once, so
it is checked rather than assumed.
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import activitywatch  # noqa: E402

FAILS = []


def check(name, cond, note=""):
    print(f"  [{'ok ' if cond else 'FAIL'}] {name}" + (f"  ({note})" if note else ""))
    if not cond:
        FAILS.append(name)


def main():
    print("=== 1. the Recent Items folder is watchable ===")
    folder = activitywatch.recent_folder()
    check("folder found", os.path.isdir(folder), folder)

    print("\n=== 2. blocking file watch must NOT hold the GIL ===")
    watcher = activitywatch.ActivityWatcher()
    watcher.start()
    time.sleep(2.0)          # let it reach the blocking read

    # If ReadDirectoryChangesW held the lock, this loop would stall.
    ticks = 0
    start = time.time()
    while time.time() - start < 3.0:
        ticks += 1
        time.sleep(0.01)
    check("main thread kept running while blocked", ticks > 200,
          f"{ticks} ticks in 3s")
    check("watcher started", watcher.started_ok)
    check("no startup error", not watcher.error, watcher.error or "none")

    print("\n=== 3. a file opening is noticed ===")
    # Dropping a shortcut into Recent Items is exactly what Windows does when
    # you open a document, so this exercises the real path.
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    probe_target = os.path.abspath(__file__)
    link = os.path.join(folder, "SystemWatch probe document.txt.lnk")
    shell = win32com.client.Dispatch("WScript.Shell")
    sc = shell.CreateShortCut(link)
    sc.TargetPath = probe_target
    sc.save()

    seen = []
    deadline = time.time() + 8
    while time.time() < deadline and not seen:
        seen = [r for r in watcher.drain()
                if "probe document" in r.get("name", "")]
        time.sleep(0.2)
    check("file open detected", bool(seen),
          seen[0]["name"] if seen else "nothing within 8s")
    if seen:
        check("resolved to a real path", bool(seen[0]["path"]),
              seen[0]["path"][:60])
        check("tagged as a file", seen[0]["kind"] == "file")

    try:
        os.unlink(link)
    except OSError:
        pass

    print("\n=== 4. process polling is cheap ===")
    import psutil
    t0 = time.perf_counter()
    for _ in range(50):
        set(psutil.pids())
    per = (time.perf_counter() - t0) / 50 * 1000
    print(f"          psutil.pids(): {per:.3f} ms per poll")
    check("poll is cheap", per < 5.0, f"{per:.3f} ms")
    budget = per / (activitywatch.POLL_SECONDS * 1000) * 100
    print(f"          => about {budget:.4f}% of one core just to poll")
    check("polling budget is tiny", budget < 0.5, f"{budget:.4f}%")

    print("\n=== 5. window-owner lookup is cheap ===")
    t0 = time.perf_counter()
    for _ in range(20):
        pids = activitywatch._visible_window_pids()
    per = (time.perf_counter() - t0) / 20 * 1000
    print(f"          EnumWindows: {per:.2f} ms, {len(pids)} windowed pids")
    check("window scan is cheap", per < 25.0, f"{per:.2f} ms")

    print("\n=== 6. noise is filtered ===")
    check("explorer.exe skipped",
          "explorer.exe" in activitywatch.SKIP_PROGRAMS)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source = ("", {os.path.normcase(os.path.join(here, "recorder.py")),
                   os.path.normcase(os.path.join(here, "main.py"))})
    py = r"C:\Python\pythonw.exe"
    check("own recorder (absolute script) skipped",
          activitywatch._is_self(
              {"exe": py, "cmdline": [py, os.path.join(here, "recorder.py")]},
              source))
    check("own window (relative script + cwd) skipped",
          activitywatch._is_self(
              {"exe": py, "cmdline": [py, "main.py", "--tray"], "cwd": here},
              source))
    check("an ordinary program is not skipped",
          not activitywatch._is_self({"exe": r"C:\Program Files\app.exe",
                                      "cmdline": []}, source))
    # These are the evasions the old name-based check allowed.
    check("a stranger named systemwatch.exe is NOT skipped",
          not activitywatch._is_self(
              {"exe": r"C:\Temp\systemwatch.exe", "cmdline": []}, source))
    check("someone else's main.py is NOT skipped",
          not activitywatch._is_self(
              {"exe": py, "cmdline": [py, r"C:\other\main.py"]}, source))
    packaged = (os.path.normcase(r"C:\Apps\SystemWatch\SystemWatch.exe"), set())
    check("packaged: own exe skipped",
          activitywatch._is_self(
              {"exe": r"C:\Apps\SystemWatch\SystemWatch.exe"}, packaged))
    check("packaged: a copy elsewhere is NOT skipped",
          not activitywatch._is_self(
              {"exe": r"C:\Users\x\Downloads\SystemWatch.exe"}, packaged))

    print("")
    print("=== 6b. shell protocol activations are not files ===")
    for junk in ("ms-gamingoverlay--- (342)",
                 "ms-screenclip---source=PrintScreen (27)"):
        check("skipped: " + junk[:32],
              activitywatch.is_protocol_entry(junk))
    for real in ("report.docx", "ms-paint-project.txt", "Traffic volume"):
        check("kept: " + real, not activitywatch.is_protocol_entry(real))

    print("\n=== 7. stop() returns promptly (no deadlock) ===")
    done = threading.Event()

    def stopper():
        watcher.stop()
        done.set()

    threading.Thread(target=stopper, daemon=True).start()
    check("stop() finished quickly", done.wait(8), "8s limit")

    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL ACTIVITY TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
