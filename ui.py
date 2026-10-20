# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""SystemWatch - user interface (PyQt5)."""

import bisect
import html
import os
import time
from datetime import datetime

from PyQt5.QtCore import (
    QAbstractTableModel, QByteArray, QModelIndex, QRectF, QSize,
    QSortFilterProxyModel, Qt, QTimer, QUrl, pyqtSignal,
)
from PyQt5.QtGui import (
    QBrush, QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPainter,
    QPainterPath, QPixmap,
)
from PyQt5.QtWidgets import (
    QAbstractItemView, QAction, QApplication, QCheckBox, QDialog,
    QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMenu, QPushButton, QShortcut, QSizePolicy, QSpinBox,
    QSplitter, QStyle, QStyleOptionViewItem, QStyledItemDelegate,
    QSystemTrayIcon, QTableView, QTabWidget, QTextBrowser, QVBoxLayout,
    QWidget,
)

import subprocess

import config as config_mod
import history
import recorder as recorder_mod
import startup as startup_mod
import theme
from activitypanel import ActivityPanel
from devicepanel import DevicePanel
from translations import (
    CHANNELS, ERROR, INFO, SEVERITY_COLOR, SEVERITY_LABEL, SEVERITY_ORDER,
    WARN, friendly_provider,
)
from version import COPYRIGHT, HOMEPAGE, LICENSE_NAME, __version__
from watcher import EventWatcher, is_admin, readable_channels

APP_NAME = "SystemWatch"

# Every colour, font and radius now comes from theme.py, which is also what
# the two panel tabs read. Before this the palette was declared three times
# over and the tabs had drifted apart from each other.
BG = theme.INK_0
PANEL = theme.INK_1
PANEL2 = theme.INK_2
BORDER = theme.LINE
TEXT = theme.TEXT_HI
MUTED = theme.TEXT_MED
ACCENT = theme.ACCENT

MAX_RECORDS = 1500          # hard cap on rows held in memory
DRAIN_MS = 500              # how often we batch-update the view
DRAIN_LIMIT = 80            # max events parsed per tick, keeps UI smooth
COALESCE_WINDOW = 120       # seconds; repeats inside this window fold together
COALESCE_SCAN = 40          # only look this far up the list for a repeat

ROW_HEIGHT = 38             # tall enough to read, dense enough to scan
PILL_HEIGHT = 28            # header pills; a QLabel would otherwise stretch


# --------------------------------------------------------------------------
# settings - the file itself is handled by config.py, shared with the recorder
# --------------------------------------------------------------------------
DEFAULTS = config_mod.DEFAULTS
load_config = config_mod.load
save_config = config_mod.save
config_path = config_mod.path


def _make_show_event():
    """
    Event a second launch uses to say "you are already running, show
    yourself". Checked on the drain timer, which costs one non-blocking
    wait per tick.
    """
    try:
        import win32event

        return win32event.CreateEvent(None, True, False,
                                      "SystemWatchWindowShow")
    except Exception:
        return None


def ensure_recorder():
    """
    Start the headless recorder if it is not already running.

    The recorder is what makes detection survive this window being closed,
    so the window makes sure it exists rather than assuming it does. It is
    launched detached and windowless, so it keeps running after we quit and
    never flashes a console. A second copy cannot start - the recorder
    claims a named mutex - so calling this when one is already live is safe.
    """
    try:
        if recorder_mod.is_running():
            return True
        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        subprocess.Popen(
            startup_mod.command_for("recorder.py"),
            cwd=startup_mod.app_dir(),
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            close_fds=True,
        )
        return True
    except Exception:
        return False


def restart_recorder(after=None):
    """
    Stop the recorder and start a fresh one, so it re-reads its settings.

    The recorder blocks on a single wait with no timer, which is why it costs
    nothing - and also why it cannot notice a settings change on its own. A
    restart is the price of that, and only happens when the setting changes.
    Polls for the old copy to exit (its mutex lingers until it does) for up
    to five seconds without blocking the window, then starts the new one.
    """
    recorder_mod.request_stop()
    deadline = time.time() + 5.0

    def check():
        if recorder_mod.is_running() and time.time() < deadline:
            QTimer.singleShot(200, check)
            return
        ok = ensure_recorder()
        if after:
            after(ok)

    QTimer.singleShot(200, check)


