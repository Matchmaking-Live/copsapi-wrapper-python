from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Optional, Protocol

MISSING: Any = object()

DEFAULT_TTLS: dict[str, float] = {
    "profile": 300.0,
    "servers": 30.0,
    "leaderboard": 60.0,
    "history": 60.0,
    "match": 3600.0,
    "weapons": 120.0,
}


class CacheStore(Protocol):
    def get(self, key: str) -> Any: ...

    def set(self, key: str, value: Any, ttl: float) -> Any: ...


class MemoryCache:
    def __init__(self, max_entries: int = 5000, clock: Callable[[], float] = time.monotonic) -> None:
        self._entries: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._max = max_entries
        self._clock = clock
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        with self._lock:
            hit = self._entries.get(key)
            if hit is None:
                return None
            expires, value = hit
            if expires <= self._clock():
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl: float) -> None:
        if ttl <= 0:
            return
        with self._lock:
            self._entries[key] = (self._clock() + ttl, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


def resolve_ttls(overrides: Optional[dict[str, float]]) -> dict[str, float]:
    ttls = dict(DEFAULT_TTLS)
    if overrides:
        unknown = set(overrides) - set(ttls)
        if unknown:
            raise ValueError(f"Unknown cache TTL keys: {', '.join(sorted(unknown))}")
        ttls.update(overrides)
    return ttls
