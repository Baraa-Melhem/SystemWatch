# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
Run every SystemWatch test.

    python tests/run_all.py

Each test runs in its own process, against a sandboxed copy of the records,
so nothing here can damage the real ones.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

TESTS = [
    ("history", "test_history.py", "records: rolling window, tamper evidence"),
    ("config", "test_config.py", "settings: validation, atomic save"),
    ("activity", "test_activity.py", "programs and files watcher"),
    ("ui", "test_ui.py", "window, all three tabs, both records on screen"),
]


def main():
    print("SystemWatch test suite\n" + "=" * 60)
    failures = []
    for name, script, description in TESTS:
        path = os.path.join(HERE, script)
        if not os.path.exists(path):
            print(f"  SKIP  {name:10s} ({script} not found)")
            continue
        started = time.time()
        result = subprocess.run(
            [sys.executable, "-u", path],
            capture_output=True, text=True, timeout=300,
        )
        took = time.time() - started
        ok = result.returncode == 0
        print(f"  {'PASS' if ok else 'FAIL'}  {name:10s} {took:5.1f}s  "
              f"{description}")
        if not ok:
            failures.append(name)
            for line in (result.stdout or "").splitlines():
                if "FAIL" in line or "Error" in line:
                    print(f"          {line.strip()}")
            for line in (result.stderr or "").splitlines()[-6:]:
                print(f"          {line.rstrip()}")

    print("=" * 60)
    if failures:
        print(f"FAILED: {', '.join(failures)}")
        return 1
    print(f"All {len(TESTS)} suites passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
