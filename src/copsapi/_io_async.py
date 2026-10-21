from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable, Optional, TypeVar

import httpx

T = TypeVar("T")

HttpClient = httpx.AsyncClient


async def sleep(seconds: float) -> None:
    await asyncio.sleep(max(0.0, seconds))


async def resolve(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class Gate:
    def __init__(self, max_concurrent: int, dedupe: bool) -> None:
        self._semaphore = asyncio.Semaphore(max(1, max_concurrent))
        self._dedupe = dedupe
        self._inflight: dict[str, asyncio.Future[Any]] = {}

    async def _limited(self, fn: Callable[[], Awaitable[T]]) -> T:
        async with self._semaphore:
            return await fn()

    async def run(self, key: Optional[str], fn: Callable[[], Awaitable[T]]) -> T:
        if key is None or not self._dedupe:
            return await self._limited(fn)
        pending = self._inflight.get(key)
        if pending is not None:
            return await asyncio.shield(pending)
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            result = await self._limited(fn)
        except BaseException as err:
            future.set_exception(err)
            future.exception()
            raise
        else:
            future.set_result(result)
            return result
        finally:
            self._inflight.pop(key, None)
