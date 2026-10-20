# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
Tamper-evident rolling records.

Two of them exist: one for device connections, one for programs and files
opened. Both work the same way, so the machinery lives in RollingRecord and
each record is one instance of it.

WHAT THIS GUARANTEES, AND WHAT IT DOES NOT
------------------------------------------
It does NOT make a record undeletable. A file your account owns can always
be deleted by your account, and an administrator can delete anything at all.
Nothing running without administrator rights can prevent that, and claiming
otherwise would be a lie.

What it does instead is make deletion and editing *obvious*:

  * Two copies live in different roots (%LOCALAPPDATA% and %APPDATA%), so
    wiping one folder does not lose the record - the survivor is restored
    automatically on the next read.
  * Every entry carries a SHA-256 hash of its own contents plus the hash of
    the entry before it. Changing one entry breaks its own hash; removing one
    from the middle breaks the next entry's link; renumbering breaks the
    sequence. Any of those is reported as tampering rather than passing
    silently.
  * Entry numbers keep counting up forever, so a gap is visible even after
    old entries have rolled off.

The hash has no secret key, and cannot usefully have one: any key this
account can read, so can whoever is using this account. So the chain catches
hand edits, deletions from the middle and damaged files - but someone who
reads this source and recomputes every hash can forge a consistent record.
It is evidence, not proof, and the documentation says so.

