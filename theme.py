# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Al-Baraa Ibrahim Melhem
"""
SystemWatch - the design system.

This module is the single source of truth for how the app looks. It holds no
state, touches no OS API and imports nothing from the monitoring layer beyond
the three severity keys, so it can be edited freely without any risk to the
parts that read the machine.

Before this existed the palette was copy-pasted into ui.py, devicepanel.py and
activitypanel.py, which meant a colour change had to be made in three places
and the three tabs had already drifted apart. Everything visual now comes from
here.

TWO RENDERING WORLDS
--------------------
The app draws through two very different engines, and a token has to work in
both:

  1. Qt widgets, styled with QSS. Supports most of what you would expect:
     border-radius, rgba(), hover/checked/focus states.

  2. QTextBrowser rich text, used by the detail pane and both panel tabs.
     This is an HTML 4 / CSS 2.1 subset. It does NOT support border-radius,
     border-left, letter-spacing, flexbox, or reliable alpha. Anything built
     for it has to use tables, bgcolor and solid colours.

That is why the palette below carries pre-blended opaque tints (WASH, EDGE).
An rgba() overlay that works in QSS silently renders as nothing in rich text,
so the rich-text side gets colours that are already flattened against their
background.

SURFACE LADDER
--------------
Four elevations, dark to light. Depth is expressed by surface, not by shadow,
because Qt does not draw shadows inside a plain widget tree.

    INK_0  the canvas          the event table, the deepest ground
    INK_1  raised              header, status bar, tab bar, panel pages
    INK_2  card / control      buttons, inputs, cards inside a page
    INK_3  overlay             hover, menus, tooltips

CONTRAST
--------
Every text/surface pair here meets WCAG AA (4.5:1) and most clear AA large by
a wide margin. The three severity colours were picked against INK_0 and then
re-checked against their own washes, since severity text is often drawn on a
tinted card rather than the plain background.
"""

import os
import sys

from translations import ERROR, INFO, WARN


def asset(name):
    """
    Absolute path to a bundled image, as QSS wants it (forward slashes).

    From source that is ./assets; in the packaged build PyInstaller unpacks
    data files under sys._MEIPASS, which is where build.py puts them.
    """
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.abspath(__file__)
    )
    return os.path.join(base, "assets", name).replace("\\", "/")

# --------------------------------------------------------------------------
# surfaces
# --------------------------------------------------------------------------
INK_0 = "#0A0D13"       # canvas
INK_1 = "#11151D"       # raised
INK_2 = "#171C26"       # card / control
INK_3 = "#1E2430"       # overlay / hover
INK_4 = "#262E3C"       # pressed

LINE = "#222936"        # hairline
LINE_STRONG = "#323C4D"  # emphasis border

# --------------------------------------------------------------------------
# text - three tiers, all AA on every surface above
# --------------------------------------------------------------------------
TEXT_HI = "#EEF2F8"     # 17.3:1 on INK_0
TEXT_MED = "#9CA8BC"    #  8.1:1 on INK_0
TEXT_LOW = "#7A8599"    #  5.2:1 on INK_0 - chrome only, never on a row

# --------------------------------------------------------------------------
# accent
# --------------------------------------------------------------------------
# A light periwinkle carrying dark text, rather than a saturated fill carrying
# white. White on this hue is only 3.15:1, which fails AA at button sizes;
# dark ink on it is 6.0:1. It also keeps the accent clearly distinct from the
# green / amber / red severity trio, which is domain information and must not
# be confused with "this is the button".
ACCENT = "#6E8CF0"
ACCENT_HOVER = "#8AA3F5"
ACCENT_QUIET = "#3A4A87"   # accent at rest, for borders and rails
ON_ACCENT = "#08101F"      # 6.0:1 on ACCENT

# Row states. Opaque, because a translucent selection over an alternating row
# colour produces two different selected shades.
SEL_BG = "#1B2340"
HOVER_BG = "#191F2B"
ROW_LINE = "#161B24"

