from __future__ import annotations

import json
import os
import re
from typing import Any, Iterable, Optional, Sequence, TypeVar, Union

from .catalog import GAME_TYPES, game_mode, is_hostable, map_id, map_name
from .errors import API_CODES, CopsApiError, make_error
from .models import Profile

T = TypeVar("T")

VERSION = "1.1.0"
DEFAULT_BASE_URL = "https://latest.prod.copsapi.criticalforce.fi/api/public/v2"
TOKEN_PATTERN = re.compile(r"^cops_[0-9a-f]{48}$", re.I)
MATCH_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")

AUTOHOST_DENIED = (
    "Your API token does not have the Autohost permission, which hosting games (autohost.create, poll and control) "
    "needs. Ask Critical Force to grant it to your token; every other endpoint works without it."
)

PlayerRef = Union[int, str]


def resolve_token(token: Optional[str], validate: bool) -> str:
    value = (token if token is not None else os.environ.get("COPS_API_TOKEN", "")).strip()
    if not value:
        raise make_error(
            "missing_token",
            'CopsClient needs your own Critical Ops API token: CopsClient("cops_...") or set COPS_API_TOKEN. '
            "Tokens are issued by Critical Force to a Critical Ops account.",
            local=True,
        )
    if validate and not TOKEN_PATTERN.match(value):
        raise make_error(
            "invalid_token",
            'That does not look like a Critical Ops API token: tokens are "cops_" followed by 48 hex digits. '
            "Pass validate_token=False if the format has changed.",
            local=True,
        )
    return value


def resolve_base_url(base_url: Optional[str]) -> str:
    return (base_url or os.environ.get("COPS_API_BASE") or DEFAULT_BASE_URL).rstrip("/")


def build_query(query: Optional[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (query or {}).items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            if value:
                out[key] = ",".join(str(v) for v in value)
        elif isinstance(value, bool):
            out[key] = "true" if value else "false"
        else:
            out[key] = str(value)
    return out


def fallback_code(status: int) -> str:
    if status == 401:
        return "invalid_token"
    if status == 403:
        return "insufficient_permissions"
    if status == 429:
        return "rate_limited"
    if status == 503:
        return "server_unavailable"
    if status >= 500:
        return "internal_error"
    return "bad_request"


def positive(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def parse_json(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def api_error(status: int, body: Any, headers: Any, method: str, path: str) -> CopsApiError:
    detail: dict[str, Any] = body["error"] if isinstance(body, dict) and isinstance(body.get("error"), dict) else {}
    raw_code = detail.get("code")
    code = raw_code if raw_code in API_CODES else fallback_code(status)
    retry_after = positive(headers.get("retry-after")) or positive(detail.get("retry_after"))
    message = detail.get("message") or f"Critical Ops API error {status}"
    return make_error(code, message, status, retry_after, method=method, path=path)


def local_error(code: str, message: str, path: str, method: str = "GET") -> CopsApiError:
    return make_error(code, message, 0, None, method=method, path=path, local=True)


def chunks(items: Sequence[T], size: int) -> list[list[T]]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def ref_key(ref: PlayerRef) -> str:
    return f"profile:id:{ref}" if isinstance(ref, int) else f"profile:name:{ref.strip().lower()}"


def dedupe_refs(players: Iterable[PlayerRef]) -> list[PlayerRef]:
    seen: set[str] = set()
    out: list[PlayerRef] = []
    for raw in players:
        if isinstance(raw, bool) or (isinstance(raw, int) and raw <= 0):
            raise local_error("bad_request", f"Invalid player id {raw!r}.", "/profile")
        ref: PlayerRef = raw if isinstance(raw, int) else str(raw).strip()
        if ref == "":
            continue
        key = ref_key(ref)
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def split_refs(refs: Sequence[PlayerRef]) -> tuple[list[int], list[str]]:
    return [r for r in refs if isinstance(r, int)], [r for r in refs if isinstance(r, str)]


def match_refs(refs: Sequence[PlayerRef], profiles: Sequence[Profile]) -> list[tuple[PlayerRef, Profile]]:
    ids, names = split_refs(refs)
    by_id = {p.basic_info.user_id: p for p in profiles}
    by_name = {p.basic_info.name.lower(): p for p in profiles}
    out: list[tuple[PlayerRef, Profile]] = [(i, by_id[i]) for i in ids if i in by_id]
    unmatched = [p for p in profiles if p.basic_info.user_id not in ids]
    for index, name in enumerate(names):
        hit = by_name.get(name.lower()) or (unmatched[index] if index < len(unmatched) else None)
        if hit is not None:
            out.append((name, hit))
    return out


def order_profiles(refs: Sequence[PlayerRef], found: dict[str, Profile]) -> list[Profile]:
    seen: set[int] = set()
    out: list[Profile] = []
    for ref in refs:
        profile = found.get(ref_key(ref))
        if profile is not None and profile.basic_info.user_id not in seen:
            seen.add(profile.basic_info.user_id)
            out.append(profile)
    return out


def game_type_code(game_type: Union[str, int]) -> int:
    if isinstance(game_type, int):
        if game_type not in (1, 2):
            raise ValueError("game_type must be 1 (ranked) or 2 (casual)")
        return game_type
    if game_type not in GAME_TYPES:
        raise ValueError("game_type must be 'ranked' or 'casual'")
    return GAME_TYPES[game_type]


def check_match_ids(ids: Iterable[str]) -> list[str]:
    out: list[str] = []
    for raw in ids:
        mid = raw.strip().lower()
        if not MATCH_ID_PATTERN.match(mid):
            raise local_error("bad_request", f"Invalid match id {raw!r}: expected 64 hex digits.", "/matches/fetch")
        if mid not in out:
            out.append(mid)
    return out


def check_rank(rank: Optional[int]) -> None:
    if rank is not None and not (isinstance(rank, int) and 0 <= rank <= 9):
        raise local_error("bad_request", f"rank must be 0 to 9, got {rank!r}.", "/leaderboards")


def create_body(server_id: int, map_: Union[int, str], mode: Union[int, str], room_name: str, password: Optional[str], validate: bool) -> dict[str, Any]:
    path = "/autohost/create"
    found_mode = game_mode(mode)
    found_map = map_id(map_)
    mode_id = found_mode.id if found_mode else (mode if isinstance(mode, int) else None)
    map_value = found_map if found_map is not None else (map_ if isinstance(map_, int) else None)
    if mode_id is None:
        raise local_error("bad_request", f"Unknown game mode {mode!r}.", path, "POST")
    if map_value is None:
        raise local_error("bad_request", f"Unknown map {map_!r}.", path, "POST")
    if validate and not is_hostable(mode_id, map_value):
        mode_label = found_mode.name if found_mode else f"Game mode {mode_id}"
        map_label = map_name(map_value) or f"map {map_value}"
        raise local_error(
            "bad_request",
            f"{mode_label} cannot be hosted on {map_label}. Pass validate=False if the API has added it since this release.",
            path,
            "POST",
        )
    if not room_name.strip():
        raise local_error("bad_request", "room_name must not be empty.", path, "POST")
    return {"server_id": server_id, "room_name": room_name, "password": password or "", "map_id": map_value, "game_mode_id": mode_id}


def check_command(command: str, user_id: Optional[int]) -> None:
    if command not in ("kick", "restart", "room_owner_add", "room_owner_remove", "close"):
        raise local_error("bad_request", f"Unknown command {command!r}.", "/autohost/control", "POST")
    if command in ("kick", "room_owner_add", "room_owner_remove") and user_id is None:
        raise local_error("bad_request", f"{command} needs a user id.", "/autohost/control", "POST")
