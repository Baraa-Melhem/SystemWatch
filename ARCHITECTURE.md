# SystemWatch — Technical Reference

This is the document to read before changing anything. `README.md` explains
what the app does for the person using it; this one explains how it is put
together, where each decision lives, and which parts are load-bearing.

Python 3.11 · PyQt5 · pywin32 · psutil · ~6,300 lines across 13 modules.

---

## 1. Shape of the system

There are **two independent processes**. This matters more than any other
structural fact, because it decides where a change belongs.

```
┌─────────────────────────────┐        ┌──────────────────────────────┐
│  recorder.py   (headless)   │        │  main.py -> ui.py  (window)  │
│                             │        │                              │
│  DeviceWatcher              │        │  EventWatcher (event log)    │
│  ActivityWatcher            │        │  DevicePanel / ActivityPanel │
│         │                   │        │            ▲                 │
│         ▼ append            │        │            │ poll (stat)     │
│   history.RollingRecord ────┼────────┼────────────┘                 │
│   (two JSONL files on disk) │        │                              │
└─────────────────────────────┘        └──────────────────────────────┘
        always running                     runs only when open
```

- **The recorder** is the always-on half. It owns device plug/unplug
  detection and program/file detection, and writes them to disk. It has no
  UI, no Qt, and no event-log subscriptions. ~16 MB, 0 % CPU.
- **The window** is the disposable half. It owns the event-log subscriptions
  and all drawing. It *reads* the recorder's files; it never writes them.

They share nothing but those two files and four named kernel objects. The
window can be closed, killed, or crash without losing a single detection.

**Consequence for you:** if you are adding something that must be captured
whether or not the window is open, it belongs in the recorder and must go
through `history`. If it is only meaningful while someone is looking, it
belongs in `ui.py`.

### Named kernel objects

| Name | Type | Created in | Purpose |
|---|---|---|---|
| `SystemWatchWindowInstance` | Mutex | `main.py:25` | Only one window may exist |
| `SystemWatchWindowShow` | Event | `main.py:26` | A 2nd launch signals the 1st to surface |
| `SystemWatchDeviceRecorder` | Mutex | `recorder.py:38` | Only one recorder may exist |
| `SystemWatchDeviceRecorderStop` | Event | `recorder.py:39` | `--stop` signals a clean shutdown |

Both single-instance checks use `CreateMutex` + `ERROR_ALREADY_EXISTS`. The
window's second launch calls `_wake_existing_window()` and exits with 0 — it
does not error, so double-clicking the icon behaves the way a user expects.

---

## 2. Module map

Arrows point at what a module depends on. Nothing above depends on anything
below it, with one deliberate exception marked `*`.

```
main.py ──────────► ui.py ──┬─► watcher.py ──► translations.py ─*─► devices.py
                            ├─► devicepanel.py ──► livestate.py
                            ├─► activitypanel.py
                            ├─► theme.py ──────► translations.py
                            ├─► history.py
                            ├─► startup.py
                            └─► recorder.py (only to launch/query it)

recorder.py ────────────────┬─► devicewatch.py
                            ├─► activitywatch.py
                            └─► history.py
```

| Module | Lines | Responsibility |
|---|---|---|
| `main.py` | 106 | Entry point, single-instance claim, Qt bootstrap |
| `ui.py` | 1635 | Window, table model, filters, tray, settings, detail pane |
| `theme.py` | 610 | Design system: tokens, the QSS, rich-text card helpers |
| `watcher.py` | 379 | Read-only Windows Event Log subscriptions |
| `translations.py` | 820 | Event ID → plain English (109 provider rules, 25 providers) |
| `devices.py` | 347 | Device/network rules + refiners; extends `translations` tables |
| `devicewatch.py` | 500 | Real-time `WM_DEVICECHANGE` plug/unplug detection |
| `activitywatch.py` | 429 | Program launches + files opened |
| `history.py` | 478 | `RollingRecord`: the tamper-evident 50-entry store |
| `livestate.py` | 390 | Point-in-time snapshot: drives, adapters, traffic |
| `devicepanel.py` | 445 | "Devices & Network" tab rendering |
| `activitypanel.py` | 222 | "Programs & Files" tab rendering |
| `recorder.py` | 204 | Headless process: run / `--status` / `--stop` |
| `startup.py` | 160 | Startup-folder `.lnk` creation; `command_for()` source vs packaged |
| `config.py` | 150 | Settings file: type-checked load, atomic save. No Qt, so the recorder can read it |
| `version.py` | 3 | `__version__` — the only place it is written; `build.py` reads it |
| `packaging/` | — | `launcher.py` (packaged entry point), `build.py`, `installer.iss` |

