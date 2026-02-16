"""CLI subcommand to create a new Claude Code tmux window.

Creates a tmux window in the ccbot session, starts claude, and attaches.
Useful for starting a desktop session that can later be bound to a Telegram topic.

This module must NOT import config.py (which requires TELEGRAM_BOT_TOKEN),
since it runs as a standalone CLI command. Config values are read from env vars.
"""

import argparse
import os
import sys
from pathlib import Path

import libtmux

# Mirror config.py defaults without importing it
_SESSION_NAME = os.getenv("TMUX_SESSION_NAME", "ccbot")
_CLAUDE_COMMAND = os.getenv("CLAUDE_COMMAND", "claude")
_MAIN_WINDOW_NAME = "__main__"


def _get_or_create_session(server: libtmux.Server) -> libtmux.Session:
    """Get existing ccbot session or create a new one."""
    session = server.sessions.get(session_name=_SESSION_NAME)
    if session:
        return session

    session = server.new_session(
        session_name=_SESSION_NAME,
        start_directory=str(Path.home()),
    )
    if session.windows:
        session.windows[0].rename_window(_MAIN_WINDOW_NAME)
    return session


def _deduplicate_name(session: libtmux.Session, name: str) -> str:
    """Append -2, -3, etc. if a window with this name already exists."""
    existing = {w.window_name for w in session.windows}
    if name not in existing:
        return name
    base = name
    counter = 2
    while f"{base}-{counter}" in existing:
        counter += 1
    return f"{base}-{counter}"


def new_session_main() -> None:
    """CLI entry point for `ccbot new`."""
    parser = argparse.ArgumentParser(
        prog="ccbot new",
        description="Create a new Claude Code tmux window and attach to it",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Working directory for the session (default: current directory)",
    )
    parser.add_argument(
        "-n",
        "--name",
        default=None,
        help="Window name (default: directory basename)",
    )
    parser.add_argument(
        "--no-attach",
        action="store_true",
        help="Create the window without attaching to it",
    )
    args = parser.parse_args(sys.argv[2:])

    # Validate directory
    path = Path(args.directory).expanduser().resolve()
    if not path.exists():
        print(f"Error: directory does not exist: {path}", file=sys.stderr)
        sys.exit(1)
    if not path.is_dir():
        print(f"Error: not a directory: {path}", file=sys.stderr)
        sys.exit(1)

    server = libtmux.Server()
    session = _get_or_create_session(server)

    window_name = args.name if args.name else path.name
    window_name = _deduplicate_name(session, window_name)

    window = session.new_window(
        window_name=window_name,
        start_directory=str(path),
    )
    window_id = window.window_id or ""

    pane = window.active_pane
    if pane:
        pane.send_keys(_CLAUDE_COMMAND, enter=True)

    print(f"Created window '{window_name}' (id={window_id}) at {path}")

    if args.no_attach:
        return

    target = f"{_SESSION_NAME}:{window_id}"
    if os.environ.get("TMUX"):
        # Already inside tmux — switch to the new window
        os.execvp("tmux", ["tmux", "switch-client", "-t", target])
    else:
        # Outside tmux — attach to the session at the new window
        os.execvp("tmux", ["tmux", "attach-session", "-t", target])
