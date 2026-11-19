# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Claude Island: a small always-on-top bar that lists your running Claude Code chats and your plan limits.

Hover to open the panel, click a card to jump to its terminal, click X twice to close a chat. The widget is
started by Claude Code hooks (with --hook) or by hand. Only one copy runs: starting it again brings it on screen.
"""
import sys
from pathlib import Path

from platforms import get_platform

# All of this runs before Qt is imported, so the hook that runs on every prompt exits cheaply.
CONFIG_DIR = Path(__file__).resolve().parent / "config"
QUIT_MARK = CONFIG_DIR / "quit.mark"     # you quit it: prompts in open chats do not bring it back

# --doctor: say whether the start hooks and the plan limits are set up, for a bug report.
if "--doctor" in sys.argv:
    import settings
    found, report = settings.limits_report()
    print("Claude Island doctor:", sys.platform, sys.executable)
    print("Start hooks:", "on" if settings.start_hook_installed() else "off")
    print("\n".join(report))
    print("Plan limits:", "OK" if found else "missing")
    sys.exit(0)
# --detach (macOS and Linux hooks): start again in a session of our own, so the widget outlives the hook.
if "--detach" in sys.argv:
    import subprocess
    subprocess.Popen([sys.executable] + [a for a in sys.argv if a != "--detach"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    sys.exit(0)
# After you quit, only a new chat (SessionStart) or starting it yourself brings it back, not every prompt.
if "--on-prompt" in sys.argv and QUIT_MARK.exists():
    sys.exit(0)
# Already running: a copy started by hand leaves a flag for the running one: show yourself, or with --toggle
# hide or show, or with --quit quit.
if not get_platform().instance.acquire():
    if "--hook" not in sys.argv:
        name = "toggle" if "--toggle" in sys.argv else "quit" if "--quit" in sys.argv else "show"
        CONFIG_DIR.mkdir(exist_ok=True)
        (CONFIG_DIR / f"{name}.flag").touch()
    sys.exit(0)
if "--quit" in sys.argv:              # nothing running to quit
    sys.exit(0)
QUIT_MARK.unlink(missing_ok=True)

import math
import os

# Linux on Wayland: an app may not place its own windows there, so the island (docked or floating) would land
# anywhere. Run it through XWayland instead when that is available and you did not pick a Qt platform yourself.
if sys.platform.startswith("linux") and os.environ.get("WAYLAND_DISPLAY") and os.environ.get("DISPLAY")         and not os.environ.get("QT_QPA_PLATFORM"):
    os.environ["QT_QPA_PLATFORM"] = "xcb"
import threading
import time
from functools import partial

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QIcon, QLinearGradient,
                           QMovie, QPainter, QPen, QPixmap)
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QLineEdit, QMenu, QSystemTrayIcon, QWidget

import settings
import sounds
from drawing import (AMBER, BG, BLUE, CARD, CARD_HOVER, CLAUDE, CLAUDE_LIGHT, CLOSE_RED, DIM, FORGOT,
                     GRAY, GREEN, ICON, INK, RED, TIME_BAR, TRACK, WHITE, WHITE_30, WHITE_170, WHITE_200, WHITE_220,
                     WORKING, Spring, apply_palette, draw_check, draw_cross, draw_eye, draw_gear, draw_mascot,
                     draw_pin, draw_plus, draw_power, draw_ring, draw_spark, draw_spinner, draw_up_arrow, ease_out, font,
                     icon_pixmap, paint_frame, ramp)
from feed import (Feed, clamp, clean_status_dir, fmt_dur, fmt_tokens, lerp, read_json, same_process,
                  session_state, short_tool, tool_detail)

PLAT = get_platform()
winctl = PLAT.winctl
SHOW_FLAG = settings.HERE / "config" / "show.flag"      # the files the guard above touches
TOGGLE_FLAG = settings.HERE / "config" / "toggle.flag"
QUIT_FLAG = settings.HERE / "config" / "quit.flag"
HIDDEN_FILE = settings.HERE / "config" / "hidden_windows.txt"
CFG = settings.load()

COMPACT_AT = 40                       # context % from which a card offers Compact
# Alcove-style notch motion. stiffness, damping ratio (<1 overshoots). The drop-down is a bit slower and
# gently bouncy (~0.39 s, ~7% overshoot); the wrap is snappy and tight (~0.27 s, barely any overshoot).
OPEN_SPRING = (260.0, 0.66)           # drop down: springy, like Alcove opening
CLOSE_SPRING = (520.0, 0.80)          # wrap up: quick and clean
ASK_ROW_H = 30                        # answer buttons under a waiting card
REPLY_H = 32                          # reply box under them
NOTCH_WING = 40                       # docked in a macOS notch: px each side of it while Claude works
COMPANION_W = 46                      # companion mode: width of the small Claude pill beside the notch
COMPANION_GAP = 8                     # companion mode: gap between the notch and the pill
COMPANION_NOTIF_W = 250               # companion mode: width the pill grows to for a compact notification
NOTCH_SNAP = 80                       # how close a drag must come to the notch to dock
NOTCH_EAR = 8                         # docked: how far the top corners flare out into the screen edge
TOP_DOCK_W = 184                      # screens with no notch: the island docks into a notch of its own
# Windows and Linux have no camera notch: the island docks on a screen edge of your choice instead (win_dock):
# the top edge, above the taskbar or panel, or the left or right side. macOS keeps its notch dock.
EDGE_DOCK = PLAT.name in ("windows", "linux")
# macOS keeps its notch dock on top; the left and right sides of the screen are free, so the same upright side tab
# as on Windows can dock there (win_dock "left" / "right"). No taskbar dock on macOS.
MAC_SIDES = PLAT.name == "macos"
WIN_DOCK_H = 32                       # Windows: height of the docked bar
WIN_DOCK_W = 72                       # Windows: width of the docked bar when idle (just a handle to hover)
WIN_WING = 30                         # Windows: px each side of it for the mascot and the dot while Claude works
# Windows dock motion, after the macOS Dynamic Island: (stiffness, damping ratio). Opening, the width leads
# (~0.4 s, 3 % bounce) and the height follows with a soft bounce (~0.5 s, 4 %); closing, the height pulls back
# first (~0.33 s, no bounce) and the width trails (~0.4 s), so the panel draws back into the bar like a drop.
WIN_OPEN_W, WIN_OPEN_H = (190.0, 0.72), (140.0, 0.68)
WIN_CLOSE_W, WIN_CLOSE_H = (170.0, 0.88), (260.0, 0.98)
WIN_STICK = 140                       # Windows: px a drag must pull away from the dock before it lets go
NOTCH_BLACK = QColor(0, 0, 0)
GLASS_TINT = 0.6                      # share of the background colour painted over the macOS glass
LIQUID_TINT = 0.3                     # the same over Liquid Glass (macOS 26), already dark and frosted
AGENT_ROW_H = 18                      # one sub-agent under its chat's card
AGENT_ROWS_MAX = 3                    # beyond this the last row says "+N more"
AGENT_LINGER_S = 60                   # a finished sub-agent keeps its row this long

# tier -> (label, colour, mascot pose)
TIERS = {
    "working": ("Working", WORKING, "coding"),
    "waiting": ("Needs you", AMBER, "waiting"),
    "done": ("Done", GREEN, "done"),
    "idle": ("Idle", BLUE, "idle"),
    "forgotten": ("Forgotten", FORGOT, "sleep"),
}
CONTEXT_STOPS = [(0, (108, 203, 95)), (COMPACT_AT, (252, 225, 0)), (60, (247, 140, 60)), (80, (240, 80, 80))]
LIMIT_STOPS = [(0, (108, 203, 95)), (50, (252, 225, 0)), (75, (247, 140, 60)), (90, (240, 80, 80))]
VERBS = [
    ({"thinking"}, "Thinking"),
    ({"writing"}, "Writing a reply"),
    ({"bash", "powershell"}, "Running commands"),
    ({"read", "grep", "glob", "ls"}, "Reading files"),
    ({"edit", "write", "multiedit", "notebookedit"}, "Editing files"),
    ({"websearch", "webfetch"}, "Searching the web"),
    ({"agent", "task"}, "Running agents"),
]
TIPS = {"quit": "Quit Claude Island (click twice). A new chat starts it again.", "newchat": "New chat", "settings": "Settings", "close": "Close this chat", "send": "Send",
        "compact": "Compact: summarise this chat to free its context"}
KEYS_HELP = ("↑/↓ or Tab: pick a chat · Enter: open it · Del twice: close it · Esc: close · "
             "Ctrl+, settings · Ctrl+N new chat · Ctrl+P pin · Ctrl+H hide/show all chats · Ctrl+W hide the island · "
             "Ctrl+R refresh · Ctrl+Q quit · from any app: Ctrl+Alt+I (⌃⌥I on a Mac) hides or shows the island")

ctx_color = partial(ramp, CONTEXT_STOPS)
limit_color = partial(ramp, LIMIT_STOPS)


def tier(s, now):
    if s["status"] == "busy":
        return "working"
    if s["status"] == "waiting":
        return "waiting"
    idle = now - s["since"]
    if idle < CFG["done_minutes"] * 60:
        return "done"
    if idle < CFG["forgotten_hours"] * 3600:
        return "idle"
    return "forgotten"


def verb(tool):
    """What a chat is doing, in plain words."""
    t = (tool or "").lower()
    if not t:
        return "Working"
    for names, words in VERBS:
        if t in names:
            return words
    if t.startswith(("todo", "task")):
        return "Planning"
    return "Using tools"


def ctx_pct(s):
    if s["tokens"] is None or not s["size"]:
        return None
    return 100.0 * s["tokens"] / s["size"]


def find(sessions, sid):
    return next((s for s in sessions if s["sid"] == sid), None)


def pending(s):
    """(tool id, name, input) of the call a chat waits on, else (None, "", {})."""
    return s["pending"] or (None, "", {})


def running_agents(s):
    return [a for a in s["agents"] if a["running"]]


def agent_time(a, now):
    """How long a sub-agent has been running, or ran."""
    return fmt_dur((now if a["running"] else a["ended"]) - a["started"])


def agent_tip(a, now):
    model = f" · {a['model']}" if a["model"] else ""
    tokens = f"{a['tokens']:,} tokens" if a["tokens"] is not None else "no tokens yet"
    state = "running" if a["running"] else "finished"
    return (f"{a['description']}\n{a['type']}{model}\n"
            f"{tokens} · {a['tool_uses']} tool uses · {agent_time(a, now)} · {state}")


def usage_text(usages, with_time=True):
    """'$1.24 · 412k in / 38k out · +120 −14 lines · 42m', summed over the usage dicts; "" when none is known."""
    def total(key):
        values = [u[key] for u in usages if isinstance(u.get(key), (int, float))]
        return sum(values) if values else None
    cost, tokens_in, tokens_out = total("cost"), total("tokens_in"), total("tokens_out")
    added, removed, duration = total("lines_added"), total("lines_removed"), total("duration")
    parts = []
    if cost is not None:
        parts.append(f"${cost:.2f}")
    if tokens_in is not None or tokens_out is not None:
        parts.append(f"{fmt_tokens(tokens_in)} in / {fmt_tokens(tokens_out)} out")
    if added is not None or removed is not None:
        parts.append(f"+{added or 0} −{removed or 0} lines")
    if with_time and duration is not None:
        parts.append(fmt_dur(duration, coarse=True))
    return " · ".join(parts)


def agents_summary(agents):
    """One tooltip line for the running sub-agents and one for the finished ones, with their tokens."""
    lines = []
    for running, label in ((True, "Running"), (False, "Finished")):
        group = [a for a in agents if a["running"] == running]
        if group:
            tokens = sum(a["tokens"] or 0 for a in group)
            lines.append(f"{label} sub-agents: {len(group)} · {fmt_tokens(tokens)} tokens")
    return lines


def card_tip(s):
    """The chat's context, cost, tokens, lines changed and time, and its sub-agents."""
    lines = []
    pct = ctx_pct(s)
    if pct is not None:
        lines.append(f"Context: {pct:.0f}% of {fmt_tokens(s['size'])}")
    usage = usage_text([s["usage"]])
    lines.append(f"Session: {usage}" if usage else "Session cost and tokens come with the status line script")
    return "\n".join(lines + agents_summary(s["agents"]))


def doing(s, default=""):
    """The current tool and what it is about, e.g. 'Bash: run the tests'."""
    tool = s["tool"] or default
    return f"{tool}: {s['detail']}" if s["detail"] else tool


