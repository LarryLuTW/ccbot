"""Application entry point — CLI dispatcher and bot bootstrap.

Handles five execution modes:
  1. `ccbot hook` — delegates to hook.hook_main() for Claude Code hook processing.
  2. `ccbot new` — creates a new Claude Code tmux window and attaches.
  3. `ccbot attach` — attaches to an existing Claude Code tmux window.
  4. `ccbot stop` — sends SIGTERM to a running bot instance via lockfile PID.
  5. Default — configures logging, initializes tmux session, and starts the
     Telegram bot polling loop via bot.create_bot().
"""

import fcntl
import logging
import os
import signal
import sys


def main() -> None:
    """Main entry point."""
    if len(sys.argv) > 1 and sys.argv[1] == "hook":
        from .hook import hook_main

        hook_main()
        return

    if len(sys.argv) > 1 and sys.argv[1] == "new":
        from .new_session import new_session_main

        new_session_main()
        return

    if len(sys.argv) > 1 and sys.argv[1] == "attach":
        from .attach_session import attach_session_main

        attach_session_main()
        return

    if len(sys.argv) > 1 and sys.argv[1] == "stop":
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
        return

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


if __name__ == "__main__":
    main()
