# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
The "Devices & Network" tab: what is plugged in and what we are connected to,
right now.

Refresh policy matters here. There is no timer. The panel rebuilds itself
only when:

  * the tab is opened, or
  * a device or network event arrives through the existing subscription.

USB sticks already announce themselves through the NTFS channel (volume
mounted / dismounted) and other hardware through Kernel-PnP, both of which
SystemWatch is already subscribed to. So live device detection costs nothing
extra - no polling, and no per-message hook on the GUI thread.
"""

import html
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout,
    QWidget,
)

import history
import livestate
import recorder
import theme

# Every colour comes from theme.py. These names are kept as local aliases
# so the rendering code below stays readable, but nothing is defined here.
BG = theme.INK_0
PANEL = theme.INK_1
BORDER = theme.LINE
TEXT = theme.TEXT_HI
MUTED = theme.TEXT_MED
GREEN = theme.OK
YELLOW = theme.CAUTION
BLUE = theme.ACCENT

# Rebuilding this panel costs two WMI queries and a log query. Chatty
# networks emit status events every few seconds, so an unthrottled
# refresh-on-every-event would burn far more CPU than the whole app
# otherwise uses. Coalesce instead: refresh at most this often, and let
# one deferred pass pick up everything that arrived in between.
MIN_REFRESH_SECONDS = 3.0

DASH = "\u2014"   # shown for a drive with no label


def _esc(value):
    return html.escape(str(value if value is not None else ""))


def _row(label, value, colour=None):
    if not value:
        return ""
    shade = colour or TEXT
    return (
        f'<tr><td width="132" valign="top" '
        f'style="color:{theme.TEXT_LOW}; font-size:11px;">{label}</td>'
        f'<td style="color:{shade}; font-size:12px;">{_esc(value)}</td></tr>'
    )


class DevicePanel(QWidget):
    """Live view of attached drives and network connections."""

    def __init__(self, get_events, parent=None):
        super().__init__(parent)
        self._get_events = get_events
        self._dirty = True
        self._last_refresh = 0.0
        self._refresh_queued = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bar = QFrame()
        bar.setObjectName("filterbar")
        bar.setFixedHeight(50)
        row = QHBoxLayout(bar)
        row.setContentsMargins(18, 0, 16, 0)

        self.headline = QLabel("Checking…")
        self.headline.setObjectName("panelheadline")
        row.addWidget(self.headline)
        row.addStretch(1)

        refresh = QPushButton("Refresh")
        refresh.setProperty("kind", "quiet")
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.setToolTip(
            "Re-read the current state. Refreshes on its own whenever a "
            "device or network event arrives."
        )
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        layout.addWidget(bar)

        self.view = QTextBrowser()
        self.view.setObjectName("panelview")
        self.view.setOpenExternalLinks(False)
        # Nothing here is a link. Turning navigation off means even text that
        # slipped through as markup could never load another document.
        self.view.setOpenLinks(False)
        layout.addWidget(self.view, 1)

    # -- refresh control -------------------------------------------------
    def mark_dirty(self):
        """A device/network event arrived; rebuild next time we're visible."""
        self._dirty = True
        if not self.isVisible():
            return                      # showEvent will catch up

        waited = time.monotonic() - self._last_refresh
        if waited >= MIN_REFRESH_SECONDS:
            self.refresh()
        elif not self._refresh_queued:
            self._refresh_queued = True
            QTimer.singleShot(
                max(200, int((MIN_REFRESH_SECONDS - waited) * 1000)),
                self._deferred_refresh,
            )

    def _deferred_refresh(self):
        self._refresh_queued = False
        if self._dirty and self.isVisible():
            self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        if self._dirty:
            self.refresh()

    def refresh(self):
        self._dirty = False
        self._last_refresh = time.monotonic()
        try:
            drives = livestate.drives()
            adapters = livestate.adapters()
        except Exception as exc:
            self.view.setHtml(theme.page(theme.status_card(
                "Could not read the current state of this PC.",
                _esc(exc),
                tone="alert",
            )))
            self.headline.setText("Unavailable")
            return

        try:
            attached = livestate.attached_devices()
        except Exception:
            attached = []
        events = self._get_events()
        network = livestate.current_network(events)
        active = livestate.active_adapter(adapters)
        # The permanent record first; fall back to reading the event log
        # for machines where the recorder has only just been switched on.
        try:
            recorded, record_status = history.load()
        except Exception as exc:
            recorded, record_status = [], f"tampered: {exc}"
        try:
            recent = livestate.device_history()
        except Exception:
            recent = livestate.recent_devices(events)
        removable = [d for d in drives if d["removable"] and d["ready"]]

        self.headline.setText(
            self._headline(removable, network, active, attached)
        )
        self.view.setHtml(
            self._render(drives, adapters, network, recent, removable, active,
                         attached, recorded, record_status)
        )

    def _headline(self, removable, network, active, attached=()):
        if removable:
            names = ", ".join(
                f"{d['label'] or 'Untitled'} ({d['letter']})"
                for d in removable
            )
            count = len(removable)
            noun = "drive" if count == 1 else "drives"
            device_part = f"{count} removable {noun} connected: {names}"
        elif attached:
            # A phone on MTP never gets a drive letter, so "no removable
            # drives" would be a misleading thing to lead with.
            shown = ", ".join(d["name"] for d in attached[:2])
            more = f" +{len(attached) - 2} more" if len(attached) > 2 else ""
            count = len(attached)
            noun = "device" if count == 1 else "devices"
            device_part = f"{count} {noun} attached: {shown}{more}"
        else:
            device_part = "Nothing plugged in"

        where = network.get("ssid") or network.get("name")
        if where:
            net_part = f"On “{where}”"
        elif active:
            # Windows only names a network when it joins one. A machine that
            # was already plugged in at boot still has a live adapter.
            net_part = f"Connected via {active['name']}"
        else:
            net_part = "No network connection"
        return f"{device_part}   ·   {net_part}"

    # -- rendering -------------------------------------------------------
    def _render(self, drives, adapters, network, recent, removable,
                active=None, attached=(), recorded=(), record_status="ok"):
        parts = [self._summary(removable, attached, drives, recorded)]

        parts.append(self._removable_card(removable))
        parts.append(self._network_section(network, adapters, active))
        parts.append(self._attached_section(attached))
        parts.append(self._drives_section(drives))
        parts.append(self._record_section(recorded, record_status))
        parts.append(self._earlier_section(recent))

        return theme.page("".join(parts))

    def _summary(self, removable, attached, drives, recorded):
        """The figures worth knowing before reading any of the detail."""
        return theme.metrics([
            theme.metric(
                len(removable), "REMOVABLE",
                theme.CAUTION if removable else theme.TEXT_HI,
            ),
            theme.metric(len(attached), "ATTACHED"),
            theme.metric(len(drives), "DRIVES"),
            theme.metric(len(recorded), "RECORDED"),
        ]) + theme.gap(14)

    def _removable_card(self, removable):
        """Leads the page: anything here can carry data off this PC."""
        if removable:
            items = "".join(
                f'<div style="font-size:13px; margin-top:6px; '
                f'color:{theme.TEXT_HI};">'
                f'<b>{_esc(d["label"] or "Untitled volume")}</b>'
                f'<span style="color:{theme.TEXT_LOW};">'
                f'&#8202;&#8202;on {_esc(d["letter"])} \u00b7 {_esc(d["fs"])} '
                f'\u00b7 {livestate.human_bytes(d["free"])} free of '
                f'{livestate.human_bytes(d["total"])}</span></div>'
                for d in removable
            )
            return theme.card(
                f'<div style="color:{theme.CAUTION}; font-size:10px;">'
                f"<b>REMOVABLE MEDIA CONNECTED</b></div>{items}",
                background=theme.WASH["warn"],
                rail=theme.CAUTION,
            )
        return theme.card(
            f'<div style="color:{theme.OK}; font-size:10px;">'
            f"<b>NO REMOVABLE MEDIA</b></div>"
            f'<div style="font-size:13px; margin-top:6px; '
            f'color:{theme.TEXT_HI};">Nothing is plugged in that can carry '
            f"data off this PC.</div>",
            background=theme.WASH["info"],
            rail=theme.OK,
        )

    def _network_section(self, network, adapters, active):
        parts = [theme.section("NETWORK")]
        where = network.get("ssid") or network.get("name")

        if where:
            security = network.get("security") or ""
            open_wifi = security.lower() in ("open", "none", "")
            inner = (
                f'<div style="font-family:{theme.FONT_DISPLAY}; '
                f'font-size:18px; color:{theme.TEXT_HI};">'
                f"<b>{_esc(where)}</b></div>"
            )
            if network.get("ssid") and security:
                colour = theme.CAUTION if open_wifi else theme.OK
                note = (
                    "UNENCRYPTED \u2014 treat as public" if open_wifi
                    else "encrypted"
                )
                inner += (
                    f'<div style="font-size:12px; color:{colour}; '
                    f'margin-top:5px;">Wi\u2011Fi security: {_esc(security)} '
                    f"({note})</div>"
                )
            if network.get("adapter"):
                inner += (
                    f'<div style="color:{theme.TEXT_LOW}; font-size:11px; '
                    f'margin-top:5px;">Wi\u2011Fi adapter: '
                    f'{_esc(network["adapter"])}</div>'
                )
            parts.append(theme.card(inner, rail=theme.ACCENT))
        elif active:
            parts.append(theme.card(
                f'<div style="font-family:{theme.FONT_DISPLAY}; '
                f'font-size:18px; color:{theme.TEXT_HI};">'
                f'<b>{_esc(active["name"])}</b></div>'
                f'<div style="color:{theme.TEXT_LOW}; font-size:11px; '
                f'margin-top:5px;">Wired or already-joined connection \u2014 '
                f"Windows only records a network name at the moment it joins "
                f"one.</div>",
                rail=theme.ACCENT,
            ))
        else:
            parts.append(theme.empty(
                "No active network connection.",
                "Nothing is reaching the internet from this PC right now.",
            ))

        for adapter in adapters:
            rows = "".join([
                _row("IPv4 address", ", ".join(adapter["ipv4"])),
                _row("Gateway (router)", ", ".join(adapter["gateway"]), BLUE),
                _row("DNS servers", ", ".join(adapter["dns"]), BLUE),
                _row("DHCP server", adapter["dhcp"], BLUE),
                _row("MAC address", adapter["mac"]),
                _row("IPv6", ", ".join(adapter["ipv6"][:2])),
            ])
            parts.append(theme.gap(8) + theme.card(
                f'<div style="font-size:13px; color:{theme.TEXT_HI};">'
                f'<b>{_esc(adapter["name"])}</b></div>'
                f'<table width="100%" cellpadding="3" cellspacing="0" '
                f'style="margin-top:6px;">{rows}</table>'
            ))

        if adapters and adapters[0].get("source") == "psutil":
            parts.append(
                f'<p style="color:{theme.TEXT_LOW}; font-size:11px;">'
                f"<i>Gateway and DNS are unavailable \u2014 the system query "
                f"service did not respond.</i></p>"
            )

        sent, received = livestate.traffic()
        parts.append(
            f'<p style="color:{theme.TEXT_LOW}; font-size:11px; '
            f'margin-top:8px;">Since this PC started: sent '
            f"{livestate.human_bytes(sent)}, received "
            f"{livestate.human_bytes(received)} across all adapters.</p>"
        )
        return "".join(parts)

    def _attached_section(self, attached):
        if not attached:
            return ""
        rows = "".join(
            f'<tr><td style="font-size:12.5px; color:{theme.TEXT_HI};">'
            f'{_esc(d["name"])}</td>'
            f'<td width="230" style="color:{theme.TEXT_LOW}; '
            f'font-size:11px;">{_esc(d["id"][:44])}</td></tr>'
            for d in attached
        )
        return (
            theme.section("ATTACHED RIGHT NOW", len(attached))
            + theme.rows(rows)
        )

    def _drives_section(self, drives):
        rows = []
        for drive in drives:
            if not drive["ready"]:
                detail = (
                    f'<span style="color:{theme.TEXT_LOW};">'
                    f"empty / not ready</span>"
                )
            else:
                detail = (
                    f'{_esc(drive["fs"])} \u00b7 '
                    f'{livestate.human_bytes(drive["free"])} free of '
                    f'{livestate.human_bytes(drive["total"])}'
                )
            colour = theme.CAUTION if drive["removable"] else theme.TEXT_HI
            rows.append(
                f'<tr><td width="46" style="color:{colour}; font-size:13px;">'
                f'<b>{_esc(drive["letter"])}</b></td>'
                f'<td width="150" style="font-size:12px; '
                f'color:{theme.TEXT_HI};">{_esc(drive["label"] or DASH)}</td>'
                f'<td width="94" style="color:{colour}; font-size:11px;">'
                f'{_esc(drive["type"])}</td>'
                f'<td style="color:{theme.TEXT_LOW}; font-size:11px;">'
                f"{detail}</td></tr>"
            )
        if not rows:
            return theme.section("DRIVES") + theme.empty("No drives found.")
        return (
            theme.section("DRIVES", len(drives))
            + theme.rows("".join(rows))
        )

    def _record_section(self, recorded, record_status):
        parts = [theme.section(
            f"RECORDED CONNECTIONS  (newest {history.MAX_ENTRIES} kept)"
        )]
        tampered = record_status.startswith("tampered")
        try:
            running = recorder.is_running()
        except Exception:
            running = False

        parts.append(theme.status_card(
            _esc(history.status_text(record_status, len(recorded))),
            (
                "Background recorder: running \u2014 detecting even with this "
                "window closed"
                if running else
                "Background recorder: NOT running \u2014 nothing is being "
                "detected right now"
            ),
            tone="caution" if (tampered or not running) else "ok",
        ))

        if recorded:
            rows = "".join(
                f'<tr><td width="46" style="color:{theme.TEXT_LOW}; '
                f'font-size:11px;">#{e.get("seq", "")}</td>'
                f'<td width="140" style="color:{theme.TEXT_LOW}; '
                f'font-size:11px;">{_esc(e.get("time", ""))}</td>'
                f'<td style="font-size:12px; color:{theme.TEXT_HI};">'
                f"{_esc(history.describe(e))}</td></tr>"
                for e in reversed(recorded)
            )
            parts.append(theme.gap(8) + theme.rows(rows))
        return "".join(parts)

    def _earlier_section(self, recent):
        if not recent:
            return theme.section("EARLIER, FROM THE EVENT LOG") + theme.empty(
                "No device connections recorded yet in this session.",
                "The permanent record above is the one that survives a "
                "restart.",
            )
        items = "".join(
            f'<tr><td width="150" style="color:{theme.TEXT_LOW}; '
            f'font-size:11px;">{item["time"].strftime("%d %b  %H:%M")}</td>'
            f'<td style="font-size:12px; color:{theme.TEXT_HI};">'
            f'{_esc(item["title"])}</td></tr>'
            for item in recent
        )
        return (
            theme.section("EARLIER, FROM THE EVENT LOG", len(recent))
            + theme.rows(items)
        )

    def _section(self, title):
        """Kept as a thin alias; theme.section() is the real implementation."""
        return theme.section(title)
