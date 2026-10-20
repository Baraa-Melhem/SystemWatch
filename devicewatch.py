# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
Real-time device arrival/removal detection.

WHY THIS EXISTS
---------------
The event log is not enough. Kernel-PnP/Configuration records driver
*configuration* - the first time Windows sets a device up, or when its driver
changes. Unplugging and re-plugging a device Windows already knows writes
nothing at all. Measured on this machine: a phone was connected at 14:02 and
the most recent Kernel-PnP record was from 10:19.

Storage is a special case, because mounting a filesystem does get logged. So
USB sticks were detected, and phones, mice, cameras and anything else that
does not mount a volume were not.

WHAT THIS DOES INSTEAD
----------------------
Windows will tell any window that asks about every device interface arriving
or leaving. `RegisterDeviceNotification` with DEVICE_NOTIFY_ALL_INTERFACE_
CLASSES subscribes to all of them, and Windows then posts WM_DEVICECHANGE.
This is the same mechanism Explorer uses, and it fires for every plug and
unplug regardless of whether a driver was installed.

WHY IT IS STILL CHEAP
---------------------
The obvious implementation - a Qt application-wide native event filter -
would run a Python callback for *every* Windows message the app receives,
including every mouse move. Instead this creates a message-only window on its
own thread. A message-only window receives nothing except the notifications
it registered for, and the thread blocks inside GetMessage the rest of the
time, consuming nothing at all.

Plugging one phone in makes Windows announce five separate interfaces (ADB,
modem, MTP, composite, ...). A short debounce groups them by vendor/product
so one plug produces one line rather than five.

