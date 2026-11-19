# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Claude Island: a small always-on-top bar that lists your running Claude Code chats and your plan limits.

Hover to open the panel, click a card to jump to its terminal, click X twice to close a chat. The widget is
started by Claude Code hooks (with --hook) or by hand. Only one copy runs: starting it again brings it on screen.
"""
import sys
from pathlib import Path

from platforms import get_platform

# Checked before Qt is imported, so the hook that runs on every prompt exits cheaply when we already run.
# A copy started by hand leaves a flag asking the running one to show itself.
if not get_platform().instance.acquire():
    if "--hook" not in sys.argv:
        flag = Path(__file__).resolve().parent / "config" / "show.flag"
        flag.parent.mkdir(exist_ok=True)
        flag.touch()
    sys.exit(0)

import math
import os
import threading
import time
from functools import partial

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QIcon, QLinearGradient,
                           QMovie, QPainter, QPen, QPixmap)
from PySide6.QtWidgets import QApplication, QFileDialog, QLineEdit, QMenu, QSystemTrayIcon, QToolTip, QWidget

import settings
import sounds
from drawing import (AMBER, BG, BLUE, CARD, CARD_HOVER, CLAUDE, CLAUDE_LIGHT, CLOSE_RED, DIM, FORGOT,
                     GRAY, GREEN, ICON, INK, RED, TIME_BAR, TRACK, WHITE, WHITE_30, WHITE_170, WHITE_200, WHITE_220,
                     WORKING, Spring, apply_palette, draw_check, draw_cross, draw_eye, draw_gear, draw_mascot,
                     draw_pin, draw_plus, draw_ring, draw_spark, draw_spinner, draw_up_arrow, ease_out, font,
                     icon_pixmap, paint_frame, ramp)
from feed import (Feed, clamp, clean_status_dir, fmt_dur, fmt_tokens, lerp, read_json, same_process,
                  session_state, short_tool, tool_detail)

PLAT = get_platform()
winctl = PLAT.winctl
SHOW_FLAG = settings.HERE / "config" / "show.flag"      # the file the guard above touches
HIDDEN_FILE = settings.HERE / "config" / "hidden_windows.txt"
CFG = settings.load()

COMPACT_AT = 40                       # context % from which a card offers Compact
OPEN_SPRING = (438.0, 1.0)            # stiffness, damping: about 0.3 s to open, no overshoot
CLOSE_SPRING = (987.0, 1.0)           # about 0.2 s to close
ASK_ROW_H = 30                        # answer buttons under a waiting card
REPLY_H = 32                          # reply box under them
NOTCH_WING = 64                       # docked in a macOS notch: px of bar on each side of it
NOTCH_SNAP = 80                       # how close a drag must come to the notch to dock
NOTCH_BLACK = QColor(0, 0, 0)
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
TIPS = {"newchat": "New chat", "settings": "Settings", "close": "Close this chat", "send": "Send",
        "compact": "Compact: summarise this chat to free its context"}
KEYS_HELP = ("↑/↓ or Tab: pick a chat · Enter: open it · Del twice: close it · Esc: close · "
             "Ctrl+, settings · Ctrl+N new chat · Ctrl+P pin · Ctrl+H hide/show all · Ctrl+R refresh · Ctrl+Q quit")

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
        self.notch = None              # macOS: QRect of the camera notch we are docked in
        self.reply_sid = None          # the chat the reply box answers
        self.reply_lock = None         # (sid, tool id) once you start typing

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
        if self.cfg["notch"]:
            self.dock(PLAT.look.notch_rect(self.screen()))
        self.tray.show()
        SHOW_FLAG.unlink(missing_ok=True)
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
        self.size_bar()
        speed = (c["animation_speed"] / 100) ** 2
        self.open_spring = (OPEN_SPRING[0] * speed, OPEN_SPRING[1])
        self.close_spring = (CLOSE_SPRING[0] * speed, CLOSE_SPRING[1])
        self.panel_height.tune(200 * speed, 0.9)
        self.visibility.tune(170 * speed, 0.9)
        self.bar_width.target = self.W
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
        self.act_hide = m.addAction("Hide all chats", self.toggle_hide_all)
        m.addAction("New chat…", lambda: self.new_chat_menu(QCursor.pos()))
        m.addSeparator()
        m.addAction("Quit Claude Island", QApplication.quit)
        m.aboutToShow.connect(self.sync_menu)
        return m

    def sync_menu(self):
        self.act_sound.setChecked(self.cfg["sounds"])
        self.act_hide.setText("Show all chats" if winctl.HIDDEN else "Hide all chats")

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
        self.apply_hover()
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
        return (self.working() or self.toast is not None or self.pinned or self.hover or self.lingering
                or self.dragging or bool(winctl.HIDDEN) or self.previewing()
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
            self.act_on(s, "waiting", winctl.reject_with, s["title"], text)
        elif kind == "question":
            n_options = len(s["pending"][2]["questions"][0]["options"])
            self.act_on(s, "waiting", winctl.answer_other, s["title"], n_options, text)
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
            return winctl.focus(s["title"])
        if s["status"] == "waiting":         # only type into a prompt that is still there
            if key == "esc":
                self.act_on(s, "waiting", winctl.reject_with, s["title"], "")
            else:
                self.act_on(s, "waiting", winctl.press, s["title"], key)
            self.attention.discard(s["sid"])
            QTimer.singleShot(1200, self.refresh)

    def act_on(self, s, expect, action, *args):
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
                action(*args)
            except Exception as e:
                print("action failed:", e, file=sys.stderr)
        threading.Thread(target=job, daemon=True).start()

    def toggle_hide_all(self):
        if self.hider and self.hider.is_alive():   # still hiding from the last click
            return
        if winctl.HIDDEN:
            winctl.show_all(HIDDEN_FILE)
        else:   # counting tabs takes a second or two, so keep it off the UI thread
            titles = [s["title"] for s in self.sessions]
            self.hider = threading.Thread(target=winctl.hide_all, args=(titles, HIDDEN_FILE), daemon=True)
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
        top = 10 + self.HEAD_H + self.PILL_H + self.PILL_GAP
        heights = [self.card_height(s) + self.CARD_GAP for s in self.sessions]
        need = top + (sum(heights) if heights else 44) + 6
        g = self.screen_geo()
        bar_top, bar_bottom = self.bar_edges()
        room_up = bar_bottom - g.top() - self.M - 4
        room_down = g.bottom() + 1 - bar_top - self.M - 4
        if decide or self.opening.x < 0.02:
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
        self.CH = n.height() if n else int(self.cfg["bar_height"])
        self.mini_w = n.width() + 2 * NOTCH_WING if n else self.CH + 4

    def dock(self, rect):
        """Dock into the notch rect, or undock with None. Docked, the island hangs from the top and opens down."""
        if rect == self.notch:
            return
        self.notch = rect
        self.size_bar()
        PLAT.look.float_over_menu_bar(self, bool(rect))
        if rect:
            self.grow_down = True
        self.apply_hover()
        self.apply_geometry()
        self.update()

    def follow_notch(self):
        """After a screen change, dock into the notch where it now is, or undock when the screen has none."""
        if self.notch is None and not self.cfg["notch"]:
            return
        self.dock(PLAT.look.notch_rect(self.screen()))

    def snap_to_notch(self, cursor):
        """While dragging, dock when the bar's top centre nears the notch and undock when pulled away."""
        n = PLAT.look.notch_rect(self.screen())
        if not n:
            return
        if self.notch:
            if math.hypot(cursor.x() - n.center().x(), cursor.y() - n.center().y()) > NOTCH_SNAP * 1.5:
                self.dock(None)
            return
        g = self.screen_geo()
        top_c = QPointF(g.right() + 1 - self.cfg["dx"] - self.W / 2, g.bottom() + 1 - self.cfg["dy"] - self.CH)
        if math.hypot(top_c.x() - n.center().x(), top_c.y() - n.bottom()) < NOTCH_SNAP:
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
            x, y = self.notch.center().x() + 1 - outer_w // 2, self.notch.top()
            if self.geometry().getRect() != (x, y, outer_w, outer_h):
                self.setGeometry(x, y, outer_w, outer_h)
            self.pill = QRectF((outer_w - width) / 2, 0, width, h)
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

    # ---------------------------------------------------------------- mouse
    def enterEvent(self, e):
        self.hover_timer.start(self.cfg["hover_delay_ms"])

    def leaveEvent(self, e):
        self.hover_hit = None
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
        keep_open = ((self.hover and not on_bar_pin) or self.lingering or self.attention or typing
                     or self.previewing() or self.kb_open)
        want = 1.0 if keep_open and not self.dragging else 0.0
        if want != self.opening.target:
            if want and self.opening.x < 0.05:
                self.panel_height.target = self.panel_height.x = self.expanded_height(decide=True)
            for sp in (self.opening, self.bar_width):
                sp.tune(*(self.open_spring if want else self.close_spring))
        self.opening.target = want
        self.bar_width.target = self.mini_w if self.is_mini() and not want else self.W
        self.visibility.target = 1.0 if self.should_show() else 0.0
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
            lines = [f"{name} limit: unknown until the status line script runs"]
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

    def mousePressEvent(self, e):
        self.activateWindow()                    # a click gives the island the keyboard (Esc, arrows, Ctrl+…)
        self.setFocus()
        if e.button() == Qt.MouseButton.LeftButton:
            self.press_at = (e.globalPosition().toPoint(), self.cfg["dx"], self.cfg["dy"])
            self.press_hit = self.hit_at(e.position())
            self.dragging = False

    def mouseMoveEvent(self, e):
        if self.press_at and e.buttons() & Qt.MouseButton.LeftButton:
            start, dx0, dy0 = self.press_at
            d = e.globalPosition().toPoint() - start
            self.dragging = self.dragging or abs(d.x()) + abs(d.y()) > 6
            if self.dragging:
                g = self.screen_geo()
                self.cfg["dx"] = clamp(dx0 - d.x(), 0, g.width() - self.W)
                self.cfg["dy"] = clamp(dy0 - d.y(), 0, g.height() - self.CH)
                self.snap_to_notch(e.globalPosition().toPoint())
                self.apply_geometry()
            return
        hit = self.hit_at(e.position())
        if hit != self.hover_hit:
            self.hover_hit = hit
            clickable = hit and not hit[0].startswith("limit:")   # the limit pills only have a tooltip
            self.setCursor(Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor)
            tip = self.tooltip(*hit) if hit else None
            if tip:
                QToolTip.showText(QCursor.pos(), tip, self)
            else:
                QToolTip.hideText()
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
            settings.save(self.cfg)
            return self.apply_hover()
        hit = self.hit_at(e.position())
        if hit != self.press_hit:            # the list moved under the mouse: not a click
            return
        if not hit:
            if self.opening.x < 0.5:         # the small bar: jump to the chat that is busy
                active = [s for s in self.sessions if s["status"] != "idle"] or self.sessions
                if active:
                    winctl.focus(active[0]["title"])
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
        elif action == "send":
            self.send_reply()
        elif action.startswith("limit:"):
            pass                             # a tooltip only
        elif s and (action in ("card", "usage") or action.startswith("agent:")):
            winctl.focus(s["title"])
        elif s and action.startswith("ans:"):
            self.answer(s, action[4:])
        elif s and self.confirm and self.confirm[:2] == (sid, action):   # second click on X or Compact
            self.confirm = None
            if action == "close":
                still_same = partial(same_process, s["pid"], s["sfile"])
                self.act_on(s, None, winctl.close, s["title"], s["pid"], still_same)
            elif s["status"] == "idle":      # typing is only safe at an idle prompt
                self.act_on(s, "idle", winctl.send_command, s["title"], "/compact")
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
            K.Key_Q: QApplication.quit,
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
            QToolTip.showText(self.mapToGlobal(self.pill.topLeft().toPoint()), KEYS_HELP, self)
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
        shape = paint_frame(qp, r, self.RAD, NOTCH_BLACK if self.notch else BG, BG.alphaF(),
                            snap=1 if self.springs_settled() else 4, flush_top=self.notch is not None)
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
        if self.working() and p < 0.5 and not self.cfg["reduce_motion"]:   # orange line running along the bar
            qp.setOpacity(1 - p * 2)
            seg = r.width() * 0.28
            x = r.left() + (((time.monotonic() - self.t0) * 0.55) % 1.0) * (r.width() + seg) - seg
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(CLAUDE)
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
        top = r.top() if self.grow_down else r.bottom() - self.CH
        cy = top + self.CH / 2
        offset = (self.CH - 56) / 2      # the text layout is designed for a 56 px bar, centred in others
        left = r.right() - self.W
        full = clamp((self.bar_width.x - self.mini_w) / max(1, self.W - self.mini_w))   # 0 mini .. 1 full width
        if self.notch and full < 0.35:
            return self.paint_notch_wings(qp, r)
        mascot_x = lerp(r.center().x(), r.left() + 28, full)
        self.paint_mascot(qp, QPointF(mascot_x, cy + 2), 20 if full > 0.5 else 22, self.mascot_mode())
        if full < 0.35:                  # mini: the mascot alone
            self.bar_pin = QRectF()
            return
        base = qp.opacity()
        qp.setOpacity(base * clamp((full - 0.35) / 0.65))
        line1, line2, color2 = self.bar_lines(time.time())
        pin_c = QPointF(r.right() - 11, top + 11)
        self.bar_pin = QRectF(pin_c.x() - 11, pin_c.y() - 10, 22, 20)
        if self.hover or self.pinned:
            draw_pin(qp, pin_c, 10, self.pin_color(self.hover_hit == ("pin", "bar"), WHITE_200), upright=self.pinned)
        right = r.right() - 26
        pct = self.limit_state("five_hour", time.time())[0]
        if pct is not None:
            color = limit_color(pct)
            draw_ring(qp, QPointF(right - 8, cy - 6), pct, 8.0, color)
            self.draw_text(qp, right - 30, cy + 4, 44, 16, f"{pct:.0f}%", self.f_small, color,
                           Qt.AlignmentFlag.AlignHCenter)
            right -= 40
        x = left + 52
        self.draw_text(qp, x, top + offset + 9, right - x, 20, line1, self.f_main, WHITE)
        self.draw_text(qp, x, top + offset + 28, right - x, 18, line2, self.f_body, color2)
        qp.setOpacity(base)

    def paint_notch_wings(self, qp, r):
        """Docked and closed: the mascot left of the notch, the state right of it."""
        cy = r.top() + self.CH / 2
        self.paint_mascot(qp, QPointF(r.left() + NOTCH_WING / 2, cy + 2), min(18, self.CH * 0.48), self.mascot_mode())
        c = QPointF(r.right() - NOTCH_WING / 2, cy)
        active = [s for s in self.sessions if s["status"] != "idle"]
        pct = self.limit_state("five_hour", time.time())[0]
        if pct is not None and not active:
            draw_ring(qp, c, pct, min(8.0, self.CH * 0.22), limit_color(pct))
        else:
            if any(s["status"] == "waiting" for s in active):
                color = AMBER
            elif active:
                color = CLAUDE
            elif self.toast and self.toast[0] == "done":
                color = GREEN
            else:
                color = DIM
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(color)
            qp.drawEllipse(QPointF(c.x() - 9, cy), 3.5, 3.5)
            self.draw_text(qp, c.x() - 3, cy - 9, 24, 18, str(len(active) or len(self.sessions)), self.f_small, WHITE)
        self.bar_pin = QRectF()

    def reveal(self, qp, r, y, h):
        """Fade and raise one panel block as the panel opens, blocks nearest the bar first."""
        full_h = max(1.0, self.panel_height.x)
        mid = y + h / 2
        from_bar = clamp((mid - r.top() if self.grow_down else r.bottom() - mid) / full_h)
        a = ease_out((clamp(self.opening.x) - 0.30 - 0.28 * from_bar) / 0.40)
        qp.setOpacity(a)
        qp.translate(0, (1 - a) * 10)

    def paint_panel(self, qp, r):
        now, t = time.time(), self.anim_t()
        x0, width = r.right() - self.W + 12, self.W - 24
        # blocks are drawn at their final place and uncovered as the shape grows
        y = (r.top() + 10) if self.grow_down else (r.bottom() - self.panel_height.x + 10)
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
        """Mascot on the left; settings, new chat, hide all and pin on the right."""
        pin_c = QPointF(x0 + width - 8, y + 12)
        gear_c = QPointF(pin_c.x() - 80, pin_c.y())
        plus_c = QPointF(pin_c.x() - 54, pin_c.y())
        eye_c = QPointF(pin_c.x() - 28, pin_c.y())
        for c, action in ((gear_c, "settings"), (plus_c, "newchat"), (eye_c, "hideall")):
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
    app.setQuitOnLastWindowClosed(False)

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
