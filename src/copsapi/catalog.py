from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Union

MAPS: dict[int, str] = {
    613: "Canals",
    615: "Plaza",
    617: "Legacy",
    618: "Grounded",
    619: "Bureau",
    839: "Brewery",
    841: "Division",
    1311: "Uplink",
    1312: "Yard",
    1360: "Raid",
    4483: "Heat",
    6655: "Warehouse",
    6670: "Gallery",
    6677: "Port",
    7201: "Park",
    7316: "Purify",
    7554: "Cargo",
    7584: "Arctic",
    8024: "Bout",
    8427: "Soar",
    8872: "Shanty",
    9310: "Hangar",
    13410: "Village",
    14066: "Impasse",
    15028: "Overhaul",
    15391: "Castello",
}


@dataclass(frozen=True)
class GameMode:
    id: int
    key: str
    name: str
    maps: tuple[int, ...]


_ALL = (613, 615, 617, 618, 619, 839, 841, 1311, 1312, 1360, 4483, 6655, 6670, 6677, 7201, 7316, 7554, 7584, 8024, 8427, 8872, 9310, 13410, 14066, 15028, 15391)

GAME_MODES: dict[str, GameMode] = {
    m.key: m
    for m in (
        GameMode(15773, "defuse", "Defuse", (613, 615, 617, 618, 619, 1311, 1312, 1360, 6677, 7201, 7316, 7584, 8024, 8427, 8872, 13410, 15391)),
        GameMode(15775, "elimination", "Elimination", (6655, 14066, 15028)),
        GameMode(15776, "gungame", "Gungame", (839, 841, 1311, 1312, 4483, 6655, 6670, 7201, 7554, 7584, 8024, 9310, 14066, 15028)),
        GameMode(15777, "tdm", "Team Deathmatch", _ALL),
        GameMode(15846, "manhunt", "Manhunt", (7316,)),
        GameMode(15847, "tournament", "Tournament Mode", (613, 615, 617, 618, 619, 1360, 6677, 8427, 13410, 15391)),
        GameMode(15860, "rush", "Rush", _ALL),
        GameMode(15861, "defend", "Defend", (8872,)),
        GameMode(18596, "manhuntz", "Manhunt Z", (7316,)),
        GameMode(18850, "wingman", "Wingman", (613, 615, 617, 619, 1360, 13410, 15391)),
    )
}

_MODE_BY_ID = {m.id: m for m in GAME_MODES.values()}
_MAP_BY_NAME = {name.lower(): map_id for map_id, name in MAPS.items()}
_ALIASES = {"teamdeathmatch": "tdm", "tournamentmode": "tournament"}


def _squash(text: str) -> str:
    return re.sub(r"[\s_-]+", "", text.strip().lower())


def map_id(map_: Union[int, str]) -> Optional[int]:
    if isinstance(map_, int):
        return map_ if map_ in MAPS else None
    text = map_.strip()
    if text.isdigit():
        return map_id(int(text))
    return _MAP_BY_NAME.get(text.lower())


def map_name(id_: int) -> Optional[str]:
    return MAPS.get(id_)


def game_mode(mode: Union[int, str]) -> Optional[GameMode]:
    if isinstance(mode, int):
        return _MODE_BY_ID.get(mode)
    key = _squash(mode)
    if key.isdigit():
        return game_mode(int(key))
    key = _ALIASES.get(key, key)
    for m in GAME_MODES.values():
        if m.key == key or _squash(m.name) == key:
            return m
    return None


def maps_for(mode: Union[int, str]) -> list[int]:
    m = game_mode(mode)
    return list(m.maps) if m else []


def modes_for(map_: Union[int, str]) -> list[GameMode]:
    mid = map_id(map_)
    if mid is None:
        return []
    return [m for m in GAME_MODES.values() if mid in m.maps]


def is_hostable(mode: Union[int, str], map_: Union[int, str]) -> bool:
    m = game_mode(mode)
    mid = map_id(map_)
    return m is not None and mid is not None and mid in m.maps


BAN_REASONS: dict[int, str] = {
    0: "Unknown",
    1: "Fraud attempt",
    2: "Hacking",
    3: "Griefing",
    4: "Verbal abuse",
    5: "Idle",
    6: "Spam",
    7: "Report abuse",
    8: "Account trading",
    9: "Glitching",
    10: "Ghosting",
    11: "Partying with hacker",
    12: "Under investigation",
    13: "Marketplace abuse",
}

USER_TYPES: dict[int, str] = {0: "Spectator", 1: "User", 2: "Assistant mod", 4: "Moderator", 8: "Veteran mod", 64: "Developer"}

ACCOUNT_AGES: dict[str, str] = {
    "1w": "Under a week",
    "1m": "Under a month",
    "3m": "Under 3 months",
    "1y": "Under a year",
    "2y": "1 to 2 years",
    "3y": "2 to 3 years",
    "4y": "3 to 4 years",
    "5y+": "4 years or more",
}

PARTY_INVITE_PERMISSIONS: dict[int, str] = {0: "Anybody", 1: "Only friends and clan members", 2: "Nobody"}

CLAN_RANKS: dict[int, str] = {10: "Member", 20: "Officer", 30: "Co-leader", 40: "Leader"}

GAME_TYPES: dict[str, int] = {"ranked": 1, "casual": 2}

LEADERBOARD_TYPES: tuple[str, ...] = ("mmr", "kills", "deaths", "assists", "matches", "wins", "losses", "xp", "mvp")

MATCH_STATES: tuple[str, ...] = ("WaitingForPlayers", "Starting", "Freezetime", "OnGoing", "BombPlanted", "Win", "TeamFlip", "GameEnd", "ChangingMap")

INPUT_DEVICES: dict[str, int] = {"keyboard_mouse": 1, "touch": 2, "gamepad": 4}

AUTOHOST_COMMANDS: tuple[str, ...] = ("kick", "restart", "room_owner_add", "room_owner_remove", "close")