Everything here is read-only: it asks Windows to notify us, and asks WMI for
device names. Nothing is mounted, ejected, installed or changed.
"""

import ctypes
import re
import threading
import time
from collections import deque
from ctypes import wintypes

import win32api
import win32con
import win32gui
import win32gui_struct

# SetTimer/KillTimer are not exposed by every pywin32 build - this one does
# not have them - so they are called through the API directly. Without a
# working timer the debounce never fires, and detected devices are collected
# but never published, which looks exactly like "nothing was detected".
_user32 = ctypes.windll.user32
_user32.SetTimer.argtypes = [
    wintypes.HWND, ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p,
]
_user32.SetTimer.restype = ctypes.c_void_p
_user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_void_p]
_user32.KillTimer.restype = wintypes.BOOL

TIMER_ID = 1


def _set_timer(hwnd, milliseconds):
    _user32.SetTimer(hwnd, TIMER_ID, milliseconds, None)


def _kill_timer(hwnd):
    _user32.KillTimer(hwnd, TIMER_ID)

DBT_DEVICEARRIVAL = 0x8000
DBT_DEVICEREMOVECOMPLETE = 0x8004
DBT_DEVTYP_DEVICEINTERFACE = 5
DBT_DEVTYP_VOLUME = 2
DEVICE_NOTIFY_WINDOW_HANDLE = 0
DEVICE_NOTIFY_ALL_INTERFACE_CLASSES = 4

DEBOUNCE_MS = 800          # group one physical plug into one report
NAME_CACHE_TTL = 3.0       # seconds; a burst re-uses one WMI lookup

_VID_PID = re.compile(r"(VID_[0-9A-F]{4}&PID_[0-9A-F]{4})")

# Names that describe plumbing rather than the thing you plugged in.
_BORING_NAMES = (
    "composite device", "root hub", "generic usb hub", "usb hub",
    "host controller",
)


def path_to_instance(path):
    r"""
    Turn a device interface path into a device instance id.

    \\?\USB#VID_04E8&PID_6860#R58N64WAQEW#{guid}  ->
    USB\VID_04E8&PID_6860\R58N64WAQEW
    """
    text = path or ""
    if text.startswith("\\\\?\\"):
        text = text[4:]
    text = text.split("#{")[0]
    return text.replace("#", "\\")


def group_key(instance):
    """
    One physical device, one key.

    A phone exposes several interfaces that share a vendor/product pair, so
    that pair identifies the device far better than any single interface.
    """
    upper = (instance or "").upper()
    match = _VID_PID.search(upper)
    if match:
        return match.group(1)
    parts = [p for p in upper.split("\\") if p]
    return "\\".join(parts[:2]) if parts else upper


def score_name(name, service, instance):
    """
    How well does this interface name describe the physical device?

    Returns None for hubs and controllers, which are plumbing rather than
    something a person plugged in. Higher is better; the MTP/WPD interface
    usually carries the name the owner gave the device ("bara's M31"),
    so it wins.
    """
    lowered = (name or "").lower()
    if any(word in lowered for word in _BORING_NAMES):
        return None
    score = 0
    if "mtp" in (instance or "").upper() or "wpd" in (service or "").lower():
        score += 3
    if "interface" in lowered:
        score -= 1
    if "driver" in lowered or "enumerator" in lowered:
        score -= 2
    return score


class DeviceWatcher:
    """Push-based device arrival/removal, off the GUI thread."""

    def __init__(self):
        self._queue = deque(maxlen=300)
        self._pending = {}
        self._lock = threading.Lock()
        self._hwnd = None
        self._handle = None
        self._thread = None
        self._running = False
        self.paused = False
        self.started_ok = False
        self.error = ""
        self.last_error = ""
        self.messages_seen = 0
        self._names = {}
        self._names_at = 0.0
        # Optional callback invoked with each batch of finished records, on
        # the watcher thread. Lets a headless recorder work with no polling
        # loop at all; the GUI uses drain() instead.
        self.on_records = None

    # -- lifecycle --------------------------------------------------------
    def start(self):
        if self._thread:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, name="SystemWatch-devices", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._running = False
        if self._hwnd:
            try:
                win32gui.PostMessage(self._hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass

    def _run(self):
        try:
            instance = win32api.GetModuleHandle(None)
            klass = win32gui.WNDCLASS()
            klass.lpfnWndProc = self._wndproc
            klass.hInstance = instance
            klass.lpszClassName = "SystemWatchDeviceWindow"
            atom = win32gui.RegisterClass(klass)

            # A top-level window, created but never shown. It must be
            # top-level rather than message-only: drive-letter arrivals
            # (DBT_DEVTYP_VOLUME) are *broadcast* to top-level windows, and a
            # message-only window would never receive them. WS_EX_TOOLWINDOW
            # keeps it out of Alt-Tab and the taskbar.
            self._hwnd = win32gui.CreateWindowEx(
                win32con.WS_EX_TOOLWINDOW,
                atom, "SystemWatch device monitor", 0,
                0, 0, 0, 0, 0, 0, instance, None,
            )

            device_filter = win32gui_struct.PackDEV_BROADCAST_DEVICEINTERFACE(
                "{00000000-0000-0000-0000-000000000000}"
            )
            self._handle = win32gui.RegisterDeviceNotification(
                self._hwnd,
                device_filter,
                DEVICE_NOTIFY_WINDOW_HANDLE
                | DEVICE_NOTIFY_ALL_INTERFACE_CLASSES,
            )
            self.started_ok = True
        except Exception as exc:
            self.error = str(exc)
            return

        # Learn the names of everything already attached, before anything is
        # unplugged. A removed device is gone from WMI by the time we are
        # told about it, so without this the very first unplug of the session
        # can only be reported as "a USB device" instead of by name.
        try:
            self._friendly_names(force=True)
        except Exception:
            pass

        # Blocks here when idle - no polling, no CPU.
        try:
            win32gui.PumpMessages()
        except Exception as exc:
            self.error = str(exc)

    # -- the window procedure ---------------------------------------------
    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == win32con.WM_DEVICECHANGE:
                self.messages_seen += 1
                self._on_device_change(hwnd, wparam, lparam)
                return True
            if msg == win32con.WM_TIMER:
                _kill_timer(hwnd)
                self._flush()
                return 0
            if msg == win32con.WM_CLOSE:
                win32gui.DestroyWindow(hwnd)
                return 0
            if msg == win32con.WM_DESTROY:
                win32gui.PostQuitMessage(0)
                return 0
        except Exception as exc:
            # Never raise into the OS, but never hide it either - a silently
            # swallowed error here looks exactly like "no devices changed".
            self.last_error = f"{type(exc).__name__}: {exc}"
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _on_device_change(self, hwnd, wparam, lparam):
        if self.paused or not self._running:
            return
        if wparam not in (DBT_DEVICEARRIVAL, DBT_DEVICEREMOVECOMPLETE):
            return
        arrived = wparam == DBT_DEVICEARRIVAL

        try:
            info = win32gui_struct.UnpackDEV_BROADCAST(lparam)
        except Exception:
            return
        if info is None:
            return

        if info.devicetype == DBT_DEVTYP_DEVICEINTERFACE:
            if not self.note_interface(
                arrived, path_to_instance(getattr(info, "name", ""))
            ):
                return
        elif info.devicetype == DBT_DEVTYP_VOLUME:
            letters = self._unitmask_letters(getattr(info, "unitmask", 0))
            if not self.note_volume(arrived, letters):
                return
        else:
            return

        # Restart the debounce so a burst collapses into one report.
        _kill_timer(hwnd)
        _set_timer(hwnd, DEBOUNCE_MS)

    def note_interface(self, arrived, instance):
        """Record one device interface arriving or leaving. Returns True if
        it was accepted (used by the tests as well as the window proc)."""
        if not instance:
            return False
        key = (arrived, group_key(instance))
        with self._lock:
            record = self._pending.setdefault(key, {
                "arrived": arrived,
                "kind": "interface",
                "instances": [],
                "drives": [],
                "time": time.time(),
            })
            if instance not in record["instances"]:
                record["instances"].append(instance)
        return True

    def note_volume(self, arrived, letters):
        """Record drive letters arriving or leaving."""
        if not letters:
            return False
        key = (arrived, "VOLUME")
        with self._lock:
            record = self._pending.setdefault(key, {
                "arrived": arrived,
                "kind": "volume",
                "instances": [],
                "drives": [],
                "time": time.time(),
            })
            for letter in letters:
                if letter not in record["drives"]:
                    record["drives"].append(letter)
        return True

    @staticmethod
    def _unitmask_letters(mask):
        return [
            f"{chr(ord('A') + bit)}:"
            for bit in range(26)
            if mask & (1 << bit)
        ]

    # -- naming ------------------------------------------------------------
    def _friendly_names(self, force=False):
        """
        Map instance id -> human name, via one read-only WMI query.

        Cached briefly: a single plug fires several notifications, and they
        should share one lookup. Removed devices are gone from WMI, so the
        cache is never purged - it is what lets an unplug still be named.
        """
        now = time.time()
        if not force and now - self._names_at < NAME_CACHE_TTL:
            return self._names
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            wmi = win32com.client.GetObject("winmgmts:")
            rows = wmi.ExecQuery(
                "SELECT Name, PNPDeviceID, Service FROM Win32_PnPEntity "
                "WHERE PNPDeviceID LIKE 'USB%' OR PNPDeviceID LIKE 'WPD%' "
                "OR PNPDeviceID LIKE 'SWD%' OR PNPDeviceID LIKE 'BTH%'"
            )
            for row in rows:
                pnp = (row.PNPDeviceID or "").upper()
                if not pnp:
                    continue
                self._names[pnp] = {
                    "name": row.Name or "",
                    "service": row.Service or "",
                }
            self._names_at = now
        except Exception:
            pass
        return self._names

    def _best_name(self, instances):
        """Pick the name that best describes the physical thing."""
        names = self._friendly_names()
        best, best_score = "", -99
        for instance in instances:
            entry = names.get(instance.upper())
            if not entry or not entry["name"]:
                continue
            score = score_name(entry["name"], entry["service"], instance)
            if score is None:
                score = -5          # plumbing: usable only as a last resort
            if score > best_score:
                best, best_score = entry["name"], score
        return best

    # -- publishing --------------------------------------------------------
    def _flush(self):
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
        if not pending:
            return

        # One lookup for the whole burst; force it for arrivals so a
        # brand-new device is named rather than missed.
        if any(item["arrived"] for item in pending):
            self._friendly_names(force=True)

        finished = []
        for item in pending:
            item["name"] = (
                self._best_name(item["instances"])
                if item["instances"] else ""
            )
            self._queue.append(item)
            finished.append(item)

        if self.on_records and finished:
            try:
                self.on_records(finished)
            except Exception as exc:
                self.last_error = f"on_records: {exc}"

    def drain(self):
        out = []
        while True:
            try:
                out.append(self._queue.popleft())
            except IndexError:
                break
        return out


def to_event(record):
    """
    Turn a device notification into an event dict the UI can display,
    shaped exactly like one that came from the event log.
    """
    from datetime import datetime

    from devices import describe_device
    from translations import INFO

    arrived = record["arrived"]
    when = datetime.fromtimestamp(record["time"])
    drives = record.get("drives") or []
    name = (record.get("name") or "").strip()
    instances = record.get("instances") or []

    kind_label, routine = "device", True
    if instances:
        kind_label, routine = describe_device(instances[0])

    verb = "connected" if arrived else "disconnected"

    if record["kind"] == "volume":
        where = ", ".join(drives)
        routine = False
        title = f"Drive {where} {verb}"
        meaning = (
            f"A drive became available as {where}."
            if arrived else
            f"The drive at {where} was removed."
        )
        action = (
            "Expected if you just plugged something in. A drive you did not "
            "connect is worth a second look."
            if arrived else
            "Safe to unplug now."
        )
    else:
        label = name or kind_label
        title = f"{label} {verb}"
        detail = instances[0] if instances else ""
        meaning = (
            f"Windows reported {'a new' if arrived else 'the removal of a'} "
            f"{kind_label}"
            + (f", identified as {name}" if name else "")
            + f".  Hardware ID: {detail}"
        )
        action = (
            "Expected if you just plugged something in. If you connected "
            "nothing, check what this device is before trusting it."
            if arrived else
            "Nothing to do."
        )

    return {
        "channel": "Live device monitor",
        # Short: this lands in a fixed-width Source column.
        "provider": "Device monitor",
        "event_id": 0,
        "level": 4,
        "record_id": "",
        "computer": "",
        "time": when,
        "fields": {},
        "raw_level_severity": INFO,
        "message": "",
        "historical": False,
        "title": title,
        "meaning": meaning,
        "action": action,
        "severity": INFO,
        "noisy": routine,
        "known": True,
        "kind": "device",
        "device_kind": kind_label,
        "device_name": name,
        "device_id": instances[0] if instances else "",
        "device_volume": drives[0] if drives else "",
        "live": True,
    }
