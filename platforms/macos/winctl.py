# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Terminal windows on macOS: not controlled, but a new chat opens in Terminal.app."""
import shlex
import subprocess

from platforms.posix import (HIDDEN, answer_other, chat_env, close, focus, hide_all, load_hidden, press,
                             prune_hidden, reject_with, save_hidden, send_command, show_all)

__all__ = ["HIDDEN", "answer_other", "close", "focus", "hide_all", "load_hidden", "new_chat", "press", "prune_hidden",
           "reject_with", "save_hidden", "send_command", "show_all"]


def new_chat(folder):
    """Open a Terminal.app window running claude in that folder."""
    line = f"cd {shlex.quote(str(folder))} && claude"
    escaped = line.replace("\\", "\\\\").replace('"', '\\"')   # it goes inside an AppleScript string
    script = f'tell application "Terminal" to do script "{escaped}"'
    subprocess.Popen(["osascript", "-e", script], env=chat_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
