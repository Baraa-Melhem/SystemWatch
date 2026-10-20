# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
Entry point for the packaged SystemWatch.exe.

The source tree has two programs - main.py (the window) and recorder.py (the
headless device recorder). The packaged build ships one exe that plays
either role:

    SystemWatch.exe                      open the window
    SystemWatch.exe --tray               start hidden in the notification area
    SystemWatch.exe --recorder           run the headless recorder
    SystemWatch.exe --recorder --stop    ask a running recorder to exit
"""

import os
import sys

# A windowed exe has no console, so stdout/stderr are None. Anything that
# writes to them directly would crash; send it nowhere instead.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")


def run():
    if "--recorder" in sys.argv[1:]:
        import recorder

        rest = [a for a in sys.argv[1:] if a != "--recorder"]
        return recorder.main([sys.argv[0]] + rest)

    import main

    return main.main()


if __name__ == "__main__":
    sys.exit(run())
