#!/usr/bin/env bash
# Bootstrap RepoGraph dev environment: venv, editable install, doctor (see scripts/repograph_setup.py).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_SOURCED=0
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  SCRIPT_SOURCED=1
fi

python3 "$ROOT/scripts/repograph_setup.py" "$@"

ACTIVATE_PATH="$ROOT/.venv/bin/activate"
TARGET_SHELL="${SHELL:-/bin/bash}"
AUTO_ACTIVATE_ALLOWED=1

if [[ ! -f "$ACTIVATE_PATH" ]]; then
  AUTO_ACTIVATE_ALLOWED=0
fi
if [[ ! -t 0 || ! -t 1 ]]; then
  AUTO_ACTIVATE_ALLOWED=0
fi
if [[ -n "${CI:-}" || -n "${REPOGRAPH_SETUP_NO_AUTO_ACTIVATE:-}" ]]; then
  AUTO_ACTIVATE_ALLOWED=0
fi

if [[ $AUTO_ACTIVATE_ALLOWED -eq 1 ]]; then
  if [[ $SCRIPT_SOURCED -eq 1 ]]; then
    echo ""
    echo "Activating RepoGraph virtualenv in the current shell..."
    # shellcheck source=/dev/null
    source "$ACTIVATE_PATH"
    hash -r 2> /dev/null || true
    return 0
  fi

  echo ""
  echo "Opening an activated RepoGraph shell (exit to return to your previous shell)..."
  exec "$TARGET_SHELL" -i -c "cd '$ROOT'; source '$ACTIVATE_PATH'; hash -r 2>/dev/null || true; exec '$TARGET_SHELL' -i"
fi
