#!/bin/bash
# SessionStart hook — collect platform, surface, device, session, and Claude metadata.
# Reads hook input JSON from stdin, merges with env vars and system info,
# writes output/session_data.json using Python + orjson for consistency.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
OUTPUT_DIR="$PROJECT_DIR/output"
OUTPUT_FILE="$OUTPUT_DIR/session_data.json"

mkdir -p "$OUTPUT_DIR"

# Read hook input JSON from stdin (SessionStartInput)
export HOOK_INPUT=""
if [ ! -t 0 ]; then
    HOOK_INPUT=$(cat)
fi

# Collect all CLAUDE_* env vars, excluding sensitive tokens/file descriptors
collect_claude_env() {
    python3 -c "
import os, json
sensitive = {'CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR',
             'CLAUDE_CODE_WEBSOCKET_AUTH_FILE_DESCRIPTOR',
             'CLAUDE_SESSION_INGRESS_TOKEN_FILE',
             'CLAUDE_CODE_OAUTH_TOKEN',
             'ANTHROPIC_API_KEY'}
env = {k: v for k, v in sorted(os.environ.items())
       if (k.startswith('CLAUDE') or k == 'CLAUDECODE')
       and k not in sensitive}
print(json.dumps(env))
"
}

# Build the full session data JSON via Python for correctness
export CLAUDE_ENV
CLAUDE_ENV=$(collect_claude_env)
export OUTPUT_FILE

python3 << 'PYEOF'
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import orjson
    def dumps(obj):
        return orjson.dumps(obj, option=orjson.OPT_INDENT_2).decode()
except ImportError:
    def dumps(obj):
        return json.dumps(obj, indent=2)

hook_input_raw = os.environ.get("HOOK_INPUT", "")
claude_env_raw = os.environ.get("CLAUDE_ENV", "")

# Parse hook input (SessionStartInput from Claude Code)
hook_input = {}
if hook_input_raw:
    try:
        hook_input = json.loads(hook_input_raw)
    except json.JSONDecodeError:
        pass

# Parse collected CLAUDE_* env vars
claude_env = {}
if claude_env_raw:
    try:
        claude_env = json.loads(claude_env_raw)
    except json.JSONDecodeError:
        pass

# --- Session ---
session = {
    "session_id": (claude_env.get("CLAUDE_CODE_SESSION_ID")
                   or hook_input.get("session_id", "")),
    "remote_session_id": claude_env.get("CLAUDE_CODE_REMOTE_SESSION_ID"),
    "source": hook_input.get("source"),
    "model": hook_input.get("model"),
    "cwd": hook_input.get("cwd", os.getcwd()),
    "transcript_path": hook_input.get("transcript_path"),
    "permission_mode": hook_input.get("permission_mode"),
    "agent_id": hook_input.get("agent_id"),
    "agent_type": hook_input.get("agent_type"),
}

# --- Surface ---
# CLAUDE_CODE_ENTRYPOINT encodes how the user launched Claude Code:
#   cli, desktop, web, ide_vscode, ide_jetbrains, remote_mobile, etc.
entrypoint = claude_env.get("CLAUDE_CODE_ENTRYPOINT", "unknown")
surface = {
    "entrypoint": entrypoint,
    "is_remote": claude_env.get("CLAUDE_CODE_REMOTE", "false") == "true",
    "remote_environment_type": claude_env.get("CLAUDE_CODE_REMOTE_ENVIRONMENT_TYPE"),
}

# --- Platform ---
uname = platform.uname()
plat = {
    "system": uname.system,
    "release": uname.release,
    "version": uname.version,
    "machine": uname.machine,
    "processor": uname.processor or uname.machine,
    "python_version": platform.python_version(),
    "platform_string": platform.platform(),
}

# --- Device / Container ---
device = {
    "container_id": claude_env.get("CLAUDE_CODE_CONTAINER_ID"),
    "hostname": platform.node(),
    "shell": os.environ.get("SHELL", "unknown"),
    "terminal": os.environ.get("TERM", "unknown"),
    "user": os.environ.get("USER", os.environ.get("LOGNAME", "unknown")),
    "home": os.environ.get("HOME", "unknown"),
    "lang": os.environ.get("LANG"),
}

# --- Claude Code Runtime ---
runtime = {
    "version": claude_env.get("CLAUDE_CODE_VERSION"),
    "exec_path": claude_env.get("CLAUDE_CODE_EXECPATH"),
    "environment_runner_version": claude_env.get("CLAUDE_CODE_ENVIRONMENT_RUNNER_VERSION"),
    "worker_epoch": claude_env.get("CLAUDE_CODE_WORKER_EPOCH"),
    "base_ref": claude_env.get("CLAUDE_CODE_BASE_REF"),
    "debug": claude_env.get("CLAUDE_CODE_DEBUG", "false") == "true",
    "diagnostics_file": claude_env.get("CLAUDE_CODE_DIAGNOSTICS_FILE"),
}

# --- Feature Flags ---
features = {
    "auto_background_tasks": claude_env.get("CLAUDE_AUTO_BACKGROUND_TASKS"),
    "after_last_compact": claude_env.get("CLAUDE_AFTER_LAST_COMPACT"),
    "stream_watchdog": claude_env.get("CLAUDE_ENABLE_STREAM_WATCHDOG"),
    "post_for_session_ingress_v2": claude_env.get("CLAUDE_CODE_POST_FOR_SESSION_INGRESS_V2"),
    "use_ccr_v2": claude_env.get("CLAUDE_CODE_USE_CCR_V2"),
    "proxy_resolves_hosts": claude_env.get("CLAUDE_CODE_PROXY_RESOLVES_HOSTS"),
    "provider_managed_by_host": claude_env.get("CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST"),
}

# --- Full output ---
data = {
    "collected_at": datetime.now(timezone.utc).isoformat(),
    "session": session,
    "surface": surface,
    "platform": plat,
    "device": device,
    "runtime": runtime,
    "features": features,
    "claude_env": claude_env,
    "hook_input": hook_input,
}

output_file = os.environ.get("OUTPUT_FILE", "output/session_data.json")
Path(output_file).parent.mkdir(parents=True, exist_ok=True)
Path(output_file).write_text(dumps(data) + "\n")
PYEOF

exit 0
