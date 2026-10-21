from __future__ import annotations

import asyncio
import inspect
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

from .errors import CopsApiError
from .models import AutohostGame

if TYPE_CHECKING:
    from ._async_client import AsyncCopsClient
    from ._sync_client import CopsClient

EVENTS = frozenset(
    {
        "update",
        "room_ready",
        "rejected",
        "state",
        "match_start",
        "score",
        "player_join",
        "player_leave",
        "player_disconnect",
        "player_reconnect",
        "player_team_change",
        "match_result",
        "ended",
        "gone",
        "poll_error",
        "handler_error",
    }
)

FATAL_CODES = frozenset({"insufficient_permissions", "invalid_token", "token_revoked", "missing_token"})

Event = tuple[str, tuple[Any, ...]]


@dataclass(frozen=True)
class JoinInfo:
    first_seen_at: float
    since_room_ready: Optional[float]


@dataclass
class _Tracked:
    id: int
    meta: Any
    added_at: float
    seen_results: int
    game: Optional[AutohostGame] = None
    last_seen_at: Optional[float] = None
    room_ready_at: Optional[float] = None
    joins: dict[int, JoinInfo] = field(default_factory=dict)
    offline_since: dict[int, float] = field(default_factory=dict)


class _Engine:
    def __init__(self, missing_grace: float, untrack_ended: bool, clock: Callable[[], float]) -> None:
        self.missing_grace = missing_grace
        self.untrack_ended = untrack_ended
        self.clock = clock
        self.games: dict[int, _Tracked] = {}

    def track(self, game_id: int, meta: Any, seen_results: int) -> None:
        if game_id not in self.games:
            self.games[game_id] = _Tracked(game_id, meta, self.clock(), seen_results)

    def apply(self, ids: list[int], games: list[AutohostGame]) -> list[Event]:
        now = self.clock()
        events: list[Event] = []
        returned: set[int] = set()
        for game in games:
            tracked = self.games.get(game.id)
            if tracked is None:
                continue
            returned.add(game.id)
            tracked.last_seen_at = now
            self._diff(tracked, game, now, events)
        for game_id in ids:
            tracked = self.games.get(game_id)
            if game_id in returned or tracked is None:
                continue
            if now - (tracked.last_seen_at or tracked.added_at) >= self.missing_grace:
                del self.games[game_id]
                events.append(("gone", (game_id, tracked.game)))
        return events

    def _diff(self, t: _Tracked, nxt: AutohostGame, now: float, events: list[Event]) -> None:
        prev = t.game
        t.game = nxt
        events.append(("update", (nxt, prev)))
        if not (prev and prev.room.code) and nxt.room.code:
            t.room_ready_at = now
            events.append(("room_ready", (nxt,)))
        prev_state = prev.match_state if prev else None
        if nxt.match_state is not None and nxt.match_state != prev_state:
            events.append(("state", (nxt, nxt.match_state, prev_state)))
        prev_started = prev.match_started_at if prev else None
        if nxt.match_started_at is not None and nxt.match_started_at != prev_started:
            events.append(("match_start", (nxt,)))
        if prev and nxt.status == "open" and nxt.scores and (nxt.round != prev.round or nxt.scores != prev.scores):
            events.append(("score", (nxt, nxt.round, list(nxt.scores))))
        if nxt.status == "open":
            self._diff_players(t, prev, nxt, now, events)
        for index in range(t.seen_results, len(nxt.results)):
            events.append(("match_result", (nxt, nxt.results[index], index)))
        t.seen_results = max(t.seen_results, len(nxt.results))
        if nxt.status == "ended" and (prev is None or prev.status != "ended"):
            if nxt.room.id == -1 or (t.room_ready_at is None and not nxt.results and nxt.rejection_reason):
                events.append(("rejected", (nxt, nxt.rejection_reason)))
            events.append(("ended", (nxt,)))
            if self.untrack_ended:
                self.games.pop(t.id, None)

    def _diff_players(self, t: _Tracked, prev: Optional[AutohostGame], nxt: AutohostGame, now: float, events: list[Event]) -> None:
        before = {p.user_id: p for p in (prev.players if prev else [])}
        after = {p.user_id: p for p in nxt.players}
        for user_id, player in after.items():
            old = before.get(user_id)
            if old is None:
                if user_id not in t.joins:
                    since = now - t.room_ready_at if t.room_ready_at is not None else None
                    t.joins[user_id] = JoinInfo(now, since)
                events.append(("player_join", (nxt, player, t.joins[user_id])))
                if player.ping < 0:
                    t.offline_since[user_id] = now
                continue
            if old.ping >= 0 and player.ping < 0:
                t.offline_since[user_id] = now
                events.append(("player_disconnect", (nxt, player)))
            elif old.ping < 0 and player.ping >= 0:
                since = t.offline_since.pop(user_id, None)
                events.append(("player_reconnect", (nxt, player, now - since if since is not None else 0.0)))
            if old.team != player.team:
                events.append(("player_team_change", (nxt, player, old.team)))
        for user_id, player in before.items():
            if user_id not in after:
                t.offline_since.pop(user_id, None)
                events.append(("player_leave", (nxt, player)))


