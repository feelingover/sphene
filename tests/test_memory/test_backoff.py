"""memory/backoff.py のテスト"""

from memory.backoff import FailureBackoff


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class TestFailureBackoff:
    def test_not_blocked_initially(self):
        backoff = FailureBackoff(10, 100, clock=FakeClock())
        assert not backoff.is_blocked("a")
        assert backoff.failure_count("a") == 0

    def test_exponential_delay_with_cap(self):
        clock = FakeClock()
        backoff = FailureBackoff(10, 35, clock=clock)
        expected_delays = [10, 20, 35, 35]
        for i, delay in enumerate(expected_delays, start=1):
            assert backoff.record_failure("a") == i
            clock.now += delay - 0.001
            assert backoff.is_blocked("a")
            clock.now += 0.001
            assert not backoff.is_blocked("a")

    def test_reset_clears_state(self):
        backoff = FailureBackoff(10, 100, clock=FakeClock())
        backoff.record_failure("a")
        backoff.reset("a")
        assert not backoff.is_blocked("a")
        assert backoff.failure_count("a") == 0
        assert backoff.record_failure("a") == 1

    def test_keys_are_independent(self):
        backoff = FailureBackoff(10, 100, clock=FakeClock())
        backoff.record_failure("a")
        assert backoff.is_blocked("a")
        assert not backoff.is_blocked("b")

    def test_reset_unknown_key_is_noop(self):
        FailureBackoff(10, 100, clock=FakeClock()).reset("missing")
