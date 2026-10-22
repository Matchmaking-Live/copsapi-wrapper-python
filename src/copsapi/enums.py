from __future__ import annotations

from enum import Enum, IntEnum, IntFlag


class _StrEnum(str, Enum):
    def __str__(self) -> str:
        return str(self.value)


class UserType(IntEnum):
    SPECTATOR = 0
    USER = 1
    ASSISTANT_MOD = 2
    MODERATOR = 4
    VETERAN_MOD = 8
    DEVELOPER = 64


class BanType(IntEnum):
    PERMANENT = 0
    TEMPORARY = 1


class BanReason(IntEnum):
    UNKNOWN = 0
    FRAUD_ATTEMPT = 1
    HACKING = 2
    GRIEFING = 3
    VERBAL_ABUSE = 4
    IDLE = 5
    SPAM = 6
    REPORT_ABUSE = 7
    ACCOUNT_TRADING = 8
    GLITCHING = 9
    GHOSTING = 10
    PARTYING_WITH_HACKER = 11
    UNDER_INVESTIGATION = 12
    MARKETPLACE_ABUSE = 13


class ClanMemberRank(IntEnum):
    MEMBER = 10
    OFFICER = 20
    CO_LEADER = 30
    LEADER = 40


class PartyInvitePermission(IntEnum):
    ANYBODY = 0
    ONLY_FRIENDS_AND_CLAN_MEMBERS = 1
    NOBODY = 2


class GameType(IntEnum):
    RANKED = 1
    CASUAL = 2


class MatchResult(IntEnum):
    WIN = 1
    LOSS = 2
    DRAW = 3


class InputDeviceFlag(IntFlag):
    KEYBOARD_MOUSE = 1
    TOUCH = 2
    GAMEPAD = 4


class MapId(IntEnum):
    CANALS = 613
    PLAZA = 615
    LEGACY = 617
    GROUNDED = 618
    BUREAU = 619
    BREWERY = 839
    DIVISION = 841
    UPLINK = 1311
    YARD = 1312
    RAID = 1360
    HEAT = 4483
    WAREHOUSE = 6655
    GALLERY = 6670
    PORT = 6677
    PARK = 7201
    PURIFY = 7316
    CARGO = 7554
    ARCTIC = 7584
    BOUT = 8024
    SOAR = 8427
    SHANTY = 8872
    HANGAR = 9310
    VILLAGE = 13410
    IMPASSE = 14066
    OVERHAUL = 15028
    CASTELLO = 15391


class GameModeId(IntEnum):
    DEFUSE = 15773
    ELIMINATION = 15775
    GUNGAME = 15776
    TEAM_DEATHMATCH = 15777
    MANHUNT = 15846
    TOURNAMENT_MODE = 15847
    RUSH = 15860
    DEFEND = 15861
    MANHUNT_Z = 18596
    WINGMAN = 18850


class AccountAge(_StrEnum):
    UNDER_A_WEEK = "1w"
    UNDER_A_MONTH = "1m"
    UNDER_THREE_MONTHS = "3m"
    UNDER_A_YEAR = "1y"
    UNDER_TWO_YEARS = "2y"
    UNDER_THREE_YEARS = "3y"
    UNDER_FOUR_YEARS = "4y"
    FOUR_YEARS_OR_MORE = "5y+"


class WinCondition(_StrEnum):
    TEAM_ELIMINATED = "TeamEliminated"
    TEAM_KILLS = "TeamKills"
    TIME_UP = "TimeUp"
    SURRENDERED = "Surrendered"


class LeaveReason(_StrEnum):
    LEFT = "Left"
    TIMEOUT = "Timeout"
    KICKED = "Kicked"
    BANNED = "Banned"
    PING_LIMIT = "PingLimit"
    AFK = "AFK"


class MatchState(_StrEnum):
    WAITING_FOR_PLAYERS = "WaitingForPlayers"
    STARTING = "Starting"
    FREEZETIME = "Freezetime"
    ON_GOING = "OnGoing"
    BOMB_PLANTED = "BombPlanted"
    WIN = "Win"
    TEAM_FLIP = "TeamFlip"
    GAME_END = "GameEnd"
    CHANGING_MAP = "ChangingMap"


class AutohostCommand(_StrEnum):
    KICK = "kick"
    RESTART = "restart"
    ROOM_OWNER_ADD = "room_owner_add"
    ROOM_OWNER_REMOVE = "room_owner_remove"
    CLOSE = "close"


class LeaderboardType(_StrEnum):
    MMR = "mmr"
    KILLS = "kills"
    DEATHS = "deaths"
    ASSISTS = "assists"
    MATCHES = "matches"
    WINS = "wins"
    LOSSES = "losses"
    XP = "xp"
    MVP = "mvp"


class GameStatus(_StrEnum):
    OPEN = "open"
    ENDED = "ended"


def has_input_device(flags: int, device: InputDeviceFlag) -> bool:
    return bool(flags & device)
