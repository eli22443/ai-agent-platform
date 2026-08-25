import pytest

from app.agent.limits import AgentLimits, LimitTracker


def test_fresh_tracker_allows_continue():
    tracker = LimitTracker(AgentLimits(max_iterations=5, timeout_seconds=60))
    assert tracker.check() is None


def test_max_iterations_halt():
    tracker = LimitTracker(AgentLimits(max_iterations=3, timeout_seconds=60))
    for _ in range(3):
        tracker.record_iteration()
    assert tracker.check() == "max_iterations"


def test_timeout_halt(monkeypatch: pytest.MonkeyPatch):
    start = 1000.0
    monkeypatch.setattr("app.agent.limits.time.monotonic", lambda: start)
    tracker = LimitTracker(AgentLimits(max_iterations=20, timeout_seconds=10))
    monkeypatch.setattr("app.agent.limits.time.monotonic", lambda: start + 11)
    assert tracker.check() == "timeout"


def test_token_budget_halt():
    tracker = LimitTracker(
        AgentLimits(max_iterations=20, timeout_seconds=60, token_budget=100)
    )
    tracker.add_tokens(100)
    assert tracker.check() == "token_budget"


def test_token_budget_disabled_ignores_usage():
    tracker = LimitTracker(
        AgentLimits(max_iterations=20, timeout_seconds=60, token_budget=0)
    )
    tracker.add_tokens(1_000_000)
    assert tracker.check() is None


def test_add_tokens_ignores_none_and_zero():
    tracker = LimitTracker(
        AgentLimits(max_iterations=20, timeout_seconds=60, token_budget=50)
    )
    tracker.add_tokens(None)
    tracker.add_tokens(0)
    assert tracker.tokens_used == 0
    assert tracker.check() is None
