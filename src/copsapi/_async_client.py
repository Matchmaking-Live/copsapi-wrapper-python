from __future__ import annotations

import builtins
import random
import time
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, Sequence, Union

import httpx

from ._core import (
    AUTOHOST_DENIED,
    VERSION,
    PlayerRef,
    api_error,
    build_query,
    check_command,
    check_match_ids,
    check_rank,
    chunks,
    create_body,
    dedupe_refs,
    game_type_code,
    match_refs,
    order_profiles,
    parse_json,
    plain,
    ref_key,
    resolve_base_url,
    resolve_token,
    split_refs,
)
from ._io_async import Gate, HttpClient, resolve, sleep
from .cache import CacheStore, MemoryCache, resolve_ttls
from .errors import CopsApiError, make_error
from .helpers import random_password, region_of
from .models import (
    AutohostGame,
    GameServer,
    HostedRoom,
    LeaderboardEntry,
    LeaderboardPage,
    MatchHistoryEntry,
    MatchInfo,
    Profile,
    QuotaSnapshot,
    TokenCheck,
    WeaponStats,
    from_dict,
)
from .quota import QuotaTracker
from .watcher import AsyncAutohostWatcher

Hook = Optional[Callable[[dict[str, Any]], Any]]


class AsyncTransport:
    def __init__(
        self,
        *,
        token: str,
        base_url: str,
        retries: int,
        gateway_retries: int,
        max_rate_limit_wait: float,
        auth_header: str,
        user_agent: Optional[str],
        quota: QuotaTracker,
        gate: Gate,
        http: Any,
        on_request: Hook,
        on_response: Hook,
        on_retry: Hook,
    ) -> None:
        self._token = token
        self._base_url = base_url
        self._retries = retries
        self._gateway_retries = gateway_retries
        self._max_rate_limit_wait = max_rate_limit_wait
        self._auth_header = auth_header
        self._user_agent = user_agent
        self._quota = quota
        self._gate = gate
        self._http = http
        self._on_request = on_request
        self._on_response = on_response
        self._on_retry = on_retry

    def _headers(self, has_body: bool, authenticated: bool) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if has_body:
            headers["Content-Type"] = "application/json"
        if self._user_agent:
            headers["User-Agent"] = self._user_agent
        if authenticated:
            if self._auth_header == "x-api-key":
                headers["X-Api-Key"] = self._token
            else:
                headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def request(
        self,
        path: str,
        *,
        method: str = "GET",
        query: Optional[dict[str, Any]] = None,
        body: Any = None,
        priority: str = "normal",
        authenticated: bool = True,
    ) -> Any:
        params = build_query(query)
        key = f"{priority} {path}?{sorted(params.items())}" if method == "GET" else None

        async def send() -> Any:
            return await self._send(path, method, params, body, priority, authenticated)

        return await self._gate.run(key, send)

    async def _retry(self, info: dict[str, Any], delay: float) -> None:
        if self._on_retry:
            self._on_retry(info)
        await sleep(delay)

    async def _send(self, path: str, method: str, params: dict[str, str], body: Any, priority: str, authenticated: bool) -> Any:
        idempotent = method == "GET"
        headers = self._headers(body is not None, authenticated)
        url = self._base_url + path
        attempt = network_retries = gateway_retries = server_retries = rate_waits = 0
        while True:
            attempt += 1
            if authenticated:
                while True:
                    wait = self._quota.try_acquire(priority)
                    if wait <= 0:
                        break
                    await sleep(wait)
            if self._on_request:
                self._on_request({"method": method, "path": path, "attempt": attempt})
            started = time.monotonic()
            try:
                response = await self._http.request(method, url, params=params, json=body, headers=headers)
            except httpx.TimeoutException as err:
                if authenticated:
                    self._quota.release()
                error = make_error("timeout", "No answer from the Critical Ops API in time.", method=method, path=path)
                if idempotent and network_retries < self._retries:
                    network_retries += 1
                    await self._retry({"method": method, "path": path, "attempt": attempt, "reason": "timeout", "error": error}, 0.25 * 2 ** (network_retries - 1))
                    continue
                raise error from err
            except httpx.TransportError as err:
                if authenticated:
                    self._quota.release()
                error = make_error("network", f"Critical Ops API unreachable: {err}", method=method, path=path)
                if idempotent and network_retries < self._retries:
                    network_retries += 1
                    await self._retry({"method": method, "path": path, "attempt": attempt, "reason": "network", "error": error}, 0.25 * 2 ** (network_retries - 1))
                    continue
                raise error from err

            if authenticated:
                self._quota.update(response.headers)
                self._quota.release()
            status = response.status_code
            if self._on_response:
                self._on_response({"method": method, "path": path, "attempt": attempt, "status": status, "duration": time.monotonic() - started})
            text = response.text
            data = parse_json(text)

            if 200 <= status < 300:
                if data is None:
                    raise make_error("invalid_response", f"Expected JSON from {path}, got {text[:60] or 'an empty body'}.", status, method=method, path=path)
                return data

            has_api_error = isinstance(data, dict) and isinstance(data.get("error"), dict)
            if not has_api_error and (status == 404 or status >= 500):
                error = make_error("gateway", f"Critical Ops API gateway answered {status} {text[:40].strip()}".strip(), status, method=method, path=path)
                if gateway_retries < self._gateway_retries:
                    gateway_retries += 1
                    await self._retry({"method": method, "path": path, "attempt": attempt, "reason": "gateway", "error": error}, 0.15 * gateway_retries)
                    continue
                raise error

            error = api_error(status, data, response.headers, method, path)
            if error.code == "rate_limited":
                self._quota.exhaust(error.retry_after)
                wait = error.retry_after if error.retry_after is not None else self._quota.seconds_until_reset()
                if rate_waits < 2 and wait <= self._max_rate_limit_wait:
                    rate_waits += 1
                    await self._retry({"method": method, "path": path, "attempt": attempt, "reason": "rate_limited", "error": error}, wait)
                    continue
                raise error

            if idempotent and error.code in ("internal_error", "server_unavailable") and server_retries < self._retries:
                server_retries += 1
                await self._retry({"method": method, "path": path, "attempt": attempt, "reason": "server_error", "error": error}, 0.5 * 2 ** (server_retries - 1))
                continue
            raise error


