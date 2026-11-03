"""Limitador de taxa de janela dupla (sequencial, sem threads)."""

import time
from collections import deque
from collections.abc import Callable, Sequence


class RateLimiter:
    def __init__(
        self,
        limits: Sequence[tuple[int, float]],
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._windows = [(max_requests, span, deque()) for max_requests, span in limits]
        self._now = now
        self._sleep = sleep
        self._blocked_until = 0.0

    def acquire(self) -> None:
        remaining = self._blocked_until - self._now()
        if remaining > 0:
            self._sleep(remaining)
        while True:
            current = self._now()
            wait = 0.0
            for max_requests, span, stamps in self._windows:
                while stamps and current - stamps[0] >= span:
                    stamps.popleft()
                if len(stamps) >= max_requests:
                    wait = max(wait, stamps[0] + span - current)
            if wait <= 0:
                break
            self._sleep(wait)
        for _, _, stamps in self._windows:
            stamps.append(current)

    def penalize(self, seconds: float) -> None:
        self._blocked_until = max(self._blocked_until, self._now() + seconds)


def riot_limiter(
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> RateLimiter:
    return RateLimiter([(20, 1.0), (100, 120.0)], now=now, sleep=sleep)
