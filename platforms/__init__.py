# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Everything that differs between operating systems, behind the small interface described in base.py.

    from platforms import get_platform
    PLAT = get_platform()
    PLAT.winctl.focus(title)

Each module (winctl, proc, sound, instance, autostart, look, hotkey) is imported the first time it is used. The OS comes
from sys.platform, and ISLAND_PLATFORM=windows|macos|linux overrides it. Importing this package never loads Qt,
so island.py can check for a running copy cheaply.
"""
import importlib
import os
import sys

NAMES = ("windows", "macos", "linux")
MODULES = ("winctl", "proc", "sound", "instance", "autostart", "look", "hotkey")
_current = None


def platform_name():
    forced = os.environ.get("ISLAND_PLATFORM", "").strip().lower()
    if forced in NAMES:
        return forced
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


class Platform:
    """One OS's modules, each imported on first use."""

    def __init__(self, name):
        self.name = name

    def __getattr__(self, module):
        if module not in MODULES:
            raise AttributeError(module)
        loaded = importlib.import_module(f"{__name__}.{self.name}.{module}")
        setattr(self, module, loaded)
        return loaded

    def __repr__(self):
        return f"<Claude Island platform {self.name}>"


def get_platform():
    global _current
    if _current is None:
        _current = Platform(platform_name())
    return _current
