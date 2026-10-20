# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
Watches for programs being launched and files being opened.

TWO DIFFERENT MECHANISMS, BECAUSE WINDOWS OFFERS NO SINGLE ONE
--------------------------------------------------------------
Programs: Windows will not push process-start notifications to a normal
user. The push APIs that exist (Win32_ProcessStartTrace, the Security log's
event 4688, ETW's kernel process provider) all require Administrator, and
4688 additionally requires turning on an audit policy - a system change this
program refuses to make. So process starts are found by polling. That is a
deliberate, measured exception to the no-polling rule:

    psutil.pids() costs 0.05 ms. Diffing a set of integers is free. Only a
    brand-new pid is looked up in detail, and looking up every process at
    once (which costs 540 ms) never happens.

At the poll interval below that works out at roughly 0.005% of one core.

Files: the shell keeps a folder of shortcuts to recently-opened documents,
and Windows updates it as you open things. Watching that folder with
ReadDirectoryChangesW is genuinely event-driven - the thread blocks until
Windows says something changed - so file tracking costs nothing at all while
you are not opening files.

WHAT "EVERY FILE" HONESTLY MEANS
--------------------------------
There is no way, without a kernel-mode filter driver (which needs
Administrator and a signed driver), to see every file that every process
opens. Nor would you want it: Windows opens thousands of files a minute.

What this sees is the useful part: documents you open through Explorer or
through a program's File-Open dialog, which is what the shell records. A
program quietly reading its own configuration file will not appear here, and
that is stated plainly rather than glossed over.
"""

import os
import threading
import time
from collections import deque

import psutil

# How often to look for new processes. Long enough to be cheap, short enough
# that a program you launched shows up while you still care.
POLL_SECONDS = 1.5

# A new process is only reported once it owns a visible window, which is what
# separates "a program the user opened" from the background helpers Windows
# spawns constantly. Some apps take a moment to show their window, so a
# candidate is kept for this many polls before being given up on.
WINDOW_GRACE_POLLS = 6

# Opening one document can touch its shortcut more than once; collapse
# repeats of the same target inside this many seconds.
FILE_DEDUPE_SECONDS = 5.0

QUEUE_MAX = 500

# Windows shell components that own visible windows but are not "programs
# the user opened" in any meaningful sense.
SKIP_PROGRAMS = {
    "applicationframehost.exe", "shellexperiencehost.exe",
    "searchhost.exe", "searchapp.exe", "startmenuexperiencehost.exe",
    "textinputhost.exe", "systemsettings.exe", "lockapp.exe",
    "widgets.exe", "widgetboard.exe", "explorer.exe",
    "dllhost.exe", "conhost.exe", "runtimebroker.exe",
    "backgroundtaskhost.exe", "sihost.exe", "ctfmon.exe",
    "wmiprvse.exe", "csrss.exe", "dwm.exe", "fontdrvhost.exe",
    "smartscreen.exe", "useroobebroker.exe", "crashpad_handler.exe",
    "openwith.exe", "rundll32.exe", "taskhostw.exe", "wscript.exe",
    "consent.exe", "audiodg.exe", "svchost.exe", "taskmgr.exe",
}

# SystemWatch's own processes should never fill its own record. They are
# recognised by exact location, never by name: matching any path containing
# "systemwatch" (as this once did) let any program hide from the record just
# by being called that, or by being started as "python main.py".
SELF_SCRIPTS = ("main.py", "recorder.py", "SystemWatch.pyw")

# Remembered file hits are pruned once there are this many, so a long uptime
# of opening documents cannot grow the dedupe table without limit.
RECENT_SEEN_MAX = 256


def is_protocol_entry(display_name):
    """
    True for shell protocol activations rather than real documents.

    Pressing PrintScreen or opening the game bar makes Windows drop things
    like "ms-screenclip---source=PrintScreen" and "ms-gamingoverlay---" into
    Recent Items. They are not files anybody opened, and left alone they
    would crowd real documents out of the 50 slots.
    """
    lowered = (display_name or "").lower()
    return lowered.startswith("ms-") and "---" in lowered


def recent_folder():
    return os.path.join(
        os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Recent"
    )


def _visible_window_pids():
    """Pids that own at least one visible top-level window."""
    found = set()
    try:
        import win32gui
        import win32process

        def callback(hwnd, _):
            try:
                if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    found.add(pid)
            except Exception:
                pass
            return True

        win32gui.EnumWindows(callback, None)
    except Exception:
        pass
    return found


def _norm(path):
    return os.path.normcase(os.path.abspath(path)) if path else ""


def _own_locations():
    """(packaged exe or "", {script paths}) that identify SystemWatch."""
    import sys

    here = os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, "frozen", False):
        return _norm(sys.executable), set()
    return "", {_norm(os.path.join(here, s)) for s in SELF_SCRIPTS}


def _is_self(process_info, own=None):
    """
    True only for SystemWatch's own window or recorder.

    Packaged, that is the exact SystemWatch.exe this copy runs from. From
    source, it is a Python whose first script argument is one of this
    folder's entry points. `cwd` resolves a relative script argument.
    """
    own_exe, own_scripts = own if own is not None else _own_locations()
    exe = _norm(process_info.get("exe"))
    if own_exe:
        return exe == own_exe
    cmdline = process_info.get("cmdline") or []
    base = process_info.get("cwd") or ""
    for arg in cmdline[1:3]:
        if arg.startswith("-"):
            continue
        candidate = arg if os.path.isabs(arg) else os.path.join(base, arg)
        return bool(base or os.path.isabs(arg)) and _norm(candidate) in own_scripts
    return False


class ActivityWatcher:
    """
    Reports programs launched and files opened.

    Records are dicts: {"kind": "program"|"file", "name", "path", "detail",
    "time"}. Either drain() them, or set on_records for a push callback.
    """

    def __init__(self):
        self.on_records = None
        self.paused = False
        self.started_ok = False
        self.error = ""
        self.last_error = ""
        self.programs_seen = 0
        self.files_seen = 0

        self._queue = deque(maxlen=QUEUE_MAX)
        self._stop = threading.Event()
        self._threads = []
        self._dir_handle = None
        self._recent_seen = {}
        self._own = _own_locations()
        # A Win32 event as well as the Python one: the file thread blocks
        # inside Windows, so it has to be woken by something Windows knows
        # about. See _watch_files.
        self._stop_handle = None
        try:
            import win32event

            self._stop_handle = win32event.CreateEvent(None, True, False, None)
        except Exception:
            pass

    # -- lifecycle -------------------------------------------------------
    def start(self):
        self._stop.clear()
        for target, name in ((self._watch_programs, "programs"),
                             (self._watch_files, "files")):
            thread = threading.Thread(
                target=self._guard, args=(target, name),
                name=f"activity-{name}", daemon=True,
            )
            thread.start()
            self._threads.append(thread)
        self.started_ok = True
        return True

    def _guard(self, target, label):
        try:
            target()
        except Exception as exc:
            self.last_error = f"{label}: {exc}"

    def stop(self):
        """
        Stop both threads. Must not block.

        Closing the directory handle is NOT how this is done. A pending
        synchronous read keeps the handle busy, so CloseHandle waits for the
        read to finish - which never happens, because the read is waiting for
        a file change. Measured: stop() never returned. Instead the read is
        issued as overlapped I/O and this signals an event the file thread is
        already waiting on, so it unwinds and closes its own handle.
        """
        self._stop.set()
        if self._stop_handle is not None:
            try:
                import win32event

                win32event.SetEvent(self._stop_handle)
            except Exception:
                pass

    # -- programs --------------------------------------------------------
    def _watch_programs(self):
        try:
            known = set(psutil.pids())
        except Exception as exc:
            self.error = f"cannot list processes: {exc}"
            return

        candidates = {}

        while not self._stop.wait(POLL_SECONDS):
            if self.paused:
                try:
                    known = set(psutil.pids())
                except Exception:
                    pass
                candidates.clear()
                continue

            try:
                current = set(psutil.pids())
            except Exception:
                continue

            for pid in current - known:
                info = self._describe_process(pid)
                if info:
                    candidates[pid] = info
            known = current

            if not candidates:
                continue

            windowed = _visible_window_pids()
            for pid, info in list(candidates.items()):
                if pid not in current:
                    candidates.pop(pid, None)          # died before showing
                elif pid in windowed:
                    candidates.pop(pid, None)
                    self._emit("program", info["name"], info["exe"],
                               info["detail"])
                    self.programs_seen += 1
                else:
                    info["polls"] += 1
                    if info["polls"] > WINDOW_GRACE_POLLS:
                        candidates.pop(pid, None)      # a background helper

    def _describe_process(self, pid):
        """Look up one new process. Only ever called for brand-new pids."""
        try:
            proc = psutil.Process(pid)
            with proc.oneshot():
                name = proc.name()
                try:
                    exe = proc.exe()
                except Exception:
                    exe = ""
                try:
                    cmdline = proc.cmdline()
                except Exception:
                    cmdline = []
                cwd = ""
                # Only a Python can be SystemWatch-from-source, and only then
                # is the working directory needed to resolve "main.py".
                if not self._own[0] and name.lower().startswith("python"):
                    try:
                        cwd = proc.cwd()
                    except Exception:
                        pass
        except Exception:
            return None

        if not name or name.lower() in SKIP_PROGRAMS:
            return None
        if _is_self({"exe": exe, "cmdline": cmdline, "cwd": cwd}, self._own):
            return None

        return {"name": name, "exe": exe, "detail": "", "polls": 0}

    # -- files -----------------------------------------------------------
    def _watch_files(self):
        import win32con
        import win32file

        folder = recent_folder()
        if not os.path.isdir(folder):
            self.error = "no Recent Items folder to watch"
            return

        try:
            self._dir_handle = win32file.CreateFile(
                folder,
                win32con.GENERIC_READ,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE
                | win32con.FILE_SHARE_DELETE,
                None,
                win32con.OPEN_EXISTING,
                win32con.FILE_FLAG_BACKUP_SEMANTICS,
                None,
            )
        except Exception as exc:
            self.error = f"cannot watch Recent Items: {exc}"
            return

        import pywintypes
        import win32event

        flags = (win32con.FILE_NOTIFY_CHANGE_FILE_NAME
                 | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE)

        overlapped = pywintypes.OVERLAPPED()
        overlapped.hEvent = win32event.CreateEvent(None, True, False, None)
        buffer = win32file.AllocateReadBuffer(8192)

        try:
            while not self._stop.is_set():
                win32event.ResetEvent(overlapped.hEvent)
                try:
                    win32file.ReadDirectoryChangesW(
                        self._dir_handle, buffer, False, flags, overlapped
                    )
                except Exception as exc:
                    self.last_error = f"watch: {exc}"
                    return

                # Block until either something changed or we were asked to
                # stop. This releases the interpreter lock, so the rest of
                # the program keeps running normally while we sit here.
                waited = win32event.WaitForMultipleObjects(
                    [overlapped.hEvent, self._stop_handle],
                    False, win32event.INFINITE,
                )
                if waited != win32event.WAIT_OBJECT_0:
                    try:
                        win32file.CancelIo(self._dir_handle)
                    except Exception:
                        pass
                    return

                try:
                    size = win32file.GetOverlappedResult(
                        self._dir_handle, overlapped, True
                    )
                    results = win32file.FILE_NOTIFY_INFORMATION(buffer, size)
                except Exception:
                    continue

                if self.paused or not results:
                    continue

                for action, name in results:
                    # 1 added, 3 modified, 5 renamed-to
                    if action not in (1, 3, 5):
                        continue
                    try:
                        self._note_recent_item(folder, name)
                    except Exception as exc:
                        self.last_error = f"recent item: {exc}"
        finally:
            handle, self._dir_handle = self._dir_handle, None
            for closeable in (handle, overlapped.hEvent):
                try:
                    win32file.CloseHandle(closeable)
                except Exception:
                    pass

    def _note_recent_item(self, folder, entry_name):
        if not entry_name.lower().endswith(".lnk"):
            return

        # The shortcut's own name is the document's name; that always works
        # even if resolving the target does not.
        display = entry_name[:-4]
        if is_protocol_entry(display):
            return
        now = time.time()
        last = self._recent_seen.get(display, 0.0)
        if now - last < FILE_DEDUPE_SECONDS:
            return
        self._recent_seen[display] = now
        if len(self._recent_seen) > RECENT_SEEN_MAX:
            self._recent_seen = {
                k: t for k, t in self._recent_seen.items()
                if now - t < FILE_DEDUPE_SECONDS
            }

        full = os.path.join(folder, entry_name)
        target = ""
        for attempt in range(4):
            target = self._resolve_shortcut(full)
            if target:
                break
            # The shortcut exists but Windows has not finished filling it in.
            time.sleep(0.15)
        detail = ""
        if target and os.path.isdir(target):
            detail = "folder"
        self._emit("file", display, target, detail)
        self.files_seen += 1

    def _resolve_shortcut(self, path):
        """Best-effort .lnk -> real path. COM needs setting up per thread."""
        try:
            import pythoncom
            import win32com.client

            if not getattr(self, "_com_ready", False):
                pythoncom.CoInitialize()
                self._com_ready = True
            shell = win32com.client.Dispatch("WScript.Shell")
            return shell.CreateShortCut(path).TargetPath or ""
        except Exception:
            return ""

    # -- output ----------------------------------------------------------
    def _emit(self, kind, name, path, detail):
        record = {
            "kind": kind,
            "name": name,
            "path": path or "",
            "detail": detail or "",
            "time": time.time(),
        }
        self._queue.append(record)
        if self.on_records:
            try:
                self.on_records([record])
            except Exception as exc:
                self.last_error = f"on_records: {exc}"

    def drain(self, limit=100):
        out = []
        for _ in range(limit):
            try:
                out.append(self._queue.popleft())
            except IndexError:
                break
        return out

    @property
    def backlog(self):
        return len(self._queue)
