#!/usr/bin/env bash
# Install ccbot as a global uv tool from the local source.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "Installing ccbot from $REPO_DIR ..."
uv tool install --force --reinstall "$REPO_DIR"

# Verify
"$HOME/.local/share/uv/tools/ccbot/bin/python3" -c "import ccbot; print('ccbot installed successfully')"
