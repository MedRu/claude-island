# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""The settings flyout, drawn like the island and docked beside it so the island works as a live preview."""
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QColorDialog, QDoubleSpinBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider, QSpinBox, QStackedWidget,
                               QVBoxLayout, QWidget)

import settings
import sounds
from platforms import get_platform
from drawing import BG, CLAUDE, draw_gear, icon_pixmap, paint_frame

BRIGHT = ["#d97757", "#fce100", "#6ccb5f", "#60cdff", "#b48cff", "#ff6f91", "#f7a35c", "#8a8a8a"]
DARK = ["#202020", "#1b1b1f", "#1e2430", "#1f2a24", "#2a1f24", "#101010", "#2b2b2b", "#3a3a3a"]
IMAGES = "Images and GIFs (*.gif *.png *.jpg *.jpeg *.webp *.bmp)"
SOUND_LABELS = (("start", "A chat starts working"), ("needs", "A chat needs you"), ("done", "A chat finished"),
                ("warn", "Usage passes 75 % / 90 %"), ("limit", "A limit is reached (100 %)"))


def hrow(*widgets, spacing=4):
    """The widgets side by side in a row without margins; spacing None keeps the style's own."""
    box = QWidget()
    line = QHBoxLayout(box)
    line.setContentsMargins(0, 0, 0, 0)
    if spacing is not None:
        line.setSpacing(spacing)
    for w in widgets:
        line.addWidget(w)
    return box


def icon_button(text, tip):
    """A small flat 24 x 24 button showing one glyph."""
    b = QPushButton(text)
    b.setObjectName("icon")
    b.setFixedSize(24, 24)
    b.setToolTip(tip)
    return b


def style(accent, bg):
    """Qt style sheet from the island's current colours."""
    lift = QColor(bg).lighter(135).name()
    fonts = ",".join(f"'{f}'" for f in get_platform().look.UI_FONTS)
    # The spin box arrows are sized to zero rather than using NoButtons, which makes Qt squeeze the text.
    return f"""
    * {{ font-family:{fonts}; font-size:12px; color:#e8e8e8; }}
    QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget {{ background:transparent; border:none; }}
    QLabel#title {{ font-size:14px; font-weight:600; color:#fff; }}
    QLabel#section {{ color:{accent}; font-size:11px; font-weight:600; padding-top:10px; }}
    QLabel#hint {{ color:#8c8c8c; font-size:11px; }}
    QLabel#name {{ color:#c8c8c8; }}
    QPushButton {{ background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.08); border-radius:6px;
        padding:4px 10px; }}
    QPushButton:hover {{ background:rgba(255,255,255,0.11); }}
    QPushButton:checked {{ background:{accent}; border-color:{accent}; color:#141414; font-weight:600; }}
    QPushButton#nav {{ background:transparent; border:none; border-radius:6px; padding:5px 9px; color:#a8a8a8; }}
    QPushButton#nav:hover {{ background:rgba(255,255,255,0.07); color:#fff; }}
    QPushButton#nav:checked {{ background:rgba(255,255,255,0.10); color:#fff; font-weight:600; }}
    QPushButton#icon {{ background:transparent; border:none; padding:0; font-size:13px; color:#bdbdbd; }}
    QPushButton#icon:hover {{ background:rgba(255,255,255,0.10); color:#fff; }}
    QSpinBox, QDoubleSpinBox {{ background:{lift}; border:1px solid rgba(255,255,255,0.08); border-radius:6px;
        padding:3px 8px; }}
    QSpinBox:focus, QDoubleSpinBox:focus {{ border-color:{accent}; }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button
        {{ width:0; height:0; border:none; }}
    QSlider::groove:horizontal {{ height:4px; background:rgba(255,255,255,0.14); border-radius:2px; }}
    QSlider::sub-page:horizontal {{ background:{accent}; border-radius:2px; }}
    QSlider::handle:horizontal {{ background:#fff; width:14px; height:14px; margin:-5px 0; border-radius:7px;
        border:3px solid {accent}; }}
    QScrollBar:vertical {{ background:transparent; width:6px; margin:2px; }}
    QScrollBar::handle:vertical {{ background:rgba(255,255,255,0.18); border-radius:3px; min-height:30px; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page
        {{ height:0; background:none; }}
    QColorDialog, QFileDialog {{ background:#2b2b2b; }}
    """