class AsyncCopsClient:
    def __init__(
        self,
        token: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        timeout: float = 10.0,
        retries: int = 2,
        gateway_retries: int = 5,
        max_rate_limit_wait: float = 15.0,
        rate_limit: int = 60,
        rate_limit_reserve: int = 0,
        on_quota_exhausted: str = "wait",
        max_quota_wait: float = 65.0,
        max_concurrent: int = 8,
        dedupe: bool = True,
        cache: Union[bool, CacheStore] = True,
        cache_ttls: Optional[dict[str, float]] = None,
        auth_header: str = "bearer",
        user_agent: Optional[str] = f"copsapi-wrapper-python/{VERSION}",
        max_players_per_request: int = 20,
        validate_token: bool = True,
        http_client: Optional[Any] = None,
        transport: Optional[Any] = None,
        on_request: Hook = None,
        on_response: Hook = None,
        on_retry: Hook = None,
    ) -> None:
        if auth_header not in ("bearer", "x-api-key"):
            raise ValueError("auth_header must be 'bearer' or 'x-api-key'")
        resolved = resolve_token(token, validate_token)
        self.base_url = resolve_base_url(base_url)
        self.max_players_per_request = max(1, max_players_per_request)
        self._quota = QuotaTracker(rate_limit, rate_limit_reserve, on_quota_exhausted, max_quota_wait)
        self._owns_http = http_client is None
        self._http = http_client if http_client is not None else HttpClient(timeout=timeout, transport=transport)
        self._transport = AsyncTransport(
            token=resolved,
            base_url=self.base_url,
            retries=retries,
            gateway_retries=gateway_retries,
            max_rate_limit_wait=max_rate_limit_wait,
            auth_header=auth_header,
            user_agent=user_agent,
            quota=self._quota,
            gate=Gate(max_concurrent, dedupe),
            http=self._http,
            on_request=on_request,
            on_response=on_response,
            on_retry=on_retry,
        )
        self._store: Optional[CacheStore] = None if cache is False else (MemoryCache() if cache is True else cache)
        self._ttls = resolve_ttls(cache_ttls)
        self._autohost_allowed: Optional[bool] = None
        self.profiles = AsyncProfilesApi(self)
        self.servers = AsyncServersApi(self)
        self.matches = AsyncMatchesApi(self)
        self.stats = AsyncStatsApi(self)
        self.leaderboards = AsyncLeaderboardsApi(self)
        self.autohost = AsyncAutohostApi(self)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r})"

    async def __aenter__(self) -> AsyncCopsClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    @property
    def quota(self) -> QuotaSnapshot:
        return self._quota.snapshot()

    @property
    def autohost_permission(self) -> Optional[bool]:
        return self._autohost_allowed

    def set_autohost_permission(self, allowed: Optional[bool]) -> None:
        self._autohost_allowed = allowed

    async def request(self, path: str, **kwargs: Any) -> Any:
        return await self._transport.request(path, **kwargs)

    async def open_api_spec(self) -> dict[str, Any]:
        return await self._transport.request("/openapi.json", authenticated=False)

    async def clear_cache(self) -> None:
        if self._store is not None and hasattr(self._store, "clear"):
            await resolve(self._store.clear())

    async def verify_token(self) -> TokenCheck:
        try:
            await self.servers.list(fresh=True)
        except CopsApiError as err:
            if err.code in ("missing_token", "invalid_token", "token_revoked"):
                return TokenCheck(False, False, err, self.quota)
            raise
        autohost = await self.autohost.is_available(fresh=True)
        return TokenCheck(True, autohost, None, self.quota)

    async def _cache_get(self, key: str) -> Any:
        if self._store is None:
            return None
        return await resolve(self._store.get(key))

    async def _cache_set(self, key: str, value: Any, kind: str) -> None:
        if self._store is not None:
            await resolve(self._store.set(key, value, self._ttls[kind]))

    async def _cached(self, key: str, kind: str, fresh: bool, loader: Callable[[], Awaitable[Any]]) -> Any:
        if not fresh:
            hit = await self._cache_get(key)
            if hit is not None:
                return hit
        value = await loader()
        await self._cache_set(key, value, kind)
        return value


