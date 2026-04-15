"""Tests for the session infrastructure — lookup table, manager, templates."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sessions.lookup import LookupTable, SessionEntry, _detect_device, topic_to_slug
from sessions.manager import SessionManager


@pytest.fixture
def tmp_sessions(tmp_path: Path) -> Path:
    """Create a temporary sessions directory with templates."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    # Copy templates from real location
    templates_dir = sessions_dir / "templates"
    templates_dir.mkdir()

    (templates_dir / "scratchpad.md.j2").write_text(
        "# Research Scratchpad: {{ topic }}\n\n**Session started:** {{ date }}\n\n---\n\n## Running Notes\n\n"
    )
    (templates_dir / "blog_post.md.j2").write_text(
        '---\ntitle: "{{ title }}"\ndate: {{ date }}\nauthor: {{ author }}\n'
        "tags: [{{ tags | join(', ') }}]\nsession: {{ session_id }}\ntopic: {{ topic }}\n"
        "status: draft\n---\n\n# {{ title }}\n\n> {{ summary }}\n\n---\n\n{{ body }}\n\n"
        "---\n\n*Research session `{{ session_id }}` — topic: {{ topic }}*\n"
    )

    return sessions_dir


# ── Lookup table ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestLookupTable:
    def test_empty_table(self, tmp_sessions: Path) -> None:
        lt = LookupTable(tmp_sessions / "lookup.yaml")
        assert lt.entries == []
        assert lt.next_id() == "001"

    def test_append_creates_entry(self, tmp_sessions: Path) -> None:
        lt = LookupTable(tmp_sessions / "lookup.yaml")
        entry = lt.append("test-topic")
        assert entry.id == "001"
        assert entry.topic == "test-topic"
        assert entry.status == "active"
        assert "ClaudeBot" in entry.user_agent

    def test_append_is_deterministic_same_day(self, tmp_sessions: Path) -> None:
        lt = LookupTable(tmp_sessions / "lookup.yaml")
        entry1 = lt.append("same-topic")
        entry2 = lt.append("same-topic")
        assert entry1.id == entry2.id  # Same topic, same day = same session

    def test_append_different_topics(self, tmp_sessions: Path) -> None:
        lt = LookupTable(tmp_sessions / "lookup.yaml")
        e1 = lt.append("topic-a")
        e2 = lt.append("topic-b")
        assert e1.id != e2.id

    def test_persists_to_yaml(self, tmp_sessions: Path) -> None:
        path = tmp_sessions / "lookup.yaml"
        lt = LookupTable(path)
        lt.append("persisted-topic")
        assert path.exists()

        # Reload from disk
        lt2 = LookupTable(path)
        assert len(lt2.entries) == 1
        assert lt2.entries[0].topic == "persisted-topic"

    def test_get_by_id(self, tmp_sessions: Path) -> None:
        lt = LookupTable(tmp_sessions / "lookup.yaml")
        entry = lt.append("findme")
        found = lt.get(entry.id)
        assert found is not None
        assert found.topic == "findme"

    def test_get_missing_returns_none(self, tmp_sessions: Path) -> None:
        lt = LookupTable(tmp_sessions / "lookup.yaml")
        assert lt.get("999") is None

    def test_next_id_increments(self, tmp_sessions: Path) -> None:
        lt = LookupTable(tmp_sessions / "lookup.yaml")
        lt.append("topic-1")
        lt.append("topic-2")
        assert lt.next_id() == "003"

    def test_surface_auto_detected(self, tmp_sessions: Path) -> None:
        lt = LookupTable(tmp_sessions / "lookup.yaml")
        entry = lt.append("auto-surface")
        assert entry.surface in ("cli", "web", "ide", "sdk")

    def test_device_auto_detected(self, tmp_sessions: Path) -> None:
        lt = LookupTable(tmp_sessions / "lookup.yaml")
        entry = lt.append("auto-device")
        assert "-" in entry.device  # e.g. "linux-x86_64"


# ── SessionEntry model ───────────────────────────────────────────────


@pytest.mark.unit
class TestSessionEntry:
    def test_defaults(self) -> None:
        entry = SessionEntry(
            id="001",
            topic="test",
            created="2026-04-15T00:00:00+00:00",
            surface="cli",
            device="linux-x86_64",
        )
        assert entry.user_agent == "ClaudeBot/1.0"
        assert entry.status == "active"

    def test_custom_fields(self) -> None:
        entry = SessionEntry(
            id="002",
            topic="custom",
            created="2026-04-15T00:00:00+00:00",
            surface="web",
            device="darwin-arm64",
            user_agent="Claude-SearchBot/1.0",
            status="archived",
        )
        assert entry.surface == "web"
        assert entry.status == "archived"


# ── topic_to_slug ────────────────────────────────────────────────────


@pytest.mark.unit
class TestTopicToSlug:
    def test_basic(self) -> None:
        assert topic_to_slug("transformer circuits pub") == "transformer-circuits-pub"

    def test_slashes(self) -> None:
        assert topic_to_slug("safety/research") == "safety-research"

    def test_dots(self) -> None:
        assert topic_to_slug("transformer-circuits.pub") == "transformer-circuits-pub"

    def test_consecutive_hyphens(self) -> None:
        assert topic_to_slug("a--b---c") == "a-b-c"

    def test_strips_edges(self) -> None:
        assert topic_to_slug("  hello  ") == "hello"