`assets/` holds the two checkbox tick PNGs the stylesheet references;
`theme.asset()` resolves them from source or from the packaged bundle.

### The one circular dependency

`translations.py` ends with a bare `import devices`, and `devices.py` starts
with `from translations import ...`. This is intentional and the comment at
`translations.py:809` explains it: device knowledge wants to live next to the
device code, but it extends tables defined in `translations`.

It must stay a **plain `import`**, not `from devices import X`. A from-import
requires the other module to be *finished*, which it is not when `devices` is
the module imported first. A plain import only needs the module object to
exist, so both import orders work. Changing this line back to a from-import
reintroduces a crash that only appears on some entry points.

---

## 3. Threads

Nothing here uses `asyncio`. Every thread is a daemon, and every one of them
is normally **blocked**, not looping — that is the whole performance story.

**Window process**

| Thread | Blocks on | Stopped by |
|---|---|---|
| Qt main | Event loop | `quit_app()` |
| Windows thread pool (N) | Delivers `EvtSubscribe` callbacks | never — see §9 |
| `backfill_async` (transient) | `EvtQuery`/`EvtNext` | finishes on its own |

**Recorder process**

| Thread | Blocks on | Stopped by |
|---|---|---|
| Main | `WaitForSingleObject(stop_event, INFINITE)` | the named stop event |
| `SystemWatch-devices` | `GetMessage` on a hidden window | `PostMessage(WM_CLOSE)` |
| `activity-programs` | `sleep(1.5)` between PID diffs | `threading.Event` |
| `activity-files` | `WaitForMultipleObjects` | a Win32 event, **not** a handle close |

All cross-thread handoff is a bounded `collections.deque` plus an optional
callback. Deques are used without a lock because `append`/`popleft` are
atomic under the GIL; anything more complex would need one.

---

## 4. The three data sources

Each tab is fed by a different mechanism with a different cost profile.

### a) Windows Event Log — `watcher.py`

Push-based. `EvtSubscribe` registers `_on_event` and Windows calls it from
its own thread pool only when a matching record is written. Idle cost is
zero.

The callback is deliberately tiny: it renders the record to XML (which
*must* happen while Windows still owns the handle) and appends to a deque.
Parsing, translating and drawing all happen later on the UI thread in
batches of `DRAIN_LIMIT` every `DRAIN_MS`.

Under a burst (`backlog > BURST_THRESHOLD`) it skips `EvtFormatMessage`,
which is by far the most expensive call. Overflow is dropped by the deque's
`maxlen` and counted in `self.dropped`, so a storm costs bounded memory.

### b) Devices — `devicewatch.py`

Push-based. A hidden top-level window created on its own thread receives
`WM_DEVICECHANGE`, registered with `DEVICE_NOTIFY_ALL_INTERFACE_CLASSES` so
it sees *every* device class, not just storage volumes.

One physical plug generates a burst of messages (interface arrival, volume
arrival, several child devices). `DEBOUNCE_MS = 800` collects them into one
report via a `SetTimer` on the hidden window. Friendly names come from a WMI
`SELECT` cached for `NAME_CACHE_TTL = 3.0` seconds, so a burst costs one
lookup. `score_name()` picks the most human of the competing names for the
same physical device.

> `win32gui.SetTimer` is missing from this pywin32 build. The module calls
> `SetTimer`/`KillTimer` through `ctypes` (`_set_timer`, `devicewatch.py:68`).
> Do not "simplify" these back to `win32gui`.

### c) Programs and files — `activitywatch.py`

Two different mechanisms, because Windows offers no single one.

**Programs are polled** — and that was forced, not chosen.
`Win32_ProcessStartTrace` returns access-denied, event 4688 needs admin
*plus* an audit-policy change (which this app refuses to make), and ETW's
kernel provider needs admin. So `_watch_programs` diffs `psutil.pids()`
every `POLL_SECONDS`. This is affordable only because of the specific call
used: `psutil.pids()` costs **0.05 ms**, while `process_iter` with
attributes costs **540 ms**. Only genuinely new PIDs get resolved.

