# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
Plain-English translations for Windows event log records.

Every rule turns a technical event into three things a human can act on:
    title    - a one-line headline ("A program crashed")
    meaning  - what actually happened, in normal words
    action   - what, if anything, the user should do about it

Rules are looked up in order of specificity:
    1. (provider, event_id)   - most precise; event IDs collide across providers
    2. (channel,  event_id)   - fallback for providers we do not know by name
    3. generic by severity    - so *every* event still gets plain language

`title` may contain {placeholders} that are filled from the event's own data
fields, e.g. "{d0} stopped working" -> "chrome.exe stopped working".
Missing fields collapse to an empty string instead of raising.
"""

# --- severity ---------------------------------------------------------------
# Deliberately only three levels, matching the green / yellow / red spec.
INFO = "info"     # green  - normal, nothing to do
WARN = "warn"     # yellow - worth a glance
ERROR = "error"   # red    - needs attention

SEVERITY_LABEL = {INFO: "Info", WARN: "Warning", ERROR: "Error"}
# Signal colours. Chosen against the darkest surface (INK_0 in theme.py)
# and re-checked against their own tinted cards, since severity text is
# often drawn on a wash rather than the plain background. Measured
# contrast on INK_0: info 10.4:1, warning 10.3:1, error 6.1:1 - all clear
# of WCAG AA, and each still at least 4.5:1 on its own wash.
SEVERITY_COLOR = {INFO: "#3ED598", WARN: "#F2B138", ERROR: "#F1615A"}
SEVERITY_ORDER = {ERROR: 0, WARN: 1, INFO: 2}

# Windows Level field -> our severity
LEVEL_TO_SEVERITY = {
    0: INFO,   # LogAlways
    1: ERROR,  # Critical
    2: ERROR,  # Error
    3: WARN,   # Warning
    4: INFO,   # Information
    5: INFO,   # Verbose
}

# --- channels ---------------------------------------------------------------
# Friendly names + whether the channel needs Administrator rights to read.
CHANNELS = {
    "System": {
        "label": "Windows & hardware",
        "needs_admin": False,
        "default_on": True,
    },
    "Application": {
        "label": "Apps & programs",
        "needs_admin": False,
        "default_on": True,
    },
    "Microsoft-Windows-Windows Defender/Operational": {
        "label": "Antivirus (Defender)",
        "needs_admin": False,
        "default_on": True,
    },
    "Setup": {
        "label": "Windows updates & setup",
        "needs_admin": False,
        "default_on": False,
    },
    "Security": {
        "label": "Sign-ins & security",
        "needs_admin": True,
        "default_on": True,
    },
}

# How Windows describes the way somebody signed in (event 4624 / 4625).
LOGON_TYPES = {
    "2": "at the keyboard",
    "3": "over the network (e.g. a shared folder)",
    "4": "as a scheduled task",
    "5": "as a background service",
    "7": "by unlocking the screen",
    "8": "over the network, password sent as plain text",
    "9": "by running a program as a different user",
    "10": "through Remote Desktop",
    "11": "using a saved (cached) password",
}


def _r(title, meaning, action, severity, noisy=False):
    return {
        "title": title,
        "meaning": meaning,
        "action": action,
        "severity": severity,
        "noisy": noisy,
    }


_OK = "Nothing to do. This is normal."
_WATCH = "Nothing to do unless you keep seeing it."

# --- provider-specific rules: (provider, event id) --------------------------
BY_PROVIDER = {
    # ---------------------------------------------------------------- power
    ("Microsoft-Windows-Kernel-Power", 41): _r(
        "The PC shut down without warning",
        "Windows never got the chance to shut down properly last time. That "
        "usually means a crash, a power cut, or the battery dying — or you "
        "held the power button down.",
        "If this keeps happening, check that the charger is seated properly "
        "and look for a matching 'blue screen' entry around the same time.",
        ERROR,
    ),
    ("Microsoft-Windows-Kernel-Power", 42): _r(
        "The PC went to sleep",
        "Windows put the laptop into sleep mode to save power.",
        _OK, INFO, noisy=True,
    ),
    ("Microsoft-Windows-Kernel-Power", 107): _r(
        "The PC woke up from sleep",
        "Windows resumed from sleep mode.",
        _OK, INFO, noisy=True,
    ),
    ("Microsoft-Windows-Kernel-Power", 105): _r(
        "Power source changed",
        "The laptop switched between running on battery and running on the "
        "charger.",
        _OK, INFO, noisy=True,
    ),
    ("Microsoft-Windows-Kernel-Power", 109): _r(
        "Windows started shutting down",
        "The system kernel began a shutdown or restart.",
        _OK, INFO, noisy=True,
    ),
    ("Microsoft-Windows-Kernel-Power", 507): _r(
        "The PC came out of standby",
        "The laptop left the low-power 'modern standby' state — usually "
        "because you opened the lid or pressed a key.",
        _OK, INFO, noisy=True,
    ),
    ("Microsoft-Windows-Kernel-Power", 566): _r(
        "Power state bookkeeping",
        "Windows recorded an internal change in its power session. This is "
        "routine background chatter.",
        _OK, INFO, noisy=True,
    ),
    ("Microsoft-Windows-Kernel-Power", 172): _r(
        "Network status while asleep",
        "Windows noted whether it still had internet while in standby.",
        _OK, INFO, noisy=True,
    ),
    ("Microsoft-Windows-Power-Troubleshooter", 1): _r(
        "The PC woke from sleep",
        "Windows recorded what woke the laptop up — a key press, the lid, a "
        "timer, or a USB device.",
        _OK, INFO, noisy=True,
    ),

    # ------------------------------------------------------- start / shutdown
    ("EventLog", 6005): _r(
        "The PC started up",
        "Windows finished booting and began recording events again.",
        _OK, INFO,
    ),
    ("EventLog", 6006): _r(
        "The PC shut down normally",
        "Windows stopped recording events as part of a clean, orderly "
        "shutdown.",
        _OK, INFO,
    ),
    ("EventLog", 6008): _r(
        "The last shutdown was unexpected",
        "Windows noticed that the previous session ended without a proper "
        "shutdown — a crash, a freeze, or a sudden power loss.",
        "One-off events are usually harmless. If it repeats, it is worth "
        "checking the battery and looking for driver problems.",
        ERROR,
    ),
    ("EventLog", 6013): _r(
        "Daily uptime report",
        "Windows logs once a day how long the PC has been running.",
        _OK, INFO, noisy=True,
    ),
    ("User32", 1074): _r(
        "A shutdown or restart was requested",
        "A person or a program asked Windows to shut down or restart. The "
        "details below name who asked and why.",
        _OK, INFO,
    ),
    ("Microsoft-Windows-Wininit", 1001): _r(
        "Disk check results",
        "Windows ran a check on the disk and recorded the result.",
        "Read the details below — if it reports repaired errors, keep an eye "
        "on the drive's health.",
        INFO,
    ),
    ("BugCheck", 1001): _r(
        "The PC hit a blue screen",
        "Windows crashed and restarted itself. The technical details include "
        "a stop code that identifies the cause — very often a driver.",
        "If this happens more than once, note the stop code below and update "
        "your drivers, especially graphics and storage.",
        ERROR,
    ),
    ("Microsoft-Windows-WER-SystemErrorReporting", 1001): _r(
        "A blue screen was reported",
        "Windows saved a crash report describing the blue screen it just "
        "recovered from.",
        "Nothing to do right now. Repeated reports point at a faulty driver "
        "or failing hardware.",
        ERROR,
    ),

    # ------------------------------------------------------------- services
    ("Service Control Manager", 7000): _r(
        "A background service failed to start",
        "Windows tried to start '{d0}' and it did not come up. Many services "
        "are optional, so this is not always a problem.",
        _WATCH, WARN,
    ),
    ("Service Control Manager", 7001): _r(
        "A service could not start because another one failed",
        "'{d0}' depends on a service that itself failed to start.",
        _WATCH, WARN,
    ),
    ("Service Control Manager", 7009): _r(
        "A service took too long to respond",
        "Windows gave up waiting for '{d1}' to start.",
        _WATCH, WARN,
    ),
    ("Service Control Manager", 7011): _r(
        "A service stopped responding",
        "'{d1}' did not answer Windows in time. This often happens when the "
        "PC is very busy.",
        _WATCH, WARN,
    ),
    ("Service Control Manager", 7022): _r(
        "A service hung while starting",
        "'{d0}' froze on startup instead of finishing.",
        _WATCH, WARN,
    ),
    ("Service Control Manager", 7023): _r(
        "A service stopped with an error",
        "'{d0}' shut down and reported a problem.",
        _WATCH, WARN,
    ),
    ("Service Control Manager", 7024): _r(
        "A service stopped with its own error code",
        "'{d0}' exited and reported an error specific to that service.",
        _WATCH, WARN,
    ),
    ("Service Control Manager", 7026): _r(
        "A startup driver did not load",
        "One of the drivers Windows loads at boot failed to load.",
        _WATCH, WARN,
    ),
    ("Service Control Manager", 7031): _r(
        "A service crashed and is being restarted",
        "'{d0}' stopped unexpectedly. Windows will try to start it again "
        "automatically.",
        _WATCH, WARN,
    ),
    ("Service Control Manager", 7034): _r(
        "A service crashed",
        "'{d0}' stopped unexpectedly and Windows will not restart it on its "
        "own.",
        "If this belongs to software you actually use, restarting that "
        "program (or the PC) usually clears it.",
        WARN,
    ),
    ("Service Control Manager", 7036): _r(
        "A background service started or stopped",
        "Routine service activity — services start and stop constantly as "
        "Windows works.",
        _OK, INFO, noisy=True,
    ),
    ("Service Control Manager", 7040): _r(
        "A service's startup setting changed",
        "A service was switched between automatic, manual, or disabled. "
        "Windows Update and installers do this regularly.",
        _OK, INFO, noisy=True,
    ),
    ("Service Control Manager", 7045): _r(
        "New background software was installed",
        "A new service called '{d0}' was registered on this PC. Installers "
        "do this legitimately — but so does unwanted software.",
        "If you just installed something, this is expected. If you did not, "
        "look up the name below before dismissing it.",
        WARN,
    ),

    # ---------------------------------------------------------------- disks
    ("disk", 7): _r(
        "A bad spot was found on the disk",
        "The drive reported a block it could not use.",
        "Back up anything important. Repeated bad blocks mean a drive is on "
        "its way out.",
        ERROR,
    ),
    ("disk", 51): _r(
        "A hiccup while writing to the disk",
        "Windows hit an error during a disk operation and retried it.",
        "Occasional entries are common. Frequent ones deserve a disk check.",
        WARN,
    ),
    ("disk", 52): _r(
        "The disk predicts its own failure",
        "The drive's built-in health monitoring (SMART) expects to fail soon.",
        "Back up your files now and plan to replace the drive.",
        ERROR,
    ),
    ("disk", 153): _r(
        "A disk request had to be retried",
        "The drive did not answer the first time and Windows tried again.",
        _WATCH, WARN,
    ),
    ("disk", 157): _r(
        "A disk was disconnected unexpectedly",
        "A drive vanished without being safely ejected — normal for a "
        "yanked USB stick, worrying for an internal drive.",
        "If this was an external drive you unplugged, ignore it.",
        WARN,
    ),
    ("Ntfs", 55): _r(
        "Damage found in the file system",
        "Windows found inconsistencies in the structure that tracks your "
        "files on disk.",
        "Back up important files, then run a disk check on that drive.",
        ERROR,
    ),
    ("Ntfs", 98): _r(
        "File system health note",
        "Windows recorded a note about the condition of a drive's file "
        "system.",
        _WATCH, WARN,
    ),
    ("storahci", 129): _r(
        "The storage controller was reset",
        "The disk stopped responding briefly and Windows reset it. Often "
        "harmless; sometimes an early sign of a failing drive or cable.",
        _WATCH, WARN,
    ),

    # ------------------------------------------------------ devices/drivers
    ("Microsoft-Windows-Kernel-PnP", 219): _r(
        "A device's driver failed to load",
        "Windows found a piece of hardware but could not load the software "
        "that runs it.",
        "If a device is not working, updating its driver usually fixes this.",
        WARN,
    ),

    # ------------------------------------------------------ windows updates
    ("Microsoft-Windows-WindowsUpdateClient", 19): _r(
        "An update installed successfully",
        "Windows Update finished installing '{updateTitle}'.",
        _OK, INFO,
    ),
    ("Microsoft-Windows-WindowsUpdateClient", 20): _r(
        "An update failed to install",
        "Windows Update could not finish installing '{updateTitle}'.",
        "Windows normally retries on its own. If an update keeps failing, "
        "run Windows Update manually from Settings.",
        WARN,
    ),
    ("Microsoft-Windows-WindowsUpdateClient", 43): _r(
        "An update started installing",
        "Windows Update began installing new software in the background.",
        _OK, INFO, noisy=True,
    ),
    ("Microsoft-Windows-WindowsUpdateClient", 44): _r(
        "An update is downloading",
        "Windows Update started downloading a new update.",
        _OK, INFO, noisy=True,
    ),

    # ---------------------------------------------------------------- COM
    ("Microsoft-Windows-DistributedCOM", 10016): _r(
        "A permission warning you can safely ignore",
        "A Windows component asked to start another component and was told "
        "no. This is a very well-known piece of harmless noise — Microsoft "
        "has confirmed it can be ignored.",
        "Nothing to do. Genuinely.",
        INFO, noisy=True,
    ),
    ("Microsoft-Windows-DistributedCOM", 10010): _r(
        "A component was slow to register",
        "A background component did not check in with Windows fast enough. "
        "Usually harmless timing noise.",
        _OK, INFO, noisy=True,
    ),
    ("Microsoft-Windows-DistributedCOM", 10005): _r(
        "A component could not be started",
        "Windows failed to launch a background component it needed.",
        _WATCH, WARN,
    ),

    # ------------------------------------------------------------- programs
    ("Application Error", 1000): _r(
        "A program crashed",
        "'{d0}' stopped working and closed itself. Your other programs are "
        "unaffected.",
        "If the same program keeps crashing, reinstalling or updating it is "
        "the usual fix.",
        ERROR,
    ),
    ("Application Hang", 1002): _r(
        "A program stopped responding",
        "'{d0}' froze — this is the 'not responding' state where the window "
        "goes pale.",
        "If it happens often with the same program, update it.",
        WARN,
    ),
    ("Windows Error Reporting", 1001): _r(
        "A crash report was saved",
        "Windows wrote down the details of a program crash that just "
        "happened, in case you want to report it.",
        _OK, INFO, noisy=True,
    ),
    (".NET Runtime", 1026): _r(
        "A program crashed (.NET)",
        "A program built on Microsoft's .NET platform hit an unhandled error "
        "and closed.",
        "Update or reinstall the program if this repeats.",
        ERROR,
    ),
    ("MsiInstaller", 11707): _r(
        "Software installed successfully",
        "An installer finished putting a new program on this PC.",
        _OK, INFO,
    ),
    ("MsiInstaller", 11708): _r(
        "A software install failed",
        "An installer could not finish and undid its changes.",
        "Try the installer again, ideally as administrator.",
        WARN,
    ),
    ("MsiInstaller", 1034): _r(
        "Software was removed",
        "A program was uninstalled from this PC.",
        _OK, INFO,
    ),
    ("VSS", 8193): _r(
        "Backup snapshot error",
        "The Windows service that takes point-in-time snapshots (used by "
        "System Restore and backup tools) hit an error.",
        "Only matters if you rely on System Restore or a backup program.",
        WARN,
    ),
    ("VSS", 8194): _r(
        "Backup snapshot permission error",
        "The snapshot service was denied access it needed.",
        "Only matters if you rely on System Restore or backups.",
        WARN,
    ),

    # --------------------------------------------------------- antivirus
    ("Microsoft-Windows-Windows Defender", 1116): _r(
        "Antivirus found something",
        "Defender detected malware or unwanted software: '{Threat_Name}'. "
        "Detection alone does not mean it ran or did any damage.",
        "Look for a follow-up 'threat removed' entry. If none appears, open "
        "Windows Security and run a full scan.",
        ERROR,
    ),
    ("Microsoft-Windows-Windows Defender", 1117): _r(
        "Antivirus removed a threat",
        "Defender acted on the malware it found and dealt with it.",
        "You are protected. A full scan is still a reasonable follow-up.",
        INFO,
    ),
    ("Microsoft-Windows-Windows Defender", 1118): _r(
        "Antivirus could not fully remove a threat",
        "Defender tried to clean up malware and the cleanup did not complete.",
        "Open Windows Security and run a full (or offline) scan.",
        ERROR,
    ),
    ("Microsoft-Windows-Windows Defender", 1119): _r(
        "Antivirus cleanup failed",
        "Defender's attempt to remove a threat ran into an error.",
        "Open Windows Security and run a full scan.",
        ERROR,
    ),
    ("Microsoft-Windows-Windows Defender", 1006): _r(
        "Antivirus detected malware during a scan",
        "A scheduled or manual scan turned something up.",
        "Check that a removal entry follows this one.",
        ERROR,
    ),
    ("Microsoft-Windows-Windows Defender", 1007): _r(
        "Antivirus dealt with what it found",
        "Defender took action on the item from its scan.",
        "You are protected.",
        INFO,
    ),
    ("Microsoft-Windows-Windows Defender", 2000): _r(
        "Antivirus definitions updated",
        "Defender refreshed its list of known threats. This happens several "
        "times a day.",
        _OK, INFO, noisy=True,
    ),
    ("Microsoft-Windows-Windows Defender", 2001): _r(
        "Antivirus could not update its definitions",
        "Defender failed to download the newest threat list, so its "
        "protection is slightly out of date.",
        "Usually a temporary network issue. If it persists, check your "
        "internet connection and Windows Update.",
        WARN,
    ),
    ("Microsoft-Windows-Windows Defender", 5000): _r(
        "Real-time antivirus protection is on",
        "Defender is actively watching files as they are opened.",
        _OK, INFO,
    ),
    ("Microsoft-Windows-Windows Defender", 5001): _r(
        "Real-time antivirus protection is OFF",
        "Defender has stopped watching files in real time. Some other "
        "antivirus products turn this off on purpose when they take over.",
        "If you did not install another antivirus, turn real-time "
        "protection back on in Windows Security immediately.",
        ERROR,
    ),
    ("Microsoft-Windows-Windows Defender", 5007): _r(
        "Antivirus settings changed",
        "Something changed Defender's configuration — often an update, "
        "sometimes a person.",
        "Worth a look if you did not change anything yourself.",
        INFO, noisy=True,
    ),
    ("Microsoft-Windows-Windows Defender", 1150): _r(
        "Antivirus is healthy",
        "Defender reported that it is running normally.",
        _OK, INFO, noisy=True,
    ),
    ("Microsoft-Windows-Windows Defender", 1151): _r(
        "Antivirus health report",
        "Defender's routine status summary.",
        _OK, INFO, noisy=True,
    ),

    # -------------------------------------------------- security (needs admin)
    ("Microsoft-Windows-Security-Auditing", 4624): _r(
        "Someone signed in successfully",
        "The account '{TargetUserName}' signed in {logon_type_text}.",
        "Normal when it is you. Sign-ins you cannot account for — especially "
        "through Remote Desktop — are worth investigating.",
        INFO,
    ),
    ("Microsoft-Windows-Security-Auditing", 4625): _r(
        "A sign-in attempt failed",
        "Someone tried to sign in as '{TargetUserName}' and the password or "
        "account was rejected.",
        "One or two are just typos. Many in a row means something is "
        "guessing passwords.",
        WARN,
    ),
    ("Microsoft-Windows-Security-Auditing", 4634): _r(
        "Someone signed out",
        "A sign-in session for '{TargetUserName}' ended.",
        _OK, INFO, noisy=True,
    ),
    ("Microsoft-Windows-Security-Auditing", 4647): _r(
        "A user signed out",
        "'{TargetUserName}' deliberately signed out.",
        _OK, INFO, noisy=True,
    ),
    ("Microsoft-Windows-Security-Auditing", 4648): _r(
        "A program ran as a different user",
        "Someone supplied another account's credentials — this is what "
        "'Run as administrator' and 'Run as different user' look like.",
        "Normal if you did it. Unexpected entries are worth a look.",
        INFO, noisy=True,
    ),
    ("Microsoft-Windows-Security-Auditing", 4672): _r(
        "An administrator signed in",
        "The account that just signed in has full administrator powers.",
        "Normal for your own admin account.",
        INFO, noisy=True,
    ),
    ("Microsoft-Windows-Security-Auditing", 4688): _r(
        "A program started",
        "A new process was launched on this PC.",
        _OK, INFO, noisy=True,
    ),
    ("Microsoft-Windows-Security-Auditing", 4720): _r(
        "A new user account was created",
        "Someone added a new account called '{TargetUserName}' to this PC.",
        "If you did not create it, this is a serious red flag — investigate "
        "immediately.",
        WARN,
    ),
    ("Microsoft-Windows-Security-Auditing", 4726): _r(
        "A user account was deleted",
        "The account '{TargetUserName}' was removed from this PC.",
        "Expected if you removed it yourself.",
        WARN,
    ),
    ("Microsoft-Windows-Security-Auditing", 4724): _r(
        "Someone reset an account password",
        "An administrator changed the password on '{TargetUserName}' "
        "without knowing the old one.",
        "Investigate if that was not you.",
        WARN,
    ),
    ("Microsoft-Windows-Security-Auditing", 4732): _r(
        "An account was added to a privileged group",
        "A user was put into a Windows group — if that group is "
        "Administrators, they now have full control of this PC.",
        "Check the group name below. Unexpected additions to Administrators "
        "should be reversed.",
        WARN,
    ),
    ("Microsoft-Windows-Security-Auditing", 4740): _r(
        "An account was locked out",
        "'{TargetUserName}' was locked after too many wrong passwords.",
        "Usually a forgotten password. Repeated lockouts can mean someone is "
        "guessing.",
        WARN,
    ),
    ("Microsoft-Windows-Security-Auditing", 4698): _r(
        "A scheduled task was created",
        "Something set up a job to run automatically on a schedule. "
        "Legitimate software does this — so does malware wanting to survive "
        "reboots.",
        "If you did not install anything just now, check the task name.",
        WARN,
    ),
    ("Microsoft-Windows-Security-Auditing", 4719): _r(
        "The security auditing policy was changed",
        "Someone changed what Windows records in its security log.",
        "Unexpected changes here can be an attempt to hide activity.",
        ERROR,
    ),
    ("Microsoft-Windows-Security-Auditing", 1102): _r(
        "The security log was cleared",
        "Someone wiped the record of security events on this PC.",
        "If you did not do this deliberately, treat it as serious — it is a "
        "classic way of covering tracks.",
        ERROR,
    ),
    ("Microsoft-Windows-Security-Auditing", 4697): _r(
        "New background software was installed",
        "A service was installed on the PC.",
        "Expected right after installing software; suspicious otherwise.",
        WARN,
    ),
    ("Microsoft-Windows-Security-Auditing", 5140): _r(
        "A shared folder was accessed",
        "Someone reached a network share on this PC.",
        _OK, INFO, noisy=True,
    ),
    ("Microsoft-Windows-Security-Auditing", 4776): _r(
        "A password was checked",
        "Windows validated an account's credentials.",
        _OK, INFO, noisy=True,
    ),
    ("Microsoft-Windows-Security-Auditing", 4798): _r(
        "An account's group memberships were listed",
        "A program looked up which groups a user belongs to. Common for "
        "management tools, also used by attackers scoping out a machine.",
        _OK, INFO, noisy=True,
    ),
}

# --- channel-level fallbacks: (channel, event id) ---------------------------
BY_CHANNEL = {
    ("Application", 1000): BY_PROVIDER[("Application Error", 1000)],
    ("Application", 1002): BY_PROVIDER[("Application Hang", 1002)],
}

# --- generic fallbacks by severity ------------------------------------------
GENERIC = {
    ERROR: _r(
        "Something failed",
        "{provider_friendly} reported an error. The exact wording from "
        "Windows is in the details below.",
        "Read the details. If this component matters to you and the error "
        "repeats, it is worth searching for the message text.",
        ERROR,
    ),
    WARN: _r(
        "Something needs attention",
        "{provider_friendly} logged a warning — it kept working, but "
        "something was not quite right.",
        "Usually safe to ignore unless it repeats.",
        WARN,
    ),
    INFO: _r(
        "Routine activity",
        "{provider_friendly} recorded a normal status update.",
        _OK,
        INFO,
    ),
}


def friendly_provider(provider):
    """Turn 'Microsoft-Windows-Kernel-Power' into 'Kernel Power'."""
    if not provider:
        return "Windows"
    name = provider
    for prefix in ("Microsoft-Windows-", "Microsoft-"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    name = name.split("/")[0]
    return name.replace("-", " ").strip() or provider


class _Blanks(dict):
    """Format map that yields '' for anything it does not have."""

    def __missing__(self, key):
        return ""


def _fill(text, fields):
    if "{" not in text:
        return text
    try:
        return text.format_map(_Blanks(fields))
    except (ValueError, IndexError):
        return text


def summarise(message, limit=95):
    """
    Condense Windows' own description into one headline-length line.

    Used for events we have no hand-written rule for: Windows' wording is
    almost always clearer than a generic "routine activity", so we lead with
    its first sentence rather than hiding it in the technical section.
    """
    text = " ".join((message or "").split())
    if not text:
        return ""
    for sep in (". ", "! ", "? "):
        idx = text.find(sep)
        if 0 < idx <= limit:
            text = text[: idx + 1]
            break
    text = text.rstrip(". ")
    if len(text) > limit:
        cut = text.rfind(" ", 0, limit)
        text = text[: cut if cut > 40 else limit].rstrip(",;: ") + "…"
    return text


def translate(event):
    """
    Take a parsed event dict and attach plain-English fields to it.

    Expects: provider, event_id, channel, level, fields (dict), message (str).
    Adds:    title, meaning, action, severity, noisy.
    """
    provider = event.get("provider") or ""
    eid = event.get("event_id")
    channel = event.get("channel") or ""
    fields = dict(event.get("fields") or {})

    fields["provider_friendly"] = friendly_provider(provider)

    # Make sign-in events read naturally.
    lt = fields.get("LogonType")
    fields["logon_type_text"] = LOGON_TYPES.get(str(lt), "on this PC")

    rule = (
        BY_PROVIDER.get((provider, eid))
        or BY_CHANNEL.get((channel, eid))
        or GENERIC[LEVEL_TO_SEVERITY.get(event.get("level", 4), INFO)]
    )

    known = (provider, eid) in BY_PROVIDER or (channel, eid) in BY_CHANNEL

    event["title"] = _fill(rule["title"], fields)
    event["meaning"] = _fill(rule["meaning"], fields)
    event["action"] = rule["action"]
    event["severity"] = rule["severity"]
    event["noisy"] = rule["noisy"]
    event["known"] = known
    # "device" / "network" tag, used by the Devices & Network tab.
    event["kind"] = rule.get("kind", "")

    # No hand-written rule? Windows' own sentence beats a generic label like
    # "Routine activity", so lead with it and keep the generic text for the
    # advice line only.
    if not known:
        headline = summarise(event.get("message", ""))
        if headline:
            event["title"] = headline
            event["meaning"] = " ".join(event["message"].split())
            event["verbatim"] = True

    for hook in _REFINERS:
        try:
            hook(event, fields)
        except Exception:
            pass
    return event


# Hooks that adjust an event after the base rule is applied. Registered at
# the bottom of this file; kept as a list so the device/network logic can
# live next to its own rules instead of being tangled into translate().
_REFINERS = []


# Device and network knowledge extends the tables above. Imported last so
# that everything it references already exists.
#
# This must be a plain `import`, not `from devices import ...`. The two
# modules are mutually dependent, and a from-import demands the other module
# be *finished*, which it is not when devices.py is the one imported first.
# A plain import only needs the module object to exist, so both orders work.
import devices  # noqa: E402,F401

try:
    # Convenience alias for callers that already have translations imported.
    describe_device = devices.describe_device
except AttributeError:  # mid-cycle; import it from devices directly instead
    pass
