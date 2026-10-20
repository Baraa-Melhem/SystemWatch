# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
Optional "start with Windows" support.

This adds (or removes) a single shortcut file in your own per-user Startup
folder:

    %APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup

That is a plain folder inside your user profile. Putting a shortcut there is
not a system change: no registry keys, no services, no scheduled tasks, no
administrator rights, and nothing outside your own profile. Windows lists it
under Task Manager -> Startup apps, so you can disable it from there too, and
deleting the shortcut undoes it completely.
"""

import os
import sys

SHORTCUT_NAME = "SystemWatch.lnk"
RECORDER_SHORTCUT_NAME = "SystemWatch Recorder.lnk"


def _shell():
    import win32com.client

    return win32com.client.Dispatch("WScript.Shell")


def startup_dir():
    try:
        return _shell().SpecialFolders("Startup")
    except Exception:
        return os.path.join(
            os.environ.get("APPDATA", ""),
            r"Microsoft\Windows\Start Menu\Programs\Startup",
        )


def shortcut_path():
    return os.path.join(startup_dir(), SHORTCUT_NAME)


def recorder_shortcut_path():
    return os.path.join(startup_dir(), RECORDER_SHORTCUT_NAME)


def pythonw():
    """Prefer pythonw.exe so no console window appears at login."""
    exe = sys.executable or ""
    if exe.lower().endswith("python.exe"):
        candidate = exe[: -len("python.exe")] + "pythonw.exe"
        if os.path.exists(candidate):
            return candidate
    return exe


def is_frozen():
    """True when running as the packaged SystemWatch.exe, not as scripts."""
    return bool(getattr(sys, "frozen", False))


def app_dir():
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def command_for(script, arguments=""):
    """
    Returns [program, arg, ...] that starts one of SystemWatch's two parts.

    Run from source, that is pythonw.exe plus the script. In the packaged
    build there is a single SystemWatch.exe, and the recorder is the same exe
    started with --recorder.
    """
    extra = arguments.split()
    if is_frozen():
        role = ["--recorder"] if script == "recorder.py" else []
        return [sys.executable] + role + extra
    return [pythonw(), os.path.join(app_dir(), script)] + extra


def is_enabled():
    return os.path.exists(shortcut_path())


def recorder_is_enabled():
    return os.path.exists(recorder_shortcut_path())


def _make_shortcut(path, script, arguments, description):
    folder = app_dir()
    program, *args = command_for(script, arguments)
    link = _shell().CreateShortCut(path)
    link.TargetPath = program
    link.Arguments = " ".join(
        '"' + a + '"' if " " in a else a for a in args
    )
    link.WorkingDirectory = folder
    link.Description = description
    link.WindowStyle = 7  # minimised
    icon = os.path.join(folder, "systemwatch.ico")
    if is_frozen():
        link.IconLocation = sys.executable + ",0"
    elif os.path.exists(icon):
        link.IconLocation = icon
    link.save()
    return path


def enable():
    """Open the SystemWatch window (in the tray) at login."""
    return _make_shortcut(
        shortcut_path(), "main.py", " --tray",
        "SystemWatch - read-only system event monitor",
    )


def enable_recorder():
    """
    Run the headless device recorder at login.

    This is the one that matters for "record even when the window is not
    open": it has no interface, and keeps writing the device record whether
    or not anybody launches SystemWatch itself.
    """
    return _make_shortcut(
        recorder_shortcut_path(), "recorder.py", "",
        "SystemWatch device recorder - records USB and device connections",
    )


def _remove(path):
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def disable():
    return _remove(shortcut_path())


def disable_recorder():
    return _remove(recorder_shortcut_path())


if __name__ == "__main__":
    arg = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    if arg == "enable":
        print("Window at login  : " + enable())
        print("Recorder at login: " + enable_recorder())
    elif arg == "disable":
        print("Window shortcut removed." if disable()
              else "Window: was already off.")
        print("Recorder shortcut removed." if disable_recorder()
              else "Recorder: was already off.")
    elif arg == "enable-recorder":
        print("Recorder at login: " + enable_recorder())
    elif arg == "disable-recorder":
        print("Removed." if disable_recorder() else "Was not enabled.")
    else:
        state = lambda on: "ON" if on else "OFF"
        print("Open window at login : " + state(is_enabled()))
        print("Run recorder at login: " + state(recorder_is_enabled()))
        print("Startup folder       : " + startup_dir())
        print("Launcher             : " + pythonw())
