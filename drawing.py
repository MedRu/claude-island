# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Look and motion: palette, fonts, the spring behind every animation, the icons and the pixel mascot."""
import functools
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QTransform

from feed import clamp, lerp
from platforms import get_platform

# Windows 11 dark flyout palette and Claude orange. apply_palette() changes the customisable colours in place,
# so every module that imported them sees the change.
BG = QColor(32, 32, 32)
CLAUDE = QColor(217, 119, 87)            # accent: mascot, activity line
DEFAULT_LIGHT = (235, 160, 130)          # CLAUDE_LIGHT for the default accent
CLAUDE_LIGHT = QColor(*DEFAULT_LIGHT)
WORKING = QColor(217, 119, 87)
AMBER = QColor(252, 225, 0)              # needs you
GREEN = QColor(108, 203, 95)             # done
BLUE = QColor(96, 205, 255)              # idle
FORGOT = QColor(138, 138, 138)           # forgotten
BORDER, CARD, CARD_HOVER = QColor(255, 255, 255, 26), QColor(255, 255, 255, 9), QColor(255, 255, 255, 20)
TRACK, TIME_BAR, ICON = QColor(255, 255, 255, 30), QColor(255, 255, 255, 150), QColor(255, 255, 255, 140)
WHITE, GRAY, DIM, INK = QColor(255, 255, 255), QColor(200, 200, 200), QColor(140, 140, 140), QColor(20, 20, 20)
WHITE_30, WHITE_170 = QColor(255, 255, 255, 30), QColor(255, 255, 255, 170)       # icon shades
WHITE_200, WHITE_220 = QColor(255, 255, 255, 200), QColor(255, 255, 255, 220)
RED, CLOSE_RED = QColor(255, 153, 164), QColor(196, 43, 28)
DEFAULT_ACCENT = CLAUDE.name()
PALETTE_KEYS = {"color_background": BG, "color_accent": CLAUDE, "color_working": WORKING, "color_waiting": AMBER,
                "color_done": GREEN, "color_idle": BLUE, "color_forgotten": FORGOT}


def apply_palette(cfg):
    for key, color in PALETTE_KEYS.items():
        color.setRgb(QColor(cfg[key]).rgb())
    BG.setAlpha(round(255 * clamp(cfg["background_opacity"] / 100)))
    # Cards are the background pre-mixed with a white veil and given their own opacity, so a see-through
    # background does not fade them too.
    card_alpha = round(255 * clamp(cfg["card_opacity"] / 100))
    for color, veil in ((CARD, 9), (CARD_HOVER, 20)):
        r, g, b = (round(c + (255 - c) * veil / 255) for c in (BG.red(), BG.green(), BG.blue()))
        color.setRgb(r, g, b, card_alpha)
    if CLAUDE.name() == DEFAULT_ACCENT:
        CLAUDE_LIGHT.setRgb(*DEFAULT_LIGHT)
    else:
        CLAUDE_LIGHT.setRgb(CLAUDE.lighter(125).rgb())


def ramp(stops, value):
    """Colour for value along [(at, (r, g, b)), ...], blended between stops."""
    value = clamp(value, stops[0][0], stops[-1][0])
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        if value <= p1:
            return QColor(*(int(lerp(a, b, (value - p0) / (p1 - p0))) for a, b in zip(c0, c1)))
    return QColor(*stops[-1][1])


@functools.lru_cache(maxsize=64)
def font(px, weight=QFont.Weight.Normal):
    for family in get_platform().look.UI_FONTS:   # the first installed one, else the last one
        f = QFont(family)
        if f.exactMatch():
            break
    f.setPixelSize(px)
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


