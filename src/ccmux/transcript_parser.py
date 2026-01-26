"""JSONL transcript parser for Claude Code session files.

Parses Claude Code session JSONL files and extracts message content.
Format reference: https://github.com/desis123/claude-code-viewer
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class ParsedMessage:
    """Parsed message from a transcript."""

    message_type: str  # "user", "assistant", "tool_use", "tool_result", etc.
    role: str | None  # "user" or "assistant"
    text: str  # Extracted text content
    tool_name: str | None = None  # For tool_use messages
    raw: dict | None = None  # Original data


class TranscriptParser:
    """Parser for Claude Code JSONL session files."""

    @staticmethod
    def parse_line(line: str) -> dict | None:
        """Parse a single JSONL line.

        Args:
            line: A single line from the JSONL file

        Returns:
            Parsed dict or None if line is empty/invalid
        """
        line = line.strip()
        if not line:
            return None

        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def get_message_type(data: dict) -> str | None:
        """Get the message type from parsed data.

        Returns:
            Message type: "user", "assistant", "file-history-snapshot", etc.
        """
        return data.get("type")

    @staticmethod
    def is_assistant_message(data: dict) -> bool:
        """Check if this is an assistant message."""
        return data.get("type") == "assistant"

    @staticmethod
    def is_user_message(data: dict) -> bool:
        """Check if this is a user message."""
        return data.get("type") == "user"

    @staticmethod
    def parse_structured_content(content_list: list[Any]) -> str:
        """Parse structured content array into a string representation.

        Handles text, tool_use, tool_result, and thinking blocks.

        Args:
            content_list: List of content blocks

        Returns:
            Combined string representation
        """
        if not isinstance(content_list, list):
            if isinstance(content_list, str):
                return content_list
            return ""

        parts = []
        for item in content_list:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                item_type = item.get("type", "")

                if item_type == "text":
                    text = item.get("text", "")
                    if text:
                        parts.append(text)

                elif item_type == "thinking":
                    # Skip thinking blocks by default
                    pass

                elif item_type == "tool_use":
                    tool_name = item.get("name", "unknown")
                    parts.append(f"[Tool: {tool_name}]")

                elif item_type == "tool_result":
                    # Skip tool results by default
                    pass

        return "\n".join(parts)

    @staticmethod
    def extract_text_only(content_list: list[Any]) -> str:
        """Extract only text content from structured content.

        This is used for Telegram notifications where we only want
        the actual text response, not tool calls or thinking.

        Args:
            content_list: List of content blocks

        Returns:
            Combined text content only
        """
        if not isinstance(content_list, list):
            if isinstance(content_list, str):
                return content_list
            return ""

        texts = []
        for item in content_list:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text":
                    text = item.get("text", "")
                    if text:
                        texts.append(text)

        return "\n".join(texts)

    @classmethod
    def parse_message(cls, data: dict) -> ParsedMessage | None:
        """Parse a message entry from the JSONL data.

        Args:
            data: Parsed JSON dict from a JSONL line

        Returns:
            ParsedMessage or None if not a parseable message
        """
        msg_type = cls.get_message_type(data)

        if msg_type not in ("user", "assistant"):
            return None

        message = data.get("message", {})
        role = message.get("role")
        content = message.get("content", "")

        if isinstance(content, list):
            text = cls.extract_text_only(content)
        else:
            text = str(content) if content else ""

        return ParsedMessage(
            message_type=msg_type,
            role=role,
            text=text,
            raw=data,
        )

    @classmethod
    def extract_assistant_text(cls, data: dict) -> str | None:
        """Extract text content from an assistant message.

        This is a convenience method for getting just the text
        from an assistant message, suitable for notifications.

        Args:
            data: Parsed JSON dict from a JSONL line

        Returns:
            Text content or None if not an assistant message
        """
        if not cls.is_assistant_message(data):
            return None

        message = data.get("message", {})
        content = message.get("content", [])

        return cls.extract_text_only(content)

    @staticmethod
    def get_session_id(data: dict) -> str | None:
        """Extract session ID from message data."""
        return data.get("sessionId")

    @staticmethod
    def get_cwd(data: dict) -> str | None:
        """Extract working directory (cwd) from message data."""
        return data.get("cwd")

    @staticmethod
    def get_timestamp(data: dict) -> str | None:
        """Extract timestamp from message data."""
        return data.get("timestamp")

    @staticmethod
    def get_uuid(data: dict) -> str | None:
        """Extract message UUID from message data."""
        return data.get("uuid")
