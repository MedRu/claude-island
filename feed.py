# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Reads the widget's data from local Claude Code files, never writing to them.

    ~/.claude/sessions/<pid>.json         each running Claude: busy / idle / waiting, folder, since when
    ~/.claude/projects/*/<session>.jsonl  transcript: title, last prompt, current tool, context tokens
    ~/.claude/island/<session>.json       raw status line JSON (limits, context size, cost), saved by statusline/
    ~/.claude/projects/*/<session>/subagents/agent-<id>.meta.json and .jsonl   each sub-agent and its transcript
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path

from platforms import get_platform

pid_alive = get_platform().proc.pid_alive

CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()
SESSIONS_DIR = CLAUDE_HOME / "sessions"
PROJECTS_DIR = CLAUDE_HOME / "projects"
STATUS_DIR = CLAUDE_HOME / "island"
TOKEN_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
STATUS_KEEP_DAYS = 8
GLOB_RETRY_S = 5       # globbing every project folder is too slow to retry every poll
STATUS_ORDER = {"waiting": 0, "busy": 1, "idle": 2}
AGENT_TOKEN_KEYS = TOKEN_KEYS + ("output_tokens",)   # what Claude Code reports as a sub-agent's tokens
AGENT_STALE_S = 600    # an unfinished sub-agent silent this long has stopped (its chat was closed under it)
AGENTS_KEPT = 10       # finished sub-agents listed per chat
AGENT_READ_BUDGET = 4 * 1024 * 1024   # bytes of sub-agent transcripts read per poll, so a backlog is spread out


def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def lerp(a, b, t):
    return a + (b - a) * t


def fmt_dur(s, coarse=False):
    """75 -> '1m 15s', or '1m' when coarse. Coarse says 'now' under a minute."""
    s = int(max(0, s))
    if s < 60:
        return "now" if coarse else f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m" if coarse else f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h {m:02d}m"
    d, h = divmod(h, 24)
    return f"{d}d {h}h"


def fmt_tokens(n):
    """87276 -> '87k', 1234567 -> '1.2M'."""
    n = int(n or 0)
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n // 1000}k"
    return f"{n / 1_000_000:.1f}M"


def iso_time(text):
    """'2026-11-19T00:11:45.151Z' -> epoch seconds, or None."""
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def short_tool(name):
    """'mcp__claude_ai_Gmail__send_message' -> 'Gmail·send_message'."""
    if not name.startswith("mcp__"):
        return name
    bits = name.split("__")
    server = bits[1].replace("claude-in-", "").replace("claude_ai_", "")
    return f"{server}·{bits[-1]}"


def tool_detail(args):
    """The argument that says what a tool call is about: a file name, a command, a query..."""
    if not isinstance(args, dict):
        return ""
    for key in ("description", "file_path", "pattern", "query", "url", "skill", "prompt", "command", "path"):
        text = str(args.get(key) or "").strip()
        if not text:
            continue
        if key in ("file_path", "path"):
            text = os.path.basename(text.rstrip("/\\")) or text
        return text.splitlines()[0][:120]
    return ""


