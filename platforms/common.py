# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Small helpers shared by every platform."""
import re
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent


def norm(title):
    """'◐ My session' -> 'my session'."""
    return re.sub(r"^[\W_]+", "", title or "").strip().lower()
