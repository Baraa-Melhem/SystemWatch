# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
Current device and network state - "what is plugged in and what am I on".

The event log tells you what *happened*; this tells you what *is*. Both are
read-only: enumerating drives and reading IP configuration are queries, and
nothing here mounts, ejects, reconfigures or writes anything.

Everything is gathered on demand - when the panel is opened, or when Windows
tells us a device arrived - never on a timer. An idle SystemWatch does not run
any of this.
"""

import socket

import psutil
import win32api
import win32file

DRIVE_TYPES = {
    0: "Unknown",
    1: "Not mounted",
    2: "Removable",
    3: "Fixed",
    4: "Network",
    5: "CD / DVD",
    6: "RAM disk",
}

# Drive types a person physically plugs in and unplugs.
REMOVABLE_TYPES = {2, 5}


def human_bytes(count):
    if not count:
        return "—"
    size = float(count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def drives():
    """
    Every drive letter Windows currently has, with type and free space.

    A card reader with no card, or an empty optical drive, still has a letter
    but cannot be queried - those come back with ready=False rather than
    raising.
    """
    found = []
    try:
        roots = win32api.GetLogicalDriveStrings().split("\x00")
    except Exception:
        return found

    for root in roots:
        if not root:
            continue
        try:
            kind = win32file.GetDriveType(root)
        except Exception:
            kind = 0

        record = {
            "letter": root.rstrip("\\"),
            "root": root,
            "type": DRIVE_TYPES.get(kind, "Unknown"),
            "removable": kind in REMOVABLE_TYPES,
            "label": "",
            "fs": "",
            "free": 0,
            "total": 0,
            "ready": True,
        }

        try:
            info = win32api.GetVolumeInformation(root)
            record["label"] = info[0] or ""
            record["fs"] = info[4] or ""
        except Exception:
            # Empty reader / no disc inserted.
            record["ready"] = False

        try:
            free, total, _ = win32file.GetDiskFreeSpaceEx(root)
            record["free"], record["total"] = free, total
        except Exception:
            pass

        found.append(record)
    return found


def removable_drives():
    return [d for d in drives() if d["removable"] and d["ready"]]


# --- network -----------------------------------------------------------------
_wmi = None


def _wmi_connection():
    """Cached WMI handle. First call costs ~0.15 s, later ones are free."""
    global _wmi
    if _wmi is None:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        _wmi = win32com.client.GetObject("winmgmts:")
    return _wmi


def adapters():
    """
    Live IP configuration for every connected adapter: addresses, gateway,
    DNS servers and the DHCP server that handed out the lease.

    Uses a read-only WMI SELECT. If WMI is unavailable for any reason this
    falls back to psutil, which still gives addresses and MAC but cannot
    report gateway or DNS.
    """
    try:
        query = _wmi_connection().ExecQuery(
            "SELECT Description, IPAddress, DefaultIPGateway, "
            "DNSServerSearchOrder, DHCPServer, MACAddress, DHCPEnabled "
            "FROM Win32_NetworkAdapterConfiguration WHERE IPEnabled = True"
        )
        results = []
        for row in query:
            addresses = list(row.IPAddress or [])
            results.append({
                "name": row.Description or "",
                "ipv4": [a for a in addresses if ":" not in a],
                "ipv6": [a for a in addresses if ":" in a],
                "gateway": list(row.DefaultIPGateway or []),
                "dns": list(row.DNSServerSearchOrder or []),
                "dhcp": row.DHCPServer or "",
                "mac": row.MACAddress or "",
                "source": "wmi",
            })
        if results:
            return results
    except Exception:
        pass
    return _adapters_via_psutil()


def _adapters_via_psutil():
    results = []
    try:
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
    except Exception:
        return results

    for name, stat in stats.items():
        if not stat.isup or name.lower().startswith("loopback"):
            continue
        ipv4, ipv6, mac = [], [], ""
        for addr in addrs.get(name, []):
            if addr.family == socket.AF_INET:
                ipv4.append(addr.address)
            elif addr.family == socket.AF_INET6:
                ipv6.append(addr.address.split("%")[0])
            elif addr.family == psutil.AF_LINK:
                mac = addr.address
        if ipv4 or ipv6:
            results.append({
                "name": name, "ipv4": ipv4, "ipv6": ipv6,
                "gateway": [], "dns": [], "dhcp": "", "mac": mac,
                "source": "psutil",
            })
    return results


def traffic():
    """Bytes sent/received since Windows started. Cheap counter read."""
    try:
        counters = psutil.net_io_counters()
        return counters.bytes_sent, counters.bytes_recv
    except Exception:
        return 0, 0


def current_network(events):
    """
    Work out which network we are on from the events already in memory.

    Windows records the name on connect (NetworkProfile 10000) and the SSID
    plus security on Wi-Fi association (WLAN-AutoConfig 8001). Reading them
    back from the event list costs nothing and needs no extra API.
    """
    state = {"name": "", "ssid": "", "security": "", "adapter": "", "when": None}
    for event in events:                     # newest first
        eid, provider = event["event_id"], event["provider"]

        if provider == "Microsoft-Windows-NetworkProfile" and not state["name"]:
            if eid == 10000:
                state["name"] = event["fields"].get("Name", "")
                state["when"] = event["time"]
            elif eid == 10001:
                # Most recent profile event is a disconnect: we are off it.
                state["name"] = ""
                state["when"] = event["time"]
                break

        if provider == "Microsoft-Windows-WLAN-AutoConfig" and not state["ssid"]:
            if eid == 8001:
                fields = event["fields"]
                state["ssid"] = fields.get("SSID", "")
                state["security"] = fields.get("AuthenticationAlgorithm", "")
                state["adapter"] = fields.get("InterfaceDescription", "")
            elif eid == 8003:
                state["ssid"] = ""

        if state["name"] and state["ssid"]:
            break
    return state


def recent_devices(events, limit=12):
    """Devices from the event stream that a person actually plugged in."""
    seen, out = set(), []
    for event in events:                     # newest first
        if event.get("kind") != "device" or event.get("noisy"):
            continue
        name = (
            event.get("device_name")
            or event.get("device_label")
            or event.get("device_kind")
            or ""
        )
        key = (name, event.get("device_volume", ""))
        if not name or key in seen:
            continue
        seen.add(key)
        out.append({
            "name": name,
            "kind": event.get("device_kind", ""),
            "volume": event.get("device_volume", ""),
            "time": event["time"],
            "title": event["title"],
        })
        if len(out) >= limit:
            break
    return out


def device_history(limit=15):
    """
    Look back through the log specifically for things that were plugged in.

    The live event stream only holds what has happened since launch, so a USB
    stick connected yesterday would not appear. This asks Windows for exactly
    the relevant records using a server-side XPath filter, so it reads a
    handful of events rather than scanning the whole log.

    Read-only, and run only when the panel is refreshed.
    """
    import win32evtlog

    from translations import translate
    from watcher import parse_event

    queries = [
        ("Microsoft-Windows-Ntfs/Operational",
         "*[System[(EventID=4 or EventID=303)]]"),
        ("Microsoft-Windows-Kernel-PnP/Configuration",
         "*[System[(EventID=410)]]"),
    ]

    collected = []
    for channel, xpath in queries:
        try:
            query = win32evtlog.EvtQuery(
                channel, win32evtlog.EvtQueryReverseDirection, xpath
            )
        except Exception:
            continue

        scanned = 0
        while scanned < limit * 6:
            try:
                handles = win32evtlog.EvtNext(query, 20)
            except Exception:
                break
            if not handles:
                break
            for handle in handles:
                scanned += 1
                try:
                    event = parse_event(
                        win32evtlog.EvtRender(
                            handle, win32evtlog.EvtRenderEventXml
                        ),
                        channel,
                    )
                    event["message"] = ""
                    translate(event)
                except Exception:
                    continue
                if event.get("noisy"):
                    continue
                collected.append({
                    "name": (event.get("device_name")
                             or event.get("device_label")
                             or event.get("device_kind") or ""),
                    "kind": event.get("device_kind", ""),
                    "volume": event.get("device_volume", ""),
                    "time": event["time"],
                    "title": event["title"],
                })

    collected.sort(key=lambda item: item["time"], reverse=True)

    seen, out = set(), []
    for item in collected:
        key = (item["title"], item["time"].replace(second=0, microsecond=0))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def active_adapter(adapters):
    """The adapter actually carrying traffic - the one with a gateway."""
    for adapter in adapters:
        if adapter.get("gateway") and adapter.get("ipv4"):
            return adapter
    for adapter in adapters:
        if adapter.get("ipv4"):
            return adapter
    return None


def attached_devices():
    """
    USB, Bluetooth and portable devices attached right now.

    A phone connected over MTP never receives a drive letter, so enumerating
    drives cannot answer "is my phone plugged in". This asks Windows for the
    live device list instead.

    Hubs, controllers and composite parents are filtered out, and the
    remaining interfaces are grouped by vendor/product so one physical device
    is one row rather than five.

    Read-only WMI SELECT, run only when the panel refreshes.
    """
    from devicewatch import group_key, score_name

    try:
        rows = _wmi_connection().ExecQuery(
            "SELECT Name, PNPDeviceID, Service, Status FROM Win32_PnPEntity "
            "WHERE PNPDeviceID LIKE 'USB%' OR PNPDeviceID LIKE 'WPD%' "
            "OR PNPDeviceID LIKE 'BTHENUM%'"
        )
    except Exception:
        return []

    groups = {}
    for row in rows:
        pnp = (row.PNPDeviceID or "")
        name = (row.Name or "").strip()
        if not pnp or not name:
            continue
        service = row.Service or ""
        score = score_name(name, service, pnp)
        if score is None:
            continue                      # hub / controller plumbing
        key = group_key(pnp)
        current = groups.get(key)
        if current is None or score > current["score"]:
            groups[key] = {
                "name": name,
                "id": pnp,
                "service": service,
                "score": score,
                "status": row.Status or "",
            }

    devices = list(groups.values())
    devices.sort(key=lambda d: d["name"].lower())
    return devices
