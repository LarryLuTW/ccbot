"""Application entry point — CLI dispatcher and bot bootstrap.

Handles execution modes:
  1. `ccbot` (no args) — print usage help and exit.
  2. `ccbot start [-d]` — start the Telegram bot (foreground or daemon).
  3. `ccbot stop` — send SIGTERM to a running bot instance via lockfile PID.
  4. `ccbot restart [-d]` — stop + start.
  5. `ccbot hook` — delegate to hook.hook_main().
  6. `ccbot new` — create a new Claude Code tmux window and attach.
  7. `ccbot attach` — attach to an existing Claude Code tmux window.
"""

import fcntl
import logging
import os
import signal
import subprocess
import sys
import time

_USAGE = """\
usage: ccbot <command> [options]

commands:
  start      Start the Telegram bot
  stop       Stop a running bot instance
  restart    Restart the bot (stop + start)
  hook       Claude Code SessionStart hook
  new        Create a new Claude Code tmux window
  attach     Attach to an existing tmux window

Run 'ccbot <command> --help' for command-specific options.\
"""


def _stop_bot(wait: bool = False) -> bool:
    """Send SIGTERM to a running bot instance.

    Returns True if a process was stopped, False if not running.
    When wait=True, polls until the process exits (up to 10s).
    """
    from .utils import ccbot_dir

    lock_path = ccbot_dir() / ".bot.lock"
    if not lock_path.exists():
        return False

    try:
        pid = int(lock_path.read_text().strip())
        os.kill(pid, signal.SIGTERM)
    except (ValueError, ProcessLookupError):
        return False

    if wait:
        for _ in range(20):  # 20 * 0.5s = 10s
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            time.sleep(0.5)

    return True


def _run_bot() -> None:
    """Configure logging, acquire singleton lock, and start the bot polling loop."""
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.WARNING,
    )

    # Import config before enabling DEBUG — avoid leaking debug logs on config errors
    try:
        from .config import config
    except ValueError as e:
        from .utils import ccbot_dir

        config_dir = ccbot_dir()
        env_path = config_dir / ".env"
        print(f"Error: {e}\n")
        print(f"Create {env_path} with the following content:\n")
        print("  TELEGRAM_BOT_TOKEN=your_bot_token_here")
        print("  ALLOWED_USERS=your_telegram_user_id")
        print()
        print("Get your bot token from @BotFather on Telegram.")
        print("Get your user ID from @userinfobot on Telegram.")
        sys.exit(1)

    logging.getLogger("ccbot").setLevel(logging.DEBUG)
    # AIORateLimiter (max_retries=5) handles retries itself; keep INFO for visibility
    logging.getLogger("telegram.ext.AIORateLimiter").setLevel(logging.INFO)
    logger = logging.getLogger(__name__)

    # Singleton lock — only one bot instance at a time.
    # lock_file must stay open for the process lifetime (flock released on close/exit).
    lock_path = config.config_dir / ".bot.lock"
    lock_file = lock_path.open("w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Another ccbot instance is already running", file=sys.stderr)
        sys.exit(1)
    lock_file.write(str(os.getpid()))
    lock_file.flush()

    from .tmux_manager import tmux_manager

    logger.info("Allowed users: %s", config.allowed_users)
    logger.info("Claude projects path: %s", config.claude_projects_path)

    # Ensure tmux session exists
    session = tmux_manager.get_or_create_session()
    logger.info("Tmux session '%s' ready", session.session_name)

    logger.info("Starting Telegram bot...")
    from .bot import create_bot

    application = create_bot()
    application.run_polling(allowed_updates=["message", "callback_query"])


def _start_daemon() -> None:
    """Stop any running instance, then re-exec ccbot start as a background daemon."""
    from .utils import ccbot_dir, find_ccbot_path

    if _stop_bot(wait=True):
        print("Stopped existing ccbot instance")

    ccbot_exe = find_ccbot_path()
    log_path = ccbot_dir() / "ccbot.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with open(log_path, "a") as log_f, open(os.devnull, "r") as devnull:
        proc = subprocess.Popen(
            [ccbot_exe, "start"],
            stdin=devnull,
            stdout=log_f,
            stderr=log_f,
            start_new_session=True,
        )

    # Wait briefly and verify the child is alive
    time.sleep(2)
    try:
        os.kill(proc.pid, 0)
    except ProcessLookupError:
        print(f"ERROR: ccbot failed to start. Check {log_path}", file=sys.stderr)
        sys.exit(1)

    print(f"ccbot started (PID {proc.pid}), log: {log_path}")


def _cmd_start() -> None:
    """Handle `ccbot start [-d]`."""
    daemon = "-d" in sys.argv[2:]
    if daemon:
        _start_daemon()
    else:
        _run_bot()


def _cmd_stop() -> None:
    """Handle `ccbot stop`."""
    from .utils import ccbot_dir

    lock_path = ccbot_dir() / ".bot.lock"
    if not lock_path.exists():
        print("No lockfile found — ccbot is not running", file=sys.stderr)
        sys.exit(1)
    try:
        pid = int(lock_path.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to ccbot (PID {pid})")
    except (ValueError, ProcessLookupError):
        print("ccbot is not running (stale lockfile)", file=sys.stderr)
        sys.exit(1)


def _cmd_restart() -> None:
    """Handle `ccbot restart [-d]`."""
    if _stop_bot(wait=True):
        print("Stopped existing ccbot instance")
    else:
        print("No running ccbot instance found")

    daemon = "-d" in sys.argv[2:]
    if daemon:
        _start_daemon()
    else:
        _run_bot()


def main() -> None:
    """Main entry point."""
    cmd = sys.argv[1] if len(sys.argv) > 1 else None

    if cmd == "hook":
        from .hook import hook_main

        hook_main()
        return

    if cmd == "new":
        from .new_session import new_session_main

        new_session_main()
        return

    if cmd == "attach":
        from .attach_session import attach_session_main

        attach_session_main()
        return

    if cmd == "start":
        _cmd_start()
        return

    if cmd == "stop":
        _cmd_stop()
        return

    if cmd == "restart":
        _cmd_restart()
        return

    if cmd in (None, "-h", "--help"):
        print(_USAGE)
        return

    print(f"ccbot: unknown command '{cmd}'", file=sys.stderr)
    print(file=sys.stderr)
    print(_USAGE, file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