FOCUS_RING = ACCENT

# --------------------------------------------------------------------------
# severity - the app's signal colours
# --------------------------------------------------------------------------
# SEVERITY_COLOR itself lives in translations.py next to the severity keys.
# What follows are the surface tints derived from it, pre-flattened for rich
# text. WASH is the card fill, EDGE the rail or border on that card.
WASH = {
    INFO: "#17302E",
    WARN: "#302B21",
    ERROR: "#302026",
}
EDGE = {
    INFO: "#256B54",
    WARN: "#765B29",
    ERROR: "#763738",
}

# Semantic aliases so panels can say what they mean rather than pick a colour.
OK = "#3ED598"
CAUTION = "#F2B138"
ALERT = "#F1615A"
INFO_BLUE = ACCENT

FONT_UI = "'Segoe UI Variable Text','Segoe UI',system-ui,sans-serif"
FONT_DISPLAY = "'Segoe UI Variable Display','Segoe UI',system-ui,sans-serif"
FONT_MONO = "'Cascadia Mono','Consolas','Courier New',monospace"

RADIUS = 6              # controls
RADIUS_CARD = 8         # cards, dialogs, menus
RADIUS_PILL = 999


# ==========================================================================
# Qt style sheet
# ==========================================================================
def qss():
    """The whole application stylesheet.

    Applied once to the top-level window, from which it cascades to the tabs,
    both panels and every dialog. Selectors are kept flat and object-name
    based so they cannot fight each other: a widget is targeted by its
    objectName or by a dynamic property, never by nesting depth.
    """
    return f"""
    /* ---- base ------------------------------------------------------- */
    QWidget {{
        background:{INK_0};
        color:{TEXT_HI};
        font-family:{FONT_UI};
        font-size:13px;
    }}
    /* These would otherwise paint the window colour over whatever card
       they sit on, boxing every label and option in its own dark rectangle. */
    QLabel {{ background:transparent; color:{TEXT_HI}; }}
    QCheckBox {{ background:transparent; }}
    QToolTip {{
        background:{INK_3};
        color:{TEXT_HI};
        border:1px solid {LINE_STRONG};
        padding:6px 9px;
        font-size:12px;
    }}

    /* ---- header ----------------------------------------------------- */
    QFrame#header {{
        background:{INK_1};
        border:none;
        border-bottom:1px solid {LINE};
    }}
    QLabel#appname {{
        font-family:{FONT_DISPLAY};
        font-size:15px; font-weight:600; color:{TEXT_HI};
    }}
    QLabel#appsub {{ font-size:11px; color:{TEXT_LOW}; }}

    QLabel#statuspill {{
        background:{WASH[INFO]};
        color:{OK};
        border:1px solid {EDGE[INFO]};
        border-radius:11px;
        padding:4px 12px;
        font-size:11px; font-weight:600;
    }}
    QLabel#statuspill[state="paused"] {{
        background:{INK_2};
        color:{TEXT_MED};
        border:1px solid {LINE_STRONG};
    }}

    /* Counter chips. Scannable at a glance: a dot plus a number, tinted by
       severity, rather than three runs of coloured text. */
    QLabel#counter {{
        background:{INK_2};
        border:1px solid {LINE};
        border-radius:{RADIUS}px;
        padding:4px 10px;
        font-size:12px; font-weight:600;
        color:{TEXT_MED};
    }}
    QLabel#counter[sev="error"][active="true"] {{
        background:{WASH[ERROR]}; border-color:{EDGE[ERROR]}; color:{ALERT};
    }}
    QLabel#counter[sev="warn"][active="true"] {{
        background:{WASH[WARN]}; border-color:{EDGE[WARN]}; color:{CAUTION};
    }}
    QLabel#counter[sev="info"][active="true"] {{
        background:{WASH[INFO]}; border-color:{EDGE[INFO]}; color:{OK};
    }}

    /* ---- bars ------------------------------------------------------- */
    QFrame#filterbar {{
        background:{INK_1};
        border:none;
        border-bottom:1px solid {LINE};
    }}
    QFrame#statusbar {{
        background:{INK_1};
        border:none;
        border-top:1px solid {LINE};
    }}
    QLabel#statustext {{ color:{TEXT_LOW}; font-size:11px; }}
    QLabel#panelheadline {{
        color:{TEXT_HI}; font-size:13px; font-weight:600;
    }}

    /* ---- buttons ---------------------------------------------------- */
    QPushButton {{
        background:{INK_2};
        border:1px solid {LINE_STRONG};
        border-radius:{RADIUS}px;
        padding:6px 14px;
        color:{TEXT_HI};
        font-size:12px;
    }}
    QPushButton:hover {{ background:{INK_3}; border-color:{ACCENT_QUIET}; }}
    QPushButton:pressed {{ background:{INK_4}; }}
    QPushButton:focus {{ border:1px solid {FOCUS_RING}; outline:none; }}
    QPushButton:disabled {{ color:{TEXT_LOW}; border-color:{LINE}; }}

    QPushButton[kind="primary"] {{
        background:{ACCENT};
        border:1px solid {ACCENT};
        color:{ON_ACCENT};
        font-weight:600;
    }}
    QPushButton[kind="primary"]:hover {{
        background:{ACCENT_HOVER}; border-color:{ACCENT_HOVER};
    }}
    QPushButton[kind="primary"]:pressed {{ background:{ACCENT_QUIET}; }}

    QPushButton[kind="quiet"] {{
        background:transparent; border:1px solid transparent;
        color:{TEXT_MED};
    }}
    QPushButton[kind="quiet"]:hover {{
        background:{INK_2}; border-color:{LINE}; color:{TEXT_HI};
    }}

    /* Severity filter chips. Unchecked keeps a border so it still reads as
       a control rather than as a run of text. */
    QPushButton#chip {{
        border-radius:13px;
        padding:5px 14px;
        font-size:11px; font-weight:600;
        color:{TEXT_LOW};
        background:transparent;
        border:1px solid {LINE};
    }}
    QPushButton#chip:hover {{ color:{TEXT_HI}; border-color:{LINE_STRONG}; }}
    QPushButton#chip:checked[sev="error"] {{
        color:{ALERT}; background:{WASH[ERROR]}; border-color:{EDGE[ERROR]};
    }}
    QPushButton#chip:checked[sev="warn"] {{
        color:{CAUTION}; background:{WASH[WARN]}; border-color:{EDGE[WARN]};
    }}
    QPushButton#chip:checked[sev="info"] {{
        color:{OK}; background:{WASH[INFO]}; border-color:{EDGE[INFO]};
    }}

    /* ---- inputs ----------------------------------------------------- */
    QLineEdit {{
        background:{INK_2};
        border:1px solid {LINE_STRONG};
        border-radius:{RADIUS}px;
        padding:6px 10px;
        color:{TEXT_HI};
        selection-background-color:{ACCENT};
        selection-color:{ON_ACCENT};
    }}
    QLineEdit:hover {{ border-color:{ACCENT_QUIET}; }}
    QLineEdit:focus {{ border:1px solid {ACCENT}; background:{INK_3}; }}

    QSpinBox {{
        background:{INK_2};
        border:1px solid {LINE_STRONG};
        border-radius:{RADIUS}px;
        padding:4px 6px;
        color:{TEXT_HI};
        min-height:18px;
    }}
    QSpinBox:focus {{ border:1px solid {ACCENT}; }}
    QSpinBox::up-button, QSpinBox::down-button {{
        background:{INK_3}; border:none; width:16px;
    }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
        background:{ACCENT_QUIET};
    }}

    QCheckBox {{ color:{TEXT_MED}; font-size:12px; spacing:8px; }}
    QCheckBox:hover {{ color:{TEXT_HI}; }}
    QCheckBox:disabled {{ color:{TEXT_LOW}; }}
    QCheckBox::indicator {{
        width:16px; height:16px;
        border-radius:4px;
        border:1px solid {LINE_STRONG};
        background:{INK_2};
    }}
    QCheckBox::indicator:hover {{ border-color:{ACCENT}; }}
    QCheckBox::indicator:focus {{ border:1px solid {FOCUS_RING}; }}
    QCheckBox:focus {{ color:{TEXT_HI}; }}
    /* The tick is what says "on". A filled square alone tells the two states
       apart by colour only, which fails anyone who cannot see the accent. */
    QCheckBox::indicator:checked {{
        background:{ACCENT}; border:1px solid {ACCENT};
        image:url("{asset('check.png')}");
    }}
    QCheckBox::indicator:checked:disabled {{
        background:{INK_2}; border-color:{LINE};
        image:url("{asset('check-disabled.png')}");
    }}
    QCheckBox::indicator:checked:hover {{
        background:{ACCENT_HOVER}; border-color:{ACCENT_HOVER};
    }}
    QCheckBox::indicator:disabled {{ background:{INK_1}; border-color:{LINE}; }}

    /* ---- table ------------------------------------------------------ */
    QTableView#table {{
        background:{INK_0};
        border:none;
        outline:none;
        gridline-color:transparent;
    }}
    QHeaderView {{ background:{INK_0}; border:none; }}
    QHeaderView::section {{
        background:{INK_0};
        color:{TEXT_LOW};
        border:none;
        border-bottom:1px solid {LINE};
        padding:9px 10px;
        font-size:11px; font-weight:600;
    }}
    QHeaderView::section:hover {{ color:{TEXT_MED}; }}
    QTableView QTableCornerButton::section {{
        background:{INK_0}; border:none;
    }}

    /* ---- rich-text panes -------------------------------------------- */
    QTextBrowser#detail {{
        background:{INK_1};
        border:none;
        border-left:1px solid {LINE};
    }}
    QTextBrowser#panelview {{
        background:{INK_1};
        border:none;
    }}

    /* ---- splitter --------------------------------------------------- */
    QSplitter#splitter::handle {{ background:{LINE}; }}
    QSplitter#splitter::handle:hover {{ background:{ACCENT_QUIET}; }}
    QSplitter#splitter::handle:pressed {{ background:{ACCENT}; }}

    /* ---- scrollbars ------------------------------------------------- */
    QScrollBar:vertical {{
        background:transparent; width:10px; margin:0;
    }}
    QScrollBar::handle:vertical {{
        background:{LINE_STRONG}; border-radius:5px; min-height:34px;
    }}
    QScrollBar::handle:vertical:hover {{ background:{ACCENT_QUIET}; }}
    QScrollBar:horizontal {{
        background:transparent; height:10px; margin:0;
    }}
    QScrollBar::handle:horizontal {{
        background:{LINE_STRONG}; border-radius:5px; min-width:34px;
    }}
    QScrollBar::handle:horizontal:hover {{ background:{ACCENT_QUIET}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height:0; width:0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}

    /* ---- tabs ------------------------------------------------------- */
    QTabWidget#tabs::pane {{
        border:none;
        border-top:1px solid {LINE};
        background:{INK_0};
    }}
    QTabBar {{ background:{INK_1}; qproperty-drawBase:0; }}
    QTabBar::tab {{
        background:transparent;
        color:{TEXT_LOW};
        padding:10px 18px;
        margin:0;
        border:none;
        border-bottom:2px solid transparent;
        font-size:12px; font-weight:600;
    }}
    QTabBar::tab:first {{ margin-left:12px; }}
    QTabBar::tab:hover {{ color:{TEXT_HI}; background:{INK_2}; }}
    QTabBar::tab:selected {{
        color:{TEXT_HI};
        border-bottom:2px solid {ACCENT};
        background:transparent;
    }}

    /* ---- dialogs ---------------------------------------------------- */
    QDialog {{ background:{INK_1}; }}
    QFrame#settingsCard {{
        background:{INK_2};
        border:1px solid {LINE};
        border-radius:{RADIUS_CARD}px;
    }}
    QFrame#settingsNote {{
        background:{WASH[INFO]};
        border:1px solid {EDGE[INFO]};
        border-radius:{RADIUS}px;
    }}
    QLabel#settingsNoteText {{ color:{OK}; font-size:11px; }}
    QLabel#groupHeading {{
        color:{TEXT_LOW}; font-size:10px; font-weight:700;
    }}
    QLabel#fieldLabel {{ color:{TEXT_MED}; font-size:12px; }}
    QDialogButtonBox QPushButton {{ min-width:84px; }}

    /* ---- menus ------------------------------------------------------ */
    QMenu {{
        background:{INK_2};
        border:1px solid {LINE_STRONG};
        padding:6px;
        color:{TEXT_HI};
    }}
    QMenu::item {{ padding:8px 26px 8px 12px; border-radius:{RADIUS}px; }}
    QMenu::item:selected {{ background:{ACCENT}; color:{ON_ACCENT}; }}
    QMenu::item:disabled {{ color:{TEXT_LOW}; }}
    QMenu::separator {{
        height:1px; background:{LINE}; margin:6px 8px;
    }}
    """