Each window is deliberately small - the newest MAX_ENTRIES entries. When the
51st arrives the oldest rolls off, which is a legitimate operation and is not
treated as tampering.
"""

import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime

MAX_ENTRIES = 50

APP_DIR_NAME = "SystemWatch"
PRIMARY_ENV = "LOCALAPPDATA"
BACKUP_ENV = "APPDATA"


def _folder(env_name):
    base = os.environ.get(env_name) or os.path.expanduser("~")
    path = os.path.join(base, APP_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


class RollingRecord:
    """
    A fixed-size, hash-chained, duplicated append-only log.

    `fields` are the per-entry values this record carries, beyond the seq,
    time and prev that every record has. They are all covered by the hash.
    """

    def __init__(self, file_name, fields, defaults=None):
        self.file_name = file_name
        self.fields = tuple(fields)
        self.defaults = defaults or {}
        self.signed_fields = ("seq", "time") + self.fields + ("prev",)
        # The recorder appends from more than one thread (the program poller
        # and the file watcher share the activity record). Without this, two
        # appends could both read entry N and both write N+1, and one of the
        # two facts would silently vanish.
        self._lock = threading.Lock()

    # -- locations ------------------------------------------------------
    def primary_path(self):
        return os.path.join(_folder(PRIMARY_ENV), self.file_name)

    def backup_path(self):
        return os.path.join(_folder(BACKUP_ENV), self.file_name)

    # -- integrity ------------------------------------------------------
    def compute_hash(self, entry):
        """SHA-256 over the signed fields, in a fixed order."""
        payload = {key: entry.get(key) for key in self.signed_fields}
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def verify(self, entries):
        """
        Check the chain. Returns (ok, reason).

        Front-trimming is expected, so the first retained entry's `prev` is
        not checked against anything - there is nothing left to check it
        against.
        """
        previous = None
        for entry in entries:
            if self.compute_hash(entry) != entry.get("hash"):
                return False, f"entry #{entry.get('seq', '?')} was modified"
            if previous is not None:
                if entry.get("prev") != previous.get("hash"):
                    return False, (
                        f"entry #{entry.get('seq', '?')} does not follow "
                        f"#{previous.get('seq', '?')} - something was removed"
                    )
                if entry.get("seq") != previous.get("seq", 0) + 1:
                    return False, (
                        f"entry numbers jump from {previous.get('seq')} to "
                        f"{entry.get('seq')} - something was removed"
                    )
            previous = entry
        return True, ""

    # -- files ----------------------------------------------------------
    def _read_file(self, path):
        entries = []
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except ValueError:
                        # A corrupt line is itself evidence; keep a marker so
                        # verification fails rather than silently skipping it.
                        entries.append({"seq": -1, "hash": "corrupt"})
        except (FileNotFoundError, OSError):
            return None
        return entries

    def _write_file(self, path, entries):
        """Write atomically, so a crash mid-write cannot leave a torn file."""
        folder = os.path.dirname(path)
        try:
            handle, temp = tempfile.mkstemp(dir=folder, suffix=".tmp")
        except OSError:
            return False
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as out:
                for entry in entries:
                    out.write(json.dumps(entry, separators=(",", ":")) + "\n")
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, path)
            return True
        except OSError:
            try:
                os.unlink(temp)
            except OSError:
                pass
            return False

    def signature(self):
        """
        Cheap change-check: (mtime, size).

        Lets a reader poll with a single stat() instead of parsing, so
        watching for new entries costs effectively nothing.
        """
        try:
            stat = os.stat(self.primary_path())
            return (stat.st_mtime_ns, stat.st_size)
        except OSError:
            return None

    # -- reading --------------------------------------------------------
    def load(self):
        """
        Read the record, healing from the backup if one copy is missing or
        has been tampered with.

        Returns (entries, status) where status is one of:
            "ok"                    both copies agree, chain intact
            "restored-from-backup"  the primary was missing or damaged
            "restored-from-primary" the backup was missing or damaged
            "empty"                 nothing recorded yet
            "tampered: <reason>"    both copies fail verification
        """
        primary = self._read_file(self.primary_path())
        backup = self._read_file(self.backup_path())

        # Neither file existing is a first run, not an attack.
        if primary is None and backup is None:
            return [], "empty"

        primary_ok = primary is not None and self.verify(primary)[0]
        backup_ok = backup is not None and self.verify(backup)[0]

        def newest_seq(entries):
            return entries[-1].get("seq", 0) if entries else 0

        if primary_ok and backup_ok:
            if newest_seq(primary) >= newest_seq(backup):
                if newest_seq(primary) > newest_seq(backup):
                    self._write_file(self.backup_path(), primary)
                return primary, ("empty" if not primary else "ok")
            self._write_file(self.primary_path(), backup)
            return backup, "restored-from-backup"

        if primary_ok:
            self._write_file(self.backup_path(), primary)
            return primary, ("empty" if not primary else "restored-from-primary")

        if backup_ok:
            self._write_file(self.primary_path(), backup)
            return backup, "restored-from-backup"

        # Neither verifies. Report it rather than quietly starting over.
        broken = primary if primary is not None else (backup or [])
        reason = self.verify(broken)[1] if broken else "both copies unreadable"
        return broken, f"tampered: {reason}"

    # -- writing --------------------------------------------------------
    def append(self, when=None, **values):
        """
        Add one entry, roll off the oldest once the window is full, and
        update both copies. Returns the entry written.
        """
        with self._lock:
            return self._append_locked(when, values)

    def _append_locked(self, when, values):
        entries, status = self.load()
        if status.startswith("tampered"):
            # Do not build on a broken chain: start a fresh one, but keep the
            # damaged file alongside it as evidence.
            self._preserve_damaged()
            entries = []

        last = entries[-1] if entries else None
        entry = {
            "seq": (last.get("seq", 0) + 1) if last else 1,
            "time": (when or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
        }
        for field in self.fields:
            default = self.defaults.get(field, "")
            value = values.get(field, default)
            if isinstance(default, list):
                value = list(value or [])
            entry[field] = value if value is not None else default
        entry["prev"] = last.get("hash", "") if last else ""
        entry["hash"] = self.compute_hash(entry)

        entries.append(entry)
        if len(entries) > MAX_ENTRIES:
            entries = entries[-MAX_ENTRIES:]

        self._write_file(self.primary_path(), entries)
        self._write_file(self.backup_path(), entries)
        return entry

    def _preserve_damaged(self):
        """Keep a copy of a tampered file instead of overwriting evidence."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for path in (self.primary_path(), self.backup_path()):
            if os.path.exists(path):
                try:
                    os.replace(path, f"{path}.damaged-{stamp}")
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# The two records
# ---------------------------------------------------------------------------
DEVICES = RollingRecord(
    "device-history.jsonl",
    ("action", "name", "kind", "device_id", "drives"),
    defaults={"drives": []},
)

ACTIVITY = RollingRecord(
    "activity-history.jsonl",
    ("action", "name", "path", "detail"),
)


# ---------------------------------------------------------------------------
# Device record: module-level API, kept as-is so existing callers still work
# ---------------------------------------------------------------------------
FILE_NAME = DEVICES.file_name


def primary_path():
    return DEVICES.primary_path()


def backup_path():
    return DEVICES.backup_path()


def compute_hash(entry):
    return DEVICES.compute_hash(entry)


def verify(entries):
    return DEVICES.verify(entries)


def signature():
    return DEVICES.signature()


def load():
    return DEVICES.load()


def _read_file(path):
    return DEVICES._read_file(path)


def _write_file(path, entries):
    return DEVICES._write_file(path, entries)


def _preserve_damaged():
    return DEVICES._preserve_damaged()


def append(action, name, kind="", device_id="", drives=None, when=None):
    """Add one device connection or disconnection to the record."""
    return DEVICES.append(
        when=when, action=action, name=name, kind=kind,
        device_id=device_id, drives=drives or [],
    )


