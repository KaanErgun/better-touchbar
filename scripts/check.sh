#!/usr/bin/env bash
# check.sh — the canonical local gate (~/.claude/CLAUDE.md §4); the steps live in dev.sh.
# Usage: ./scripts/check.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/dev.sh" check