A process is recorded once it owns a **visible window** (`EnumWindows`),
checked for up to `WINDOW_GRACE_POLLS` polls. That heuristic is what
separates "a program the user started" from the ~322 background processes
Windows runs. `SKIP_PROGRAMS` filters known shell infrastructure.

**Files are event-driven and free.** `_watch_files` runs
`ReadDirectoryChangesW` over the shell's Recent Items folder — Windows
writes a shortcut there whenever a document is opened through Explorer or a
File-Open dialog. Each new `.lnk` is resolved to its real target with a
4-attempt retry (Windows creates the file before writing the target).
`is_protocol_entry()` drops `ms-*---` shell activations, which are not files.

---

## 5. Data shapes

### The event dict

One dict flows through the entire window. `parse_event()` builds it,
`translate()` decorates it, `EventModel` displays it. Everything that wants
to appear in the Live list — including record entries replayed from disk —
must produce this shape.

```python
{
  "channel": "System",              # from parse_event()
  "provider": "Microsoft-Windows-Kernel-Power",
  "event_id": 42,
  "level": 4,                       # Windows level, 1=critical .. 4=info
  "record_id": "184023",
  "computer": "DESKTOP-X",
  "time": datetime,
  "fields": {...},                  # EventData/UserData, plus dN aliases
  "message": "...",                 # Windows' own rendered text
  "raw_level_severity": "info",

  "title":    "...",                # added by translate()
  "meaning":  "...",
  "action":   "...",
  "severity": "info" | "warn" | "error",
  "noisy":    False,                # hidden by "Hide routine chatter"
  "known":    True,                 # False = no hand-written rule
  "kind":     "" | "device" | "network",
  "verbatim": True,                 # only when falling back to Windows' text
}
```

`fields` gets two conveniences: names containing spaces are duplicated with
underscores (`"Threat Name"` → `Threat_Name`) so they work as format
placeholders, and every value is also aliased positionally as `d0`, `d1`, …

### A record entry

```python
{"seq": 7, "time": "2026-08-23 14:02:11",
 "action": "connected", "name": "Kingston DataTraveler 3.0",
 "kind": "USB storage", "device_id": "USBSTOR\\...", "drives": ["E:"],
 "prev": "<hash of entry 6>", "hash": "<sha256 of this entry>"}
```

`seq` never resets, even as entries roll off — so entry #61 in a 50-entry
file is visible proof that eleven older ones aged out normally.

---

## 6. On-disk state

The app writes to exactly these files plus two optional shortcuts. It never
writes anywhere else, and never to a system location.

| Path | Written by | Contents |
|---|---|---|
| `%LOCALAPPDATA%\SystemWatch\config.json` | window | Settings (read by the recorder too) |
| `%LOCALAPPDATA%\SystemWatch\error.log` | window | Tracebacks of bugs it survived; capped at 256 KB, only exists after one |
| `%LOCALAPPDATA%\SystemWatch\device-history.jsonl` | recorder | Device record |
| `%APPDATA%\SystemWatch\device-history.jsonl` | recorder | Its mirror |
| `%LOCALAPPDATA%\SystemWatch\activity-history.jsonl` | recorder | Programs/files |
| `%APPDATA%\SystemWatch\activity-history.jsonl` | recorder | Its mirror |
| `shell:startup\SystemWatch.lnk` | `startup.py` | Optional autostart |
| `shell:startup\SystemWatch Recorder.lnk` | `startup.py` | Optional autostart |

### How `RollingRecord` protects a file

`history.py` is one generic class with two instances. It gives you four
things, and it is worth knowing which is which:

1. **A rolling window.** `MAX_ENTRIES = 50`, oldest rolled off on append.
2. **Tamper *evidence*, not tamper *prevention*.** Each entry's `hash` is a
   SHA-256 over `signed_fields` in fixed order, and includes `prev` — the
   previous entry's hash. Editing any entry breaks every hash after it. A
   file can still be deleted; you just cannot alter it *unnoticed*.
3. **Two copies in separate folders.** `load()` prefers whichever verifies,
   and silently heals the other. Deleting one loses nothing.
4. **Evidence preservation.** If a chain fails verification, `append()` does
   not build on it — it renames the damaged file with a timestamp and starts
   a fresh chain, so the broken file survives as proof.

Writes are atomic (`tempfile` + `os.replace`), so a power cut cannot leave a
half-written record.

`signature()` returns `(mtime_ns, size)`. The window polls that — one
`stat()` per tick — and only re-parses when it actually changes.

---

## 7. Tuning constants