class AsyncProfilesApi:
    def __init__(self, client: AsyncCopsClient) -> None:
        self._client = client

    async def get(self, player: PlayerRef, *, fresh: bool = False) -> Profile:
        found = await self.many([player], fresh=fresh, skip_missing=False)
        if not found:
            raise make_error("user_not_found", f"No Critical Ops player {player!r}.", 404, path="/profile", method="GET")
        return found[0]

    async def find(self, player: PlayerRef, *, fresh: bool = False) -> Optional[Profile]:
        found = await self.many([player], fresh=fresh)
        return found[0] if found else None

    async def many(self, players: Sequence[PlayerRef], *, fresh: bool = False, skip_missing: bool = True) -> list[Profile]:
        refs = dedupe_refs(players)
        found: dict[str, Profile] = {}
        missing: list[PlayerRef] = []
        for ref in refs:
            hit = None if fresh else await self._client._cache_get(ref_key(ref))
            if hit is not None:
                found[ref_key(ref)] = hit
            else:
                missing.append(ref)
        for group in chunks(missing, self._client.max_players_per_request):
            for ref, profile in await self._load(group, skip_missing):
                found[ref_key(ref)] = profile
                await self._client._cache_set(ref_key(ref), profile, "profile")
                await self._client._cache_set(ref_key(profile.basic_info.user_id), profile, "profile")
        return order_profiles(refs, found)

    async def by_ids(self, ids: Sequence[int], *, fresh: bool = False) -> dict[int, Profile]:
        return {p.basic_info.user_id: p for p in await self.many(ids, fresh=fresh)}

    async def by_usernames(self, names: Sequence[str], *, fresh: bool = False) -> dict[str, Profile]:
        by_lower = {p.basic_info.name.lower(): p for p in await self.many(names, fresh=fresh)}
        return {name: by_lower[name.strip().lower()] for name in names if name.strip().lower() in by_lower}

    async def _load(self, refs: list[PlayerRef], skip_missing: bool) -> list[tuple[PlayerRef, Profile]]:
        ids, names = split_refs(refs)
        try:
            data = await self._client.request("/profile", query={"ids": ids, "usernames": names})
        except CopsApiError as err:
            if not skip_missing or err.code != "user_not_found":
                raise
            if len(refs) <= 1:
                return []
            mid = (len(refs) + 1) // 2
            return [*(await self._load(refs[:mid], True)), *(await self._load(refs[mid:], True))]
        return match_refs(refs, [from_dict(Profile, p) for p in data])


