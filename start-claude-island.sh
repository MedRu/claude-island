#!/bin/sh
# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
# Starts Claude Island in the background on macOS and Linux. The Windows twin is "Start Claude Island.vbs".
# Run it by hand to start the widget alone; Claude Code hooks add --hook.
# Uses python3 from PATH, or the interpreter named in $PYTHON. It needs PySide6.
here="$(cd "$(dirname "$0")" && pwd)"
# Prefer the project venv (python3 on PATH may be too new for PySide6 wheels).
if [ -z "$PYTHON" ] && [ -x "$here/.venv/bin/python" ]; then
  PYTHON="$here/.venv/bin/python"
fi
exec "${PYTHON:-python3}" "$here/island.py" --detach "$@"