Everything tunable is a module-level constant. There is no config file for
these; they are deliberately in code, next to the reasoning.

| Constant | File | Value | Raise it to… |
|---|---|---|---|
| `MAX_ENTRIES` | `history.py:39` | 50 | keep more history (files grow linearly) |
| `QUEUE_MAX` | `watcher.py:54` | 4000 | drop fewer events in a storm |
| `BURST_THRESHOLD` | `watcher.py:58` | 250 | keep full text later into a burst |
| `MAX_RECORDS` | `ui.py:48` | 1500 | hold more rows in memory |
| `DRAIN_MS` | `ui.py:49` | 500 | update the list less often |
| `DRAIN_LIMIT` | `ui.py:50` | 80 | parse more per tick (less smooth) |
| `COALESCE_WINDOW` | `ui.py:51` | 120 s | fold repeats over a longer span |
| `POLL_SECONDS` | `activitywatch.py:46` | 1.5 | notice programs later, cost less |
| `WINDOW_GRACE_POLLS` | `activitywatch.py:52` | 6 | wait longer for a window to appear |
| `FILE_DEDUPE_SECONDS` | `activitywatch.py:56` | 5.0 | suppress repeat file hits longer |
| `DEBOUNCE_MS` | `devicewatch.py:82` | 800 | group a slower device's burst |
| `NAME_CACHE_TTL` | `devicewatch.py:83` | 3.0 | fewer WMI lookups |
| `MIN_REFRESH_SECONDS` | `devicepanel.py:44` | 3.0 | rebuild the panel less often |

---

## 8. Making common changes

### Add or fix a plain-English translation

`translations.py`, in `BY_PROVIDER`, keyed by `(provider, event_id)`:

```python
("Microsoft-Windows-Kernel-Power", 109):
    _r("Windows is shutting down",
       "The kernel started an orderly shutdown.",
       _OK, INFO, noisy=False),
```

`_r(title, meaning, action, severity, noisy)`. Both `title` and `meaning`
run through `_fill()`, so `{TargetUserName}` style placeholders resolve
against the event's `fields` — a missing key renders blank rather than
raising. `noisy=True` hides it behind "Hide routine chatter".

Find the provider and ID by clicking the event in the app; the detail pane
shows both. If no rule matches, `summarise()` leads with Windows' own first
sentence — which is why unknown events still read sensibly instead of
saying "Routine activity".

### Add a device or network rule

Same idea, but in `devices.py` using `_d(...)`, which takes an extra `kind`
(`"device"` or `"network"`) so the Devices & Network tab can find it. For
logic that needs to *adjust* an event rather than replace it, append a hook
to `_REFINERS` (see `_refine_network`, `_refine_device`). Refiners run after
the base rule, and exceptions inside them are swallowed by design.

### Watch another event log channel

Add to `CHANNELS` (in `translations.py`, or `devices.py` if it is
device-related):

```python
"Microsoft-Windows-TaskScheduler/Operational": {
    "label": "Scheduled tasks", "needs_admin": False, "default_on": True,
},
```

It appears in Settings automatically. `_adopt_new_channels()` in `ui.py`
turns newly-added default-on channels on for existing users without
overriding what they have deliberately switched off.

### Add a field to a record

Add it to the `RollingRecord(...)` constructor's `fields` tuple in
`history.py`. Note the consequence: `signed_fields` changes, so **every
existing entry fails verification**. That is the hash chain working
correctly, not a bug. Either accept one "tampered" report (the damaged file
is preserved, a fresh chain starts) or write a migration.

### Record a new kind of thing

1. Detect it in a `*watch.py` module; emit through a bounded deque + callback.
2. Add a `RollingRecord` instance in `history.py`.
3. Wire the callback in `recorder.py` (`_on_records` / `_on_activity`).
4. Add `describe_*` and `*_as_event` helpers so it can render in both the
   panel and the Live list.
5. Poll it in `ui.py` alongside `_new_record_events`, using `signature()`.

### Change colours

All of it is in `theme.py`. The surface ladder (`INK_0`…`INK_3`), the three
text tiers, the accent and the row states are declared once at the top; every
widget style is in `qss()` below them; the rich-text card helpers are at the
bottom. `ui.py` and both panels only hold aliases onto those names.

`SEVERITY_COLOR` is the one exception and stays in `translations.py:31`,
next to the severity keys it maps — it is domain information, not decoration.
If you change it, update `WASH` and `EDGE` in `theme.py` to match: those are
the same colours pre-flattened against their background, because Qt rich text
does not render alpha.

