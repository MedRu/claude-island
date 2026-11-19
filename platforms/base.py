# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""The interface every platform package provides, one module per Protocol.

Documentation only: nothing imports these classes at run time. A platform that cannot do something returns
False or None, or does nothing, and the widget carries on without that feature.
"""
from pathlib import Path
from typing import Callable, Optional, Protocol


class WinCtl(Protocol):
    """winctl: find, focus, hide, close and type into a chat's terminal window."""
    HIDDEN: dict                      # what we hid (windows, or apps on macOS) -> a name

    def focus(self, title: str, pid: Optional[int] = None) -> bool: ...
    def close(self, title: str, pid: int, still_same_process: Callable[[], bool] = ...) -> Optional[str]: ...
    def send_command(self, title: str, text: str, pid: Optional[int] = None) -> bool: ...          # e.g. "/compact" at an idle prompt
    def press(self, title: str, ch: str, pid: Optional[int] = None) -> bool: ...                   # answer a prompt with one key
    def reject_with(self, title: str, text: str, pid: Optional[int] = None) -> bool: ...           # Esc, then what to do instead
    def answer_other(self, title: str, n_options: int, text: str, pid: Optional[int] = None) -> bool: ...
    def hide_all(self, chats: list, path: Optional[Path] = None) -> None: ...    # [(title, pid)]; path: memory
    def show_all(self, path: Optional[Path] = None) -> None: ...
    def prune_hidden(self, live_titles: list) -> None: ...
    def save_hidden(self, path: Path) -> None: ...
    def load_hidden(self, path: Path) -> None: ...
    def new_chat(self, folder: str) -> None: ...


class Proc(Protocol):
    # True if the process runs and, where the OS can tell, is not a reused pid.
    def pid_alive(self, pid: int, proc_start=None) -> bool: ...


class Sound(Protocol):
    def play_file(self, path) -> None: ...                              # returns at once; OSError on failure


class Instance(Protocol):
    # True if no other copy runs. The lock is held for the life of the process. Must not load Qt.
    def acquire(self) -> bool: ...


class Autostart(Protocol):
    shortcut_supported: bool          # False hides the shortcut row in the settings window
    shortcut_label: str               # e.g. "Start menu entry"

    def hook_command(self, event: str) -> str: ...    # the Claude Code hook command that starts the widget
    def is_ours(self, command: str) -> bool: ...      # also matches commands written by an older install
    def shortcut_exists(self) -> bool: ...
    def set_shortcut(self, on: bool) -> None: ...


class Hotkey(Protocol):
    LABEL: Optional[str]              # how the shortcut is written, e.g. "Ctrl+Alt+I"; None where unsupported

    def register(self, callback: Callable[[], None]) -> Optional[str]: ...   # the label, or None if it failed
    def unregister(self) -> None: ...


class Look(Protocol):
    UI_FONTS: list                    # font families to try, best first; the last is used if none matches
    HAS_GLASS: bool                   # glass() can blur the desktop behind the island

    def app_identity(self, app) -> None: ...          # once: show as Claude Island, not Python, in the Dock/taskbar
    def fix_tool_window(self, widget) -> None: ...    # called once on each frameless tool window
    def force_show(self, widget) -> None: ...         # after show(), make sure the window really appeared
    def force_focus(self, widget) -> None: ...        # give the window the keyboard
    def notch_rect(self, screen): ...                 # global QRect of the screen's camera notch, or None
    def glass(self, widget, rect, radius: float, dark: bool) -> bool: ...   # native blur behind rect; True if shown
    def keep_on_top(self, widget, over_menu_bar: bool, bump: int = 0, raise_front: bool = True) -> None: ...  # bump lifts a tooltip over the island; raise_front=False stays put, a polite neighbour to other notch apps