class AsyncServersApi:
    def __init__(self, client: AsyncCopsClient) -> None:
        self._client = client

    async def list(self, *, fresh: bool = False) -> list[GameServer]:
        async def load() -> list[GameServer]:
            data = await self._client.request("/status/servers")
            servers = []
            for key, value in data.items():
                if not str(key).isdigit():
                    continue
                name = str(value.get("name", ""))
                servers.append(GameServer(int(key), name, value.get("status") == "online", region_of(name)))
            return sorted(servers, key=lambda s: s.id)

        return await self._client._cached("servers", "servers", fresh, load)

    async def online(self, *, fresh: bool = False) -> builtins.list[GameServer]:
        return [s for s in await self.list(fresh=fresh) if s.online]

    async def get(self, server_id: int, *, fresh: bool = False) -> Optional[GameServer]:
        return next((s for s in await self.list(fresh=fresh) if s.id == server_id), None)

    async def pick(self, *, region: Optional[str] = None, name: Optional[str] = None, fallback_to_any: bool = True, fresh: bool = False) -> Optional[GameServer]:
        online = await self.online(fresh=fresh)
        matches = [
            s
            for s in online
            if (region is None or s.region == region) and (name is None or name.lower() in s.name.lower())
        ]
        if matches:
            return random.choice(matches)
        return online[0] if fallback_to_any and online else None


class AsyncMatchesApi:
    def __init__(self, client: AsyncCopsClient) -> None:
        self._client = client

    async def history(self, user_id: int, *, fresh: bool = False) -> list[MatchHistoryEntry]:
        async def load() -> list[MatchHistoryEntry]:
            data = await self._client.request("/matches/player", query={"user_id": user_id})
            return [from_dict(MatchHistoryEntry, m) for m in data.get("matches", [])]

        return await self._client._cached(f"history:{user_id}", "history", fresh, load)

    async def get(self, ids: Sequence[str], *, fresh: bool = False) -> list[MatchInfo]:
        wanted = check_match_ids(ids)
        found: dict[str, MatchInfo] = {}
        missing: list[str] = []
        for mid in wanted:
            hit = None if fresh else await self._client._cache_get(f"match:{mid}")
            if hit is not None:
                found[mid] = hit
            else:
                missing.append(mid)
        for group in chunks(missing, 20):
            data = await self._client.request("/matches/fetch", query={"ids": group})
            for raw in data.get("matches", []):
                match = from_dict(MatchInfo, raw)
                found[match.id.lower()] = match
                await self._client._cache_set(f"match:{match.id.lower()}", match, "match")
        return [found[mid] for mid in wanted if mid in found]

    async def one(self, match_id: str, *, fresh: bool = False) -> Optional[MatchInfo]:
        found = await self.get([match_id], fresh=fresh)
        return found[0] if found else None

    async def recent(self, user_id: int, *, limit: int = 5, game_type: Optional[Union[str, int]] = None, fresh: bool = False) -> list[tuple[MatchHistoryEntry, Optional[MatchInfo]]]:
        history = await self.history(user_id, fresh=fresh)
        if game_type is not None:
            code = game_type_code(game_type)
            history = [h for h in history if h.game_type == code]
        history = history[:limit]
        matches = {m.id.lower(): m for m in await self.get([h.id for h in history], fresh=fresh)} if history else {}
        return [(entry, matches.get(entry.id.lower())) for entry in history]


