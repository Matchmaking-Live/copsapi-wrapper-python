from __future__ import annotations

import time

import httpx
import pytest

from conftest import TOKEN, api_error, game, profile, reply, room
from copsapi import (
    AuthenticationError,
    BadRequestError,
    ConnectionFailedError,
    CopsApiError,
    CopsClient,
    GameRejectedError,
    NotFoundError,
    PermissionDeniedError,
    Profile,
    RateLimitError,
    ServiceUnavailableError,
    is_cops_error,
)


class TestTokens:
    def test_requires_the_users_own_token(self, monkeypatch):
        monkeypatch.delenv("COPS_API_TOKEN", raising=False)
        with pytest.raises(AuthenticationError) as err:
            CopsClient()
        assert err.value.code == "missing_token"
        with pytest.raises(AuthenticationError):
            CopsClient("   ")

    def test_reads_the_token_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("COPS_API_TOKEN", TOKEN)
        assert CopsClient().quota.limit == 60

    def test_rejects_tokens_in_the_wrong_format_unless_told_not_to_check(self):
        with pytest.raises(AuthenticationError) as err:
            CopsClient("my-password")
        assert err.value.code == "invalid_token"
        CopsClient("cops_future-format", validate_token=False)

    def test_sends_the_token_as_bearer_or_x_api_key(self, make):
        cops, mock = make(lambda c: reply({}))
        cops.servers.list()
        assert mock.calls[0].headers["authorization"] == f"Bearer {TOKEN}"
        cops, mock = make(lambda c: reply({}), auth_header="x-api-key")
        cops.servers.list()
        assert mock.calls[0].headers["x-api-key"] == TOKEN
        assert "authorization" not in mock.calls[0].headers

    def test_never_shows_the_token_in_repr(self, make):
        cops, _ = make(lambda c: reply({}))
        assert TOKEN not in repr(cops)

    def test_fetches_the_openapi_document_without_the_token(self, make):
        cops, mock = make(lambda c: reply({"openapi": "3.1.0"}))
        assert cops.open_api_spec() == {"openapi": "3.1.0"}
        assert "authorization" not in mock.calls[0].headers


