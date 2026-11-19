# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Terminal windows on macOS.

A chat is found through its process: the claude pid's parents lead to the app it runs in (Terminal, iTerm2,
VS Code, Ghostty...). That app is brought to the front, or hidden and shown again, with AppKit when pyobjc is
installed and System Events otherwise. In Terminal and iTerm2 the chat's own tab is selected too, by its tty.
macOS asks once for permission to control those apps.

Typing into a chat is not supported yet, so answers are given in the terminal.
"""
import plistlib
import shlex
import subprocess
from pathlib import Path

from platforms.posix import answer_other, chat_env, close, press, reject_with, send_command

__all__ = ["HIDDEN", "answer_other", "close", "focus", "hide_all", "load_hidden", "new_chat", "press", "prune_hidden",
           "reject_with", "save_hidden", "send_command", "show_all"]

HIDDEN = {}       # apps we hid: bundle id -> app name
TERMINAL, ITERM = "com.apple.Terminal", "com.googlecode.iterm2"
ACTIVATE_IGNORING_OTHER_APPS = 2          # NSApplicationActivateIgnoringOtherApps

TERMINAL_TAB = '''tell application id "com.apple.Terminal"
    repeat with w in windows
        repeat with t in tabs of w
            if tty of t is "{tty}" then
                set selected tab of w to t
                set index of w to 1
                return "ok"
            end if
        end repeat
    end repeat
end tell'''

ITERM_TAB = '''tell application id "com.googlecode.iterm2"
    repeat with w in windows
        repeat with t in tabs of w
            repeat with s in sessions of t
                if tty of s is "{tty}" then
                    select w
                    select t
                    select s
                    return "ok"
                end if
            end repeat
        end repeat
    end repeat
end tell'''


def _run(cmd, timeout=4):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _osascript(script):
    return _run(["osascript", "-e", script]).strip()


def _processes():
    """pid -> (parent pid, executable path) for every process."""
    table = {}
    for line in _run(["ps", "-A", "-o", "pid=,ppid=,comm="]).splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = (int(parts[1]), parts[2])
    return table


def _app_of(pid, table=None):
    """(bundle id, app name) of the app a process runs in, found by walking up its parents; None if none."""
    table = table if table is not None else _processes()
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    for _ in range(40):
        if pid <= 1 or pid not in table:
            return None
        ppid, command = table[pid]
        if ".app/" in command:
            bundle = Path(command.split(".app/")[0] + ".app")      # the outer app, not a helper inside it
            try:
                with open(bundle / "Contents" / "Info.plist", "rb") as f:
                    info = plistlib.load(f)
                return info["CFBundleIdentifier"], info.get("CFBundleName") or bundle.stem
            except (OSError, KeyError, ValueError, plistlib.InvalidFileException):
                return None
        pid = ppid
    return None


def _running(bundle_id):
    """The app's NSRunningApplication objects, or None without pyobjc."""
    try:
        from AppKit import NSRunningApplication
    except ImportError:
        return None
    return list(NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id))


def _set_visible(bundle_id, visible):
    apps = _running(bundle_id)
    if apps is None:
        _osascript(f'tell application "System Events" to set visible of every application process '
                   f'whose bundle identifier is "{bundle_id}" to {"true" if visible else "false"}')
        return
    for app in apps:
        if visible:
            app.unhide()
        else:
            app.hide()


def _activate(bundle_id):
    apps = _running(bundle_id)
    if apps:
        apps[0].unhide()
        apps[0].activateWithOptions_(ACTIVATE_IGNORING_OTHER_APPS)
    else:
        _osascript(f'tell application id "{bundle_id}" to activate')


def _tty(pid):
    name = _run(["ps", "-o", "tty=", "-p", str(int(pid))]).strip()
    return f"/dev/{name}" if name and "?" not in name else None


def focus(title, pid=None):
    """Bring the chat's app to the front, on the chat's own tab in Terminal and iTerm2."""
    app = _app_of(pid) if pid else None
    if not app:
        return False
    bundle_id = app[0]
    HIDDEN.pop(bundle_id, None)
    _activate(bundle_id)
    tty = _tty(pid)
    tab = {TERMINAL: TERMINAL_TAB, ITERM: ITERM_TAB}.get(bundle_id)
    if tty and tab:
        _osascript(tab.replace("{tty}", tty))
    return True


def hide_all(chats, path=None):
    """Hide the apps the chats run in. chats: [(title, pid)]. The whole app hides, with its other windows."""
    table = _processes()
    for _title, pid in chats:
        app = _app_of(pid, table)
        if app and app[0] not in HIDDEN:
            _set_visible(app[0], False)
            HIDDEN[app[0]] = app[1]
    if path:
        save_hidden(path)


def show_all(path=None):
    for bundle_id in list(HIDDEN):
        _set_visible(bundle_id, True)
    HIDDEN.clear()
    if path:
        save_hidden(path)


def prune_hidden(live_titles):
    """Once no chat is left, give the hidden apps back."""
    if not live_titles and HIDDEN:
        show_all()


def save_hidden(path):
    try:
        path.parent.mkdir(exist_ok=True)
        path.write_text("\n".join(f"{b}\t{n}" for b, n in list(HIDDEN.items())), encoding="utf-8")
    except OSError:
        pass


def load_hidden(path):
    """After a restart, remember the apps the last run hid, so "Show all chats" brings them back."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        bundle_id, _, name = line.partition("\t")
        if bundle_id and name:
            HIDDEN[bundle_id] = name


def new_chat(folder):
    """Open a Terminal.app window running claude in that folder."""
    line = f"cd {shlex.quote(str(folder))} && claude"
    escaped = line.replace("\\", "\\\\").replace('"', '\\"')   # it goes inside an AppleScript string
    script = f'tell application "Terminal" to do script "{escaped}"'
    subprocess.Popen(["osascript", "-e", script], env=chat_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
