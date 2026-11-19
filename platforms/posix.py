# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Best-effort fallbacks shared by macOS and Linux.

Terminal windows cannot be found, focused, hidden or typed into here, so those calls return False and the widget
offers what it can. A chat is closed by ending its process. POSIX-only modules such as fcntl are imported inside
the functions that need them, so this file can be checked on any OS.
"""
import os
import signal
import subprocess
import sys

from platforms.common import APP_DIR

# ----------------------------------------------------------------- winctl
HIDDEN = {}      # stays empty: windows are never hidden here


def focus(title):
    return False


def send_command(title, text):
    return False


def press(title, ch):
    return False


def reject_with(title, text):
    return False


def answer_other(title, n_options, text):
    return False


def hide_all(titles, path=None):
    pass


def show_all(path=None):
    pass


def prune_hidden(live_titles):
    pass


def save_hidden(path):
    pass


def load_hidden(path):
    pass


def close(title, pid, still_same_process=lambda: True):
    """There is no window to close cleanly, so send SIGTERM to the claude process."""
    if not still_same_process():
        return None
    try:
        os.kill(int(pid), signal.SIGTERM)
    except OSError:
        return None
    return "process"


def chat_env():
    """The environment for a new chat."""
    # Without the CLAUDE* variables, or the new chat would think it is a child of the one that started us.
    return {k: v for k, v in os.environ.items() if not k.upper().startswith("CLAUDE")}


def first_that_runs(commands, **popen):
    """Start the first command found on this system; OSError if none is."""
    for cmd in commands:
        try:
            return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **popen)
        except OSError:
            continue
    raise OSError(f"none of {[c[0] for c in commands]} found")


# ----------------------------------------------------------------- proc
def pid_alive(pid, proc_start=None):
    """True if the process exists. A reused pid cannot be detected here."""
    try:
        os.kill(int(pid), 0)
    except PermissionError:
        return True          # exists, but belongs to another user
    except (OSError, ValueError):
        return False
    return True


# ----------------------------------------------------------------- instance
_lock = None


def acquire():
    """True if no other copy runs, using an exclusive lock on config/island.lock."""
    global _lock
    import fcntl
    path = APP_DIR / "config" / "island.lock"
    path.parent.mkdir(exist_ok=True)
    _lock = open(path, "w")   # kept open: the lock lasts as long as the process
    try:
        fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


# ----------------------------------------------------------------- autostart
def hook_command():
    return f'nohup "{sys.executable}" "{APP_DIR.as_posix()}/island.py" --hook >/dev/null 2>&1 &'


def is_ours(command):
    return f"{APP_DIR.as_posix()}/island.py" in command and "--hook" in command


# ----------------------------------------------------------------- look
def system_fonts():
    from PySide6.QtGui import QFontDatabase      # needs the running app, so look.UI_FONTS is read lazily
    return [QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()]


def force_show(widget):
    pass


def force_focus(widget):
    widget.raise_()
    widget.activateWindow()
    widget.setFocus()


def notch_rect(screen):
    return None


def float_over_menu_bar(widget, on):
    pass
