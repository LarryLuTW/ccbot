# CCMux

Telegram Bot for managing Claude Code sessions via tmux.

## Features

- Create and manage multiple Claude Code sessions
- Each session runs in its own tmux window
- Change working directory via Telegram menu
- Send text directly to Claude Code via Telegram messages
- User whitelist for access control

## Installation

```bash
# Clone and enter directory
cd ccmux

# Install dependencies with uv
uv sync
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Required environment variables:

- `TELEGRAM_BOT_TOKEN` - Your Telegram Bot token from @BotFather
- `ALLOWED_USERS` - Comma-separated list of allowed Telegram user IDs

Optional:

- `TMUX_SESSION_NAME` - Name of the tmux session (default: `ccmux`)

## Usage

Start the bot:

```bash
uv run python -m ccmux.main
# or
uv run ccmux
```

### Telegram Interface

The bot uses a reply keyboard for easy interaction:

- **Session buttons** - Click to switch sessions (🟢 = current, ⚪ = other)
- **➕ New** - Create a new session
- Click current session for options:
  - **📂 Change Dir** - Change working directory (sends `/cd` to Claude Code)
  - **🗑 Delete** - Delete the session

Once you're in a session, any text message you send will be forwarded directly to Claude Code in the corresponding tmux window.

## Viewing Sessions

To attach to the tmux session and see what Claude Code is doing:

```bash
tmux attach -t ccmux
```

Use `Ctrl+b` then a number or `n`/`p` to navigate between windows.

## How It Works

1. Each session is a tmux window (uses current working directory by default)
2. Claude Code is automatically started in each window
3. Text messages from Telegram are sent as keystrokes to the active window
4. Working directory can be changed via the session menu (sends `/cd` to Claude Code)
