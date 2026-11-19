# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Autostart on Windows: the Claude Code hook command and a Start menu shortcut."""
import os
import subprocess
from pathlib import Path

from platforms.common import APP_DIR

LAUNCHER = APP_DIR / "Start Claude Island.vbs"
SHORTCUT = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Claude Island.lnk"
NO_WINDOW = 0x08000000
shortcut_supported = True
shortcut_label = "Start menu entry"


def hook_command():
    return f'wscript.exe "{LAUNCHER.as_posix()}" --hook'


def is_ours(command):
    return LAUNCHER.name in command


def shortcut_exists():
    return SHORTCUT.exists()


def set_shortcut(on):
    if not on:
        SHORTCUT.unlink(missing_ok=True)
        return
    script = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{SHORTCUT}');"
              f"$s.TargetPath='wscript.exe';$s.Arguments='\"{LAUNCHER}\"';$s.WorkingDirectory='{APP_DIR}';"
              "$s.IconLocation='imageres.dll,76';$s.Description='Claude Island';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", script], creationflags=NO_WINDOW, timeout=20)