### Stop a program cluttering the list

Add its executable name to `SKIP_PROGRAMS` (`activitywatch.py:62`).

---

## 9. Load-bearing invariants

These look like ordinary code. They are not. Each one was arrived at by
something breaking, and each has a comment in place explaining it.

**① The read-only surface is the whole security model.**
`watcher.py` imports exactly five Event Log functions, all reads:
`EvtQuery`, `EvtNext`, `EvtSubscribe`, `EvtRender`, `EvtFormatMessage`.
`EvtClearLog`, `EvtExportLog` and `EvtArchiveExportedLog` are never
imported, so no code path can reach them. The import list at the top of
`watcher.py` *is* the audit — keep it that way, and do not add write-capable
calls anywhere in the project.

**② Never close an event-log subscription while running.**
`EvtClose` blocks until in-flight callbacks return. Those callbacks are
Python and need the GIL, which the closing thread is holding. If an event
arrives at that moment the process deadlocks completely — measured, with a
watchdog thread that could not fire. So subscriptions open once per channel
and stay open for the process lifetime; pause and channel changes are plain
flag checks in the callback. `shutdown()` deliberately does not close them.
Verified across 8.99 M pause/resume cycles during a flood.

**③ Never `CloseHandle` the directory watcher to stop it.**
A pending synchronous `ReadDirectoryChangesW` keeps the handle busy, so
`CloseHandle` waits for a read that is itself waiting for a file change.
Measured: `stop()` never returned. The read is issued as overlapped I/O and
`stop()` signals a Win32 event the thread is already waiting on.

**④ Recorder-sourced events are exempt from `_fold()`.**
`ui.py:298` coalesces repeated events. Device and activity records must not
be folded: unplugging and replugging a phone twice in a minute is two facts,
not one. The exemption list is `("Device recorder", "Activity recorder")` —
if you add a third recorder source, add it here too.

**⑤ Qt's rich text is an HTML 4 subset.**
`QTextBrowser` silently ignores `border-left`, `border-radius`,
`letter-spacing` and most of modern CSS. Accent rails are built from `<table>`
cells for exactly this reason — see `theme.card()`, which nests a second table
so `cellpadding` cannot inflate the 3px rail into a slab. Test any HTML change
by looking at it: it fails by rendering wrong, not by erroring.

Three specific traps inside that subset, each of which cost a render cycle:

- **`letter-spacing` has no substitute except real spaces**, and a normal or
  hair space is a legal line-break point. In a narrow cell Qt takes every one
  of them and renders the label as a vertical column of single letters.
  `theme.spaced()` uses U+202F NARROW NO-BREAK SPACE for this reason. Section
  titles skip it entirely so the rendered HTML stays searchable.
- **`width="100%"` on a spacer cell means it.** Qt gives that cell the whole
  row and compresses its neighbours until it breaks words in half. Size a
  strip with percentages that sum to 100 and use no spacer — `theme.metrics()`.
- **A `QTextBrowser`'s QSS background is painted under the document, not
  through it.** The body element has to repeat the colour or the page shows
  through wherever content is shorter than the viewport. `theme.page()`.

**⑥ `&` is a keyboard mnemonic in every Qt control that shows text.**
Tab titles need `"Devices && Network"`, and so does anything else built from
`CHANNELS[...]["label"]` — five of the nine channel names contain an
ampersand, and in a `QCheckBox` a single `&` is swallowed and underlines the
next letter instead. `SettingsDialog` doubles it on the way in.

**⑦ Widgets that sit on a card must opt out of the base background.**
`QWidget { background: INK_0 }` cascades into `QLabel` and `QCheckBox`, which
then paint the canvas colour over whatever card they are on and box every
option in its own dark rectangle. Both are exempted explicitly at the top of
`qss()`; add any new text-bearing widget to that rule.

**⑧ Mouse tracking has to be set on the viewport.**
`QAbstractItemView` delivers mouse events through its viewport child, so
`setMouseTracking(True)` on the view alone reaches nothing — `entered` never
fires and hover silently does not paint. `EventTable` sets it on both and
reads the hovered row from `mouseMoveEvent` + `indexAt()` rather than relying
on the signal.

**⑨ Python 3.11 forbids a backslash inside an f-string expression.**
`f'{x or "\u2014"}'` is a `SyntaxError`, not a runtime one, so it takes the
whole module out. Hoist the character to a module constant — see `DASH` in
`devicepanel.py`.