def open_data_folder():
    """Show the folder holding settings and the records, in Explorer."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(config_mod.folder()))


def event_as_text(ev):
    """
    A selected event as plain text, for the clipboard.

    This is what someone pastes into a message to IT, so it leads with the
    plain-English part and keeps the identifiers they will ask for.
    """
    lines = [
        f"{ev['title']}",
        f"{SEVERITY_LABEL[ev['severity']]} · "
        f"{ev['time'].strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"What this means: {ev['meaning']}",
        f"What to do: {ev['action']}",
        "",
        f"Source: {ev['provider']}   Event ID: {ev['event_id']}   "
        f"Log: {ev['channel']}",
    ]
    if ev.get("count", 1) > 1:
        lines.append(f"Seen {ev['count']} times")
    raw = " ".join((ev.get("message") or "").split())
    if raw and not ev.get("verbatim"):
        lines += ["", f"Windows' message: {raw}"]
    return "\n".join(lines)


class InfoDialog(QDialog):
    """
    A short, styled message with one or two choices.

    Used for the first-run welcome and for About. A QMessageBox would do, but
    it ignores most of the stylesheet and cannot hold a checkbox neatly.
    """

    def __init__(self, title, heading, body_html, parent=None,
                 accept_text="OK", option=None, extra=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowIcon(shield_icon())
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(shield_icon().pixmap(36, 36))
        top.addWidget(logo, 0, Qt.AlignVCenter)
        name = QLabel(heading)
        name.setObjectName("appname")
        name.setWordWrap(True)
        top.addWidget(name, 1)
        layout.addLayout(top)

        body = QLabel(body_html)
        body.setWordWrap(True)
        body.setTextFormat(Qt.RichText)
        body.setOpenExternalLinks(False)
        body.setStyleSheet(f"color:{theme.TEXT_MED}; font-size:12px;")
        layout.addWidget(body)

        self.option = None
        if option:
            self.option = QCheckBox(option[0])
            self.option.setChecked(option[1])
            layout.addWidget(self.option)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        ok = buttons.button(QDialogButtonBox.Ok)
        ok.setText(accept_text)
        ok.setProperty("kind", "primary")
        ok.setCursor(Qt.PointingHandCursor)
        buttons.accepted.connect(self.accept)
        if extra:
            # A secondary action, e.g. "Project page". Opens only on click;
            # the app never reaches the network by itself.
            label, handler = extra
            more = buttons.addButton(label, QDialogButtonBox.ActionRole)
            more.setProperty("kind", "quiet")
            more.setCursor(Qt.PointingHandCursor)
            more.clicked.connect(handler)
        layout.addWidget(buttons)

    def option_checked(self):
        return self.option.isChecked() if self.option else None


def welcome_dialog(cfg, parent=None):
    """First launch: say plainly what is watched and recorded, and where."""
    body = (
        "<p>SystemWatch reads the Windows event log and explains what your "
        "PC is doing in plain English. It <b>only reads</b> — it cannot "
        "change, clear or switch off anything in Windows.</p>"
        "<p>A small background recorder also keeps a record on this PC of:"
        "<br>• devices plugged in and removed (USB drives, phones)"
        "<br>• programs you open and documents you open</p>"
        f"<p>It keeps the newest {history.MAX_ENTRIES} of each in your own "
        "user folder. Nothing is ever sent over the internet. You can change "
        "any of this later in <b>Settings</b>.</p>"
    )
    return InfoDialog(
        f"Welcome to {APP_NAME}", f"Welcome to {APP_NAME}", body, parent,
        accept_text="Get started",
        option=("Record the programs and documents I open",
                cfg["record_activity"]),
    )


def about_dialog(parent=None):
    keys = "".join(
        f"<tr><td width='96' style='color:{theme.TEXT_HI};'>{k}</td>"
        f"<td>{what}</td></tr>"
        for k, what in (
            ("Ctrl+F", "Search events (Esc clears the search)"),
            ("Ctrl+C", "Copy the selected event, ready to send to IT"),
            ("Ctrl+1 / 2 / 3", "Switch tab"),
            ("F5", "Refresh the current tab"),
            ("Ctrl+Comma", "Settings"),
            ("Ctrl+Q", "Quit completely"),
        )
    )
    body = (
        "<p>A read-only monitor for the Windows event log, devices, networks "
        "and the programs and documents you open.</p>"
        "<p>It never writes to Windows' logs or settings, and never sends "
        "anything over the network. Its own files are kept in:<br>"
        f"<span style='color:{theme.TEXT_HI};'>"
        f"{html.escape(config_mod.folder())}</span></p>"
        f"<p><b>Keyboard</b></p><table cellpadding='2'>{keys}</table>"
        f"<p style='color:{theme.TEXT_LOW}; font-size:11px;'>"
        f"{html.escape(COPYRIGHT)}. Free software under the "
        f"{LICENSE_NAME}: you may share and change it under its terms. "
        "It comes with NO WARRANTY.<br>"
        f"Source code: {html.escape(HOMEPAGE)}</p>"
    )
    return InfoDialog(
        f"About {APP_NAME}", f"{APP_NAME} {__version__}", body, parent,
        extra=("Project page",
               lambda: QDesktopServices.openUrl(QUrl(HOMEPAGE))),
    )


# --------------------------------------------------------------------------
# icon
# --------------------------------------------------------------------------
def shield_icon(color=None, size=64):
    color = color or theme.OK
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 64.0
    path = QPainterPath()
    path.moveTo(32 * s, 5 * s)
    path.lineTo(55 * s, 15 * s)
    path.lineTo(55 * s, 33 * s)
    path.quadTo(55 * s, 50 * s, 32 * s, 59 * s)
    path.quadTo(9 * s, 50 * s, 9 * s, 33 * s)
    path.lineTo(9 * s, 15 * s)
    path.closeSubpath()
    p.fillPath(path, QBrush(QColor(color)))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(theme.INK_0))
    p.drawEllipse(QRectF(27 * s, 20 * s, 10 * s, 10 * s))
    p.drawRoundedRect(
        QRectF(29 * s, 32 * s, 6 * s, 14 * s), 3 * s, 3 * s
    )
    p.end()
    return QIcon(pix)


# --------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------
def _time_font():
    """
    Tabular figures for the time column. Cascadia Mono ships with Windows 11
    but not every Windows 10, so Consolas (present since Vista) backs it up
    rather than letting Qt fall through to Courier.
    """
    font = QFont()
    font.setStyleHint(QFont.Monospace)
    font.setFamilies(["Cascadia Mono", "Consolas"])
    font.setPointSizeF(8.5)
    return font


_TIME_FONT = None   # built on first use - a QFont needs the QApplication
class EventModel(QAbstractTableModel):
    HEADERS = ["Time", "Severity", "Source", "What happened"]
    SEV_ROLE = Qt.UserRole + 1
    EVENT_ROLE = Qt.UserRole + 2

    def __init__(self):
        super().__init__()
        global _TIME_FONT
        if _TIME_FONT is None:
            _TIME_FONT = _time_font()
        self._rows = []      # newest first
        self._keys = []      # negative epoch times, parallel to _rows
        self._today = datetime.now().date()
        self.counts = {ERROR: 0, WARN: 0, INFO: 0}

    # -- Qt plumbing ---------------------------------------------------
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        ev = self._rows[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                # Backfilled events can predate today; don't imply "just now".
                if ev["time"].date() == self._today:
                    return ev["time"].strftime("%H:%M:%S")
                return ev["time"].strftime("%d %b  %H:%M")
            if col == 1:
                return SEVERITY_LABEL[ev["severity"]]
            if col == 2:
                return friendly_provider(ev["provider"])
            if col == 3:
                text = ev["title"]
                if ev.get("count", 1) > 1:
                    text += f"   ×{ev['count']}"
                return text

        elif role == Qt.ToolTipRole:
            if col == 0:
                return ev["time"].strftime("%d %b %Y  %H:%M:%S")
            if col == 2:
                return ev["provider"]
            return ev["meaning"]

        elif role == self.SEV_ROLE:
            return ev["severity"]

        elif role == self.EVENT_ROLE:
            return ev

        elif role == Qt.ForegroundRole:
            # The time and source columns sit one tier down so the headline
            # in column 3 is what the eye lands on. Both are TEXT_MED rather
            # than TEXT_LOW: on a selected row TEXT_LOW would fall to 4.2:1,
            # just under AA, while TEXT_MED holds 6.4:1.
            if col in (0, 2):
                return QColor(theme.TEXT_MED)
            return QColor(theme.TEXT_HI)

        elif role == Qt.TextAlignmentRole:
            return int(Qt.AlignVCenter | Qt.AlignLeft)

        elif role == Qt.FontRole and col == 0:
            return _TIME_FONT

        return None

    def recent(self, limit):
        """Newest-first slice of the retained events."""
        return self._rows[:limit]

    def event_at(self, row):
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    # -- ingestion -----------------------------------------------------
    def add_events(self, events):
        """Insert a batch, newest-first, folding together repeats."""
        self._today = datetime.now().date()
        added = 0
        for ev in events:
            key = -ev["time"].timestamp()

            if self._fold(ev):
                continue

            pos = bisect.bisect_left(self._keys, key)
            self.beginInsertRows(QModelIndex(), pos, pos)
            self._keys.insert(pos, key)
            ev["count"] = 1
            self._rows.insert(pos, ev)
            self.endInsertRows()
            self.counts[ev["severity"]] += 1
            added += 1

        self._trim()
        return added

    def _fold(self, ev):
        """Bump an existing near-identical row instead of adding a new one."""
        # Recorded device connections are never folded. Collapsing two
        # separate plug-ins into one row with a "x2" badge is right for log
        # chatter but wrong for a record of physical events - unplugging and
        # replugging a phone twice in a minute is two facts, not one, and the
        # record on disk keeps them separate too.
        if ev.get("provider") in ("Device recorder", "Activity recorder"):
            return False

        limit = min(COALESCE_SCAN, len(self._rows))
        for row in range(limit):
            old = self._rows[row]
            if (
                old["event_id"] == ev["event_id"]
                and old["provider"] == ev["provider"]
                and old["title"] == ev["title"]
                and abs((old["time"] - ev["time"]).total_seconds())
                <= COALESCE_WINDOW
            ):
                old["count"] = old.get("count", 1) + 1
                idx = self.index(row, 3)
                self.dataChanged.emit(idx, idx, [Qt.DisplayRole])
                return True
        return False

    def _trim(self):
        excess = len(self._rows) - MAX_RECORDS
        if excess <= 0:
            return
        first = len(self._rows) - excess
        self.beginRemoveRows(QModelIndex(), first, len(self._rows) - 1)
        for ev in self._rows[first:]:
            self.counts[ev["severity"]] = max(
                0, self.counts[ev["severity"]] - 1
            )
        del self._rows[first:]
        del self._keys[first:]
        self.endRemoveRows()

    def clear(self):
        self.beginResetModel()
        self._rows.clear()
        self._keys.clear()
        self.counts = {ERROR: 0, WARN: 0, INFO: 0}
        self.endResetModel()


class EventFilter(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.severities = {ERROR, WARN, INFO}
        self.text = ""
        self.hide_noisy = True

    def set_severities(self, severities):
        self.severities = set(severities)
        self.invalidateFilter()

    def set_text(self, text):
        self.text = text.strip().lower()
        self.invalidateFilter()

    def set_hide_noisy(self, hide):
        self.hide_noisy = bool(hide)
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        model = self.sourceModel()
        ev = model.event_at(row)
        if ev is None:
            return False
        if ev["severity"] not in self.severities:
            return False
        if self.hide_noisy and ev.get("noisy") and ev["severity"] == INFO:
            return False
        if self.text:
            haystack = (
                ev["title"] + " " + ev["meaning"] + " " + ev["provider"]
                + " " + str(ev["event_id"]) + " " + ev.get("message", "")
            ).lower()
            if self.text not in haystack:
                return False
        return True


class RowDelegate(QStyledItemDelegate):
    """
    Paints the chrome shared by every cell in a row, then lets Qt draw the
    text on top of it.

    Qt has no row-level hover: `QTableView::item:hover` in a stylesheet lights
    up the single cell under the pointer, which on a four-column row looks
    like a rendering fault rather than a highlight. Painting the background
    here, from one delegate installed on the whole view, is what makes hover
    and selection span the row.
    """

    def __init__(self, view):
        super().__init__(view)
        self._view = view

    def _row_chrome(self, painter, option, index):
        rect = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        hovered = index.row() == self._view.hover_row

        if selected:
            painter.fillRect(rect, QColor(theme.SEL_BG))
        elif hovered:
            painter.fillRect(rect, QColor(theme.HOVER_BG))

        painter.setPen(QColor(theme.ROW_LINE))
        painter.drawLine(
            rect.left(), rect.bottom(), rect.right(), rect.bottom()
        )

        # The selection rail is drawn on the first column only. Drawing it
        # per cell would stripe it across every column boundary.
        if selected and index.column() == 0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme.ACCENT))
            painter.drawRoundedRect(
                QRectF(rect.left(), rect.top() + 6, 3.0, rect.height() - 12),
                1.5, 1.5,
            )

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        self._row_chrome(painter, option, index)
        painter.restore()

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        # The row background is already down. Clearing these stops the style
        # from painting its own selection block over the top of it.
        opt.state &= ~QStyle.State_Selected
        opt.state &= ~QStyle.State_MouseOver
        opt.backgroundBrush = QBrush(Qt.NoBrush)
        super().paint(painter, opt, index)

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), ROW_HEIGHT)


class SeverityDelegate(RowDelegate):
    """Draws the severity cell as a small coloured pill."""

    def paint(self, painter, option, index):
        sev = index.data(EventModel.SEV_ROLE) or INFO
        colour = QColor(SEVERITY_COLOR[sev])

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        self._row_chrome(painter, option, index)

        rect = QRectF(option.rect)
        pill = QRectF(rect.left() + 6, rect.center().y() - 9, 76, 19)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.WASH[sev]))
        painter.drawRoundedRect(pill, 9.5, 9.5)

        painter.setPen(QColor(theme.EDGE[sev]))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(pill.adjusted(0.5, 0.5, -0.5, -0.5), 9.5, 9.5)

        painter.setPen(Qt.NoPen)
        painter.setBrush(colour)
        painter.drawEllipse(
            QRectF(pill.left() + 9, pill.center().y() - 3, 6, 6)
        )

        painter.setPen(colour)
        font = painter.font()
        font.setPointSizeF(8.0)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            pill.adjusted(22, 0, 0, 0),
            Qt.AlignVCenter | Qt.AlignLeft,
            SEVERITY_LABEL[sev],
        )
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(96, ROW_HEIGHT)


class EventTable(QTableView):
    """
    The event list.

    Adds two things a plain QTableView has no notion of: which row the
    pointer is over, and what to say when there is nothing to show.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hover_row = -1
        self.empty_title = "Waiting for activity"
        self.empty_body = "Events appear here as Windows records them."
        # Both are needed. A QAbstractScrollArea delivers mouse events through
        # its viewport child, so tracking set on the view alone never reaches
        # the code below - which is exactly why the first version of this
        # painted no hover at all despite the delegate being correct.
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def _set_hover(self, row):
        if row != self.hover_row:
            self.hover_row = row
            self.viewport().update()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self._set_hover(self.indexAt(event.pos()).row())

    def leaveEvent(self, event):
        self._set_hover(-1)
        super().leaveEvent(event)

    def set_empty_state(self, title, body):
        if (title, body) != (self.empty_title, self.empty_body):
            self.empty_title = title
            self.empty_body = body
            self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        model = self.model()
        if model is not None and model.rowCount():
            return

        # An empty table that draws nothing reads as a broken window. Saying
        # which of the several possible reasons applies is the difference
        # between "no results" and "is this thing on?".
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)
        area = self.viewport().rect()

        font = QFont(painter.font())
        font.setPointSizeF(10.5)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(theme.TEXT_MED))
        painter.drawText(
            area.adjusted(24, 0, -24, -26),
            Qt.AlignCenter | Qt.TextWordWrap,
            self.empty_title,
        )

        font.setPointSizeF(9.0)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor(theme.TEXT_LOW))
        painter.drawText(
            area.adjusted(48, 30, -48, 0),
            Qt.AlignHCenter | Qt.AlignVCenter | Qt.TextWordWrap,
            self.empty_body,
        )
        painter.end()


