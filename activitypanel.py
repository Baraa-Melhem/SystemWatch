# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
The "Programs & Files" tab: the last 50 programs launched and files opened.

Like the device record, this is written by the background recorder and only
read here, so it survives the window being closed. The panel never watches
anything itself - it reads the record and renders it.
"""

import html
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout,
    QWidget,
)

import config
import history
import recorder
import theme

# Local aliases onto theme.py. Nothing is defined here.
BG = theme.INK_0
PANEL = theme.INK_1
TEXT = theme.TEXT_HI
MUTED = theme.TEXT_MED
GREEN = theme.OK
YELLOW = theme.CAUTION
BLUE = theme.ACCENT

MIN_REFRESH_SECONDS = 2.0


def _esc(value):
    return html.escape(str(value if value is not None else ""))


class ActivityPanel(QWidget):
    """Read-only view of the recorded programs and files."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dirty = True
        self._last_refresh = 0.0
        self._queued = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bar = QFrame()
        bar.setObjectName("filterbar")
        bar.setFixedHeight(50)
        row = QHBoxLayout(bar)
        row.setContentsMargins(18, 0, 16, 0)

        self.headline = QLabel("Reading the record…")
        self.headline.setObjectName("panelheadline")
        row.addWidget(self.headline)
        row.addStretch(1)

        refresh = QPushButton("Refresh")
        refresh.setProperty("kind", "quiet")
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.setToolTip("Re-read the record from disk.")
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
        self._dirty = True
        if not self.isVisible():
            return
        waited = time.monotonic() - self._last_refresh
        if waited >= MIN_REFRESH_SECONDS:
            self.refresh()
        elif not self._queued:
            self._queued = True
            QTimer.singleShot(
                max(200, int((MIN_REFRESH_SECONDS - waited) * 1000)),
                self._deferred,
            )

    def _deferred(self):
        self._queued = False
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
            entries, status = history.load_activity()
        except Exception as exc:
            entries, status = [], f"tampered: {exc}"

        programs = [e for e in entries if e.get("action") == "program"]
        files = [e for e in entries if e.get("action") != "program"]

        self.headline.setText(
            f"{len(programs)} programs and {len(files)} files recorded"
            f"   ·   newest {history.MAX_ENTRIES} kept"
        )
        self.headline.setToolTip(
            "Written by the background recorder, so it keeps filling in "
            "while this window is closed."
        )
        self.view.setHtml(self._render(entries, programs, files, status))

    # -- rendering -------------------------------------------------------
    def _render(self, entries, programs, files, status):
        tampered = status.startswith("tampered")
        try:
            running = recorder.is_running()
        except Exception:
            running = False

        summary = theme.metrics([
            theme.metric(len(programs), "PROGRAMS"),
            theme.metric(len(files), "FILES"),
            theme.metric(f"{len(entries)}/{history.MAX_ENTRIES}", "RECORD"),
        ]) + theme.gap(14)

        if not config.record_activity():
            banner = theme.status_card(
                "Programs and files are not being recorded right now",
                "You switched this off, so nothing new is written here. Turn "
                "it back on in Settings \u2192 Privacy. Anything listed below "
                "was recorded earlier.",
                tone="caution",
            )
        else:
            banner = theme.status_card(
                _esc(history.status_text(
                    status, len(entries), "programs and files"
                )),
                (
                    "Background recorder: running \u2014 recording even with "
                    "this window closed"
                    if running else
                    "Background recorder: NOT running \u2014 nothing is being "
                    "recorded right now"
                ),
                tone="caution" if (tampered or not running) else "ok",
            )

        return theme.page(
            summary
            + banner
            + theme.section("PROGRAMS OPENED", len(programs))
            + self._table(programs, is_program=True)
            + theme.section("FILES OPENED", len(files))
            + self._table(files, is_program=False)
            + self._scope_note()
        )

    def _scope_note(self):
        """
        Says plainly what this tab can and cannot see.

        Without it an empty list reads as "nothing happened", which would be
        a much stronger claim than this tab is able to make.
        """
        return (
            theme.gap(18)
            + theme.card(
                f'<div style="color:{theme.TEXT_MED}; font-size:11px;">'
                f"<b>What this covers</b></div>"
                f'<div style="color:{theme.TEXT_LOW}; font-size:11px; '
                f'line-height:160%; margin-top:6px;">'
                f"Programs are spotted when they open a window, so background "
                f"helpers Windows starts by itself are left out on purpose. "
                f"Files are the documents you open through Explorer or the "
                f"File-Open dialog of a program, which is what Windows itself "
                f"keeps track of. A program quietly reading its own settings "
                f"file does not appear here \u2014 seeing that would need a "
                f"driver running as Administrator, which this program will "
                f"not install.</div>",
                background=theme.INK_0,
            )
        )

    def _table(self, entries, is_program):
        if not entries:
            what = "programs" if is_program else "files"
            return theme.empty(
                f"No {what} recorded yet.",
                "The recorder writes here as soon as it sees one.",
            )

        rows = []
        for entry in reversed(entries):          # newest first
            name = _esc(entry.get("name", ""))
            path = _esc(entry.get("path", ""))
            detail = entry.get("detail", "")
            if detail:
                name += (
                    f' <span style="color:{theme.TEXT_LOW};">'
                    f"({_esc(detail)})</span>"
                )
            path_html = (
                f'<div style="color:{theme.TEXT_LOW}; font-size:11px; '
                f'margin-top:2px;">{path}</div>'
                if path else ""
            )
            rows.append(
                f"<tr>"
                f'<td width="44" valign="top" style="color:{theme.TEXT_LOW}; '
                f'font-size:11px;">#{_esc(entry.get("seq", ""))}</td>'
                f'<td width="140" valign="top" '
                f'style="color:{theme.TEXT_LOW}; font-size:11px;">'
                f'{_esc(entry.get("time", ""))}</td>'
                f'<td style="font-size:12px; color:{theme.TEXT_HI};">'
                f"{name}{path_html}</td></tr>"
            )
        return theme.rows("".join(rows))

    def _section(self, title):
        """Kept as a thin alias; theme.section() is the real implementation."""
        return theme.section(title)
