# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Claude Island from the command line, on Windows, macOS and Linux.

    claude-island start      start the widget (or bring it on screen when it runs)
    claude-island stop       ask it to quit, like Quit in its menu
    claude-island restart    stop, then start
    claude-island kill       end it at once (it gives hidden chat windows back first when it can)
    claude-island status     running or not, with its process id
    claude-island toggle     hide or show it
    claude-island show       bring it on screen
    claude-island doctor     start hooks and plan limits, for a bug report
    claude-island install    put the claude-island command and an /island slash command in ~/.claude
    claude-island uninstall  take them away again

`python cli.py <command>` works without installing. Qt is never loaded here, so every command returns quickly.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from platforms import platform_name   # noqa: E402  (needs HERE on the path)

CONFIG = HERE / "config"
PID_FILE = CONFIG / "island.pid"
HIDDEN_FILE = CONFIG / "hidden_windows.txt"
ISLAND = HERE / "island.py"
CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
BIN = CLAUDE_HOME / "bin"
SLASH = CLAUDE_HOME / "commands" / "island.md"
WINDOWS = platform_name() == "windows"
RC_MARK = "# Claude Island command line (claude-island install)"
COMMANDS = ("start", "stop", "restart", "kill", "status", "toggle", "show", "doctor", "install", "uninstall")


