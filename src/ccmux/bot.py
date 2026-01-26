"""Telegram bot handlers for Claude Code session monitoring."""

import logging

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from .config import config
from .session import ClaudeSession, session_manager
from .session_monitor import NewMessage, SessionMonitor
from .telegram_sender import split_message

logger = logging.getLogger(__name__)

# Session monitor instance
session_monitor: SessionMonitor | None = None

# Callback data prefixes
CB_SUBSCRIBE = "sub:"
CB_UNSUBSCRIBE = "unsub:"
CB_REFRESH = "refresh"
CB_PAGE = "page:"

# Pagination
SESSIONS_PER_PAGE = 5


def is_user_allowed(user_id: int | None) -> bool:
    """Check if user is allowed."""
    return user_id is not None and config.is_user_allowed(user_id)


def build_session_list_keyboard(
    user_id: int, page: int = 0
) -> InlineKeyboardMarkup:
    """Build inline keyboard showing Claude sessions.

    Shows sessions with subscribe/unsubscribe buttons.
    Subscribed sessions are marked with a checkmark.
    """
    sessions = session_manager.list_active_sessions()
    total_pages = (len(sessions) + SESSIONS_PER_PAGE - 1) // SESSIONS_PER_PAGE

    # Get sessions for current page
    start = page * SESSIONS_PER_PAGE
    end = start + SESSIONS_PER_PAGE
    page_sessions = sessions[start:end]

    keyboard = []

    for session in page_sessions:
        is_subscribed = session_manager.is_subscribed(user_id, session.session_id)
        icon = "✅" if is_subscribed else "⬜"
        callback = CB_UNSUBSCRIBE if is_subscribed else CB_SUBSCRIBE

        # Show: icon + project name + short summary
        label = f"{icon} [{session.project_name}] {session.short_summary}"
        if len(label) > 50:
            label = label[:47] + "..."

        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=f"{callback}{session.session_id}"
            )
        ])

    # Navigation row
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"{CB_PAGE}{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"{CB_PAGE}{page + 1}"))
    if nav_row:
        keyboard.append(nav_row)

    # Refresh button
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data=CB_REFRESH)])

    return InlineKeyboardMarkup(keyboard)


