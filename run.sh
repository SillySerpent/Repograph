#!/usr/bin/env bash
# Run RepoGraph from this checkout: prefers .venv/bin/python when present.
# With no arguments, prompts for a common entry (menu, doctor, help, status, or custom).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY=python3
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
fi

if [[ $# -gt 0 ]]; then
  exec "$PY" -m repograph.entry "$@"
fi

echo ""
echo "RepoGraph — choose how to run"
echo "  (Tip: pass args directly, e.g. ./run.sh sync --full)"
echo ""
echo "  1) Interactive menu     python -m repograph.entry menu"
echo "  2) Doctor                 repograph doctor"
echo "  3) CLI help               repograph --help"
echo "  4) Status                 repograph status"
echo "  5) Custom                 type subcommand + flags (e.g. sync --full)"
echo ""
read -r -p "Choice [1-5, default=1]: " choice
choice=${choice:-1}

case "$choice" in
  1) exec "$PY" -m repograph.entry menu ;;
  2) exec "$PY" -m repograph doctor ;;
  3) exec "$PY" -m repograph --help ;;
  4) exec "$PY" -m repograph status ;;
  5)
    read -r -p "Arguments after 'repograph': " rest
    # shellcheck disable=SC2206
    parts=($rest)
    exec "$PY" -m repograph "${parts[@]}"
    ;;
  *) exec "$PY" -m repograph.entry menu ;;
esac
