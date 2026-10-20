# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
SystemWatch device recorder - the always-on part.

This is a headless background program with no window. It watches for devices
being plugged in and unplugged and writes each one into the tamper-evident
record in history.py. It runs whether or not the SystemWatch window is open,
which is the point: closing the window, or never opening it, must not stop
the recording.

    pythonw recorder.py            run it (no window appears)
    python  recorder.py --status   report whether it is running, and dump
                                   the current record
    python  recorder.py --stop     ask a running recorder to exit

Only one copy can run at a time. A second launch notices the first through a
named mutex and exits immediately, so a login shortcut plus a manual start
cannot produce two recorders fighting over the same file.

It costs nothing while idle: Windows pushes device notifications to it, and
between them every thread is blocked. There is no polling loop.
"""

import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")

import win32api
import win32event
import winerror

import config
import history
from activitywatch import ActivityWatcher
from devicewatch import DeviceWatcher, to_event

MUTEX_NAME = "SystemWatchDeviceRecorder"
STOP_EVENT_NAME = "SystemWatchDeviceRecorderStop"


def _claim_single_instance():
    """
    Returns (mutex_handle, already_running).

    The handle must be kept alive for as long as the process runs - letting
    it be garbage collected would release the claim.
    """
    handle = win32event.CreateMutex(None, False, MUTEX_NAME)
    return handle, win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS


def is_running():
    """True if a recorder is already live in this session."""
    try:
        handle = win32event.OpenMutex(
            win32event.SYNCHRONIZE, False, MUTEX_NAME
        )
    except Exception:
        return False
    if handle:
        win32api.CloseHandle(handle)
        return True
    return False


def request_stop():
    """Signal a running recorder to shut down. Returns True if one existed."""
    try:
        event = win32event.OpenEvent(
            win32event.EVENT_MODIFY_STATE, False, STOP_EVENT_NAME
        )
    except Exception:
        return False
    if not event:
        return False
    win32event.SetEvent(event)
    win32api.CloseHandle(event)
    return True


def _on_activity(records):
    """
    Called on a watcher thread for each program launched or file opened.

    Kept deliberately thin: append to the record and nothing else.
    """
    for record in records:
        try:
            history.append_activity(
                action="program" if record["kind"] == "program" else "file",
                name=record.get("name", ""),
                path=record.get("path", ""),
                detail=record.get("detail", ""),
            )
        except Exception:
            continue


def _on_records(records):
    """
    Called on the watcher thread once per finished batch.

    Routine internal devices - the ones Windows re-enumerates constantly -
    are skipped, so the 50 slots are spent on things a person actually
    plugged in.
    """
    for record in records:
        try:
            event = to_event(record)
        except Exception:
            continue
        if event.get("noisy"):
            continue
        history.append(
            action="connected" if record["arrived"] else "disconnected",
            name=record.get("name") or event.get("device_kind") or "",
            kind=event.get("device_kind", ""),
            device_id=event.get("device_id", ""),
            drives=record.get("drives") or [],
        )


def run():
    mutex, already = _claim_single_instance()
    if already:
        print("A recorder is already running; this copy will exit.")
        return 0

    stop_event = win32event.CreateEvent(None, True, False, STOP_EVENT_NAME)

    watcher = DeviceWatcher()
    watcher.on_records = _on_records
    watcher.start()

    # Programs and files are only watched if the user has left that on. The
    # window restarts the recorder when the setting changes, so reading it
    # once here is enough.
    activity = None
    if config.record_activity():
        activity = ActivityWatcher()
        activity.on_records = _on_activity
        activity.start()

    # Give the watcher a moment to register, then report how it went. When
    # started from a login shortcut nobody sees this, but it matters when
    # run by hand to diagnose a problem.
    time.sleep(2.0)
    if not watcher.started_ok:
        print(f"Could not start device watching: {watcher.error}")
        return 1
    print(f"Recorder running (pid {os.getpid()}). Ctrl+C or --stop to quit.")
    if activity is None:
        print("  programs/files: not recorded (switched off in Settings)")
    elif activity.error:
        print(f"  note: programs/files - {activity.error}")

    try:
        # Blocks until someone signals the stop event. No polling.
        win32event.WaitForSingleObject(stop_event, win32event.INFINITE)
    except KeyboardInterrupt:
        pass
    finally:
        if activity is not None:
            activity.stop()
        watcher.stop()
        win32api.CloseHandle(stop_event)
        del mutex
    return 0


def show_status():
    print(f"Recorder running : {'yes' if is_running() else 'no'}")

    entries, status = history.load()
    print("\n--- DEVICES ---")
    print(f"  status  : {history.status_text(status, len(entries))}")
    print(f"  main    : {history.primary_path()}")
    print(f"  backup  : {history.backup_path()}")
    print(f"  entries : {len(entries)} (newest {history.MAX_ENTRIES})")
    for entry in reversed(entries):
        print(f"    #{entry['seq']:<4} {entry['time']}  "
              f"{history.describe(entry)}")

    acts, astatus = history.load_activity()
    print("\n--- PROGRAMS & FILES ---")
    print(f"  status  : "
          f"{history.status_text(astatus, len(acts), 'programs and files')}")
    print(f"  main    : {history.ACTIVITY.primary_path()}")
    print(f"  backup  : {history.ACTIVITY.backup_path()}")
    print(f"  entries : {len(acts)} (newest {history.MAX_ENTRIES})")
    for entry in reversed(acts):
        print(f"    #{entry['seq']:<4} {entry['time']}  "
              f"{history.describe_activity(entry)}")
    return 0


def main(argv):
    arg = (argv[1] if len(argv) > 1 else "").lower()
    if arg in ("--status", "-s", "status"):
        return show_status()
    if arg in ("--stop", "stop"):
        if request_stop():
            print("Stop signal sent.")
            return 0
        print("No recorder was running.")
        return 1
    return run()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
