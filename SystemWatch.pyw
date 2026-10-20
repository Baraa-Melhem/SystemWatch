# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
Double-click launcher.

The .pyw extension tells Windows to run this with pythonw.exe, so no black
console window appears. If you want to see diagnostic output instead, run
`python main.py` from a terminal.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import main

if __name__ == "__main__":
    main()
