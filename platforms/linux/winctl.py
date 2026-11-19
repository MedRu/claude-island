# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Terminal windows on Linux: not controlled, but a new chat opens in a terminal emulator."""
from platforms.posix import (HIDDEN, answer_other, chat_env, close, first_that_runs, focus, hide_all, load_hidden,
                             press, prune_hidden, reject_with, save_hidden, send_command, show_all)

__all__ = ["HIDDEN", "answer_other", "close", "focus", "hide_all", "load_hidden", "new_chat", "press", "prune_hidden",
           "reject_with", "save_hidden", "send_command", "show_all"]


def new_chat(folder):
    """Start claude in the desktop's default terminal, else in the first common one found."""
    terminals = [
        ["x-terminal-emulator", "-e", "claude"],
        ["gnome-terminal", "--", "claude"],
        ["konsole", "-e", "claude"],
        ["xterm", "-e", "claude"],
    ]
    first_that_runs(terminals, cwd=str(folder), env=chat_env(), start_new_session=True)