class TestTransport:
    def test_maps_api_errors_to_exception_classes(self, make):
        cases = [
            ("token_revoked", 401, AuthenticationError),
            ("insufficient_permissions", 403, PermissionDeniedError),
            ("user_not_found", 404, NotFoundError),
            ("bad_request", 400, BadRequestError),
            ("api_disabled", 503, ServiceUnavailableError),
        ]
        for code, status, cls in cases:
            cops, _ = make(lambda c, code=code, status=status: api_error(code, status), retries=0)
            with pytest.raises(cls) as err:
                cops.matches.history(1)
            assert err.value.code == code
            assert err.value.status == status
            assert is_cops_error(err.value, code)

    def test_retries_the_plain_text_404_from_the_front_proxy(self, make):
        answers = iter([reply(text="Endpoint Not Found.", status=404), reply(text="Endpoint Not Found.", status=404), reply({"1": {"name": "EU-1", "status": "online"}})])
        cops, mock = make(lambda c: next(answers))
        servers = cops.servers.list()
        assert [(s.id, s.name, s.online, s.region) for s in servers] == [(1, "EU-1", True, "EU")]
        assert len(mock.calls) == 3

    def test_gives_up_on_the_gateway_after_the_configured_retries(self, make):
        cops, mock = make(lambda c: reply(text="<html>bad gateway</html>", status=502), gateway_retries=2)
        with pytest.raises(ServiceUnavailableError) as err:
            cops.servers.list()
        assert err.value.code == "gateway"
        assert len(mock.calls) == 3

    def test_retries_network_errors_on_get_but_never_on_post(self, make):
        answers = iter([httpx.ConnectError("boom"), reply({})])
        cops, mock = make(lambda c: next(answers))
        cops.servers.list()
        assert len(mock.calls) == 2

        def refuse(c):
            raise httpx.ConnectError("boom")

        cops, mock = make(refuse)
        with pytest.raises(ConnectionFailedError):
            cops.autohost.create(server_id=1, map="Canals", mode="tournament", room_name="x")
        assert len(mock.calls) == 1

    def test_reports_timeouts(self, make):
        def slow(c):
            raise httpx.ReadTimeout("slow")

        cops, mock = make(slow, retries=1)
        with pytest.raises(ConnectionFailedError) as err:
            cops.servers.list()
        assert err.value.code == "timeout"
        assert len(mock.calls) == 2

    def test_does_not_retry_api_500s_for_post(self, make):
        cops, mock = make(lambda c: api_error("internal_error", 500))
        with pytest.raises(ServiceUnavailableError):
            cops.autohost.close(5)
        assert len(mock.calls) == 1

    def test_waits_out_a_short_429(self, make, no_sleep):
        answers = iter([reply({"error": {"code": "rate_limited", "message": "slow", "retry_after": 2}}, 429, headers={"retry-after": "2"}), reply({})])
        cops, mock = make(lambda c: next(answers))
        cops.servers.list()
        assert len(mock.calls) == 2
        assert 2 in no_sleep

    def test_raises_on_a_429_longer_than_the_limit(self, make):
        cops, _ = make(lambda c: reply({"error": {"code": "rate_limited", "message": "slow"}}, 429, headers={"retry-after": "40"}), max_rate_limit_wait=5)
        with pytest.raises(RateLimitError) as err:
            cops.servers.list()
        assert err.value.retry_after == 40

    def test_tracks_the_quota_from_headers(self, make):
        reset = int(time.time()) + 30
        cops, _ = make(lambda c: reply({}, headers={"x-ratelimit-limit": "120", "x-ratelimit-remaining": "77", "x-ratelimit-reset": str(reset)}))
        cops.servers.list()
        quota = cops.quota
        assert (quota.limit, quota.remaining, quota.reset_at) == (120, 77, reset)

    def test_keeps_the_reserve_for_autohost_calls(self, make):
        reset = str(int(time.time()) + 50)
        cops, _ = make(
            lambda c: reply({"autohosts": []}, headers={"x-ratelimit-limit": "60", "x-ratelimit-remaining": "5", "x-ratelimit-reset": reset}),
            rate_limit_reserve=5,
            on_quota_exhausted="raise",
        )
        cops.autohost.poll([1])
        with pytest.raises(RateLimitError) as err:
            cops.servers.list()
        assert err.value.local
        assert cops.autohost.poll([1]) == []

    def test_calls_the_hooks(self, make):
        seen: list[str] = []
        answers = iter([reply(text="nope", status=404), reply({})])
        cops, _ = make(
            lambda c: next(answers),
            on_request=lambda i: seen.append(f"request {i['attempt']}"),
            on_response=lambda i: seen.append(f"response {i['status']}"),
            on_retry=lambda i: seen.append(f"retry {i['reason']}"),
        )
        cops.servers.list()
        assert seen == ["request 1", "response 404", "retry gateway", "request 2", "response 200"]


