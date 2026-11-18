#!/usr/bin/env bash
# Point this worktree at the versioned .githooks directory.
set -euo pipefail

ROOT="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel)"
HOOK="$ROOT/.githooks/pre-commit"

[[ -f "$HOOK" ]] || { echo "install_hooks: missing $HOOK" >&2; exit 1; }
chmod +x "$HOOK"
git -C "$ROOT" config core.hooksPath .githooks

echo "hooks: $HOOK"
echo "hooks: core.hooksPath=.githooks"
