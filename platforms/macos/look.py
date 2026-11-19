# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Fonts, tool windows and the camera notch dock on macOS.

The exact notch comes from AppKit (pip install pyobjc-framework-Cocoa). Without it the notch is guessed from the
taller menu bar of notched screens.
"""
from platforms.posix import force_focus, force_show, system_fonts

__all__ = ["fix_tool_window", "force_show", "force_focus", "notch_rect", "keep_on_top", "glass", "HAS_GLASS", "app_identity"]

NOTCH_MENU_BAR = 32          # pt: notched screens have a ~37 pt menu bar, others 24-25 pt
GUESS_W = 200                # pt: assumed notch width when AppKit is not available

# Raw AppKit values, so pyobjc is only needed at call time.
MENU_LEVEL, FLOATING_LEVEL = 25, 3                 # NSMainMenuWindowLevel + 1, NSFloatingWindowLevel
# NSWindowCollectionBehavior: CanJoinAllSpaces | Stationary | IgnoresCycle | FullScreenAuxiliary,
# so the island stays on every desktop and over full-screen apps.
EVERYWHERE = 1 | 16 | 64 | 256
HUD_MATERIAL, BEHIND_WINDOW, ALWAYS_ACTIVE, BELOW = 13, 0, 1, -1   # NSVisualEffectView values, NSWindowBelow

ACCESSORY_POLICY = 1         # NSApplicationActivationPolicyAccessory
HAS_GLASS = True             # glass() works when pyobjc is installed
_glass_views = {}            # window id -> the native view blurring what is behind that window


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


def keep_on_top(widget, over_menu_bar=False):
    """Float above other apps, on every desktop and over full-screen apps.

    Docked in the notch the island sits inside the menu bar, so its level must be above the menu bar too.
    """
    if not widget.isVisible():
        return
    try:
        import objc
        window = objc.objc_object(c_void_p=int(widget.winId())).window()
        level = MENU_LEVEL if over_menu_bar else FLOATING_LEVEL
        if window.level() != level:
            window.setLevel_(level)
        if window.collectionBehavior() != EVERYWHERE:
            window.setCollectionBehavior_(EVERYWHERE)
        window.orderFrontRegardless()                      # in front without taking focus
    except Exception:                                      # no pyobjc, or no native window yet
        widget.raise_()


def _make_glass(content, dark):
    """Liquid Glass on macOS 26 and later, the frosted HUD material before it."""
    import objc
    from AppKit import NSAppearance, NSMakeRect, NSVisualEffectView
    try:
        view = objc.lookUpClass("NSGlassEffectView").alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
    except objc.nosuchclass_error:
        view = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        view.setMaterial_(HUD_MATERIAL)
        view.setBlendingMode_(BEHIND_WINDOW)
        view.setState_(ALWAYS_ACTIVE)
        view.setWantsLayer_(True)
        view.layer().setMasksToBounds_(True)
    view.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua" if dark else "NSAppearanceNameAqua"))
    # Behind Qt's view, which stays see-through where the island paints nothing.
    content.superview().addSubview_positioned_relativeTo_(view, BELOW, content)
    return view


def glass(widget, rect, radius, dark=True):
    """Blur the desktop behind rect (widget coordinates, a QRectF) with rounded corners; None removes it.

    Returns True when the glass is there, so the island paints a lighter tint over it instead of its solid
    background.
    """
    key = int(widget.winId())
    view = _glass_views.get(key)
    if rect is None or rect.isEmpty():
        if view is not None:
            view.setHidden_(True)
        return False
    try:
        import objc
        from AppKit import NSMakeRect
        content = objc.objc_object(c_void_p=key)
        if view is None:
            view = _glass_views[key] = _make_glass(content, dark)
        y = rect.y() if content.isFlipped() else content.bounds().size.height - rect.y() - rect.height()
        frame = content.convertRect_toView_(NSMakeRect(rect.x(), y, rect.width(), rect.height()),
                                            content.superview())
        view.setFrame_(frame)
        if view.respondsToSelector_(b"setCornerRadius:"):
            view.setCornerRadius_(radius)
        else:
            view.layer().setCornerRadius_(radius)
        view.setHidden_(False)
        return True
    except Exception:                    # no pyobjc, or the window is not native yet: keep the painted background
        return False


def app_identity(app):
    """No Dock icon and no "Python" menu bar: run as an accessory app, like menu bar extras do.

    Plain ctypes, so it works without pyobjc. Qt makes the app a regular one at startup, so this runs after.
    """
    import ctypes
    try:
        objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
        get = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(address)
        set_policy = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long)(address)
        ns_app = get(objc.objc_getClass(b"NSApplication"), objc.sel_registerName(b"sharedApplication"))
        set_policy(ns_app, objc.sel_registerName(b"setActivationPolicy:"), ACCESSORY_POLICY)
    except (OSError, AttributeError):
        pass