def read_json(path):
    """The JSON object in path, or None. Anything but an object counts as unreadable, so callers can .get()."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def as_dict(value):
    return value if isinstance(value, dict) else {}


class Transcript:
    """Follows one .jsonl transcript, reading only what was appended since the last update."""
    FIRST_READ_MAX = 2 * 1024 * 1024   # the title is written again and again, so the last 2 MB is enough

    def __init__(self, path):
        self.path = path
        self.offset = 0
        self.partial = b""             # an unfinished last line, completed by the next read
        self.title = self.prompt = self.ctx_tokens = self.model = self.tool = self.answer = None
        self.detail = ""
        self.open_tools = {}           # tool_use id -> (name, input) for calls without a result yet

    def update(self):
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size < self.offset:         # rewritten: start over
            self.offset, self.partial = 0, b""
        if size == self.offset:
            return
        start = self.offset or max(0, size - self.FIRST_READ_MAX)
        try:
            with open(self.path, "rb") as f:
                f.seek(start)
                data = f.read(size - start)
        except OSError:
            return
        self.offset = size
        *lines, self.partial = (self.partial + data).split(b"\n")
        for raw in lines:
            try:
                self._read(json.loads(raw))
            except (ValueError, AttributeError, TypeError):
                pass                   # empty, cut in half, or a format we do not know

    def _read(self, entry):
        kind = entry.get("type")
        if kind in ("ai-title", "custom-title"):
            self.title = entry.get("aiTitle") or entry.get("customTitle") or self.title
        elif entry.get("isSidechain") or entry.get("isMeta"):
            return
        elif kind == "user":
            self._user((entry.get("message") or {}).get("content"))
        elif kind == "assistant":
            self._assistant(entry.get("message") or {})

    def _user(self, content):
        if isinstance(content, list):
            blocks = [b for b in content if isinstance(b, dict)]
            results = [b for b in blocks if b.get("type") == "tool_result"]
            for b in results:
                self.open_tools.pop(b.get("tool_use_id"), None)
            if results:
                return
            content = " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        text = content.strip() if isinstance(content, str) else ""
        if text and not text.startswith(("<", "[Request interrupted")):
            self.prompt = " ".join(text.split())[:200]
            self.answer, self.tool, self.detail = None, "Thinking", ""
            self.open_tools.clear()

    def _assistant(self, msg):
        if msg.get("usage"):
            self.ctx_tokens = sum(msg["usage"].get(k) or 0 for k in TOKEN_KEYS)
        if msg.get("model") and not str(msg["model"]).startswith("<"):
            self.model = msg["model"]
        for b in msg.get("content") or []:
            kind = b.get("type") if isinstance(b, dict) else None
            if kind == "tool_use":
                self.tool, self.detail = short_tool(b.get("name", "tool")), tool_detail(b.get("input"))
                if b.get("id"):
                    self.open_tools[b["id"]] = (b.get("name", ""), b.get("input") or {})
            elif kind == "thinking":
                self.tool, self.detail = "Thinking", ""
            elif kind == "text" and b.get("text", "").strip():
                self.tool, self.detail = "Writing", ""
                first = next(ln.strip() for ln in b["text"].splitlines() if ln.strip())
                self.answer = first.lstrip("#*> ").strip()[:160] or None

    @property
    def pending(self):
        """(id, name, input) of the only open tool call, else None."""
        # With zero or several open calls the widget only offers "Open chat", so it never approves a call
        # it cannot show exactly.
        if len(self.open_tools) != 1:
            return None
        tool_id, (name, args) = next(iter(self.open_tools.items()))
        return tool_id, name, args


class AgentLog:
    """Follows one sub-agent: its .meta.json, and its .jsonl transcript read in pieces as it grows."""

    def __init__(self, folder, agent_id):
        self.id = agent_id
        self.log = folder / f"agent-{agent_id}.jsonl"
        self.meta_file = folder / f"agent-{agent_id}.meta.json"
        self.meta, self.meta_mtime = {}, None
        self.restart()

    def restart(self):
        self.offset, self.partial, self.seen_first = 0, b"", False
        self.tokens, self.tool_uses = None, 0
        self.started = self.ended = None

    def update_meta(self, mtime):
        if mtime != self.meta_mtime:
            self.meta_mtime = mtime
            self.meta = read_json(self.meta_file) or {}

    def update_log(self, size, budget):
        """Read at most budget new bytes of the transcript; return how many were read."""
        if size < self.offset:         # rewritten: start over
            self.restart()
        if size <= self.offset or budget <= 0:
            return 0
        try:
            with open(self.log, "rb") as f:
                f.seek(self.offset)
                data = f.read(min(size - self.offset, budget))
        except OSError:
            return 0
        self.offset += len(data)
        *lines, self.partial = (self.partial + data).split(b"\n")
        for raw in lines:
            # Only the first line (start time) and assistant lines (tokens, tool calls) need parsing.
            if not self.seen_first or b'"assistant"' in raw:
                self._read(raw)
        if lines:                      # the newest complete line says when the agent last did something
            self.ended = iso_time(self._parse(lines[-1]).get("timestamp")) or self.ended
        return len(data)

    @staticmethod
    def _parse(raw):
        try:
            return as_dict(json.loads(raw))
        except ValueError:
            return {}

    def _read(self, raw):
        entry = self._parse(raw)
        if not entry:
            return
        if not self.seen_first:
            self.seen_first = True
            self.started = iso_time(entry.get("timestamp"))
        if entry.get("type") != "assistant":
            return
        msg = as_dict(entry.get("message"))
        usage = msg.get("usage")
        if isinstance(usage, dict):    # the last call's whole prompt plus its output, as Claude Code counts it
            self.tokens = sum(usage.get(k) or 0 for k in AGENT_TOKEN_KEYS)
        content = msg.get("content")
        if isinstance(content, list):   # the final hand-off to the parent chat is not counted, as in Claude Code
            calls = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
            self.tool_uses += sum(1 for b in calls if b.get("name") != "SubagentHandback")

    def info(self, now, mtime):
        finished = bool(self.meta.get("finished"))
        return dict(
            id=self.id, description=str(self.meta.get("description") or "Sub-agent"),
            type=str(self.meta.get("agentType") or "agent"), model=str(self.meta.get("model") or ""),
            running=not finished and now - mtime < AGENT_STALE_S,
            tokens=self.tokens, tool_uses=self.tool_uses,
            started=self.started or mtime, ended=self.ended or mtime,
        )


def _mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0


class Feed:
    def __init__(self):
        self.transcripts = {}          # sid -> Transcript
        self.paths = {}                # sid -> transcript path
        self.misses = {}               # sid -> when a glob last found nothing
        self.agents = {}               # sid -> {agent id: AgentLog}
        self.budget = 0                # sub-agent transcript bytes still allowed this poll
        self.limits_key = None
        self.transcripts = {}           # status file -> its chat's transcript, for when a reading was made
        self.limits = None

    def _transcript(self, sid):
        if sid not in self.transcripts:
            if sid not in self.paths:
                if time.monotonic() - self.misses.get(sid, -1e9) < GLOB_RETRY_S:
                    return None
                hits = list(PROJECTS_DIR.glob(f"*/{sid}.jsonl"))
                if not hits:
                    self.misses[sid] = time.monotonic()
                    return None
                self.misses.pop(sid, None)
                self.paths[sid] = hits[0]
            self.transcripts[sid] = Transcript(self.paths[sid])
        tr = self.transcripts[sid]
        tr.update()
        return tr

    def poll(self):
        """(sessions sorted waiting > busy > idle, plan limits)."""
        now, sessions = time.time(), []
        self.budget = AGENT_READ_BUDGET
        for f in SESSIONS_DIR.glob("*.json"):
            info = read_json(f)
            if not (info and info.get("pid") and info.get("sessionId")):
                continue
            if pid_alive(info["pid"], info.get("procStart")):
                sessions.append(self._session(f, info, now))
        live = {s["sid"] for s in sessions}
        for cache in (self.transcripts, self.paths, self.misses, self.agents):
            for sid in [k for k in cache if k not in live]:
                del cache[sid]
        sessions.sort(key=lambda s: (STATUS_ORDER[s["status"]], -s["since"]))
        return sessions, self._limits()

    def _session(self, path, info, now):
        sid = info["sessionId"]
        tr = self._transcript(sid)
        line = read_json(STATUS_DIR / f"{sid}.json") or {}
        window = as_dict(line.get("context_window"))

        tokens = tr.ctx_tokens if tr else None
        if tokens is None and isinstance(window.get("current_usage"), dict):
            tokens = sum(window["current_usage"].get(k) or 0 for k in TOKEN_KEYS)

        size = window.get("context_window_size")
        if not size:                   # no status line yet: guess from the model name and usage
            big = (tr and tr.model and "[1m]" in tr.model) or (tokens or 0) > 200_000
            size = 1_000_000 if big else 200_000

        status = str(info.get("status") or "idle").lower()
        if status not in ("busy", "idle", "waiting"):
            status = "busy"            # an unknown state must never offer answer buttons

        cwd = info.get("cwd") or ""
        since_ms = info.get("statusUpdatedAt") or info.get("updatedAt") or info.get("startedAt") or now * 1000
        title = None
        if tr:
            title = tr.title or (tr.prompt and tr.prompt[:60])
        title = title or os.path.basename(cwd.rstrip("\\/")) or info.get("name") or sid[:8]

        return dict(
            sid=sid, pid=info["pid"], cwd=cwd, status=status, since=since_ms / 1000, title=title,
            tool=tr and tr.tool, detail=tr.detail if tr else "",
            prompt=tr and tr.prompt, answer=tr and tr.answer, pending=tr and tr.pending,
            tokens=tokens, size=size,
            wait_for=info.get("waitingFor") if status == "waiting" else None,   # "permission prompt", "input needed"
            sfile=str(path), status_at=info.get("statusUpdatedAt"),
            usage=_usage(line), agents=self._agents(sid, now),
        )

    def _agents(self, sid, now):
        """The chat's sub-agents, running first then the most recent, with at most AGENTS_KEPT finished ones."""
        path = self.paths.get(sid)
        if not path:
            return []
        folder = path.parent / sid / "subagents"
        try:
            stats = {e.name: e.stat() for e in os.scandir(folder)}   # cheap: no file is opened
        except OSError:
            return []
        found = []                     # (transcript mtime, agent id, transcript size)
        for name, st in stats.items():
            if name.startswith("agent-") and name.endswith(".jsonl"):
                found.append((st.st_mtime, name[len("agent-"):-len(".jsonl")], st.st_size))
        found.sort(reverse=True)
        # Old finished agents are never read: only the newest few, and any that may still be running.
        found = [f for i, f in enumerate(found) if i < AGENTS_KEPT or now - f[0] < AGENT_STALE_S]
        logs = self.agents.setdefault(sid, {})
        for agent_id in set(logs) - {f[1] for f in found}:
            del logs[agent_id]
        agents = []
        for mtime, agent_id, size in found:
            if agent_id not in logs:
                logs[agent_id] = AgentLog(folder, agent_id)
            log = logs[agent_id]
            meta = stats.get(f"agent-{agent_id}.meta.json")
            if meta:
                log.update_meta(meta.st_mtime)
            self.budget -= log.update_log(size, self.budget)
            agents.append(log.info(now, mtime))
        agents.sort(key=lambda a: (not a["running"], -a["ended"]))
        running = [a for a in agents if a["running"]]
        return running + [a for a in agents if not a["running"]][:AGENTS_KEPT]

    def _limits(self):
        """Plan limits from the chat that got a reply most recently, per limit; re-read only when that changes.

        Each chat's file holds the limits from that chat's last reply, and an idle chat keeps rewriting its
        file (the status line refreshes on a timer), so the newest file is often the stalest reading. A reading
        is as fresh as its chat's last reply, so the time that counts is when the chat's transcript last
        changed (the file's own time when there is no transcript). Readings are not mixed across chats by their
        reset times: two chats may run on two Claude logins with different limits, and the chat in use wins.
        """
        key = []
        for f in STATUS_DIR.glob("*.json"):
            transcript = self.transcripts.get(f)
            key.append((_mtime(f), _mtime(Path(transcript)) if transcript else 0.0, f))
        key.sort(reverse=True)
        if key != self.limits_key:
            self.limits_key = key
            readings = []
            for file_time, _, f in key:
                data = read_json(f) or {}
                transcript = data.get("transcript_path")
                if transcript:
                    self.transcripts[f] = transcript
                reply_time = _mtime(Path(transcript)) if transcript else 0.0
                readings.append((reply_time or file_time, as_dict(data.get("rate_limits"))))
            merged = {}
            for _, found in sorted(readings, key=lambda r: r[0], reverse=True):
                for name, reading in found.items():
                    if name not in merged and isinstance(reading, dict) and reading.get("used_percentage") is not None:
                        merged[name] = reading
            self.limits = merged or None
        return self.limits


def _usage(line):
    """The chat's cost, tokens, duration and lines changed, from its status line JSON (Nones when unknown)."""
    cost, window = as_dict(line.get("cost")), as_dict(line.get("context_window"))
    ms = cost.get("total_duration_ms")
    return dict(
        cost=cost.get("total_cost_usd"), duration=ms / 1000 if isinstance(ms, (int, float)) else None,
        tokens_in=window.get("total_input_tokens"), tokens_out=window.get("total_output_tokens"),
        lines_added=cost.get("total_lines_added"), lines_removed=cost.get("total_lines_removed"),
    )


def session_state(sfile):
    """(status, statusUpdatedAt), read fresh right before typing into a chat."""
    info = read_json(sfile) or {}
    return info.get("status"), info.get("statusUpdatedAt")


def same_process(pid, sfile):
    info = read_json(sfile) or {}
    return info.get("pid") == pid and pid_alive(pid, info.get("procStart"))


def clean_status_dir():
    """Delete status line files older than STATUS_KEEP_DAYS."""
    cutoff = time.time() - STATUS_KEEP_DAYS * 86400
    for f in STATUS_DIR.glob("*.json"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass
