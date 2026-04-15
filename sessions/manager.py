"""Session manager — creates session directories, writes templates, manages pages.

Each session lives at sessions/session_{id}/ and contains:
  - session.yaml      — auto-populated metadata (device, surface, UA, timestamps)
  - pages/            — one YAML file per web-fetched page
  - scratchpad.md     — freeform research notes
  - blog_post.md      — styled blog post output (Jinja2 template)
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader

from sessions.lookup import SESSIONS_DIR, LookupTable, topic_to_slug

TEMPLATES_DIR = SESSIONS_DIR / "templates"


class SessionManager:
    """High-level session lifecycle manager."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or SESSIONS_DIR
        self.lookup = LookupTable(self.base_dir / "lookup.yaml")
        self._jinja = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def create_session(self, topic: str, surface: str | None = None) -> str:
        """Create a new session (or return existing for today's topic).

        Returns the session ID (e.g. "001").
        """
        entry = self.lookup.append(topic, surface)
        session_dir = self._session_dir(entry.id)
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "pages").mkdir(exist_ok=True)

        # Write session.yaml from template
        meta_path = session_dir / "session.yaml"
        if not meta_path.exists():
            meta = {
                "id": entry.id,
                "topic": entry.topic,
                "slug": topic_to_slug(entry.topic),
                "created": entry.created,
                "surface": entry.surface,
                "device": entry.device,
                "user_agent": entry.user_agent,
                "status": "active",
                "pages_fetched": 0,
                "last_updated": entry.created,
            }
            meta_path.write_text(yaml.dump(meta, default_flow_style=False, sort_keys=False))

        # Initialize scratchpad
        scratch_path = session_dir / "scratchpad.md"
        if not scratch_path.exists():
            tmpl = self._jinja.get_template("scratchpad.md.j2")
            scratch_path.write_text(tmpl.render(topic=entry.topic, date=entry.created[:10]))

        return entry.id

    def add_page(
        self,
        session_id: str,
        url: str,
        title: str = "",
        content: str = "",
        content_type: str = "article",
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Add a fetched page to the session's pages/ directory.

        Returns the path to the created page file.
        """
        session_dir = self._session_dir(session_id)
        pages_dir = session_dir / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)

        # Deterministic filename from URL
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:8]
        slug = topic_to_slug(title or url.split("/")[-1])[:40]
        filename = f"{url_hash}_{slug}.yaml"

        page_data = {
            "url": url,
            "title": title,
            "content_type": content_type,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "content_length": len(content),
            "content_hash": hashlib.sha256(content.encode()).hexdigest(),
            "metadata": metadata or {},
            "body": content,
        }

        page_path = pages_dir / filename
        page_path.write_text(yaml.dump(page_data, default_flow_style=False, sort_keys=False, allow_unicode=True))

        # Update session metadata
        self._update_session_meta(session_id, pages_fetched_delta=1)

        return page_path

    def write_scratchpad(self, session_id: str, note: str) -> None:
        """Append a timestamped note to the session scratchpad."""
        scratch_path = self._session_dir(session_id) / "scratchpad.md"
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        entry = f"\n### {timestamp}\n\n{note}\n"

        with scratch_path.open("a") as f:
            f.write(entry)

    def write_blog_post(
        self,
        session_id: str,
        title: str,
        summary: str,
        body: str,
        tags: list[str] | None = None,
        author: str = "Research Session",
    ) -> Path:
        """Render a blog post from the Jinja2 template and write to session dir."""
        entry = self.lookup.get(session_id)
        topic = entry.topic if entry else "unknown"

        tmpl = self._jinja.get_template("blog_post.md.j2")
        rendered = tmpl.render(
            title=title,
            summary=summary,
            body=body,
            tags=tags or [topic],
            author=author,
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            session_id=session_id,
            topic=topic,
        )

        post_path = self._session_dir(session_id) / "blog_post.md"
        post_path.write_text(rendered)
        return post_path

    def get_session_meta(self, session_id: str) -> dict[str, Any]:
        """Read session.yaml metadata."""
        meta_path = self._session_dir(session_id) / "session.yaml"
        if meta_path.exists():
            return yaml.safe_load(meta_path.read_text()) or {}
        return {}

    def list_pages(self, session_id: str) -> list[Path]:
        """List all page files in a session."""
        pages_dir = self._session_dir(session_id) / "pages"
        if pages_dir.exists():
            return sorted(pages_dir.glob("*.yaml"))
        return []

    def _session_dir(self, session_id: str) -> Path:
        return self.base_dir / f"session_{session_id}"

    def _update_session_meta(self, session_id: str, pages_fetched_delta: int = 0) -> None:
        meta_path = self._session_dir(session_id) / "session.yaml"
        if meta_path.exists():
            meta = yaml.safe_load(meta_path.read_text()) or {}
            meta["pages_fetched"] = meta.get("pages_fetched", 0) + pages_fetched_delta
            meta["last_updated"] = datetime.now(timezone.utc).isoformat()
            meta_path.write_text(yaml.dump(meta, default_flow_style=False, sort_keys=False))
