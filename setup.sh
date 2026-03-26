#!/usr/bin/env bash
# Bootstrap RepoGraph dev environment: venv, editable install, doctor (see scripts/repograph_setup.py).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$ROOT/scripts/repograph_setup.py" "$@"
