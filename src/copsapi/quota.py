from __future__ import annotations

import math
import threading
import time
from typing import Callable, Mapping, Optional

from .errors import make_error
from .models import QuotaSnapshot


def _next_minute(now: float) -> float:
    return (math.floor(now / 60) + 1) * 60


class QuotaTracker:
    def __init__(
        self,
        limit: int = 60,
        reserve: int = 0,
        on_exhausted: str = "wait",
        max_wait: float = 65.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if on_exhausted not in ("wait", "raise"):
            raise ValueError("on_exhausted must be 'wait' or 'raise'")
        self._limit = limit
        self._remaining = limit
        self._reset_at = 0.0
        self._in_flight = 0
        self._reserve = max(0, reserve)
        self._mode = on_exhausted
        self._max_wait = max_wait
        self._clock = clock
        self._lock = threading.Lock()

    def _roll(self, now: float) -> None:
        if now >= self._reset_at:
            self._remaining = self._limit
            self._reset_at = _next_minute(now)

    def try_acquire(self, priority: str) -> float:
        with self._lock:
            now = self._clock()
            self._roll(now)
            floor = self._reserve if priority == "normal" else 0
            if self._remaining > floor:
                self._remaining -= 1
                self._in_flight += 1
                return 0.0
            wait = self._reset_at - now + 0.025
        if self._mode == "raise" or wait > self._max_wait:
            why = (
                f"the last {floor} requests of this minute are reserved for high-priority calls"
                if floor > 0
                else "the per-minute quota is used up"
            )
            raise make_error("rate_limited", f"Request held back: {why}.", 429, math.ceil(wait), local=True)
        return wait

    def release(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)

    def update(self, headers: Mapping[str, str]) -> None:
        def number(name: str) -> Optional[float]:
            value = headers.get(name)
            try:
                return float(value) if value is not None else None
            except ValueError:
                return None

        limit = number("x-ratelimit-limit")
        remaining = number("x-ratelimit-remaining")
        reset = number("x-ratelimit-reset")
        with self._lock:
            if limit and limit > 0:
                self._limit = int(limit)
            if reset and reset > 0:
                self._reset_at = reset
            if remaining is not None:
                self._remaining = max(0, int(remaining) - max(0, self._in_flight - 1))

    def exhaust(self, retry_after: Optional[float]) -> None:
        with self._lock:
            self._remaining = 0
            if retry_after is not None:
                self._reset_at = self._clock() + retry_after

    def seconds_until_reset(self) -> float:
        return max(0.0, self._reset_at - self._clock())

    def snapshot(self) -> QuotaSnapshot:
        with self._lock:
            now = self._clock()
            self._roll(now)
            return QuotaSnapshot(self._limit, self._remaining, self._reset_at, max(0.0, self._reset_at - now), self._reserve)