# ==========================================================================
# rich-text helpers  (QTextBrowser: HTML 4 subset only)
# ==========================================================================
def spaced(text):
    """Fake letter-spacing for an uppercase eyebrow.

    Qt rich text ignores `letter-spacing` outright. Putting a real space
    character between the letters is the only way to get the same effect.

    It has to be U+202F NARROW NO-BREAK SPACE specifically. A hair space
    (U+200A) looks identical but is breakable, so in a narrow table cell Qt
    wraps at every gap and renders the label as a vertical column of single
    letters.
    """
    return " ".join(text)


def page(inner, background=INK_1, margin="16px 18px"):
    """Wrap panel content in a body with the right ground colour.

    The QSS background on a QTextBrowser is painted underneath the document,
    so the document's own body has to repeat it or the page shows through
    wherever the content is shorter than the viewport.
    """
    return (
        f'<body style="background:{background}; color:{TEXT_HI}; '
        f'font-family:{FONT_UI}; font-size:13px;">'
        f'<div style="margin:{margin};">{inner}</div></body>'
    )


def gap(height=10):
    """Vertical space between cards. Qt collapses empty block margins."""
    return f'<div style="font-size:1px; line-height:{height}px;">&nbsp;</div>'


def card(inner, background=INK_2, rail=None, pad=12):
    """A padded block, optionally with a coloured rail down its left edge.

    `border-left` does not render in Qt rich text, so the rail is a real
    table cell three pixels wide. The content sits in a nested table, because
    `cellpadding` applies to every cell in a table - putting the rail and the
    content in one table would pad the rail out to about 27px and turn a
    hairline into a slab.
    """
    body = (
        f'<table cellpadding="{pad}" cellspacing="0" width="100%">'
        f'<tr><td bgcolor="{background}">{inner}</td></tr></table>'
    )
    if not rail:
        return body
    return (
        f'<table cellpadding="0" cellspacing="0" width="100%">'
        f'<tr><td width="3" bgcolor="{rail}"></td>'
        f'<td>{body}</td></tr></table>'
    )