**⑪ The recorder recognises itself by exact path, never by name.**
`activitywatch._is_self()` skips only the exact packaged `SystemWatch.exe`
this copy runs from, or a Python running one of *this folder's* entry
scripts. The original check skipped anything whose path or command line
contained "systemwatch" or "main.py" — which let any program keep itself
out of the record just by being named that. Do not loosen it back.

**⑫ `RollingRecord.append()` holds a lock.** The program poller and the
file watcher both append to the activity record from different threads.
Without the lock both could read entry N and write N+1, losing one fact
with the chain still verifying. `test_history.py` hammers it from 4 threads.

**⑬ Everything from config.json is untrusted.** `config._clean()` keeps a
value only if it has the same type as its default, clamps `backfill`, and
drops unknown channels and keys. A hand-edited file cannot crash the window
or switch on something that is not offered in Settings.

**⑭ Exceptions must not escape a slot.** PyQt5 aborts the process when one
does, and the packaged exe has no console. `main._install_error_log()`
replaces `sys.excepthook`, which PyQt honours: the traceback goes to
`error.log` and the window keeps running.

**⑮ The recorder reads its settings once.** It blocks on a single wait and
has no timer, so it cannot notice a change. `ui.restart_recorder()` stops it
via the named stop event, waits (off the UI thread, by timer) for its mutex
to go, and starts a fresh one. Only "Record programs and documents" needs it.

**⑩ Do not build patch scripts with bash heredocs in this project.**
The tooling halves backslashes, which silently corrupts Windows paths and
escape sequences. Use the Write tool.

---

## 10. Tests

```bash
python tests/run_all.py
```

Each suite runs in its own process and sandboxes `LOCALAPPDATA` / `APPDATA`
into a temp directory, so a test cannot touch real records. (An earlier
version did not, and wrote "Test Device 99" into the live record — hence the
sandboxing.)

| Suite | Covers |
|---|---|
| `test_history.py` | Rolling window, hash chain, tamper detection, backup healing |
| `test_activity.py` | Program and file watchers, protocol filtering, `stop()` |
| `test_config.py` | Hostile/broken settings files fall back safely; atomic save |
| `test_ui.py` | Window builds, all three tabs render, both records appear, markup in titles is escaped, copy and layout memory |

`tests/render_states.py` is a harness rather than a test: it builds the
window, drives it into the states that only exist after an interaction —
empty search results, the paused header, an error-severity detail pane, the
settings dialog — and grabs a PNG of each. Use it when changing anything
visual; those states are unreachable from a plain screenshot and awkward to
reach with synthetic mouse clicks.

```bash
python tests/render_states.py out-dir
```

`test_ui.py` is worth keeping green: it caught a `NameError` in
`_detail_html` that would have crashed the detail pane for every recorded
event, on a path nothing else exercised.

Not currently covered: the event-log deadlock stress test (lost when a
scratch directory was wiped), and `translations` rule coverage.

---

## 11. Known limits — state these plainly, don't paper over them

- **"Every file opened" is not literal and cannot be.** Seeing every file
  every process touches needs a kernel-mode filter driver — Administrator
  plus a signed driver — and would be unusable noise. What you get is
  documents opened through Explorer or a File-Open dialog, which is what
  Windows itself records. A program quietly reading its own config will not
  appear. The tab says so on screen, so an empty list is never mistaken for
  "nothing happened".
- **Programs without a window can be missed.** The visible-window heuristic
  is what makes the list meaningful; the cost is that a short-lived
  console-only process may not register.
- **The record can be deleted, only not altered unnoticed.** Making a file
  undeletable requires Administrator. Two copies plus a hash chain is the
  honest maximum without it.
- **The hash chain has no secret.** It catches hand edits, removals and
  damage. Someone who reads `history.py` and recomputes every hash can forge
  a consistent file. A key would not help: anything this account can read,
  whoever is using this account can read too.
- **The packaged exe is not code-signed.** SmartScreen warns on first run
  until it is signed with a certificate the user's PC trusts.
- **The Security channel needs Administrator.** Without it, sign-in events
  are simply unavailable; the app reports this rather than showing an empty
  list. `readable_channels()` probes what is actually readable at startup.
- **Anything the machine does before the recorder starts is invisible.**
  There is no retroactive capture for devices or programs — only the event
  log has a backfill, and only for its own records.