def format_session_details(session: ClaudeSession, is_subscribed: bool) -> str:
    """Format session details for display."""
    status = "Subscribed ✅" if is_subscribed else "Not subscribed"
    return (
        f"📁 *{session.project_name}*\n"
        f"📝 {session.summary}\n"
        f"💬 {session.message_count} messages\n"
        f"🔔 {status}"
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command - show session list."""
    user = update.effective_user
    if not user or not is_user_allowed(user.id):
        if update.message:
            await update.message.reply_text("You are not authorized to use this bot.")
        return

    sessions = session_manager.list_active_sessions()
    subscribed = session_manager.get_subscribed_sessions(user.id)

    text = (
        f"🤖 *Claude Code Monitor*\n\n"
        f"Found {len(sessions)} active sessions.\n"
        f"You are subscribed to {len(subscribed)} sessions.\n\n"
        f"Tap a session to subscribe/unsubscribe.\n"
        f"You'll receive notifications for subscribed sessions."
    )

    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=build_session_list_keyboard(user.id),
            parse_mode="Markdown",
        )


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /list command - show subscribed sessions."""
    user = update.effective_user
    if not user or not is_user_allowed(user.id):
        if update.message:
            await update.message.reply_text("You are not authorized to use this bot.")
        return

    subscribed = session_manager.get_subscribed_sessions(user.id)

    if not subscribed:
        text = "You are not subscribed to any sessions.\nUse /start to browse and subscribe."
    else:
        lines = ["🔔 *Subscribed Sessions*\n"]
        for session in subscribed:
            lines.append(f"• [{session.project_name}] {session.short_summary}")
        text = "\n".join(lines)

    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard callbacks."""
    query = update.callback_query
    if not query or not query.data:
        return

    user = update.effective_user
    if not user or not is_user_allowed(user.id):
        await query.answer("Not authorized")
        return

    data = query.data

    if data.startswith(CB_SUBSCRIBE):
        session_id = data[len(CB_SUBSCRIBE):]
        session = session_manager.get_session(session_id)

        if session:
            session_manager.subscribe(user.id, session_id)
            await query.answer(f"Subscribed to {session.short_summary}")
        else:
            await query.answer("Session not found")

        # Refresh the list
        await query.edit_message_reply_markup(
            reply_markup=build_session_list_keyboard(user.id)
        )

    elif data.startswith(CB_UNSUBSCRIBE):
        session_id = data[len(CB_UNSUBSCRIBE):]
        session = session_manager.get_session(session_id)

        if session:
            session_manager.unsubscribe(user.id, session_id)
            await query.answer(f"Unsubscribed from {session.short_summary}")
        else:
            await query.answer("Session not found")

        # Refresh the list
        await query.edit_message_reply_markup(
            reply_markup=build_session_list_keyboard(user.id)
        )

    elif data.startswith(CB_PAGE):
        page = int(data[len(CB_PAGE):])
        await query.answer()
        await query.edit_message_reply_markup(
            reply_markup=build_session_list_keyboard(user.id, page)
        )

    elif data == CB_REFRESH:
        sessions = session_manager.list_active_sessions()
        subscribed = session_manager.get_subscribed_sessions(user.id)
        await query.answer(f"Found {len(sessions)} sessions, {len(subscribed)} subscribed")
        await query.edit_message_reply_markup(
            reply_markup=build_session_list_keyboard(user.id)
        )


async def send_notification(bot: Bot, user_id: int, session: ClaudeSession, text: str) -> None:
    """Send a notification about Claude response to a user."""
    # Truncate very long messages
    max_length = 2000
    if len(text) > max_length:
        text = text[:max_length] + "\n\n[... truncated]"

    header = f"🤖 [{session.project_name}] {session.short_summary}"
    full_message = f"{header}\n\n{text}"

    chunks = split_message(full_message)
    for chunk in chunks:
        try:
            await bot.send_message(chat_id=user_id, text=chunk)
        except Exception as e:
            logger.error(f"Failed to send notification to {user_id}: {e}")


async def handle_new_message(msg: NewMessage, bot: Bot) -> None:
    """Handle a new assistant message from the monitor."""
    # Get subscribers for this session
    subscribers = session_manager.get_subscribers(msg.session_id)

    if not subscribers:
        logger.debug(f"No subscribers for session {msg.session_id}")
        return

    # Get session info for display
    session = session_manager.get_session(msg.session_id)
    if not session:
        logger.warning(f"Session not found: {msg.session_id}")
        return

    # Notify all subscribers
    for user_id in subscribers:
        logger.info(f"Notifying user {user_id} for session {session.short_summary}")
        await send_notification(bot, user_id, session, msg.text)


async def post_init(application: Application) -> None:
    """Initialize bot and start session monitor."""
    global session_monitor

    await application.bot.delete_my_commands()

    # Set bot commands
    from telegram import BotCommand
    await application.bot.set_my_commands([
        BotCommand("start", "Browse and manage session subscriptions"),
        BotCommand("list", "Show subscribed sessions"),
    ])

    # Create and start session monitor
    monitor = SessionMonitor()

    async def message_callback(msg: NewMessage) -> None:
        await handle_new_message(msg, application.bot)

    monitor.set_message_callback(message_callback)
    monitor.start()
    session_monitor = monitor

    logger.info("Session monitor started")


async def post_shutdown(application: Application) -> None:
    """Clean up resources on shutdown."""
    global session_monitor

    if session_monitor:
        session_monitor.stop()
        logger.info("Session monitor stopped")


def create_bot() -> Application:
    """Create and configure the Telegram bot application."""
    application = (
        Application.builder()
        .token(config.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CallbackQueryHandler(callback_handler))

    return application