class Tip(QLabel):
    """A tooltip the island owns. Qt's native tooltip is a plain window, so on macOS it opens *under* the
    island, which floats above other windows; this one is raised one level higher, so it is always on top."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Only text colour and padding here. The background is painted in paintEvent: a stylesheet background
        # on a translucent top-level window does not fill reliably, so over the glass the box went invisible.
        self.setStyleSheet("color:#f0f0f0; padding:6px 9px;")
        self.setWordWrap(True)                                   # long tool details wrap instead of overflowing
        PLAT.look.fix_tool_window(self)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(28, 28, 28, 246))                      # opaque dark box, so text always reads
        p.drawRoundedRect(QRectF(self.rect()), 7, 7)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QColor(255, 255, 255, 38))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
        p.end()
        super().paintEvent(e)                                    # QLabel draws the text on top

    def show_text(self, pos, text, over_menu_bar=False):
        """Show text near the global point pos, kept on screen and above the island."""
        if not text:
            return self.hide()
        self.setText(text)
        scr = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        area = scr.availableGeometry()
        self.setMaximumWidth(min(360, area.width() - 16))        # cap width, then let word wrap set the height
        self.adjustSize()
        x = clamp(pos.x() + 12, area.left() + 4, area.right() - self.width() - 4)
        y = clamp(pos.y() + 18, area.top() + 4, area.bottom() - self.height() - 4)
        self.move(int(x), int(y))
        self.show()
        PLAT.look.keep_on_top(self, over_menu_bar, bump=1)


class Island(QWidget):
    M = 14            # margin around the shape, room for its shadow
    HEAD_H = 32
    PILL_H = 42
    PILL_GAP = 10
    CARD_H = 50
    CARD_GAP = 6

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setWindowTitle("Claude Island")
        PLAT.look.fix_tool_window(self)
        self.f_main = font(13, QFont.Weight.DemiBold)
        self.f_body = font(12)
        self.f_small = font(11)
        self.f_bold = font(12, QFont.Weight.DemiBold)
        self._metrics, self._elided = {}, {}
        self.movies = {}               # mascot path -> QMovie or QPixmap
        self.mascots_now = None        # the mascot settings the movies were loaded for
        self.settings_win = None
        self.shown_data = None         # what the last refresh painted: repaint only when it changes
        self.cfg = CFG
        self.solo = "--hook" not in sys.argv      # started by hand, not by a Claude hook

        self.feed = Feed()
        self.sessions, self.limits, self.order = [], None, []
        self.agent_rows = {}           # sid -> (sub-agents listed on its card, how many more)
        self.hider = None              # the thread hiding every chat window, while it runs
        self.prev_status = None
        self.toast = None              # (kind, title, until)
        self.attention = set()         # waiting chats that opened the panel by themselves
        self.limit_marks = None        # key -> (highest warning mark reached, resets_at)
        self.last_alive = self.last_activity = time.time()

        self.opening = Spring(0.0, 158, 0.82)                  # 0 = small bar, 1 = panel
        self.panel_height = Spring(200, 200, 0.9, eps=0.3)
        self.visibility = Spring(0.0, 170, 0.9)
        self.bar_width = Spring(380, 158, 0.86, eps=0.3)
        self.t0 = self.last_frame = time.monotonic()
        self.last_opacity = -1.0
        self.win_box = (0.0, 0.0)      # window size held during a transition
        self.grow_down = False
        self.visible_k = 0             # how many cards fit on screen

        self.pill = self.bar_pin = self.reply_rect = QRectF()
        self.hits = []                 # (rect, action, sid), rebuilt on every paint; first match wins
        self.hover = self.lingering = self.dragging = False
        self.hover_hit = self.press_at = self.press_hit = None
        self.confirm = None            # (sid, action, until): a second click does it
        self.last_hover = 0.0
        self.kb_open = False           # opened from the keyboard: stay open until Esc or focus loss
        self.island_hidden = False     # hidden by you (shortcut or menu) until you show it again
        self.hotkey = None             # label of the shortcut that hides and shows the island from any app
        self.notch = None              # macOS: QRect of the camera notch we are docked in
        self.dock_bottom = False       # Windows/Linux: docked above the taskbar, opening upward
        self.dock_side = None          # Windows/Linux: "left" or "right" when docked on a side of the screen
        self.glassed = False           # a native blur is behind the shape (macOS), so paint only a tint
        self.reply_sid = None          # the chat the reply box answers
        self.reply_lock = None         # (sid, tool id) once you start typing

        self.tip = Tip()
        self.reply = QLineEdit(self)
        self.reply.hide()
        self.reply.setFont(font(12))
        self.reply.returnPressed.connect(self.send_reply)
        self.reply.textEdited.connect(self.lock_reply)
        self.frame = QTimer(self, interval=16, timeout=self.on_frame)
        self.data = QTimer(self, interval=1000, timeout=self.refresh)
        self.hover_timer = QTimer(self, singleShot=True, timeout=self.apply_hover)

        winctl.load_hidden(HIDDEN_FILE)
        clean_status_dir()
        self.menu = self.build_menu()
        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip("Claude Island")
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.apply_settings()
        settings.update_start_hook()
        settings.ensure_status_line()
        if self.cfg["notch"] or self.cfg.get("companion"):
            self.dock(self.notch_of(self.screen()))
        self.tray.show()
        for flag in (SHOW_FLAG, TOGGLE_FLAG, QUIT_FLAG):
            flag.unlink(missing_ok=True)
        self.refresh()
        self.panel_height.x = self.panel_height.target
        self.data.start()

    # ---------------------------------------------------------------- settings
    @property
    def pinned(self):
        return bool(self.cfg["pinned"])

    def apply_settings(self):
        c = self.cfg
        apply_palette(c)
        self.W, self.RAD = int(c["width"]), int(c["corner_radius"])
        if EDGE_DOCK:
            self.apply_win_dock()
        elif MAC_SIDES and c.get("win_dock") in ("left", "right"):   # macOS side tab, instead of the notch
            c["notch"] = False
            if not self.dragging:
                self.dock(self.notch_of(self.screen()))
        else:
            # Companion and notch modes both dock to the camera notch; turning both off undocks again.
            should_dock = bool(c.get("companion") or c["notch"])
            if should_dock and self.notch is None:
                self.dock(self.notch_of(self.screen()))
            elif not should_dock and self.notch is not None and not self.dragging:
                self.dock(None)
        self.size_bar()
        speed = (c["animation_speed"] / 100) ** 2
        self.open_spring = (OPEN_SPRING[0] * speed, OPEN_SPRING[1])
        self.close_spring = (CLOSE_SPRING[0] * speed, CLOSE_SPRING[1])
        self.win_springs = {k: (v[0] * speed, v[1]) for k, v in
                            (("open_w", WIN_OPEN_W), ("open_h", WIN_OPEN_H),
                             ("close_w", WIN_CLOSE_W), ("close_h", WIN_CLOSE_H))}
        self.panel_height.tune(200 * speed, 0.9)
        self.visibility.tune(170 * speed, 0.9)
        self.bar_width.target = self.W
        self.sync_hotkey()
        sounds.configure(c["sound_volume"], {cue: c[f"sound_file_{cue}"] for cue in sounds.CUES})
        self.reply.setStyleSheet(
            f"QLineEdit{{background:#2b2b2b;color:#fff;border:1px solid #3d3d3d;border-radius:6px;padding:0 8px;"
            f"selection-background-color:{CLAUDE.name()};}}QLineEdit:focus{{border:1px solid {AMBER.name()};}}")
        mascots = ((c["mascot_file"], c["mascot_size"], c["reduce_motion"], CLAUDE.name())
                   + tuple(c[f"mascot_{s}"] for s in settings.MASCOT_STATES))
        if mascots != self.mascots_now:   # reloading restarts every GIF, so only do it on a real change
            self.mascots_now = mascots
            for m in self.movies.values():
                if isinstance(m, QMovie):
                    m.stop()
            self.movies = {}
            self.update_tray_icon()
        self.act_pin.setChecked(self.pinned)
        self.last_opacity = -1.0
        self.pick_agent_rows(time.time())
        self.panel_height.target = self.expanded_height()
        self.apply_hover()
        self.apply_geometry()
        self.update()
        if self.settings_win:
            self.settings_win.sync()

    def update_tray_icon(self):
        size = 34 / (self.cfg["mascot_size"] / 100)    # same tray icon size whatever the mascot scale
        icon = QIcon(icon_pixmap(64, lambda p: self.paint_mascot(p, QPointF(32, 32), size, "idle", t=0.5)))
        QApplication.instance().setWindowIcon(icon)
        self.setWindowIcon(icon)
        self.tray.setIcon(icon)

    def set_cfg(self, key, value):
        self.cfg[key] = value
        settings.save(self.cfg)
        self.apply_settings()
        self.sync_glass()
        self.update()

    def toggle_pin(self):
        self.set_cfg("pinned", not self.pinned)

    def reset_position(self):
        self.cfg.update(dx=settings.DEFAULTS["dx"], dy=settings.DEFAULTS["dy"])
        settings.save(self.cfg)
        self.apply_geometry()

    def open_settings(self, toggle=False):
        """Show the settings window with keyboard focus; with toggle, close it if it is already open."""
        if toggle and self.previewing():
            return self.settings_win.close()
        from settings_ui import SettingsWindow   # loaded on first use to keep startup light
        if not self.settings_win:
            self.settings_win = SettingsWindow(self)
        if not self.settings_win.isVisible():
            self.settings_win.place()
        self.settings_win.show()
        PLAT.look.force_show(self.settings_win)       # Windows may ignore show() for a tool window
        self.settings_win.raise_()
        PLAT.look.force_focus(self.settings_win)
        self.apply_hover()

    def previewing(self):
        """The settings window is open."""
        return bool(self.settings_win and self.settings_win.isVisible())

    def build_menu(self):
        m = QMenu()
        m.setStyleSheet("QMenu{background:#2b2b2b;color:#fff;border:1px solid #3d3d3d;border-radius:8px;padding:4px;}"
                        "QMenu::item{padding:6px 22px;border-radius:4px;}QMenu::item:selected{background:#3a3a3a;}"
                        "QMenu::separator{height:1px;background:#3d3d3d;margin:4px 6px;}")
        m.addAction("Settings…", self.open_settings)
        self.act_pin = m.addAction("Pin (stay on screen when idle)", self.toggle_pin)
        self.act_pin.setCheckable(True)
        self.act_sound = m.addAction("Sounds", lambda: self.set_cfg("sounds", not self.cfg["sounds"]))
        self.act_sound.setCheckable(True)
        m.addAction("Move back to bottom-right", self.reset_position)
        self.act_island = m.addAction("Hide Claude Island", self.toggle_island)
        self.act_hide = m.addAction("Hide all chats", self.toggle_hide_all)
        m.addAction("New chat…", lambda: self.new_chat_menu(QCursor.pos()))
        m.addSeparator()
        m.addAction("Quit Claude Island", self.quit_by_user)
        m.aboutToShow.connect(self.sync_menu)
        return m

    def sync_menu(self):
        self.act_sound.setChecked(self.cfg["sounds"])
        self.act_hide.setText("Show all chats" if winctl.HIDDEN else "Hide all chats")
        label = "Show Claude Island" if self.island_hidden else "Hide Claude Island"
        self.act_island.setText(f"{label}\t{self.hotkey}" if self.hotkey else label)

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.open_settings()

    # ---------------------------------------------------------------- data, once a second
    def refresh(self):
        try:
            sessions, self.limits = self.feed.poll()
            if self.hover or self.opening.target == 1.0:   # never reorder cards under the mouse
                pos = {sid: i for i, sid in enumerate(self.order)}
                sessions.sort(key=lambda x: pos.get(x["sid"], len(pos)))
            self.sessions, self.order = sessions, [x["sid"] for x in sessions]
        except Exception as e:   # a half-written file must never take the widget down
            print("poll error:", e, file=sys.stderr)
        now = time.time()
        self.notice_changes(now)
        if SHOW_FLAG.exists():   # someone started us by hand again
            SHOW_FLAG.unlink(missing_ok=True)
            self.solo = True
            self.island_hidden = False
        if TOGGLE_FLAG.exists():
            TOGGLE_FLAG.unlink(missing_ok=True)
            self.toggle_island()
        if QUIT_FLAG.exists():
            QUIT_FLAG.unlink(missing_ok=True)
            self.quit_by_user()
            return
        if winctl.HIDDEN:
            before = dict(winctl.HIDDEN)
            winctl.prune_hidden([x["title"] for x in self.sessions])
            if winctl.HIDDEN != before:
                winctl.save_hidden(HIDDEN_FILE)
        self.attention &= {s["sid"] for s in self.sessions if s["status"] == "waiting"}
        if self.working() or self.toast or self.attention:
            self.last_activity = now
        if self.toast and self.toast[2] < now:
            self.toast = None
        if self.confirm and self.confirm[2] < now:
            self.confirm = None
        if self.sessions:
            self.last_alive = now
        if self.idle_too_long(now):
            QApplication.quit()
            return
        if not self.dragging:
            self.follow_notch()
        self.pick_agent_rows(now)
        self.panel_height.target = self.expanded_height()
        if self.notch:
            self.size_bar()            # the wings come and go with the news
        self.apply_hover()
        if not self.dragging:
            self.stay_on_top()
        if self.springs_settled():
            self.apply_geometry()      # the frame timer may be stopped: follow a monitor change
        busy = any(s["status"] == "busy" or running_agents(s) for s in self.sessions)
        clock = int(now) if busy else int(now // 60)   # durations tick every second only while a chat works
        shown = (self.sessions, self.limits, clock, self.toast, self.confirm,
                 self.attention, bool(winctl.HIDDEN), self.solo, self.agent_rows)
        if shown != self.shown_data:
            self.shown_data = shown
            self.update()

    def pick_agent_rows(self, now):
        """Which sub-agents each card lists: the running ones, and finished ones for AGENT_LINGER_S.

        Older finished agents are only counted in the card's tooltip, so a card never changes height because
        the mouse is over it (which would move the cards under the mouse).
        """
        self.agent_rows = {}
        if not self.cfg["show_agents"]:
            return
        for s in self.sessions:
            recent = [a for a in s["agents"] if a["running"] or now - a["ended"] < AGENT_LINGER_S]
            if len(recent) > AGENT_ROWS_MAX:
                keep = AGENT_ROWS_MAX - 1
                self.agent_rows[s["sid"]] = (recent[:keep], len(recent) - keep)
            elif recent:
                self.agent_rows[s["sid"]] = (recent, 0)

    def agents_height(self, sid):
        rows, more = self.agent_rows.get(sid, ([], 0))
        return (len(rows) + (1 if more else 0)) * AGENT_ROW_H

    def agents_spinning(self):
        """A running sub-agent's spinner is on screen."""
        if self.opening.x < 0.5:
            return False
        for rows, _ in self.agent_rows.values():
            if any(a["running"] for a in rows):
                return True
        return False

    def idle_too_long(self, now):
        """No chat for quit_after_min minutes, and nothing asks us to stay."""
        quit_after = self.cfg["quit_after_min"] * 60
        if not quit_after or now - self.last_alive <= quit_after:
            return False
        return not (self.pinned or self.solo or self.previewing())

    def notice_changes(self, now):
        """Toast and play a sound when a chat finished, needs you or got to work since the last refresh."""
        cues = set()
        if self.prev_status is not None:   # the first refresh only records where things stand
            for s in self.sessions:
                was = self.prev_status.get(s["sid"])
                if was == "busy" and s["status"] == "idle":
                    self.toast = ("done", s["title"], now + 6)
                    cues.add("done")
                elif was != "waiting" and s["status"] == "waiting":
                    self.toast = ("waiting", s["title"], now + 8)
                    if self.cfg["auto_open"]:
                        self.attention.add(s["sid"])
                    cues.add("needs")
                elif was == "idle" and s["status"] == "busy":
                    cues.add("start")
        self.prev_status = {s["sid"]: s["status"] for s in self.sessions}
        cues |= self.notice_limits(now)
        if self.cfg["sounds"]:
            sounds.play_most_important({c for c in cues if self.cfg[f"sound_{c}"]})

    def notice_limits(self, now):
        """Return "warn" / "limit" cues for session or week usage that crossed 75, 90 or 100 % since last time.

        Marks already passed at startup stay silent. A mark only goes back down when its window really reset,
        so two chats whose status lines differ by a point (89 / 90 %) cannot replay the warning.
        """
        cues, marks = set(), dict(self.limit_marks or {})
        for key in ("five_hour", "seven_day"):
            pct = self.limit_state(key, now)[0]
            if pct is None:
                continue
            reset = ((self.limits or {}).get(key) or {}).get("resets_at")
            mark = max((m for m in (75, 90, 100) if pct >= m), default=0)
            prev, prev_reset = marks.get(key, (None, None))
            if prev is None:
                marks[key] = (mark, reset)
                continue
            if reset and prev_reset and reset < prev_reset:
                continue                                  # figures from an older window
            renewed = bool(reset) and (reset < now or bool(prev_reset and reset != prev_reset))
            if mark > (0 if renewed else prev):
                cues.add("limit" if mark == 100 else "warn")
            marks[key] = (mark if renewed else max(prev, mark), reset)
        self.limit_marks = marks
        return cues

    def limit_state(self, key, now):
        """(used %, window start, reset time) for "five_hour" or "seven_day", Nones when unknown."""
        data = (self.limits or {}).get(key)
        if not data or data.get("used_percentage") is None:
            return None, None, None
        pct, reset = float(data["used_percentage"]), data.get("resets_at")
        if reset and reset < now:        # it has reset since the status line last wrote
            return 0.0, None, None
        window = 5 * 3600 if key == "five_hour" else 7 * 86400
        start = reset - window if reset else None
        return pct, start, reset

    def mascot_mode(self):
        if any(s["status"] == "waiting" for s in self.sessions):
            return "waiting"
        if any(s["status"] == "busy" for s in self.sessions):
            return "coding"
        if self.toast and self.toast[0] == "done":
            return "done"
        now = time.time()
        return "idle" if any(tier(s, now) in ("done", "idle") for s in self.sessions) else "sleep"

    def working(self):
        return any(s["status"] in ("busy", "waiting") for s in self.sessions)

    def companion(self):
        """Companion mode: a small Claude pill always beside a real camera notch, not over it."""
        return bool(self.cfg.get("companion")) and self.notch is not None and not self.dock_side

    def has_news(self):
        """Something worth a compact notification: a chat working, waiting, or one that just finished."""
        return bool(self.working() or self.attention or self.toast)

    def is_mini(self):
        """Show only the mascot: always when docked, else when pinned or solo and quiet for a while."""
        if self.notch is not None:
            return True
        if not (self.pinned or self.solo):
            return False
        if self.working() or self.toast or self.attention or self.previewing():
            return False
        return time.time() - self.last_activity > self.cfg["mini_after_s"]

    def should_show(self):
        if self.island_hidden:
            return False
        # docked, an idle island is just the notch's own black, there to be hovered
        return (self.working() or self.toast is not None or self.pinned or self.hover or self.lingering
                or self.dragging or self.companion() or (self.notch is not None and bool(self.sessions))
                or bool(winctl.HIDDEN) or self.previewing()
                or (self.solo and self.cfg["show_when_started_by_hand"]))

    # ---------------------------------------------------------------- actions
    def ask_kind(self, s):
        """How a waiting chat can be answered from its card: "permission", "question", "other", or None."""
        if s["status"] != "waiting":
            return None
        if s["wait_for"] == "permission prompt":   # Allow / Deny only when we know which call is asking
            return "permission" if s["pending"] else "other"
        _, name, args = pending(s)
        questions = args.get("questions") if name == "AskUserQuestion" and isinstance(args, dict) else None
        if not questions or len(questions) != 1:
            return "other"
        q = questions[0]
        return "question" if q.get("options") and not q.get("multiSelect") else "other"

    def lock_reply(self, _text=""):
        """On the first keystroke, tie the reply box to this chat and this exact request."""
        s = find(self.sessions, self.reply_sid)
        if s and not self.reply_lock:
            self.reply_lock = (s["sid"], pending(s)[0])

    def pick_reply_sid(self):
        lock = self.reply_lock
        if lock and (self.reply.hasFocus() or self.reply.text()):
            s = find(self.sessions, lock[0])
            if s and s["status"] == "waiting" and pending(s)[0] == lock[1]:
                return lock[0]
            # The request you typed for is gone: drop the text, or it would move on to another chat's card.
            self.reply.clear()
        self.reply_lock = None
        return next((s["sid"] for s in self.sessions if self.ask_kind(s) in ("permission", "question")), None)

    def send_reply(self):
        text = self.reply.text().strip()
        sid, request_id = self.reply_lock or (self.reply_sid, None)
        s = find(self.sessions, sid)
        if not text or not s or s["status"] != "waiting":
            return
        if request_id and pending(s)[0] != request_id:   # the question changed while you typed
            return
        kind = self.ask_kind(s)
        if kind == "permission":
            self.act_on(s, "waiting", winctl.reject_with, s["title"], text, pid=s["pid"])
        elif kind == "question":
            n_options = len(s["pending"][2]["questions"][0]["options"])
            self.act_on(s, "waiting", winctl.answer_other, s["title"], n_options, text, pid=s["pid"])
        else:
            return
        self.reply.clear()
        self.reply.clearFocus()
        self.reply_lock = None
        self.attention.discard(s["sid"])
        QTimer.singleShot(1200, self.refresh)

    def answer(self, s, key):
        """A button under a waiting card: "open", "esc" (deny) or a key to press ("1" allows)."""
        if key == "open":
            return winctl.focus(s["title"], s["pid"])
        if s["status"] == "waiting":         # only type into a prompt that is still there
            if key == "esc":
                self.act_on(s, "waiting", winctl.reject_with, s["title"], "", pid=s["pid"])
            else:
                self.act_on(s, "waiting", winctl.press, s["title"], key, pid=s["pid"])
            self.attention.discard(s["sid"])
            QTimer.singleShot(1200, self.refresh)

    def act_on(self, s, expect, action, *args, **kwargs):
        """Run action off the UI thread, only if the chat is still in the state its card showed.

        Typing into a terminal that moved on (a new prompt, another question) would answer the wrong thing,
        so the status file is read again right before acting. expect=None skips the check.
        """
        sfile, status_at = s["sfile"], s["status_at"]

        def job():
            status, at = session_state(sfile) if sfile else (expect, status_at)
            if expect and (status != expect or at != status_at):
                return
            try:
                action(*args, **kwargs)
            except Exception as e:
                print("action failed:", e, file=sys.stderr)
        threading.Thread(target=job, daemon=True).start()

    def quit_by_user(self):
        """Quit until a new chat starts or you start it again: prompts in open chats do not reopen it."""
        try:
            QUIT_MARK.parent.mkdir(exist_ok=True)
            QUIT_MARK.touch()
        except OSError:
            pass
        QApplication.quit()

    def toggle_island(self):
        """Hide the island until you show it again (the shortcut, the menu, or starting it again)."""
        self.island_hidden = not self.island_hidden
        if self.island_hidden:
            self.kb_open = False
            self.attention = set()
            if self.previewing():
                self.settings_win.close()
        self.apply_hover()
        if not self.island_hidden:
            self.stay_on_top(raise_front=True)    # you summoned it: come forward even past other notch apps

    def sync_hotkey(self):
        want = bool(self.cfg["global_hotkey"])
        if want and not self.hotkey:
            self.hotkey = PLAT.hotkey.register(lambda: QTimer.singleShot(0, self.toggle_island))
        elif not want and self.hotkey:
            PLAT.hotkey.unregister()
            self.hotkey = None

    def toggle_hide_all(self):
        if self.hider and self.hider.is_alive():   # still hiding from the last click
            return
        if winctl.HIDDEN:
            winctl.show_all(HIDDEN_FILE)
        else:   # counting tabs takes a second or two, so keep it off the UI thread
            chats = [(s["title"], s["pid"]) for s in self.sessions]
            self.hider = threading.Thread(target=winctl.hide_all, args=(chats, HIDDEN_FILE), daemon=True)
            self.hider.start()
        self.update()

    def new_chat_menu(self, pos):
        """Offer the folders of running chats (newest first), then trusted projects, then any folder."""
        known = [s["cwd"] for s in sorted(self.sessions, key=lambda x: -x["since"])]
        projects = (read_json(Path.home() / ".claude.json") or {}).get("projects") or {}
        known += [os.path.normpath(f) for f in projects]
        folders, seen = [], set()
        for f in known:
            if not f:
                continue
            key = os.path.normcase(os.path.normpath(f)).rstrip("\\/")
            if key not in seen and Path(f).is_dir():
                seen.add(key)
                folders.append(f)
        m = QMenu()
        m.setStyleSheet(self.menu.styleSheet())
        for f in folders[:8]:
            name = Path(f).name or f
            label = f"{name}    {f}" if name != f else f
            m.addAction(label, lambda _=False, f=f: winctl.new_chat(f))
        m.addSeparator()
        m.addAction("Other folder…", self.new_chat_in_chosen_folder)
        m.exec(pos)

    def new_chat_in_chosen_folder(self):
        folder = QFileDialog.getExistingDirectory(None, "Folder for the new Claude chat", str(Path.home()))
        if folder:
            winctl.new_chat(folder)

    # ---------------------------------------------------------------- layout
    def card_height(self, s):
        height = self.CARD_H + self.agents_height(s["sid"])
        kind = self.ask_kind(s)
        if kind:
            height += ASK_ROW_H
            if kind != "other" and s["sid"] == self.reply_sid:
                height += REPLY_H + 8
        return height

    def screen_geo(self):
        return (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()

    def bar_edges(self):
        if self.notch:
            return self.notch.top(), self.notch.top() + self.CH
        bottom = self.screen_geo().bottom() + 1 - int(self.cfg["dy"])
        return bottom - self.CH, bottom

    def expanded_height(self, decide=False):
        """Height of the open panel, and which way it opens.

        It opens up if it fits above the bar, else down if it fits below, else toward the bigger side showing
        only the cards that fit ("+N more"). The direction only changes while closed (or with decide).
        Also settles which chat the reply box answers, since that changes card heights.
        """
        self.reply_sid = self.pick_reply_sid()
        top = 10 + self.notch_pad() + self.HEAD_H + self.PILL_H + self.PILL_GAP
        heights = [self.card_height(s) + self.CARD_GAP for s in self.sessions]
        need = top + (sum(heights) if heights else 44) + 6
        g = self.screen_geo()
        bar_top, bar_bottom = self.bar_edges()
        room_up = bar_bottom - g.top() - self.M - 4
        room_down = g.bottom() + 1 - bar_top - self.M - 4
        if self.dock_side:             # on a side: the panel opens sideways, centred on the tab, any height
            room_down = room_up = g.height() - 2 * self.M - 8
        if decide or self.opening.x < 0.02:
            if self.dock_side:
                self.grow_down = True
            elif self.dock_bottom:     # standing on the taskbar: always opens upward
                self.grow_down = False
            else:
                self.grow_down = bool(self.notch) or (need > room_up and (need <= room_down or room_down > room_up))
        avail = room_down if self.grow_down else room_up
        if need <= avail or not heights:
            self.visible_k = len(heights)
            return need
        body, k = 0, 0
        for h in heights:
            if k and top + body + h + 24 > avail:
                break
            body += h
            k += 1
        self.visible_k = k
        return min(top + body + 24, max(avail, self.CH))

    # ---------------------------------------------------------------- macOS camera notch
    def size_bar(self):
        """Bar height and closed width: from the settings, or when docked, the notch plus a wing each side."""
        n = self.notch
        if self.dock_side and n:       # upright tab: CH is its thickness, mini_w its length down the edge
            self.CH, self.mini_w = n.width(), n.height() + 2 * self.notch_wing()
            return
        self.CH = n.height() if n else int(self.cfg["bar_height"])
        if self.companion():
            self.mini_w = COMPANION_W            # a small pill beside the notch, not the notch itself
        else:
            self.mini_w = n.width() + 2 * self.notch_wing() if n else self.CH + 4

    def notch_pad(self):
        """Docked under a real camera notch, the panel starts below it, so no button hides behind the camera."""
        n = self.notch
        if not n or self.dock_side:
            return 0
        if getattr(self, "_pad_for", None) != n:            # asking AppKit every frame is too slow
            self._pad_for, self._pad = n, max(0, n.height() - 6) if PLAT.look.notch_rect(self.screen()) else 0
        return self._pad

    def notch_wing(self):
        """Docked and closed, the island is the notch alone, with a small wing for the mascot while there is
        news: a chat working or waiting, or one that just finished."""
        busy = self.working() or self.attention or (self.toast and self.toast[0] in ("done", "waiting"))
        if not busy:
            return 0
        return WIN_WING if EDGE_DOCK else NOTCH_WING

    def dock(self, rect):
        """Dock into the notch rect, or undock with None. Docked, the island hangs from the top and opens down."""
        if rect == self.notch:
            return
        self.notch = rect
        self.dock_bottom = EDGE_DOCK and rect is not None and self.cfg.get("win_dock") == "bottom"
        side = self.cfg.get("win_dock")
        self.dock_side = side if (EDGE_DOCK or MAC_SIDES) and rect is not None and side in ("left", "right") else None
        self.size_bar()
        PLAT.look.keep_on_top(self, bool(rect) and not self.dock_side)
        if rect:
            self.grow_down = not self.dock_bottom
        self.apply_hover()
        self.apply_geometry()
        self.update()

    def notch_of(self, screen):
        """The screen's camera notch, or on a screen without one a notch-sized place at its top centre.

        Docked there, the island is a black pill hanging from the top edge, like Alcove on a Mac without notch.
        """
        if screen is not None and MAC_SIDES and self.cfg.get("win_dock") in ("left", "right"):
            return self.win_dock_rect(screen, self.cfg["win_dock"])
        n = PLAT.look.notch_rect(screen)
        if n is not None or screen is None:
            return n
        if EDGE_DOCK:
            return self.win_dock_rect(screen, self.cfg.get("win_dock"))
        g = screen.geometry()
        bar = screen.availableGeometry().top() - g.top()          # the macOS menu bar; 0 on Windows
        return QRect(g.center().x() + 1 - TOP_DOCK_W // 2, g.top(), TOP_DOCK_W, bar if bar >= 22 else 32)

    # ---------------------------------------------------------------- Windows dock (no camera notch)
    def apply_win_dock(self):
        """Windows: dock on the top edge or on the taskbar as win_dock says, or float when it is off."""
        c = self.cfg
        if c.get("win_dock") not in ("off", "top", "bottom", "left", "right"):   # first run: keep an older dock
            c["win_dock"] = "top" if c["notch"] else "off"
        c["notch"] = c["win_dock"] != "off"
        if self.dragging:
            return
        self.dock(self.notch_of(self.screen()) if c["notch"] else None)

    def win_dock_rect(self, screen, edge, pos=None):
        """The docked bar on the top edge of the screen or just above the taskbar, where you put it along that
        edge: pos (win_dock_pos) is in % of the edge, 0 = left end, 100 = right end."""
        a = screen.availableGeometry()
        pos = clamp(float(self.cfg.get("win_dock_pos", 50) if pos is None else pos) / 100)
        w = self.win_dock_w()
        span = a.width() - w - 2 * WIN_WING                    # the wings stay on screen at either end
        x = a.left() + WIN_WING + round(pos * span)
        if edge in ("left", "right"):  # upright tab: pos runs from the top (0 %) to the bottom (100 %)
            span = a.height() - w - 2 * WIN_WING
            y = a.top() + WIN_WING + round(pos * span)
            x = a.left() if edge == "left" else a.right() + 1 - WIN_DOCK_H
            return QRect(x, y, WIN_DOCK_H, w)
        if edge == "bottom":
            return QRect(x, a.bottom() + 1 - WIN_DOCK_H, w, WIN_DOCK_H)
        return QRect(x, screen.geometry().top(), w, WIN_DOCK_H)

    def win_dock_w(self):
        """Width of the docked bar in px, from Settings > Dock width."""
        return int(clamp(float(self.cfg.get("win_dock_w", WIN_DOCK_W)), 48, 400))

    def win_pos_at(self, screen, x, vertical=False):
        """win_dock_pos that puts the bar's centre under the global x (or y on a side)."""
        a = screen.availableGeometry()
        w = self.win_dock_w()
        start, length = (a.top(), a.height()) if vertical else (a.left(), a.width())
        span = max(1, length - w - 2 * WIN_WING)
        return round(clamp((x - start - WIN_WING - w / 2) / span) * 100, 1)

    def snap_to_win_dock(self, cursor):
        """While dragging: bring the bar near an edge (top, taskbar, left or right side), anywhere along it, and it
        docks there; docked, it slides along the edge under the cursor. It sticks: it lets go only when pulled
        WIN_STICK px away from its edge, or brought nearer another edge."""
        screen = QGuiApplication.screenAt(cursor) or self.screen()
        if not screen:
            return
        a, full = screen.availableGeometry(), screen.geometry()
        dist = {"top": cursor.y() - full.top(), "bottom": a.bottom() - cursor.y(),
                "left": cursor.x() - a.left(), "right": a.right() - cursor.x()}
        current = self.cfg.get("win_dock") if self.notch is not None else None
        edge = min(dist, key=dist.get)
        if dist[edge] > NOTCH_SNAP:
            edge = None
        if current in dist and dist[current] <= WIN_STICK and (edge is None or dist[edge] >= dist[current] - 4):
            edge = current             # docked: hold on to this edge until pulled well away
        if edge is None:
            if self.notch is not None:
                self.cfg["win_dock"] = "off"
                self.dock(None)
            return
        vertical = edge in ("left", "right")
        pos = self.win_pos_at(screen, cursor.y() if vertical else cursor.x(), vertical)
        self.cfg["win_dock"], self.cfg["win_dock_pos"] = edge, pos
        n = self.win_dock_rect(screen, edge, pos)
        if self.notch != n:
            self.notch = None          # a new place (or edge): dock() sets it all up again
            self.dock(n)

    def snap_to_mac_side(self, cursor):
        """macOS, while dragging: near the left or right side of the screen the bar docks there as an upright tab,
        anywhere along it, and slides with the cursor; it lets go when pulled WIN_STICK px away. True while the
        sides own the bar, so the notch logic is skipped; False lets the notch logic run as before."""
        screen = QGuiApplication.screenAt(cursor) or self.screen()
        if not screen:
            return False
        a = screen.availableGeometry()
        dist = {"left": cursor.x() - a.left(), "right": a.right() - cursor.x()}
        edge = min(dist, key=dist.get)
        if dist[edge] > NOTCH_SNAP:
            edge = None
        current = self.dock_side
        if current and dist[current] <= WIN_STICK and (edge is None or dist[edge] >= dist[current] - 4):
            edge = current
        if edge is None:
            if current:                # pulled off the side: float, and the notch can take it from here
                self.cfg["win_dock"] = "off"
                self.dock(None)
            return False
        pos = self.win_pos_at(screen, cursor.y(), vertical=True)
        self.cfg["win_dock"], self.cfg["win_dock_pos"] = edge, pos
        n = self.win_dock_rect(screen, edge, pos)
        if self.notch != n:
            self.notch = None
            self.dock(n)
        return True

    def follow_notch(self):
        """After a screen change, dock into the notch (or top centre) of the screen we are now on."""
        if self.notch is None and not self.cfg["notch"]:
            return
        self.dock(self.notch_of(self.screen()))

    def snap_to_notch(self, cursor):
        """While dragging, dock when the cursor enters a box a bit bigger than the notch, and undock when
        pulled well clear of it. The box is a forgiving target: step inside and the bar takes the notch
        style right away, so you see where it will land. A hysteresis margin stops it flickering at the edge.
        """
        if EDGE_DOCK:
            return self.snap_to_win_dock(cursor)
        if MAC_SIDES and self.snap_to_mac_side(cursor):
            return
        n = self.notch_of(self.screen())
        if not n:
            return
        near = QRect(n.left() - NOTCH_SNAP, n.top(), n.width() + 2 * NOTCH_SNAP, n.height() + NOTCH_SNAP)
        if self.notch:
            if not near.adjusted(-NOTCH_SNAP, 0, NOTCH_SNAP, NOTCH_SNAP).contains(cursor):
                self.dock(None)
        elif near.contains(cursor):
            self.dock(n)

    # ---------------------------------------------------------------- animation
    def springs(self):
        return self.opening, self.panel_height, self.visibility, self.bar_width

    def springs_settled(self):
        return all(sp.settled() for sp in self.springs())

    def kick(self):
        """Start the frame timer if anything moves; it stays off otherwise to save CPU."""
        if not self.frame.isActive() and self.frame_interval():
            self.last_frame = time.monotonic()
            self.frame.start()

    def frame_interval(self):
        """Milliseconds between frames, or 0 when nothing on screen moves."""
        if not self.springs_settled():
            return 16
        if not self.isVisible() or self.cfg["reduce_motion"]:
            return 0
        working, mode, spinning = self.working(), self.mascot_mode(), self.agents_spinning()
        # GIF mascots repaint themselves, only the drawn mascot needs frames
        drawn_mascot = self.mascot_image(mode) is None or (self.cfg["card_icon"] == "mascot" and self.opening.x > 0.5)
        if not (working or drawn_mascot or spinning):
            return 0
        if working or self.toast or spinning:
            return 33
        if self.is_mini() or mode == "sleep":
            return 100
        return 50

    def on_frame(self):
        now = time.monotonic()
        dt = clamp(now - self.last_frame, 0.0, 0.05)
        self.last_frame = now
        if not self.springs_settled():
            for sp in self.springs():
                sp.step(dt)
            vis = clamp(self.visibility.x)
            if vis > 0.01 and not self.isVisible():
                self.show()
                self.stay_on_top()
            opacity = vis * self.cfg["opacity"] / 100
            if abs(opacity - self.last_opacity) > 0.002:
                self.setWindowOpacity(opacity)
                self.last_opacity = opacity
            self.apply_geometry()
            if self.springs_settled() and vis <= 0.01 and self.isVisible():
                self.hide()
        self.update()
        interval = self.frame_interval()
        if not interval:
            self.frame.stop()          # the 1 s refresh repaints when the data changes
        elif self.frame.interval() != interval:
            self.frame.setInterval(interval)

    def apply_geometry(self):
        """Place the window; the shape is painted at its bottom-right (top centre when docked).

        During a transition the window is sized once to hold both the start and end shapes, so only the
        painting moves. Resizing a translucent window every frame flickers on Windows. The transparent part
        lets clicks through.
        """
        if self.dock_side and self.notch:
            return self.apply_side_geometry()
        h = max(lerp(self.CH, self.panel_height.x, self.opening.x), self.CH * 0.6)
        width = self.bar_width.x
        if self.springs_settled():
            win_w, win_h = width, max(h, self.CH)
            self.win_box = (0.0, 0.0)
        else:
            end_h = lerp(self.CH, self.panel_height.target, self.opening.target)
            win_w = max(width, self.bar_width.target, self.win_box[0])
            win_h = max(h, end_h * 1.04 + 4, self.CH, self.win_box[1])
            self.win_box = (win_w, win_h)
        inner_w, inner_h = math.ceil(win_w), math.ceil(win_h)
        outer_w, outer_h = inner_w + 2 * self.M, inner_h + 2 * self.M
        if self.notch:
            if self.companion():
                # Beside the notch: left-anchored at its right edge, so the pill holds still while it grows
                # rightward and downward. Clamped so an open panel stays on screen.
                g = self.screen_geo()
                x = min(self.notch.right() + COMPANION_GAP - self.M, g.right() + 1 - outer_w)
                y = self.notch.top()
                pill_x = self.notch.right() + COMPANION_GAP - x
            else:
                x, y = self.notch.center().x() + 1 - outer_w // 2, self.notch.top()
                pill_x = (outer_w - width) / 2
                if EDGE_DOCK:                # near a screen end the open panel slides over, the bar stays put
                    g = self.screen_geo()
                    x = clamp(x, g.left() - self.M, g.right() + 1 + self.M - outer_w)
                    pill_x = clamp(self.notch.center().x() + 1 - width / 2 - x, self.M, outer_w - self.M - width)
            pill_y = 0
            if self.dock_bottom:       # standing on the taskbar: the window ends at its top edge
                y = self.notch.bottom() + 1 - outer_h
                pill_y = outer_h - h
            if self.geometry().getRect() != (x, y, outer_w, outer_h):
                self.setGeometry(int(x), int(y), outer_w, outer_h)
            self.pill = QRectF(pill_x, pill_y, width, h)
            self.sync_glass()
            return
        g = self.screen_geo()
        # back on screen after a monitor change
        self.cfg["dx"] = clamp(self.cfg["dx"], 0, max(0, g.width() - self.W))
        self.cfg["dy"] = clamp(self.cfg["dy"], 0, max(0, g.height() - self.CH))
        slide = int((1 - clamp(self.visibility.x)) * 18)    # rises while fading in, like a toast
        x = g.right() + 1 - int(self.cfg["dx"]) - inner_w - self.M
        bar_top, bar_bottom = self.bar_edges()
        if self.grow_down:
            y, pill_y = bar_top - self.M + slide, self.M
        else:
            y, pill_y = bar_bottom + self.M + slide - outer_h, outer_h - self.M - h
        if self.geometry().getRect() != (x, y, outer_w, outer_h):
            self.setGeometry(x, y, outer_w, outer_h)
        self.pill = QRectF(outer_w - self.M - width, pill_y, width, h)
        self.sync_glass()

    def side_size(self, opening, bar_width, panel_h):
        """(width, height) of the shape docked on a side: an upright tab that grows sideways into the panel.
        The width follows bar_width (it leads, as on the top dock) and the height follows opening."""
        n = self.notch
        closed_len = min(bar_width, n.height() + 2 * WIN_WING)       # the tab and its wings
        fw = clamp((bar_width - self.mini_w) / max(1, self.W - self.mini_w), 0, 1.06)
        w = lerp(self.CH, self.W, fw)
        h = lerp(closed_len, panel_h, clamp(opening, 0, 1.06))
        return max(w, self.CH * 0.6), max(h, self.CH)

    def apply_side_geometry(self):
        """Docked on a side: the window hugs that edge, the shape is centred on the tab and kept on screen."""
        n, g = self.notch, self.screen_geo()
        width, h = self.side_size(self.opening.x, self.bar_width.x, self.panel_height.x)
        if self.springs_settled():
            win_w, win_h = width, h
            self.win_box = (0.0, 0.0)
        else:
            end_w, end_h = self.side_size(self.opening.target, self.bar_width.target, self.panel_height.target)
            win_w = max(width, end_w * 1.06, self.win_box[0])
            win_h = max(h, end_h * 1.06, self.win_box[1])
            self.win_box = (win_w, win_h)
        outer_w, outer_h = math.ceil(win_w) + self.M, math.ceil(win_h) + 2 * self.M
        x = n.left() if self.dock_side == "left" else n.right() + 1 - outer_w
        y = clamp(n.center().y() + 1 - outer_h // 2, g.top() - self.M, g.bottom() + 1 + self.M - outer_h)
        pill_x = 0 if self.dock_side == "left" else outer_w - width
        pill_y = clamp(n.center().y() + 1 - h / 2 - y, self.M, outer_h - self.M - h)
        if self.geometry().getRect() != (x, int(y), outer_w, outer_h):
            self.setGeometry(x, int(y), outer_w, outer_h)
        self.pill = QRectF(pill_x, pill_y, width, h)
        self.sync_glass()              # macOS: take the glass away while docked, like in the notch

    def paint_side_dock_bar(self, qp, r):
        """Docked on a side, closed: the mascot stands in the tab; while a chat works the tab grows longer, the
        mascot moves up and Claude's spark (or the amber / green dot) shows below it."""
        self.bar_pin = QRectF()
        wing = (r.height() - self.notch.height()) / 2
        k = clamp((wing - 6) / max(1, WIN_WING - 6))
        cx = r.center().x()
        y = lerp(r.center().y(), r.top() + wing / 2 + 4, k)
        self.paint_mascot(qp, QPointF(cx, y + 2), min(16, self.CH * 0.44), self.mascot_mode())
        if k <= 0.01:
            return
        base = qp.opacity()
        qp.setOpacity(base * k)
        c = QPointF(cx, r.bottom() - wing / 2 - 3)
        if any(s["status"] == "waiting" for s in self.sessions):
            color = AMBER
        elif self.toast and self.toast[0] == "done":
            color = GREEN
        else:
            color = None
            draw_spark(qp, c, 6.5, self.anim_t(), self.working(), CLAUDE)
        if color is not None:
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(color)
            qp.drawEllipse(c, 4, 4)
        qp.setOpacity(base)

    def liquid(self):
        """macOS 26 Liquid Glass is behind the shape: it brings its own shadow and edge."""
        return self.glassed and getattr(PLAT.look, "LIQUID", False)

    def sync_glass(self):
        """Keep the macOS glass under the painted shape. Docked in the notch the island stays black instead."""
        want = self.cfg["glass"] and PLAT.look.HAS_GLASS and self.notch is None
        if want or self.glassed:
            self.glassed = PLAT.look.glass(self, self.pill if want else None, self.RAD, BG.lightnessF() < 0.5)

    # ---------------------------------------------------------------- mouse
    def wants_front(self):
        """Whether the island should push itself to the very front right now.

        Docked, we stay a polite neighbour to other notch apps and only come forward when Claude has
        something to show or you are reaching for it; otherwise we hold our level without fighting for the
        top. Floating (no notch) we always stay on top, as before.
        """
        if self.notch is None:
            return True
        return bool(self.hover or self.lingering or self.dragging or self.kb_open or self.working()
                    or self.attention or self.toast or self.previewing() or self.opening.target > 0.01)

    def stay_on_top(self, raise_front=None):
        """Windows and macOS sometimes drop the island behind other apps; put it (and settings) back on top.

        raise_front None decides politely from wants_front(); pass True to force the island forward now.
        """
        if raise_front is None:
            raise_front = self.wants_front()
        in_notch = self.notch is not None and not self.dock_side
        PLAT.look.keep_on_top(self, in_notch, raise_front=raise_front)
        if self.settings_win and self.settings_win.isVisible():
            PLAT.look.keep_on_top(self.settings_win, in_notch)

    def enterEvent(self, e):
        self.stay_on_top()             # hovered: in front of everything, even if an app covered it
        self.hover_timer.start(self.cfg["hover_delay_ms"])

    def leaveEvent(self, e):
        self.hover_hit = None
        self.tip.hide()
        if self.attention and not self.reply.hasFocus():
            self.attention.clear()   # seen: back to plain hover behaviour
        self.hover_timer.start(int(self.cfg["linger_s"] * 1000) + 50)

    def apply_hover(self):
        """Decide whether the panel is open and whether the island is shown at all.

        It opens on hover (except over the small bar's pin) and lingers after the mouse leaves. It also stays
        open while a chat needs you, while you type a reply, while settings are open and after keyboard use.
        """
        local = QPointF(self.mapFromGlobal(QCursor.pos()))
        self.hover = self.isVisible() and self.pill.adjusted(-4, -4, 4, 4).contains(local)
        on_bar_pin = self.opening.x < 0.5 and self.bar_pin.contains(local)
        mono, linger_s = time.monotonic(), self.cfg["linger_s"]
        if self.hover:
            self.last_hover = mono
        self.lingering = self.opening.target == 1.0 and mono - self.last_hover < linger_s
        if self.lingering and not self.hover:
            self.hover_timer.start(int((linger_s - (mono - self.last_hover)) * 1000) + 50)
        typing = self.reply.hasFocus() and bool(self.reply.text())
        # Companion mode shows a compact strip for news instead of throwing the whole panel open, so a waiting
        # chat does not force the full detail; you still open it yourself by hovering.
        attention_opens = self.attention and not self.companion()
        keep_open = ((self.hover and not on_bar_pin) or self.lingering or attention_opens or typing
                     or self.previewing() or self.kb_open)
        want = 1.0 if keep_open and not self.dragging else 0.0
        if want != self.opening.target:
            if want and self.opening.x < 0.05:
                self.panel_height.target = self.panel_height.x = self.expanded_height(decide=True)
            if self.notch is not None and (EDGE_DOCK or self.dock_side):   # edge or side dock: Dynamic Island
                mode = "open" if want else "close"
                self.bar_width.tune(*self.win_springs[mode + "_w"])
                self.opening.tune(*self.win_springs[mode + "_h"])
            else:
                for sp in (self.opening, self.bar_width):
                    sp.tune(*(self.open_spring if want else self.close_spring))
        self.opening.target = want
        if self.companion() and not want:
            # closed: a slim strip (mascot + one line) when there is news, otherwise just the mascot pill
            self.bar_width.target = COMPANION_NOTIF_W if self.has_news() else self.mini_w
        else:
            self.bar_width.target = self.mini_w if self.is_mini() and not want else self.W
        self.visibility.target = 1.0 if self.should_show() else 0.0
        if not want:
            self.tip.hide()            # the panel is closing: no tooltip should linger over the bar
        self.kick()

    def hit_at(self, pos):
        """The (action, sid) under pos, or None."""
        if self.opening.x < 0.5:                     # small bar: only its pin is a button
            return ("pin", "bar") if self.bar_pin.contains(pos) else None
        if self.opening.x < 0.85:                    # panel still opening: buttons are not in place yet
            return None
        return next(((action, sid) for rect, action, sid in self.hits if rect.contains(pos)), None)

    def tooltip(self, action, sid):
        if action in TIPS:
            return TIPS[action]
        if action == "pin":
            return "Unpin (hide when idle)" if self.pinned else "Pin: stay on screen when idle"
        if action == "hideall":
            return "Show all chats" if winctl.HIDDEN else "Hide all chats in the island"
        if action.startswith("limit:"):
            return self.limit_tip(action[len("limit:"):])
        s = find(self.sessions, sid)
        if s and action == "usage":
            return card_tip(s)
        if s and action.startswith("agent:"):
            agent = next((a for a in s["agents"] if a["id"] == action[len("agent:"):]), None)
            return agent_tip(agent, time.time()) if agent else None
        return None

    def limit_tip(self, key):
        """A limit pill's tooltip; the Session pill adds what all open chats used."""
        now = time.time()
        pct, _, reset = self.limit_state(key, now)
        name = "Session (5 h)" if key == "five_hour" else "Week"
        if pct is None:
            lines = [f"{name} limit: not known yet", settings.limits_report()[1][-1]]
        elif reset:
            lines = [f"{name} limit: {pct:.0f}% used, resets in {fmt_dur(reset - now, coarse=True)}"]
        else:
            lines = [f"{name} limit: {pct:.0f}% used"]
        if key == "five_hour" and self.sessions:
            usage = usage_text([s["usage"] for s in self.sessions], with_time=False)
            if usage:
                lines.append(f"Open chats: {usage}")
            running = [a for s in self.sessions for a in running_agents(s)]
            if running:
                tokens = sum(a["tokens"] or 0 for a in running)
                lines.append(f"Running sub-agents: {len(running)} · {fmt_tokens(tokens)} tokens")
        return "\n".join(lines)

    def collapse_for_drag(self):
        """Snap the panel shut at the start of a drag, so the window stays a fixed-size bar while it moves.

        Dragging the open panel is jumpy: it resizes every frame (and can flip from opening upward to
        downward as it nears an edge) while it is anchored to a screen corner. Collapsed, only the bar moves.
        """
        self.tip.hide()
        self.hover = self.lingering = self.kb_open = False
        self.attention.clear()
        for sp in (self.opening, self.bar_width):
            sp.tune(*self.close_spring)
        self.opening.x = self.opening.target = 0.0
        self.bar_width.x = self.bar_width.target = self.mini_w if self.is_mini() else self.W
        self.win_box = (0.0, 0.0)

    def place_under_cursor(self, gp):
        """While dragging, keep the compact bar centred under the cursor, so it moves with the pointer
        instead of drifting away from a corner anchor ("moving it from afar")."""
        g = self.screen_geo()
        width = self.bar_width.target or self.W
        self.cfg["dx"] = clamp(g.right() + 1 - gp.x() - width / 2, 0, g.width() - self.W)
        self.cfg["dy"] = clamp(g.bottom() + 1 - gp.y() - self.CH / 2, 0, g.height() - self.CH)

    def mousePressEvent(self, e):
        self.activateWindow()                    # a click gives the island the keyboard (Esc, arrows, Ctrl+…)
        self.setFocus()
        if e.button() == Qt.MouseButton.LeftButton:
            self.press_at = (e.globalPosition().toPoint(), self.cfg["dx"], self.cfg["dy"])
            self.press_hit = self.hit_at(e.position())
            self.dragging = False

    def mouseMoveEvent(self, e):
        if self.press_at and e.buttons() & Qt.MouseButton.LeftButton:
            start, _dx0, _dy0 = self.press_at
            gp = e.globalPosition().toPoint()
            was_dragging = self.dragging
            self.dragging = self.dragging or (gp - start).manhattanLength() > 6
            if self.dragging:
                if not was_dragging:
                    self.collapse_for_drag()     # drag the compact bar, not the resizing open panel
                self.place_under_cursor(gp)      # the bar follows the pointer
                self.snap_to_notch(gp)
                self.apply_geometry()
            return
        hit = self.hit_at(e.position())
        if hit != self.hover_hit:
            self.hover_hit = hit
            clickable = hit and not hit[0].startswith("limit:")   # the limit pills only have a tooltip
            self.setCursor(Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor)
            tip = self.tooltip(*hit) if hit else None
            self.tip.show_text(QCursor.pos(), tip, self.notch is not None and not self.dock_side)
            self.update()
        if self.opening.target == 0.0 and hit != ("pin", "bar"):
            self.hover_timer.start(self.cfg["hover_delay_ms"])   # moved off the bar's pin: open after a rest

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or not self.press_at:
            return
        self.press_at = None
        if self.dragging:
            self.dragging = False
            self.cfg["notch"] = self.notch is not None
            if MAC_SIDES:
                self.cfg["notch"] = self.notch is not None and not self.dock_side
                self.cfg["win_dock"] = self.dock_side or "off"
            if EDGE_DOCK:
                if self.notch is None:
                    self.cfg["win_dock"] = "off"
                elif self.dock_side:       # left or right: keep the side it was dropped on
                    self.cfg["win_dock"] = self.dock_side
                else:
                    self.cfg["win_dock"] = "bottom" if self.dock_bottom else "top"
            settings.save(self.cfg)
            return self.apply_hover()
        hit = self.hit_at(e.position())
        if hit != self.press_hit:            # the list moved under the mouse: not a click
            return
        if not hit:
            if self.opening.x < 0.5:         # the small bar: jump to the chat that is busy
                active = [s for s in self.sessions if s["status"] != "idle"] or self.sessions
                if active:
                    winctl.focus(active[0]["title"], active[0]["pid"])
            return
        self.do(*hit, self.mapToGlobal(e.position().toPoint()))

    def do(self, action, sid, pos=None):
        """Run a button or card action; the keyboard uses this too."""
        s = find(self.sessions, sid)
        if action == "pin":
            self.toggle_pin()
        elif action == "hideall":
            self.toggle_hide_all()
        elif action == "newchat":
            self.new_chat_menu(pos or self.mapToGlobal(self.pill.topRight().toPoint()))
        elif action == "settings":
            self.open_settings(toggle=True)
        elif action == "quit":
            if self.confirm and self.confirm[:2] == (None, "quit"):
                return self.quit_by_user()
            self.confirm = (None, "quit", time.time() + 4)
        elif action == "send":
            self.send_reply()
        elif action.startswith("limit:"):
            pass                             # a tooltip only
        elif s and (action in ("card", "usage") or action.startswith("agent:")):
            winctl.focus(s["title"], s["pid"])
        elif s and action.startswith("ans:"):
            self.answer(s, action[4:])
        elif s and self.confirm and self.confirm[:2] == (sid, action):   # second click on X or Compact
            self.confirm = None
            if action == "close":
                still_same = partial(same_process, s["pid"], s["sfile"])
                self.act_on(s, None, winctl.close, s["title"], s["pid"], still_same)
            elif s["status"] == "idle":      # typing is only safe at an idle prompt
                self.act_on(s, "idle", winctl.send_command, s["title"], "/compact", pid=s["pid"])
            QTimer.singleShot(1500, self.refresh)
        elif s:
            self.confirm = (sid, action, time.time() + 4)
        self.update()

    def contextMenuEvent(self, e):
        self.menu.exec(e.globalPos())

    # ---------------------------------------------------------------- keyboard (once the island was clicked)
    def keyPressEvent(self, e):
        k, mods = e.key(), e.modifiers()
        K = Qt.Key
        ctrl = bool(mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier))
        shortcuts = {
            K.Key_Comma: partial(self.open_settings, toggle=True),
            K.Key_N: partial(self.do, "newchat", None),
            K.Key_P: self.toggle_pin,
            K.Key_H: self.toggle_hide_all,
            K.Key_R: self.refresh,
            K.Key_Q: self.quit_by_user,
            K.Key_W: self.toggle_island,
        }
        if ctrl and k in shortcuts:
            shortcuts[k]()
            return
        if k == K.Key_Escape:
            if self.confirm:
                self.confirm = None
            elif self.previewing():
                self.settings_win.close()
            else:
                self.kb_open = False
                self.last_hover = 0.0
                self.attention = set()
                self.clearFocus()
            self.apply_hover()
            return self.update()
        order = [s["sid"] for s in self.sessions[:self.visible_k or len(self.sessions)]]
        cur = self.hover_hit[1] if self.hover_hit and self.hover_hit[1] in order else None
        if k in (K.Key_Down, K.Key_Up, K.Key_Tab, K.Key_Backtab) and order:
            back = k in (K.Key_Up, K.Key_Backtab) or (k == K.Key_Tab and mods & Qt.KeyboardModifier.ShiftModifier)
            if cur:
                i = order.index(cur) + (-1 if back else 1)
            else:
                i = len(order) - 1 if back else 0
            self.hover_hit = ("card", order[i % len(order)])
            self.kb_open = True
        elif k in (K.Key_Return, K.Key_Enter) and cur:
            self.do("card", cur)
        elif k == K.Key_Delete and cur:
            self.do("close", cur)              # like the X, the first press only asks
        elif k in (K.Key_F1, K.Key_Question):
            self.tip.show_text(self.mapToGlobal(self.pill.topLeft().toPoint()), KEYS_HELP,
                               self.notch is not None and not self.dock_side)
        else:
            return super().keyPressEvent(e)
        self.apply_hover()
        self.update()

    def focusOutEvent(self, e):
        self.kb_open = False
        self.apply_hover()
        super().focusOutEvent(e)

    def event(self, e):
        # Qt uses Tab to move focus between child widgets; here it picks the next card instead
        is_tab = e.type() == QEvent.Type.KeyPress and e.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab)
        if is_tab and not self.reply.hasFocus():
            self.keyPressEvent(e)
            return True
        return super().event(e)

    # ---------------------------------------------------------------- painting helpers
    def metrics(self, f):
        key = f.key()
        fm = self._metrics.get(key)
        if fm is None:
            fm = self._metrics[key] = QFontMetrics(f)
        return fm

    def elided(self, s, f, w):
        """s cut with … to fit w pixels. Cached because the same strings are drawn every frame."""
        key = (s, f.key(), int(max(0, w)))
        cut = self._elided.get(key)
        if cut is None:
            if len(self._elided) > 500:
                self._elided.clear()
            cut = self._elided[key] = self.metrics(f).elidedText(s, Qt.TextElideMode.ElideRight, key[2])
        return cut

    def draw_right(self, qp, right, y, h, s, f, color, pad=2):
        """Draw one line ending at right. Returns its left edge."""
        w = self.metrics(f).horizontalAdvance(s) + pad
        self.draw_text(qp, right - w, y, w, h, s, f, color, Qt.AlignmentFlag.AlignRight)
        return right - w

    def draw_text(self, qp, x, y, w, h, s, f, color, align=Qt.AlignmentFlag.AlignLeft):
        """Draw one line, cut with … when too long."""
        qp.setFont(f)
        qp.setPen(color)
        qp.drawText(QRectF(x, y, w, h), int(align | Qt.AlignmentFlag.AlignVCenter), self.elided(s, f, w))

    def anim_t(self):
        return 0.5 if self.cfg["reduce_motion"] else time.monotonic() - self.t0

    def mascot_image(self, mode):
        """The user's picture or GIF for this state as a pixmap, or None to draw the built-in mascot."""
        path = self.cfg[f"mascot_{mode}"] or self.cfg["mascot_file"]
        if not path:
            return None
        if path not in self.movies:
            movie = QMovie(path)
            if movie.isValid() and movie.frameCount() != 1:
                movie.setCacheMode(QMovie.CacheMode.CacheAll)
                movie.frameChanged.connect(self.on_gif_frame)
                if self.cfg["reduce_motion"]:
                    movie.jumpToFrame(0)
                else:
                    movie.start()
                self.movies[path] = movie
            else:
                self.movies[path] = QPixmap(path)
        item = self.movies[path]
        pix = item.currentPixmap() if isinstance(item, QMovie) else item
        return None if pix.isNull() else pix

    def on_gif_frame(self, _frame):
        if self.isVisible() and not self.frame.isActive():   # a running frame timer repaints anyway
            self.update()

    def paint_mascot(self, qp, c, height, mode, t=None):
        height *= self.cfg["mascot_size"] / 100
        pix = self.mascot_image(mode)
        if pix is None:
            draw_mascot(qp, c, height, self.anim_t() if t is None else t, mode)
            return
        k = height * 1.5 / max(pix.width(), pix.height())
        w, h = pix.width() * k, pix.height() * k
        qp.save()
        qp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        qp.drawPixmap(QRectF(c.x() - w / 2, c.y() - h / 2, w, h), pix, QRectF(pix.rect()))
        qp.restore()

    # ---------------------------------------------------------------- painting
    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        qp.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        r, p = self.pill, clamp(self.opening.x)
        if self.notch:
            bg = NOTCH_BLACK
        elif self.glassed:              # the blur shows through a lighter tint of the background colour
            tint = LIQUID_TINT if self.liquid() else GLASS_TINT
            bg = QColor(BG.red(), BG.green(), BG.blue(), round(BG.alpha() * tint))
        else:
            bg = BG
        rad = self.RAD
        if self.notch:                  # small and tight round the notch, softer as it opens, like Alcove
            rad = lerp(min(self.CH * 0.42, 14), 26, p)
        flush = self.notch is not None and not self.companion()   # companion is a free pill, rounded all round
        shape = paint_frame(qp, r, rad, bg, BG.alphaF(), snap=1 if self.springs_settled() else 4,
                            flush_top=flush and not self.dock_bottom and not self.dock_side, glass=self.glassed,
                            ear=NOTCH_EAR, native_edge=self.liquid() and not self.notch,
                            flush_bottom=flush and self.dock_bottom, flush_side=self.dock_side if flush else None)
        qp.setClipPath(shape)
        self.hits = []
        bar_alpha = clamp(1 - p * 4)    # the bar's content is gone by p = 0.25, before the panel's appears
        if bar_alpha > 0:
            qp.save()
            qp.setOpacity(ease_out(bar_alpha))
            qp.translate(0, p * (-12 if self.grow_down else 12))
            self.paint_bar(qp, r)
            qp.restore()
        if p > 0.2:
            self.paint_panel(qp, r)
            if p < 0.995:               # feather the growing edge so text is never seen sliced
                qp.setOpacity(1)
                if self.grow_down:
                    edge = r.bottom() - 18
                    fade = QLinearGradient(0, edge + 18, 0, edge)
                else:
                    edge = r.top()
                    fade = QLinearGradient(0, edge, 0, edge + 18)
                fade.setColorAt(0, BG)
                fade.setColorAt(1, QColor(BG.red(), BG.green(), BG.blue(), 0))
                qp.fillRect(QRectF(r.left(), edge, r.width(), 18), fade)
        if self.working() and p < 0.5 and not self.cfg["reduce_motion"] and not self.notch:   # orange line along the bar
            qp.setOpacity(1 - p * 2)
            seg = r.width() * 0.28
            x = r.left() + (((time.monotonic() - self.t0) * 0.55) % 1.0) * (r.width() + seg) - seg
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(CLAUDE)
            qp.setClipRect(QRectF(r.left() + rad, r.top(), r.width() - 2 * rad, r.height()),
                           Qt.ClipOperation.IntersectClip)    # the straight part of the edge, clear of the corners
            qp.drawRoundedRect(QRectF(x, r.bottom() - 2.5, seg, 2.5), 1.2, 1.2)
        qp.end()
        if self.reply.isVisible() or (p > 0.95 and not self.reply_rect.isNull()):
            QTimer.singleShot(0, self.sync_reply)   # moving a child widget inside paintEvent is not allowed

    def sync_reply(self):
        """Keep the real text box over the space the painted card left for it."""
        show = self.opening.x > 0.95 and not self.reply_rect.isNull() and self.isVisible()
        if show:
            if self.reply.geometry() != self.reply_rect.toRect():
                self.reply.setGeometry(self.reply_rect.toRect())
            s = find(self.sessions, self.reply_sid)
            if s and self.ask_kind(s) == "permission":
                hint = "Or tell Claude what to do instead…"
            else:
                hint = "Type your own answer…"
            if self.reply.placeholderText() != hint:
                self.reply.setPlaceholderText(hint)
        if show != self.reply.isVisible():
            self.reply.setVisible(show)
            if not show:
                self.reply.clearFocus()

    def bar_lines(self, now):
        """The small bar's two lines of text and the second line's colour."""
        active = [s for s in self.sessions if s["status"] != "idle"]
        waiting = [s for s in active if s["status"] == "waiting"]
        done = self.toast[1] if self.toast and self.toast[0] == "done" else None
        if len(active) == 1:
            s = active[0]
            if waiting:
                return s["title"], "Needs you", AMBER
            if done:
                return s["title"], f"{done} finished", GREEN
            n = len(running_agents(s)) if self.cfg["show_agents"] else 0
            agents = f" · {n} agent{'s' if n != 1 else ''}" if n else ""
            return s["title"], f"{fmt_dur(now - s['since'])}{agents} · {doing(s, 'Working')}", GRAY
        if active:
            title = f"{len(active)} chats in progress"
            if len(waiting) == 1:
                return title, f"{waiting[0]['title']} needs you", AMBER
            if waiting:
                return title, f"{len(waiting)} chats need you", AMBER
            if done:
                return title, f"{done} finished", GREEN
            verbs = list(dict.fromkeys(verb(s["tool"]) for s in sorted(active, key=lambda x: -x["since"])))
            return title, " · ".join(verbs[:3]), GRAY
        if done:
            return done, "Finished", GREEN
        n = len(self.sessions)
        if not n:
            return "Claude Code", "not running", DIM
        return "Claude Code", f"{n} chat{'s' if n != 1 else ''} idle", DIM

    def pin_color(self, over, lit):
        """Accent when pinned and under the mouse, lit when only under the mouse, icon grey otherwise."""
        if not over:
            return ICON
        return CLAUDE_LIGHT if self.pinned else lit

    def paint_bar(self, qp, r):
        if self.dock_side and self.notch:
            return self.paint_side_dock_bar(qp, r)
        top = r.top() if self.grow_down else r.bottom() - self.CH
        cy = top + self.CH / 2
        offset = (self.CH - 56) / 2      # the text layout is designed for a 56 px bar, centred in others
        left = r.right() - self.W
        full = clamp((self.bar_width.x - self.mini_w) / max(1, self.W - self.mini_w))   # 0 mini .. 1 full width
        if self.notch and full < 0.35:
            if self.companion():
                return self.paint_companion_pill(qp, r)
            return self.paint_notch_wings(qp, r)
        mascot_x = lerp(r.center().x(), r.left() + 32, full)
        self.paint_mascot(qp, QPointF(mascot_x, cy + 2), 20 if full > 0.5 else 22, self.mascot_mode())
        if full < 0.35:                  # mini: the mascot alone
            self.bar_pin = QRectF()
            return
        base = qp.opacity()
        qp.setOpacity(base * clamp((full - 0.35) / 0.65))
        line1, line2, color2 = self.bar_lines(time.time())
        pin_c = QPointF(r.right() - 14, top + 14)
        self.bar_pin = QRectF(pin_c.x() - 11, pin_c.y() - 10, 22, 20)
        if self.hover or self.pinned:
            draw_pin(qp, pin_c, 10, self.pin_color(self.hover_hit == ("pin", "bar"), WHITE_200), upright=self.pinned)
        right = r.right() - 30
        pct = self.limit_state("five_hour", time.time())[0]
        if pct is not None:
            color = limit_color(pct)
            draw_ring(qp, QPointF(right - 8, cy - 6), pct, 8.0, color)
            self.draw_text(qp, right - 30, cy + 4, 44, 16, f"{pct:.0f}%", self.f_small, color,
                           Qt.AlignmentFlag.AlignHCenter)
            right -= 40
        x = left + 56
        self.draw_text(qp, x, top + offset + 9, right - x, 20, line1, self.f_main, WHITE)
        self.draw_text(qp, x, top + offset + 28, right - x, 18, line2, self.f_body, color2)
        qp.setOpacity(base)

    def paint_companion_pill(self, qp, r):
        """Companion mode, closed: a small Claude mascot in a pill beside the notch. The mascot animates for
        its state (coding/waiting/done/idle); a coloured dot flags a chat that needs you or just finished."""
        self.bar_pin = QRectF()
        cy = r.top() + self.CH / 2
        self.paint_mascot(qp, QPointF(r.center().x(), cy + 1), min(16, self.CH * 0.46), self.mascot_mode())
        if any(s["status"] == "waiting" for s in self.sessions):
            color = AMBER
        elif self.toast and self.toast[0] == "done":
            color = GREEN
        else:
            color = None
        if color is not None:
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(color)
            qp.drawEllipse(QPointF(r.right() - 8, r.top() + 8), 3.5, 3.5)

    def paint_notch_wings(self, qp, r):
        """Docked and closed: the working mascot peeking out left of the notch, a dot right of it when a chat
        needs you or just finished. Idle, the wings are folded away and only the notch is left."""
        self.bar_pin = QRectF()
        wing = (r.width() - self.notch.width()) / 2      # follows the width spring as the wings open
        if EDGE_DOCK:
            return self.paint_win_dock_bar(qp, r, wing)
        if wing < 12:
            return
        base = qp.opacity()
        qp.setOpacity(base * clamp((wing - 12) / (NOTCH_WING - 12)))
        cy = (r.top() if self.grow_down else r.bottom() - self.CH) + self.CH / 2
        self.paint_mascot(qp, QPointF(r.left() + wing / 2 + 2, cy + 2), min(16, self.CH * 0.44), self.mascot_mode())
        if any(s["status"] == "waiting" for s in self.sessions):
            color = AMBER
        elif self.toast and self.toast[0] == "done":
            color = GREEN
        else:
            color = None
        if color is not None:
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(color)
            qp.drawEllipse(QPointF(r.right() - wing / 2 - 2, cy), 4, 4)
        qp.setOpacity(base)

    def paint_win_dock_bar(self, qp, r, wing):
        """Windows dock, closed: the Claude mascot is always there. Idle it sits in the middle of the bar; when a
        chat works it glides out into the left wing as the bar widens, and a dot on the right flags a chat that
        needs you or just finished (Claude's turning spark there while it just works)."""
        k = clamp((wing - 6) / max(1, WIN_WING - 6))     # 0 idle bar .. 1 wings fully out
        cy = (r.top() if self.grow_down else r.bottom() - self.CH) + self.CH / 2
        x = lerp(r.center().x(), r.left() + wing / 2 + 4, k)
        self.paint_mascot(qp, QPointF(x, cy + 2), min(16, self.CH * 0.44), self.mascot_mode())
        if k <= 0.01:
            return
        if any(s["status"] == "waiting" for s in self.sessions):
            color = AMBER
        elif self.toast and self.toast[0] == "done":
            color = GREEN
        else:                          # just working: Claude's spark turns in the right wing, no empty black
            base = qp.opacity()
            qp.setOpacity(base * k)
            draw_spark(qp, QPointF(r.right() - wing / 2 - 3, cy), 6.5, self.anim_t(), self.working(), CLAUDE)
            qp.setOpacity(base)
            return
        base = qp.opacity()
        qp.setOpacity(base * k)
        qp.setPen(Qt.PenStyle.NoPen)
        qp.setBrush(color)
        qp.drawEllipse(QPointF(r.right() - wing / 2 - 3, cy), 4, 4)
        qp.setOpacity(base)

    def reveal(self, qp, r, y, h):
        """Fade and raise one panel block as the panel opens, blocks nearest the bar first."""
        full_h = max(1.0, self.panel_height.x)
        mid = y + h / 2
        from_bar = clamp((mid - r.top() if self.grow_down else r.bottom() - mid) / full_h)
        a = ease_out((clamp(self.opening.x) - 0.30 - 0.28 * from_bar) / 0.40)
        qp.setOpacity(a)
        qp.translate(0, (1 - a) * 10)
        if self.notch is not None and (EDGE_DOCK or self.dock_side):   # each block grows in from 92 % of its size
            k = 0.92 + 0.08 * a
            qp.translate(r.center().x(), mid)
            qp.scale(k, k)
            qp.translate(-r.center().x(), -mid)

    def paint_panel(self, qp, r):
        now, t = time.time(), self.anim_t()
        left = r.left() if self.dock_side == "left" else r.right() - self.W   # left dock: content stays put
        x0, width = left + 12, self.W - 24
        # blocks are drawn at their final place and uncovered as the shape grows
        y = (r.top() + 10 + self.notch_pad()) if self.grow_down else (r.bottom() - self.panel_height.x + 10)
        qp.save()
        self.reveal(qp, r, y, self.HEAD_H)
        self.paint_header(qp, x0, y, width)
        qp.restore()
        y += self.HEAD_H
        half = (width - 8) / 2
        qp.save()
        self.reveal(qp, r, y, self.PILL_H)
        for i, key in enumerate(("five_hour", "seven_day")):
            rc = QRectF(x0 + i * (half + 8), y, half, self.PILL_H)
            self.paint_limit_pill(qp, rc, key, now)
            self.hits.append((rc, "limit:" + key, None))
        qp.restore()
        y += self.PILL_H + self.PILL_GAP
        qp.setOpacity(ease_out((clamp(self.opening.x) - 0.5) / 0.4))
        self.reply_rect = QRectF()          # set again below by the card that shows the reply box
        if not self.sessions:
            self.draw_text(qp, x0, y, width, 36, "No Claude Code session running", self.f_body, DIM,
                           Qt.AlignmentFlag.AlignHCenter)
            return
        shown = self.visible_k or len(self.sessions)
        for s in self.sessions[:shown]:
            h = self.card_height(s)
            qp.save()
            self.reveal(qp, r, y, h)
            self.paint_card(qp, QRectF(x0, y, width, h), s, now, t)
            qp.restore()
            y += h + self.CARD_GAP
        if len(self.sessions) > shown:
            self.draw_text(qp, x0, y - 4, width, 16, f"+{len(self.sessions) - shown} more", self.f_small, DIM,
                           Qt.AlignmentFlag.AlignHCenter)

    def paint_header(self, qp, x0, y, width):
        """Mascot on the left; quit, settings, new chat, hide all and pin on the right."""
        pin_c = QPointF(x0 + width - 8, y + 12)
        quit_c = QPointF(pin_c.x() - 106, pin_c.y())
        gear_c = QPointF(pin_c.x() - 80, pin_c.y())
        plus_c = QPointF(pin_c.x() - 54, pin_c.y())
        eye_c = QPointF(pin_c.x() - 28, pin_c.y())
        for c, action in ((quit_c, "quit"), (gear_c, "settings"), (plus_c, "newchat"), (eye_c, "hideall")):
            self.hits.append((QRectF(c.x() - 11, c.y() - 9, 22, 18), action, None))
        self.hits.append((QRectF(pin_c.x() - 12, pin_c.y() - 10, 24, 20), "pin", None))
        over = self.hover_hit[0] if self.hover_hit and self.hover_hit[1] is None else None
        hidden = bool(winctl.HIDDEN)
        if hidden:
            eye_color = CLAUDE_LIGHT
        elif over == "hideall":
            eye_color = WHITE_220
        else:
            eye_color = ICON
        asking = bool(self.confirm and self.confirm[:2] == (None, "quit"))
        draw_power(qp, quit_c, 12, CLOSE_RED if asking or over == "quit" else ICON, filled=asking)
        draw_gear(qp, gear_c, 12, CLAUDE_LIGHT if over == "settings" else ICON)
        draw_plus(qp, plus_c, 11, CLAUDE_LIGHT if over == "newchat" else ICON)
        draw_eye(qp, eye_c, 13, eye_color, slashed=hidden)
        draw_pin(qp, pin_c, 11, self.pin_color(over == "pin", WHITE_170), upright=self.pinned)
        self.paint_mascot(qp, QPointF(x0 + 13, y + 13), 16, self.mascot_mode())

    def paint_limit_pill(self, qp, rc, key, now):
        """Ring, name and used %, over a thin bar showing how much of the window has gone by."""
        qp.setPen(Qt.PenStyle.NoPen)
        qp.setBrush(CARD)
        qp.drawRoundedRect(rc, 8, 8)
        pct, start, reset = self.limit_state(key, now)
        row = QRectF(rc.left() + 12, rc.top() + 7, rc.width() - 24, 20)
        color = limit_color(pct or 0)
        draw_ring(qp, QPointF(row.left() + 6, row.center().y()), pct, 6, color)
        name = "Session" if key == "five_hour" else "Week"
        self.draw_text(qp, row.left() + 20, row.top(), 90, 20, name, self.f_body, GRAY)
        if pct is None:
            self.draw_text(qp, row.right() - 50, row.top(), 50, 20, "–", self.f_bold, DIM, Qt.AlignmentFlag.AlignRight)
        else:
            self.draw_text(qp, row.right() - 50, row.top(), 50, 20, f"{pct:.0f}%", self.f_bold, color,
                           Qt.AlignmentFlag.AlignRight)
        bar = QRectF(rc.left() + 12, rc.bottom() - 11, rc.width() - 24, 3)
        qp.setPen(Qt.PenStyle.NoPen)
        qp.setBrush(TRACK)
        qp.drawRoundedRect(bar, 1.5, 1.5)
        gone = clamp((now - start) / (reset - start)) if start and reset else 0
        if gone > 0:
            qp.setBrush(TIME_BAR)
            qp.drawRoundedRect(QRectF(bar.left(), bar.top(), max(3.0, bar.width() * gone), 3), 1.5, 1.5)

    def small_button(self, qp, rect, label, hovered, confirming, color):
        if confirming:                    # filled, with a "?": click again to do it
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(color)
            qp.drawRoundedRect(rect, 4, 4)
            label += "?"
            color = WHITE if color == CLOSE_RED else INK
        else:
            qp.setBrush(QColor(color.red(), color.green(), color.blue(), 60 if hovered else 0))
            qp.setPen(QPen(color, 1))
            qp.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        self.draw_text(qp, rect.left(), rect.top(), rect.width(), rect.height(), label, self.f_small, color,
                       Qt.AlignmentFlag.AlignHCenter)

    def paint_card_icon(self, qp, c, tk, color, t):
        style = self.cfg["card_icon"]
        if style == "star":
            draw_spark(qp, c, 7, t, tk == "working", color)
        elif style == "dot":             # breathes while its chat works
            radius = 4 + (math.sin(t * 5) if tk == "working" else 0)
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(color)
            qp.drawEllipse(c, radius, radius)
        elif style == "mascot":
            self.paint_mascot(qp, c, 10, TIERS[tk][2])

    def paint_card(self, qp, rc, s, now, t):
        """One chat's card: title and state, then what it does and its context use.

        Hovering shows the X and Compact buttons. A waiting card adds its question and answer buttons.
        """
        sid, tk = s["sid"], tier(s, now)
        label, color, _ = TIERS[tk]
        hovered = bool(self.hover_hit) and self.hover_hit[1] == sid
        confirming = self.confirm[1] if self.confirm and self.confirm[0] == sid else None
        base = qp.opacity()
        qp.setPen(Qt.PenStyle.NoPen)
        qp.setBrush(CARD_HOVER if hovered else CARD)
        qp.drawRoundedRect(rc, 6, 6)
        if tk == "waiting":
            qp.setBrush(QColor(color.red(), color.green(), color.blue(), 18))
            qp.drawRoundedRect(rc, 6, 6)
        if tk == "forgotten" and not hovered:          # dim the content, not the card itself
            qp.setOpacity(base * 0.55)
        qp.setBrush(color)
        qp.drawRoundedRect(QRectF(rc.left(), rc.top() + 10, 3, rc.height() - 20), 1.5, 1.5)   # state stripe
        x, y = rc.left() + 10, rc.top()
        kind = self.ask_kind(s)

        # line 1: icon, title, state, and the X button
        right = rc.right() - 10
        x_w = 52 if confirming == "close" else 22
        x_rect = QRectF(rc.right() - 6 - x_w, y + 4, x_w, 22)
        self.hits.append((x_rect, "close", sid))
        if confirming == "close":
            self.small_button(qp, x_rect, "Close", False, True, CLOSE_RED)
        elif hovered:
            over_x = self.hover_hit == ("close", sid)
            if over_x:
                qp.setPen(Qt.PenStyle.NoPen)
                qp.setBrush(CLOSE_RED)
                qp.drawRoundedRect(x_rect, 4, 4)
            draw_cross(qp, x_rect.center(), WHITE if over_x else GRAY)
        if hovered or confirming == "close":
            right = x_rect.left() - 6
        self.paint_card_icon(qp, QPointF(x + 7, y + 15), tk, color, t)
        age = now - s["since"]
        if tk == "working":
            state = fmt_dur(age)
        elif tk == "waiting":
            state = label
        else:
            state = f"{label} · {fmt_dur(age, coarse=True)}"
        state_x = self.draw_right(qp, right, y + 5, 20, state, self.f_small, color, pad=4)
        self.draw_text(qp, x + 20, y + 5, state_x - x - 28, 20, s["title"], self.f_bold,
                       GRAY if tk == "forgotten" else WHITE)

        # line 2: activity, context %, and the Compact button
        right2, pct = rc.right() - 10, ctx_pct(s)
        usage_left = right2 - 40         # the context % area: hovering it shows the chat's usage
        if pct is not None:
            pct_color = GRAY if kind else ctx_color(pct)     # no yellow % beside a yellow "Needs you"
            right2 = self.draw_right(qp, right2, y + 25, 18, f"{pct:.0f}%", self.f_bold, pct_color) - 4
            if hovered:
                right2 = self.draw_right(qp, right2, y + 25, 18, "context", self.f_small, DIM) - 8
            usage_left = min(usage_left, right2 + 4)
            # the button only exists while it is drawn, so the mouse never hovers an invisible one
            if pct >= COMPACT_AT and s["status"] == "idle" and (hovered or confirming == "compact"):
                w = 70 if confirming == "compact" else 60
                c_rect = QRectF(right2 - w, y + 24, w, 20)
                self.hits.append((c_rect, "compact", sid))
                self.small_button(qp, c_rect, "Compact", self.hover_hit == ("compact", sid),
                                  confirming == "compact", AMBER)
                right2 -= w + 8
        self.hits.append((QRectF(usage_left, y + 24, rc.right() - 6 - usage_left, 20), "usage", sid))

        if kind:
            line, line_color = self.ask_text(s, kind), WHITE
        elif tk in ("working", "waiting") and s["tool"]:
            line, line_color = doing(s), GRAY
        elif tk == "done" and s["answer"]:
            line, line_color = s["answer"], GRAY
        elif s["prompt"]:
            line, line_color = f"“{s['prompt']}”", DIM
        else:
            line, line_color = s["cwd"], DIM
        self.draw_text(qp, x + 20, y + 25, right2 - x - 24, 18, line, self.f_body, line_color)
        self.paint_agents(qp, rc, sid, now, t)
        if kind:
            self.paint_answers(qp, rc, s, kind)
        self.hits.append((rc, "card", sid))   # added last so the buttons inside the card win
        qp.setOpacity(base)

    def paint_agents(self, qp, rc, sid, now, t):
        """A row per listed sub-agent under the card's two lines, then "+N more" if some did not fit."""
        rows, more = self.agent_rows.get(sid, ([], 0))
        row = QRectF(rc.left() + 30, rc.top() + self.CARD_H - 6, rc.width() - 40, AGENT_ROW_H)
        for a in rows:
            self.paint_agent_row(qp, row, a, now, t)
            self.hits.append((row, "agent:" + a["id"], sid))
            row = row.translated(0, AGENT_ROW_H)
        if more:
            label = f"+{more} more sub-agent{'s' if more != 1 else ''}"
            self.draw_text(qp, row.left() + 14, row.top(), row.width() - 14, row.height(), label, self.f_small, DIM)

    def paint_agent_row(self, qp, row, a, now, t):
        """Status icon, description, then tokens, tool calls and time on the right."""
        icon = QPointF(row.left() + 5, row.center().y())
        if not a["running"]:
            draw_check(qp, icon, DIM)
        elif self.cfg["reduce_motion"]:
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(CLAUDE)
            qp.drawEllipse(icon, 3, 3)
        else:
            draw_spinner(qp, icon, 4, t, CLAUDE)
        tools = a["tool_uses"]
        stats = [f"{tools} tool{'s' if tools != 1 else ''}", agent_time(a, now)]
        if a["tokens"] is not None:
            stats.insert(0, f"{fmt_tokens(a['tokens'])} tok")
        left = self.draw_right(qp, row.right(), row.top(), row.height(), " · ".join(stats), self.f_small, DIM)
        self.draw_text(qp, row.left() + 14, row.top(), left - row.left() - 20, row.height(), a["description"],
                       self.f_small, GRAY if a["running"] else DIM)

    @staticmethod
    def ask_text(s, kind):
        _, name, args = pending(s)
        if kind == "question":
            return args["questions"][0].get("question", "Claude has a question")
        if kind == "permission" and name:
            detail = tool_detail(args)
            return f"Wants to use {short_tool(name)}" + (f": {detail}" if detail else "")
        return "Wants your permission" if kind == "permission" else "Waiting for you in the terminal"

    def paint_answers(self, qp, rc, s, kind):
        """Answer buttons under a waiting card, and the reply box for the chat it belongs to."""
        sid = s["sid"]
        x, w, y = rc.left() + 30, rc.width() - 40, rc.top() + self.CARD_H - 4 + self.agents_height(sid)
        if kind == "permission":
            buttons = [("1", "Allow", GREEN), ("esc", "Deny", RED), ("open", "Open chat", GRAY)]
        elif kind == "question":
            options = s["pending"][2]["questions"][0]["options"][:4]
            buttons = [(str(i + 1), o.get("label", str(i + 1)), AMBER) for i, o in enumerate(options)]
        else:
            buttons = [("open", "Open chat", AMBER)]
        fm = self.metrics(self.f_small)
        bx = x
        for key, label, color in buttons:
            bw = min(fm.horizontalAdvance(label) + 22, (w - 6 * (len(buttons) - 1)) / len(buttons))
            rect, action = QRectF(bx, y, bw, 24), "ans:" + key
            self.hits.append((rect, action, sid))
            self.small_button(qp, rect, self.elided(label, self.f_small, bw - 10),
                              self.hover_hit == (action, sid), False, color)
            bx += bw + 6
        if kind == "other" or sid != self.reply_sid:
            return
        ry = y + ASK_ROW_H + 2
        send = QRectF(x + w - REPLY_H, ry, REPLY_H, REPLY_H)
        self.reply_rect = QRectF(x, ry, w - REPLY_H - 6, REPLY_H)
        self.hits.append((send, "send", sid))
        lit = self.hover_hit == ("send", sid) or bool(self.reply.text())
        qp.setPen(Qt.PenStyle.NoPen)
        qp.setBrush(AMBER if lit else WHITE_30)
        qp.drawRoundedRect(send, 6, 6)
        draw_up_arrow(qp, send.center(), INK if lit else GRAY)


def main():
    if sys.stderr is None:               # pythonw has no console: keep errors in config/island.log
        log = settings.HERE / "config" / "island.log"
        if log.exists() and log.stat().st_size > 1_000_000:
            log.unlink()
        sys.stdout = sys.stderr = open(log, "a", encoding="utf-8", buffering=1)
        print(time.strftime("--- %Y-%m-%d %H:%M:%S started"), " ".join(sys.argv[1:]))
    app = QApplication(sys.argv)
    app.setApplicationName("Claude Island")
    app.setApplicationDisplayName("Claude Island")
    app.setQuitOnLastWindowClosed(False)
    PLAT.look.app_identity(app)          # a widget, not a "Python" app in the Dock or taskbar

    def give_chats_back():               # never leave a chat window hidden behind us
        winctl.show_all(HIDDEN_FILE)
    app.aboutToQuit.connect(give_chats_back)
    previous_hook = sys.excepthook

    def on_crash(*exc):
        try:
            give_chats_back()
        finally:
            previous_hook(*exc)
    sys.excepthook = on_crash
    app.island = Island()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
