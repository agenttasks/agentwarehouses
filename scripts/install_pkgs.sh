#!/bin/bash
# SessionStart hook — install dependencies via uv + Makefile
# Runs on both local and remote; use CLAUDE_CODE_REMOTE to differentiate

cd "$CLAUDE_PROJECT_DIR" || exit 1

# Ensure uv is available
if ! command -v uv &>/dev/null; then
    pip install uv --quiet 2>/dev/null
fi

# Install core deps first, then dev + models
if [ -f Makefile ]; then
    make install 2>/dev/null
    make install-dev 2>/dev/null
else
    uv pip install --system -e . --quiet
    uv pip install --system -e ".[dev,models]" --quiet
fi

# Install pre-commit hooks if .pre-commit-config.yaml exists
if [ -f .pre-commit-config.yaml ] && command -v pre-commit &>/dev/null; then
    pre-commit install --install-hooks --quiet 2>/dev/null
    pre-commit install --hook-type pre-push --quiet 2>/dev/null
fi

exit 0
