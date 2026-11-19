# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Settings: defaults, load and save, and what we add to Claude Code: the start hooks and the status line."""
import base64
import json
import os
import re
import shutil
import sys
from pathlib import Path

from platforms import get_platform

HERE = Path(__file__).resolve().parent
CFG_FILE = HERE / "config" / "island_config.json"
CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()
CLAUDE_SETTINGS = CLAUDE_HOME / "settings.json"
STATUS_SCRIPT = HERE / "statusline" / "island_statusline.py"
STATUS_BEFORE = HERE / "config" / "statusline_before.json"   # your own status line, given back when turned off
AUTOSTART = get_platform().autostart
MASCOT_STATES = {"coding": "Working", "waiting": "Needs you", "done": "Done", "idle": "Idle", "sleep": "Sleeping"}
SOUND_CUES = ("start", "needs", "done", "warn", "limit")   # the keys of sounds.CUES

DEFAULTS = {
    # look
    "color_background": "#202020",
    "color_accent": "#d97757",
    "color_working": "#d97757",
    "color_waiting": "#fce100",
    "color_done": "#6ccb5f",
    "color_idle": "#60cdff",
    "color_forgotten": "#8a8a8a",
    "opacity": 100,                 # %, the whole widget
    "background_opacity": 100,      # %, the background only
    "card_opacity": 100,            # %, cards and limit boxes
    "glass": True,                  # macOS: blur the desktop behind the island
    "width": 380,
    "bar_height": 56,
    "corner_radius": 16 if sys.platform == "darwin" else 8,   # rounder on macOS, like its own glass panels
    "show_agents": True,            # a row per running sub-agent on its chat's card
    # mascot and icons
    "card_icon": "star",            # star / dot / mascot / none
    "mascot_file": "",              # your own GIF or image; "" draws the pixel mascot
    **{f"mascot_{state}": "" for state in MASCOT_STATES},
    "mascot_size": 100,             # %
    # sounds
    "sounds": True,
    "sound_volume": 100,
    **{f"sound_{cue}": True for cue in SOUND_CUES},
    **{f"sound_file_{cue}": "" for cue in SOUND_CUES},
    # timing
    "hover_delay_ms": 150,
    "linger_s": 1.2,
    "mini_after_s": 120,
    "done_minutes": 15,
    "forgotten_hours": 2,
    "animation_speed": 100,         # %
    # behaviour and startup
    "pinned": False,
    "auto_open": True,
    "reduce_motion": False,
    "show_when_started_by_hand": True,
    "global_hotkey": True,          # Ctrl+Alt+I (⌃⌥I on macOS) hides and shows the island from any app
    "quit_after_min": 0,            # 0 keeps it running with no chat
    "dx": 12,
    "dy": 12,
    "notch": False,                 # macOS: docked in the camera notch
}
NOT_RESET = ("pinned", "dx", "dy", "notch")   # "Reset to defaults" leaves the widget where it is


def load():
    try:
        saved = json.loads(CFG_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        saved = {}
    known = {k: v for k, v in saved.items() if k in DEFAULTS}
    return {**DEFAULTS, **known}


def save(cfg):
    try:
        CFG_FILE.parent.mkdir(exist_ok=True)
        CFG_FILE.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    except OSError:
        pass


def reset(cfg):
    cfg.update({k: v for k, v in DEFAULTS.items() if k not in NOT_RESET})


# ----------------------------------------------------------------- start with Claude Code
HOOK_EVENTS = ("SessionStart", "UserPromptSubmit")   # a chat opens, or you send a prompt


def _is_ours(group):
    return any(AUTOSTART.is_ours(h.get("command", "")) for h in group.get("hooks", []))


def _our_hook(event):
    return {"hooks": [{"type": "command", "command": AUTOSTART.hook_command(event), "timeout": 15, "async": True}]}


def update_start_hook():
    """Rewrite our hooks if they are out of date (an older version, Python moved), keeping them on."""
    data = _read_claude_settings()
    if not data or not start_hook_installed():
        return
    hooks = data.get("hooks", {})
    for event in HOOK_EVENTS:
        ours = [g for g in hooks.get(event, []) if _is_ours(g)]
        if ours != [_our_hook(event)]:
            set_start_hook(True)
            return


def start_hook_installed():
    try:
        hooks = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8-sig")).get("hooks", {})
    except (OSError, ValueError):
        return False
    return any(_is_ours(g) for g in hooks.get("SessionStart", []))


def _read_claude_settings():
    """~/.claude/settings.json as a dict, {} when missing, None when unreadable (then it is never overwritten)."""
    try:
        data = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_claude_settings(data):
    if CLAUDE_SETTINGS.exists():
        shutil.copy2(CLAUDE_SETTINGS, CLAUDE_SETTINGS.with_name("settings.json.bak-island-ui"))
    CLAUDE_SETTINGS.parent.mkdir(exist_ok=True)
    CLAUDE_SETTINGS.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def set_start_hook(on):
    """Add or remove our hooks in ~/.claude/settings.json, keeping everything else and a backup of the file."""
    data = _read_claude_settings()
    if data is None:
        return False
    hooks = data.setdefault("hooks", {})
    for event in HOOK_EVENTS:
        groups = [g for g in hooks.get(event, []) if not _is_ours(g)]
        if on:
            groups.append(_our_hook(event))
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)
    if not hooks:
        data.pop("hooks")
    _write_claude_settings(data)
    return True


