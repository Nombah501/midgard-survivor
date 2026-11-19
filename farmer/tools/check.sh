#!/usr/bin/env bash
# Static checks for the farmer repository.
#
# Usage:
#   tools/check.sh                 pre-commit checks (safe in .githooks/pre-commit)
#   tools/check.sh --post-commit   also require HEAD == worktree (clean tree)
#
# check_api.py needs the local, gitignored analysis/src tree. When it is
# missing the check is skipped with a message instead of failing a clean clone.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FARMER="$ROOT/farmer"
MODE="${1:-pre-commit}"

case "$MODE" in
	pre-commit|--post-commit|post-commit) ;;
	*) echo "check: unknown mode: $MODE" >&2; exit 2 ;;
esac

cd "$ROOT"
fail=0

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
	echo "check: not inside a git worktree" >&2
	exit 2
}

# Whitespace errors in the working tree and in the index.
if ! git diff --check; then
	fail=1
fi
if ! git diff --cached --check; then
	fail=1
fi

# Shell syntax.
for f in \
	"$FARMER/build.sh" \
	"$FARMER/install.sh" \
	"$FARMER/run.sh" \
	"$FARMER/uninstall.sh" \
	"$FARMER/tools/check.sh" \
	"$FARMER/tools/verify.sh" \
	"$FARMER/tools/install_hooks.sh" \
	"$ROOT/.githooks/pre-commit"
do
	[[ -f "$f" ]] || continue
	if ! bash -n "$f"; then
		echo "check: shell syntax: $f" >&2
		fail=1
	fi
done

# Python syntax (tools only; the game code is GDScript).
if ! python3 - "$FARMER"/tools/*.py <<'PY'
import ast
import sys

for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as fh:
        ast.parse(fh.read(), path)
PY
then
	echo "check: python syntax failed" >&2
	fail=1
fi

# Test-only seams: FARMER_TEST_* is read only by farmer.gd's _test_env, which
# ignores it outside verify-* sessions.
seams="$(grep -n 'get_environment("FARMER_TEST_' "$FARMER/src/farmer.gd" || true)"
if [[ "$(grep -c . <<<"$seams")" -ne 1 ]] || ! grep -q '"FARMER_TEST_" + name' <<<"$seams"; then
	echo "check: FARMER_TEST_* must be read only through _test_env in farmer.gd:" >&2
	echo "$seams" >&2
	fail=1
fi

# Behaviour tests for supervisor.py and run.sh/install.sh (fake child, fake
# game; no real game). Run when that code is staged, and always post-commit.
if [[ "$MODE" != "pre-commit" ]] \
	|| git diff --cached --name-only | grep -Eq '^farmer/(tools/|tests/|run\.sh$|install\.sh$)'; then
	if ! (cd "$FARMER" && python3 -m pytest -q tests); then
		echo "check: pytest failed" >&2
		fail=1
	fi
fi

# Game API identifiers used by farmer.gd. analysis/src is not committed.
if [[ -d "$ROOT/analysis/src" ]]; then
	if ! (cd "$FARMER" && python3 tools/check_api.py); then
		fail=1
	fi
else
	echo "check: SKIP check_api (analysis/src missing; decompile the game first)"
fi

if [[ "$MODE" == "--post-commit" || "$MODE" == "post-commit" ]]; then
	if ! git diff --exit-code HEAD >/dev/null; then
		echo "check: worktree differs from HEAD" >&2
		git diff --stat HEAD >&2
		fail=1
	fi
	if ! git diff --cached --exit-code HEAD >/dev/null; then
		echo "check: index differs from HEAD" >&2
		git diff --cached --stat HEAD >&2
		fail=1
	fi
	if [[ -n "$(git status --porcelain)" ]]; then
		echo "check: uncommitted or untracked files:" >&2
		git status --short >&2
		fail=1
	fi
fi

if [[ "$fail" -ne 0 ]]; then
	echo "check: FAIL" >&2
	exit 1
fi

echo "check: OK"
