# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
Read-only Windows Event Log reader.

HOW THIS STAYS SAFE
-------------------
This module uses exactly five functions from the Windows Event Log API, and
every one of them is a *read* operation:

    EvtQuery                - open an existing log for reading
    EvtNext                 - read the next record from that query
    EvtSubscribe            - ask Windows to hand us new records as they occur
    EvtRender               - convert a record we were handed into XML text
    EvtFormatMessage        - convert a record into its human-readable string

The destructive parts of the same API - EvtClearLog, EvtExportLog,
EvtArchiveExportedLog, and every registry/service/policy call - are never
imported and never called. There is no code path in this program that can
write to, clear, truncate, re-configure, or take ownership of a log. Windows
also enforces this independently: the channel handles are opened with read
access only, so a clear attempt would be refused by the OS even if one
existed.

The program writes to exactly one place on disk: its own settings file under
%LOCALAPPDATA%\\SystemWatch\\. It never touches system files or settings.

HOW THIS STAYS CHEAP
--------------------
Nothing polls. EvtSubscribe registers a callback and Windows invokes it from
its own thread pool only when a matching event is actually written. While the
machine is quiet this process does no work at all - no timers firing against
the log, no file scanning, no re-reading.

The callback itself is deliberately tiny: it renders the record (which must
happen while Windows still owns the handle) and appends it to a bounded
deque. All parsing, translating and drawing happens later, in batches, on the
UI thread. Under a burst the callback skips the expensive message-formatting
step and the deque discards the oldest overflow, so a storm of events costs
bounded memory and bounded CPU instead of dragging the machine down.
"""

import ctypes
import threading
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime, timezone

import win32evtlog

from translations import CHANNELS, LEVEL_TO_SEVERITY, translate

NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"

# Bounded so a burst of events can never grow memory without limit.
QUEUE_MAX = 4000

# Above this backlog we stop asking Windows to format message strings, which
# is by far the most expensive part of handling an event.
BURST_THRESHOLD = 250


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _parse_time(value):
    """'2026-08-17T11:39:10.7059392Z' -> local datetime."""
    if not value:
        return datetime.now()
    try:
        txt = value.rstrip("Z")
        if "." in txt:
            head, frac = txt.split(".", 1)
            frac = (frac + "000000")[:6]
            txt = f"{head}.{frac}"
            fmt = "%Y-%m-%dT%H:%M:%S.%f"
        else:
            fmt = "%Y-%m-%dT%H:%M:%S"
        dt = datetime.strptime(txt, fmt).replace(tzinfo=timezone.utc)
        return dt.astimezone().replace(tzinfo=None)
    except Exception:
        return datetime.now()


def parse_event(xml_str, channel_hint=""):
    """Turn a rendered event XML string into a plain dict."""
    root = ET.fromstring(xml_str)
    sysel = root.find(NS + "System")

    def _txt(tag, default=""):
        el = sysel.find(NS + tag) if sysel is not None else None
        return el.text if el is not None and el.text else default

    provider_el = sysel.find(NS + "Provider") if sysel is not None else None
    provider = provider_el.get("Name", "") if provider_el is not None else ""

    time_el = sysel.find(NS + "TimeCreated") if sysel is not None else None
    when = _parse_time(time_el.get("SystemTime") if time_el is not None else "")

    try:
        event_id = int(_txt("EventID", "0"))
    except ValueError:
        event_id = 0
    try:
        level = int(_txt("Level", "4"))
    except ValueError:
        level = 4

    fields = {}
    positional = []
    for container in ("EventData", "UserData"):
        el = root.find(NS + container)
        if el is None:
            continue
        # UserData wraps its payload in one provider-specific element.
        nodes = list(el)
        if container == "UserData" and len(nodes) == 1:
            nodes = list(nodes[0])
        for node in nodes:
            value = (node.text or "").strip()
            name = node.get("Name")
            if not name:
                name = node.tag.split("}")[-1]
            if name:
                fields[name] = value
                # Spaced names like "Threat Name" cannot be used in a format
                # placeholder, so keep an underscore alias too.
                if " " in name:
                    fields[name.replace(" ", "_")] = value
            positional.append(value)
    for i, value in enumerate(positional):
        fields.setdefault(f"d{i}", value)

    return {
        "channel": _txt("Channel", channel_hint),
        "provider": provider,
        "event_id": event_id,
        "level": level,
        "record_id": _txt("EventRecordID", ""),
        "computer": _txt("Computer", ""),
        "time": when,
        "fields": fields,
        "raw_level_severity": LEVEL_TO_SEVERITY.get(level, "info"),
    }


def readable_channels():
    """Probe which channels this user can actually read. Read-only."""
    out = {}
    for name, meta in CHANNELS.items():
        try:
            handle = win32evtlog.EvtQuery(
                name, win32evtlog.EvtQueryReverseDirection
            )
            del handle
            out[name] = True
        except Exception:
            out[name] = False
    return out


class EventWatcher:
    """
    Subscribes to one or more event log channels and hands parsed, translated
    events to whoever calls drain(). Entirely read-only.
    """

    def __init__(self):
        self._queue = deque(maxlen=QUEUE_MAX)
        self._subs = {}          # channel -> handle, opened once, never closed
        self._active = set()     # channels we currently accept events from
        self._meta_cache = {}
        self._running = False
        self._paused = False
        self.dropped = 0
        self.total_seen = 0
        self.errors = []

    # -- subscription lifecycle ------------------------------------------
    #
    # WHY SUBSCRIPTIONS ARE NEVER CLOSED WHILE RUNNING
    #
    # Closing an event-log subscription blocks until any callbacks already
    # in flight have returned. Those callbacks are Python, so they need the
    # GIL - which the thread calling the close is still holding. If an event
    # happens to arrive at the moment we close, the two wait on each other
    # and the entire process freezes, watchdogs included. This was measured,
    # not assumed: closing a subscription mid-delivery hung a test process
    # hard enough that even a watchdog thread could not fire.
    #
    # So this class opens at most one subscription per channel, keeps it for
    # the life of the process, and switches delivery on and off with plain
    # flags that the callback checks. Pausing and changing channels then cost
    # one set lookup per event and cannot deadlock. The handles are released
    # by Windows when the process exits, which is the only moment at which no
    # callback can still be running. Only a handful of channels are ever
    # subscribed, so nothing accumulates.

    def set_channels(self, channels):
        """
        Make `channels` the live set. Subscribes to any channel not already
        subscribed; channels dropped from the set simply stop being accepted
        in the callback. Returns {channel: ok}.
        """
        wanted = set(channels)
        results = {}
        for channel in wanted:
            if channel in self._subs:
                results[channel] = True
                continue
            try:
                sub = win32evtlog.EvtSubscribe(
                    channel,
                    win32evtlog.EvtSubscribeToFutureEvents,
                    Callback=self._on_event,
                    Context=channel,
                )
                self._subs[channel] = sub
                results[channel] = True
            except Exception as exc:
                results[channel] = False
                self.errors.append(f"{channel}: {exc}")
        self._active = {c for c in wanted if c in self._subs}
        self._running = True
        return results

    def pause(self):
        """Stop accepting events. The callback returns immediately."""
        self._paused = True

    def resume(self):
        self._paused = False

    def shutdown(self):
        """
        Called on quit. Deliberately does not close the subscriptions - see
        the note above. Windows reclaims the handles as the process exits.
        """
        self._paused = True
        self._running = False
        self._active = set()
        self._queue.clear()

    @property
    def active(self):
        return self._running and not self._paused and bool(self._active)

    # -- the hot path ------------------------------------------------------
    def _on_event(self, action, context, event_handle):
        """
        Called by Windows on one of its own thread-pool threads.

        Must stay short: the handle is only valid for the duration of this
        call, so we render here and defer everything else.
        """
        if self._paused or not self._running or context not in self._active:
            return 0
        try:
            if action != win32evtlog.EvtSubscribeActionDeliver:
                return 0
            xml_str = win32evtlog.EvtRender(
                event_handle, win32evtlog.EvtRenderEventXml
            )
            message = None
            if len(self._queue) < BURST_THRESHOLD:
                message = self._format(event_handle, xml_str)
            if len(self._queue) == self._queue.maxlen:
                self.dropped += 1
            self._queue.append((context, xml_str, message, False))
            self.total_seen += 1
        except Exception:
            # Never let an exception escape into the OS callback.
            pass
        return 0

    def _format(self, event_handle, xml_str):
        """Ask Windows for the record's human-readable text."""
        try:
            start = xml_str.find("<Provider Name='")
            if start == -1:
                start = xml_str.find('<Provider Name="')
                if start == -1:
                    return None
                quote = '"'
            else:
                quote = "'"
            start += len("<Provider Name=") + 1
            end = xml_str.find(quote, start)
            provider = xml_str[start:end]

            if provider in self._meta_cache:
                meta = self._meta_cache[provider]
            else:
                try:
                    meta = win32evtlog.EvtOpenPublisherMetadata(provider)
                except Exception:
                    meta = None
                self._meta_cache[provider] = meta
            if meta is None:
                return None
            return win32evtlog.EvtFormatMessage(
                meta, event_handle, win32evtlog.EvtFormatMessageEvent
            )
        except Exception:
            return None

    # -- history ------------------------------------------------------------
    def backfill(self, channels, per_channel=25):
        """
        Read the most recent records already in the log so the window is not
        empty on launch. Read-only; runs off the UI thread.
        """
        for channel in channels:
            try:
                query = win32evtlog.EvtQuery(
                    channel, win32evtlog.EvtQueryReverseDirection
                )
            except Exception:
                continue
            fetched = 0
            while fetched < per_channel:
                try:
                    events = win32evtlog.EvtNext(
                        query, min(10, per_channel - fetched)
                    )
                except Exception:
                    break
                if not events:
                    break
                for handle in events:
                    try:
                        xml_str = win32evtlog.EvtRender(
                            handle, win32evtlog.EvtRenderEventXml
                        )
                        message = self._format(handle, xml_str)
                        self._queue.append((channel, xml_str, message, True))
                    except Exception:
                        pass
                    fetched += 1

    def backfill_async(self, channels, per_channel=25, done=None):
        def run():
            self.backfill(channels, per_channel)
            if done:
                done()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread

    # -- consumption --------------------------------------------------------
    def drain(self, limit=80):
        """
        Pop up to `limit` queued records, parse and translate them.

        Bounded on purpose: under a burst the UI thread does a fixed amount
        of work per tick and picks the rest up next tick, so the interface
        stays responsive and CPU stays flat.
        """
        out = []
        for _ in range(limit):
            try:
                channel, xml_str, message, historical = self._queue.popleft()
            except IndexError:
                break
            try:
                event = parse_event(xml_str, channel)
            except Exception:
                continue
            event["message"] = (message or "").strip()
            event["historical"] = historical
            out.append(translate(event))
        return out

    @property
    def backlog(self):
        return len(self._queue)
