"""Session monitoring service for Claude Code sessions.

Polls Claude Code session files and detects new assistant messages
for notification.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Awaitable

from .config import config
from .monitor_state import MonitorState, TrackedSession
from .transcript_parser import TranscriptParser

logger = logging.getLogger(__name__)


@dataclass
class SessionInfo:
    """Information about a Claude Code session."""

    session_id: str
    file_path: Path
    file_mtime: float
    project_path: str


@dataclass
class NewMessage:
    """A new assistant message detected by the monitor."""

    session_id: str
    project_path: str
    text: str
    uuid: str | None


class SessionMonitor:
    """Monitors Claude Code sessions for new assistant messages.

    Scans the Claude projects directory, tracks session files,
    and detects new assistant messages by polling file changes.
    """

    def __init__(
        self,
        projects_path: Path | None = None,
        poll_interval: float | None = None,
        stable_wait: float | None = None,
        state_file: Path | None = None,
    ):
        """Initialize the session monitor.

        Args:
            projects_path: Path to Claude projects directory (~/.claude/projects)
            poll_interval: Seconds between polling cycles
            stable_wait: Seconds to wait for file stability before processing
            state_file: Path to state file for persistence
        """
        self.projects_path = projects_path or config.claude_projects_path
        self.poll_interval = poll_interval or config.monitor_poll_interval
        self.stable_wait = stable_wait or config.monitor_stable_wait

        self.state = MonitorState(
            state_file=state_file or config.monitor_state_file
        )
        self.state.load()

        self._running = False
        self._task: asyncio.Task | None = None
        self._message_callback: Callable[[NewMessage], Awaitable[None]] | None = None

        # Track file mtimes for stability detection
        self._last_mtimes: dict[str, float] = {}

    def set_message_callback(
        self, callback: Callable[[NewMessage], Awaitable[None]]
    ) -> None:
        """Set callback for new message notifications.

        Args:
            callback: Async function to call with new messages
        """
        self._message_callback = callback

    def scan_projects(self) -> list[SessionInfo]:
        """Scan all projects and return active session information.

        Returns:
            List of SessionInfo for all active sessions
        """
        sessions = []

        if not self.projects_path.exists():
            logger.warning(f"Projects path does not exist: {self.projects_path}")
            return sessions

        for project_dir in self.projects_path.iterdir():
            if not project_dir.is_dir():
                continue

            index_file = project_dir / "sessions-index.json"
            if not index_file.exists():
                continue

            try:
                index_data = json.loads(index_file.read_text())
                entries = index_data.get("entries", [])
                original_path = index_data.get("originalPath", "")

                for entry in entries:
                    session_id = entry.get("sessionId", "")
                    full_path = entry.get("fullPath", "")
                    file_mtime = entry.get("fileMtime", 0)
                    project_path = entry.get("projectPath", original_path)

                    if session_id and full_path:
                        file_path = Path(full_path)
                        if file_path.exists():
                            sessions.append(
                                SessionInfo(
                                    session_id=session_id,
                                    file_path=file_path,
                                    file_mtime=file_mtime,
                                    project_path=project_path,
                                )
                            )

            except (json.JSONDecodeError, OSError) as e:
                logger.debug(f"Error reading index {index_file}: {e}")

        return sessions

    def _read_new_lines(
        self, session: TrackedSession, file_path: Path
    ) -> list[dict]:
        """Read new lines from a session file.

        Args:
            session: Tracked session state
            file_path: Path to the JSONL file

        Returns:
            List of parsed JSON objects from new lines
        """
        new_entries = []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                # Skip already processed lines
                for _ in range(session.last_line_count):
                    f.readline()

                # Read new lines
                line_count = session.last_line_count
                for line in f:
                    line_count += 1
                    data = TranscriptParser.parse_line(line)
                    if data:
                        new_entries.append(data)

                # Update line count
                session.last_line_count = line_count

        except OSError as e:
            logger.error(f"Error reading session file {file_path}: {e}")

        return new_entries

    def _is_file_stable(self, session_id: str, current_mtime: float) -> bool:
        """Check if file has been stable (unchanged) for stable_wait period.

        Args:
            session_id: Session ID to check
            current_mtime: Current file modification time

        Returns:
            True if file has been stable
        """
        last_mtime = self._last_mtimes.get(session_id, 0)

        if current_mtime != last_mtime:
            # File changed, update tracked mtime
            self._last_mtimes[session_id] = current_mtime
            return False

        # File unchanged since last check
        return True

    async def check_for_updates(self) -> list[NewMessage]:
        """Check all sessions for new assistant messages.

        Returns:
            List of new messages detected
        """
        new_messages = []
        sessions = self.scan_projects()

        for session_info in sessions:
            try:
                # Get actual file mtime
                actual_mtime = session_info.file_path.stat().st_mtime

                # Get or create tracked session
                tracked = self.state.get_session(session_info.session_id)

                if tracked is None:
                    # New session, start tracking from current state
                    tracked = TrackedSession(
                        session_id=session_info.session_id,
                        file_path=str(session_info.file_path),
                        last_mtime=actual_mtime,
                        last_line_count=self._count_lines(session_info.file_path),
                        project_path=session_info.project_path,
                    )
                    self.state.update_session(tracked)
                    logger.info(f"Started tracking session: {session_info.session_id}")
                    continue

                # Check if file has been modified
                if actual_mtime <= tracked.last_mtime:
                    continue

                # Check file stability
                if not self._is_file_stable(session_info.session_id, actual_mtime):
                    logger.debug(
                        f"Session {session_info.session_id} file changed, "
                        "waiting for stability"
                    )
                    continue

                # File is stable, read new content
                new_entries = self._read_new_lines(tracked, session_info.file_path)

                # Process assistant messages
                for entry in new_entries:
                    if TranscriptParser.is_assistant_message(entry):
                        text = TranscriptParser.extract_assistant_text(entry)
                        if text:
                            msg_uuid = TranscriptParser.get_uuid(entry)

                            # Skip if already processed
                            if tracked.last_message_uuid == msg_uuid:
                                continue

                            new_messages.append(
                                NewMessage(
                                    session_id=session_info.session_id,
                                    project_path=session_info.project_path,
                                    text=text,
                                    uuid=msg_uuid,
                                )
                            )

                            tracked.last_message_uuid = msg_uuid

                # Update tracked state
                tracked.last_mtime = actual_mtime
                tracked.project_path = session_info.project_path
                self.state.update_session(tracked)

            except OSError as e:
                logger.debug(f"Error processing session {session_info.session_id}: {e}")

        # Save state if modified
        self.state.save_if_dirty()

        return new_messages

    def _count_lines(self, file_path: Path) -> int:
        """Count total lines in a file.

        Args:
            file_path: Path to file

        Returns:
            Number of lines
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return sum(1 for _ in f)
        except OSError:
            return 0

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        logger.info(
            f"Session monitor started, polling every {self.poll_interval}s"
        )

        while self._running:
            try:
                new_messages = await self.check_for_updates()

                for msg in new_messages:
                    logger.info(
                        f"New message in session {msg.session_id}: "
                        f"{msg.text[:100]}..."
                    )

                    if self._message_callback:
                        try:
                            await self._message_callback(msg)
                        except Exception as e:
                            logger.error(f"Message callback error: {e}")

            except Exception as e:
                logger.error(f"Monitor loop error: {e}")

            await asyncio.sleep(self.poll_interval)

        logger.info("Session monitor stopped")

    def start(self) -> None:
        """Start the monitoring loop."""
        if self._running:
            logger.warning("Monitor already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())

    def stop(self) -> None:
        """Stop the monitoring loop."""
        self._running = False

        if self._task:
            self._task.cancel()
            self._task = None

        # Final state save
        self.state.save()
        logger.info("Session monitor stopped and state saved")

    async def start_async(self) -> None:
        """Start monitoring (async version for use with asyncio.create_task)."""
        self.start()

    async def stop_async(self) -> None:
        """Stop monitoring (async version)."""
        self.stop()
