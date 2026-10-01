#!/usr/bin/env bash
# Context Arbor one-line installer (macOS / Linux / WSL / Git Bash).
#
#   curl -fsSL https://raw.githubusercontent.com/renf0x/context-arbor/main/install.sh | bash
#
# Downloads arbor.py and scaffolds memory and agent adapters.
set -euo pipefail

RAW="https://raw.githubusercontent.com/renf0x/context-arbor/main/arbor.py"
TARGET="${1:-.}"
AGENTS="${ARBOR_AGENTS:-all}"

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "error: Python 3.10+ is required but was not found on PATH." >&2
  exit 1
fi

mkdir -p "$TARGET"
echo "Downloading arbor.py -> $TARGET/arbor.py"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$RAW" -o "$TARGET/arbor.py"
else
  wget -qO "$TARGET/arbor.py" "$RAW"
fi

echo "Scaffolding Context Arbor (agents: $AGENTS)"
( cd "$TARGET" && "$PY" arbor.py init --agents "$AGENTS" )

echo
echo "Done. Memory, Obsidian integration and session management are ready."
echo "Search notes: python arbor.py memory query 'question'"
