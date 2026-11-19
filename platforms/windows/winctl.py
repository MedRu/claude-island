# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Find, focus, hide, close and type into a Claude session's terminal window on Windows.

Claude Code titles its terminal "<spinner glyph> <session title>", so windows are found by title. An inactive
Windows Terminal tab is selected through UI Automation (tab_focus.ps1). A window with several tabs is never
hidden or closed as a whole, since that would take other chats with it; only the claude process is ended.
"""
import ctypes
import os
import subprocess
import time
from ctypes import wintypes as W
from pathlib import Path

from platforms.common import norm

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
USER32_ARGTYPES = {
    "EnumWindows": [ENUMPROC, W.LPARAM],
    "IsWindow": [W.HWND],
    "IsWindowVisible": [W.HWND],
    "GetWindowTextLengthW": [W.HWND],
    "GetWindowTextW": [W.HWND, W.LPWSTR, ctypes.c_int],
    "GetClassNameW": [W.HWND, W.LPWSTR, ctypes.c_int],
    "IsIconic": [W.HWND],
    "ShowWindow": [W.HWND, ctypes.c_int],
    "SetForegroundWindow": [W.HWND],
    "BringWindowToTop": [W.HWND],
    "PostMessageW": [W.HWND, W.UINT, W.WPARAM, W.LPARAM],
    "AllowSetForegroundWindow": [W.DWORD],
    "GetWindowThreadProcessId": [W.HWND, ctypes.c_void_p],
    "SwitchToThisWindow": [W.HWND, W.BOOL],
    "AttachThreadInput": [W.DWORD, W.DWORD, W.BOOL],
}
for _name, _args in USER32_ARGTYPES.items():
    getattr(user32, _name).argtypes = _args
user32.GetForegroundWindow.restype = W.HWND
user32.GetWindowThreadProcessId.restype = W.DWORD
kernel32.OpenProcess.restype = W.HANDLE
kernel32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel32.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
kernel32.CloseHandle.argtypes = [W.HANDLE]

SW_HIDE, SW_SHOW, SW_RESTORE = 0, 5, 9
VK_RETURN, VK_ESCAPE, VK_MENU = 0x0D, 0x1B, 0x12
KEYUP, UNICODE = 0x0002, 0x0004               # KEYEVENTF_* flags
INPUT_KEYBOARD = 1
WM_CLOSE = 0x0010
PROCESS_TERMINATE = 0x0001
ASFW_ANY = 0xFFFFFFFF
NO_WINDOW = 0x08000000                        # CREATE_NO_WINDOW
DETACHED = 0x00000008                         # DETACHED_PROCESS
WT, CONSOLE = "CASCADIA_HOSTING_WINDOW_CLASS", "ConsoleWindowClass"   # Windows Terminal, classic console
HERE = Path(__file__).resolve().parent
HIDDEN = {}   # windows we hid: hwnd -> normalised title


def _title(h):
    buf = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(h) + 1)
    user32.GetWindowTextW(h, buf, len(buf))
    return buf.value


def _class(h):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, buf, 256)
    return buf.value


def _starts_with_glyph(raw):
    """Claude Code puts a status glyph before the session title."""
    return bool(raw[:1]) and not raw[:1].isalnum()


def _ps(script, *args):
    return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HERE / script), *args]


def _orphan(h, cls, raw):
    """A Claude terminal hidden by an earlier run whose hidden list was lost, e.g. after a crash."""
    # Windows Terminal never hides its own windows, so a hidden one with a glyph title must be ours.
    return cls == WT and not user32.IsWindowVisible(h) and _starts_with_glyph(raw)


def adopt_orphans():
    """Take back hidden Claude terminals that no run remembers, so focus and Show all can reach them."""
    def check(h, _):
        cls = _class(h)
        if cls == WT and h not in HIDDEN:
            raw = _title(h)
            if _orphan(h, cls, raw):
                HIDDEN[h] = norm(raw)
        return True
    user32.EnumWindows(ENUMPROC(check), 0)


def find_window(title, strict=False):
    """The terminal window titled after the session, or None.

    strict, used before typing or closing, wants an exact title starting with Claude's glyph, and exactly one
    such window.
    """
    target, hits = norm(title), []
    if len(target) < 3:
        return None

    def check(h, _):
        cls = _class(h)
        if cls not in (WT, CONSOLE):
            return True
        raw = _title(h)
        if user32.IsWindowVisible(h) or h in HIDDEN or _orphan(h, cls, raw):
            t = norm(raw)
            if strict:
                ok = t == target and _starts_with_glyph(raw)
            else:
                # the terminal may cut a long title short
                ok = t == target or (len(t) >= 12 and (t.startswith(target) or target.startswith(t)))
            if ok:
                hits.append(h)
        return True
    user32.EnumWindows(ENUMPROC(check), 0)
    if strict:
        return hits[0] if len(hits) == 1 else None
    return hits[0] if hits else None


def _bring_front(h):
    if user32.IsIconic(h):
        user32.ShowWindow(h, SW_RESTORE)
    user32.SetForegroundWindow(h)
    if user32.GetForegroundWindow() == h:
        return
    # Windows guards the foreground. Try sharing input with its current owner, then an Alt tap,
    # then SwitchToThisWindow.
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    me = kernel32.GetCurrentThreadId()
    attached = bool(fg_thread) and fg_thread != me and user32.AttachThreadInput(me, fg_thread, True)
    try:
        user32.BringWindowToTop(h)
        user32.SetForegroundWindow(h)
    finally:
        if attached:
            user32.AttachThreadInput(me, fg_thread, False)
    if user32.GetForegroundWindow() != h:
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYUP, 0)
        user32.SetForegroundWindow(h)
    if user32.GetForegroundWindow() != h:
        user32.SwitchToThisWindow(h, True)


def focus(title, pid=None):
    """Bring the chat's terminal to the front, un-hiding it. False if only a tab switch could be tried."""
    h = find_window(title)
    if h:
        HIDDEN.pop(h, None)
        if not user32.IsWindowVisible(h):
            user32.ShowWindow(h, SW_SHOW)
        _bring_front(h)
        return True
    # Maybe an inactive tab: let the PowerShell helper select it and take the foreground.
    user32.AllowSetForegroundWindow(ASFW_ANY)
    subprocess.Popen(_ps("tab_focus.ps1", "-Title", norm(title)), creationflags=NO_WINDOW)
    return False


