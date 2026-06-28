#!/bin/bash
# SessionStart hook for Claude Code on the web.
# Installs project dependencies so tests and linters are ready when the
# session starts. Stack is auto-detected from the dependency manifest, so this
# keeps working as KeloFred grows — no edits needed when you pick a stack.
#
# Runs synchronously (no async block) so dependencies are guaranteed ready
# before the agent loop begins. Switch to async mode for faster startup once
# installs get slow.
set -euo pipefail

# Only run in the remote (Claude Code on the web) environment.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

if [ -f package.json ]; then
  echo "Detected Node project — installing npm dependencies..."
  if [ -f package-lock.json ]; then npm ci; else npm install; fi
elif [ -f pyproject.toml ] || [ -f requirements.txt ]; then
  echo "Detected Python project — installing dependencies..."
  python -m pip install --upgrade pip
  [ -f requirements.txt ] && pip install -r requirements.txt
  [ -f pyproject.toml ] && pip install -e . 2>/dev/null || true
elif [ -f go.mod ]; then
  echo "Detected Go project — downloading modules..."
  go mod download
elif [ -f Cargo.toml ]; then
  echo "Detected Rust project — fetching crates..."
  cargo fetch
else
  echo "No dependency manifest found yet — skipping install."
  echo "This hook will auto-install once you add a manifest (package.json, pyproject.toml, go.mod, Cargo.toml)."
fi

echo "SessionStart hook complete."
