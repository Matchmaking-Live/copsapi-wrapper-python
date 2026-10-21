from __future__ import annotations

import asyncio

import pytest

from conftest import api_error, game, player, profile, reply
from copsapi import PermissionDeniedError


def run(coro):
    return asyncio.run(coro)


def test_async_client_covers_the_same_calls(make_async):
    async def main():
        def handler(c):
            if c.path == "/profile":
                return reply([profile(int(i)) for i in c.query["ids"].split(",")])
            if c.path == "/status/servers":
                return reply({"6": {"name": "Europe/DE-1", "status": "online"}})
            return reply({"leaderboard_size": 1, "entries": [{"position": 1, "score": 9, "basic_info": {"user_id": 1}, "ranked": {}}]})

        cops, _ = make_async(handler)
        async with cops:
            assert [p.user_id for p in await cops.profiles.many(list(range(1, 25)))] == list(range(1, 25))
            assert (await cops.servers.pick(region="EU")).id == 6
            assert [e.position async for e in cops.leaderboards.iterate("mmr")] == [1]

    run(main())


def test_identical_requests_at_the_same_time_become_one(make_async):
    async def main():
        cops, mock = make_async(lambda c: reply({"1": {"name": "EU-1", "status": "online"}}), delay=0.05, cache=False)
        results = await asyncio.gather(cops.servers.list(), cops.servers.list(), cops.servers.list())
        assert len(mock.calls) == 1
        assert all(r == results[0] for r in results)
        await cops.aclose()

    run(main())


def test_async_cache_store_is_awaited(make_async):
    class AsyncStore:
        def __init__(self):
            self.data = {}

        async def get(self, key):
            return self.data.get(key)

        async def set(self, key, value, ttl):
            self.data[key] = value

    async def main():
        store = AsyncStore()
        cops, mock = make_async(lambda c: reply([profile(3)]), cache=store)
        await cops.profiles.get(3)
        await cops.profiles.get(3)
        assert len(mock.calls) == 1
        assert "profile:id:3" in store.data

    run(main())


def test_async_permission_errors(make_async):
    async def main():
        cops, _ = make_async(lambda c: api_error("insufficient_permissions", 403))
        with pytest.raises(PermissionDeniedError):
            await cops.autohost.poll([1])
        assert await cops.autohost.is_available() is False

    run(main())


def test_async_watcher_runs_until_the_game_ends(make_async):
    states = iter(
        [
            game(1, players=[player(10)]),
            game(1, players=[player(10, ping=-1)]),
            game(1, status="ended", players=[], room={"id": 7, "code": None, "name": "R", "map_id": 613, "game_mode_id": 15847, "has_password": False}),
        ]
    )

    async def main():
        cops, _ = make_async(lambda c: reply({"autohosts": [next(states)]}))
        watcher = cops.autohost.watch(interval=1)
        watcher.interval = 0.01
        events: list[str] = []
        watcher.on("player_join", lambda g, p, j: events.append(f"join {p.user_id}"))

        @watcher.on("player_disconnect")
        async def on_dc(g, p):
            await asyncio.sleep(0)
            events.append(f"dc {p.user_id}")

        watcher.on("ended", lambda g: events.append("ended"))
        watcher.track(1)
        await asyncio.wait_for(watcher.run(), 5)
        assert events == ["join 10", "dc 10", "ended"]
        assert len(watcher) == 0

    run(main())


def test_async_watcher_stops_when_the_token_cannot_host(make_async):
    async def main():
        cops, _ = make_async(lambda c: api_error("insufficient_permissions", 403))
        watcher = cops.autohost.watch()
        errors = []
        watcher.on("poll_error", errors.append)
        watcher.track(1)
        await asyncio.wait_for(watcher.run(), 5)
        assert [e.code for e in errors] == ["insufficient_permissions"]

    run(main())
