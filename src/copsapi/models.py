from __future__ import annotations

import dataclasses
import sys
import types
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Literal, Optional, TypeVar, Union, cast, get_args, get_origin, get_type_hints

T = TypeVar("T")

_UNION_TYPES: tuple[Any, ...] = (Union, types.UnionType) if sys.version_info >= (3, 10) else (Union,)


@lru_cache(maxsize=None)
def _hints(cls: type) -> dict[str, Any]:
    return get_type_hints(cls)


def _convert(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    origin = get_origin(tp)
    if origin in _UNION_TYPES:
        options = [a for a in get_args(tp) if a is not type(None)]
        return _convert(options[0], value) if len(options) == 1 else value
    if origin is Literal:
        return value
    if origin is list:
        (item,) = get_args(tp) or (Any,)
        return [_convert(item, v) for v in value] if isinstance(value, list) else []
    if origin is dict:
        return value if isinstance(value, dict) else {}
    if isinstance(tp, type) and dataclasses.is_dataclass(tp):
        return from_dict(tp, value) if isinstance(value, dict) else None
    if tp is float and isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    return value


def from_dict(cls: type[T], data: dict[str, Any]) -> T:
    target = cast(Any, cls)
    hints = _hints(target)
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(target):
        if not f.init:
            continue
        if f.name == "raw":
            kwargs["raw"] = data
            continue
        if f.name in data:
            kwargs[f.name] = _convert(hints[f.name], data[f.name])
    return cls(**kwargs)


def _ts(value: Optional[int]) -> Optional[datetime]:
    return datetime.fromtimestamp(value, tz=timezone.utc) if value else None


@dataclass(frozen=True)
class PlayerLevel:
    level: int = 0
    current_xp: int = 0
    next_level_xp: int = 0


@dataclass(frozen=True)
class ProfileBasicInfo:
    user_id: int = 0
    name: str = ""
    user_type: int = 1
    icon_id: int = 0
    player_level: PlayerLevel = field(default_factory=PlayerLevel)
    last_seen_time: str = ""


@dataclass(frozen=True)
class Ban:
    type: int = 0
    reason: int = 0
    days_left: int = 0

    @property
    def permanent(self) -> bool:
        return self.type == 0


@dataclass(frozen=True)
class ClanBasicInfo:
    id: int = 0
    name: str = ""
    tag: str = ""
    emblem_id: int = 0


@dataclass(frozen=True)
class ClanMembership:
    basic_info: ClanBasicInfo = field(default_factory=ClanBasicInfo)
    member_rank: int = 10
    joined: str = ""


@dataclass(frozen=True)
class MatchStats:
    k: int = 0
    d: int = 0
    a: int = 0
    w: int = 0
    l: int = 0


@dataclass(frozen=True)
class SeasonStats:
    season: int = 0
    ranked: MatchStats = field(default_factory=MatchStats)
    casual: MatchStats = field(default_factory=MatchStats)
    custom: MatchStats = field(default_factory=MatchStats)


@dataclass(frozen=True)
class RankedStats:
    placement_matches_left: int = 0
    wins: int = 0
    losses: int = 0
    highest_rank: int = 0
    mmr: int = 0
    global_position: int = 0
    rank: int = 0


@dataclass(frozen=True)
class LeaderboardPosition:
    position: int = 0
    score: int = 0


@dataclass(frozen=True)
class ProfileStats:
    seasonal_stats: list[SeasonStats] = field(default_factory=list)
    ranked: RankedStats = field(default_factory=RankedStats)
    leaderboard_data: LeaderboardPosition = field(default_factory=LeaderboardPosition)


@dataclass(frozen=True)
class Profile:
    basic_info: ProfileBasicInfo = field(default_factory=ProfileBasicInfo)
    account_age: str = ""
    blocked_friend_requests: bool = False
    blocked_clan_requests: bool = False
    party_invite_permissions: int = 0
    ban: Optional[Ban] = None
    stats: ProfileStats = field(default_factory=ProfileStats)
    clan: Optional[ClanMembership] = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def user_id(self) -> int:
        return self.basic_info.user_id

    @property
    def name(self) -> str:
        return self.basic_info.name


@dataclass(frozen=True)
class GameServer:
    id: int
    name: str
    online: bool
    region: Optional[str]


@dataclass(frozen=True)
class MatchHistoryEntry:
    id: str = ""
    game_type: int = 0
    game_mode_id: int = 0
    map_id: int = 0
    team: int = 0
    result: int = 0
    left_match: bool = False
    scores: list[int] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class PartyInfo:
    is_leader: bool = False
    players: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class MatchPlayer:
    user_id: int = 0
    team: int = -1
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    damage_dealt: int = 0
    input_device_flags: int = 0
    left_match: bool = False
    leave_reason: Optional[str] = None
    level: int = 0
    match_presence: float = 0.0
    party_info: Optional[PartyInfo] = None


@dataclass(frozen=True)
class MatchInfo:
    id: str = ""
    game_type: int = 0
    game_mode_id: int = 0
    server_id: int = 0
    map_id: int = 0
    team_factions: list[int] = field(default_factory=list)
    winning_team: int = -1
    win_condition: str = ""
    scores: list[int] = field(default_factory=list)
    started_at: int = 0
    ended_at: int = 0
    players: list[MatchPlayer] = field(default_factory=list)
    replay_id: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def started(self) -> Optional[datetime]:
        return _ts(self.started_at)

    @property
    def ended(self) -> Optional[datetime]:
        return _ts(self.ended_at)


@dataclass(frozen=True)
class WeaponStats:
    weapon_id: int = 0
    name: str = ""
    k: int = 0
    a: int = 0
    h: int = 0

    @property
    def headshot_rate(self) -> float:
        return round(self.h / self.k, 3) if self.k else 0.0


@dataclass(frozen=True)
class LeaderboardEntry:
    position: int = 0
    score: int = 0
    basic_info: ProfileBasicInfo = field(default_factory=ProfileBasicInfo)
    ranked: RankedStats = field(default_factory=RankedStats)
    clan: Optional[ClanMembership] = None


@dataclass(frozen=True)
class LeaderboardPage:
    type: str
    page: int
    rank: Optional[int]
    size: int
    pages: int
    entries: list[LeaderboardEntry]


@dataclass(frozen=True)
class PlayerMatchStats:
    user_id: int = 0
    team: int = -1
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    damage_dealt: int = 0
    input_device_flags: int = 0
    left_match: bool = False
    leave_reason: Optional[str] = None
    ping: int = 0
    user_type: int = 1
    is_owner: bool = False

    @property
    def connected(self) -> bool:
        return self.ping >= 0


@dataclass(frozen=True)
class AutohostRoom:
    id: int = -1
    code: Optional[str] = None
    name: str = ""
    map_id: int = 0
    game_mode_id: int = 0
    has_password: bool = False


@dataclass(frozen=True)
class AutohostResult:
    match_id: Optional[str] = None
    map_id: int = 0
    team_factions: list[int] = field(default_factory=list)
    winning_team: int = -1
    win_condition: str = ""
    scores: list[int] = field(default_factory=list)
    started_at: int = 0
    ended_at: int = 0
    map_variation: int = 0
    rounds_played: int = 0
    players: list[PlayerMatchStats] = field(default_factory=list)


@dataclass(frozen=True)
class AutohostGame:
    id: int = 0
    status: Literal["open", "ended"] = "open"
    created_at: int = 0
    updated_at: int = 0
    ended_at: Optional[int] = None
    pending_expires_at: Optional[int] = None
    server_id: int = 0
    room: AutohostRoom = field(default_factory=AutohostRoom)
    player_count: int = 0
    match_started_at: Optional[int] = None
    match_state: Optional[str] = None
    round: int = 0
    scores: list[int] = field(default_factory=list)
    players: list[PlayerMatchStats] = field(default_factory=list)
    results: list[AutohostResult] = field(default_factory=list)
    replay_id: Optional[str] = None
    rejection_reason: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def open(self) -> bool:
        return self.status == "open"

    @property
    def code(self) -> Optional[str]:
        return self.room.code


@dataclass(frozen=True)
class HostedRoom:
    id: int
    code: str
    password: Optional[str]
    server_id: int
    game: AutohostGame


@dataclass(frozen=True)
class QuotaSnapshot:
    limit: int
    remaining: int
    reset_at: float
    resets_in: float
    reserve: int


@dataclass(frozen=True)
class TokenCheck:
    valid: bool
    autohost: bool
    error: Optional[Exception]
    quota: QuotaSnapshot