def tab_counts():
    """{hwnd: tabs} for Windows Terminal windows, or {} if UI Automation fails. Takes 1-3 s."""
    try:
        out = subprocess.run(_ps("tab_count.ps1"), capture_output=True, text=True, timeout=15,
                             creationflags=NO_WINDOW).stdout
        counts = {}
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 2:
                counts[int(parts[0])] = int(parts[1])
        return counts
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def _single_tab(h, counts):
    """True if the window is known to hold only this chat; an unknown tab count counts as no."""
    return h in HIDDEN or _class(h) == CONSOLE or counts.get(h) == 1


def close(title, pid, still_same_process=lambda: True):
    """Close the chat. Returns "window", "process" or None.

    A window holding only this chat gets WM_CLOSE, so Claude exits cleanly and keeps the transcript. Otherwise
    only the claude process is ended, once still_same_process() rules out a reused pid.
    """
    h = find_window(title, strict=True)
    if h and _single_tab(h, tab_counts()):
        HIDDEN.pop(h, None)
        user32.PostMessageW(h, WM_CLOSE, 0, 0)
        return "window"
    if not still_same_process():
        return None
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
    if not handle:
        return None
    kernel32.TerminateProcess(handle, 1)
    kernel32.CloseHandle(handle)
    return "process"


class _KEY(ctypes.Structure):
    _fields_ = [("vk", W.WORD), ("scan", W.WORD), ("flags", W.DWORD), ("time", W.DWORD), ("extra", ctypes.c_size_t)]


class _MOUSE(ctypes.Structure):
    # Never sent. It is the largest union member, so INPUT gets the size Windows expects.
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("data", W.DWORD), ("flags", W.DWORD), ("time", W.DWORD),
                ("extra", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEY), ("mi", _MOUSE)]
    _fields_ = [("type", W.DWORD), ("u", _U)]


def _send(h, keys):
    """Send (vk, scan, flags) key events, only while h is still in front."""
    if user32.GetForegroundWindow() != h:   # you may have clicked elsewhere meanwhile
        raise RuntimeError("the chat window lost focus")
    events = [_INPUT(INPUT_KEYBOARD, _INPUT._U(ki=_KEY(vk, scan, flags, 0, 0))) for vk, scan, flags in keys]
    arr = (_INPUT * len(events))(*events)
    user32.SendInput(len(events), arr, ctypes.sizeof(_INPUT))


