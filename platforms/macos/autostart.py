# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Autostart on macOS: the Claude Code hook command, and a small app in ~/Applications.

The app is a bundle whose executable is a shell script that starts the widget with this same Python, so it
opens from Spotlight, Launchpad or the Dock like any app. LSUIElement keeps it out of the Dock while it runs.
"""
import plistlib
import shutil
import sys
from pathlib import Path

from platforms.common import APP_DIR
from platforms.posix import hook_command, is_ours

__all__ = ["hook_command", "is_ours", "set_shortcut", "shortcut_exists", "shortcut_label", "shortcut_supported"]
shortcut_supported = True
shortcut_label = "Claude Island in Applications"
BUNDLE = Path.home() / "Applications" / "Claude Island.app"


def shortcut_exists():
    return BUNDLE.exists()


def set_shortcut(on):
    if not on:
        shutil.rmtree(BUNDLE, ignore_errors=True)
        return
    contents = BUNDLE / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    info = {
        "CFBundleName": "Claude Island",
        "CFBundleDisplayName": "Claude Island",
        "CFBundleIdentifier": "io.github.medru.claude-island",
        "CFBundleExecutable": "claude-island",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1",
        "LSUIElement": True,
    }
    with open(contents / "Info.plist", "wb") as f:
        plistlib.dump(info, f)
    launcher = contents / "MacOS" / "claude-island"
    # --detach: the widget runs on its own, so the app "finishes" at once instead of looking stuck.
    launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{APP_DIR.as_posix()}/island.py" --detach\n',
                        encoding="utf-8")
    launcher.chmod(0o755)