def section(title, count=None):
    """An eyebrow label introducing a group."""
    suffix = (
        f'<span style="color:{TEXT_LOW}; font-weight:400;">'
        f'&#8202;&#8202;{count}</span>'
        if count is not None else ""
    )
    # Deliberately NOT letter-spaced. The eyebrow look is carried by size,
    # weight and colour instead, so the rendered HTML still contains the
    # title as a plain searchable string - which the panel tests rely on and
    # which spaced() would break by wedging a hair space between every
    # character.
    return (
        f'<p style="color:{TEXT_LOW}; font-size:10px; margin:18px 0 7px 0;">'
        f"<b>{title}</b>{suffix}</p>"
    )


def kv(pairs, label_width=132):
    """A key/value grid. Pairs whose value is empty are dropped."""
    rows = "".join(
        f'<tr>'
        f'<td width="{label_width}" valign="top" '
        f'style="color:{TEXT_LOW}; font-size:11px;">{key}</td>'
        f'<td style="color:{TEXT_HI}; font-size:12px;">{value}</td>'
        f"</tr>"
        for key, value in pairs
        if value
    )
    if not rows:
        return ""
    return (
        f'<table width="100%" cellpadding="4" cellspacing="0">{rows}</table>'
    )


def rows(row_html, background=INK_2, pad=10, inner_pad=5):
    """Wrap pre-built <tr> markup in a card-shaped data table."""
    if not row_html:
        return ""
    return (
        f'<table cellpadding="{pad}" cellspacing="0" width="100%">'
        f'<tr><td bgcolor="{background}">'
        f'<table width="100%" cellpadding="{inner_pad}" cellspacing="0">'
        f"{row_html}</table></td></tr></table>"
    )


