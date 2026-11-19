#!/bin/sh
# Claude Island status line for macOS / Linux (POSIX sh + python3).
#
# Claude Code runs the status line command with a JSON document on stdin (model, context window,
# plan limits, cost...). This script saves that JSON, unchanged, to
#   ~/.claude/island/<session_id>.json
# where Claude Island reads it, then prints a short status line (model + context %).
# It never fails: on any error it still prints something and exits 0.
#
# settings.json:
#   "statusLine": { "type": "command", "command": "sh /path/to/island-statusline.sh" }

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python

# Hand stdin to Python, which saves the file atomically and prints the status line.
"$PY" -c '
import json, os, re, sys, tempfile
raw = sys.stdin.buffer.read()
try:
    d = json.loads(raw.decode("utf-8"))
    if not isinstance(d, dict):
        d = {}
except Exception:
    d = {}
try:
    sid = str(d.get("session_id") or "")
    if re.fullmatch(r"[A-Za-z0-9._-]+", sid):
        folder = os.path.join(os.path.expanduser("~"), ".claude", "island")
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=sid + ".", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
            os.replace(tmp, os.path.join(folder, sid + ".json"))
        except Exception:
            try:
                os.remove(tmp)
            except Exception:
                pass
except Exception:
    pass
parts = []
try:
    model = (d.get("model") or {}).get("display_name")
    if model:
        parts.append(str(model))
    cw = d.get("context_window") or {}
    pct = cw.get("used_percentage")
    if pct is None and cw.get("context_window_size") and cw.get("current_usage"):
        u = cw["current_usage"]
        used = sum(float(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        pct = used / float(cw["context_window_size"]) * 100
    if pct is not None:
        parts.append("ctx %.0f%%" % float(pct))
except Exception:
    pass
print(" | ".join(parts) or "Claude Code")
' 2>/dev/null || echo "Claude Code"
exit 0
