# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Process checks on Windows, including whether a pid was reused."""
import ctypes

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_ACCESS_DENIED = 5
STILL_ACTIVE = 259

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenProcess.restype = ctypes.c_void_p
_k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
_k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
_k32.CloseHandle.argtypes = [ctypes.c_void_p]
_k32.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(ctypes.c_ulonglong)] * 4


def pid_alive(pid, proc_start=None):
    """True if the process runs and, given the session file's procStart, is that same process."""
    h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        # Access denied means it exists, but its identity cannot be checked.
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED and proc_start is None
    try:
        code = ctypes.c_ulong()
        if not _k32.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != STILL_ACTIVE:
            return False
        if proc_start:
            created, exited, kernel, user = (ctypes.c_ulonglong() for _ in range(4))
            if _k32.GetProcessTimes(h, ctypes.byref(created), ctypes.byref(exited),
                                    ctypes.byref(kernel), ctypes.byref(user)):
                return str(created.value) == str(proc_start)
        return True
    finally:
        _k32.CloseHandle(h)
