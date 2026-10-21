from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Any, Generic, Optional, TypeVar, Union

from .catalog import ACCOUNT_AGES, BAN_REASONS, INPUT_DEVICES, map_name
from .models import AutohostResult, Ban, MatchInfo, MatchPlayer, MatchStats, PlayerMatchStats, Profile


def input_devices(flags: int) -> list[str]:
    return [name for name, bit in INPUT_DEVICES.items() if flags & bit]


def ban_reason(ban: Optional[Ban]) -> Optional[str]:
    if ban is None:
        return None
    return BAN_REASONS.get(ban.reason, f"Reason {ban.reason}")


def describe_ban(ban: Optional[Ban]) -> Optional[str]:
    if ban is None:
        return None
    reason = ban_reason(ban)
    if ban.type == 0:
        return f"Permanently banned ({reason})"
    if ban.days_left == 0:
        return f"Banned with no end date ({reason})"
    return f"Banned for {ban.days_left} more day{'' if ban.days_left == 1 else 's'} ({reason})"


def account_age_label(profile: Profile) -> str:
    return ACCOUNT_AGES.get(profile.account_age, profile.account_age)


def is_new_account(profile: Profile) -> bool:
    return profile.account_age in ("1w", "1m")


def is_staff(user_type: int) -> bool:
    return user_type >= 2


def kd(kills: int, deaths: int, digits: int = 2) -> float:
    return round(kills if deaths == 0 else kills / deaths, digits)


@dataclass(frozen=True)
class Totals:
    kills: int
    deaths: int
    assists: int
    wins: int
    losses: int
    matches: int
    kd: float
    win_rate: float


_SCOPES = ("ranked", "casual", "custom")


def _totals(rows: list[MatchStats]) -> Totals:
    k = sum(r.k for r in rows)
    d = sum(r.d for r in rows)
    a = sum(r.a for r in rows)
    w = sum(r.w for r in rows)
    l_ = sum(r.l for r in rows)
    matches = w + l_
    return Totals(k, d, a, w, l_, matches, kd(k, d), round(w / matches, 3) if matches else 0.0)


def _pick(scope: str) -> tuple[str, ...]:
    if scope == "all":
        return _SCOPES
    if scope not in _SCOPES:
        raise ValueError("scope must be 'ranked', 'casual', 'custom' or 'all'")
    return (scope,)


def career_totals(profile: Profile, scope: str = "all") -> Totals:
    keys = _pick(scope)
    return _totals([getattr(season, key) for season in profile.stats.seasonal_stats for key in keys])


def season_totals(profile: Profile, season: Optional[int] = None, scope: str = "all") -> Optional[Totals]:
    seasons = profile.stats.seasonal_stats
    if not seasons:
        return None
    entry = seasons[-1] if season is None else next((s for s in seasons if s.season == season), None)
    if entry is None:
        return None
    return _totals([getattr(entry, key) for key in _pick(scope)])


P = TypeVar("P", PlayerMatchStats, MatchPlayer)


@dataclass(frozen=True)
class TeamSummary(Generic[P]):
    team: int
    score: int
    faction: Optional[int]
    won: bool
    players: list[P]


@dataclass(frozen=True)
class ResultSummary(Generic[P]):
    map: Optional[str]
    winning_team: Optional[int]
    draw: bool
    win_condition: str
    duration: int
    teams: list[TeamSummary[P]]
    top_fragger: Optional[P]
    leavers: list[P]


def summarize_result(result: Union[AutohostResult, MatchInfo]) -> ResultSummary:
    players: list[Any] = list(result.players)
    winner = result.winning_team if result.winning_team >= 0 else None
    team_count = max([len(result.scores), *(p.team + 1 for p in players), 0])

    def order(p):
        return (-p.kills, p.deaths, -p.damage_dealt)

    teams = [
        TeamSummary(
            team=t,
            score=result.scores[t] if t < len(result.scores) else 0,
            faction=result.team_factions[t] if t < len(result.team_factions) else None,
            won=winner == t,
            players=sorted((p for p in players if p.team == t), key=order),
        )
        for t in range(team_count)
    ]
    ranked = sorted((p for p in players if p.team >= 0), key=order)
    return ResultSummary(
        map=map_name(result.map_id),
        winning_team=winner,
        draw=winner is None,
        win_condition=result.win_condition,
        duration=max(0, result.ended_at - result.started_at),
        teams=teams,
        top_fragger=ranked[0] if ranked else None,
        leavers=[p for p in players if p.left_match],
    )


PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def random_password(length: int = 6, alphabet: str = PASSWORD_ALPHABET) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(length))


_REGIONS: list[tuple[str, re.Pattern[str]]] = [
    ("EU", re.compile(r"^(eu\b|eu-|europe|de-|frankfurt|amsterdam|london|paris|stockholm|warsaw|madrid|finland|helsinki)", re.I)),
    ("NA", re.compile(r"^(na\b|na-|us\b|us-|usa|north america|america|new york|chicago|dallas|seattle|los angeles|virginia|oregon|canada)", re.I)),
    ("SA", re.compile(r"^(sa\b|sa-|br\b|br-|brazil|south america|sao paulo|são paulo|santiago|buenos aires)", re.I)),
    ("AS", re.compile(r"^(as\b|as-|asia|sg\b|sg-|singapore|jp\b|jp-|japan|tokyo|hk\b|hong kong|kr\b|seoul|in\b|india|mumbai|sea\b)", re.I)),
    ("OC", re.compile(r"^(oc\b|oc-|oceania|au\b|au-|australia|sydney)", re.I)),
    ("ME", re.compile(r"^(me\b|me-|middle east|dubai|bahrain)", re.I)),
    ("AF", re.compile(r"^(af\b|af-|africa|johannesburg)", re.I)),
]


def region_of(server_name: str) -> Optional[str]:
    name = server_name.strip()
    for region, pattern in _REGIONS:
        if pattern.search(name):
            return region
    return None