# ----------------------------------------------------------------- is it running
def running():
    """True while a copy holds the single-instance lock (the same test island.py makes)."""
    if WINDOWS:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenMutexW(0x00100000, False, "Local\\ClaudeIslandWidget")   # SYNCHRONIZE
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    import fcntl
    lock = CONFIG / "island.lock"
    if not lock.exists():
        return False
    with open(lock, "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
    return False


def island_pids():
    """Process ids of running island.py copies of this folder: the pid file, checked, or a search."""
    pids = []
    try:
        pid = int(PID_FILE.read_text(encoding="ascii").strip())
        if _is_island(pid):
            pids.append(pid)
    except (OSError, ValueError):
        pass
    return pids or _search()


def _command_line(pid):
    if WINDOWS:
        out = _powershell(f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine")
    else:
        out = _run(["ps", "-p", str(int(pid)), "-o", "command="])
    return out or ""


def _is_island(pid):
    line = _command_line(pid).replace("\\", "/")
    return "island.py" in line and HERE.name in line


def _search():
    if WINDOWS:
        out = _powershell("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'island\\.py' } | "
                          "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }")
        rows = [line.split("\t", 1) for line in out.splitlines() if "\t" in line]
    else:
        out = _run(["ps", "-axo", "pid=,command="])
        rows = [line.strip().split(None, 1) for line in out.splitlines() if "island.py" in line]
    own = {os.getpid(), os.getppid()}
    found = []
    for row in rows:
        if len(row) == 2 and row[0].strip().isdigit():
            pid, line = int(row[0]), row[1].replace("\\", "/")
            # the widget itself, not a shell or a search that only mentions it
            if pid not in own and "island.py" in line and HERE.name in line and "cli.py" not in line \
                    and "--doctor" not in line and "python" in line.lower():
                found.append(pid)
    return found


def _run(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _powershell(script):
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])


def wait_for(state, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if running() == state:
            return True
        time.sleep(0.2)
    return running() == state


# ----------------------------------------------------------------- commands
def gui_python():
    """The interpreter for the widget: pythonw on Windows, so no console window opens."""
    exe = Path(sys.executable)
    if WINDOWS and not exe.stem.lower().startswith("pythonw"):
        windowed = exe.with_name(exe.name.lower().replace("python", "pythonw", 1))
        if windowed.exists():
            return str(windowed)
    return str(exe)


def flag(name):
    CONFIG.mkdir(exist_ok=True)
    (CONFIG / f"{name}.flag").touch()


def start():
    if running():
        flag("show")
        print("Claude Island is already running; brought it on screen.")
        return 0
    if WINDOWS:
        flags = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([gui_python(), str(ISLAND)], cwd=str(HERE), creationflags=flags, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen([sys.executable, str(ISLAND)], cwd=str(HERE), start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if wait_for(True, 15):
        pids = island_pids()
        print(f"Claude Island started (pid {pids[0]})." if pids else "Claude Island started.")
        return 0
    print("Claude Island did not start. Try `python island.py` in this folder to see the error"
          + (" (or read config/island.log)." if WINDOWS else "."), file=sys.stderr)
    return 1


def stop():
    if not running():
        print("Claude Island is not running.")
        return 0
    flag("quit")
    if wait_for(False, 10):
        print("Claude Island stopped.")
        return 0
    print("Claude Island did not quit within 10 s; `claude-island kill` ends it at once.", file=sys.stderr)
    return 1


def kill():
    pids = island_pids()
    if not pids and not running():
        print("Claude Island is not running.")
        return 0
    if not pids:
        print("Claude Island runs, but its process was not found; try `claude-island stop`.", file=sys.stderr)
        return 1
    for pid in pids:
        if WINDOWS:
            _run(["taskkill", "/PID", str(pid), "/T", "/F"])
        else:
            import signal
            try:
                os.kill(pid, signal.SIGTERM)          # ends it without its own clean-up: done below
            except OSError:
                pass
    if not wait_for(False, 5) and not WINDOWS:
        import signal
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        wait_for(False, 3)
    give_chats_back()
    PID_FILE.unlink(missing_ok=True)
    if running():
        print(f"Could not end Claude Island (pid {', '.join(map(str, pids))}).", file=sys.stderr)
        return 1
    print(f"Claude Island killed (pid {', '.join(map(str, pids))}).")
    return 0


def give_chats_back():
    """A killed widget cannot show the chat windows it hid; do it for it."""
    if not HIDDEN_FILE.exists() or not HIDDEN_FILE.read_text(encoding="utf-8", errors="ignore").strip():
        return
    try:
        from platforms import get_platform
        get_platform().winctl.show_all(HIDDEN_FILE)
        print("Hidden chat windows shown again.")
    except Exception as e:                            # never fail a kill over this
        print(f"Could not show the hidden chat windows again: {e}", file=sys.stderr)


def restart():
    if running() and stop() != 0 and kill() != 0:
        return 1
    return start()


def status():
    if not running():
        print("Claude Island: not running")
        return 3
    pids = island_pids()
    since = ""
    if PID_FILE.exists():
        since = time.strftime(", since %Y-%m-%d %H:%M", time.localtime(PID_FILE.stat().st_mtime))
    print(f"Claude Island: running (pid {', '.join(map(str, pids)) or 'unknown'}{since})")
    print(f"Folder: {HERE}")
    return 0


def toggle():
    if not running():
        return start()
    flag("toggle")
    print("Claude Island hidden or shown.")
    return 0


def show():
    return start()


def doctor():
    return subprocess.call([sys.executable, str(ISLAND), "--doctor"], cwd=str(HERE))


# ----------------------------------------------------------------- install into ~/.claude
def console_python():
    """The interpreter the commands run with: one that prints (python, not pythonw, on Windows)."""
    exe = Path(sys.executable)
    if exe.stem.lower().startswith("pythonw"):
        console = exe.with_name(exe.name.lower().replace("pythonw", "python", 1))
        if console.exists():
            return console.as_posix()
    return exe.as_posix()


def install():
    BIN.mkdir(parents=True, exist_ok=True)
    py, cli = console_python(), (HERE / "cli.py").as_posix()
    shell = BIN / "claude-island"
    shell.write_text(f'#!/bin/sh\n# Claude Island command line, written by `claude-island install`\n'
                     f'exec "{py}" "{cli}" "$@"\n', encoding="utf-8", newline="\n")
    shell.chmod(0o755)
    written = [shell]
    if WINDOWS:
        cmd = BIN / "claude-island.cmd"
        cmd.write_text(f'@echo off\r\nrem Claude Island command line, written by `claude-island install`\r\n'
                       f'"{Path(py)}" "{Path(cli)}" %*\r\n', encoding="utf-8", newline="")
        written.append(cmd)
    SLASH.parent.mkdir(parents=True, exist_ok=True)
    shim = shell.as_posix()
    shim = shim if " " not in shim else f'"{shim}"'      # quoted only when it must be, so the permission matches
    SLASH.write_text(SLASH_COMMAND.format(shim=shim), encoding="utf-8", newline="\n")
    written.append(SLASH)
    for path in written:
        print(f"wrote {path}")
    print(add_to_path())
    print("Then: claude-island status   (and /island status inside Claude Code)")
    return 0


def uninstall():
    for path in (BIN / "claude-island", BIN / "claude-island.cmd", SLASH):
        if path.exists():
            path.unlink()
            print(f"removed {path}")
    print(remove_from_path())
    return 0


SLASH_COMMAND = """---
description: Start, stop, restart, kill or check the Claude Island widget
argument-hint: start | stop | restart | kill | status | toggle | show | doctor
allowed-tools: Bash({shim}:*)
---
Run the Claude Island command line with the Bash tool:

    {shim} $ARGUMENTS

With no argument, run it with `status`. Report its output in one or two lines. If it fails, show the error
and suggest `{shim} doctor`.
"""


def add_to_path():
    folder = str(BIN)
    if WINDOWS:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            try:
                value, kind = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                value, kind = "", winreg.REG_EXPAND_SZ
            parts = [p for p in value.split(";") if p]
            if any(os.path.normcase(os.path.expandvars(p)).rstrip("\\/") == os.path.normcase(folder) for p in parts):
                return f"{folder} is already on your PATH."
            winreg.SetValueEx(key, "Path", 0, kind, ";".join(parts + [folder]))
        _broadcast_env_change()
        return f"Added {folder} to your user PATH (new terminals see it)."
    rc = _shell_rc()
    text = rc.read_text(encoding="utf-8") if rc.exists() else ""
    if RC_MARK in text:
        return f"{folder} is already on your PATH ({rc})."
    with open(rc, "a", encoding="utf-8") as f:
        f.write(f'\n{RC_MARK}\nexport PATH="$HOME/{BIN.relative_to(Path.home()).as_posix()}:$PATH"\n'
                if BIN.is_relative_to(Path.home()) else f'\n{RC_MARK}\nexport PATH="{folder}:$PATH"\n')
    return f"Added {folder} to your PATH in {rc} (new terminals see it)."


def remove_from_path():
    folder = str(BIN)
    if WINDOWS:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            try:
                value, kind = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                return "Nothing to take off your PATH."
            parts = [p for p in value.split(";") if p]
            keep = [p for p in parts if os.path.normcase(os.path.expandvars(p)).rstrip("\\/") != os.path.normcase(folder)]
            if keep == parts:
                return "Nothing to take off your PATH."
            winreg.SetValueEx(key, "Path", 0, kind, ";".join(keep))
        _broadcast_env_change()
        return f"Took {folder} off your user PATH."
    rc = _shell_rc()
    if not rc.exists() or RC_MARK not in rc.read_text(encoding="utf-8"):
        return "Nothing to take off your PATH."
    lines = rc.read_text(encoding="utf-8").splitlines(keepends=True)
    out, skip = [], 0
    for line in lines:
        if skip:
            skip -= 1
            continue
        if line.strip() == RC_MARK:
            skip = 1                                   # the export line under the mark
            if out and not out[-1].strip():
                out.pop()
            continue
        out.append(line)
    rc.write_text("".join(out), encoding="utf-8")
    return f"Took {folder} off your PATH in {rc}."


def _shell_rc():
    shell = os.path.basename(os.environ.get("SHELL", ""))
    if shell == "zsh" or (not shell and platform_name() == "macos"):
        return Path.home() / ".zshrc"
    if shell == "bash" and platform_name() == "macos":
        return Path.home() / ".bash_profile"
    return Path.home() / ".bashrc"


def _broadcast_env_change():
    """Tell Explorer and new terminals that the user environment changed (WM_SETTINGCHANGE)."""
    try:
        import ctypes
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 3000, ctypes.byref(result))
    except Exception:
        pass


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    command = argv[0].lower()
    if command not in COMMANDS:
        print(f"Unknown command {argv[0]!r}. Commands: {', '.join(COMMANDS)}", file=sys.stderr)
        return 2
    return globals()[command]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
