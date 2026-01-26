"""Entry point for CCMux."""

import logging

from .bot import create_bot
from .config import config


def main() -> None:
    """Main entry point."""
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    logger = logging.getLogger(__name__)

    logger.info(f"Allowed users: {config.allowed_users}")
    logger.info(f"Claude projects path: {config.claude_projects_path}")

    logger.info("Starting Telegram bot...")
    application = create_bot()
    application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
