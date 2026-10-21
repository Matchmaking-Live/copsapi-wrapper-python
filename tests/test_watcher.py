from __future__ import annotations

import pytest

from conftest import api_error, game, player, reply, result, room
from copsapi import AutohostGame
from copsapi.models import from_dict
from copsapi.watcher import _Engine


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def g(**kwargs) -> AutohostGame:
    return from_dict(AutohostGame, game(1, **kwargs))


def names(events) -> list[str]:
    return [name for name, _ in events if name != "update"]


def test_room_ready_and_join_times():
    clock = Clock()
    engine = _Engine(60, True, clock)
    engine.track(1, None, 0)
    engine.apply([1], [g(room=room(id=-1, code=None))])
    assert "room_ready" in names(engine.apply([1], [g()]))
    clock.now += 90
    events = engine.apply([1], [g(players=[player(10)])])
    join = next(args for name, args in events if name == "player_join")
    assert join[2].since_room_ready == 90
    assert names(engine.apply([1], [g(players=[])])) == ["player_leave"]


def test_disconnects_reconnects_and_team_changes():
    clock = Clock()
    engine = _Engine(60, True, clock)
    engine.track(1, None, 0)
    engine.apply([1], [g(players=[player(10)])])
    assert names(engine.apply([1], [g(players=[player(10, ping=-1)])])) == ["player_disconnect"]
    clock.now += 12
    events = engine.apply([1], [g(players=[player(10, ping=30, team=1)])])
    assert names(events) == ["player_reconnect", "player_team_change"]
    assert events[1][1][2] == 12


def test_state_score_and_results_once():
    engine = _Engine(60, True, Clock())
    engine.track(1, None, 0)
    seen = names(engine.apply([1], [g()]))
    seen += names(engine.apply([1], [g(match_state="OnGoing", round=2, scores=[1, 0])]))
    seen += names(engine.apply([1], [g(match_state="GameEnd", round=10, scores=[7, 3], results=[result()])]))
    seen += names(engine.apply([1], [g(match_state="GameEnd", round=10, scores=[7, 3], results=[result()])]))
    assert seen == ["room_ready", "state", "state", "score", "state", "score", "match_result"]


def test_resume_skips_handled_results():
    engine = _Engine(60, True, Clock())
    engine.track(1, None, 1)
    events = engine.apply([1], [g(results=[result(), result()])])
    assert [args[2] for name, args in events if name == "match_result"] == [1]


def test_rejected_games_end_and_are_untracked():
    engine = _Engine(60, True, Clock())
    engine.track(1, None, 0)
    events = engine.apply([1], [g(status="ended", match_state=None, room=room(id=-1, code=None), rejection_reason="ServerFull")])
    assert names(events) == ["rejected", "ended"]
    assert engine.games == {}


def test_gone_only_after_grace():
    clock = Clock()
    engine = _Engine(10, True, clock)
    engine.track(1, None, 0)
    assert engine.apply([1], []) == []
    clock.now += 11
    assert names(engine.apply([1], [])) == ["gone"]
    assert engine.games == {}


def test_sync_watcher_run_and_handlers(make):
    states = iter([game(1, players=[player(10)]), game(1, players=[]), game(1, status="ended", players=[])])
    cops, _ = make(lambda c: reply({"autohosts": [next(states)]}))
    watcher = cops.autohost.watch(interval=1)
    watcher.interval = 0.01
    events: list[str] = []

    @watcher.on("player_join")
    def joined(game_, p, join):
        events.append(f"join {p.user_id}")

    watcher.on("player_leave", lambda game_, p: events.append(f"leave {p.user_id}"))
    watcher.on("ended", lambda game_: events.append("ended"))
    watcher.track(1, meta={"scrim": 1})
    assert watcher.meta(1) == {"scrim": 1}
    watcher.run()
    assert events == ["join 10", "leave 10", "ended"]


def test_sync_watcher_reports_handler_errors(make):
    cops, _ = make(lambda c: reply({"autohosts": [game(1)]}))
    watcher = cops.autohost.watch()
    errors = []
    watcher.on("room_ready", lambda game_: 1 / 0)
    watcher.on("handler_error", lambda err, event: errors.append((type(err).__name__, event)))
    watcher.track(1)
    watcher.poll_now()
    assert errors == [("ZeroDivisionError", "room_ready")]


def test_sync_watcher_thread_stops_on_permission_error(make):
    cops, _ = make(lambda c: api_error("insufficient_permissions", 403))
    watcher = cops.autohost.watch()
    errors = []
    watcher.on("poll_error", errors.append)
    watcher.track(1).start()
    watcher._thread.join(5)
    assert not watcher.running
    assert errors and errors[0].code == "insufficient_permissions"


def test_unknown_events_are_rejected(make):
    cops, _ = make(lambda c: reply({}))
    with pytest.raises(ValueError):
        cops.autohost.watch().on("player_joined", print)
