"""CLI subcommand to attach to an existing Claude Code tmux window.

Lists all windows in the ccbot session (excluding __main__), shows which ones
are bound to a Telegram topic, and lets the user pick one to attach to.

This module must NOT import config.py (which requires TELEGRAM_BOT_TOKEN),
since it runs as a standalone CLI command. Config values are read from env vars.
"""

import json
import os
import sys

import libtmux
from simple_term_menu import TerminalMenu

from .utils import ccbot_dir

_SESSION_NAME = os.getenv("TMUX_SESSION_NAME", "ccbot")
_MAIN_WINDOW_NAME = "__main__"


def _get_bound_window_ids() -> set[str]:
    """Read state.json and return window IDs that are bound to a Telegram topic."""
    state_file = ccbot_dir() / "state.json"
    try:
        state = json.loads(state_file.read_text())
    except (OSError, json.JSONDecodeError):
        return set()

    bound: set[str] = set()
    for bindings in state.get("thread_bindings", {}).values():
        for wid in bindings.values():
            bound.add(wid)
    return bound


def _get_session_map() -> dict[str, dict[str, str]]:
    """Read session_map.json for cwd info."""
    map_file = ccbot_dir() / "session_map.json"
    try:
        return json.loads(map_file.read_text())  # type: ignore[no-any-return]
    except (OSError, json.JSONDecodeError):
        return {}


def attach_session_main() -> None:
    """CLI entry point for `ccbot attach`."""
    server = libtmux.Server()
    session = server.sessions.get(session_name=_SESSION_NAME)
    if not session:
        print(f"No tmux session '{_SESSION_NAME}' found.", file=sys.stderr)
        sys.exit(1)

    windows = [w for w in session.windows if w.window_name != _MAIN_WINDOW_NAME]
    if not windows:
        print("No windows available.")
        sys.exit(0)

    bound_ids = _get_bound_window_ids()
    session_map = _get_session_map()

    # Auto-attach if only one window
    if len(windows) == 1:
        window = windows[0]
        wid = window.window_id or ""
        print(f"Attaching to '{window.window_name}' ({wid})")
        _attach(wid)
        return

    # Build menu entries
    entries: list[str] = []
    for w in windows:
        wid = w.window_id or ""
        name = w.window_name or ""
        map_key = f"{_SESSION_NAME}:{wid}"
        cwd = session_map.get(map_key, {}).get("cwd", "")
        tag = " [T]" if wid in bound_ids else ""
        entries.append(f"{name}   ({wid})  {cwd}{tag}")

    menu = TerminalMenu(entries, title="Available windows:")
    idx = menu.show()
    if idx is None:
        sys.exit(0)

    window = windows[idx]  # type: ignore[index]
    wid = window.window_id or ""
    _attach(wid)


def _attach(window_id: str) -> None:
    """Attach or switch to the given window."""
    target = f"{_SESSION_NAME}:{window_id}"
    if os.environ.get("TMUX"):
        os.execvp("tmux", ["tmux", "switch-client", "-t", target])
    else:
        os.execvp("tmux", ["tmux", "attach-session", "-t", target])
