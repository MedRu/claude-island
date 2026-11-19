# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Terminal windows on macOS.

A chat is found through its process: the claude pid's parents lead to the app it runs in (Terminal, iTerm2,
VS Code, Ghostty...). That app is brought to the front, or hidden and shown again, with AppKit when pyobjc is
installed and System Events otherwise. In Terminal and iTerm2 the chat's own tab is selected too, by its tty.
macOS asks once for permission to control those apps.

Answering from the island (Allow, Deny, a reply, /compact) types into the chat. In iTerm2 the text is written
straight to the chat's session, without bringing it up. Elsewhere the chat is brought to the front, checked to
really be in front (and on its own tab in Terminal), then typed into with System Events, which needs
System Settings > Privacy & Security > Accessibility for the app that started the island.
"""
import plistlib
import shlex
import subprocess
import sys
import time
from pathlib import Path

from platforms.posix import chat_env, close

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
        # Python.app inside Python.framework and the like are runtimes, not the app the chat shows in
        if ".app/" in command and ".framework/" not in command.split(".app/")[0]:
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


# ----------------------------------------------------------------- typing into a chat
# Prompt keys as on Windows (Claude Code 2.1): a permission prompt takes "1" for Yes, Esc for No and then what
# to do instead; a question takes an option's number, and options + 1 is "Type something".
# Steps: ("text", str), ("esc",), ("enter",), ("wait", seconds).
ACCESSIBILITY_PANE = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
_asked_access = False


def _quote(text):
    """An AppleScript string literal; the reply box is one line, so line breaks become spaces."""
    text = " ".join(str(text).splitlines())
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _osascript_checked(script):
    """Run AppleScript; returns stdout. RuntimeError with the reason when it fails."""
    try:
        done = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"osascript: {e}")
    if done.returncode:
        err = done.stderr.strip()
        if "not allowed" in err or "(1002)" in err or "(-1719)" in err or "(-25211)" in err:
            _ask_accessibility()
            raise PermissionError("macOS blocks typing into the chat: allow the app that started Claude Island "
                                  "(Terminal, or Python) in System Settings > Privacy & Security > Accessibility")
        raise RuntimeError(err or "osascript failed")
    return done.stdout.strip()


def _ask_accessibility():
    """Open the Accessibility settings once per run, where the permission is given."""
    global _asked_access
    if not _asked_access:
        _asked_access = True
        subprocess.Popen(["open", ACCESSIBILITY_PANE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _system_events(steps):
    lines = []
    for step in steps:
        kind = step[0]
        if kind == "esc":
            lines.append("key code 53")
        elif kind == "enter":
            lines.append("key code 36")
        elif kind == "wait":
            lines.append(f"delay {step[1]}")
        elif step[1].isascii():
            lines.append(f"keystroke {_quote(step[1])}")
        else:                      # keystroke mistypes accents and other non-ASCII text: paste it instead
            lines += [f"set the clipboard to {_quote(step[1])}", "keystroke \"v\" using command down",
                      "delay 0.3"]
    return "\n".join(lines)


def _steps_block(steps):
    """Steps inside the System Events tell; a paste briefly leaves it to set the clipboard."""
    out = []
    for line in _system_events(steps).splitlines():
        if line.startswith("set the clipboard"):
            out += ["    end tell", "    " + line, "    tell application \"System Events\""]
        else:
            out.append("        " + line)
    return "\n".join(out)


def _iterm_writes(steps):
    lines = []
    for step in steps:
        kind = step[0]
        if kind == "esc":
            lines.append("write text (character id 27) newline NO")
        elif kind == "enter":
            lines.append("write text (character id 13) newline NO")
        elif kind == "wait":
            lines.append(f"delay {step[1]}")
        else:
            lines.append(f"write text {_quote(step[1])} newline NO")
    return "\n".join("                        tell s to " + line if not line.startswith("delay")
                     else "                        " + line for line in lines)


ITERM_WRITE = '''tell application id "com.googlecode.iterm2"
    repeat with w in windows
        repeat with t in tabs of w
            repeat with s in sessions of t
                if tty of s is "{tty}" then
{steps}
                    return "ok"
                end if
            end repeat
        end repeat
    end repeat
    return "gone"
end tell'''

TYPE_IN_FRONT = '''{tab_check}
tell application "System Events"
    set front_app to first application process whose frontmost is true
    if bundle identifier of front_app is not "{bundle}" then return "lost"
end tell
set old_clip to missing value
try
    set old_clip to the clipboard
end try
try
    tell application "System Events"
{steps}
    end tell
on error e number n
    if old_clip is not missing value then set the clipboard to old_clip
    error e number n
end try
if old_clip is not missing value then set the clipboard to old_clip
return "ok"'''

TERMINAL_TAB_CHECK = '''tell application id "com.apple.Terminal"
    if (count of windows) is 0 then return "lost"
    if tty of selected tab of front window is not "{tty}" then return "lost"
end tell'''


def _type(pid, steps):
    """Type steps into the chat run by pid. False when the chat or its window cannot be reached for sure."""
    app = _app_of(pid) if pid else None
    tty = _tty(pid) if pid else None
    if not app:
        return False
    bundle_id = app[0]
    if bundle_id == ITERM and tty:
        script = ITERM_WRITE.replace("{tty}", tty).replace("{steps}", _iterm_writes(steps))
        return _osascript_checked(script) == "ok"
    if bundle_id == TERMINAL and not tty:
        return False
    was_hidden = bundle_id in HIDDEN
    focus(None, pid)
    time.sleep(0.35)               # let the app and its tab come to the front
    try:
        check = TERMINAL_TAB_CHECK.replace("{tty}", tty) if bundle_id == TERMINAL else ""
        script = TYPE_IN_FRONT.replace("{tab_check}", check).replace("{bundle}", bundle_id)
        result = _osascript_checked(script.replace("{steps}", _steps_block(steps)))
        if result != "ok":
            print(f"not typed: {app[1]} was not in front on the chat", file=sys.stderr)
        return result == "ok"
    finally:
        if was_hidden:
            time.sleep(0.35)
            _set_visible(bundle_id, False)
            HIDDEN[bundle_id] = app[1]


def send_command(title, text, pid=None):
    """Run a line such as '/compact'. Only call it while the chat is idle at its prompt."""
    return _type(pid, [("text", text), ("wait", 0.2), ("enter",)])


def press(title, ch, pid=None):
    return _type(pid, [("text", ch)])


def reject_with(title, text, pid=None):
    steps = [("esc",)]
    if text.strip():
        steps += [("wait", 0.8), ("text", text), ("wait", 0.2), ("enter",)]
    return _type(pid, steps)


def answer_other(title, n_options, text, pid=None):
    return _type(pid, [("text", str(n_options + 1)), ("wait", 0.4), ("text", text), ("wait", 0.2), ("enter",)])
