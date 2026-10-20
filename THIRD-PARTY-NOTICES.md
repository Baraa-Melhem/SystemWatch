# Third-party notices

SystemWatch's own code is licensed under the GNU GPL v3 (see `LICENSE`).
The packaged installer (`SystemWatch-Setup-*.exe`) also bundles the
following components, each under its own licence. Their source code is
available from the links below; SystemWatch's source is at
<https://github.com/Baraa-Melhem/SystemWatch>.

| Component | Version in the installer | Licence | Source |
|---|---|---|---|
| Python | 3.11 | Python Software Foundation License 2 | <https://www.python.org/> |
| PyQt5 | 5.15.11 | GNU GPL v3 | <https://www.riverbankcomputing.com/software/pyqt/> |
| Qt | 5.15.2 | GNU LGPL v3 | <https://download.qt.io/archive/qt/5.15/> |
| pywin32 | 312 | Python Software Foundation License | <https://github.com/mhammond/pywin32> |
| psutil | 7.2.2 | BSD 3-Clause | <https://github.com/giampaolo/psutil> |
| PyInstaller bootloader | 6.22 | GNU GPL v2 with bootloader exception | <https://github.com/pyinstaller/pyinstaller> |
| Microsoft Visual C++ runtime | 14 | Microsoft redistributable licence | <https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist> |

PyQt5 is GPL v3, which is why SystemWatch is GPL v3 too: a program
distributed together with GPL-licensed PyQt5 must be offered under the GPL.

Qt is used as unmodified shared libraries (`Qt5*.dll`) loaded at run time,
as the LGPL v3 permits; you may replace them with your own build of Qt
5.15 in the installed `_internal\PyQt5\Qt5\bin` folder.

The full text of the GPL v3 is in `LICENSE`. The LGPL v3 is at
<https://www.gnu.org/licenses/lgpl-3.0.html>, the PSF License at
<https://docs.python.org/3/license.html>, and the BSD 3-Clause licence of
psutil in its repository.