def describe(entry):
    """One human-readable line for a device entry."""
    what = entry.get("name") or entry.get("kind") or "device"
    drives = entry.get("drives") or []
    where = f" ({', '.join(drives)})" if drives else ""
    return f"{what}{where} {entry.get('action', '')}"


def status_text(status, count, noun="connections"):
    """Plain-English summary of a record's condition."""
    if status.startswith("tampered"):
        reason = status.split(":", 1)[1].strip()
        return (
            f"The record was altered outside SystemWatch - {reason}. The "
            f"damaged file has been kept alongside as evidence and a fresh "
            f"record started."
        )
    if status == "restored-from-backup":
        return (
            "The main record was missing or damaged and has been rebuilt "
            "from the backup copy. Nothing was lost."
        )
    if status == "restored-from-primary":
        return (
            "The backup copy was missing or damaged and has been rebuilt "
            "from the main record. Nothing was lost."
        )
    if status == "empty" or not count:
        return f"No {noun} recorded yet."
    return f"{count} {noun} recorded, and the record is intact."


def as_event(entry):
    """
    Shape a recorded device entry like a live event, so the main list can
    show connections that happened while the window was closed.
    """
    try:
        when = datetime.strptime(entry.get("time", ""), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        when = datetime.now()

    arrived = entry.get("action") == "connected"
    name = entry.get("name") or entry.get("kind") or "device"
    drives = entry.get("drives") or []
    where = f" ({', '.join(drives)})" if drives else ""
    verb = "connected" if arrived else "disconnected"

    return {
        "channel": "Recorded devices",
        "provider": "Device recorder",
        "event_id": 1 if arrived else 2,
        "level": 4,
        "record_id": str(entry.get("seq", "")),
        "computer": "",
        "time": when,
        "fields": {},
        "raw_level_severity": "info",
        "message": "",
        "historical": True,
        "title": f"{name}{where} {verb}",
        "meaning": (
            f"{name} was {verb}"
            + (f" as {', '.join(drives)}" if drives else "")
            + ". This was written to the permanent record by the background "
            "recorder, which watches even when this window is closed."
        ),
        "action": (
            "Expected if you plugged it in yourself. Anything here you do "
            "not recognise is worth looking into."
            if arrived else
            "Nothing to do."
        ),
        "severity": "info",
        "noisy": False,
        "known": True,
        "kind": "device",
        "device_name": entry.get("name", ""),
        "device_kind": entry.get("kind", ""),
        "device_id": entry.get("device_id", ""),
        "seq": entry.get("seq"),
    }


# ---------------------------------------------------------------------------
# Activity record: programs launched and files opened
# ---------------------------------------------------------------------------
def append_activity(action, name, path="", detail="", when=None):
    """
    Record a program being launched or a file being opened.

    action is "program" or "file".
    """
    return ACTIVITY.append(
        when=when, action=action, name=name, path=path, detail=detail,
    )


def load_activity():
    return ACTIVITY.load()


def activity_signature():
    return ACTIVITY.signature()


def describe_activity(entry):
    """One human-readable line for an activity entry."""
    name = entry.get("name") or "(unnamed)"
    if entry.get("action") == "program":
        return f"Opened program: {name}"
    return f"Opened file: {name}"


def activity_as_event(entry):
    """Shape an activity entry like a live event for the main list."""
    try:
        when = datetime.strptime(entry.get("time", ""), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        when = datetime.now()

    is_program = entry.get("action") == "program"
    name = entry.get("name") or "(unnamed)"
    path = entry.get("path") or ""
    detail = entry.get("detail") or ""

    return {
        "channel": "Recorded activity",
        "provider": "Activity recorder",
        "event_id": 3 if is_program else 4,
        "level": 4,
        "record_id": str(entry.get("seq", "")),
        "computer": "",
        "time": when,
        "fields": {},
        "raw_level_severity": "info",
        "message": "",
        "historical": True,
        "title": (
            f"Program opened: {name}" if is_program else f"File opened: {name}"
        ),
        "meaning": (
            (f"The program {name} was started."
             if is_program else
             f"The file {name} was opened.")
            + (f"  {path}" if path else "")
            + (f"  ({detail})" if detail else "")
        ),
        "action": (
            "Expected if you opened it yourself. Anything here you do not "
            "recognise is worth looking into."
        ),
        "severity": "info",
        "noisy": False,
        "known": True,
        "kind": "activity",
        "activity_name": name,
        "activity_path": path,
        "seq": entry.get("seq"),
    }
