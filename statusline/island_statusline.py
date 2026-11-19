# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Claude Island status line, for every OS. Installed from Settings > Startup > "Show plan limits".

Claude Code runs the status line command with a JSON document on stdin (model, context window, plan limits,
cost...). This saves that JSON, unchanged, to ~/.claude/island/<session_id>.json for the island, then prints
the status line: your own previous status line command when there was one (--then-b64, base64 so no shell
quoting can break it), else the model and context %. It never fails and always exits 0.
"""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile


def save(raw, d):
    sid = str(d.get("session_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", sid):
        return
    folder = os.path.join(os.path.expanduser("~"), ".claude", "island")
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=sid + ".", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        os.replace(tmp, os.path.join(folder, sid + ".json"))
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def own_line(d):
    parts = []
    model = (d.get("model") or {}).get("display_name")
    if model:
        parts.append(str(model))
    cw = d.get("context_window") or {}
    pct = cw.get("used_percentage")
    if pct is None and cw.get("context_window_size") and cw.get("current_usage"):
        u = cw["current_usage"]
        used = sum(float(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                  "cache_read_input_tokens"))
        pct = used / float(cw["context_window_size"]) * 100
    if pct is not None:
        parts.append("ctx %.0f%%" % float(pct))
    return " | ".join(parts) or "Claude Code"


def main():
    raw = sys.stdin.buffer.read()
    try:
        d = json.loads(raw.decode("utf-8"))
        d = d if isinstance(d, dict) else {}
    except ValueError:
        d = {}
    try:
        save(raw, d)
    except Exception:
        pass
    if "--then-b64" in sys.argv[1:-1]:
        command = base64.b64decode(sys.argv[sys.argv.index("--then-b64") + 1]).decode("utf-8")
        try:
            done = subprocess.run(command, shell=True, input=raw, capture_output=True, timeout=10)
            sys.stdout.buffer.write(done.stdout)
            return
        except Exception:
            pass
    print(own_line(d))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Claude Code")
    sys.exit(0)
