# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""A shortcut that works from any app: Control-Option-I (⌃⌥I), through Carbon's RegisterEventHotKey.

Carbon hot keys need no Accessibility permission and are delivered by the main run loop that Qt already runs.
Only ctypes is used, so pyobjc is not needed.
"""
import ctypes
from ctypes import POINTER, Structure, byref, c_int32, c_uint32, c_ulong, c_void_p

LABEL = "⌃⌥I"
KEY_I = 34                                   # kVK_ANSI_I
CONTROL, OPTION = 0x1000, 0x0800             # controlKey, optionKey
EVENT_CLASS_KEYBOARD = int.from_bytes(b"keyb", "big")
HOT_KEY_PRESSED = 5
SIGNATURE = int.from_bytes(b"CIsl", "big")

_HANDLER = ctypes.CFUNCTYPE(c_int32, c_void_p, c_void_p, c_void_p)
_state = {}                                  # keeps the callback and the handles alive


class _EventTypeSpec(Structure):
    _fields_ = [("eventClass", c_uint32), ("eventKind", c_uint32)]


class _HotKeyID(Structure):
    _fields_ = [("signature", c_uint32), ("id", c_uint32)]


def register(callback):
    """Call callback() when the shortcut is pressed anywhere. Returns its label, or None if it failed."""
    if _state:
        return LABEL
    try:
        carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        carbon.GetApplicationEventTarget.restype = c_void_p
        carbon.InstallEventHandler.argtypes = [c_void_p, _HANDLER, c_ulong, POINTER(_EventTypeSpec), c_void_p,
                                               POINTER(c_void_p)]
        carbon.RegisterEventHotKey.argtypes = [c_uint32, c_uint32, _HotKeyID, c_void_p, c_uint32, POINTER(c_void_p)]
        carbon.UnregisterEventHotKey.argtypes = [c_void_p]

        def on_key(_next, _event, _data):
            try:
                callback()
            except Exception:
                pass
            return 0

        handler = _HANDLER(on_key)
        spec = _EventTypeSpec(EVENT_CLASS_KEYBOARD, HOT_KEY_PRESSED)
        target = carbon.GetApplicationEventTarget()
        handler_ref, hotkey_ref = c_void_p(), c_void_p()
        if carbon.InstallEventHandler(target, handler, 1, byref(spec), None, byref(handler_ref)) != 0:
            return None
        if carbon.RegisterEventHotKey(KEY_I, CONTROL | OPTION, _HotKeyID(SIGNATURE, 1), target, 0,
                                      byref(hotkey_ref)) != 0:
            return None
    except (OSError, AttributeError):
        return None
    _state.update(carbon=carbon, handler=handler, hotkey=hotkey_ref)
    return LABEL


def unregister():
    if _state:
        _state["carbon"].UnregisterEventHotKey(_state["hotkey"])
        _state.clear()
