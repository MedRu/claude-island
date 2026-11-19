# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Fonts, tool windows and the camera notch dock on macOS.

The exact notch comes from AppKit (pip install pyobjc-framework-Cocoa). Without it the notch is guessed from the
taller menu bar of notched screens.
"""
from platforms.posix import force_focus, force_show, system_fonts

__all__ = ["fix_tool_window", "force_show", "force_focus", "notch_rect", "float_over_menu_bar"]

NOTCH_MENU_BAR = 32          # pt: notched screens have a ~37 pt menu bar, others 24-25 pt
GUESS_W = 200                # pt: assumed notch width when AppKit is not available

# Raw AppKit values, so pyobjc is only needed at call time.
MENU_LEVEL, FLOATING_LEVEL = 25, 3                 # NSMainMenuWindowLevel + 1, NSFloatingWindowLevel
ALL_SPACES_STATIONARY = 1 | 16                     # NSWindowCollectionBehavior CanJoinAllSpaces | Stationary


def __getattr__(name):
    # UI_FONTS asks Qt for the system font, which only works once the app is running.
    if name == "UI_FONTS":
        return system_fonts()
    raise AttributeError(name)


def fix_tool_window(widget):
    """Keep the window on screen when the app is not active (macOS hides tool windows then)."""
    from PySide6.QtCore import Qt
    widget.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)


def _appkit_notch(screen):
    """(left, width, height) of the notch from NSScreen; None if there is no notch, False without AppKit."""
    try:
        from AppKit import NSScreen
    except ImportError:
        return False
    g = screen.geometry()
    for ns in NSScreen.screens():
        f = ns.frame()
        same_screen = (round(f.size.width) == g.width() and round(f.size.height) == g.height()
                       and round(f.origin.x) == g.x())
        if not same_screen:
            continue
        top = ns.safeAreaInsets().top if hasattr(ns, "safeAreaInsets") else 0
        if top <= 0:
            return None
        left_w = round(ns.auxiliaryTopLeftArea().size.width)
        right_w = round(ns.auxiliaryTopRightArea().size.width)
        return left_w, g.width() - left_w - right_w, round(top)
    return False


def notch_rect(screen):
    """The camera notch of this screen in global Qt coordinates, or None."""
    from PySide6.QtCore import QRect
    if screen is None:
        return None
    g = screen.geometry()
    menu_h = screen.availableGeometry().top() - g.top()
    found = _appkit_notch(screen)
    if found:
        left_w, w, h = found
        return QRect(g.left() + left_w, g.top(), w, h)
    if found is None or menu_h < NOTCH_MENU_BAR:
        return None
    return QRect(g.center().x() - GUESS_W // 2, g.top(), GUESS_W, menu_h)


def float_over_menu_bar(widget, on):
    """Docked in the notch, the island sits inside the menu bar, so its window level must be above it."""
    try:
        import objc
        window = objc.objc_object(c_void_p=int(widget.winId())).window()
        window.setLevel_(MENU_LEVEL if on else FLOATING_LEVEL)
        window.setCollectionBehavior_(ALL_SPACES_STATIONARY if on else 0)
    except Exception:                                      # no pyobjc, or no native window yet
        pass
