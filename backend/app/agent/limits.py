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
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self._started_at = time.monotonic()

    def record_iteration(self) -> None:
        self.iterations += 1

    def add_tokens(
        self,
        n: int | None = None,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        """Accumulate usage. ``n`` is total tokens when the API reports it."""
        if input_tokens:
            self.prompt_tokens += input_tokens
        if output_tokens:
            self.completion_tokens += output_tokens
        if n is None and (input_tokens is not None or output_tokens is not None):
            n = (input_tokens or 0) + (output_tokens or 0)
        if n:
            self.total_tokens += n

    def check(self) -> str | None:
        """Return a halt reason, or None if the run may continue."""
        if self.iterations >= self._limits.max_iterations:
            return "max_iterations"
        if time.monotonic() - self._started_at >= self._limits.timeout_seconds:
            return "timeout"
        budget = self._limits.token_budget
        if budget > 0 and self.total_tokens >= budget:
            return "token_budget"
        return None