# ----------------------------------------------------------------- the frame (island and settings flyout)
@functools.lru_cache(maxsize=16)
def _shadow(w, h, rad, alpha, dpr):
    """Soft shadow just below a w x h rounded rect, as a pixmap starting 12 px left of and 6 px above it."""
    pm = QPixmap(round((w + 24) * dpr), round((h + 24) * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    qp = QPainter(pm)
    qp.setRenderHint(QPainter.RenderHint.Antialiasing)
    qp.setPen(Qt.PenStyle.NoPen)
    r = QRectF(12, 6, w, h)
    for i in range(1, 13):
        qp.setBrush(QColor(0, 0, 0, int(22 * math.exp(-i * i / 28.0) * alpha / 255)))
        qp.drawRoundedRect(r.adjusted(-i, -i + 6, i, i + 6), rad + i, rad + i)
    qp.end()
    return pm


def paint_frame(qp, rect, rad, bg, shadow_k=1.0, snap=1, flush_top=False):
    """Paint the shadow, the filled rounded shape and its border; return the shape for clipping the content.

    The shadow is cached by size, rounded to snap px so an animation does not flood the cache. flush_top, for the
    notch dock, squares the top corners and drops the shadow and border so the island merges with the notch.
    """
    if flush_top:
        shape, edge = QPainterPath(), QPainterPath()
        shape.addRoundedRect(rect.adjusted(0, -2 * rad, 0, 0), rad, rad)
        edge.addRect(rect)
        shape = shape.intersected(edge)
        qp.fillPath(shape, bg)
        return shape
    w = max(1, round(rect.width() / snap) * snap)
    h = max(1, round(rect.height() / snap) * snap)
    dpr = qp.device().devicePixelRatioF() if qp.device() else 1.0
    qp.drawPixmap(QPointF(rect.left() - 12, rect.top() - 6), _shadow(w, h, rad, round(255 * shadow_k), dpr))
    shape = QPainterPath()
    shape.addRoundedRect(rect, rad, rad)
    qp.fillPath(shape, bg)
    qp.setPen(QPen(BORDER, 1))
    qp.drawPath(shape)
    return shape


def icon_pixmap(size, paint, dpr=1):
    """A transparent size x size pixmap, painted antialiased by paint(painter)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    qp = QPainter(pm)
    qp.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint(qp)
    qp.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def ease_out(v):
    return 1 - (1 - clamp(v)) ** 3


def pulse(v):
    """0 -> 1 -> 0 as v goes 0 -> 1."""
    return math.sin(math.pi * clamp(v))


class Spring:
    """Damped spring: set .target, call step(dt) every frame, read .x. Damping 1.0 arrives without overshoot."""

    def __init__(self, x, stiffness=200.0, damping=0.7, eps=0.002):
        self.x = self.target = float(x)
        self.v, self.eps = 0.0, eps
        self.tune(stiffness, damping)

    def tune(self, stiffness, damping):
        self.k, self.c = stiffness, 2 * math.sqrt(stiffness) * damping

    def step(self, dt):
        self.v += (self.k * (self.target - self.x) - self.c * self.v) * dt
        self.x += self.v * dt
        if self.settled():
            self.x, self.v = self.target, 0.0

    def settled(self):
        return abs(self.target - self.x) < self.eps and abs(self.v) < self.eps * 10


# ----------------------------------------------------------------- icons
def pen(color, width):
    p = QPen(color, width)
    p.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return p


def draw_ring(qp, c, pct, radius, color):
    """Usage ring: a faint circle with an arc for pct % clockwise from 12 o'clock."""
    width = 2.4
    qp.setBrush(Qt.BrushStyle.NoBrush)
    qp.setPen(QPen(TRACK, width))
    qp.drawEllipse(c, radius, radius)
    if pct:
        degrees = max(3.0, clamp(pct / 100) * 360)        # any usage above 0 shows at least a short arc
        qp.setPen(pen(color, width))
        # Qt angles are in 1/16 degree, counter-clockwise from 3 o'clock
        qp.drawArc(QRectF(c.x() - radius, c.y() - radius, 2 * radius, 2 * radius), 90 * 16, int(-degrees * 16))


def draw_spark(qp, c, radius, t, active, color):
    """Claude's starburst. While its chat works it turns and breathes like the CLI spinner."""
    # rounded so that _spark_rays() caches a small number of shapes
    breathe = round(0.82 + 0.18 * math.sin(t * 4.2), 2) if active else 1.0
    qp.save()
    qp.translate(c)
    qp.rotate((t * 70) % 360 if active else 18)
    qp.fillPath(_spark_rays(radius, breathe), color)
    qp.setPen(Qt.PenStyle.NoPen)
    qp.setBrush(color)
    qp.drawEllipse(QPointF(0, 0), radius * 0.26, radius * 0.26)
    qp.restore()


@functools.lru_cache(maxsize=64)
def _spark_rays(radius, breathe):
    rays = QPainterPath()
    rays.setFillRule(Qt.FillRule.WindingFill)
    for i in range(10):
        long_ray = i % 2 == 0
        if long_ray:
            length, w = radius * breathe, radius * 0.30
        else:
            length, w = radius * 0.72 * (2 - breathe), radius * 0.24
        ray = QPainterPath()
        ray.addRoundedRect(QRectF(-w / 2, -length, w, length * 0.78), w / 2, w / 2)
        rays.addPath(QTransform().rotate(i * 36).map(ray))
    return rays


def draw_pin(qp, c, s, color, upright=False):
    """Push-pin, tilted when not pinned and upright when pinned."""
    qp.save()
    qp.translate(c)
    qp.rotate(0 if upright else 45)
    qp.setPen(Qt.PenStyle.NoPen)
    qp.setBrush(color)
    qp.drawRoundedRect(QRectF(-s * 0.30, -s * 0.55, s * 0.60, s * 0.22), s * 0.06, s * 0.06)   # head
    qp.drawRect(QRectF(-s * 0.18, -s * 0.36, s * 0.36, s * 0.36))                             # body
    qp.drawRoundedRect(QRectF(-s * 0.42, -s * 0.02, s * 0.84, s * 0.14), s * 0.05, s * 0.05)  # collar
    qp.setPen(pen(color, max(1.0, s * 0.09)))
    qp.drawLine(QPointF(0, s * 0.14), QPointF(0, s * 0.55))                                     # needle
    qp.restore()


def draw_plus(qp, c, size, color):
    h = size / 2
    qp.save()
    qp.setPen(pen(color, max(1.4, size * 0.15)))
    qp.drawLine(QPointF(c.x() - h, c.y()), QPointF(c.x() + h, c.y()))
    qp.drawLine(QPointF(c.x(), c.y() - h), QPointF(c.x(), c.y() + h))
    qp.restore()


def draw_eye(qp, c, size, color, slashed=False):
    """Open eye when chat windows are visible, slashed when they are hidden in the island."""
    w, h, x, y = size, size * 0.62, c.x(), c.y()
    qp.save()
    qp.setPen(pen(color, max(1.2, size * 0.11)))
    qp.setBrush(Qt.BrushStyle.NoBrush)
    outline = QPainterPath()
    outline.moveTo(x - w / 2, y)
    outline.quadTo(x, y - h, x + w / 2, y)
    outline.quadTo(x, y + h, x - w / 2, y)
    qp.drawPath(outline)
    qp.setBrush(color)
    qp.drawEllipse(c, size * 0.14, size * 0.14)
    if slashed:
        qp.drawLine(QPointF(x - w / 2, y + h * 0.75), QPointF(x + w / 2, y - h * 0.75))
    qp.restore()


def draw_gear(qp, c, size, color):
    """Settings cog with eight teeth."""
    qp.save()
    qp.translate(c)
    qp.setPen(Qt.PenStyle.NoPen)
    qp.setBrush(color)
    qp.drawPath(_gear(size))
    qp.restore()


@functools.lru_cache(maxsize=8)
def _gear(size):
    r = size / 2
    gear = QPainterPath()
    gear.setFillRule(Qt.FillRule.WindingFill)
    gear.addEllipse(QPointF(0, 0), r * 0.74, r * 0.74)
    tooth = QPainterPath()
    tooth.addRoundedRect(QRectF(-r * 0.19, -r, r * 0.38, r * 0.5), r * 0.08, r * 0.08)
    for i in range(8):
        gear.addPath(QTransform().rotate(i * 45).map(tooth))
    hole = QPainterPath()
    hole.addEllipse(QPointF(0, 0), r * 0.32, r * 0.32)
    return gear.simplified().subtracted(hole)


def draw_cross(qp, c, color):
    qp.setPen(pen(color, 1.3))
    qp.drawLine(QPointF(c.x() - 4, c.y() - 4), QPointF(c.x() + 4, c.y() + 4))
    qp.drawLine(QPointF(c.x() + 4, c.y() - 4), QPointF(c.x() - 4, c.y() + 4))


def draw_check(qp, c, color):
    qp.setPen(pen(color, 1.4))
    qp.drawPolyline([QPointF(c.x() - 3.5, c.y()), QPointF(c.x() - 1, c.y() + 2.5), QPointF(c.x() + 3.5, c.y() - 2.5)])


def draw_spinner(qp, c, radius, t, color):
    """A three-quarter ring turning once a second, for work in progress."""
    qp.setPen(pen(color, 1.6))
    qp.setBrush(Qt.BrushStyle.NoBrush)
    start = int(-(t % 1.0) * 360 * 16)            # Qt angles are in 1/16 degree, counter-clockwise
    qp.drawArc(QRectF(c.x() - radius, c.y() - radius, 2 * radius, 2 * radius), start, 270 * 16)


def draw_up_arrow(qp, c, color):
    qp.setPen(pen(color, 1.8))
    qp.drawLine(QPointF(c.x(), c.y() + 6), QPointF(c.x(), c.y() - 6))
    qp.drawPolyline([QPointF(c.x() - 5, c.y() - 1), QPointF(c.x(), c.y() - 6), QPointF(c.x() + 5, c.y() - 1)])


# ----------------------------------------------------------------- the mascot
# Claude Code's mascot from the CLI welcome screen: 17 x 5 cells, each about 2.15 times taller than wide.
#   ..#############..   head
#   ..##.#######.##..   eyes in columns 4 and 12
#   #################   body and arms (columns 0-1, 15-16)
#   ..#############..
#   ..#.#.......#.#..   legs in columns 2, 4, 12, 14
EYES, LEGS, ASPECT = (4, 12), (2, 4, 12, 14), 2.15
SLEEP_COLOR, CODE_COLOR = QColor(160, 96, 74), QColor(235, 235, 235)
# The see-through part of an eye cell, as (top, bottom) fractions of the cell height.
EYE_HOLES = {"open": (0.0, 1.0), "closed": (0.62, 0.80), "happy": (0.22, 0.40), "down": (0.40, 1.0)}


def _pose(mode, t):
    """(lift, bob, left arm, right arm, legs, eyes, look) at time t, in cells, negative is up.

    lift moves the whole body for hops, bob only the upper body.
    """
    lift = bob = arm_l = arm_r = look = 0.0
    legs, eyes, blink = [0.0] * 4, "open", (t % 3.7) < 0.14
    if mode == "coding":                                   # typing, reading along the line
        arm_l, arm_r = (0.5, -0.1) if int(t * 9) % 2 == 0 else (-0.1, 0.5)
        bob = -0.06 if int(t * 4.5) % 2 else 0.0
        eyes = "closed" if (t % 5.3) < 0.12 else "down"
        look = 0.3 * math.sin(t * 2.2)
    elif mode == "idle":                                   # breathing, a glance left then right every 7 s
        bob = -0.10 * (0.5 + 0.5 * math.sin(t * 1.9))
        g = t % 7.0
        if 2.0 < g < 2.9:
            look = -0.45
        elif 3.1 < g < 4.0:
            look = 0.45
        eyes = "closed" if blink else "open"
    elif mode == "sleep":
        bob = 0.10 + 0.10 * math.sin(t * 1.1)
        eyes = "closed"
    elif mode == "waiting":                                # hops and waves
        phase = (t * 1.8) % 1.0
        hop = pulse(phase / 0.55) if phase < 0.55 else 0.0
        wave = math.sin(t * 9)
        lift = -0.55 * hop
        legs = [0.25 * hop] * 4
        arm_l, arm_r = -0.85 + 0.35 * wave, -0.85 - 0.35 * wave
        eyes = "closed" if blink else "open"
    elif mode == "done":                                   # happy hop, arms up
        phase = (t * 1.4) % 1.0
        lift = -0.4 * pulse(phase / 0.45) if phase < 0.45 else 0.0
        arm_l = arm_r = -1.0
        eyes = "happy"
    return lift, bob, arm_l, arm_r, legs, eyes, look


def draw_mascot(qp, c, height, t, mode):
    """The pixel mascot in one of the settings.MASCOT_STATES poses."""
    color = CLAUDE
    if mode == "sleep":
        color = SLEEP_COLOR if CLAUDE.name() == DEFAULT_ACCENT else CLAUDE.darker(135)
    lift, bob, arm_l, arm_r, legs, eyes, look = _pose(mode, t)
    uh = height / 5
    uw = uh / ASPECT
    x0, base_y = c.x() - 17 * uw / 2, c.y() - height / 2
    body = QPainterPath()
    body.setFillRule(Qt.FillRule.WindingFill)
    seam = 0.04 * uh   # cells overlap a little, so no antialiasing lines show between them

    def cells(c0, c1, y, h):
        if h > 0 and c1 > c0:
            body.addRect(QRectF(x0 + c0 * uw - seam, y - seam, (c1 - c0) * uw + 2 * seam, h + 2 * seam))

    top = base_y + (lift + bob) * uh
    cells(2, 15, top, uh)                                  # head
    eye_y, el, er = top + uh, EYES[0] + look, EYES[1] + look
    for a, b in ((2, el), (el + 1, er), (er + 1, 15)):
        cells(a, b, eye_y, uh)
    hole_top, hole_bottom = EYE_HOLES[eyes]
    for e in (el, er):                                     # eye cells minus their hole
        cells(e, e + 1, eye_y, uh * hole_top)
        cells(e, e + 1, eye_y + uh * hole_bottom, uh * (1 - hole_bottom))
    arm_y = top + 2 * uh
    cells(2, 15, arm_y, uh)
    for (c0, c1, outer), r in (((0, 2, 0), arm_l), ((15, 17, 16), arm_r)):
        if r <= -0.5:      # raised: a shoulder stub and an arm pointing up
            reach = -r * 1.6 * uh
            cells(c0, c1, arm_y, uh)
            cells(outer, outer + 1, arm_y - reach, reach)
        else:              # at the side, tapping while typing
            cells(c0, c1, arm_y + r * uh, uh)
    cells(2, 15, top + 3 * uh, uh)
    ground, leg_top = base_y + (5 + lift) * uh, top + 4 * uh
    for i, col in enumerate(LEGS):
        cells(col, col + 1, leg_top, ground - legs[i] * uh - leg_top)

    qp.save()
    qp.setPen(Qt.PenStyle.NoPen)
    qp.fillPath(body, color)
    extra = {"coding": _code_bits, "sleep": _zzz, "waiting": _exclamation, "done": _sparkles}.get(mode)
    if extra:
        extra(qp, x0, top, uw, uh, t)
    qp.restore()


def _code_bits(qp, x0, y, uw, uh, t):
    """Four dashes of code rising above the head, each coming back at a new column and length."""
    for k in range(4):
        progress = t * 0.9 + k / 4
        phase, cycle = progress % 1.0, int(progress)
        c = QColor(CODE_COLOR)
        c.setAlphaF(0.85 * pulse(phase))
        qp.setBrush(c)
        column = 3 + (k * 7 + cycle * 5) % 10
        length = 1 + (k + cycle) % 3
        qp.drawRect(QRectF(x0 + column * uw, y - (0.4 + 1.5 * phase) * uh, length * uw, uh * 0.22))


def _zzz(qp, x0, y, uw, uh, t):
    for k in range(3):
        phase = (t * 0.35 + k / 3) % 1.0
        c = QColor(200, 200, 200)
        c.setAlphaF(0.9 * pulse(phase))
        size = int(5 * uh * (0.30 + 0.25 * phase)) // 2 * 2   # 2 px steps keep the font cache small
        qp.setFont(font(max(6, size), QFont.Weight.Bold))
        qp.setPen(c)
        qp.drawText(QPointF(x0 + (13 + 3 * phase) * uw, y - (0.2 + 1.8 * phase) * uh), "z")
    qp.setPen(Qt.PenStyle.NoPen)


def _exclamation(qp, x0, y, uw, uh, t):
    if int(t * 3) % 2 == 0:
        qp.setBrush(AMBER)
        qp.drawRect(QRectF(x0 + 8 * uw, y - 1.75 * uh, uw, 0.95 * uh))
        qp.drawRect(QRectF(x0 + 8 * uw, y - 0.65 * uh, uw, 0.28 * uh))


def _sparkles(qp, x0, y, uw, uh, t):
    for k, (sx, sy) in enumerate(((-1.5, 0.2), (18.0, 0.6), (3.5, -1.3), (14.0, -1.1))):
        a = pulse((t * 1.3 + k * 0.27) % 1.0)
        if a < 0.15:
            continue
        c = QColor((GREEN, AMBER)[k % 2])
        c.setAlphaF(a)
        qp.setBrush(c)
        px, py, s = x0 + sx * uw, y + sy * uh, uh * 0.22 * (0.6 + 0.6 * a)
        qp.drawRect(QRectF(px - s * 2.2, py - s / 2, s * 4.4, s))
        qp.drawRect(QRectF(px - s / 2, py - s * 2.2, s, s * 4.4))
