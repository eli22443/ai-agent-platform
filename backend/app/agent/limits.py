from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentLimits:
    """Immutable per-run limit configuration (from Settings)."""

    max_iterations: int = 10
    timeout_seconds: float = 180
    token_budget: int = 0  # 0 = disabled


class LimitTracker:
    """Mutable counters for one run_agent invocation."""

    def __init__(self, limits: AgentLimits) -> None:
        self._limits = limits
        self.iterations = 0
        self.tokens_used = 0
        self._started_at = time.monotonic()

    def record_iteration(self) -> None:
        self.iterations += 1

    def add_tokens(self, n: int | None) -> None:
        if n:
            self.tokens_used += n

    def check(self) -> str | None:
        """Return a halt reason, or None if the run may continue."""
        if self.iterations >= self._limits.max_iterations:
            return "max_iterations"
        if time.monotonic() - self._started_at >= self._limits.timeout_seconds:
            return "timeout"
        budget = self._limits.token_budget
        if budget > 0 and self.tokens_used >= budget:
            return "token_budget"
        return None
