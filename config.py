# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
Settings, shared by the window and the recorder.

Lives outside ui.py so the recorder - which has no Qt - can read the one
setting it cares about (whether to record programs and files).

The file is user-editable JSON, so nothing read from it is trusted: every
key is checked against the type its default has, and anything unexpected
falls back to the default instead of reaching the UI. Writes are atomic, so
a crash mid-save cannot leave a half-written file that resets every setting
on the next launch.
"""

import json
import os
import tempfile

from translations import CHANNELS

APP_NAME = "SystemWatch"

DEFAULTS = {
    "channels": [k for k, v in CHANNELS.items() if v["default_on"]],
    "known_channels": [],
    "hide_noisy": True,
    "notify_errors": True,
    "minimize_to_tray": True,
    "backfill": 25,
    # Programs launched and files opened are personal. Recording them is
    # on by default, because that is what the Programs & Files tab is for,
    # but the welcome screen says so plainly and Settings can switch it off.
    "record_activity": True,
    "welcomed": False,
    # Window placement, restored on the next launch. Hex-encoded Qt state.
    "geometry": "",
    "splitter": "",
}

BACKFILL_RANGE = (0, 200)


def folder():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def path():
    return os.path.join(folder(), "config.json")


def _clean(raw):
    """Keep only known keys whose values have the expected type."""
    cfg = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return cfg
    for key, default in DEFAULTS.items():
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(default, bool):
            if isinstance(value, bool):
                cfg[key] = value
        elif isinstance(default, int):
            # bool is an int subclass; a stray `true` is not a count.
            if isinstance(value, int) and not isinstance(value, bool):
                low, high = BACKFILL_RANGE
                cfg[key] = min(high, max(low, value))
        elif isinstance(default, list):
            if isinstance(value, list):
                cfg[key] = [v for v in value if isinstance(v, str)]
        elif isinstance(default, str):
            if isinstance(value, str):
                cfg[key] = value
    # Only channels SystemWatch knows how to read can be switched on.
    cfg["channels"] = [c for c in cfg["channels"] if c in CHANNELS]
    return cfg


def load():
    try:
        with open(path(), "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        raw = {}
    return adopt_new_channels(_clean(raw))


def adopt_new_channels(cfg):
    """
    Switch on channels introduced by a newer version - once.

    Without this, anyone who already had a settings file would silently keep
    the old channel list, and a new feature (device and network monitoring,
    say) would appear to do nothing. `known_channels` records what has ever
    been offered, so a channel the user deliberately unticks stays unticked
    instead of coming back on every launch.
    """
    known = set(cfg.get("known_channels") or [])
    if not known:
        # First run after upgrading: whatever was already chosen counts as
        # seen, so only genuinely new channels get switched on.
        known = set(cfg.get("channels") or [])

    channels = list(cfg.get("channels") or [])
    for name, meta in CHANNELS.items():
        if name in known:
            continue
        known.add(name)
        if meta["default_on"] and name not in channels:
            channels.append(name)

    cfg["channels"] = channels
    cfg["known_channels"] = sorted(known)
    return cfg


def save(cfg):
    """Atomic write: a temp file in the same folder, then os.replace."""
    target = path()
    try:
        handle, temp = tempfile.mkstemp(dir=os.path.dirname(target),
                                        suffix=".tmp")
    except OSError:
        return False
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(_clean(cfg), out, indent=2)
        os.replace(temp, target)
        return True
    except OSError:
        try:
            os.unlink(temp)
        except OSError:
            pass
        return False


def record_activity():
    """The recorder's question: are programs and files being recorded?"""
    return load()["record_activity"]
