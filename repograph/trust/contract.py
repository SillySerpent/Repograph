"""Versioned accuracy contract — machine-readable defaults for health reports."""
from __future__ import annotations

# Bump when ACCURACY_CONTRACT.md semantics change in a user-visible way.
CONTRACT_VERSION = "2026.03.22"

# Minimum edge confidence treated as "strong" for dead-code / impact heuristics docs.
STRONG_CALL_CONFIDENCE = 0.5
