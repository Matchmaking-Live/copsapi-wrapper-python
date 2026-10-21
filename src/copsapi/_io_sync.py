from __future__ import annotations

import time
from typing import Any, Callable, Optional, TypeVar

import httpx

T = TypeVar("T")

HttpClient = httpx.Client


def sleep(seconds: float) -> None:
    time.sleep(max(0.0, seconds))


def resolve(value: Any) -> Any:
    return value


class Gate:
    def __init__(self, max_concurrent: int, dedupe: bool) -> None:
        pass

    def run(self, key: Optional[str], fn: Callable[[], T]) -> T:
        return fn()
