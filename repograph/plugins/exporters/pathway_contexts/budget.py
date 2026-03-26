# Canonical token-budget helpers owned by the pathway-context exporter.
"""Token budget management — trims context docs to fit within token limits."""
from __future__ import annotations


# Rough characters-per-token estimate
CHARS_PER_TOKEN = 4


class TokenBudgetManager:
    """Manages token budget for context document generation."""

    def __init__(self, max_tokens: int = 2000) -> None:
        self.max_tokens = max_tokens
        self._max_chars = max_tokens * CHARS_PER_TOKEN

    def trim_steps(self, steps: list[dict]) -> list[dict]:
        """
        Trim lowest-confidence steps to fit within budget,
        always preserving the entry (order=0) and terminal (last) steps.
        """
        if not steps:
            return steps

        # Estimate chars per step (~120 chars each)
        chars_per_step = 150
        header_chars = 400  # fixed header overhead

        available_chars = self._max_chars - header_chars
        max_steps = max(2, available_chars // chars_per_step)

        if len(steps) <= max_steps:
            return steps

        # Always keep first (entry) and last (terminal)
        entry = steps[0]
        terminal = steps[-1]
        middle = steps[1:-1]

        # Sort middle by confidence descending, keep top N
        slots = max_steps - 2
        if slots <= 0:
            return [entry, terminal]

        middle_sorted = sorted(
            middle,
            key=lambda s: s.get("confidence", 0.5),
            reverse=True,
        )
        kept = sorted(middle_sorted[:slots], key=lambda s: s.get("step_order", s.get("order", 0)))
        return [entry] + kept + [terminal]

    def estimate_tokens(self, text: str) -> int:
        return len(text) // CHARS_PER_TOKEN
