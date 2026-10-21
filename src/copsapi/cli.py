from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from typing import Any, Optional, Sequence

from ._core import VERSION
from ._sync_client import CopsClient
from .catalog import AUTOHOST_COMMANDS, GAME_MODES, LEADERBOARD_TYPES, MAPS, map_name
from .errors import CopsApiError
from .helpers import career_totals, describe_ban, input_devices, summarize_result


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in dataclasses.fields(value) if f.name != "raw"}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, BaseException):
        return {"code": getattr(value, "code", None), "message": str(value)}
    return value


def _print_json(value: Any) -> None:
    print(json.dumps(_jsonable(value), indent=2, ensure_ascii=False))


def _ref(text: str) -> Any:
    return int(text) if text.isdigit() else text


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="copsapi", description=f"copsapi {VERSION}: the Critical Ops Public API v2 from the command line")
    parser.add_argument("--token", help="your API token (default: COPS_API_TOKEN)")
    parser.add_argument("--base", help="API base URL (default: COPS_API_BASE or the production API)")
    parser.add_argument("--json", action="store_true", help="print raw JSON")
    parser.add_argument("--version", action="version", version=f"copsapi {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("token", help="check your token and whether it can host games")
    p = sub.add_parser("profile", help="player profiles")
    p.add_argument("players", nargs="+", help="user ids or usernames")
    sub.add_parser("servers", help="game servers and their status")
    p = sub.add_parser("history", help="a player's recent matches")
    p.add_argument("user_id", type=int)
    p = sub.add_parser("match", help="full scoreboards of matches")
    p.add_argument("match_ids", nargs="+")
    p = sub.add_parser("weapons", help="a player's weapon totals")
    p.add_argument("user_id", type=int)
    p.add_argument("game_type", nargs="?", default="ranked", choices=["ranked", "casual"])
    p = sub.add_parser("leaderboard", help="a leaderboard page")
    p.add_argument("type", nargs="?", default="mmr", choices=LEADERBOARD_TYPES)
    p.add_argument("page", nargs="?", type=int, default=1)
    p.add_argument("--rank", type=int, choices=range(10), metavar="0-9")
    p = sub.add_parser("host", help="host a custom game and wait for its room code")
    p.add_argument("--server", type=int, required=True)
    p.add_argument("--map", required=True)
    p.add_argument("--mode", required=True)
    p.add_argument("--name", default="Custom game")
    p.add_argument("--password")
    p.add_argument("--no-password", action="store_true")
    p.add_argument("--owner", type=int, action="append", default=[])
    p = sub.add_parser("poll", help="hosted games")
    p.add_argument("game_ids", nargs="+", type=int)
    p = sub.add_parser("control", help="send a command to a hosted game")
    p.add_argument("game_id", type=int)
    p.add_argument("action", choices=AUTOHOST_COMMANDS)
    p.add_argument("user_id", nargs="?", type=int)
    p = sub.add_parser("watch", help="follow hosted games live")
    p.add_argument("game_ids", nargs="+", type=int)
    sub.add_parser("catalog", help="hostable game modes and maps")
    sub.add_parser("quota", help="requests left this minute")
    return parser


def _run(args: argparse.Namespace) -> None:
    if args.command == "catalog":
        if args.json:
            _print_json({"maps": MAPS, "game_modes": {k: dataclasses.asdict(m) for k, m in GAME_MODES.items()}})
            return
        for mode in GAME_MODES.values():
            print(f"{mode.name} ({mode.key}, {mode.id}): {', '.join(map_name(m) or str(m) for m in mode.maps)}")
        return

    with CopsClient(args.token, base_url=args.base) as cops:
        if args.command == "token":
            check = cops.verify_token()
            if args.json:
                _print_json(check)
            elif not check.valid:
                print(f"Token rejected: {check.error}")
            else:
                can = "yes, you can host games" if check.autohost else "no, hosting commands will not work"
                print(f"Token valid. Autohost permission: {can}. Requests left this minute: {check.quota.remaining}.")
        elif args.command == "profile":
            refs = [_ref(p) for p in args.players]
            profiles = cops.profiles.many(refs)
            if args.json:
                _print_json(profiles)
                return
            for p in profiles:
                totals = career_totals(p)
                ranked = p.stats.ranked
                clan = f" [{p.clan.basic_info.tag}]" if p.clan else ""
                print(f"{p.name} ({p.user_id}){clan}")
                ban = f", {describe_ban(p.ban)}" if p.ban else ""
                print(f"  Level {p.basic_info.player_level.level}, account {p.account_age}{ban}")
                placements = f", {ranked.placement_matches_left} placements left" if ranked.placement_matches_left else ""
                print(f"  Ranked: rank {ranked.rank}, {ranked.mmr} MMR, {ranked.wins}W {ranked.losses}L{placements}")
                print(f"  Career: {totals.kills} kills, K/D {totals.kd}, {totals.matches} matches, {round(totals.win_rate * 100)}% won")
            if len(profiles) < len(refs):
                print(f"{len(refs) - len(profiles)} player(s) not found.")
        elif args.command == "servers":
            servers = cops.servers.list()
            if args.json:
                _print_json(servers)
                return
            for s in servers:
                print(f"{s.id:>5}  {'online ' if s.online else 'offline'}  {s.name}{f'  ({s.region})' if s.region else ''}")
        elif args.command == "history":
            history = cops.matches.history(args.user_id)
            if args.json:
                _print_json(history)
                return
            for h in history:
                result = {1: "W", 2: "L", 3: "D"}.get(h.result, "?")
                kind = "ranked" if h.game_type == 1 else "casual"
                left = "  (left)" if h.left_match else ""
                print(f"{result}  {kind}  {str(map_name(h.map_id) or h.map_id):<10} {'-'.join(map(str, h.scores))}{left}  {h.id}")
        elif args.command == "match":
            matches = cops.matches.get(args.match_ids)
            if args.json:
                _print_json(matches)
                return
            for m in matches:
                summary = summarize_result(m)
                outcome = "draw" if summary.draw else f"team {summary.winning_team} won"
                print(f"{summary.map or m.map_id}: {'-'.join(map(str, m.scores))}, {outcome} by {summary.win_condition} in {round(summary.duration / 60)} min")
                for team in summary.teams:
                    print(f"  Team {team.team}{' (won)' if team.won else ''}")
                    for p in team.players:
                        left = f"  left: {p.leave_reason}" if p.left_match else ""
                        print(f"    {p.user_id:<10} {p.kills}/{p.deaths}/{p.assists}  {p.damage_dealt} dmg  {'+'.join(input_devices(p.input_device_flags))}{left}")
        elif args.command == "weapons":
            weapons = cops.stats.weapons(args.user_id, args.game_type)
            if args.json:
                _print_json(weapons)
                return
            for w in sorted(weapons, key=lambda w: w.k, reverse=True):
                print(f"{w.name:<16} {w.k:>7} kills  {w.h:>7} headshots  {w.a:>6} assists")
        elif args.command == "leaderboard":
            page = cops.leaderboards.page(args.type, page=args.page, rank=args.rank)
            if args.json:
                _print_json(page)
                return
            print(f"{page.type} leaderboard, page {page.page} of {page.pages} ({page.size} players)")
            for e in page.entries:
                clan = f" [{e.clan.basic_info.tag}]" if e.clan else ""
                print(f"{e.position:>6}  {e.score:>8}  {e.basic_info.name}{clan}")
        elif args.command == "host":
            password: Any = False if args.no_password else args.password
            room = cops.autohost.host(
                server_id=args.server,
                map=_ref(args.map),
                mode=_ref(args.mode),
                room_name=args.name,
                password=password,
                owners=args.owner,
            )
            if args.json:
                _print_json(room)
                return
            pw = f", password: {room.password}" if room.password else ""
            print(f"Game {room.id} is up. Room code: {room.code}{pw}")
        elif args.command == "poll":
            _print_json(cops.autohost.poll(args.game_ids))
        elif args.command == "control":
            game = cops.autohost.control(args.game_id, args.action, args.user_id)
            if args.json:
                _print_json(game)
            else:
                print(f"Sent {args.action} to game {game.id}.")
        elif args.command == "watch":
            _watch(cops, args.game_ids)
        elif args.command == "quota":
            cops.servers.list(fresh=True)
            _print_json(cops.quota)


def _watch(cops: CopsClient, game_ids: Sequence[int]) -> None:
    watcher = cops.autohost.watch()
    for game_id in game_ids:
        watcher.track(game_id)

    def log(game_id: int, text: str) -> None:
        print(f"{time.strftime('%H:%M:%S')}  #{game_id}  {text}", flush=True)

    watcher.on("room_ready", lambda g: log(g.id, f"room ready, code {g.room.code}"))
    watcher.on("state", lambda g, s, _prev: log(g.id, f"state {s}"))
    watcher.on("score", lambda g, rnd, scores: log(g.id, f"round {rnd}, {'-'.join(map(str, scores))}"))
    watcher.on(
        "player_join",
        lambda g, p, j: log(g.id, f"{p.user_id} joined" + (f" after {round(j.since_room_ready)}s" if j.since_room_ready is not None else "")),
    )
    watcher.on("player_leave", lambda g, p: log(g.id, f"{p.user_id} left"))
    watcher.on("player_disconnect", lambda g, p: log(g.id, f"{p.user_id} disconnected"))
    watcher.on("player_reconnect", lambda g, p, secs: log(g.id, f"{p.user_id} reconnected after {round(secs)}s"))
    watcher.on(
        "match_result",
        lambda g, r, _i: log(g.id, f"match over on {map_name(r.map_id) or r.map_id}: {'-'.join(map(str, r.scores))}, winner team {r.winning_team}"),
    )
    watcher.on("rejected", lambda g, reason: log(g.id, f"refused by the game server: {reason or 'no reason given'}"))
    watcher.on("ended", lambda g: log(g.id, "ended"))
    watcher.on("gone", lambda game_id, _last: log(game_id, "gone"))
    watcher.on("poll_error", lambda err: print(f"{time.strftime('%H:%M:%S')}  poll failed: {err}", file=sys.stderr, flush=True))
    try:
        watcher.run()
    except KeyboardInterrupt:
        watcher.stop()


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _run(args)
    except CopsApiError as err:
        status = f", HTTP {err.status}" if err.status else ""
        print(f"Error ({err.code}{status}): {err}", file=sys.stderr)
        return 1
    except ValueError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