def _key(vk):
    return [(vk, 0, 0), (vk, 0, KEYUP)]


def _chars(text):
    events = []
    for c in text:
        events.append((0, ord(c), UNICODE))
        events.append((0, ord(c), UNICODE | KEYUP))
    return events


def _type_line(h, text):
    _send(h, _chars(text))
    time.sleep(0.2)   # let the CLI draw its slash-command menu before Enter
    _send(h, _key(VK_RETURN))


def _in_front(title, keys):
    """Bring the chat up, run keys(hwnd), and hide it again if it was hidden. False on any doubt."""
    h = find_window(title, strict=True)
    if not h:
        return False
    hidden = h in HIDDEN
    if hidden:
        user32.ShowWindow(h, SW_SHOW)
    _bring_front(h)
    time.sleep(0.3)
    try:
        if user32.GetForegroundWindow() != h:
            return False
        keys(h)
        return True
    except RuntimeError:
        return False
    finally:
        if hidden:
            time.sleep(0.35)
            user32.ShowWindow(h, SW_HIDE)


# Prompt keys checked on Claude Code 2.1.327. Permission prompt: "1" is Yes, Esc is No and the next line says
# what to do instead. Question: an option's number picks it, and options + 1 is "Type something".
def send_command(title, text):
    """Run a line such as '/compact'. Only call it while the chat is idle at its prompt."""
    return _in_front(title, lambda h: _type_line(h, text))


def press(title, ch):
    return _in_front(title, lambda h: _send(h, _chars(ch)))


def reject_with(title, text):
    def keys(h):
        _send(h, _key(VK_ESCAPE))
        time.sleep(0.8)
        if text.strip():
            _type_line(h, text)
    return _in_front(title, keys)


def answer_other(title, n_options, text):
    def keys(h):
        _send(h, _chars(str(n_options + 1)))
        time.sleep(0.4)
        _type_line(h, text)
    return _in_front(title, keys)


def hide_all(chats, path=None):
    """Hide these chats' windows from screen and taskbar, except windows that hold other tabs too.

    chats: [(title, pid)]; windows are found by title here.
    """
    counts = tab_counts()
    for t, _pid in chats:
        h = find_window(t, strict=True)
        if h and h not in HIDDEN and user32.IsWindowVisible(h) and _single_tab(h, counts):
            user32.ShowWindow(h, SW_HIDE)
            HIDDEN[h] = norm(_title(h))
    if path:
        save_hidden(path)


def show_all(path=None):
    # Copies of HIDDEN are iterated here and below: worker threads (hide_all, close) change it meanwhile.
    for h in list(HIDDEN):
        if user32.IsWindow(h):
            user32.ShowWindow(h, SW_SHOW)
    HIDDEN.clear()
    if path:
        save_hidden(path)


def prune_hidden(live_titles):
    """Forget closed windows and give back hidden ones whose chat has ended."""
    live = {norm(t) for t in live_titles}
    for h in list(HIDDEN):
        alive = user32.IsWindow(h)
        if alive and norm(_title(h)) in live:
            continue
        if alive:
            user32.ShowWindow(h, SW_SHOW)
        HIDDEN.pop(h, None)


def save_hidden(path):
    try:
        path.parent.mkdir(exist_ok=True)
        path.write_text("\n".join(f"{h}\t{t}" for h, t in list(HIDDEN.items())), encoding="utf-8")
    except OSError:
        pass


def load_hidden(path):
    """After a restart, take back the windows the last run hid."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        handle, _, title = line.partition("\t")
        if not (handle.isdigit() and title):
            continue
        h = int(handle)
        # Windows reuses handles, so it must still be a hidden terminal with the same title.
        if (user32.IsWindow(h) and not user32.IsWindowVisible(h) and _class(h) in (WT, CONSOLE)
                and norm(_title(h)) == title):
            HIDDEN[h] = title
    adopt_orphans()


def new_chat(folder):
    """Start a new Claude Code in its own Windows Terminal window, or a console without Windows Terminal."""
    # Without the CLAUDE* variables, or the new session thinks it is a child of the one that started this
    # widget and does not save its transcript.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("CLAUDE")}
    try:
        subprocess.Popen(["wt", "-w", "new", "-d", str(folder), "claude"], env=env, creationflags=DETACHED)
    except OSError:
        subprocess.Popen(["cmd", "/c", "start", "", "cmd", "/k", "claude"], cwd=str(folder), env=env,
                         creationflags=NO_WINDOW)
