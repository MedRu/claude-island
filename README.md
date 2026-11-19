# Claude Island

Claude Island is a small desktop widget that shows what your Claude Code sessions are doing. It sits in the
bottom-right corner, just above the taskbar, appears while Claude is working and slides away when nothing
is. At a glance you see every running chat, which one needs you, your plan limits (5-hour session and weekly)
and how full each chat's context is. You can answer permission prompts, open, compact or close a chat
without hunting for its terminal. It is written in Python with PySide6. Windows is the main platform;
macOS and Linux run it with a few features missing (see [Platform support](#platform-support)).

Not affiliated with Anthropic. Claude and Claude Code are trademarks of Anthropic.

<!-- screenshot: docs/screenshot.png -->

## Features

- **Small bar.** The Claude Code mascot, a ring for the 5-hour limit, and an orange line running along the
  bottom while Claude works. With one active chat it shows the chat's title, then the time, the tool and what
  it is doing. With several it shows "3 chats in progress" and, in plain words, what they are doing
  ("Running commands · Thinking · Editing files"). The second line gives priority to "<title> needs you"
  (yellow), then "<title> finished" (green, for 6 seconds), even while other chats keep working.
- **Panel on hover.** The bar grows upward (same width) into a panel: a header row, two slim limit pills
  (**Session** and **Week**) and one two-line card per chat with its title, state and time, current tool (or
  last prompt) and context %.
- **Sub-agents.** A chat's running sub-agents get a small row each on its card: description, tokens, tool calls
  and time, with a spinner. A finished one keeps its row (with a check) for a minute. With one active chat,
  the small bar adds "· 2 agents".
- **Usage.** Hover a card's context % for that chat's cost, tokens in and out, lines changed and time, and its
  sub-agents; hover the Session pill for the total over all open chats.
- **Needs-you handling.** When a chat waits on a permission or a question, the panel opens by itself, plays
  a sound and shows what is being asked, with Allow / Deny / Open chat buttons or the question's own choices,
  plus a reply box.
- **Chat control.** Click a card to bring its terminal to the front, compact a chat that is filling up, close
  it, start a new chat in a recent project, or hide every Claude terminal window and keep them only in the
  island.
- **Mini mode.** When pinned and nothing has happened for 2 minutes, the bar shrinks to a small square with
  just the mascot.
- **Animated mascot** that follows the state of all chats together (working, needs you, done, idle, sleeping).
- **Sounds** for "started", "needs you" and "finished", synthesised locally.
- **Settings window** for colours, transparency, size, your own mascot GIF or picture, sounds, timing and
  startup behaviour.
- **macOS notch dock.** On a MacBook with a camera notch, the bar can dock into the notch.
- **Edge dock on Windows and Linux.** The bar docks as a small notch-style tab on the top edge, just above the
  taskbar, or upright on the left or right side, anywhere along that edge.
- **Side dock on macOS.** Besides the notch, the bar docks as the same upright tab on the left or right side.

## Requirements

- Python 3.10 or later (developed and tested on 3.13)
- PySide6 (`PySide6-Essentials` is enough)
- Claude Code
- Windows 10 or 11 for the full feature set. macOS and Linux work with reduced features.
- Recommended on macOS: `pyobjc-framework-Cocoa`, for the glass background, the exact notch size, and
  faster focusing and hiding of terminal apps.

## Install and run

```
git clone https://github.com/MedRu/claude-island.git
cd claude-island
pip install -r requirements.txt
```

**Windows.** Double-click `Start Claude Island.vbs` to start it without a console window, or run
`python island.py` to see errors in the terminal. Starting it again while it runs just brings it on screen
(a named mutex keeps a single copy).

**macOS / Linux.** Run `./start-claude-island.sh`. It uses `python3` from your PATH, or the interpreter named
in `$PYTHON`, which needs PySide6. A lock on `config/island.lock` keeps a single copy. Run
`python3 island.py` in a terminal if you need to see errors. On macOS, Settings, Startup, **Claude Island in
Applications** adds a small app to `~/Applications`, so you can start it from Spotlight or Launchpad. It runs
without a Dock icon, like a menu bar app; its menu is the icon in the menu bar.

**Start with Claude.** In Settings, under Startup, turn on "start when a Claude chat starts". This adds
asynchronous `SessionStart` and `UserPromptSubmit` hooks to `~/.claude/settings.json` that run the launcher
with `--hook`, so the widget is there as soon as a chat opens. On macOS and Linux the hook adds `--detach`, so
the widget starts in its own session and outlives the hook. A copy of your previous settings file is kept
next to it as `settings.json.bak-island-ui`. Turning the option off removes the hooks again. Hooks written by
an older version are updated when the widget starts.

**Starting and quitting.** With or without Claude chats running:

| To | Do |
|---|---|
| start it, or bring it back | run the launcher (or the Applications / Start menu entry) again |
| hide it for a while | Ctrl+Alt+I (⌃⌥I on macOS) from any app; the same again shows it |
| quit | the power button in the panel header (click twice), "Quit" in the tray / menu bar menu, or Ctrl+Q |

After you quit, prompts in chats that are already open do not bring it back; a new chat does (when the start
hooks are on), and so does starting it yourself. From a terminal, `island.py --toggle` hides or shows the
running widget and `island.py --quit` quits it.

### Command line (Windows, macOS, Linux)

`cli.py` runs, stops and checks the widget from any terminal, without loading Qt:

| Command | What it does |
|---|---|
| `claude-island start` | start it, or bring it on screen when it already runs |
| `claude-island stop` | ask it to quit, like Quit in its menu (waits up to 10 s) |
| `claude-island restart` | stop, then start |
| `claude-island kill` | end it at once, then show again any chat windows it had hidden |
| `claude-island status` | running or not, its process id and since when (exit code 3 when not running) |
| `claude-island toggle` / `show` | hide or show it / bring it on screen |
| `claude-island doctor` | start hooks and plan limits, for a bug report |

Without installing, use `python cli.py <command>` (`python3` on macOS and Linux) in this folder.
`python cli.py install` puts it in your Claude folder: a `claude-island` command in `~/.claude/bin`
(`claude-island.cmd` too on Windows), that folder on your PATH (the user PATH on Windows, your `~/.zshrc` or
`~/.bashrc` elsewhere; new terminals see it), and an **/island** slash command in `~/.claude/commands`, so
`/island status` or `/island restart` works inside Claude Code. Run install with the Python that runs the
widget (on macOS and Linux, the `.venv` one if you made it). `python cli.py uninstall` takes all of it away.
The macOS and Linux side of the command line has not been tried on real hardware yet.

The widget keeps running with or without chats, unless you set Settings, Startup, "Quit after N minutes"
(0, the default, means never). When it was started by a hook and is not pinned, it hides while nothing is
working; the tray icon stays.

## Status line setup

Chat cards work without any extra setup. The limit pills, cost and the exact context window size need one more
piece: Claude Code only exposes plan limits to the status line command, which receives a JSON document on
stdin. Without it the limit pills show "–".

**Automatic:** when Claude Code has no status line yet, the island sets this one up the first time it starts,
and repairs it later if Python or the island folder moves. A status line of your own is never replaced
automatically.

**The switch:** in Settings, under Startup, turn on **Show plan limits and cost**. This sets Claude Code's
status line to `statusline/island_statusline.py`, which saves that JSON to `~/.claude/island/<session_id>.json`
for the widget and prints the model and context %. If you already had a status line, it keeps running and its
output is what you see: the island script calls it with the same input. Turning the switch off puts your own
status line back. A copy of your settings file is kept as `settings.json.bak-island-ui`. Limits appear after
the next message in a chat, and refresh whenever a chat's status line refreshes.

**By hand**, add this to `~/.claude/settings.json` with the real paths:

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 /path/to/claude-island/statusline/island_statusline.py"
  }
}
```

To keep your own status line, append `--then-b64 <your command, base64-encoded>`.

**Limits still missing?** Hover the "–" in a limit pill: the tooltip says what is missing. Or run
`python3 island.py --doctor` (on Windows `python island.py --doctor`), which prints the Claude Code folder, the
start hooks, the status line command, the newest status file and whether it holds limits. Claude Code only
sends plan limits when you are logged in with a Claude Pro or Max subscription (not an API key), after the
first reply in a session. `CLAUDE_CONFIG_DIR` is honoured when Claude Code uses another folder. The older shell scripts
`island-statusline.ps1` (Windows) and `island-statusline.sh` still work and are recognised by the switch.

## Using it

### The bar and the panel

Hover the bar to open the panel. It grows upward only and stays open 1.2 seconds after the mouse leaves
(Settings, Timing). The header row holds the mascot and the buttons: Settings, New chat, Hide all (eye) and
Pin.

The two limit pills show a ring and a percentage that change colour as you approach the limit: green, yellow
from 50 %, then orange, red from 90 %. A thin grey bar along the bottom of each pill shows how much of its
window (5 hours or 7 days) has gone by; it never changes colour.

Each card has a stripe, dot and label in its state colour, and the Claude star in that colour (it spins while
the chat works). The thresholds are at the top of `island.py`.

| Colour | State | Rule |
|---|---|---|
| orange, spinning star | Working | Claude is busy |
| yellow | Needs you | waiting on a permission or a question |
| green | Done | idle for less than 15 minutes |
| blue | Idle | idle from 15 minutes to 2 hours |
| grey, faded | Forgotten | idle for more than 2 hours |

Hovering a card shows its exact context %, the close button and, from 40 %, the Compact button. Resting the
mouse on the context % shows the chat's usage, for example "Session: $1.24 · 412k in / 38k out · +120 −14 lines
· 42m", and how many sub-agents ran and their tokens (cost and tokens need the status line script).

Sub-agents appear under their chat's two lines, at most three rows ("+N more" beyond): a turning ring while
running, a check once finished. Finished rows stay for a minute and then leave, so a card never grows or
shrinks because the mouse is over it; the tooltip still counts them. Hover a row for its type, model, tokens,
tool calls and duration. A sub-agent that never finished and has been silent for 10 minutes counts as stopped.
 Context %
blends from green to yellow at 40 % (the point where compacting is worthwhile), orange at 60 % and red at
80 %.

The mascot in the small bar and the header follows the state of all chats together:

| State | Animation |
|---|---|
| working | types with alternating arms, eyes down, bits of code float up |
| needs you | hops and waves both arms, blinking yellow "!" |
| done | happy hop, arms up, smiling eyes, sparkles |
| idle | breathes, blinks, glances left and right |
| sleeping (every chat forgotten) | eyes shut, slow breathing, z z z, dimmer |

### When a Claude needs you

The panel opens by itself, with a sound, and that chat's card grows to show:

- what it asks, for example "Wants to use Write: notes.txt", or the question text;
- **Allow / Deny / Open chat** for a permission, or the question's own choices;
- a **reply box** (on the first waiting chat). On a permission it means "no, do this instead" (Esc followed
  by your text). On a question it is your own answer ("Type something" followed by your text). Enter or the
  arrow button sends it.

The card stays open until you answer, or until you hover it and move away. Questions with several parts or
multiple selection only get **Open chat**. The keys typed into the terminal are `1` for Yes, Esc for No and
the option number to pick a choice (tested on Claude Code 2.1.327).

### Card and header actions

- **Click a card** to bring that chat's terminal window to the front. An inactive Windows Terminal tab is
  selected through UI Automation (`platforms/windows/tab_focus.ps1`).
- **Compact** (idle chats from 40 % context): click once to get "Compact?", again to bring the terminal to
  the front and type `/compact` and Enter. It is only offered on idle chats, because typing into a busy chat
  or a permission prompt would land in the wrong place. If you had half-typed text in that chat's prompt,
  `/compact` is appended to it.
- **✕** on a card: click once to get "Close?", again within 4 seconds to close that chat's terminal window.
  Claude exits cleanly; resume later with `claude --resume`.
- **New chat**: pick a recent project folder (running sessions first, then trusted projects) or "Other
  folder…". It opens a new Claude Code in its own Windows Terminal window. Claude session variables are
  removed from its environment, so it is a normal session and not a child of the one that started the widget.
- **Hide all chats** (eye): hides every Claude terminal window, off screen and off the taskbar, so they live
  only in the island. A slashed orange eye means chats are hidden; click it to show them all again. Clicking a
  card brings that one back. Answering or compacting a hidden chat shows it just long enough to type, then
  hides it again.
- **Pin** (top-right of the bar and the panel, or the tray menu): keeps the widget on screen even when no
  Claude is working. It does not keep the panel open. Hovering the pin on the small bar does not open the
  panel, so the pin can be clicked. Upright means pinned, tilted means not.
- **Drag** the widget to move it. Right-click it, or use the tray icon, for the menu: Settings…, Pin, Sounds,
  Move back to bottom-right, Hide / Show all chats, New chat…, Quit.

### Mini mode

When the widget is pinned and nothing has happened for 2 minutes (no chat working, waiting or just finished),
the bar shrinks to a small square with only the mascot, idle or sleeping. Hover it for the full panel, idle
and forgotten chats included. It grows back into the bar as soon as a Claude starts working. The delay is in
Settings, Timing.

### Keyboard shortcuts

Click the island first: hovering never takes keyboard focus away from your terminal.

| Key | Action |
|---|---|
| ↑ / ↓ or Tab | pick a chat (the panel stays open) |
| Enter | open the selected chat |
| Del twice | close it (like ✕) |
| Esc | cancel a pending close, else close Settings, else close the panel |
| Ctrl+, | open or close Settings |
| Ctrl+N | new chat |
| Ctrl+P | pin |
| Ctrl+H | hide or show all chats |
| Ctrl+R | refresh |
| Ctrl+W | hide the island (bring it back with the shortcut below or the tray menu) |
| Ctrl+Q | quit |
| F1 or ? | show this list |

On macOS, Cmd works in place of Ctrl. In Settings, Esc, Ctrl+W or Ctrl+, close it.

**From any app**, **Ctrl+Alt+I** (Windows) or **⌃⌥I** (macOS) hides the island, and pressing it again brings
it back. It can be turned off in Settings, Startup. While hidden, sounds still play and the tray icon stays; its
menu has "Show Claude Island" and "Quit". On Linux, bind a desktop shortcut to
`python3 island.py --toggle`. From a terminal on any OS, `island.py --toggle` hides or shows the running
island and `island.py --quit` quits it.

### Settings

Open Settings from the gear in the panel header, by clicking the tray icon, or from the right-click menu. It
is a flyout drawn like the island that docks beside it without covering it (left, else right, above or
below). Drag it by its header; Esc or ✕ closes it. Changes apply at once and the panel stays open as a live
preview. Settings are saved to `config/island_config.json` shortly after the last change. **Reset to
defaults** keeps the position and the pin.

Colours are picked from swatches (the last dot opens the full colour picker). The mouse wheel only changes a
slider or number you clicked first, so scrolling the page never changes a value by accident.

- **Look:** background, accent and the five state colours; transparency for the whole widget, the background
  only, and the cards; width, small bar height, corner radius; show sub-agents on cards.
- **Mascot & icons:** your own GIF (animated) or picture for all states, or one per state; mascot size; the
  icon on each card (Claude star, dot, mascot or none).
- **Sounds:** on/off, volume, each cue on/off, and your own `.wav` per cue with a test button.
- **Timing:** hover delay, linger, animation speed, reduce motion, when a chat counts as Done or Forgotten,
  and when the pinned bar shrinks to the mascot.
- **Startup:** start when a Claude chat starts (hooks), show plan limits and cost (status line), Start menu
  entry, show when started by hand, pin, the hide/show shortcut, open when Claude needs you, quit after N
  minutes with no chat.

### Sounds

A soft low tock when a Claude starts working, two rising notes when one needs you, a short rising chime when
one finishes. When several happen at once only the most important plays (needs you, then finished, then
started). Mute them from the right-click menu. The sounds are synthesised by `sounds.py` into
`config/sounds/` and rebuilt automatically when the sound design changes (`VERSION` in that file).
`python sounds.py` rebuilds and plays them.

### Top dock (macOS notch, any screen)

Drag the bar to the top centre of the screen and it docks there, in the style of Alcove and the iPhone's
Dynamic Island: a black pill hanging from the top edge, its top corners flaring into the edge like the camera
notch, with round bottom corners that grow softer as it opens. On a MacBook with a notch it wraps the notch;
on other Mac screens it makes a notch-sized pill of its own at the top centre (Windows and Linux have their own
edge dock, below). Docked, it hangs from the top edge in the notch's black. While nothing happens it is the notch alone;
while Claude works, the mascot peeks out on a small wing at the left, with a dot on the right when a chat needs
you (amber) or just finished (green). Hover opens the panel downward, in front of every app. Drag it away to
undock. The choice is remembered across restarts.

With `pip install pyobjc-framework-Cocoa`, the exact notch size is read from AppKit and the window is raised
above the menu bar. Without it, the notch is estimated (200 pt wide, centred, on screens with the taller notch
menu bar). This has so far only been tested on Windows with a simulated notch, not on a real Mac.

### Edge dock (Windows and Linux)

Settings > Startup > Staying > **Dock**: Off, Top, Taskbar, Left or Right. Docked, the island is a small black
tab flush with that edge, its corners flaring into it like a notch: hanging from the top edge, standing on the
taskbar (or panel), or upright on a side. **Dock position** puts it anywhere along the edge (0 % = left or top
end, 100 % = right or bottom end) and **Dock width** sets its length in px (default 72). You can also drag the
bar onto any edge and along it; it sticks until pulled about 140 px away.

The tab is never empty: idle, the mascot sits in it; while a chat works the tab grows and the mascot moves to one
end, with Claude's turning spark at the other (an amber dot when a chat needs you, green when one finished).
Hover opens the panel toward the screen, with motion after the macOS Dynamic Island: the width leads with a
small bounce, the height follows, and closing pulls the height back first. Near a screen corner the open panel
slides over to stay on screen while the tab stays put. On Linux this needs X11; on Wayland the island runs
through XWayland when it is there, because Wayland does not let an app place its own windows. Linux has not
been tested on real hardware yet.

On macOS the top belongs to the notch dock, unchanged, and there is no taskbar dock; the left and right sides
take the same upright tab (Settings > Startup > Staying > **Side dock**, **Side position**, **Side tab length**,
or drag the bar to a side). Pull it away from the side to float again, or drag it to the notch as before.
This has only been tried with a simulated macOS on Windows so far, not on a real Mac.

### Transitions

The window is resized once per transition, and the transparent extra space lets clicks through, so only the
painting animates. Motion uses a spring (response about 0.5 s, damping 0.82). Settings, Timing has an
animation speed slider and a reduce-motion switch.

## How it works

Everything is read from local files that Claude Code already writes. Nothing is sent over the network, and
the widget never modifies Claude Code's files. The only things it writes outside its own `config/` folder are
the optional start hooks in `~/.claude/settings.json` (when you turn them on) and keystrokes typed into a
chat's terminal when you ask for it (Allow, Deny, an answer, Compact).

| File | Gives |
|---|---|
| `~/.claude/sessions/<pid>.json` | running sessions, busy or idle status, working folder, time in status |
| `~/.claude/projects/*/<session>.jsonl` | AI title, last prompt, current tool, context tokens |
| `~/.claude/island/<session>.json` | plan limits, context window size, cost, tokens and lines changed, written by the status line script |
| `~/.claude/projects/*/<session>/subagents/agent-<id>.meta.json` | a sub-agent's description, type, model and whether it finished |
| `~/.claude/projects/*/<session>/subagents/agent-<id>.jsonl` | its transcript: tokens, tool calls, start and end time (read in pieces, newest agents only) |

Finding a chat's terminal window relies on Claude Code putting the session title in the terminal title. A
session whose title was renamed by hand may not be found; in that case ✕ ends the claude process directly
instead of closing its window.

## Safety

Typing into a terminal is the only risky thing the widget does, so every action that types or closes runs off
the UI thread and only if, right before acting:

- the session file still shows the same state as the card (otherwise the prompt was answered in the terminal
  in the meantime);
- exactly one terminal window has that exact title, starting with Claude's status glyph;
- that window is still in front before each batch of keys.

In addition:

- Allow and Deny only appear when exactly one tool call is open, so the card shows precisely what gets
  approved.
- The reply box stays locked to the request you started typing for.
- A click must be released on the same button it pressed, and cards never reorder under the mouse.
- ✕ closes a window only if it has a single tab. Otherwise, or when the tab count cannot be read, it ends the
  claude process, and only if the process start time still matches the session file (so a reused pid is
  never killed).
- Windows with several tabs are never hidden.
- Hidden chats are given back when the widget quits, after a crash, and when their chat ends. Their list is
  kept in `config/hidden_windows.txt` and re-checked by title after a restart. A hidden Claude terminal that
  no run remembers (for example after the list was lost) is taken back at start-up, so its card still opens
  it and "Show all" brings it back.

## Platform support

Everything that touches the operating system lives in `platforms/<os>/`; the rest of the widget is plain Qt.
`ISLAND_PLATFORM=windows`, `macos` or `linux` overrides the automatic choice.

| Feature | Windows | macOS | Linux |
|---|---|---|---|
| Bar, panel, cards, limits, context %, mascot, settings | yes | yes | yes |
| Sounds | yes | yes (`afplay`) | yes (`paplay`, then `aplay`) |
| New chat | Windows Terminal | Terminal.app | `x-terminal-emulator` or a common terminal |
| Start with Claude (hooks) | yes | yes | yes |
| Menu entry | Start menu | `~/Applications/Claude Island.app` | applications menu (`~/.local/share/applications/claude-island.desktop`) |
| Notch dock | no | yes (untested on real hardware) | no |
| Edge dock (top, taskbar, sides) | yes | sides only, the top is the notch dock (untested on real hardware) | yes (X11 / XWayland, untested on real hardware) |
| Glass background | no | yes (pyobjc) | no |
| Click a card to focus its terminal | yes | the app, and the tab in Terminal and iTerm2 | no |
| Allow / Deny / answers / reply box / Compact | yes | no | no |
| Hide all chats | yes | hides the terminal apps | no |
| Shortcut from any app to hide the island | Ctrl+Alt+I | ⌃⌥I | `island.py --toggle` |
| ✕ on a card | closes the window | ends the process (SIGTERM) | ends the process (SIGTERM) |
| Log file `config/island.log` | yes | no | no |

On macOS a chat is found through its process: the parents of its `claude` process lead to the app it runs in
(Terminal, iTerm2, VS Code, Ghostty...). That whole app is focused or hidden, with any other windows it has.
macOS asks once for permission to control Terminal, iTerm2 or System Events. Typing into a chat (answers,
Compact) is not supported there yet. On Linux, the actions that need a window do nothing. On both, a reused pid
cannot be told apart from the chat's own process. Contributions are welcome.

## Files

| File | Role |
|---|---|
| `island.py` | the widget: state, layout, mouse, painting of the bar, panel and cards |
| `cli.py` | the command line: start, stop, restart, kill, status, toggle, doctor, install into `~/.claude` |
| `drawing.py` | colours, fonts, the spring behind every animation, cached frame and shadow, icons and the pixel mascot |
| `settings.py` | defaults, load and save, the start hooks in `~/.claude/settings.json` |
| `settings_ui.py` | the settings window |
| `feed.py` | reads the local Claude Code files (read-only) |
| `sounds.py` | synthesises the sound cues and picks which one plays |
| `Start Claude Island.vbs`, `start-claude-island.sh` | launchers for Windows and for macOS / Linux (`--hook` when called from a hook) |
| `statusline/` | status line scripts that save the status JSON for the widget |
| `platforms/__init__.py` | `get_platform()`: picks the OS layer |
| `platforms/base.py` | the interface every OS layer provides, documented as Protocols |
| `platforms/common.py`, `platforms/posix.py` | shared helpers, and the fallbacks macOS and Linux share |
| `platforms/<os>/winctl.py` | finds, focuses, hides, closes and types into a session's terminal window |
| `platforms/<os>/proc.py`, `sound.py`, `instance.py` | is a process alive, play a `.wav`, single instance |
| `platforms/<os>/autostart.py`, `look.py` | hook command and menu shortcut; UI fonts and window quirks |
| `platforms/windows/tab_focus.ps1` | UI Automation fallback that selects an inactive Windows Terminal tab |
| `platforms/windows/tab_count.ps1` | UI Automation: number of tabs per Windows Terminal window |
| `config/` | settings, sounds, log and lock files written at run time (not in Git) |

## License

MIT, see [LICENSE](LICENSE).

Author: Mohamed HAMANA ([github.com/MedRu](https://github.com/MedRu))

Contributors:
- magrihalah ([github.com/magrihalah](https://github.com/magrihalah)): macOS - tested on a real Mac, Liquid
  Glass, the companion pill beside the notch, typing answers into Terminal and iTerm2, smoother drag, tooltips
  and notch motion.