class NoStrayWheel(QObject):
    """Scrolling the page must not change a slider or number it passes over: only a focused one takes the wheel."""

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.Wheel and not obj.hasFocus():
            e.ignore()
            return True
        return False


class Toggle(QAbstractButton):
    """Windows 11 style switch."""

    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.knob = 0.0
        self.anim = QVariantAnimation(self, duration=120, valueChanged=self._moved)
        self.toggled.connect(self._slide)

    def _slide(self, on):
        self.anim.stop()
        self.anim.setStartValue(self.knob)
        self.anim.setEndValue(1.0 if on else 0.0)
        self.anim.start()

    def _moved(self, v):
        self.knob = v
        self.update()

    def snap(self):
        """Jump to the current state without animating."""
        self.knob = 1.0 if self.isChecked() else 0.0
        self.update()

    def sizeHint(self):
        return QSize(40, 20)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1, 1, 38, 18)
        on = QColor(CLAUDE)
        on.setAlphaF(self.knob)
        p.setPen(QPen(QColor(255, 255, 255, int(150 * (1 - self.knob))), 1))
        p.setBrush(on)
        p.drawRoundedRect(r, 9, 9)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 20) if self.knob > 0.5 else QColor(220, 220, 220))
        knob = 6 + (1.5 if self.underMouse() else 0)
        p.drawEllipse(QPointF(10 + 20 * self.knob, 10), knob, knob)


class Swatches(QWidget):
    """A row of colour dots, the last of which opens the colour picker. The chosen one gets a ring."""
    D, GAP = 18, 7

    def __init__(self, presets, value, changed):
        super().__init__()
        self.presets, self.value, self.changed = presets, value, changed
        self.setFixedSize((len(presets) + 1) * (self.D + self.GAP), self.D + 6)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Pick a colour; the last dot opens the colour picker")

    def centers(self):
        step = self.D + self.GAP
        return [QPointF(3 + self.D / 2 + i * step, 3 + self.D / 2) for i in range(len(self.presets) + 1)]

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.D / 2
        custom = self.value.lower() not in self.presets
        for i, c in enumerate(self.centers()):
            last = i == len(self.presets)
            if last and not custom:
                # a rainbow ring with a plus, meaning "any colour"
                for k in range(12):
                    p.setPen(QPen(QColor.fromHsv(k * 30, 170, 240), 3))
                    p.drawArc(QRectF(c.x() - r + 2, c.y() - r + 2, 2 * r - 4, 2 * r - 4), k * 480, 480)
                p.setPen(QPen(QColor(230, 230, 230), 1.5))
                p.drawLine(QPointF(c.x() - 3, c.y()), QPointF(c.x() + 3, c.y()))
                p.drawLine(QPointF(c.x(), c.y() - 3), QPointF(c.x(), c.y() + 3))
            else:
                p.setPen(QPen(QColor(255, 255, 255, 75), 1))   # keeps dark dots visible
                p.setBrush(QColor(self.value if last else self.presets[i]))
                p.drawEllipse(c, r - 2, r - 2)
            chosen = custom if last else self.presets[i] == self.value.lower()
            if chosen:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(255, 255, 255), 2))
                p.drawEllipse(c, r + 1, r + 1)

    def mouseReleaseEvent(self, e):
        for i, c in enumerate(self.centers()):
            if (e.position() - c).manhattanLength() > self.D * 0.7:
                continue
            if i < len(self.presets):
                self.set(self.presets[i])
            else:
                color = QColorDialog.getColor(QColor(self.value), self.window(), "Choose a colour")
                if color.isValid():
                    self.set(color.name())

    def set(self, value, notify=True):
        self.value = value
        self.update()
        if notify:
            self.changed(value)