class TestProfiles:
    def test_splits_big_lookups_into_requests_of_20(self, make):
        ids = list(range(1, 46))
        cops, mock = make(lambda c: reply([profile(int(i)) for i in c.query["ids"].split(",")]))
        found = cops.profiles.many(ids)
        assert [p.user_id for p in found] == ids
        assert [len(c.query["ids"].split(",")) for c in mock.calls] == [20, 20, 5]
        assert isinstance(found[0], Profile)
        assert found[0].stats.ranked.mmr == 2400

    def test_mixes_ids_and_usernames(self, make):
        cops, mock = make(lambda c: reply([profile(1), profile(2, "Alice")]))
        found = cops.profiles.many([1, "Alice"])
        assert [p.name for p in found] == ["player1", "Alice"]
        assert mock.calls[0].query == {"ids": "1", "usernames": "Alice"}

    def test_isolates_unknown_players(self, make):
        def handler(c):
            ids = [int(i) for i in c.query["ids"].split(",")]
            return api_error("user_not_found", 404) if 13 in ids else reply([profile(i) for i in ids])

        cops, _ = make(handler)
        assert [p.user_id for p in cops.profiles.many([11, 12, 13, 14])] == [11, 12, 14]
        with pytest.raises(NotFoundError):
            cops.profiles.get(13)
        assert cops.profiles.find(13) is None

    def test_caches_by_id_and_name(self, make):
        cops, mock = make(lambda c: reply([profile(5, "Bob")]))
        cops.profiles.get("Bob")
        cops.profiles.get(5)
        cops.profiles.get("bob")
        assert len(mock.calls) == 1
        cops.profiles.get(5, fresh=True)
        assert len(mock.calls) == 2

    def test_cache_can_be_turned_off(self, make):
        cops, mock = make(lambda c: reply([profile(5)]), cache=False)
        cops.profiles.get(5)
        cops.profiles.get(5)
        assert len(mock.calls) == 2

    def test_rejects_invalid_ids_before_calling(self, make):
        cops, mock = make(lambda c: reply([]))
        with pytest.raises(BadRequestError):
            cops.profiles.many([0])
        assert mock.calls == []

    def test_keeps_unknown_fields_in_raw(self, make):
        data = profile(1)
        data["new_field"] = "hello"
        cops, _ = make(lambda c: reply([data]))
        assert cops.profiles.get(1).raw["new_field"] == "hello"


MID = "a" * 64


class TestMatchesStatsLeaderboards:
    def test_validates_and_caches_matches(self, make):
        cops, mock = make(lambda c: reply({"matches": [{"id": MID, "players": [], "started_at": 100, "ended_at": 200}]}))
        with pytest.raises(BadRequestError):
            cops.matches.get(["nope"])
        match = cops.matches.one(MID)
        cops.matches.one(MID.upper())
        assert len(mock.calls) == 1
        assert match.started.year == 1970

    def test_recent_combines_history_and_scoreboards(self, make):
        def handler(c):
            if c.path == "/matches/player":
                return reply({"matches": [{"id": MID, "game_type": 1}, {"id": "b" * 64, "game_type": 2}]})
            return reply({"matches": [{"id": MID, "players": []}]})

        cops, _ = make(handler)
        recent = cops.matches.recent(1, game_type="ranked")
        assert len(recent) == 1
        assert recent[0][1].id == MID

    def test_weapon_stats(self, make):
        weapons = [{"weapon_id": 1, "name": "AK47", "k": 10, "a": 1, "h": 4}, {"weapon_id": 2, "name": "M4", "k": 20, "a": 0, "h": 5}]
        cops, mock = make(lambda c: reply({"weapons": weapons}))
        top = cops.stats.top_weapons(7, game_type="casual", limit=1)
        assert mock.calls[0].query["game_type"] == "2"
        assert [(w.name, w.headshot_rate) for w in top] == [("M4", 0.25)]

    def test_leaderboard_paging_skips_repeats(self, make):
        pages = {"1": [1, 2], "2": [2, 3], "3": []}

        def handler(c):
            ids = pages.get(c.query["page"], [])
            return reply({"leaderboard_size": 25, "entries": [{"position": i + 1, "score": 100, "basic_info": {"user_id": uid}, "ranked": {}} for i, uid in enumerate(ids)]})

        cops, _ = make(handler)
        assert [e.basic_info.user_id for e in cops.leaderboards.iterate("mmr")] == [1, 2, 3]
        page = cops.leaderboards.page("mmr", page=2)
        assert (page.page, page.pages, page.size) == (2, 3, 25)
        with pytest.raises(BadRequestError):
            cops.leaderboards.page("mmr", rank=12)
        assert len(cops.leaderboards.top("mmr", 2)) == 2


