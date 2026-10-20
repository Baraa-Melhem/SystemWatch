# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
Devices (USB and friends) and networks.

Every rule here was written against a real record read from this machine's
own logs, so the field names are the ones Windows actually emits rather than
ones that merely look plausible.

This module is imported at the bottom of translations.py and extends the
tables defined there, so device/network knowledge lives in one place instead
of being tangled into the general event logic.
"""

from translations import (
    BY_PROVIDER, CHANNELS, ERROR, INFO, WARN, _OK, _REFINERS, _r,
)

# --- extra channels ---------------------------------------------------------
CHANNELS.update({
    "Microsoft-Windows-NetworkProfile/Operational": {
        "label": "Networks joined & left",
        "needs_admin": False,
        "default_on": True,
    },
    "Microsoft-Windows-WLAN-AutoConfig/Operational": {
        "label": "Wi-Fi",
        "needs_admin": False,
        "default_on": True,
    },
    "Microsoft-Windows-Ntfs/Operational": {
        "label": "Drives & USB storage",
        "needs_admin": False,
        "default_on": True,
    },
    "Microsoft-Windows-Kernel-PnP/Configuration": {
        "label": "Devices plugged in",
        "needs_admin": False,
        "default_on": True,
    },
})

# NetworkProfile "Category" field.
NETWORK_CATEGORY = {"0": "Public", "1": "Private", "2": "Domain"}

# A PnP device instance id starts with the bus it lives on. That prefix is the
# only reliable way to tell "somebody plugged a USB stick in" apart from
# "Windows re-enumerated an internal component", which happens constantly.
DEVICE_BUSES = [
    ("USBSTOR\\",      "USB storage device", False),
    ("WPDBUSENUMROOT", "portable device (phone, camera or media player)", False),
    ("USB\\",          "USB device", False),
    ("BTHENUM\\",      "Bluetooth device", False),
    ("BTHLEDEVICE",    "Bluetooth device", False),
    ("SD\\",           "memory card", False),
    ("MMC\\",          "memory card", False),
    ("HID\\",          "input device (keyboard, mouse or touchpad)", True),
    ("SWD\\",          "software device", True),
    ("ACPI\\",         "built-in system component", True),
    ("PCI\\",          "internal component", True),
    ("ROOT\\",         "system driver", True),
    ("SCSI\\",         "internal drive", True),
    ("STORAGE\\",      "storage volume", True),
    ("DISPLAY\\",      "monitor", True),
    ("UMB\\",          "system component", True),
]


def describe_device(instance_id):
    """
    Map a PnP device instance id to (plain-English kind, is_routine).

    is_routine is True for the internal components Windows re-enumerates on
    every boot and wake. Those get folded into "routine chatter" so that the
    things a person actually plugged in stand out.
    """
    text = (instance_id or "").upper()
    for prefix, label, routine in DEVICE_BUSES:
        if text.startswith(prefix):
            return label, routine
    return "device", True


def _article(label):
    """"A" or "An". USB reads as "you-ess-bee", so it takes "a"."""
    if label.upper().startswith("USB"):
        return "A"
    return "An" if label[0].lower() in "aeiou" else "A"


def parse_device_name(instance_id):
    """
    Pull a readable maker and model out of a device instance id.

    USB storage ids carry them in plain text, e.g.
        USBSTOR\Disk&Ven_Kingston&Prod_DataTraveler_3.0&Rev_PMAP\...
    becomes "Kingston DataTraveler 3.0". Ids that only carry numeric VID/PID
    codes have no name to give, so this returns "" and the caller falls back
    to the generic wording.
    """
    vendor = product = ""
    for token in (instance_id or "").replace("\\", "&").split("&"):
        upper = token.upper()
        if upper.startswith("VEN_"):
            vendor = token[4:]
        elif upper.startswith("PROD_"):
            product = token[5:]
    name = " ".join(
        part.replace("_", " ") for part in (vendor, product) if part
    )
    return " ".join(name.split())


def _d(title, meaning, action, severity, kind, noisy=False):
    rule = _r(title, meaning, action, severity, noisy)
    rule["kind"] = kind
    return rule


BY_PROVIDER.update({
    # ------------------------------------------------------------ networks
    ("Microsoft-Windows-NetworkProfile", 10000): _d(
        "Connected to the network “{Name}”",
        "This PC joined the network “{Name}”.",
        "Normal when you connect to Wi-Fi or plug in a cable. On a network "
        "you do not recognise, avoid signing in to anything sensitive.",
        INFO, "network",
    ),
    ("Microsoft-Windows-NetworkProfile", 10001): _d(
        "Disconnected from the network “{Name}”",
        "This PC left the network “{Name}”.",
        _OK, INFO, "network",
    ),
    ("Microsoft-Windows-NetworkProfile", 4004): _d(
        "Network status changed",
        "Windows noticed a change in connectivity — going online or offline, "
        "or switching between metered and unmetered.",
        _OK, INFO, "network", noisy=True,
    ),

    # ---------------------------------------------------------------- Wi-Fi
    ("Microsoft-Windows-WLAN-AutoConfig", 8001): _d(
        "Joined the Wi-Fi network “{SSID}”",
        "Connected to “{SSID}” using {AuthenticationAlgorithm} security with "
        "{CipherAlgorithm} encryption, over {InterfaceDescription}.",
        "Check the security type: WPA2-Personal or WPA3 is good. If it says "
        "Open or WEP, treat the connection as public and avoid banking on it.",
        INFO, "network",
    ),
    ("Microsoft-Windows-WLAN-AutoConfig", 8002): _d(
        "Could not join the Wi-Fi network “{SSID}”",
        "Windows tried to connect to “{SSID}” and failed. Reason given: "
        "{FailureReason}",
        "Usually the network was out of range or the password changed. "
        "Repeated failures on your own network can mean a weak signal.",
        WARN, "network",
    ),
    ("Microsoft-Windows-WLAN-AutoConfig", 8003): _d(
        "Left the Wi-Fi network “{SSID}”",
        "Disconnected from “{SSID}”. Reason given: {Reason}",
        _OK, INFO, "network",
    ),
    ("Microsoft-Windows-WLAN-AutoConfig", 11004): _d(
        "Wi-Fi security session ended",
        "The encrypted session with “{SSID}” was torn down — this always "
        "accompanies a disconnect.",
        _OK, INFO, "network", noisy=True,
    ),
    ("Microsoft-Windows-WLAN-AutoConfig", 11005): _d(
        "Wi-Fi security check passed",
        "The encryption handshake with “{SSID}” succeeded, so the connection "
        "is properly protected.",
        _OK, INFO, "network", noisy=True,
    ),

    # ------------------------------------------------------- drives and USB
    ("Microsoft-Windows-Ntfs", 4): _d(
        "Drive connected: {VolumeLabel} ({VolumeId})",
        "A drive was plugged in and mounted as {VolumeId}. Windows "
        "identifies it as {VendorId} {ProductId}.",
        "Expected if you just plugged something in. A drive appearing that "
        "you did not connect is worth a second look.",
        INFO, "device",
    ),
    ("Microsoft-Windows-Ntfs", 300): _d(
        "Drive is being removed: {VolumeLabel} ({VolumeId})",
        "Windows started safely disconnecting {VendorId} {ProductId}.",
        _OK, INFO, "device", noisy=True,
    ),
    ("Microsoft-Windows-Ntfs", 303): _d(
        "Drive removed: {VolumeLabel} ({VolumeId})",
        "The drive {VendorId} {ProductId} was disconnected from {VolumeId} "
        "and is now safe to unplug.",
        _OK, INFO, "device",
    ),
    ("Microsoft-Windows-Ntfs", 501): _d(
        "A program cleared a drive's change journal",
        "Something deleted the log NTFS keeps of recent file changes on "
        "{VolumeName}. Search indexers do this legitimately.",
        "Harmless from SearchIndexer. From an unfamiliar program it is worth "
        "checking, since it also erases a forensic trail.",
        INFO, "device",
    ),

    # Routine per-volume statistics: constant, and useful to nobody.
    ("Microsoft-Windows-Ntfs", 9): _d(
        "Drive housekeeping", "NTFS scanned a volume's free-space map.",
        _OK, INFO, "device", noisy=True),
    ("Microsoft-Windows-Ntfs", 10): _d(
        "Drive housekeeping", "NTFS recorded internal cache statistics.",
        _OK, INFO, "device", noisy=True),
    ("Microsoft-Windows-Ntfs", 142): _d(
        "Disk space summary",
        "Routine hourly note of how much free space {VolumeName} has.",
        _OK, INFO, "device", noisy=True),
    ("Microsoft-Windows-Ntfs", 151): _d(
        "Files deleted from your folders",
        "Windows counted files removed from Desktop, Documents, Downloads "
        "and similar folders in the last hour.",
        _OK, INFO, "device", noisy=True),
    ("Microsoft-Windows-Ntfs", 156): _d(
        "Drive housekeeping", "NTFS recorded internal lock statistics.",
        _OK, INFO, "device", noisy=True),
    ("Microsoft-Windows-Ntfs", 158): _d(
        "Drive housekeeping", "NTFS recorded metadata read/write counters.",
        _OK, INFO, "device", noisy=True),
    ("Microsoft-Windows-Ntfs", 170): _d(
        "Drive speed summary",
        "Routine note of how quickly {VolumeName} responded to requests.",
        _OK, INFO, "device", noisy=True),
    ("Microsoft-Windows-Ntfs", 171): _d(
        "Drive maintenance summary",
        "Routine note about trim operations on {VolumeName}.",
        _OK, INFO, "device", noisy=True),

    # -------------------------------------------------------------- devices
    # Default to routine; _refine_device promotes the ones a person actually
    # plugged in, based on which bus the device sits on.
    ("Microsoft-Windows-Kernel-PnP", 400): _d(
        "A device was set up",
        "Windows configured a device and installed its driver.",
        _OK, INFO, "device", noisy=True,
    ),
    ("Microsoft-Windows-Kernel-PnP", 410): _d(
        "A device started",
        "Windows started a device and it is now available for use.",
        _OK, INFO, "device", noisy=True,
    ),
})


# --- refinement hooks -------------------------------------------------------
def _refine_network(event, fields):
    """Attach the network name and say whether Windows trusts the network."""
    if event.get("kind") != "network":
        return

    event["network_name"] = fields.get("SSID") or fields.get("Name") or ""

    if event["event_id"] == 10000:
        category = NETWORK_CATEGORY.get(str(fields.get("Category", "")), "")
        if category == "Public":
            event["meaning"] += (
                "  Windows is treating it as a Public network, so this PC is "
                "hidden from other machines on it — the safer setting."
            )
        elif category == "Private":
            event["meaning"] += (
                "  Windows is treating it as a Private network, so this PC "
                "can be discovered by other machines on it. That is right for "
                "home or office, wrong for a café or airport."
            )
        elif category == "Domain":
            event["meaning"] += "  It is a managed work domain network."


def _refine_device(event, fields):
    """
    Give PnP events a real headline, and keep the internal components that
    Windows re-enumerates on every boot out of the way.
    """
    if event.get("kind") != "device":
        return

    volume = fields.get("VolumeId") or ""
    product = " ".join(
        part for part in (fields.get("VendorId"), fields.get("ProductId"))
        if part
    ).strip()
    if product:
        event["device_name"] = product
    if volume:
        event["device_volume"] = volume
    if fields.get("VolumeLabel"):
        event["device_label"] = fields["VolumeLabel"]

    # NTFS volume events name the volume twice and sometimes fall back to a
    # raw GUID path, which reads as "Windows (Windows)". Rebuild the headline
    # around what actually identifies the drive: its label, its letter, and
    # the hardware behind it.
    if event["event_id"] in (4, 300, 303) and volume:
        letter = volume if len(volume) == 2 and volume.endswith(":") else ""
        label = fields.get("VolumeLabel") or ""
        if "Volume{" in volume and not label:
            label = "Unnamed volume"
        verb = {4: "connected", 300: "being removed", 303: "removed"}[
            event["event_id"]
        ]
        headline = f"Drive {verb}: {label or 'Unnamed volume'}"
        if letter:
            headline += f" ({letter})"
        if product and product.lower() not in headline.lower():
            headline += f" — {product}"
        event["title"] = headline

    instance = fields.get("DeviceInstanceId")
    if not instance:
        return

    label, routine = describe_device(instance)
    event["device_kind"] = label
    event["device_id"] = instance
    # 400 "configured" and 410 "started" fire as a pair for the same device,
    # so only the second is shown - one plug-in should be one row.
    event["noisy"] = routine or event["event_id"] == 400

    if not routine:
        name = parse_device_name(instance)
        if name:
            event["device_name"] = name
            event["title"] = f"{label[0].upper()}{label[1:]} connected: {name}"
        else:
            event["title"] = f"{_article(label)} {label} was connected"

        driver = fields.get("DriverName") or ""
        event["meaning"] = (
            f"Windows recognised {_article(label).lower()} {label}"
            + (f" — {name}" if name else "")
            + " and made it available for use"
            + (f", using the driver {driver}" if driver else "")
            + "."
        )
        event["action"] = (
            "Expected if you just plugged something in. If you connected "
            "nothing, check what this device is before trusting it."
        )


_REFINERS.extend([_refine_network, _refine_device])
