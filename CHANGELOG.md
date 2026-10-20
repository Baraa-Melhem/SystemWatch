# Changelog

## 1.1.1 — 2026-10-20

- **Published as free software** under the GNU GPL v3 or later, at
  <https://github.com/Baraa-Melhem/SystemWatch>.
- The installer now carries the licence and the third-party notices, and
  Settings → Apps shows the publisher, support and update links.
- About shows the licence, the source address and a "Project page" button.
- `packaging\build.bat` no longer assumes Anaconda: it uses `SW_PYTHON`, an
  Anaconda install, the `py` launcher or `python`, in that order.

## 1.1.0 — 2026-10-20

### Security and privacy
- **Closed a way to hide from the record.** The recorder used to skip any
  program whose path or command line contained "systemwatch" or "main.py",
  so anything could keep itself out of the record by being named that. It
  now recognises only its own exact executable or scripts.
- **No more lost entries.** Two recorder threads could append to the
  programs-and-documents record at the same moment and silently drop one
  entry. Appends are now serialised.
- **Settings file is validated.** A damaged or hand-edited `config.json` can
  no longer crash the window or switch on unsupported logs; it is saved
  atomically.
- **New privacy setting:** recording of programs and documents can be
  switched off (Settings → Privacy). A first-run welcome explains what is
  recorded and where.
- All text panels refuse to follow links, and network values in the Devices
  tab are escaped like everything else.
- Documentation now states plainly what the hash chain can and cannot prove.
- The installer stops the recorder cleanly before replacing it, kills only
  its own `SystemWatch.exe`, and asks on uninstall whether to delete the
  recorded history.

### Interface
- Ticked checkboxes now show a tick, not just a colour.
- The tray menu, dialogs and message boxes use the app's dark theme.
- Right-click an event to copy its details for IT, copy the title, or show
  only events like it.
- Keyboard shortcuts: Ctrl+F, Esc, Ctrl+C, Ctrl+1/2/3, F5, Ctrl+, F1, Ctrl+Q.
- The window remembers its size, position and split.
- Clicking an error notification opens the window on that error.
- New About dialog (F1 or the tray menu); Settings shows the version and can
  open the data folder.
- Settings is two-column so it fits a 768-pixel-high screen.
- If Windows offers no notification area, closing the window quits instead
  of leaving an unreachable process behind.
- The time column falls back to Consolas where Cascadia Mono is missing.

### Reliability
- A bug in the window no longer closes the whole app: it is written to
  `error.log` in the data folder and the window keeps running.

## 1.0.0 — 2026-10-18
- First packaged release: one `SystemWatch.exe` (window, or `--recorder`)
  and a per-user installer.
