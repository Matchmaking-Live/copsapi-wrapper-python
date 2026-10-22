# copsapi-wrapper (Python)

A typed, quota-aware Python client for the [Critical Ops Public API v2](https://criticalopsgame.com/api/), with both synchronous and `asyncio` clients.

```sh
pip install copsapi-wrapper
```

```python
from copsapi import CopsClient

with CopsClient("cops_your_token_here") as cops:
    player = cops.profiles.get("SomePlayer")
    print(player.name, player.stats.ranked.mmr)
```

It covers every endpoint in the API: player profiles, leaderboards, match history, weapon stats, server status, and hosting custom games (Autohost). It also handles the parts you'd otherwise write yourself:

- **Sync and async.** `CopsClient` and `AsyncCopsClient` have the same methods and behave the same way.
- **Typed models.** Responses come back as frozen dataclasses that match the official OpenAPI spec field for field. Fields the API adds later are kept in `.raw`. The package ships `py.typed` for type checkers.
- **Quota management.** The client reads the `X-RateLimit-*` headers and waits for the next minute instead of hitting `429`. It can also keep a reserve of requests for hosting traffic.
- **Safe retries.** Network errors, timeouts and the API's front proxy answering a plain-text `404 Endpoint Not Found.` are retried. `POST` requests are never retried after a failure that could mean the API already acted, so a game is never hosted twice.
- **Batching.** Profile lookups are split into requests of 20, match lookups into requests of 20, and game polling into requests of 50.
- **Unknown players don't break a batch.** The API fails a whole profile request when one player doesn't exist. `profiles.many()` narrows down the missing players and returns everyone else.
- **Caching.** Results are cached in memory, or in your own store such as Redis. The async client also combines identical requests made at the same time into one.
- **An Autohost toolkit.** Host a room and get its code in one call. A live watcher reports joins, leaves, disconnects, score changes, match results and the room ending.
- **A game catalog.** Every hostable game mode and map is included, with name lookup and validation before the request is sent.
- **A CLI.** The `copsapi` command does quick lookups, and hosts and watches rooms from a terminal.

It needs Python 3.10 or newer, and its only dependency is [httpx](https://www.python-httpx.org/). A [JavaScript/TypeScript version](https://www.npmjs.com/package/copsapi-wrapper) is also available.

## Contents

- [Your token](#your-token)
- [Sync and async](#sync-and-async)
- [Client options](#client-options)
- [Profiles](#profiles)
- [Servers](#servers)
- [Match history](#match-history)
- [Weapon stats](#weapon-stats)
- [Leaderboards](#leaderboards)
- [Hosting games (Autohost)](#hosting-games-autohost)
- [Watching hosted games](#watching-hosted-games)
- [Rate limits and the quota](#rate-limits-and-the-quota)
- [Errors](#errors)
- [Caching](#caching)
- [Game catalog](#game-catalog)
- [Helpers](#helpers)
- [Command line](#command-line)
- [Models](#models)
- [Development](#development)

## Your token

You need your own API token, issued by Critical Force to your Critical Ops account. This package doesn't include a token and never shares one. Tokens look like `cops_` followed by 48 hex digits.

What a token can do depends on its permissions:

| Endpoints | Needs |
| --- | --- |
| Profiles, servers, match history, weapon stats, leaderboards | Any valid token |
| Autohost (`create`, `poll`, `control`, `host`, the watcher) | A token with the `Autohost` permission (Developer Issued) |

There are three ways to pass the token:

```python
cops = CopsClient("cops_your_token_here")
cops = CopsClient(os.environ["MY_COPS_TOKEN"], timeout=5)
cops = CopsClient()
```

The last form reads `COPS_API_TOKEN` from the environment.

- The constructor raises `AuthenticationError` with code `missing_token` if there is no token.
- It raises `invalid_token` if the token isn't in the `cops_` + 48 hex format. Pass `validate_token=False` if Critical Force changes the format.

A token acts on behalf of the account it was issued to, so keep it on a server and out of your repository.

### Check your token and its permissions

```python
check = cops.verify_token()
can_host = cops.autohost.is_available()
```

- `verify_token` returns `TokenCheck(valid, autohost, error, quota)`.
- `is_available` returns `True` or `False`. The answer is remembered, so later calls are free.

You can also run `copsapi token` from the command line.

If your token lacks `Autohost`, hosting calls raise `PermissionDeniedError` with a message saying which permission is missing. After the first refusal, the client remembers the answer, and further hosting calls fail at once without spending quota. A running watcher stops by itself. Every other endpoint keeps working.

## Sync and async

```python
from copsapi import CopsClient, AsyncCopsClient

with CopsClient() as cops:
    servers = cops.servers.online()

async with AsyncCopsClient() as cops:
    servers = await cops.servers.online()
    async for entry in cops.leaderboards.iterate("kills", max_pages=3):
        print(entry.position, entry.basic_info.name)
```

Both clients have the same methods. Every method of the async client is awaited, and its `iterate()` is an async generator.

Use the client as a context manager, or call `close()` (`await aclose()` for the async client), so the HTTP connections are released.

## Client options

| Option | Default | Description |
| --- | --- | --- |
| `token` | `COPS_API_TOKEN` | Your own API token. Required. It can also be the first positional argument. |
| `validate_token` | `True` | Check the token format up front. |
| `base_url` | `COPS_API_BASE`, or `https://latest.prod.copsapi.criticalforce.fi/api/public/v2` | The API base URL. |
| `timeout` | `10.0` | Seconds allowed for each attempt. |
| `retries` | `2` | Retries for network errors, timeouts and `500`/`503` on `GET` requests. |
| `gateway_retries` | `5` | Retries when the front proxy answers a non-JSON `404`/`5xx` page. |
| `max_rate_limit_wait` | `15.0` | On a `429`, wait and retry if `Retry-After` is at most this long, otherwise raise. |
| `rate_limit` | `60` | Assumed requests per minute until the API reports the real number. |
| `rate_limit_reserve` | `0` | Requests per minute kept back for high-priority calls (all Autohost calls). |
| `on_quota_exhausted` | `"wait"` | `"wait"` for the next minute, or `"raise"` a local `RateLimitError`. |
| `max_quota_wait` | `65.0` | Longest time to wait for quota before raising. |
| `max_concurrent` | `8` | Requests in flight at once (async client). |
| `dedupe` | `True` | Combine identical `GET` requests made at the same time (async client). |
| `cache` | `True` | `True` uses an in-memory cache, `False` turns caching off, and any [store](#caching) uses that store. |
| `cache_ttls` | see [Caching](#caching) | Override TTLs per kind of data, in seconds. |
| `max_players_per_request` | `20` | Players per `/profile` request. Raise it only if Critical Force raised your token's limit. |
| `auth_header` | `"bearer"` | `"x-api-key"` sends the token as `X-Api-Key` instead. |
| `user_agent` | `copsapi-wrapper-python/<version>` | `None` sends no `User-Agent` header. |
| `http_client` | none | Your own `httpx.Client` or `httpx.AsyncClient`, for proxies or custom TLS. |
| `transport` | none | An `httpx` transport, such as `httpx.MockTransport` in tests. |
| `on_request`, `on_response`, `on_retry` | none | Callbacks that receive a dict about each request, for logging and metrics. |

```python
cops = CopsClient(
    rate_limit_reserve=15,
    on_retry=lambda info: log.warning("retrying %s (%s)", info["path"], info["reason"]),
    on_response=lambda info: metrics.observe(info["path"], info["status"], info["duration"]),
)
```

Every read method accepts `fresh=True` to skip the cache.

## Profiles

An `int` is a user id, and a `str` is a username.

```python
one = cops.profiles.get(123456)
maybe = cops.profiles.find("NoSuchPlayer")
found = cops.profiles.many([123456, "Alice", "Bob"])
by_id = cops.profiles.by_ids([1, 2, 3])
by_name = cops.profiles.by_usernames(["Alice", "Bob"])
```

- `get` raises `NotFoundError` when the player doesn't exist.
- `find` returns `None` instead of raising.
- `many` takes any number of players. It returns them in request order without duplicates, and skips players who don't exist. Pass `skip_missing=False` to raise instead.
- `by_ids` returns a `dict[int, Profile]`.
- `by_usernames` returns a `dict` keyed by the names you asked for.

## Servers

```python
servers = cops.servers.list()
online = cops.servers.online()
server = cops.servers.pick(region="EU")
```

- `list` returns a `GameServer(id, name, online, region)` for every server. `region` is guessed from the server name; see `region_of()`.
- `pick` returns a random online server in the region. If none match, it falls back to any online server; pass `fallback_to_any=False` to get `None` instead. You can also filter with `name="DE"`.

## Match history

```python
history = cops.matches.history(user_id)
match = cops.matches.one(history[0].id)
recent = cops.matches.recent(user_id, limit=5, game_type="ranked")
```

- `history` returns the player's recent matches, newest first. The history resets with each game update.
- `one` returns a full scoreboard, and `matches.get([...])` returns several (requests are split into groups of 20). Finished matches are cached for an hour.
- `recent` returns `(entry, match)` pairs, combining history and scoreboards.

## Weapon stats

```python
weapons = cops.stats.weapons(user_id, "ranked")
best = cops.stats.top_weapons(user_id, by="k", limit=5)
```

- The game type is `"ranked"` or `"casual"`. Custom games count as casual.
- `top_weapons` sorts by kills (`k`), assists (`a`) or headshots (`h`). Each `WeaponStats` also has a `.headshot_rate`.

## Leaderboards

```python
page = cops.leaderboards.page("mmr", page=1)
elite = cops.leaderboards.page("mmr", rank=9)

for entry in cops.leaderboards.iterate("kills", max_pages=10):
    print(entry.position, entry.basic_info.name, entry.score)

top50 = cops.leaderboards.top("wins", 50)
```

- The types are `mmr`, `kills`, `deaths`, `assists`, `matches`, `wins`, `losses`, `xp` and `mvp`. Pages hold 10 entries.
- `page` returns a `LeaderboardPage(type, page, rank, size, pages, entries)`. `rank` (0 to 9) filters to one rank.
- Players move as matches end, so `iterate` skips anyone already yielded on an earlier page.

## Hosting games (Autohost)

This needs a token with the `Autohost` permission. To check before offering hosting features to your users, call `cops.autohost.is_available()`.

### One call: host, wait for the code, add owners

```python
server = cops.servers.pick(region="EU")
room = cops.autohost.host(
    server_id=server.id,
    mode="tournament",
    map="Castello",
    room_name="Scrim #42",
    owners=[captain_user_id],
)
print(f"Join with code {room.code}, password {room.password}")
```

- `mode` and `map` accept names (`"Tournament Mode"`, `"castello"`) or ids. Combinations the API doesn't allow raise `BadRequestError` before the request is sent; pass `validate=False` if Critical Force added a map after this release.
- A random 6-character password is generated unless you pass `password="..."`. Pass `password=False` for an open room.
- `host` raises `GameRejectedError` if the game server refuses the game (it's full or in maintenance, or the token already hosts 10 games there). It raises `GameGoneError`, or `ConnectionFailedError` with code `timeout`, if the room never appears.

### Step by step

```python
game = cops.autohost.create(server_id=6, mode=15847, map=15391, room_name="Final", password="abc")
ready = cops.autohost.wait_for_room(game.id)
games = cops.autohost.poll([game.id, other_id])
one = cops.autohost.get(game.id)
```

- `wait_for_room` waits until the room code appears.
- `poll` checks many games at once (up to 50 per request, split automatically).
- `get` returns `None` once the game is gone.

### Room commands

```python
cops.autohost.kick(game_id, user_id)
cops.autohost.add_owner(game_id, user_id)
cops.autohost.remove_owner(game_id, user_id)
cops.autohost.restart(game_id)
cops.autohost.close(game_id)
cops.autohost.control(game_id, "kick", user_id)
```

- `kick` removes the player and keeps them out for an hour.
- `add_owner` works before the player joins.
- `close` ends the game; the matches played so far stay in its results.
- `control` is the general form; the other methods call it.

### Rules from the API

- A room closes when nobody joins within 3 minutes, when everyone leaves, or after 3 hours.
- Each game server hosts at most 100 games, and at most 10 per token.
- Game ids are unique within the current game version only.
- `results` lists every match that was played to the end in the room. A match restarted before it ends leaves no result.

## Watching hosted games

The watcher polls every game you track in a single request every 5 seconds, which is how often game servers update. It compares each poll with the previous one and calls your handlers.

```python
watcher = cops.autohost.watch()
watcher.track(room.id, meta={"scrim_id": 42})

@watcher.on("player_join")
def joined(game, player, join):
    print(player.user_id, "joined after", join.since_room_ready, "seconds")

@watcher.on("match_result")
def finished(game, result, index):
    save_result(watcher.meta(game.id), summarize_result(result))

watcher.on("player_disconnect", lambda game, player: print(player.user_id, "lost connection"))
watcher.on("ended", lambda game: print("room closed", game.replay_id))

watcher.run()
```

- `run()` blocks until every tracked game has ended.
- `start()` polls in a background thread instead. Stop it with `stop()`, or use `with watcher:`.

With the async client, handlers can be plain functions or coroutines:

```python
watcher = cops.autohost.watch()
watcher.track(room.id)

@watcher.on("score")
async def score(game, round_, scores):
    await post_to_discord(f"Round {round_}: {scores[0]}-{scores[1]}")

await watcher.run()
```

- `await watcher.run()` waits until every tracked game has ended.
- `watcher.start()` polls in a background task. Stop it with `await watcher.stop()`, or use `async with watcher:`.

### Events

| Event | Handler arguments | When |
| --- | --- | --- |
| `update` | `game, previous` | Every poll. |
| `room_ready` | `game` | The room code first appears. |
| `rejected` | `game, reason` | The game server refused the game. |
| `state` | `game, state, previous` | `match_state` changed. |
| `match_start` | `game` | A match started or was restarted. |
| `score` | `game, round, scores` | The round or scores changed. |
| `player_join` | `game, player, JoinInfo(first_seen_at, since_room_ready)` | A player appeared in the room. |
| `player_leave` | `game, player` | A player left the room. |
| `player_disconnect` | `game, player` | Ping dropped to `-1`. |
| `player_reconnect` | `game, player, offline_seconds` | Ping came back. |
| `player_team_change` | `game, player, previous_team` | A player switched team. |
| `match_result` | `game, result, index` | A match finished. Each result fires once. |
| `ended` | `game` | The room closed. The game is untracked unless `untrack_ended=False`. |
| `gone` | `game_id, last_known` | Polling stopped returning the game for `missing_grace` seconds. |
| `poll_error` | `error` | A poll failed. The watcher keeps going, except for token and permission errors. |
| `handler_error` | `error, event` | One of your handlers raised an exception. |

### Options and methods

- `watch(interval=5.0, missing_grace=60.0, untrack_ended=True)`
- `track(game_id, meta=None, seen_results=0)`, `untrack(game_id)`, `poll_now()`
- `latest(game_id)`, `meta(game_id)`, `join_times(game_id)`, `room_ready_at(game_id)`, `ids`, `len(watcher)`, `running`

`missing_grace` exists because a game created a moment ago can be missing from the first polls.

### Resuming after a restart

To resume after your process restarts, track the game ids again. Pass `seen_results` set to the number of results you already processed, so they aren't reported twice.

### Late joiners

`join_times(game_id)` and the `player_join` event tell you how long each player took to join after the room was ready. You can use that to flag no-shows.

## Rate limits and the quota

Each token gets a quota of requests per wall-clock minute (60 by default). Every authenticated request counts, including failed ones.

The client reads `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset` from every response:

```python
print(cops.quota)
```

This prints `QuotaSnapshot(limit=60, remaining=57, reset_at=..., resets_in=41.2, reserve=0)`.

When the quota runs out, requests wait for the next minute by default. With `on_quota_exhausted="raise"` they raise a local `RateLimitError` at once instead.

If you host games, set `rate_limit_reserve`, for example to `15`. Autohost calls run at high priority and can use the last requests of each minute. Everything else stops early, so a burst of profile lookups can never starve room polling.

Fetching the OpenAPI document (`cops.open_api_spec()`) needs no token and doesn't count toward the quota.

## Errors

Every failure raises a subclass of `CopsApiError`, which carries a stable `code`:

```python
from copsapi import CopsApiError, NotFoundError, RateLimitError

try:
    cops.profiles.get("ghost")
except NotFoundError:
    ...
except RateLimitError as err:
    print(f"retry in {err.retry_after}s")
except CopsApiError as err:
    print(err.code, err.status, err)
```

| Exception | Codes |
| --- | --- |
| `AuthenticationError` | `missing_token`, `invalid_token`, `token_revoked` |
| `PermissionDeniedError` | `insufficient_permissions`: the token lacks a permission, such as `Autohost` |
| `RateLimitError` | `rate_limited`: wait `retry_after` seconds |
| `BadRequestError` | `bad_request`: a parameter is malformed or out of range |
| `NotFoundError` | `user_not_found`, `game_not_found` |
| `ServiceUnavailableError` | `server_unavailable`, `api_disabled`, `internal_error`, `gateway` |
| `ConnectionFailedError` | `network`, `timeout` |
| `InvalidResponseError` | `invalid_response`: a 2xx response that isn't JSON |
| `GameRejectedError` | `game_rejected`: the game server refused a hosted game |
| `GameGoneError` | `game_gone`: a hosted game disappeared |

Other attributes:
- `err.status` is the HTTP status, or `0` if there was no response.
- `err.retryable` tells you whether trying again later can work.
- `err.local` is `True` when the library refused the request without calling the API, for example on validation or to keep the quota reserve.
- `is_cops_error(err, "user_not_found")` checks for a code without importing the classes.

## Caching

Responses are cached in memory, with up to 5,000 entries. Default lifetimes:

| Kind | Default TTL |
| --- | --- |
| `profile` | 5 minutes |
| `servers` | 30 seconds |
| `leaderboard` | 1 minute |
| `history` | 1 minute |
| `match` | 1 hour |
| `weapons` | 2 minutes |

Autohost calls are never cached. Pass `fresh=True` to any read to skip the cache, change lifetimes with `cache_ttls={"profile": 60}`, or call `cops.clear_cache()`.

To share a cache between processes, pass any object with `get(key)` and `set(key, value, ttl_seconds)`, and optionally `clear()`. The async client also accepts async methods. Cached values are model objects, so a shared store needs to pickle them:

```python
import pickle
import redis

class RedisStore:
    def __init__(self, client):
        self.client = client

    def get(self, key):
        data = self.client.get(f"cops:{key}")
        return pickle.loads(data) if data else None

    def set(self, key, value, ttl):
        self.client.set(f"cops:{key}", pickle.dumps(value), ex=max(1, int(ttl)))

cops = CopsClient(cache=RedisStore(redis.Redis()))
```

## Game catalog

The game modes and maps that can be hosted through the API:

```python
from copsapi import GAME_MODES, MAPS, game_mode, map_id, map_name, is_hostable, maps_for, modes_for

game_mode("tournament")
map_id("Castello")
map_name(613)
is_hostable("wingman", "Grounded")
maps_for("tournament")
modes_for("Purify")
```

- `game_mode("tournament")` returns `GameMode(id=15847, key='tournament', name='Tournament Mode', maps=(...))`.
- `map_id("Castello")` returns `15391`, and `map_name(613)` returns `'Canals'`.
- `is_hostable("wingman", "Grounded")` returns `False`.

| Mode | `key` | id | Maps |
| --- | --- | --- | --- |
| Defuse | `defuse` | 15773 | Canals, Plaza, Legacy, Grounded, Bureau, Uplink, Yard, Raid, Port, Park, Purify, Arctic, Bout, Soar, Shanty, Village, Castello |
| Elimination | `elimination` | 15775 | Warehouse, Impasse, Overhaul |
| Gungame | `gungame` | 15776 | Brewery, Division, Uplink, Yard, Heat, Warehouse, Gallery, Park, Cargo, Arctic, Bout, Hangar, Impasse, Overhaul |
| Team Deathmatch | `tdm` | 15777 | All 26 maps |
| Manhunt | `manhunt` | 15846 | Purify |
| Tournament Mode | `tournament` | 15847 | Canals, Plaza, Legacy, Grounded, Bureau, Raid, Port, Soar, Village, Castello |
| Rush | `rush` | 15860 | All 26 maps |
| Defend | `defend` | 15861 | Shanty |
| Manhunt Z | `manhuntz` | 18596 | Purify |
| Wingman | `wingman` | 18850 | Canals, Plaza, Legacy, Bureau, Raid, Village, Castello |

The package also exports these label tables:
- `BAN_REASONS`, `USER_TYPES`, `ACCOUNT_AGES`, `PARTY_INVITE_PERMISSIONS` and `CLAN_RANKS`, which map API codes to readable text.
- `LEADERBOARD_TYPES`, `MATCH_STATES`, `GAME_TYPES`, `INPUT_DEVICES` and `AUTOHOST_COMMANDS`.

## Helpers

| Helper | Returns |
| --- | --- |
| `career_totals(profile, "ranked" \| "casual" \| "custom" \| "all")` | `Totals(kills, deaths, assists, wins, losses, matches, kd, win_rate)` over all seasons. |
| `season_totals(profile, season=None, scope="all")` | The same for one season (the latest by default). |
| `summarize_result(result)` | Teams sorted by kills, the winner, draw, duration, top fragger and leavers, for autohost results or fetched matches. |
| `describe_ban(ban)` | Text such as `"Banned for 3 more days (Griefing)"`. |
| `ban_reason(ban)` | The reason label. |
| `input_devices(flags)` | `["keyboard_mouse", "touch", "gamepad"]`, decoded from `input_device_flags`. |
| `account_age_label(profile)` | Text such as `"Under 3 months"`. |
| `is_new_account(profile)` | `True` for accounts under a month old. |
| `is_staff(user_type)` | `True` for Critical Ops moderators and developers. |
| `kd(kills, deaths)` | The K/D ratio, rounded. |
| `random_password(length=6)` | A room password without look-alike characters. |
| `region_of(server_name)` | `"EU"`, `"NA"`, `"SA"`, `"AS"`, `"OC"`, `"ME"`, `"AF"` or `None`, guessed from the name. |

## Command line

```sh
pip install copsapi-wrapper
export COPS_API_TOKEN=cops_...

copsapi token
copsapi profile 123456 SomePlayer
copsapi servers
copsapi history 123456
copsapi match <match_id>
copsapi weapons 123456 casual
copsapi leaderboard mmr 1 --rank 9
copsapi host --server 6 --mode tournament --map Castello --name "Scrim" --owner 123456
copsapi watch 812
copsapi control 812 kick 654321
copsapi catalog
copsapi quota
```

Pass your own token with `--token cops_...`, or set `COPS_API_TOKEN`. Add `--json` before the command for JSON output, for example `copsapi --json servers`. `python -m copsapi` works too.

## Models

Responses are frozen dataclasses. They keep the API's own snake_case field names, exactly as the OpenAPI spec defines them:

- `Profile` has `basic_info`, `account_age`, `ban`, `stats` (`seasonal_stats`, `ranked`, `leaderboard_data`) and `clan`, plus the shortcuts `.user_id` and `.name`.
- `AutohostGame` has `status`, `room` (`code`, `map_id`, ...), `players`, `scores`, `round`, `match_state` and `results`, plus the shortcuts `.open` and `.code`.
- `MatchInfo` and `AutohostResult` have `players`, `scores`, `winning_team` and `win_condition`. `MatchInfo` also has `.started` and `.ended` as `datetime`.
- `Profile`, `MatchInfo`, `MatchHistoryEntry` and `AutohostGame` keep the full JSON in `.raw`, including fields the API adds after this release.

Field reference:
- **Times** are Unix timestamps in seconds.
- **`team`** is `-1` for a player who hasn't picked a team.
- **`ping`** is `-1` while the player is disconnected; `PlayerMatchStats.connected` checks this for you.
- **`winning_team`** is `-1` when no team won.
- **`ranked.rank`** is `0` while placement matches are left and `9` for Elite Ops.
- **`ban.days_left`** is `0` for a ban that never ends; `Ban.permanent` tells you whether the ban is permanent.

## Development

```sh
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
pytest
mypy
```

On macOS and Linux, use `.venv/bin/pip`.

The sync client (`_sync_client.py`) is generated from the async source (`_async_client.py`). After changing the async client, run `python scripts/generate_sync.py`; a test fails if the two are out of step.

## License

MIT. This is an unofficial client; Critical Ops and the Critical Ops API belong to Critical Force.
