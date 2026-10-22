from __future__ import annotations

import json

from conftest import game, profile, reply
from copsapi import (
    ACCOUNT_AGES,
    AUTOHOST_COMMANDS,
    BAN_REASONS,
    CLAN_RANKS,
    GAME_MODES,
    GAME_TYPES,
    INPUT_DEVICES,
    LEADERBOARD_TYPES,
    MAPS,
    MATCH_STATES,
    PARTY_INVITE_PERMISSIONS,
    USER_TYPES,
    AccountAge,
    AutohostCommand,
    BanReason,
    BanType,
    ClanMemberRank,
    GameModeId,
    GameStatus,
    GameType,
    InputDeviceFlag,
    LeaderboardType,
    LeaveReason,
    MapId,
    MatchResult,
    MatchState,
    PartyInvitePermission,
    Profile,
    UserType,
    WinCondition,
    has_input_device,
)
from copsapi.models import from_dict


def values(enum) -> list:
    return sorted(member.value for member in enum)


def test_constants_cover_exactly_the_catalog_codes():
    assert values(MapId) == sorted(MAPS)
    assert values(GameModeId) == sorted(m.id for m in GAME_MODES.values())
    assert values(BanReason) == sorted(BAN_REASONS)
    assert values(UserType) == sorted(USER_TYPES)
    assert values(ClanMemberRank) == sorted(CLAN_RANKS)
    assert values(PartyInvitePermission) == sorted(PARTY_INVITE_PERMISSIONS)
    assert values(AccountAge) == sorted(ACCOUNT_AGES)
    assert values(GameType) == sorted(GAME_TYPES.values())
    assert values(InputDeviceFlag) == sorted(INPUT_DEVICES.values())
    assert values(LeaderboardType) == sorted(LEADERBOARD_TYPES)
    assert values(MatchState) == sorted(MATCH_STATES)
    assert values(AutohostCommand) == sorted(AUTOHOST_COMMANDS)
    assert values(GameStatus) == ["ended", "open"]
    assert values(BanType) == [0, 1]
    assert values(MatchResult) == [1, 2, 3]


def test_map_constant_names_match_map_names():
    for member in MapId:
        assert MAPS[member.value].upper() == member.name


def test_constants_compare_equal_to_api_values():
    data = profile(1)
    data["ban"] = {"type": 1, "reason": 2, "days_left": 3}
    p = from_dict(Profile, data)
    assert p.ban.reason == BanReason.HACKING
    assert p.ban.type == BanType.TEMPORARY
    assert p.basic_info.user_type == UserType.USER
    assert BanReason(p.ban.reason) is BanReason.HACKING
    assert "TimeUp" == WinCondition.TIME_UP
    assert LeaveReason.AFK == "AFK"
    assert str(LeaderboardType.KILLS) == "kills"
    assert f"{AutohostCommand.KICK}" == "kick"


def test_input_device_flags_decode_the_bitmask():
    flags = InputDeviceFlag(6)
    assert InputDeviceFlag.TOUCH in flags and InputDeviceFlag.GAMEPAD in flags
    assert InputDeviceFlag.KEYBOARD_MOUSE not in flags
    assert has_input_device(5, InputDeviceFlag.GAMEPAD)
    assert not has_input_device(5, InputDeviceFlag.TOUCH)


def test_constants_serialise_as_plain_values():
    assert json.loads(json.dumps({"map": MapId.CASTELLO, "command": AutohostCommand.KICK})) == {"map": 15391, "command": "kick"}


def test_constants_can_be_passed_to_client_methods(make):
    def handler(c):
        if c.path == "/leaderboards":
            return reply({"entries": [], "leaderboard_size": 0})
        if c.path == "/stats/weapons":
            return reply({"weapons": []})
        return reply({"autohost": game(1)}, 202)

    cops, mock = make(handler)
    cops.autohost.create(server_id=1, map=MapId.CASTELLO, mode=GameModeId.TOURNAMENT_MODE, room_name="x")
    cops.autohost.control(1, AutohostCommand.KICK, 5)
    cops.leaderboards.page(LeaderboardType.KILLS)
    cops.stats.weapons(7, GameType.CASUAL)
    assert mock.calls[0].body == {"server_id": 1, "room_name": "x", "password": "", "map_id": 15391, "game_mode_id": 15847}
    assert mock.calls[1].body == {"id": 1, "command": "kick", "user_id": 5}
    assert mock.calls[2].query["type"] == "kills"
    assert mock.calls[3].query["game_type"] == "2"


def test_constants_become_plain_values_in_requests_on_every_python_version():
    from copsapi._core import build_query, game_type_code

    assert build_query({"type": LeaderboardType.KILLS, "game_type": GameType.CASUAL, "ids": [MapId.CANALS, 5], "rank": None}) == {"type": "kills", "game_type": "2", "ids": "613,5"}
    assert type(game_type_code(GameType.RANKED)) is int
