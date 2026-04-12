#!/bin/bash

if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR" || exit 1

# Install in editable mode with all dependencies
pip install -e ".[dev]" --quiet

exit 0