class SettingsWindow(QWidget):
    M, W, H = 14, 400, 580          # shadow margin, size

    def __init__(self, island):
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Claude Island · Settings")
        get_platform().look.fix_tool_window(self)
        self.island, self.cfg = island, island.cfg
        self.syncers = []               # callbacks that show the current cfg values in the controls
        self.drag_from = None
        self.colors_now = None
        self.no_wheel = NoStrayWheel(self)
        self.save_timer = QTimer(self, singleShot=True, interval=400, timeout=lambda: settings.save(self.cfg))
        self.resize(self.W + 2 * self.M, self.H + 2 * self.M)
        self.build()
        self.restyle()
        # Esc, Ctrl+W and Ctrl+, close it whichever control has the keyboard (Qt maps Ctrl to Cmd on macOS)
        for keys in (QKeySequence(Qt.Key.Key_Escape), QKeySequence.StandardKey.Close, QKeySequence("Ctrl+,")):
            QShortcut(keys, self, self.close, context=Qt.ShortcutContext.WindowShortcut)

    # ---------------- frame: painted like the island
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor(BG)
        bg.setAlpha(255)                    # always solid, so the settings text stays crisp
        paint_frame(p, QRectF(self.rect()).adjusted(self.M, self.M, -self.M, -self.M), self.island.RAD, bg)

    def restyle(self):
        # setStyleSheet is slow, so only redo it when the colours changed
        if self.colors_now != (CLAUDE.name(), BG.name()):
            self.colors_now = (CLAUDE.name(), BG.name())
            self.setStyleSheet(style(*self.colors_now))
            if hasattr(self, "gear"):
                self.paint_gear()
        self.update()

    def paint_gear(self):
        """The header cog, in the accent colour."""
        self.gear.setPixmap(icon_pixmap(36, lambda p: draw_gear(p, QPointF(18, 18), 26, QColor(CLAUDE)), dpr=2))

    def place(self):
        """Beside the island, never over it: left of it, else right, above or below, with edges lined up."""
        isl = self.island
        g = isl.screen_geo()
        pill = isl.pill.translated(isl.geometry().topLeft()).toRect()
        w, h, m, gap = self.width(), self.height(), self.M, 10
        right_x = pill.right() - w + m + 1
        bottom_y = pill.bottom() - h + m + 1
        spots = [
            (pill.left() - w + m - gap, bottom_y),         # left
            (pill.right() + 1 - m + gap, bottom_y),        # right
            (right_x, pill.top() - h + m - gap),           # above
            (right_x, pill.bottom() + 1 - m + gap),        # below
        ]

        def fits(x, y):
            return (x + m >= g.left() and y + m >= g.top()
                    and x + w - m <= g.right() + 1 and y + h - m <= g.bottom() + 1)
        x, y = next(((x, y) for x, y in spots if fits(x, y)), spots[0])
        x = max(g.left() - m, min(x, g.right() + 1 - w + m))
        y = max(g.top() - m, min(y, g.bottom() + 1 - h + m))
        self.move(x, y)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < self.M + 46:   # the header drags
            self.drag_from = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self.drag_from is not None:
            self.move(e.globalPosition().toPoint() - self.drag_from)

    def mouseReleaseEvent(self, e):
        self.drag_from = None

    def showEvent(self, e):
        self.sync()
        super().showEvent(e)

    def closeEvent(self, e):
        settings.save(self.cfg)
        super().closeEvent(e)
        QTimer.singleShot(0, self.island.apply_hover)

    # ---------------- layout
    def build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(self.M + 14, self.M + 10, self.M + 10, self.M + 12)
        outer.setSpacing(8)

        head = QHBoxLayout()
        self.gear = QLabel()
        self.paint_gear()
        title = QLabel("Settings")
        title.setObjectName("title")
        close = QPushButton("✕")
        close.setFixedSize(28, 24)
        close.setStyleSheet("QPushButton{background:transparent;border:none;border-radius:4px;color:#bdbdbd;}"
                            "QPushButton:hover{background:#c42b1c;color:#fff;}")
        close.setToolTip("Close (Esc)")
        close.clicked.connect(self.close)
        head.addWidget(self.gear)
        head.addWidget(title)
        head.addStretch()
        head.addWidget(close)
        outer.addLayout(head)

        nav, self.pages = QHBoxLayout(), QStackedWidget()
        nav.setSpacing(2)
        group = QButtonGroup(self)
        pages = (("Look", self.look()), ("Mascot", self.mascot()), ("Sounds", self.sounds()),
                 ("Timing", self.timing()), ("Startup", self.startup()))
        for i, (name, rows) in enumerate(pages):
            b = QPushButton(name)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            group.addButton(b, i)
            nav.addWidget(b)
            self.pages.addWidget(self.page(rows))
        group.idClicked.connect(self.pages.setCurrentIndex)
        nav.addStretch()
        outer.addLayout(nav)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background:rgba(255,255,255,0.08);")
        outer.addWidget(line)
        outer.addWidget(self.pages, 1)

        foot = QHBoxLayout()
        reset = QPushButton("Reset to defaults")
        reset.setToolTip("Everything back to how it came, except where the island sits and the pin")
        reset.clicked.connect(self.reset)
        foot.addWidget(reset)
        foot.addStretch()
        outer.addLayout(foot)

    def page(self, rows):
        """A scrolling page. Rows are a section title, a "~hint" or a (name, control) pair."""
        body = QWidget()
        body.setObjectName("page")
        box = QVBoxLayout(body)
        box.setContentsMargins(0, 0, 8, 6)
        box.setSpacing(7)
        for row in rows:
            if isinstance(row, str):
                if row.startswith("~"):
                    label = QLabel(row[1:])
                    label.setObjectName("hint")
                else:
                    label = QLabel(row.upper())
                    label.setObjectName("section")
                label.setWordWrap(True)
                box.addWidget(label)
            else:
                name, control = row
                line = QHBoxLayout()
                label = QLabel(name)
                label.setObjectName("name")
                line.addWidget(label)
                line.addStretch()
                line.addWidget(control)
                box.addLayout(line)
        box.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        return scroll

    # ---------------- applying a change
    def set(self, key, value):
        if self.cfg[key] == value:
            return
        self.cfg[key] = value
        self.island.apply_settings()          # calls sync() back, so every control and colour follows
        self.save_timer.start()

    def sync(self):
        """Show the current values, also after a change made elsewhere such as the island's pin or the tray menu."""
        for refresh in self.syncers:
            refresh()
        self.restyle()

    def reset(self):
        settings.reset(self.cfg)
        self.island.apply_settings()
        settings.save(self.cfg)

    def bound(self, widget, refresh):
        """Register refresh() to show the setting in widget, without firing its change signals."""
        def quiet_refresh():
            widget.blockSignals(True)
            refresh()
            widget.blockSignals(False)
        self.syncers.append(quiet_refresh)
        return widget

    # ---------------- controls tied to a setting
    def toggle(self, key):
        t = Toggle()
        t.toggled.connect(lambda v: self.set(key, v))

        def refresh():
            t.setChecked(bool(self.cfg[key]))
            t.snap()
        return self.bound(t, refresh)

    def colors(self, key, presets=BRIGHT):
        s = Swatches(presets, self.cfg[key], lambda v: self.set(key, v))
        return self.bound(s, lambda: s.set(self.cfg[key], notify=False))

    def slider(self, key, lo, hi):
        """A percentage slider with its value shown beside it."""
        slider, value = QSlider(Qt.Orientation.Horizontal), QLabel()
        slider.setRange(lo, hi)
        slider.setFixedWidth(150)
        slider.installEventFilter(self.no_wheel)
        slider.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        value.setFixedWidth(38)
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def moved(v):
            value.setText(f"{v}%")
            self.set(key, v)

        def refresh():
            v = int(self.cfg[key])
            slider.setValue(v)
            value.setText(f"{v}%")
        slider.valueChanged.connect(moved)
        self.bound(slider, refresh)
        return hrow(slider, value, spacing=None)

    def number(self, key, lo, hi, step=1, suffix=""):
        """A spin box; a float step makes it decimal."""
        decimal = isinstance(step, float)
        spin = QDoubleSpinBox() if decimal else QSpinBox()
        if decimal:
            spin.setDecimals(1)
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setSuffix(suffix)
        spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        spin.setFixedWidth(92)
        spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        spin.installEventFilter(self.no_wheel)
        spin.setKeyboardTracking(False)       # apply when you finish typing, not at every digit
        spin.valueChanged.connect(lambda v: self.set(key, v))
        return self.bound(spin, lambda: spin.setValue(self.cfg[key]))

    def segmented(self, key, options):
        """One button per (value, label) option, the current one checked."""
        group = QButtonGroup(self)
        for i, (_, label) in enumerate(options):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            group.addButton(b, i)
        group.idClicked.connect(lambda i: self.set(key, options[i][0]))

        def refresh():
            current = next((i for i, (value, _) in enumerate(options) if value == self.cfg[key]), 0)
            group.button(current).setChecked(True)
        self.bound(group, refresh)
        return hrow(*group.buttons())

    def file(self, key, kind, extra=None, thumb=False):
        """A file picker button with a clear button, an optional thumbnail and an optional extra widget."""
        pick, clear, preview = QPushButton(), icon_button("✕", "Back to the built-in one"), QLabel()
        pick.setFixedWidth(150)
        pick.setCursor(Qt.CursorShape.PointingHandCursor)
        preview.setFixedSize(26, 26)

        def refresh():
            path = self.cfg[key]
            pick.setText(Path(path).name if path else "Built-in")
            pick.setToolTip(path or "Choose a file")
            clear.setVisible(bool(path))
            pm = QPixmap(path) if thumb and path else QPixmap()
            if not pm.isNull():
                pm = pm.scaled(26, 26, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            preview.setPixmap(pm)
            preview.setVisible(thumb)

        def choose():
            start = str(Path(self.cfg[key]).parent) if self.cfg[key] else str(Path.home())
            f, _ = QFileDialog.getOpenFileName(self, "Choose a file", start, kind)
            if f:
                self.set(key, f)
        pick.clicked.connect(choose)
        clear.clicked.connect(lambda: self.set(key, ""))
        self.syncers.append(refresh)
        widgets = [preview, pick, clear]
        if extra:
            widgets.append(extra)
        return hrow(*widgets)

    def outside(self, is_on, turn):
        """A switch for something kept outside our config, such as the start hooks or the menu shortcut."""
        t = Toggle()

        def flip(v):
            QGuiApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
            try:
                turn(v)
            finally:
                QGuiApplication.restoreOverrideCursor()
            t.blockSignals(True)
            t.setChecked(is_on())             # show what really happened
            t.blockSignals(False)

        def refresh():
            t.setChecked(is_on())
            t.snap()
        t.toggled.connect(flip)
        return self.bound(t, refresh)

    # ---------------- the pages
    def look(self):
        return ["Colours",
                ("Background", self.colors("color_background", DARK)),
                ("Accent", self.colors("color_accent")),
                ("Working", self.colors("color_working")),
                ("Needs you", self.colors("color_waiting")),
                ("Done", self.colors("color_done")),
                ("Idle", self.colors("color_idle")),
                ("Forgotten", self.colors("color_forgotten")),
                "~The accent colours the mascot and the line that runs along the bar while Claude works.",
                "Transparency",
                ("Whole island", self.slider("opacity", 30, 100)),
                ("Background only", self.slider("background_opacity", 0, 100)),
                ("Cards", self.slider("card_opacity", 20, 100)),
                "~Cards keep their own opacity: a see-through background no longer fades them.",
                *([("Glass", self.toggle("glass")),
                   "~Blurs what is behind the island, like macOS menus. Docked in the notch it stays black."]
                  if get_platform().look.HAS_GLASS else []),
                "Size",
                ("Width", self.number("width", 320, 600, 10, " px")),
                ("Bar height", self.number("bar_height", 48, 80, 2, " px")),
                ("Corner radius", self.number("corner_radius", 0, 20, 1, " px")),
                "Chat cards",
                ("Show sub-agents on cards", self.toggle("show_agents")),
                "~A row per running sub-agent, kept for a minute after it finishes. Hover a card's context % "
                "for the chat's cost and tokens and its finished agents."]

    def mascot(self):
        rows = ["Your own mascot",
                "~A GIF plays, a picture stays still. Built-in = the pixel mascot. A state without its own file uses "
                "the one for all states.",
                ("All states", self.file("mascot_file", IMAGES, thumb=True))]
        for state, label in settings.MASCOT_STATES.items():
            rows.append((label, self.file(f"mascot_{state}", IMAGES, thumb=True)))
        icons = [("star", "Star"), ("dot", "Dot"), ("mascot", "Mascot"), ("none", "None")]
        return rows + [("Size", self.slider("mascot_size", 50, 200)),
                       "Chat cards",
                       ("Icon", self.segmented("card_icon", icons))]

    def sounds(self):
        rows = ["Sounds",
                ("Play sounds", self.toggle("sounds")),
                ("Volume", self.slider("sound_volume", 0, 100)),
                "When"]
        for cue, label in SOUND_LABELS:
            test = icon_button("▶", "Play it")
            test.clicked.connect(lambda _=False, c=cue: sounds.play(c, force=True))
            rows.append((label, self.toggle(f"sound_{cue}")))
            rows.append(("     sound", self.file(f"sound_file_{cue}", "Sounds (*.wav)", test)))
        return rows + ["~Usage = the Session (5 h) and Week limits. Your own sound must be a .wav file."]

    def timing(self):
        return ["Panel",
                ("Open after hovering", self.number("hover_delay_ms", 0, 1500, 50, " ms")),
                ("Stay open after leaving", self.number("linger_s", 0.0, 10.0, 0.1, " s")),
                ("Animation speed", self.slider("animation_speed", 40, 250)),
                ("Reduce motion", self.toggle("reduce_motion")),
                "States",
                ("Done until idle for", self.number("done_minutes", 1, 240, 1, " min")),
                ("Forgotten after", self.number("forgotten_hours", 1, 72, 1, " h")),
                ("Shrink to the mascot after", self.number("mini_after_s", 10, 3600, 10, " s"))]

    def startup(self):
        auto = settings.AUTOSTART
        menu = []
        if auto.shortcut_supported:
            menu.append((auto.shortcut_label, self.outside(auto.shortcut_exists, auto.set_shortcut)))
        start_hook = self.outside(settings.start_hook_installed, settings.set_start_hook)
        status_line = self.outside(settings.status_line_installed, settings.set_status_line)
        return ["Starting",
                ("Start when a Claude chat starts", start_hook),
                "~Adds two hooks to ~/.claude/settings.json (a backup is kept next to it).",
                ("Show plan limits and cost", status_line),
                "~Sets Claude Code's status line to a small script that shares the limits with the island. "
                "Your own status line, if you had one, keeps showing. Applies from the next message in a chat.",
                *menu,
                ("Show when started by hand", self.toggle("show_when_started_by_hand")),
                "~Started by hand (the .vbs or the Start menu) it works alone, no Claude chat needed.",
                "Staying",
                ("Keep on screen when idle (pin)", self.toggle("pinned")),
                *([(f"{get_platform().hotkey.LABEL} hides or shows the island", self.toggle("global_hotkey")),
                   "~Works from any app. Hidden, the island stays away until you press it again or use the "
                   "tray menu; sounds still play."]
                  if get_platform().hotkey.LABEL else []),
                ("Open when Claude needs you", self.toggle("auto_open")),
                ("Quit after no chat for", self.number("quit_after_min", 0, 600, 5, " min")),
                "~0 min = never: it keeps running with or without Claude chats."]
