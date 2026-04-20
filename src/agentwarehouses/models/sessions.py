"""Session management types for Claude Code sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from agentwarehouses.models.base import BaseModel, LenientModel


class SessionInfo(BaseModel):
    """Session metadata as returned by list_sessions() / claude -r."""

    session_id: str
    summary: str
    last_modified: int
    file_size: int | None = None
    custom_title: str | None = None
    first_prompt: str | None = None
    git_branch: str | None = None
    cwd: str | None = None
    tag: str | None = None
    created_at: int | None = None


class SessionMessage(BaseModel):
    """A single message in a session transcript."""

    type: Literal["user", "assistant"]
    uuid: str
    session_id: str
    message: Any
    parent_tool_use_id: str | None = None


class SessionCLIFlags(BaseModel):
    """CLI flags for session management."""

    continue_: bool | None = Field(None, alias="continue", description="-c flag")
    resume: str | None = Field(None, description="-r <id|name>")
    session_id: str | None = Field(None, description="--session-id <uuid>")
    fork_session: bool | None = Field(None, description="--fork-session")
    teleport: bool | None = None
    remote: str | None = None
    name: str | None = Field(None, description="-n <name>")


# --- Session environment data collected at SessionStart ---


class SessionContext(BaseModel):
    """Core session identifiers and hook input fields."""

    session_id: str
    remote_session_id: str | None = None
    source: Literal["startup", "resume", "clear", "compact"] | None = None
    model: str | None = None
    cwd: str | None = None
    transcript_path: str | None = None
    permission_mode: str | None = None
    agent_id: str | None = None
    agent_type: str | None = None


class SurfaceInfo(BaseModel):
    """How the user launched Claude Code (entrypoint / surface).

    Known entrypoints: cli, desktop, web, ide_vscode, ide_jetbrains,
    remote_mobile, remote_desktop, remote_cli.
    """

    entrypoint: str = "unknown"
    is_remote: bool = False
    remote_environment_type: str | None = None


class PlatformInfo(BaseModel):
    """OS and architecture details from ``platform.uname()``."""

    system: str  # e.g. "Linux", "Darwin", "Windows"
    release: str | None = None
    version: str | None = None
    machine: str  # e.g. "x86_64", "arm64"
    processor: str | None = None
    python_version: str | None = None
    platform_string: str | None = None


class DeviceInfo(BaseModel):
    """Container, terminal, and user environment."""

    container_id: str | None = None
    hostname: str | None = None
    shell: str | None = None
    terminal: str | None = None
    user: str | None = None
    home: str | None = None
    lang: str | None = None


class RuntimeInfo(BaseModel):
    """Claude Code binary and runner metadata."""

    version: str | None = None
    exec_path: str | None = None
    environment_runner_version: str | None = None
    worker_epoch: str | None = None
    base_ref: str | None = None
    debug: bool = False
    diagnostics_file: str | None = None


class FeatureFlags(LenientModel):
    """Runtime feature flags — extra="allow" for forward compatibility."""

    auto_background_tasks: str | None = None
    after_last_compact: str | None = None
    stream_watchdog: str | None = None
    post_for_session_ingress_v2: str | None = None
    use_ccr_v2: str | None = None
    proxy_resolves_hosts: str | None = None
    provider_managed_by_host: str | None = None


class SessionEnvironment(LenientModel):
    """Full session environment snapshot collected at SessionStart.

    Written to ``output/session_data.json`` by ``scripts/collect_session_data.sh``.
    Uses LenientModel (extra="allow") so new fields from future Claude Code
    versions don't break deserialization.
    """

    collected_at: datetime
    session: SessionContext
    surface: SurfaceInfo
    platform: PlatformInfo
    device: DeviceInfo
    runtime: RuntimeInfo
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    claude_env: dict[str, str] = Field(default_factory=dict)
    hook_input: dict[str, Any] = Field(default_factory=dict)