# ----------------------------------------------------------------- status line: plan limits, context, cost
def _status_command(data):
    return str(((data or {}).get("statusLine") or {}).get("command") or "")


def _console_python():
    """The Python that runs the status line: it must print, so not pythonw on Windows."""
    exe = Path(sys.executable)
    if exe.stem.lower().startswith("pythonw"):
        console = exe.with_name(exe.name.lower().replace("pythonw", "python", 1))
        if console.exists():
            return console.as_posix()
    return exe.as_posix()


def status_line_installed():
    """True when Claude Code's status line feeds the island: ours, or a script of yours that writes ~/.claude/island."""
    command = _status_command(_read_claude_settings())
    if STATUS_SCRIPT.name in command or "island-statusline" in command:
        return True
    for token in re.findall(r"[^\s\"']+\.(?:ps1|sh|py)", command):
        try:
            text = Path(os.path.expanduser(token)).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "island" in text and ".claude" in text:
            return True
    return False


def set_status_line(on):
    """Point Claude Code's status line at our script, which keeps showing your own status line if you had one."""
    data = _read_claude_settings()
    if data is None:
        return False
    current = data.get("statusLine") if isinstance(data.get("statusLine"), dict) else None
    ours = STATUS_SCRIPT.name in _status_command(data)
    if on:
        if status_line_installed():
            return True
        command = f'"{_console_python()}" "{STATUS_SCRIPT.as_posix()}"'
        if current and current.get("command"):
            STATUS_BEFORE.parent.mkdir(exist_ok=True)
            STATUS_BEFORE.write_text(json.dumps(current), encoding="utf-8")
            command += " --then-b64 " + base64.b64encode(current["command"].encode("utf-8")).decode("ascii")
        data["statusLine"] = {**(current or {}), "type": "command", "command": command}
    elif ours:
        try:
            data["statusLine"] = json.loads(STATUS_BEFORE.read_text(encoding="utf-8"))
            STATUS_BEFORE.unlink()
        except (OSError, ValueError):
            data.pop("statusLine", None)
    else:
        return False          # a status line you set up yourself: left alone
    _write_claude_settings(data)
    return True


def _our_parts(command):
    """(python, script) paths in our status line command, or None when the command is not ours."""
    found = re.match(r'\s*"([^"]+)"\s+"([^"]+)"', command)
    return found.groups() if found and STATUS_SCRIPT.name in found.group(2) else None


def ensure_status_line():
    """At startup: set up the status line when there is none yet, and repair ours when Python or the island moved.

    A status line of your own is never changed here; the Startup switch does that, keeping yours running.
    """
    data = _read_claude_settings()
    if data is None:
        return
    command = _status_command(data)
    if not command:
        set_status_line(True)
        return
    parts = _our_parts(command)
    if parts and (parts[0] != _console_python() or parts[1] != STATUS_SCRIPT.as_posix()):
        rest = command.split(parts[1], 1)[1].lstrip('"')             # keeps --then-b64 <your line>
        data["statusLine"]["command"] = f'"{_console_python()}" "{STATUS_SCRIPT.as_posix()}"{rest}'
        _write_claude_settings(data)


def limits_report():
    """(limits found, lines explaining where they come from and what is missing)."""
    import time
    lines = [f"Claude Code folder: {CLAUDE_HOME}"]
    data = _read_claude_settings()
    command = _status_command(data)
    if data is None:
        return False, lines + ["settings.json cannot be read"]
    if not command:
        return False, lines + ["No status line: turn on Settings > Startup > Show plan limits and cost"]
    lines.append(f"Status line: {command[:140]}")
    if not status_line_installed():
        return False, lines + ["Your status line does not share the limits with the island: turn on "
                               "Settings > Startup > Show plan limits and cost (yours keeps showing)"]
    parts = _our_parts(command)
    if parts:
        for label, path in (("Python", parts[0]), ("Script", parts[1])):
            if not Path(path).exists():
                return False, lines + [f"{label} in the status line is missing: {path}. Restart the island "
                                       "to repair it"]
    folder = CLAUDE_HOME / "island"
    files = sorted(folder.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True) if folder.is_dir() else []
    if not files:
        return False, lines + [f"Nothing in {folder} yet: Claude Code runs the status line after your next "
                               "message in a chat (chats opened before the change need a new message too)"]
    age = time.time() - files[0].stat().st_mtime
    lines.append(f"Newest status file: {files[0].name}, {age / 60:.0f} min ago")
    for f in files[:20]:
        try:
            limits = json.loads(f.read_text(encoding="utf-8-sig")).get("rate_limits")
        except (OSError, ValueError, AttributeError):
            continue
        if limits:
            return True, lines + [f"Limits: {json.dumps(limits)}"]
    return False, lines + ["Claude Code runs the status line but sends no plan limits. They are only sent "
                           "when you are logged in with a Claude Pro or Max subscription (/login), not with "
                           "an API key, and after the first reply of a session. Claude Code 2.1 or later."]
