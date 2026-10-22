# Changelog

## 1.1.0

- Named constants for every code the API uses, such as `BanReason.HACKING`, `UserType.MODERATOR`, `MapId.CASTELLO`, `GameModeId.TOURNAMENT_MODE`, `LeaderboardType.KILLS` and `AutohostCommand.KICK`. Number codes are `IntEnum`s and text codes are `str` enums, so both compare equal to the plain values in the models.
- `InputDeviceFlag` is an `IntFlag`: `InputDeviceFlag(player.input_device_flags)` decodes the bitmask, and `has_input_device()` checks for one device.
- Every client method that takes a map, mode, game type, leaderboard type or command also accepts these constants. Nothing else changed, so existing code keeps working.

## 1.0.0

First release, covering the Critical Ops Public API v2.0.0:

- `CopsClient` and `AsyncCopsClient` with the same methods, built on httpx.
- Profiles, server status, match history, match scoreboards, weapon stats and leaderboards, returned as typed dataclasses.
- Autohost: create, poll, control, `host()` in one call, and watchers with live events (background thread or asyncio).
- Every user supplies their own token, and it is checked up front. `verify_token()` and `autohost.is_available()` report what a token can do. Hosting calls with a token that lacks `Autohost` raise a clear `PermissionDeniedError` without spending more quota.
- Quota tracking from the rate-limit headers, a reserve for Autohost traffic, and waiting instead of `429`s.
- Retries for network errors, timeouts and gateway pages that are safe for `POST` requests.
- Automatic batching, isolation of unknown players, caching with pluggable stores, and combining of duplicate requests (async).
- Catalog of hostable game modes and maps, label tables and stat helpers.
- `copsapi` command line tool.
