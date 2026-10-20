# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
Renders the shield drawn by ui.shield_icon() into systemwatch.ico, so the
exe, the installer and the shortcuts carry the same icon as the tray.

    python packaging/make_icon.py <output.ico>
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import QBuffer, QByteArray, QIODevice
from PyQt5.QtWidgets import QApplication

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def main(out_path):
    from PIL import Image
    import io

    app = QApplication(sys.argv)  # noqa: F841 - QPixmap needs an app
    from ui import shield_icon

    images = []
    for size in SIZES:
        pix = shield_icon(size=size).pixmap(size, size)
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.WriteOnly)
        pix.save(buf, "PNG")
        images.append(Image.open(io.BytesIO(bytes(data))).convert("RGBA"))

    largest = images[-1]
    largest.save(out_path, format="ICO", sizes=[(s, s) for s in SIZES],
                 append_images=images[:-1])
    print("wrote " + out_path)


if __name__ == "__main__":
    main(sys.argv[1])