class _WatcherBase:
    def __init__(self, interval: float, missing_grace: float, untrack_ended: bool, clock: Callable[[], float] = time.monotonic) -> None:
        self.interval = max(1.0, interval)
        self._engine = _Engine(missing_grace, untrack_ended, clock)
        self._handlers: dict[str, list[Callable[..., Any]]] = {}

    def on(self, event: str, handler: Optional[Callable[..., Any]] = None) -> Any:
        if event not in EVENTS:
            raise ValueError(f"Unknown event {event!r}. Events: {', '.join(sorted(EVENTS))}")

        def register(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._handlers.setdefault(event, []).append(fn)
            return fn

        return register(handler) if handler is not None else register

    def off(self, event: str, handler: Callable[..., Any]) -> None:
        handlers = self._handlers.get(event, [])
        if handler in handlers:
            handlers.remove(handler)

    def track(self, game: Any, *, meta: Any = None, seen_results: int = 0) -> Any:
        game_id = game.id if isinstance(game, AutohostGame) else int(game)
        self._engine.track(game_id, meta, seen_results)
        return self

    def untrack(self, game_id: int) -> bool:
        return self._engine.games.pop(game_id, None) is not None

    @property
    def ids(self) -> list[int]:
        return list(self._engine.games)

    def __len__(self) -> int:
        return len(self._engine.games)

    def latest(self, game_id: int) -> Optional[AutohostGame]:
        tracked = self._engine.games.get(game_id)
        return tracked.game if tracked else None

    def meta(self, game_id: int) -> Any:
        tracked = self._engine.games.get(game_id)
        return tracked.meta if tracked else None

    def join_times(self, game_id: int) -> dict[int, JoinInfo]:
        tracked = self._engine.games.get(game_id)
        return dict(tracked.joins) if tracked else {}

    def room_ready_at(self, game_id: int) -> Optional[float]:
        tracked = self._engine.games.get(game_id)
        return tracked.room_ready_at if tracked else None


class AsyncAutohostWatcher(_WatcherBase):
    def __init__(self, client: AsyncCopsClient, *, interval: float = 5.0, missing_grace: float = 60.0, untrack_ended: bool = True) -> None:
        super().__init__(interval, missing_grace, untrack_ended)
        self._client = client
        self._task: Optional[asyncio.Task[None]] = None
        self._lock: Optional[asyncio.Lock] = None
        self._stopping = False

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _emit(self, event: str, *args: Any) -> None:
        for handler in list(self._handlers.get(event, [])):
            try:
                result = handler(*args)
                if inspect.isawaitable(result):
                    await result
            except Exception as err:
                if event == "handler_error":
                    raise
                await self._emit("handler_error", err, event)

    async def poll_now(self) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            ids = self.ids
            if not ids:
                return
            try:
                games = await self._client.autohost.poll(ids)
            except CopsApiError as err:
                await self._emit("poll_error", err)
                if err.code in FATAL_CODES:
                    self._stopping = True
                return
            except Exception as err:
                await self._emit("poll_error", err)
                return
            for event, args in self._engine.apply(ids, games):
                await self._emit(event, *args)

    async def _loop(self, until_empty: bool) -> None:
        while not self._stopping:
            started = time.monotonic()
            await self.poll_now()
            if self._stopping or (until_empty and not self.ids):
                return
            await asyncio.sleep(max(0.0, self.interval - (time.monotonic() - started)))

    def start(self) -> AsyncAutohostWatcher:
        if not self.running:
            self._stopping = False
            self._task = asyncio.get_running_loop().create_task(self._loop(False))
        return self

    async def run(self) -> None:
        self._stopping = False
        await self._loop(True)

    async def stop(self) -> None:
        self._stopping = True
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def __aenter__(self) -> AsyncAutohostWatcher:
        return self.start()

    async def __aexit__(self, *exc: Any) -> None:
        await self.stop()


class AutohostWatcher(_WatcherBase):
    def __init__(self, client: CopsClient, *, interval: float = 5.0, missing_grace: float = 60.0, untrack_ended: bool = True) -> None:
        super().__init__(interval, missing_grace, untrack_ended)
        self._client = client
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _emit(self, event: str, *args: Any) -> None:
        for handler in list(self._handlers.get(event, [])):
            try:
                handler(*args)
            except Exception as err:
                if event == "handler_error":
                    raise
                self._emit("handler_error", err, event)

    def poll_now(self) -> None:
        with self._lock:
            ids = self.ids
            if not ids:
                return
            try:
                games = self._client.autohost.poll(ids)
            except CopsApiError as err:
                self._emit("poll_error", err)
                if err.code in FATAL_CODES:
                    self._stop.set()
                return
            except Exception as err:
                self._emit("poll_error", err)
                return
            for event, args in self._engine.apply(ids, games):
                self._emit(event, *args)

    def _loop(self, until_empty: bool) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            self.poll_now()
            if self._stop.is_set() or (until_empty and not self.ids):
                return
            self._stop.wait(max(0.0, self.interval - (time.monotonic() - started)))

    def start(self) -> AutohostWatcher:
        if not self.running:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, args=(False,), name="copsapi-watcher", daemon=True)
            self._thread.start()
        return self

    def run(self) -> None:
        self._stop.clear()
        self._loop(True)

    def stop(self, timeout: Optional[float] = 10.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def __enter__(self) -> AutohostWatcher:
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()
