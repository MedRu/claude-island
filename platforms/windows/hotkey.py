# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""A shortcut that works from any app: Ctrl+Alt+I, through RegisterHotKey."""
import ctypes
from ctypes import wintypes

LABEL = "Ctrl+Alt+I"
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000
VK_I, WM_HOTKEY, HOTKEY_ID = 0x49, 0x0312, 0x1C1A
_filter = None


def register(callback):
    """Call callback() when the shortcut is pressed anywhere. Returns its label, or None if it is taken."""
    global _filter
    if _filter:
        return LABEL
    from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication

    class HotkeyFilter(QAbstractNativeEventFilter):
        def nativeEventFilter(self, event_type, message):
            if event_type == b"windows_generic_MSG":
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    callback()
                    return True, 0
            return False, 0

    # No window: the message goes to this thread's queue, which Qt's event loop reads.
    if not ctypes.windll.user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_I):
        return None
    _filter = HotkeyFilter()
    QCoreApplication.instance().installNativeEventFilter(_filter)
    return LABEL


def unregister():
    global _filter
    if _filter:
        ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.instance().removeNativeEventFilter(_filter)
        _filter = None
