# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Autostart on Linux: the Claude Code hook command and an applications menu entry."""
import sys
from pathlib import Path

from platforms.common import APP_DIR
from platforms.posix import hook_command, is_ours

__all__ = ["hook_command", "is_ours", "set_shortcut", "shortcut_exists", "shortcut_label", "shortcut_supported"]
SHORTCUT = Path.home() / ".local/share/applications/claude-island.desktop"
shortcut_supported = True
shortcut_label = "Applications menu entry"


def shortcut_exists():
    return SHORTCUT.exists()


def set_shortcut(on):
    if not on:
        SHORTCUT.unlink(missing_ok=True)
        return
    app = APP_DIR.as_posix()
    SHORTCUT.parent.mkdir(parents=True, exist_ok=True)
    SHORTCUT.write_text("[Desktop Entry]\n"
                        "Type=Application\n"
                        "Name=Claude Island\n"
                        "Comment=Every running Claude Code chat and the plan limits\n"
                        f'Exec="{sys.executable}" "{app}/island.py"\n'
                        f"Path={app}\n"
                        "Terminal=false\n"
                        "Categories=Utility;\n", encoding="utf-8")
