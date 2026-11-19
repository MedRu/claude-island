# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Settings: defaults, load and save, and the Claude Code hooks that start the widget."""
import json
import shutil
from pathlib import Path

from platforms import get_platform

HERE = Path(__file__).resolve().parent
CFG_FILE = HERE / "config" / "island_config.json"
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
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
    "width": 380,
    "bar_height": 56,
    "corner_radius": 8,
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


def start_hook_installed():
    try:
        hooks = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8-sig")).get("hooks", {})
    except (OSError, ValueError):
        return False
    return any(_is_ours(g) for g in hooks.get("SessionStart", []))


def set_start_hook(on):
    """Add or remove our hooks in ~/.claude/settings.json, keeping everything else and a backup of the file."""
    try:
        data = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError):
        return False      # unreadable: never overwrite it
    hooks = data.setdefault("hooks", {})
    ours = {"hooks": [{"type": "command", "command": AUTOSTART.hook_command(), "timeout": 15, "async": True}]}
    for event in HOOK_EVENTS:
        groups = [g for g in hooks.get(event, []) if not _is_ours(g)]
        if on:
            groups.append(ours)
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)
    if not hooks:
        data.pop("hooks")
    if CLAUDE_SETTINGS.exists():
        shutil.copy2(CLAUDE_SETTINGS, CLAUDE_SETTINGS.with_name("settings.json.bak-island-ui"))
    CLAUDE_SETTINGS.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True
