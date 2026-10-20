# Security policy

SystemWatch is meant to be trustworthy on someone's own PC: it only reads
the Windows event log, it makes no network requests, and it keeps its
records in the user's own profile. A bug that breaks any of those promises
is a security bug.

## Reporting a vulnerability

Please report it **privately**, not as a public issue: use GitHub's
[private vulnerability reporting](https://github.com/Baraa-Melhem/SystemWatch/security/advisories/new)
for this repository. Include the version (F1, or the foot of Settings), what
you did, and what happened.

This is a one-person project, so replies come as soon as time allows. Fixes
go into a new release, and the changelog credits the reporter unless they
would rather not be named.

## In scope

- Anything that lets SystemWatch write to, clear or reconfigure a Windows
  log or setting.
- Any network access by the app.
- Markup or links from event text, device names or file names being
  rendered or followed rather than shown as text.
- A way for a program to keep itself out of the programs-and-documents
  record, or to alter the record without it being reported.
- The installer or uninstaller touching anything outside its own folder,
  shortcuts and data folder.

## Known limits (not vulnerabilities)

These are documented in `ARCHITECTURE.md`:

- The record's hash chain has no secret, so someone who rebuilds every hash
  can forge a consistent record. Deleting the record is also possible.
- Programs that never open a window can be missed, and only documents opened
  through Explorer or a File-Open dialog are seen.
- The installer is not code-signed.
