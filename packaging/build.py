# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
Builds the shareable SystemWatch installer.

    packaging\\build.bat          (does everything below)

Steps:
  1. render systemwatch.ico from the tray shield
  2. freeze the app into dist\\SystemWatch\\ with PyInstaller (one exe that is
     both the window and, with --recorder, the headless recorder)
  3. prune Qt pieces a widgets-only app never loads (OpenGL fallback,
     QML/Quick, WebGL platform) - roughly halves the size
  4. compile installer.iss with Inno Setup into ..\\release\\

Run it with the build venv's Python; build.bat creates that venv.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(HERE, "dist")
WORK = os.path.join(HERE, "build")
APP = os.path.join(DIST, "SystemWatch")
ICON = os.path.join(HERE, "systemwatch.ico")

# Never loaded by SystemWatch: it is QtWidgets only, with no QML, no network
# module and no OpenGL.
PRUNE = [
    r"PyQt5\Qt5\bin\opengl32sw.dll",
    r"PyQt5\Qt5\bin\d3dcompiler_47.dll",
    r"PyQt5\Qt5\bin\libEGL.dll",
    r"PyQt5\Qt5\bin\libGLESv2.dll",
    r"PyQt5\Qt5\bin\Qt5Quick.dll",
    r"PyQt5\Qt5\bin\Qt5Qml.dll",
    r"PyQt5\Qt5\bin\Qt5QmlModels.dll",
    r"PyQt5\Qt5\bin\Qt5WebSockets.dll",
    r"PyQt5\Qt5\bin\Qt5Network.dll",
    r"PyQt5\Qt5\bin\Qt5DBus.dll",
    r"PyQt5\Qt5\plugins\platforms\qwebgl.dll",
    r"PyQt5\Qt5\plugins\platformthemes",
    r"PyQt5\Qt5\plugins\generic",
]

ISCC_CANDIDATES = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Inno Setup 6\ISCC.exe"),
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]


def step(text):
    print("\n=== " + text)


def make_icon():
    step("icon")
    subprocess.check_call([sys.executable, os.path.join(HERE, "make_icon.py"), ICON])


def app_version():
    """Read version.py without importing the app."""
    scope = {}
    with open(os.path.join(ROOT, "version.py"), encoding="utf-8") as fh:
        exec(fh.read(), scope)
    return scope["__version__"]


def write_version_info():
    """Fill version_info.txt (the exe's Properties > Details) from version.py."""
    version = app_version()
    parts = (version.split(".") + ["0", "0", "0"])[:4]
    numbers = ", ".join(str(int(p)) for p in parts)
    with open(os.path.join(HERE, "version_info.txt"), encoding="utf-8") as fh:
        text = fh.read()
    import re
    text = re.sub(r"filevers=\([^)]*\)", f"filevers=({numbers})", text)
    text = re.sub(r"prodvers=\([^)]*\)", f"prodvers=({numbers})", text)
    text = re.sub(r"(StringStruct\('(?:File|Product)Version', ')[^']*'",
                  lambda m: m.group(1) + version + "'", text)
    out = os.path.join(WORK, "version_info.txt")
    os.makedirs(WORK, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    return out


def freeze():
    step("PyInstaller")
    env = dict(os.environ)
    # A venv made from Anaconda keeps ffi.dll, liblzma.dll and LIBBZ2.dll in
    # Library\bin, which PyInstaller only finds if it is on PATH. Without
    # ffi.dll the frozen app cannot use ctypes.
    conda_bin = os.path.join(sys.base_prefix, "Library", "bin")
    if os.path.isdir(conda_bin):
        env["PATH"] = conda_bin + os.pathsep + env.get("PATH", "")
    subprocess.check_call([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed", "--onedir",
        "--name", "SystemWatch",
        "--icon", ICON,
        "--version-file", write_version_info(),
        "--paths", ROOT,
        "--distpath", DIST, "--workpath", WORK, "--specpath", HERE,
        "--add-data", os.path.join(ROOT, "assets") + os.pathsep + "assets",
        "--hidden-import", "win32com.client",
        "--exclude-module", "tkinter",
        os.path.join(HERE, "launcher.py"),
    ], env=env)


def prune():
    step("prune")
    internal = os.path.join(APP, "_internal")
    for rel in PRUNE:
        path = os.path.join(internal, rel)
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)
        else:
            continue
        print("  removed " + rel)
    # Keep only the base Qt translations (standard dialog buttons).
    tr = os.path.join(internal, r"PyQt5\Qt5\translations")
    if os.path.isdir(tr):
        for name in os.listdir(tr):
            if not name.startswith("qtbase_"):
                os.remove(os.path.join(tr, name))
    total = sum(
        os.path.getsize(os.path.join(d, f))
        for d, _, files in os.walk(APP) for f in files
    )
    print(f"  app folder is now {total / 1e6:.0f} MB")


def installer():
    step("Inno Setup")
    iscc = next((p for p in ISCC_CANDIDATES if os.path.exists(p)), None)
    if not iscc:
        print("  Inno Setup 6 not found - install it with:\n"
              "    winget install JRSoftware.InnoSetup --scope user\n"
              "  The unpacked app is still usable at " + APP)
        return 1
    subprocess.check_call([iscc, "/Q", f"/DAppVersion={app_version()}",
                           os.path.join(HERE, "installer.iss")])
    print("  installer written to " + os.path.join(ROOT, "release"))
    return 0


def main():
    make_icon()
    freeze()
    prune()
    return installer()


if __name__ == "__main__":
    sys.exit(main())