# ── detect_device ────────────────────────────────────────────────────


@pytest.mark.unit
class TestDetectDevice:
    def test_returns_os_arch(self) -> None:
        device = _detect_device()
        assert "-" in device
        parts = device.split("-")
        assert len(parts) == 2
        assert parts[0] in ("linux", "darwin", "windows")


# ── Session manager ──────────────────────────────────────────────────


@pytest.mark.integration
class TestSessionManager:
    def test_create_session(self, tmp_sessions: Path) -> None:
        mgr = SessionManager(tmp_sessions)
        sid = mgr.create_session("test-research")
        assert sid == "001"
        assert (tmp_sessions / "session_001").is_dir()
        assert (tmp_sessions / "session_001" / "session.yaml").exists()
        assert (tmp_sessions / "session_001" / "pages").is_dir()
        assert (tmp_sessions / "session_001" / "scratchpad.md").exists()

    def test_create_session_idempotent(self, tmp_sessions: Path) -> None:
        mgr = SessionManager(tmp_sessions)
        sid1 = mgr.create_session("same-topic")
        sid2 = mgr.create_session("same-topic")
        assert sid1 == sid2

    def test_session_yaml_auto_populated(self, tmp_sessions: Path) -> None:
        mgr = SessionManager(tmp_sessions)
        sid = mgr.create_session("meta-test")
        meta = mgr.get_session_meta(sid)
        assert meta["id"] == "001"
        assert meta["topic"] == "meta-test"
        assert meta["slug"] == "meta-test"
        assert meta["surface"] in ("cli", "web", "ide", "sdk")
        assert "-" in meta["device"]
        assert meta["user_agent"] == "ClaudeBot/1.0"
        assert meta["status"] == "active"
        assert meta["pages_fetched"] == 0

    def test_add_page(self, tmp_sessions: Path) -> None:
        mgr = SessionManager(tmp_sessions)
        sid = mgr.create_session("page-test")
        page_path = mgr.add_page(
            sid,
            url="https://transformer-circuits.pub/2025/attribution-graphs/index.html",
            title="Circuit Tracing",
            content="# Circuit Tracing\n\nContent here.",
            metadata={"authors": "Ameisen et al."},
        )
        assert page_path.exists()
        page_data = yaml.safe_load(page_path.read_text())
        assert page_data["url"] == "https://transformer-circuits.pub/2025/attribution-graphs/index.html"
        assert page_data["title"] == "Circuit Tracing"
        assert page_data["content_length"] == len("# Circuit Tracing\n\nContent here.")
        assert len(page_data["content_hash"]) == 64

    def test_add_page_increments_count(self, tmp_sessions: Path) -> None:
        mgr = SessionManager(tmp_sessions)
        sid = mgr.create_session("count-test")
        mgr.add_page(sid, url="https://example.com/1", content="page 1")
        mgr.add_page(sid, url="https://example.com/2", content="page 2")
        meta = mgr.get_session_meta(sid)
        assert meta["pages_fetched"] == 2

    def test_list_pages(self, tmp_sessions: Path) -> None:
        mgr = SessionManager(tmp_sessions)
        sid = mgr.create_session("list-test")
        mgr.add_page(sid, url="https://example.com/a", content="a")
        mgr.add_page(sid, url="https://example.com/b", content="b")
        pages = mgr.list_pages(sid)
        assert len(pages) == 2

    def test_write_scratchpad(self, tmp_sessions: Path) -> None:
        mgr = SessionManager(tmp_sessions)
        sid = mgr.create_session("scratch-test")
        mgr.write_scratchpad(sid, "First finding")
        mgr.write_scratchpad(sid, "Second finding")
        content = (tmp_sessions / f"session_{sid}" / "scratchpad.md").read_text()
        assert "First finding" in content
        assert "Second finding" in content
        assert content.count("###") >= 2  # Two timestamped entries

    def test_write_blog_post(self, tmp_sessions: Path) -> None:
        mgr = SessionManager(tmp_sessions)
        sid = mgr.create_session("blog-test")
        post_path = mgr.write_blog_post(
            sid,
            title="Test Post",
            summary="A test summary",
            body="## Section\n\nBody content here.",
            tags=["test", "research"],
            author="Test Author",
        )
        assert post_path.exists()
        content = post_path.read_text()
        assert "Test Post" in content
        assert "A test summary" in content
        assert "Body content here." in content
        assert "test, research" in content
        assert "Test Author" in content
        assert "session: 001" in content

    def test_scratchpad_initialized_from_template(self, tmp_sessions: Path) -> None:
        mgr = SessionManager(tmp_sessions)
        sid = mgr.create_session("template-test")
        content = (tmp_sessions / f"session_{sid}" / "scratchpad.md").read_text()
        assert "Research Scratchpad: template-test" in content
        assert "Running Notes" in content