def mono(text):
    """A monospace block for raw machine output."""
    return (
        f'<span style="font-family:{FONT_MONO}; font-size:11px; '
        f'color:{TEXT_MED};">{text}</span>'
    )


def empty(message, hint=""):
    """What a group shows when it has nothing in it.

    Always says what is being reported, never renders as blank space - an
    empty area reads as a bug, or worse, as "nothing happened".
    """
    hint_html = (
        f'<div style="color:{TEXT_LOW}; font-size:11px; margin-top:5px;">'
        f"{hint}</div>"
        if hint else ""
    )
    return card(
        f'<div style="color:{TEXT_MED}; font-size:12px;">{message}</div>'
        f"{hint_html}",
        background=INK_2,
    )


def status_card(message, detail="", tone="ok"):
    """The record-condition banner used at the top of both panel tabs."""
    colour = {"ok": OK, "caution": CAUTION, "alert": ALERT}.get(tone, OK)
    detail_html = (
        f'<div style="color:{TEXT_LOW}; font-size:11px; margin-top:5px;">'
        f"{detail}</div>"
        if detail else ""
    )
    return card(
        f'<div style="color:{TEXT_HI}; font-size:12px;">{message}</div>'
        f"{detail_html}",
        background=INK_2,
        rail=colour,
    )


def metric(value, caption, colour=None):
    """One figure for the strip at the top of a panel.

    Returns its parts rather than markup: metrics() needs to know how many
    cells there are before it can size any of them.
    """
    return (str(value), caption, colour or TEXT_HI)


def metrics(cells):
    """Lay a row of metric() figures out side by side.

    Widths are percentages summing to 100 and there is no spacer cell. A
    spacer with width="100%" would take the entire row and squeeze the
    figures until Qt broke them mid-word.
    """
    if not cells:
        return ""
    width = 100 // len(cells)
    body = "".join(
        f'<td width="{width}%" valign="top" style="padding:2px 0 2px 0;">'
        f'<div style="font-family:{FONT_DISPLAY}; font-size:22px; '
        f'color:{colour};"><b>{value}</b></div>'
        f'<div style="color:{TEXT_LOW}; font-size:10px;">{caption}</div>'
        f"</td>"
        for value, caption, colour in cells
    )
    return (
        f'<table cellpadding="0" cellspacing="0" width="100%">'
        f"<tr>{body}</tr></table>"
    )
