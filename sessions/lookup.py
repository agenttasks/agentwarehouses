"""Deterministic session lookup table — append-only, used as filename basis.

The lookup table maps session IDs to metadata. IDs are deterministic:
derived from (topic, date) so the same research topic on the same day
always resolves to the same session directory.

File: sessions/lookup.yaml
Format:
  - id: "001"
    topic: "transformer-circuits-pub"
    created: "2026-04-15T00:00:00+00:00"
    surface: "cli"
    device: "linux-x86_64"
    user_agent: "ClaudeBot/1.0"
"""
from __future__ import annotations

import hashlib
import os
import platform
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

SESSIONS_DIR = Path(__file__).parent
LOOKUP_FILE = SESSIONS_DIR / "lookup.yaml"


class SessionEntry(BaseModel):
    """Single row in the session lookup table."""

    id: str = Field(description="Zero-padded 3-digit session ID")
    topic: str = Field(description="Research topic slug")
    created: str = Field(description="ISO 8601 UTC timestamp")
    surface: str = Field(description="Execution surface: cli, web, ide, sdk")
    device: str = Field(description="Platform string: os-arch")
    user_agent: str = Field(default="ClaudeBot/1.0", description="Bot role UA")
    status: str = Field(default="active", description="active | archived")


class LookupTable:
    """Append-only session lookup table backed by YAML."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or LOOKUP_FILE
        self._entries: list[SessionEntry] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            raw = yaml.safe_load(self.path.read_text()) or []
            self._entries = [SessionEntry(**e) for e in raw]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = [e.model_dump() for e in self._entries]
        self.path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

    @property
    def entries(self) -> list[SessionEntry]:
        return list(self._entries)

    def next_id(self) -> str:
        """Return next zero-padded ID (001, 002, ...)."""
        return f"{len(self._entries) + 1:03d}"

    def find_by_topic_date(self, topic: str, date: str) -> SessionEntry | None:
        """Deterministic lookup: same topic + date = same session."""
        for e in self._entries:
            if e.topic == topic and e.created.startswith(date):
                return e
        return None

    def append(self, topic: str, surface: str | None = None) -> SessionEntry:
        """Create a new session entry or return existing for today's topic.

        Deterministic: calling twice with same topic on same day returns
        the same entry (no duplicates).
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        existing = self.find_by_topic_date(topic, today)
        if existing:
            return existing

        entry = SessionEntry(
            id=self.next_id(),
            topic=topic,
            created=datetime.now(timezone.utc).isoformat(),
            surface=surface or _detect_surface(),
            device=_detect_device(),
        )
        self._entries.append(entry)
        self._save()
        return entry

    def get(self, session_id: str) -> SessionEntry | None:
        for e in self._entries:
            if e.id == session_id:
                return e
        return None


def _detect_surface() -> str:
    """Auto-detect execution surface from environment."""
    # Claude Code web
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT") == "web":
        return "web"
    # IDE extensions
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT") in ("vscode", "jetbrains"):
        return "ide"
    # SDK usage
    if os.environ.get("CLAUDE_CODE_SDK"):
        return "sdk"
    return "cli"


def _detect_device() -> str:
    """Auto-detect device string: os-arch."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    return f"{system}-{machine}"


def topic_to_slug(topic: str) -> str:
    """Normalize topic string to filesystem-safe slug."""
    slug = topic.lower().strip()
    slug = slug.replace(" ", "-").replace("/", "-").replace(".", "-")
    # Remove consecutive hyphens
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def deterministic_hash(topic: str, date: str) -> str:
    """SHA256-based deterministic ID for a topic+date pair."""
    return hashlib.sha256(f"{topic}:{date}".encode()).hexdigest()[:12]