class AsyncStatsApi:
    def __init__(self, client: AsyncCopsClient) -> None:
        self._client = client

    async def weapons(self, user_id: int, game_type: Union[str, int] = "ranked", *, fresh: bool = False) -> list[WeaponStats]:
        code = game_type_code(game_type)

        async def load() -> list[WeaponStats]:
            data = await self._client.request("/stats/weapons", query={"user_id": user_id, "game_type": code})
            return [from_dict(WeaponStats, w) for w in data.get("weapons", [])]

        return await self._client._cached(f"weapons:{user_id}:{code}", "weapons", fresh, load)

    async def top_weapons(self, user_id: int, *, game_type: Union[str, int] = "ranked", by: str = "k", limit: int = 5, fresh: bool = False) -> list[WeaponStats]:
        if by not in ("k", "a", "h"):
            raise ValueError("by must be 'k', 'a' or 'h'")
        weapons = await self.weapons(user_id, game_type, fresh=fresh)
        return sorted(weapons, key=lambda w: getattr(w, by), reverse=True)[:limit]


class AsyncLeaderboardsApi:
    def __init__(self, client: AsyncCopsClient) -> None:
        self._client = client

    async def page(self, type: str, *, page: int = 1, rank: Optional[int] = None, fresh: bool = False) -> LeaderboardPage:
        check_rank(rank)
        page = max(1, int(page))

        async def load() -> LeaderboardPage:
            data = await self._client.request("/leaderboards", query={"type": plain(type), "page": page, "rank": plain(rank)})
            size = int(data.get("leaderboard_size", 0))
            entries = [from_dict(LeaderboardEntry, e) for e in data.get("entries", [])]
            return LeaderboardPage(type, page, rank, size, -(-size // 10), entries)

        return await self._client._cached(f"leaderboard:{plain(type)}:{plain(rank)}:{page}", "leaderboard", fresh, load)

    async def iterate(self, type: str, *, rank: Optional[int] = None, start_page: int = 1, max_pages: Optional[int] = None, fresh: bool = False) -> AsyncIterator[LeaderboardEntry]:
        seen: set[int] = set()
        page = start_page
        fetched = 0
        while max_pages is None or fetched < max_pages:
            result = await self.page(type, page=page, rank=rank, fresh=fresh)
            fetched += 1
            if not result.entries:
                return
            for entry in result.entries:
                if entry.basic_info.user_id in seen:
                    continue
                seen.add(entry.basic_info.user_id)
                yield entry
            if page >= result.pages:
                return
            page += 1

    async def top(self, type: str, count: int = 10, *, rank: Optional[int] = None, fresh: bool = False) -> list[LeaderboardEntry]:
        out: list[LeaderboardEntry] = []
        async for entry in self.iterate(type, rank=rank, max_pages=-(-count // 10) + 1, fresh=fresh):
            out.append(entry)
            if len(out) >= count:
                break
        return out


class AsyncAutohostApi:
    def __init__(self, client: AsyncCopsClient) -> None:
        self._client = client

    async def is_available(self, *, fresh: bool = False) -> bool:
        known = self._client.autohost_permission
        if known is not None and not fresh:
            return known
        try:
            await self._client.request("/autohost/poll", query={"ids": [1]}, priority="high")
            self._client.set_autohost_permission(True)
        except CopsApiError as err:
            if err.code == "insufficient_permissions":
                self._client.set_autohost_permission(False)
            elif err.code in ("game_not_found", "bad_request"):
                self._client.set_autohost_permission(True)
            else:
                raise
        return self._client.autohost_permission is True

    async def _call(self, path: str, method: str, **kwargs: Any) -> Any:
        if self._client.autohost_permission is False:
            raise make_error("insufficient_permissions", AUTOHOST_DENIED, 403, method=method, path=path, local=True)
        try:
            result = await self._client.request(path, method=method, priority="high", **kwargs)
        except CopsApiError as err:
            if err.code == "insufficient_permissions" and not err.local:
                self._client.set_autohost_permission(False)
                raise make_error("insufficient_permissions", AUTOHOST_DENIED, err.status, method=method, path=path) from err
            raise
        self._client.set_autohost_permission(True)
        return result

    async def create(self, *, server_id: int, map: Union[int, str], mode: Union[int, str], room_name: str, password: Optional[str] = None, validate: bool = True) -> AutohostGame:
        body = create_body(server_id, map, mode, room_name, password, validate)
        data = await self._call("/autohost/create", "POST", body=body)
        return from_dict(AutohostGame, data["autohost"])

    async def poll(self, ids: Sequence[int]) -> list[AutohostGame]:
        unique = list(dict.fromkeys(ids))
        games: list[AutohostGame] = []
        for group in chunks(unique, 50):
            data = await self._call("/autohost/poll", "GET", query={"ids": group})
            games.extend(from_dict(AutohostGame, g) for g in data.get("autohosts", []))
        return games

    async def get(self, game_id: int) -> Optional[AutohostGame]:
        games = await self.poll([game_id])
        return games[0] if games else None

    async def control(self, game_id: int, command: str, user_id: Optional[int] = None) -> AutohostGame:
        check_command(command, user_id)
        body = {"id": int(game_id), "command": str(plain(command)), "user_id": None if user_id is None else int(user_id)}
        data = await self._call("/autohost/control", "POST", body=body)
        return from_dict(AutohostGame, data["autohost"])

    async def kick(self, game_id: int, user_id: int) -> AutohostGame:
        return await self.control(game_id, "kick", user_id)

    async def restart(self, game_id: int) -> AutohostGame:
        return await self.control(game_id, "restart")

    async def add_owner(self, game_id: int, user_id: int) -> AutohostGame:
        return await self.control(game_id, "room_owner_add", user_id)

    async def remove_owner(self, game_id: int, user_id: int) -> AutohostGame:
        return await self.control(game_id, "room_owner_remove", user_id)

    async def close(self, game_id: int) -> AutohostGame:
        return await self.control(game_id, "close")

    async def wait_for_room(self, game_id: int, *, timeout: float = 35.0, interval: float = 1.5) -> AutohostGame:
        interval = max(0.5, interval)
        deadline = time.monotonic() + timeout
        while True:
            game = await self.get(game_id)
            if game is not None and game.room.code:
                return game
            if game is not None and game.status == "ended":
                raise make_error("game_rejected", f"The game server refused game {game_id}: {game.rejection_reason or 'no reason given'}.", path="/autohost/poll")
            if time.monotonic() + interval > deadline:
                if game is None:
                    raise make_error("game_gone", f"Game {game_id} is gone: the game server never created its room.", path="/autohost/poll")
                raise make_error("timeout", f"Game {game_id} had no room code after {timeout:g} seconds.", path="/autohost/poll")
            await sleep(interval)

    async def host(
        self,
        *,
        server_id: int,
        map: Union[int, str],
        mode: Union[int, str],
        room_name: str,
        password: Union[str, bool, None] = None,
        owners: Sequence[int] = (),
        validate: bool = True,
        timeout: float = 35.0,
        interval: float = 1.5,
    ) -> HostedRoom:
        if password is False:
            room_password: Optional[str] = None
        elif password is None or password is True:
            room_password = random_password()
        else:
            room_password = str(password)
        created = await self.create(server_id=server_id, map=map, mode=mode, room_name=room_name, password=room_password, validate=validate)
        game = await self.wait_for_room(created.id, timeout=timeout, interval=interval)
        for owner in owners:
            latest = await self.add_owner(created.id, owner)
            if latest.room.code:
                game = latest
        return HostedRoom(created.id, game.room.code or "", room_password, created.server_id, game)

    def watch(self, *, interval: float = 5.0, missing_grace: float = 60.0, untrack_ended: bool = True) -> AsyncAutohostWatcher:
        return AsyncAutohostWatcher(self._client, interval=interval, missing_grace=missing_grace, untrack_ended=untrack_ended)
