# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
Tests for the settings file.

config.json is plain user-editable JSON, so the loader must survive anything
in it: wrong types, unknown keys, a truncated file, or not JSON at all.
Runs in a sandbox - never touches the real settings.
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_box = tempfile.mkdtemp(prefix="swcfg-")
os.environ["LOCALAPPDATA"] = os.path.join(_box, "local")
os.makedirs(os.environ["LOCALAPPDATA"], exist_ok=True)

import config  # noqa: E402

FAILS = []


def check(name, cond, note=""):
    print(f"  [{'ok ' if cond else 'FAIL'}] {name}" + (f"  ({note})" if note else ""))
    if not cond:
        FAILS.append(name)


def write_raw(text):
    with open(config.path(), "w", encoding="utf-8") as fh:
        fh.write(text)


def main():
    print("=== missing file -> defaults ===")
    cfg = config.load()
    check("backfill default", cfg["backfill"] == 25)
    check("activity recorded by default", cfg["record_activity"] is True)
    check("not yet welcomed", cfg["welcomed"] is False)

    print("\n=== round trip ===")
    cfg["backfill"] = 60
    cfg["record_activity"] = False
    check("save succeeds", config.save(cfg))
    again = config.load()
    check("backfill kept", again["backfill"] == 60)
    check("activity switch kept", again["record_activity"] is False)
    check("recorder sees it", config.record_activity() is False)
    leftovers = [n for n in os.listdir(config.folder()) if n.endswith(".tmp")]
    check("atomic save leaves no temp file", not leftovers, str(leftovers))

    print("\n=== hostile or broken files ===")
    for label, text in (
        ("not JSON", "{{{ nope"),
        ("truncated", '{"backfill": 4'),
        ("a list, not an object", "[1, 2, 3]"),
        ("empty", ""),
    ):
        write_raw(text)
        cfg = config.load()
        check(f"{label}: falls back to defaults",
              cfg["backfill"] == 25 and cfg["hide_noisy"] is True)

    write_raw(json.dumps({
        "backfill": "lots",               # wrong type
        "hide_noisy": "yes",              # string, not bool
        "notify_errors": 0,               # int, not bool
        "record_activity": None,
        "channels": ["System", 42, "Not-A-Real/Channel"],
        "geometry": 123,
        "evil": "<script>",               # unknown key
    }))
    cfg = config.load()
    check("wrong-typed backfill ignored", cfg["backfill"] == 25)
    check("string bool ignored", cfg["hide_noisy"] is True)
    check("int bool ignored", cfg["notify_errors"] is True)
    check("null bool ignored", cfg["record_activity"] is True)
    check("non-string and unknown channels dropped",
          "System" in cfg["channels"]
          and 42 not in cfg["channels"]
          and "Not-A-Real/Channel" not in cfg["channels"])
    check("wrong-typed geometry ignored", cfg["geometry"] == "")
    check("unknown keys dropped", "evil" not in cfg)

    write_raw(json.dumps({"backfill": 10 ** 9}))
    check("backfill clamped to range", config.load()["backfill"] == 200)
    write_raw(json.dumps({"backfill": True}))
    check("a bool is not a count", config.load()["backfill"] == 25)

    shutil.rmtree(_box, ignore_errors=True)
    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL CONFIG TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