class TestAutohost:
    def test_accepts_names_and_sends_ids(self, make):
        cops, mock = make(lambda c: reply({"autohost": game(9)}, 202))
        created = cops.autohost.create(server_id=3, map="castello", mode="Tournament Mode", room_name="Final", password="pw")
        assert mock.calls[0].body == {"server_id": 3, "room_name": "Final", "password": "pw", "map_id": 15391, "game_mode_id": 15847}
        assert created.id == 9
        assert created.code == "ABC123"

    def test_refuses_combinations_the_api_does_not_host(self, make):
        cops, mock = make(lambda c: reply({"autohost": game(1)}))
        with pytest.raises(BadRequestError) as err:
            cops.autohost.create(server_id=3, map="Heat", mode="tournament", room_name="x")
        assert err.value.local
        assert mock.calls == []
        cops.autohost.create(server_id=3, map=4483, mode=15847, room_name="x", validate=False)
        assert len(mock.calls) == 1

    def test_polls_in_batches_of_50(self, make):
        cops, mock = make(lambda c: reply({"autohosts": [game(int(i)) for i in c.query["ids"].split(",")]}))
        assert len(cops.autohost.poll(list(range(1, 121)))) == 120
        assert [len(c.query["ids"].split(",")) for c in mock.calls] == [50, 50, 20]

    def test_player_commands_need_a_user_id(self, make):
        cops, mock = make(lambda c: reply({"autohost": game(1)}))
        with pytest.raises(BadRequestError):
            cops.autohost.control(1, "kick")
        cops.autohost.kick(1, 55)
        assert mock.calls[0].body == {"id": 1, "command": "kick", "user_id": 55}

    def test_host_waits_for_the_room_and_adds_owners(self, make):
        polls = iter([game(4, room=room(id=-1, code=None)), game(4)])

        def handler(c):
            if c.path == "/autohost/create":
                return reply({"autohost": game(4, room=room(id=-1, code=None))}, 202)
            if c.path == "/autohost/poll":
                return reply({"autohosts": [next(polls)]})
            return reply({"autohost": game(4)})

        cops, mock = make(handler)
        hosted = cops.autohost.host(server_id=3, map="Canals", mode="tournament", room_name="Final", owners=[77], interval=0.5)
        assert (hosted.id, hosted.code) == (4, "ABC123")
        assert len(hosted.password) == 6
        assert mock.calls[-1].body == {"id": 4, "command": "room_owner_add", "user_id": 77}

    def test_reports_a_refused_game(self, make):
        cops, _ = make(lambda c: reply({"autohosts": [game(4, status="ended", room=room(id=-1, code=None), rejection_reason="ServerFull")]}))
        with pytest.raises(GameRejectedError):
            cops.autohost.wait_for_room(4)


class TestAutohostPermission:
    DENIED = staticmethod(lambda: api_error("insufficient_permissions", 403, "Missing permission Autohost"))

    def test_explains_and_stops_calling_hosting_endpoints(self, make):
        cops, mock = make(lambda c: self.DENIED() if c.path.startswith("/autohost") else reply({}))
        with pytest.raises(PermissionDeniedError) as err:
            cops.autohost.create(server_id=1, map="Canals", mode="tournament", room_name="x")
        assert "Autohost permission" in str(err.value)
        assert cops.autohost_permission is False
        with pytest.raises(PermissionDeniedError) as again:
            cops.autohost.poll([1])
        assert again.value.local
        assert len(mock.calls) == 1
        cops.servers.list()
        assert len(mock.calls) == 2

    def test_is_available_checks_once(self, make):
        cops, mock = make(lambda c: self.DENIED())
        assert cops.autohost.is_available() is False
        assert cops.autohost.is_available() is False
        assert len(mock.calls) == 1
        cops, _ = make(lambda c: reply({"autohosts": []}))
        assert cops.autohost.is_available() is True

    def test_verify_token(self, make):
        cops, _ = make(lambda c: self.DENIED() if c.path.startswith("/autohost") else reply({}))
        check = cops.verify_token()
        assert (check.valid, check.autohost, check.error) == (True, False, None)
        cops, _ = make(lambda c: api_error("token_revoked", 401))
        check = cops.verify_token()
        assert (check.valid, check.autohost) == (False, False)
        assert isinstance(check.error, CopsApiError) and check.error.code == "token_revoked"


def test_context_manager_closes_the_http_client(make):
    cops, _ = make(lambda c: reply({}))
    with cops as client:
        client.servers.list()
    assert cops._http.is_closed