# --------------------------------------------------------------------------
# settings dialog
# --------------------------------------------------------------------------
class SettingsDialog(QDialog):
    def __init__(self, cfg, access, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SystemWatch settings")
        self.setMinimumWidth(640)
        self.setWindowIcon(shield_icon())
        self.cfg = cfg

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(10)

        # --- what to watch ---------------------------------------------
        layout.addWidget(self._heading("What to watch"))
        channels_card, channels_body = self._card()
        self.channel_boxes = {}
        # Two columns: nine logs in one column made this dialog taller than
        # a 768-pixel laptop screen once the privacy section was added.
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(9)
        half = (len(CHANNELS) + 1) // 2
        for index, (name, meta) in enumerate(CHANNELS.items()):
            # A single "&" would be swallowed as a mnemonic, the same way it
            # is in a tab title. Five channel names contain one.
            box = QCheckBox(meta["label"].replace("&", "&&"))
            box.setChecked(name in cfg["channels"])
            if not access.get(name, False):
                box.setEnabled(False)
                box.setChecked(False)
                # Said in the tooltip and the accessible description rather
                # than glued onto the label, so the option still reads as
                # its name.
                why = (
                    "Needs Administrator" if meta["needs_admin"]
                    else "Not available on this PC"
                )
                box.setText(box.text() + "  —  " + why.lower())
                box.setToolTip(why)
            self.channel_boxes[name] = box
            grid.addWidget(box, index % half, index // half)
        channels_body.addLayout(grid)
        layout.addWidget(channels_card)

        # --- behaviour --------------------------------------------------
        layout.addSpacing(4)
        layout.addWidget(self._heading("Behaviour"))
        behaviour_card, behaviour_body = self._card()

        self.noisy = QCheckBox("Hide routine background chatter")
        self.noisy.setChecked(cfg["hide_noisy"])
        behaviour_body.addWidget(self.noisy)

        self.notify = QCheckBox("Show a notification for red (Error) events")
        self.notify.setChecked(cfg["notify_errors"])
        behaviour_body.addWidget(self.notify)

        self.tray_close = QCheckBox("Closing the window keeps it in the tray")
        self.tray_close.setChecked(cfg["minimize_to_tray"])
        behaviour_body.addWidget(self.tray_close)

        self.autostart = QCheckBox(
            "Start SystemWatch in the tray when I sign in to Windows"
        )
        self.autostart.setChecked(startup_mod.is_enabled())
        behaviour_body.addWidget(self.autostart)

        self.autorecord = QCheckBox(
            "Keep recording in the background, even when this window is "
            "closed"
        )
        self.autorecord.setChecked(startup_mod.recorder_is_enabled())
        behaviour_body.addWidget(self.autorecord)

        row = QHBoxLayout()
        row.setContentsMargins(0, 6, 0, 0)
        caption = QLabel("Recent events to load on launch")
        caption.setObjectName("fieldLabel")
        row.addWidget(caption)
        row.addStretch(1)
        self.backfill = QSpinBox()
        self.backfill.setRange(0, 200)
        self.backfill.setValue(cfg["backfill"])
        self.backfill.setFixedWidth(78)
        row.addWidget(self.backfill)
        behaviour_body.addLayout(row)
        layout.addWidget(behaviour_card)

        # --- privacy ----------------------------------------------------
        layout.addSpacing(4)
        layout.addWidget(self._heading("Privacy"))
        privacy_card, privacy_body = self._card()
        self.record_activity = QCheckBox(
            "Record the programs I open and the documents I open"
        )
        self.record_activity.setChecked(cfg["record_activity"])
        privacy_body.addWidget(self.record_activity)
        privacy_note = QLabel(
            "Kept only on this PC, in your own user folder, newest "
            f"{history.MAX_ENTRIES} of each. Nothing is ever sent anywhere."
        )
        privacy_note.setObjectName("fieldLabel")
        privacy_note.setWordWrap(True)
        privacy_note.setStyleSheet(f"color:{theme.TEXT_LOW}; font-size:11px;")
        privacy_body.addWidget(privacy_note)
        layout.addWidget(privacy_card)

        # --- read-only assurance ----------------------------------------
        note_frame = QFrame()
        note_frame.setObjectName("settingsNote")
        note_layout = QHBoxLayout(note_frame)
        note_layout.setContentsMargins(12, 10, 12, 10)
        note = QLabel(
            "SystemWatch only ever reads. It cannot clear, edit or "
            "reconfigure any Windows log."
        )
        note.setObjectName("settingsNoteText")
        note.setWordWrap(True)
        note_layout.addWidget(note)
        layout.addSpacing(4)
        layout.addWidget(note_frame)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        ok = buttons.button(QDialogButtonBox.Ok)
        ok.setText("Save")
        ok.setProperty("kind", "primary")
        ok.setCursor(Qt.PointingHandCursor)
        buttons.button(QDialogButtonBox.Cancel).setCursor(
            Qt.PointingHandCursor
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        # Version and data folder sit at the left of the button row, where
        # they are findable without competing with Save.
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        folder_btn = QPushButton("Open data folder")
        folder_btn.setProperty("kind", "quiet")
        folder_btn.setCursor(Qt.PointingHandCursor)
        folder_btn.setToolTip(config_mod.folder())
        folder_btn.clicked.connect(open_data_folder)
        footer.addWidget(folder_btn)
        version = QLabel(f"{APP_NAME} {__version__}")
        version.setObjectName("fieldLabel")
        version.setStyleSheet(f"color:{theme.TEXT_LOW}; font-size:11px;")
        footer.addWidget(version)
        footer.addStretch(1)
        footer.addWidget(buttons)
        layout.addSpacing(2)
        layout.addLayout(footer)

    def _card(self):
        """An elevated group box. Returns (frame, layout to fill)."""
        frame = QFrame()
        frame.setObjectName("settingsCard")
        body = QVBoxLayout(frame)
        body.setContentsMargins(14, 12, 14, 12)
        body.setSpacing(9)
        return frame, body

    def _heading(self, text):
        label = QLabel(theme.spaced(text.upper()))
        label.setObjectName("groupHeading")
        return label

    def result_config(self):
        cfg = dict(self.cfg)
        cfg["channels"] = [
            name for name, box in self.channel_boxes.items()
            if box.isChecked() and box.isEnabled()
        ]
        cfg["hide_noisy"] = self.noisy.isChecked()
        cfg["notify_errors"] = self.notify.isChecked()
        cfg["minimize_to_tray"] = self.tray_close.isChecked()
        cfg["backfill"] = self.backfill.value()
        cfg["record_activity"] = self.record_activity.isChecked()
        return cfg

    def wants_autostart(self):
        return self.autostart.isChecked()

    def wants_recorder(self):
        return self.autorecord.isChecked()


# --------------------------------------------------------------------------
# main window
# --------------------------------------------------------------------------
class MainWindow(QWidget):
    quit_requested = pyqtSignal()

    def __init__(self, start_hidden=False):
        super().__init__()
        self.cfg = load_config()
        self.access = readable_channels()
        self.watcher = EventWatcher()
        # Devices are NOT watched here. The background recorder owns that job
        # and writes every plug and unplug to the permanent record, running
        # whether or not this window exists. Reading its record instead of
        # duplicating the detection means connections that happened while the
        # window was closed still show up in the list when it reopens - and
        # there is exactly one detector, so nothing is counted twice.
        self._history_seen = set()
        self._history_sig = None
        self._activity_seen = set()
        self._activity_sig = None
        self._show_event = _make_show_event()
        self.paused = False
        self._last_notify = 0.0
        self._proc = None
        try:
            import psutil

            self._proc = psutil.Process()
            self._proc.cpu_percent(None)
            self._cpu_count = psutil.cpu_count() or 1
        except Exception:
            self._cpu_count = 1

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(shield_icon())
        self.resize(1140, 720)
        self.setMinimumSize(880, 520)

        self._build_ui()
        self._apply_style()
        self._build_tray()

        self._start_monitoring(first_run=True)
        self.recorder_ok = ensure_recorder()
        self._seed_from_record()

        self.drain_timer = QTimer(self)
        self.drain_timer.timeout.connect(self._drain)
        self.drain_timer.start(DRAIN_MS)

        self.stat_timer = QTimer(self)
        self.stat_timer.timeout.connect(self._update_stats)
        self.stat_timer.start(5000)

        self._build_shortcuts()
        self._restore_layout()

        if not start_hidden:
            self.show()
            QTimer.singleShot(250, self._maybe_welcome)

    # -- first run, layout memory, keyboard -------------------------------
    def _maybe_welcome(self):
        """Explain what is recorded, once, the first time the window shows."""
        if self.cfg.get("welcomed") or getattr(self, "_welcoming", False):
            return
        self._welcoming = True
        dialog = welcome_dialog(self.cfg, self)
        dialog.exec_()
        self._welcoming = False
        self.cfg["welcomed"] = True
        wanted = dialog.option_checked()
        changed = wanted is not None and wanted != self.cfg["record_activity"]
        self.cfg["record_activity"] = bool(wanted)
        save_config(self.cfg)
        if changed:
            restart_recorder()
            self.activity_panel.mark_dirty()

    def _restore_layout(self):
        """Put the window and the list/detail split back where they were."""
        try:
            if self.cfg.get("geometry"):
                self.restoreGeometry(
                    QByteArray.fromHex(self.cfg["geometry"].encode("ascii"))
                )
            if self.cfg.get("splitter"):
                self.splitter.restoreState(
                    QByteArray.fromHex(self.cfg["splitter"].encode("ascii"))
                )
        except Exception:
            pass

    def _remember_layout(self):
        self.cfg["geometry"] = bytes(self.saveGeometry().toHex()).decode()
        self.cfg["splitter"] = bytes(self.splitter.saveState().toHex()).decode()

    def _build_shortcuts(self):
        def bind(keys, handler):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(handler)

        bind("Ctrl+F", self._focus_search)
        bind("Ctrl+C", self._copy_selected)
        bind("Ctrl+,", self.open_settings)
        bind("Ctrl+Q", self.quit_app)
        bind("F5", self._refresh_current)
        bind("F1", self.show_about)
        for number in range(3):
            bind(f"Ctrl+{number + 1}",
                 lambda n=number: self.tabs.setCurrentIndex(n))

    def _focus_search(self):
        self.tabs.setCurrentIndex(0)
        self.search.setFocus(Qt.ShortcutFocusReason)
        self.search.selectAll()

    def _refresh_current(self):
        page = self.tabs.currentWidget()
        if hasattr(page, "refresh"):
            page.refresh()

    def _selected_event(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.model.event_at(self.proxy.mapToSource(rows[0]).row())

    def _copy_selected(self):
        # Ctrl+C inside the search box or the detail pane keeps its normal
        # meaning: copy the text selected there.
        focus = QApplication.focusWidget()
        if focus is self.search or focus is self.detail:
            focus.copy()
            return
        event = self._selected_event()
        if event:
            QApplication.clipboard().setText(event_as_text(event))
            self.status_left.setText("Copied the selected event to the clipboard")
            QTimer.singleShot(2500, self._update_status_text)

    def _table_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        self.table.selectRow(index.row())
        event = self._selected_event()
        if not event:
            return
        menu = QMenu(self)
        copy = menu.addAction("Copy details")
        copy.setShortcut(QKeySequence("Ctrl+C"))
        copy.triggered.connect(self._copy_selected)
        title = menu.addAction("Copy title")
        title.triggered.connect(
            lambda: QApplication.clipboard().setText(event["title"])
        )
        menu.addSeparator()
        similar = menu.addAction("Show only events like this")
        similar.triggered.connect(
            lambda: self.search.setText(str(event["title"]))
        )
        menu.exec_(self.table.viewport().mapToGlobal(pos))

    def show_about(self):
        about_dialog(self).exec_()

    # -- construction ---------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Model and proxy first - the filter bar wires straight into them.
        self.model = EventModel()
        self.proxy = EventFilter()
        self.proxy.setSourceModel(self.model)
        self.proxy.set_hide_noisy(self.cfg["hide_noisy"])

        root.addWidget(self._build_header())

        self.tabs = QTabWidget()
        self.tabs.setObjectName("tabs")

        events_tab = QWidget()
        events_layout = QVBoxLayout(events_tab)
        events_layout.setContentsMargins(0, 0, 0, 0)
        events_layout.setSpacing(0)
        events_layout.addWidget(self._build_filterbar())

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("splitter")
        splitter.setHandleWidth(1)

        self.table = EventTable()
        self.table.setModel(self.proxy)
        self.table.setObjectName("table")
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.StrongFocus)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(False)
        # One delegate for the whole view paints hover and selection across
        # the full row; the severity column swaps in a subclass that also
        # draws the pill.
        self.table.setItemDelegate(RowDelegate(self.table))
        self.table.setItemDelegateForColumn(1, SeverityDelegate(self.table))

        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setFixedHeight(34)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        # Source is the one column worth resizing by hand: provider names
        # range from "Kernel-Power" to the full Defender path.
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setStretchLastSection(True)
        header.setMinimumSectionSize(72)
        self.table.setColumnWidth(0, 92)
        self.table.setColumnWidth(1, 104)
        self.table.setColumnWidth(2, 176)

        self.table.selectionModel().selectionChanged.connect(self._on_select)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self.table.setAccessibleName("Event list")
        self.table.setAccessibleDescription(
            "Newest first. Select an event to read its explanation. "
            "Ctrl+C copies it."
        )

        self.detail = QTextBrowser()
        self.detail.setObjectName("detail")
        self.detail.setOpenExternalLinks(False)
        self.detail.setOpenLinks(False)
        self.detail.setAccessibleName("Event explanation")
        self._show_placeholder()

        self.splitter = splitter
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([660, 480])
        events_layout.addWidget(splitter, 1)
        self.tabs.addTab(events_tab, "Live events")

        self.device_panel = DevicePanel(self._recent_events)
        self.tabs.addTab(self.device_panel, "Devices && Network")

        self.activity_panel = ActivityPanel()
        self.tabs.addTab(self.activity_panel, "Programs && Files")

        root.addWidget(self.tabs, 1)
        root.addWidget(self._build_statusbar())

    def _recent_events(self, limit=500):
        """Newest-first events, for the Devices & Network tab to read."""
        return self.model.recent(limit)

    def _build_header(self):
        bar = QFrame()
        bar.setObjectName("header")
        bar.setFixedHeight(66)
        row = QHBoxLayout(bar)
        row.setContentsMargins(18, 0, 16, 0)
        row.setSpacing(14)

        logo = QLabel()
        logo.setPixmap(shield_icon().pixmap(28, 28))
        row.addWidget(logo)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        name = QLabel(APP_NAME)
        name.setObjectName("appname")
        sub = QLabel("Read-only system monitor")
        sub.setObjectName("appsub")
        titles.addWidget(name)
        titles.addWidget(sub)
        row.addLayout(titles)

        row.addSpacing(10)
        self.status_pill = QLabel("●  Monitoring")
        self.status_pill.setObjectName("statuspill")
        self.status_pill.setProperty("state", "live")
        self.status_pill.setFixedHeight(PILL_HEIGHT)
        row.addWidget(self.status_pill)

        row.addStretch(1)

        self.count_error = self._counter(0, ERROR)
        self.count_warn = self._counter(0, WARN)
        self.count_info = self._counter(0, INFO)
        for widget in (self.count_error, self.count_warn, self.count_info):
            row.addWidget(widget)
            row.addSpacing(6)

        row.addSpacing(4)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setCursor(Qt.PointingHandCursor)
        self.pause_btn.setToolTip(
            "Stop taking in new events. Nothing is read while paused."
        )
        self.pause_btn.clicked.connect(self.toggle_pause)
        row.addWidget(self.pause_btn)

        settings_btn = QPushButton("Settings")
        settings_btn.setCursor(Qt.PointingHandCursor)
        settings_btn.clicked.connect(self.open_settings)
        row.addWidget(settings_btn)

        return bar

    @staticmethod
    def _counter_text(count, severity):
        """"3 errors" / "1 warning" - a chip should never read "1 errors"."""
        word = SEVERITY_LABEL[severity].lower()
        if severity != INFO and count != 1:
            word += "s"
        return f"●  {count}  {word}"

    def _counter(self, count, severity):
        """
        A severity tally.

        Styled entirely from the stylesheet rather than an inline
        setStyleSheet, so it can carry hover and state variants and so the
        palette stays in one file. The chip greys out at zero: three lit
        chips when two of them mean nothing is just noise.
        """
        label = QLabel(self._counter_text(count, severity))
        label.setToolTip(
            f"{SEVERITY_LABEL[severity]} events currently in the list, "
            "whether or not they are filtered out"
        )
        label.setObjectName("counter")
        label.setProperty("sev", severity)
        label.setProperty("active", "false")
        label.setFixedHeight(PILL_HEIGHT)
        return label

    def _build_filterbar(self):
        bar = QFrame()
        bar.setObjectName("filterbar")
        bar.setFixedHeight(50)
        row = QHBoxLayout(bar)
        row.setContentsMargins(18, 0, 16, 0)
        row.setSpacing(8)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search events…   Ctrl+F")
        self.search.setObjectName("search")
        self.search.setAccessibleName("Search events")
        self.search.setFixedWidth(268)
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip(
            "Searches the title, explanation, source, event ID and the "
            "original Windows text."
        )
        self.search.textChanged.connect(self._on_search)
        # Esc in the box clears it - the quickest way back to everything.
        clear_search = QShortcut(QKeySequence("Esc"), self.search)
        clear_search.setContext(Qt.WidgetShortcut)
        clear_search.activated.connect(self.search.clear)
        row.addWidget(self.search)

        row.addSpacing(6)
        self.chips = {}
        for severity in (ERROR, WARN, INFO):
            chip = QPushButton(SEVERITY_LABEL[severity])
            chip.setCheckable(True)
            chip.setChecked(True)
            chip.setCursor(Qt.PointingHandCursor)
            chip.setObjectName("chip")
            chip.setProperty("sev", severity)
            chip.clicked.connect(self._sync_chips)
            self.chips[severity] = chip
            row.addWidget(chip)

        row.addSpacing(12)
        self.noisy_box = QCheckBox("Hide routine chatter")
        self.noisy_box.setChecked(self.cfg["hide_noisy"])
        self.noisy_box.setCursor(Qt.PointingHandCursor)
        self.noisy_box.setToolTip(
            "Hides the noisiest housekeeping events — service start and "
            "stop, power-state bookkeeping, the harmless DCOM 10016 warning."
        )
        self.noisy_box.stateChanged.connect(self._toggle_noisy)
        row.addWidget(self.noisy_box)

        row.addStretch(1)

        clear = QPushButton("Clear view")
        clear.setProperty("kind", "quiet")
        clear.setCursor(Qt.PointingHandCursor)
        clear.setToolTip(
            "Clears this window only. Windows' own logs are never touched."
        )
        clear.clicked.connect(self._clear_view)
        row.addWidget(clear)

        return bar

    def _build_statusbar(self):
        bar = QFrame()
        bar.setObjectName("statusbar")
        bar.setFixedHeight(32)
        row = QHBoxLayout(bar)
        row.setContentsMargins(18, 0, 16, 0)

        self.status_left = QLabel("Starting…")
        self.status_left.setSizePolicy(
            QSizePolicy.Minimum, QSizePolicy.Fixed
        )
        self.status_left.setObjectName("statustext")
        row.addWidget(self.status_left)
        row.addStretch(1)
        self.status_right = QLabel("")
        self.status_right.setObjectName("statustext")
        row.addWidget(self.status_right)
        return bar

    def _build_tray(self):
        self.tray = QSystemTrayIcon(shield_icon(), self)
        self.tray.setToolTip(f"{APP_NAME} — monitoring")

        menu = QMenu()

        # A non-interactive first line, so right-clicking the tray icon
        # answers "is it running?" without opening the window.
        self.act_state = QAction("Monitoring — read-only", self)
        self.act_state.setEnabled(False)
        menu.addAction(self.act_state)
        menu.addSeparator()

        self.act_show = QAction("Open SystemWatch", self)
        self.act_show.setIcon(shield_icon())
        self.act_show.triggered.connect(self._restore)
        menu.addAction(self.act_show)

        self.act_pause = QAction("Pause monitoring", self)
        self.act_pause.triggered.connect(self.toggle_pause)
        menu.addAction(self.act_pause)

        act_settings = QAction("Settings…", self)
        act_settings.triggered.connect(self._settings_from_tray)
        menu.addAction(act_settings)

        act_about = QAction("About SystemWatch", self)
        act_about.triggered.connect(self.show_about)
        menu.addAction(act_about)

        menu.addSeparator()
        act_quit = QAction("Quit SystemWatch", self)
        act_quit.triggered.connect(self.quit_app)
        menu.addAction(act_quit)

        self.tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        # Clicking an error notification should land on that error, not
        # just open the window wherever it was.
        self.tray.messageClicked.connect(self._notification_clicked)
        self.tray.show()

    # -- styling ---------------------------------------------------------
    def _apply_style(self):
        """
        One stylesheet for the whole application.

        Set on the application rather than this window: the tray menu has
        no parent widget and message boxes are top-level, so a sheet set on
        the window never reached either and they drew in stock Windows grey.
        Every value comes from theme.py - there are no colours written down
        in this file.
        """
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.qss())
        else:
            self.setStyleSheet(theme.qss())

    # -- monitoring ------------------------------------------------------
    def _start_monitoring(self, first_run=False):
        wanted = [
            channel for channel in self.cfg["channels"]
            if self.access.get(channel, False)
        ]
        self.watcher.set_channels(wanted)
        if first_run and self.cfg["backfill"]:
            self.watcher.backfill_async(wanted, self.cfg["backfill"])
        self._update_status_text()

    @staticmethod
    def _repolish(widget):
        """Re-evaluate a widget's stylesheet after a dynamic property change.

        Qt caches the resolved style per widget; changing a property that a
        selector depends on does nothing visible until the widget is
        unpolished and polished again.
        """
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def toggle_pause(self):
        self.paused = not self.paused
        if self.paused:
            self.watcher.pause()
            self.pause_btn.setText("Resume")
            # Resume becomes the call to action while paused, so it takes
            # the accent fill. A permanently filled Pause button would put
            # the loudest thing on screen on the control you least want.
            self.pause_btn.setProperty("kind", "primary")
            self.act_pause.setText("Resume monitoring")
            self.act_state.setText("Paused — nothing is being read")
            self.status_pill.setText("●  Paused")
            self.status_pill.setProperty("state", "paused")
            self.tray.setIcon(shield_icon(theme.TEXT_LOW))
            self.tray.setToolTip(f"{APP_NAME} — paused")
        else:
            self.watcher.resume()
            self._start_monitoring()
            self.pause_btn.setText("Pause")
            self.pause_btn.setProperty("kind", "")
            self.act_pause.setText("Pause monitoring")
            self.act_state.setText("Monitoring — read-only")
            self.status_pill.setText("●  Monitoring")
            self.status_pill.setProperty("state", "live")
            self.tray.setIcon(shield_icon())
            self.tray.setToolTip(f"{APP_NAME} — monitoring")
        self._repolish(self.status_pill)
        self._repolish(self.pause_btn)
        self._update_status_text()

    def _check_show_request(self):
        """A second launch asked us to come to the front."""
        if not self._show_event:
            return
        try:
            import win32event

            if win32event.WaitForSingleObject(self._show_event, 0) == \
                    win32event.WAIT_OBJECT_0:
                win32event.ResetEvent(self._show_event)
                self._restore()
        except Exception:
            pass

    def _drain(self):
        self._check_show_request()
        events = []
        if self.watcher.backlog:
            events = self.watcher.drain(DRAIN_LIMIT)

        # Device connections, programs and files all come from the
        # recorder's permanent records.
        events.extend(self._new_record_events())
        events.extend(self._new_activity_events())

        if not events:
            return

        at_top = self.table.verticalScrollBar().value() == 0
        had_selection = self.table.selectionModel().hasSelection()

        self.model.add_events(events)

        if at_top:
            self.table.verticalScrollBar().setValue(0)
        if not had_selection and self.proxy.rowCount():
            self.table.selectRow(0)

        self._update_counters()
        self._update_status_text()

        # Anything that changes what is plugged in, or which network we are
        # on, makes the Devices & Network tab stale.
        if any(
            e.get("kind") in ("device", "network") and not e.get("noisy")
            for e in events
        ):
            self.device_panel.mark_dirty()

        if self.cfg["notify_errors"]:
            worst = [
                e for e in events
                if e["severity"] == ERROR and not e.get("historical")
            ]
            now = time.time()
            if worst and now - self._last_notify > 30:
                self._last_notify = now
                event = worst[0]
                self.tray.showMessage(
                    event["title"],
                    event["meaning"][:180],
                    QSystemTrayIcon.Warning,
                    6000,
                )

    def _seed_from_record(self):
        """
        Load everything the recorder captured - including while this window
        was closed - so the list is populated the moment it opens.
        """
        try:
            entries, status = history.load()
        except Exception:
            return
        self._history_sig = history.signature()
        seeded = []
        for entry in entries:
            seq = entry.get("seq")
            if seq in self._history_seen:
                continue
            self._history_seen.add(seq)
            try:
                seeded.append(history.as_event(entry))
            except Exception:
                pass

        # The programs-and-files record is seeded the same way, so opening
        # the window shows what ran while it was closed.
        try:
            acts, _ = history.load_activity()
            self._activity_sig = history.activity_signature()
            for entry in acts:
                seq = entry.get("seq")
                if seq in self._activity_seen:
                    continue
                self._activity_seen.add(seq)
                seeded.append(history.activity_as_event(entry))
        except Exception:
            pass

        if seeded:
            self.model.add_events(seeded)
            self._update_counters()
        self._record_status = status

    def _new_record_events(self):
        """
        Pick up anything the recorder has written since we last looked.

        Costs one stat() per tick unless the file actually changed, so
        polling here is far cheaper than re-parsing.
        """
        if self.paused:
            return []
        signature = history.signature()
        if signature == self._history_sig:
            return []
        self._history_sig = signature

        try:
            entries, status = history.load()
        except Exception:
            return []
        self._record_status = status

        fresh = []
        for entry in entries:
            seq = entry.get("seq")
            if seq in self._history_seen:
                continue
            self._history_seen.add(seq)
            try:
                fresh.append(history.as_event(entry))
            except Exception:
                pass
        return fresh

    def _new_activity_events(self):
        """Programs and files the recorder has written since we last looked."""
        if self.paused:
            return []
        signature = history.activity_signature()
        if signature == self._activity_sig:
            return []
        self._activity_sig = signature

        try:
            entries, _ = history.load_activity()
        except Exception:
            return []

        fresh = []
        for entry in entries:
            seq = entry.get("seq")
            if seq in self._activity_seen:
                continue
            self._activity_seen.add(seq)
            try:
                fresh.append(history.activity_as_event(entry))
            except Exception:
                pass
        if fresh:
            self.activity_panel.mark_dirty()
        return fresh

    def _update_counters(self):
        counts = self.model.counts
        for widget, severity in (
            (self.count_error, ERROR),
            (self.count_warn, WARN),
            (self.count_info, INFO),
        ):
            count = counts[severity]
            widget.setText(self._counter_text(count, severity))
            active = "true" if count else "false"
            if widget.property("active") != active:
                widget.setProperty("active", active)
                self._repolish(widget)

    def _update_status_text(self):
        watching = [
            CHANNELS[c]["label"] for c in self.cfg["channels"]
            if self.access.get(c, False)
        ]
        state = (
            "Paused · not reading" if self.paused
            else "Read-only · watching"
        )

        # Naming every channel crowds out the event count once more than a
        # handful are on, so summarise and put the full list in the tooltip.
        if not watching:
            names = "nothing selected"
        elif len(watching) <= 3:
            names = ", ".join(watching)
        else:
            names = f"{len(watching)} logs"

        showing = self.proxy.rowCount()
        total = self.model.rowCount()
        text = f"{state} {names}   ·   showing {showing} of {total} events"
        if not is_admin() and "Security" in self.cfg["channels"]:
            text += "   ·   sign-in events need Administrator"
        self.status_left.setText(text)
        self.status_left.setToolTip(
            "Watching: " + ", ".join(watching) if watching else ""
        )
        self._update_empty_state()

    def _on_search(self, text):
        self.proxy.set_text(text)
        self._update_status_text()

    def _update_empty_state(self):
        """
        Decide what the table should say when it has no rows to draw.

        There are four quite different reasons the list can be empty and
        only one of them is "nothing has happened yet". Saying which one
        applies is the difference between a working filter and an app that
        looks broken.
        """
        if self.model.rowCount() == 0:
            watching = [
                c for c in self.cfg["channels"] if self.access.get(c, False)
            ]
            if not watching:
                title = "No logs are being watched"
                body = ("Open Settings and tick at least one log for events "
                        "to appear here.")
            elif self.paused:
                title = "Monitoring is paused"
                body = ("Nothing is being read from Windows. Press Resume "
                        "in the top right to start again.")
            else:
                title = "Waiting for activity"
                body = ("Events appear here the moment Windows records "
                        "them. A quiet machine is a good sign.")
        elif self.proxy.rowCount() == 0:
            query = self.search.text().strip()
            if query:
                title = f"Nothing matches “{query}”"
                body = ("Try a shorter search, or clear the box to see "
                        "everything again.")
            else:
                title = "Everything is filtered out"
                body = ("Switch a severity chip back on, or untick "
                        "“Hide routine chatter”.")
        else:
            return
        self.table.set_empty_state(title, body)

    def _update_stats(self):
        if not self._proc:
            return
        try:
            cpu = self._proc.cpu_percent(None) / max(1, self._cpu_count)
            ram = self._proc.memory_info().rss / (1024 * 1024)
            dropped = self.watcher.dropped
            extra = f"   ·   {dropped} dropped" if dropped else ""
            self.status_right.setText(
                f"this app: {cpu:.1f}% CPU · {ram:.0f} MB RAM{extra}"
            )
        except Exception:
            pass

    # -- interaction -----------------------------------------------------
    def _sync_chips(self):
        active = {s for s, chip in self.chips.items() if chip.isChecked()}
        if not active:                      # never leave the view empty
            self.chips[INFO].setChecked(True)
            active = {INFO}
        self.proxy.set_severities(active)
        self._update_status_text()

    def _toggle_noisy(self, state):
        hide = bool(state)
        self.cfg["hide_noisy"] = hide
        self.proxy.set_hide_noisy(hide)
        save_config(self.cfg)
        self._update_status_text()

    def _clear_view(self):
        self.model.clear()
        self._update_counters()
        self._show_placeholder()
        self._update_status_text()

    def _on_select(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        source = self.proxy.mapToSource(rows[0])
        event = self.model.event_at(source.row())
        if event:
            self.detail.setHtml(self._detail_html(event))

    def _show_placeholder(self):
        """What the detail pane shows before anything is selected."""
        legend = "".join(
            f'<tr>'
            f'<td width="14" valign="top">'
            f'<span style="color:{SEVERITY_COLOR[sev]}; font-size:15px;">'
            f"\u25cf</span></td>"
            f'<td style="font-size:12px; color:{theme.TEXT_MED};">'
            f'<b style="color:{SEVERITY_COLOR[sev]};">{name}</b> \u2014 {what}'
            f"</td></tr>"
            for sev, name, what in (
                (INFO, "Green", "normal, nothing to do."),
                (WARN, "Yellow", "worth a glance if it repeats."),
                (ERROR, "Red", "something failed \u2014 read the advice."),
            )
        )
        self.detail.setHtml(theme.page(
            theme.card(
                f'<div style="font-family:{theme.FONT_DISPLAY}; '
                f'font-size:15px; color:{theme.TEXT_HI};">'
                f"<b>Nothing selected</b></div>"
                f'<div style="font-size:12.5px; color:{theme.TEXT_MED}; '
                f'margin-top:6px;">Pick an event on the left and this panel '
                f"will explain, in plain English, what it means and whether "
                f"you need to do anything.</div>"
            )
            + theme.section("Reading the colours")
            + theme.card(
                f'<table width="100%" cellpadding="3" cellspacing="0">'
                f"{legend}</table>"
            )
        ))

    def _detail_html(self, ev):
        """
        The selected event, as a diagnostic card stack.

        Everything here is built from tables and solid colours because
        QTextBrowser renders an HTML 4 subset: border-radius, border-left,
        letter-spacing and rgba() are all silently dropped. See theme.card()
        for how the accent rails are constructed.
        """
        severity = ev["severity"]
        colour = SEVERITY_COLOR[severity]
        esc = html.escape
        raw = " ".join((ev.get("message") or "").split())

        repeats = (
            f'<span style="color:{theme.TEXT_LOW}; font-size:10px;">'
            f"&#8202;&#8202;\u00b7&#8202;&#8202;seen {ev['count']} times</span>"
            if ev.get("count", 1) > 1 else ""
        )

        # --- headline card, tinted by severity -------------------------
        headline = theme.card(
            f'<div style="color:{colour}; font-size:10px;">'
            f"<b>{theme.spaced(SEVERITY_LABEL[severity].upper())}</b>"
            f"{repeats}</div>"
            f'<div style="font-family:{theme.FONT_DISPLAY}; font-size:18px; '
            f'color:{theme.TEXT_HI}; margin-top:7px;">'
            f"<b>{esc(ev['title'])}</b></div>"
            f'<div style="color:{theme.TEXT_LOW}; font-size:11px; '
            f'margin-top:6px;">'
            f"{ev['time'].strftime('%A %d %B %Y, %H:%M:%S')}</div>",
            background=theme.WASH[severity],
            rail=colour,
        )

        # --- what it means ---------------------------------------------
        meaning = theme.section("What this means") + theme.card(
            f'<div style="font-size:13px; line-height:155%; '
            f'color:{theme.TEXT_HI};">{esc(ev["meaning"])}</div>'
        )

        # --- what to do -------------------------------------------------
        advice = theme.section("What you should do") + theme.card(
            f'<div style="font-size:13px; line-height:155%; '
            f'color:{theme.TEXT_HI};">{esc(ev["action"])}</div>',
            rail=colour,
        )

        # --- metadata grid ----------------------------------------------
        details = theme.section("Technical detail") + theme.card(
            theme.kv([
                ("Event ID", f"<b>{ev['event_id']}</b>"),
                ("Source", esc(ev["provider"])),
                ("Log", esc(ev["channel"])),
                ("Record", f"#{esc(str(ev['record_id']))}"),
                ("Computer", esc(ev.get("computer", ""))),
            ])
        )

        # --- Windows' own words -----------------------------------------
        # For events with no hand-written rule, `meaning` already *is*
        # Windows' wording, so repeating it verbatim here would be noise.
        if raw and not ev.get("verbatim"):
            raw_block = (
                theme.section("Original message")
                + theme.card(theme.mono(esc(raw)), background=theme.INK_0)
            )
        elif raw:
            raw_block = ""
        elif ev.get("provider") in ("Device recorder", "Activity recorder"):
            # This did not come from Windows, so saying Windows was silent
            # about it would be misleading.
            raw_block = theme.section("Where this came from") + theme.card(
                f'<div style="color:{theme.TEXT_MED}; font-size:12px; '
                f'line-height:150%;">Detected directly from Windows device '
                f"notifications and written to the permanent record "
                f"(entry #{esc(str(ev.get('record_id', '')))} of the newest "
                f"{history.MAX_ENTRIES} kept).</div>"
            )
        else:
            raw_block = theme.section("Original message") + theme.card(
                f'<div style="color:{theme.TEXT_LOW}; font-size:12px;">'
                f"Windows did not supply a text description for this "
                f"record.</div>"
            )

        # --- footnote ----------------------------------------------------
        if ev.get("known") or ev.get("provider") in (
            "Device recorder", "Activity recorder"
        ):
            note = ""
        else:
            note = (
                f'<p style="color:{theme.TEXT_LOW}; font-size:11px; '
                f'line-height:150%; margin-top:14px;"><i>Shown in Windows\u2019 '
                f"own words \u2014 SystemWatch has no hand-written explanation "
                f"for this event type.</i></p>"
            )

        return theme.page(
            headline + meaning + advice + details + raw_block + note
        )

    def open_settings(self):
        dialog = SettingsDialog(self.cfg, self.access, self)
        if dialog.exec_() != QDialog.Accepted:
            return

        new_cfg = dialog.result_config()
        channels_changed = set(new_cfg["channels"]) != set(self.cfg["channels"])
        activity_changed = (
            new_cfg["record_activity"] != self.cfg["record_activity"]
        )
        self.cfg = new_cfg
        save_config(self.cfg)

        if activity_changed:
            # The recorder reads this once at start, so it has to restart to
            # pick it up. The tab redraws now to say which state it is in.
            restart_recorder(lambda ok: self.activity_panel.mark_dirty())
            self.activity_panel.mark_dirty()

        self.noisy_box.setChecked(self.cfg["hide_noisy"])
        self.proxy.set_hide_noisy(self.cfg["hide_noisy"])

        try:
            if dialog.wants_autostart() and not startup_mod.is_enabled():
                startup_mod.enable()
            elif not dialog.wants_autostart() and startup_mod.is_enabled():
                startup_mod.disable()

            if dialog.wants_recorder():
                if not startup_mod.recorder_is_enabled():
                    startup_mod.enable_recorder()
                ensure_recorder()
            elif startup_mod.recorder_is_enabled():
                startup_mod.disable_recorder()
        except Exception as exc:
            self.tray.showMessage(
                "Could not change the startup setting",
                str(exc),
                QSystemTrayIcon.Warning,
                5000,
            )

        if channels_changed and not self.paused:
            self._start_monitoring()
        self._update_status_text()

    # -- window / tray behaviour -----------------------------------------
    def _tray_activated(self, reason):
        if reason in (
            QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick
        ):
            self._restore()

    def _restore(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(250, self._maybe_welcome)

    def _settings_from_tray(self):
        self._restore()
        self.open_settings()

    def _notification_clicked(self):
        """Open the window on the newest error - the one just announced."""
        self._restore()
        self.tabs.setCurrentIndex(0)
        for row in range(self.proxy.rowCount()):
            source = self.proxy.mapToSource(self.proxy.index(row, 0))
            event = self.model.event_at(source.row())
            if event and event["severity"] == ERROR:
                self.table.selectRow(row)
                self.table.scrollTo(self.proxy.index(row, 0))
                return

    def closeEvent(self, event):
        # Hiding to the tray is only safe if there is a tray to come back
        # from. Without one the window would vanish while the process kept
        # running, with no way to reach it short of Task Manager.
        if self.cfg["minimize_to_tray"] and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self._remember_layout()
            save_config(self.cfg)
            self.hide()
            if not getattr(self, "_told_about_tray", False):
                self._told_about_tray = True
                self.tray.showMessage(
                    "Still running",
                    "SystemWatch is in the notification area. "
                    "Right-click its icon to pause or quit completely.",
                    QSystemTrayIcon.Information,
                    5000,
                )
        else:
            self.quit_app()

    def quit_app(self):
        self.drain_timer.stop()
        self.stat_timer.stop()
        self.watcher.shutdown()
        self._remember_layout()
        save_config(self.cfg)
        self.tray.hide()
        self.quit_requested.emit()
        QApplication.quit()
