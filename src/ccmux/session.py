"""Claude Code session management.

Manages user subscriptions to Claude Code sessions and provides
access to active session information.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .config import config

logger = logging.getLogger(__name__)


@dataclass
class ClaudeSession:
    """Information about a Claude Code session."""

    session_id: str
    summary: str
    project_path: str
    first_prompt: str
    message_count: int
    modified: str
    file_path: str

    @property
    def short_summary(self) -> str:
        """Get a shortened summary for display."""
        if len(self.summary) > 30:
            return self.summary[:27] + "..."
        return self.summary

    @property
    def project_name(self) -> str:
        """Get the project directory name."""
        return Path(self.project_path).name


@dataclass
class SessionManager:
    """Manages user subscriptions to Claude Code sessions."""

    # user_id -> set of subscribed session_ids
    subscriptions: dict[int, set[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Load state from file on initialization."""
        self._load_state()

    def _save_state(self) -> None:
        """Save subscription state to file."""
        config.state_file.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "subscriptions": {
                str(k): list(v) for k, v in self.subscriptions.items()
            },
        }
        config.state_file.write_text(json.dumps(state, indent=2))

    def _load_state(self) -> None:
        """Load subscription state from file."""
        if config.state_file.exists():
            try:
                state = json.loads(config.state_file.read_text())
                self.subscriptions = {
                    int(k): set(v)
                    for k, v in state.get("subscriptions", {}).items()
                }
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Failed to load state: {e}")
                self.subscriptions = {}

    def list_active_sessions(self) -> list[ClaudeSession]:
        """List all active Claude Code sessions.

        Scans all projects in ~/.claude/projects/ and returns
        session information sorted by modification time (newest first).
        """
        sessions = []

        if not config.claude_projects_path.exists():
            return sessions

        for project_dir in config.claude_projects_path.iterdir():
            if not project_dir.is_dir():
                continue

            index_file = project_dir / "sessions-index.json"
            if not index_file.exists():
                continue

            try:
                index_data = json.loads(index_file.read_text())
                entries = index_data.get("entries", [])

                for entry in entries:
                    session = ClaudeSession(
                        session_id=entry.get("sessionId", ""),
                        summary=entry.get("summary", "Untitled"),
                        project_path=entry.get("projectPath", ""),
                        first_prompt=entry.get("firstPrompt", ""),
                        message_count=entry.get("messageCount", 0),
                        modified=entry.get("modified", ""),
                        file_path=entry.get("fullPath", ""),
                    )
                    if session.session_id:
                        sessions.append(session)

            except (json.JSONDecodeError, OSError) as e:
                logger.debug(f"Error reading index {index_file}: {e}")

        # Sort by modification time, newest first
        sessions.sort(key=lambda s: s.modified, reverse=True)
        return sessions

    def get_session(self, session_id: str) -> ClaudeSession | None:
        """Get a specific session by ID."""
        for session in self.list_active_sessions():
            if session.session_id == session_id:
                return session
        return None

    def subscribe(self, user_id: int, session_id: str) -> bool:
        """Subscribe a user to a session.

        Returns True if newly subscribed, False if already subscribed.
        """
        if user_id not in self.subscriptions:
            self.subscriptions[user_id] = set()

        if session_id in self.subscriptions[user_id]:
            return False

        self.subscriptions[user_id].add(session_id)
        self._save_state()
        return True

    def unsubscribe(self, user_id: int, session_id: str) -> bool:
        """Unsubscribe a user from a session.

        Returns True if unsubscribed, False if wasn't subscribed.
        """
        if user_id not in self.subscriptions:
            return False

        if session_id not in self.subscriptions[user_id]:
            return False

        self.subscriptions[user_id].remove(session_id)
        self._save_state()
        return True

    def is_subscribed(self, user_id: int, session_id: str) -> bool:
        """Check if a user is subscribed to a session."""
        return session_id in self.subscriptions.get(user_id, set())

    def get_subscribed_sessions(self, user_id: int) -> list[ClaudeSession]:
        """Get all sessions a user is subscribed to."""
        subscribed_ids = self.subscriptions.get(user_id, set())
        all_sessions = self.list_active_sessions()
        return [s for s in all_sessions if s.session_id in subscribed_ids]

    def get_subscribers(self, session_id: str) -> list[int]:
        """Get all user IDs subscribed to a session."""
        return [
            user_id
            for user_id, session_ids in self.subscriptions.items()
            if session_id in session_ids
        ]

    def cleanup_stale_subscriptions(self) -> int:
        """Remove subscriptions to sessions that no longer exist.

        Returns the number of stale subscriptions removed.
        """
        active_ids = {s.session_id for s in self.list_active_sessions()}
        removed = 0

        for user_id in list(self.subscriptions.keys()):
            stale = self.subscriptions[user_id] - active_ids
            if stale:
                self.subscriptions[user_id] -= stale
                removed += len(stale)

        if removed > 0:
            self._save_state()
            logger.info(f"Cleaned up {removed} stale subscriptions")

        return removed


session_manager = SessionManager()
