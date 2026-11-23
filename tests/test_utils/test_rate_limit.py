"""utils/rate_limit.py のテスト"""

from utils.rate_limit import SlidingWindowRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _hit(limiter: SlidingWindowRateLimiter, key: object) -> bool:
    if limiter.is_allowed(key):
        limiter.record(key)
        return True
    return False


class TestSlidingWindowRateLimiter:
    def test_allows_up_to_max_events(self):
        limiter = SlidingWindowRateLimiter(3, 60, clock=FakeClock())
        assert [_hit(limiter, "a") for _ in range(4)] == [True, True, True, False]

    def test_keys_are_independent(self):
        limiter = SlidingWindowRateLimiter(1, 60, clock=FakeClock())
        assert _hit(limiter, "a")
        assert _hit(limiter, "b")
        assert not _hit(limiter, "a")

    def test_window_slides(self):
        clock = FakeClock()
        limiter = SlidingWindowRateLimiter(2, 60, clock=clock)
        assert _hit(limiter, "a")
        clock.now += 30
        assert _hit(limiter, "a")
        assert not _hit(limiter, "a")
        clock.now += 30  # 最初のイベントがちょうど期限切れ
        assert _hit(limiter, "a")
        assert not _hit(limiter, "a")

    def test_is_allowed_does_not_record(self):
        limiter = SlidingWindowRateLimiter(1, 60, clock=FakeClock())
        assert limiter.is_allowed("a")
        assert limiter.is_allowed("a")
        assert len(limiter) == 0

    def test_disabled_when_max_events_is_zero(self):
        limiter = SlidingWindowRateLimiter(0, 60, clock=FakeClock())
        assert not limiter.enabled
        assert all(_hit(limiter, "a") for _ in range(100))
        assert len(limiter) == 0

    def test_stale_keys_are_swept(self):
        clock = FakeClock()
        limiter = SlidingWindowRateLimiter(5, 60, clock=clock)
        for key in range(10):
            _hit(limiter, key)
        assert len(limiter) == 10
        clock.now += 61
        assert _hit(limiter, "new")
        assert len(limiter) == 1
