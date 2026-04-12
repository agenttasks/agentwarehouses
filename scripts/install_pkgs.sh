#!/bin/bash
# SessionStart hook — install dependencies via uv + Makefile
# Runs on both local and remote; use CLAUDE_CODE_REMOTE to differentiate

cd "$CLAUDE_PROJECT_DIR" || exit 1

# Ensure uv is available
if ! command -v uv &>/dev/null; then
    pip install uv --quiet 2>/dev/null
fi

# Install with dev + models deps via Makefile
if [ -f Makefile ]; then
    make install-dev 2>/dev/null
else
    uv pip install --system -e ".[dev,models]" --quiet
fi

exit 0
