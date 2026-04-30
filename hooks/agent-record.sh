#!/usr/bin/env bash
set -euo pipefail

TOOL="${1:?tool required}"
EVENT="${2:-}"
ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

# Hooks must be silent. Claude UserPromptSubmit stdout becomes model context,
# and Codex may show hook output in the TUI.
"$ROOT/bin/cmux-recovery" record --tool "$TOOL" --event "$EVENT" >/dev/null 2>&1 || true

