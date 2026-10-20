# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
Tests for the tamper-evident rolling records.

Runs entirely inside a temporary sandbox - it never touches the real record.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_box = tempfile.mkdtemp(prefix="swtest-")
os.environ["LOCALAPPDATA"] = os.path.join(_box, "local")
os.environ["APPDATA"] = os.path.join(_box, "roaming")
for _d in (os.environ["LOCALAPPDATA"], os.environ["APPDATA"]):
    os.makedirs(_d, exist_ok=True)

import history  # noqa: E402

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'ok ' if ok else 'FAIL'}] {name}")
    if not ok:
        print(f"          got : {got!r}\n          want: {want!r}")
        FAILS.append(name)


def check_true(name, cond, note=""):
    check(name + (f" ({note})" if note else ""), bool(cond), True)


def reset():
    shutil.rmtree(_box, ignore_errors=True)
    for d in (os.environ["LOCALAPPDATA"], os.environ["APPDATA"]):
        os.makedirs(d, exist_ok=True)


def main():
    print("=== device record: basic append ===")
    reset()
    history.append("connected", "Test Phone", "USB device", "USB\\VID_1")
    history.append("disconnected", "Test Phone", "USB device", "USB\\VID_1")
    entries, status = history.load()
    check("two entries", len(entries), 2)
    check("status ok", status, "ok")
    check("seq numbering", [e["seq"] for e in entries], [1, 2])
    check_true("chain verifies", history.verify(entries)[0])
    check("describe reads plainly",
          history.describe(entries[0]), "Test Phone connected")

    print("\n=== both copies written and identical ===")
    check_true("primary exists", os.path.exists(history.primary_path()))
    check_true("backup exists", os.path.exists(history.backup_path()))
    check("copies identical",
          open(history.primary_path(), encoding="utf-8").read(),
          open(history.backup_path(), encoding="utf-8").read())

    print("\n=== rolling window of 50 ===")
    for i in range(60):
        history.append("connected", f"Device {i}", "USB device")
    entries, status = history.load()
    check("capped at MAX_ENTRIES", len(entries), history.MAX_ENTRIES)
    check("newest kept", entries[-1]["name"], "Device 59")
    check("seq keeps counting past the window", entries[-1]["seq"], 62)
    check("rolling is not tampering", status, "ok")
    check_true("chain still verifies", history.verify(entries)[0])
    size = os.path.getsize(history.primary_path())
    print(f"          file at full capacity: {size} bytes")
    check_true("stays small", size < 40 * 1024, f"{size} bytes")

    print("\n=== tamper: edit an entry ===")
    entries, _ = history.load()
    entries[10]["name"] = "innocent thing"
    history._write_file(history.primary_path(), entries)
    history._write_file(history.backup_path(), entries)
    _, status = history.load()
    check_true("edit detected", status.startswith("tampered"), status[:52])

    print("\n=== tamper: delete a line from the middle ===")
    reset()
    for i in range(6):
        history.append("connected", f"Dev{i}", "USB device")
    entries, _ = history.load()
    del entries[2]
    history._write_file(history.primary_path(), entries)
    history._write_file(history.backup_path(), entries)
    _, status = history.load()
    check_true("mid-file deletion detected",
               status.startswith("tampered"), status[:52])

    print("\n=== damaged file kept as evidence, fresh chain started ===")
    history.append("connected", "after tamper", "USB device")
    damaged = [f for f in os.listdir(os.path.dirname(history.primary_path()))
               if ".damaged-" in f]
    check_true("damaged copy kept", len(damaged) >= 1, str(damaged[:1]))
    entries, status = history.load()
    check("fresh chain", status, "ok")
    check("fresh chain has one entry", len(entries), 1)

    print("\n=== recovery: one copy deleted ===")
    reset()
    for i in range(5):
        history.append("connected", f"Dev{i}", "USB device")
    os.unlink(history.primary_path())
    entries, status = history.load()
    check("recovered from backup", status, "restored-from-backup")
    check("nothing lost", len(entries), 5)
    check_true("primary rebuilt", os.path.exists(history.primary_path()))
    os.unlink(history.backup_path())
    entries, status = history.load()
    check("recovered from primary", status, "restored-from-primary")
    check_true("backup rebuilt", os.path.exists(history.backup_path()))

    print("\n=== first run is 'empty', not 'tampered' ===")
    reset()
    entries, status = history.load()
    check("empty on first run", status, "empty")
    check("no entries", len(entries), 0)

    print("\n=== activity record is separate and independent ===")
    reset()
    history.append("connected", "A Device", "USB device")
    history.append_activity("program", "notepad.exe",
                            r"C:\Windows\notepad.exe")
    history.append_activity("file", "report.docx",
                            r"C:\Users\x\report.docx")
    devices, dstatus = history.load()
    acts, astatus = history.load_activity()
    check("device record unaffected", len(devices), 1)
    check("activity record has both", len(acts), 2)
    check("separate files",
          history.primary_path() != history.ACTIVITY.primary_path(), True)
    check("both intact", (dstatus, astatus), ("ok", "ok"))
    check("activity describes a program",
          history.describe_activity(acts[0]), "Opened program: notepad.exe")
    check("activity describes a file",
          history.describe_activity(acts[1]), "Opened file: report.docx")
    check_true("activity chain verifies", history.ACTIVITY.verify(acts)[0])

    print("\n=== activity record rolls at 50 too ===")
    for i in range(60):
        history.append_activity("program", f"prog{i}.exe")
    acts, astatus = history.load_activity()
    check("activity capped", len(acts), history.MAX_ENTRIES)
    check("activity still intact", astatus, "ok")
    devices, _ = history.load()
    check("device record still untouched by all that", len(devices), 1)

    print("\n=== activity tampering is detected ===")
    acts, _ = history.load_activity()
    acts[5]["name"] = "something else.exe"
    history.ACTIVITY._write_file(history.ACTIVITY.primary_path(), acts)
    history.ACTIVITY._write_file(history.ACTIVITY.backup_path(), acts)
    _, astatus = history.load_activity()
    check_true("activity edit detected",
               astatus.startswith("tampered"), astatus[:52])

    print("\n=== events shaped for the main list ===")
    reset()
    history.append("connected", "A Phone", "USB device")
    history.append_activity("program", "chrome.exe", r"C:\chrome.exe")
    dev_event = history.as_event(history.load()[0][0])
    act_event = history.activity_as_event(history.load_activity()[0][0])
    check("device event kind", dev_event["kind"], "device")
    check("activity event kind", act_event["kind"], "activity")
    check("activity event title",
          act_event["title"], "Program opened: chrome.exe")
    check_true("no unfilled placeholders",
               "{" not in act_event["title"] + act_event["meaning"])

    print("\n=== plain-English status lines ===")
    for st in ["ok", "empty", "restored-from-backup",
               "tampered: entry #3 was modified"]:
        text = history.status_text(st, 7, "programs and files")
        print(f"          {st:32s} -> {text[:70]}")
        check_true(f"readable for {st}", "{" not in text and len(text) > 10)

    print("\n=== concurrent appends lose nothing ===")
    # The recorder's program poller and file watcher both append to the
    # activity record. Without the lock two threads could both read entry N
    # and both write N+1, and one fact would vanish.
    reset()
    import threading

    def burst(tag):
        for i in range(10):
            history.append_activity("file", f"{tag}-{i}.txt")

    threads = [threading.Thread(target=burst, args=(t,)) for t in "abcd"]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    acts, status = history.load_activity()
    check("40 appends from 4 threads -> 40 entries", len(acts), 40)
    check("chain still verifies", status, "ok")
    check("sequence has no gaps or repeats",
          [e["seq"] for e in acts], list(range(1, 41)))

    shutil.rmtree(_box, ignore_errors=True)
    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL HISTORY TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
