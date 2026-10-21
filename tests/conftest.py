from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Callable, Optional, Union

import httpx
import pytest

import copsapi._async_client as async_module
import copsapi._sync_client as sync_module
from copsapi import AsyncCopsClient, CopsClient

TOKEN = "cops_" + "0" * 48


@dataclass
class Call:
    method: str
    path: str
    query: dict[str, str]
    headers: httpx.Headers
    body: Any


Reply = Union[dict[str, Any], Exception]
Handler = Callable[[Call], Reply]


def reply(json_body: Any = None, status: int = 200, text: Optional[str] = None, headers: Optional[dict[str, str]] = None) -> dict[str, Any]:
    return {"status": status, "json": json_body, "text": text, "headers": headers or {}}


def api_error(code: str, status: int, message: str = "x", **extra: Any) -> dict[str, Any]:
    return reply({"error": {"code": code, "message": message, **extra}}, status)


class Mock:
    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.calls: list[Call] = []

    def _call(self, request: httpx.Request) -> Call:
        body = json.loads(request.content) if request.content else None
        path = request.url.path.split("/api/public/v2", 1)[-1]
        call = Call(request.method, path, dict(request.url.params), request.headers, body)
        self.calls.append(call)
        return call

    def _respond(self, result: Reply, request: httpx.Request) -> httpx.Response:
        if isinstance(result, Exception):
            raise result
        if result["text"] is not None:
            content = result["text"].encode()
        elif result["json"] is not None:
            content = json.dumps(result["json"]).encode()
        else:
            content = b""
        return httpx.Response(result["status"], content=content, headers=result["headers"], request=request)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(lambda request: self._respond(self.handler(self._call(request)), request))

    def slow_transport(self, delay: float) -> httpx.MockTransport:
        async def handle(request: httpx.Request) -> httpx.Response:
            call = self._call(request)
            await asyncio.sleep(delay)
            return self._respond(self.handler(call), request)

        return httpx.MockTransport(handle)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    async def fake_async_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(sync_module, "sleep", fake_sleep)
    monkeypatch.setattr(async_module, "sleep", fake_async_sleep)
    return slept


@pytest.fixture
def make() -> Callable[..., tuple[CopsClient, Mock]]:
    def factory(handler: Handler, **options: Any) -> tuple[CopsClient, Mock]:
        mock = Mock(handler)
        options.setdefault("token", TOKEN)
        return CopsClient(transport=mock.transport(), **options), mock

    return factory


@pytest.fixture
def make_async() -> Callable[..., tuple[AsyncCopsClient, Mock]]:
    def factory(handler: Handler, delay: float = 0.0, **options: Any) -> tuple[AsyncCopsClient, Mock]:
        mock = Mock(handler)
        options.setdefault("token", TOKEN)
        transport = mock.slow_transport(delay) if delay else mock.transport()
        return AsyncCopsClient(transport=transport, **options), mock

    return factory


def profile(user_id: int, name: Optional[str] = None) -> dict[str, Any]:
    stats = {"k": 10, "d": 5, "a": 2, "w": 3, "l": 1}
    return {
        "basic_info": {"user_id": user_id, "name": name or f"player{user_id}", "user_type": 1, "icon_id": 0, "player_level": {"level": 50, "current_xp": 1, "next_level_xp": 2}, "last_seen_time": ""},
        "account_age": "2y",
        "blocked_friend_requests": False,
        "blocked_clan_requests": False,
        "party_invite_permissions": 0,
        "ban": None,
        "stats": {
            "seasonal_stats": [
                {"season": 0, "ranked": stats, "casual": stats, "custom": stats},
                {"season": 1, "ranked": {"k": 20, "d": 10, "a": 0, "w": 2, "l": 2}, "casual": stats, "custom": stats},
            ],
            "ranked": {"placement_matches_left": 0, "wins": 5, "losses": 3, "highest_rank": 6, "mmr": 2400, "global_position": 0, "rank": 5},
            "leaderboard_data": {"position": 0, "score": 0},
        },
    }


def player(user_id: int, **extra: Any) -> dict[str, Any]:
    base = {"user_id": user_id, "team": 0, "kills": 0, "deaths": 0, "assists": 0, "damage_dealt": 0, "input_device_flags": 1, "left_match": False, "leave_reason": None, "ping": 40, "user_type": 1, "is_owner": False}
    base.update(extra)
    return base


def room(**extra: Any) -> dict[str, Any]:
    base = {"id": 7, "code": "ABC123", "name": "Room", "map_id": 613, "game_mode_id": 15847, "has_password": True}
    base.update(extra)
    return base


def game(game_id: int, **extra: Any) -> dict[str, Any]:
    base = {
        "id": game_id,
        "status": "open",
        "created_at": 1,
        "updated_at": 1,
        "ended_at": None,
        "pending_expires_at": None,
        "server_id": 3,
        "room": room(),
        "player_count": 0,
        "match_started_at": None,
        "match_state": "WaitingForPlayers",
        "round": 0,
        "scores": [0, 0],
        "players": [],
        "results": [],
        "replay_id": None,
        "rejection_reason": None,
    }
    base.update(extra)
    return base


def result(**extra: Any) -> dict[str, Any]:
    base = {"match_id": "m", "map_id": 613, "team_factions": [0, 1], "winning_team": 0, "win_condition": "TeamKills", "scores": [7, 3], "started_at": 1, "ended_at": 2, "map_variation": 0, "rounds_played": 10, "players": []}
    base.update(extra)
    return base
