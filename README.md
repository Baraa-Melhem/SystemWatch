# SystemWatch

A lightweight, **strictly read-only** monitor for the Windows event log. It
watches what your PC is doing and explains it in plain English, with a
green / yellow / red indicator so you can judge system health at a glance.
It also shows what is plugged in, which network you are on, and keeps a
small local record of devices connected and programs and documents opened.

- **Read-only.** It cannot clear, edit or reconfigure any Windows log or
  setting - the destructive parts of the Event Log API are never imported.
- **Private.** Everything stays on your PC. The code makes no network
  requests at all.
- **Light.** Well under 1 % of one CPU core, about 70 MB of memory.
- **No admin rights** to install or run.
- **Free and open source** under the [GNU GPL v3](LICENSE).

Windows 10 and 11, 64-bit.

## Download

Get **`SystemWatch-Setup-<version>.exe`** from the
[latest release](https://github.com/Baraa-Melhem/SystemWatch/releases/latest),
run it, and click Next. It installs for your user only, needs no
administrator password, and comes with a normal uninstaller. Python is not
needed. Each release lists the installer's SHA-256 so you can check the
download.

The installer is not code-signed, so Windows SmartScreen may say "Windows
protected your PC" the first time - choose **More info -> Run anyway**. If
you would rather not trust a binary, build it yourself (below); it is the
same code.

## Build from source

You need Windows and Python 3.11 (64-bit).

```bash
python -m pip install -r requirements.txt
python main.py
```

To build the installer: install [Inno Setup 6](https://jrsoftware.org/isinfo.php)
(`winget install JRSoftware.InnoSetup --scope user`) and run
`packaging\build.bat`. It makes its own build environment in
`packaging\.buildenv`, freezes the app with PyInstaller and writes
`release\SystemWatch-Setup-<version>.exe`. Run the tests with
`python tests/run_all.py`.

`ARCHITECTURE.md` is the technical reference - read it before changing
anything. Bug reports and pull requests are welcome; see `SECURITY.md` for
reporting a vulnerability privately.

## Performance

Measured on a typical laptop while idle and monitoring:

| | |
|---|---|
| CPU | **0.07 – 0.25 % of one core** (0.006 – 0.02 % of the whole machine) |
| RAM | ~35 MB private, ~70 MB working set — bounded, see below |
| Threads | 5 – 8 |
| Polling | none — Windows pushes both events and device changes to the app |

The headless recorder is separate and smaller still: **0 % CPU** (nothing
measurable over 75 seconds idle) and 16 MB private, watching devices,
programs and files at once. Almost everything it does is blocked waiting on
Windows rather than looping; the one thing that does poll - looking for new
processes - costs 0.05 ms every 1.5 seconds, which does not register.

Measured over 90-second windows once settled, with all 8 logs subscribed plus
real-time device watching. The range reflects how chatty the machine is: a
quiet wired connection sits at the bottom of it, a busy Wi-Fi link that emits
connectivity events every few seconds at the top. The first ~30 seconds after
launch cost more (around 1 % of a core) while the backlog of recent events is
read in, then it settles.

---

## Running from source

After `python -m pip install -r requirements.txt`, start it with any of:

- Double-click **`Run SystemWatch.bat`** (tries an Anaconda Python first,
  then whatever `pythonw` is on PATH)
- Double-click **`SystemWatch.pyw`** (no console window)
- `python main.py` from a terminal, if you want to see diagnostic output

---

## The installer

`SystemWatch-Setup-<version>.exe` is a per-user installer: no admin rights,
installs to `%LOCALAPPDATA%\Programs\SystemWatch`, adds Start menu /
desktop / optional sign-in shortcuts, and a normal uninstaller that asks
whether to keep the recorded history. `docs\How to install SystemWatch.txt`
is a plain-language guide to hand to people who just want to use it.

To release a new version, change the number in **`version.py`** only - the
exe's file properties, the installer and its file name all take it from
there - note what changed in `CHANGELOG.md`, and run `packaging\build.bat`.

The packaged build is a single `SystemWatch.exe` that plays both parts:
plain it is the window, with `--recorder` it is the headless recorder
(`--recorder --stop` stops one). `startup.command_for()` picks the right
command for whichever form is running, so the window's recorder launch and
the start-with-Windows shortcuts work in both. The exe is not code-signed,
so Windows SmartScreen shows "Windows protected your PC" on first run -
**More info -> Run anyway**.

---

## Using it

| Control | What it does |
|---|---|
| **Pause** | Stops taking in new events. Nothing is read while paused. |
| **Error / Warning / Info** chips | Show or hide each severity. |
| **Hide routine chatter** | Hides the very noisy housekeeping events (service start/stop, power-state bookkeeping, the harmless DCOM 10016 warning). |
| **Search** | Filters on title, explanation, source, event ID, and the original Windows text. |
| **Clear view** | Empties *this window only*. Windows' own logs are never touched. |
| **Settings** | Choose which logs to watch, toggle notifications and start-with-Windows, and switch recording of programs and documents on or off (Privacy). Also shows the version and opens the data folder. |
| **Right-click an event** | Copy details (ready to paste into a message to IT), copy the title, or show only events like it. |

Keyboard: **Ctrl+F** search (Esc clears it) · **Ctrl+C** copy the selected
event · **Ctrl+1/2/3** switch tab · **F5** refresh · **Ctrl+,** settings ·
**F1** about · **Ctrl+Q** quit completely.

The window remembers its size, position and the list/detail split. On the
very first launch a short welcome explains what is recorded and offers to
leave programs and documents out.

### Privacy

Everything stays on the PC, in the user's own profile. Nothing is sent over
the network - the code makes no network requests at all. The device record
and the programs-and-documents record hold the newest 50 entries each.
Recording of programs and documents can be switched off in **Settings ->
Privacy**; device connections are always recorded, since that is the
recorder's core job. Uninstalling asks whether to delete the records too.

### The three tabs

**Live events** is the stream described above.

**Devices & Network** answers "what is plugged in, and what am I connected
to?" at a glance:

- a green or amber banner saying whether any **removable drive is connected
  right now**, with its label, drive letter and free space
- **Attached right now** - every USB, Bluetooth and portable device currently
  plugged in, including phones, which never get a drive letter and so cannot
  be found by looking at drives
- the **network** you are on - Wi-Fi SSID and its security type, or the wired
  adapter - plus **IP address, gateway (router), DNS servers, DHCP server**
  and MAC address
- every drive letter, with removable ones highlighted
- **Recently connected** - a timeline of what has been plugged in, read back
  from the log, naming the actual hardware (e.g. *"Drive connected: KINGSTON
  (E:) - Kingston DataTraveler 3.0"*)

That tab has no timer. It refreshes when you open it, when you press
**Refresh**, and whenever a device or network event arrives on a channel
SystemWatch is already subscribed to. Idle cost is zero.

### The permanent record of device connections

Every device connection and disconnection is written to a record that keeps
the **newest 50** entries. When the 51st arrives the oldest rolls off.

This is kept by a **separate background program** with no window, so it keeps
recording whether or not SystemWatch itself is open:

```bash
python recorder.py --status
```

That prints whether the recorder is running and dumps the whole record.
`python recorder.py --stop` shuts it down. Only one copy can ever run - a
second launch sees the first through a named mutex and exits - so the login
shortcut plus a manual start cannot produce two recorders fighting over the
same file.

The SystemWatch window starts the recorder if it is not already running.

**The window does not detect devices itself.** It reads the recorder's record
and shows it in two places: the **Live events** list, and **Devices & Network
-> Recorded connections**. That is deliberate - one detector, one record.
It means connections that happened while the window was shut are there in the
main list the moment you open it, and nothing is ever counted twice.

#### Storage

Each entry is roughly 270 bytes. At the full 50 the file is about **13 KB**,
or 27 KB counting the backup copy. The 51st entry pushes the oldest out, so
it never grows past that - it is a fixed cost, not a growing one.

#### About "so no one can delete it"

**It cannot be made undeletable, and this is worth being straight about.** A
file your account owns can always be deleted by your account, and an
administrator can delete anything on the machine. Preventing that needs a
service running as SYSTEM with locked-down permissions, which would mean
administrator rights and real changes to the system - the opposite of what
this program is meant to be.

So instead of a promise it cannot keep, the record is built so that deleting
or editing it **does not go unnoticed**:

| | |
|---|---|
| **Two copies, different folders** | `%LOCALAPPDATA%\SystemWatch\` and `%APPDATA%\SystemWatch\`. Delete one and the other rebuilds it automatically on the next read — nothing is lost. |
| **Hash-chained entries** | Each entry carries a SHA-256 of its own contents plus the hash of the entry before it. Editing one breaks its own hash; removing one from the middle breaks the next entry's link. |
| **Entry numbers never reset** | They keep counting up, so a gap is visible even long after old entries have rolled off. |
| **Damaged files are kept** | If the chain fails, the bad file is renamed `.damaged-<timestamp>` rather than overwritten, and a fresh record is started alongside it. |

The Devices & Network tab states the record's condition in plain words —
*"50 connections recorded, and the record is intact"*, or *"The record was
altered outside SystemWatch — entry #23 was modified"*. Someone can still
delete it; they cannot delete it **quietly**.

### The record of programs and files

A third tab, **Programs & Files**, keeps the newest 50 programs launched and
files opened, in the same tamper-evident, duplicated, hash-chained record as
the device history. The background recorder writes it, so it keeps filling in
whether or not the window is open.

#### How each half is watched, and why they differ

**Programs are polled.** Windows will not push process-start notifications to
a normal user: `Win32_ProcessStartTrace` is access-denied, the Security log's
event 4688 needs Administrator *and* an audit policy turned on, and ETW's
kernel provider needs Administrator. So this is a deliberate, measured
exception to the no-polling rule elsewhere in the program:

- `psutil.pids()` costs **0.05 ms**; diffing a set of integers is free
- only a **brand-new** pid is looked up in detail - enumerating every process
  at once costs 540 ms and never happens
- at a 1.5 s interval that is about **0.005% of one core**

A new process is only recorded once it opens a **visible window**, which is
what separates a program you started from the helpers Windows spawns
constantly. Shell components (`explorer.exe`, `RuntimeBroker.exe`,
`OpenWith.exe` and friends) and SystemWatch's own processes are skipped.

**Files are event-driven.** Windows keeps a folder of shortcuts to documents
you have opened and updates it as you work. Watching that folder with
`ReadDirectoryChangesW` means the thread blocks until Windows says something
changed, so file tracking costs **nothing at all** while you are not opening
files. Each shortcut is resolved to the real path it points at.

Shell protocol activations - the `ms-gamingoverlay---` and
`ms-screenclip---source=PrintScreen` entries Windows drops in there when you
press PrintScreen or open the game bar - are filtered out, so they cannot
crowd real documents out of the 50 slots.

#### What "every file" honestly means

**It is not literally every file, and it cannot be.** Seeing every file that
every process opens needs a kernel-mode filter driver, which means
Administrator rights and a signed driver - the opposite of what this program
is. It would also be useless noise: Windows opens thousands of files a
minute.

What you get is the part that matters: **documents you open through Explorer
or through a program's File-Open dialog**, which is exactly what Windows
itself keeps track of. A program quietly reading its own settings file will
not appear. The tab says so on screen, so an empty list is never mistaken for
"nothing happened".

Short-lived programs that never open a window, and programs that come and go
between two polls, can also be missed.

### Only one window at a time

Launching SystemWatch when it is already running does **not** start a second
copy - it brings the existing window to the front and exits.

This matters more than it sounds. Without it, every launch added another
process, each with its own tray icon and its own idea of what had happened.
Closing "the program" closed one of them while the others stayed in the tray
showing whatever they had loaded when *they* started, which looks exactly
like the record failing to update.

If you ever want to be sure, the count should be two: one window, and one
recorder.

```bash
python recorder.py --status
```

### Closing and quitting

- The **X** button hides the window to the notification area and keeps
  monitoring (it tells you the first time it does this).
- **Right-click the tray shield → Quit** exits completely.
- To make **X** quit outright instead, untick *"Closing the window keeps it in
  the tray"* in Settings.

### The colours

| | Meaning |
|---|---|
| 🟢 **Green — Info** | Normal activity. Nothing to do. |
| 🟡 **Yellow — Warning** | Something wasn't quite right but kept working. Worth a glance if it repeats. |
| 🔴 **Red — Error** | Something failed. The detail panel tells you what to do. |

Selecting any row explains it in three parts: **what this means**, **what you
should do**, and the raw technical detail (event ID, source, log, and Windows'
own wording) for when you want to search for it.

---

## Starting automatically with Windows

**It is already enabled.** Tick or untick *"Start automatically when Windows
starts"* in Settings at any time, or from a terminal:

```bash
python startup.py status
```

`python startup.py enable` and `python startup.py disable` do the same thing
without opening the app.

### How that works, and why it's safe

Enabling it creates **one shortcut file** here:

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\SystemWatch.lnk
```

That is an ordinary folder inside your own user profile. Windows runs whatever
it finds there when you log in. This means:

- **No administrator rights** are needed.
- **No registry keys**, no services, no scheduled tasks, no Group Policy.
- Nothing outside your own profile is modified.
- It appears in **Task Manager → Startup apps**, so you can disable it there
  too.
- Deleting the shortcut undoes it completely.

The shortcut launches `pythonw.exe` (the windowless Python) with `--tray`, so
at login SystemWatch starts quietly in the notification area instead of
opening a window in your face.

There are **two** such shortcuts, and they are independent:

| Shortcut | What it does |
|---|---|
| `SystemWatch.lnk` | opens the window (in the tray) at login |
| `SystemWatch Recorder.lnk` | runs the headless device recorder at login |

The recorder is the one that matters for recording devices when the window is
closed. Both are toggled in Settings, or from a terminal:

```bash
python startup.py status
```

`enable` / `disable` set both; `enable-recorder` / `disable-recorder` set just
the recorder.

---

## How it reads logs without interfering with Windows

This is the part that matters most, so here it is precisely.

### It only ever calls read functions

SystemWatch uses exactly five functions from the Windows Event Log API, and
every one of them is a read operation:

| Call | Purpose |
|---|---|
| `EvtQuery` | open an existing log **for reading** |
| `EvtNext` | read the next record from that query |
| `EvtSubscribe` | ask Windows to hand us new records as they occur |
| `EvtRender` | turn a record we were handed into XML text |
| `EvtFormatMessage` | turn a record into its human-readable sentence |

The destructive half of that same API — `EvtClearLog`, `EvtExportLog`,
`EvtArchiveExportedLog` — is **never imported and never called**. Neither is
any registry, service-control, or policy API. There is no code path in this
program that can clear, edit, truncate, re-configure, or take ownership of a
log.

Windows enforces this independently of our good intentions: the channel
handles are opened with read access only, so a clear attempt would be refused
by the operating system even if one existed. You can verify the whole surface
yourself — it is a single file, [`watcher.py`](watcher.py), and the imports at
the top are the complete list of OS calls the program can make.

### It doesn't poll, so it doesn't cost anything

Nothing scans, re-reads, or wakes up on a timer to check the logs.
`EvtSubscribe` registers a callback and **Windows invokes it from its own
thread pool only when an event is actually written**. While your machine is
quiet, SystemWatch does no work at all. That is why idle CPU measures 0.02 %
of a core rather than "low".

Windows was going to write these events whether or not this app is running.
Subscribing is passive: it adds a reader, it does not cause any extra logging,
and it does not slow the writers down.

### It stays cheap even when things get busy

- The OS callback is deliberately tiny — it renders the record and drops it
  into a fixed-size queue. Parsing, translating and drawing all happen later,
  in batches, on the UI thread.
- Under a burst the callback skips the expensive message-formatting step, and
  the queue discards the oldest overflow rather than growing. A storm of
  events costs bounded memory and bounded CPU instead of dragging the machine
  down.
- The UI drains at most 80 events every 500 ms, so the interface stays smooth
  no matter what the logs are doing.
- At most 1500 rows are held in memory; repeats within two minutes fold into
  a single row with a `×N` counter. Memory therefore rises slightly as the
  list fills and then **stops** — it does not grow with uptime. *Clear view*
  releases it immediately.

### Devices and networks

**The event log is not enough for devices, and this is worth understanding.**
Kernel-PnP records driver *configuration* - the first time Windows sets a
device up, or when its driver changes. Unplugging and re-plugging something
Windows already knows writes nothing at all. Measured on a test machine: a
phone was connected at 14:02 while the newest Kernel-PnP record was still
from 10:19. Storage happens to be the exception, because mounting a
filesystem does get logged.

So devices are watched a second way, straight from Windows.
`RegisterDeviceNotification` with `DEVICE_NOTIFY_ALL_INTERFACE_CLASSES` asks
for every device interface arrival and removal - the same mechanism Explorer
uses - and Windows then posts `WM_DEVICECHANGE`. That fires on every plug and
unplug regardless of driver state, which is what "detect every movement"
actually requires.

The obvious way to receive those messages - a Qt application-wide native
event filter - would run a Python callback for *every* Windows message,
including every mouse move. Instead SystemWatch creates one hidden top-level
window on its own thread. It receives device notifications and nothing else,
and the thread blocks inside `GetMessage` the rest of the time, costing
nothing. (It has to be top-level rather than message-only: drive-letter
arrivals are *broadcast*, and broadcasts never reach a message-only window.)

Plugging in one phone makes Windows announce five separate interfaces - ADB,
modem, MTP, composite and so on. They are grouped by vendor/product behind a
short debounce, so one plug produces one line, named from the MTP interface
where the owner's own device name lives (*"bara's M31 connected"*) rather
than five rows of hardware IDs.

The NTFS channel is still used as well, since it carries the vendor, model,
label and drive letter for storage.

Windows re-enumerates dozens of internal components on every boot and wake.
SystemWatch tells those apart from things a person actually plugged in by
reading the bus prefix on the device id - `USBSTOR\`, `USB\`, `BTHENUM\` and
friends are real; `PCI\`, `ACPI\`, `SWD\` and `ROOT\` are internal - and folds
the internal ones into routine chatter.

The Devices & Network tab additionally reads current state directly:

| What | How |
|---|---|
| Drive letters, type, label, free space | `GetLogicalDriveStrings`, `GetDriveType`, `GetVolumeInformation`, `GetDiskFreeSpaceEx` |
| Devices attached right now (incl. phones) | one read-only WMI `SELECT` against `Win32_PnPEntity` |
| IP, gateway, DNS, DHCP server, MAC | one read-only WMI `SELECT` against `Win32_NetworkAdapterConfiguration` |
| Bytes sent/received | `psutil` counters |

All of these are queries. Nothing mounts, ejects, assigns a drive letter, or
changes any network setting. The WMI call is a `SELECT` - the only verb used -
and it runs on demand, never on a timer.

### The one thing it writes

Its own settings file, and nothing else:

```
%LOCALAPPDATA%\SystemWatch\config.json
```

Deleting that file resets the app to defaults. No system file, no system
setting, and no other program's data is ever written.

### A deliberate design note

Event-log subscriptions are opened once and kept for the life of the process
rather than being closed and reopened when you pause or change channels.

This is not laziness — closing a subscription blocks until any callbacks
already in flight have returned, and those callbacks need Python's interpreter
lock, which the closing thread is still holding. If an event arrives at that
exact moment, the two wait on each other and the whole process freezes. This
was measured during development, not assumed: closing mid-delivery hung a test
process hard enough that even a watchdog thread couldn't fire.

So pausing and switching channels are done with simple flags the callback
checks, which costs one lookup per event and cannot deadlock. Handles are
released by Windows when the process exits — the only moment at which no
callback can still be running. There are five channels at most, so nothing
accumulates.

---

## What it watches

| Log | Friendly name | Needs admin |
|---|---|---|
| `System` | Windows & hardware | no |
| `Application` | Apps & programs | no |
| `Microsoft-Windows-Windows Defender/Operational` | Antivirus (Defender) | no |
| `Setup` | Windows updates & setup | no |
| `Microsoft-Windows-NetworkProfile/Operational` | Networks joined & left | no |
| `Microsoft-Windows-WLAN-AutoConfig/Operational` | Wi-Fi | no |
| `Microsoft-Windows-Ntfs/Operational` | Drives & USB storage | no |
| `Microsoft-Windows-Kernel-PnP/Configuration` | Devices plugged in | no |
| `Security` | Sign-ins & security | **yes** |

### About the Security log

The Security log — which holds sign-in events like **4624** — can only be read
by an administrator. That is a Windows rule, not a limitation of this app.

Run SystemWatch normally and it monitors everything else and tells you in the
status bar that sign-in events need Administrator. If you want them, start it
elevated (right-click → *Run as administrator*); the Security channel then
appears in Settings and can be ticked.

Everything else works fine as a normal user, which is the recommended way to
run it.

---

## Plain-English translations

**111 rules across 25 event sources** are hand-written — crashes, service
failures, disk errors, blue screens, malware detections, Defender being
switched off, unexpected shutdowns, sign-ins, new accounts, new services, and
the audit log being cleared, among others.

For example, event ID **4624** becomes *"Someone signed in successfully"*,
along with **how** they signed in — at the keyboard, over the network, through
Remote Desktop, or by unlocking the screen.

For anything without a hand-written rule, SystemWatch leads with **Windows'
own sentence** rather than an unhelpful generic label, and marks it in the
detail panel as *"shown in Windows' own words"* so you always know which you
are reading. It never invents an explanation it doesn't have.

---

## Files

| File | Role |
|---|---|
| `main.py` | entry point |
| `ui.py` | window, event table, detail panel, tray icon |
| `theme.py` | the design system — every colour, font and the whole stylesheet |
| `watcher.py` | the read-only event log reader — **the whole OS surface** |
| `translations.py` | event ID → plain English, and severity rules |
| `devices.py` | USB/device and network rules, and device-bus classification |
| `livestate.py` | current drives and IP configuration (read-only queries) |
| `devicepanel.py` | the Devices & Network tab |
| `devicewatch.py` | real-time plug/unplug detection via `WM_DEVICECHANGE` (used by the recorder) |
| `recorder.py` | the headless always-on recorder (no window) |
| `history.py` | the tamper-evident rolling records (50 each) |
| `activitywatch.py` | watches for programs launched and files opened |
| `activitypanel.py` | the Programs & Files tab |
| `tests/` | the test suite - `python tests/run_all.py` |
| `ARCHITECTURE.md` | technical reference for anyone changing the code |
| `startup.py` | creates/removes the Startup-folder shortcut |
| `SystemWatch.pyw` | double-click launcher, no console |
| `Run SystemWatch.bat` | launcher that finds your Python for you |
| `old/` | an earlier, unrelated implementation, kept for reference |

---

## Troubleshooting

**The Devices & Network tab shows no network name.** Windows only records a
network *name* at the moment it joins one. If the PC was already plugged in
at boot, there is nothing to name, so the tab falls back to showing the
adapter that actually holds the gateway - which is the same information.

**Nothing appears in the list.** Check that at least one log is ticked in
Settings, and that the app isn't paused. Freshly booted machines are quiet —
raise *"Recent events to load on launch"* in Settings to pull in history.

**"Sign-in events need Administrator" in the status bar.** Expected when
running as a normal user. See *About the Security log* above.

**It won't start from the .pyw file.** Windows may have `.pyw` associated with
a different Python. Use `Run SystemWatch.bat` instead.

**I want it gone.** Untick start-with-Windows in Settings (or run
`python startup.py disable`), quit from the tray, and delete this folder. The
only traces left are `%LOCALAPPDATA%\SystemWatch\` and its backup copy in
`%APPDATA%\SystemWatch\`, which you can delete too. If you used the
installer, uninstall from Settings -> Apps instead; it offers to delete both.

---

## License

SystemWatch is free software: you can redistribute it and/or modify it under
the terms of the [GNU General Public License](LICENSE) as published by the
Free Software Foundation, either version 3 of the License, or (at your
option) any later version. It is distributed in the hope that it will be
useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

Copyright (C) 2026 Al-Baraa Ibrahim Melhem.

The packaged installer also contains Python, PyQt5, Qt, pywin32 and psutil
under their own licences - see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
