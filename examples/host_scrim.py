import sys

from copsapi import CopsClient, GameRejectedError, map_name, summarize_result

CAPTAINS = [111111, 222222]
LATE_AFTER = 10 * 60

with CopsClient(rate_limit_reserve=15) as cops:
    if not cops.autohost.is_available():
        sys.exit("Your token does not have the Autohost permission, so it cannot host games.")

    server = cops.servers.pick(region="EU")
    if server is None:
        sys.exit("No game server is online.")

    try:
        room = cops.autohost.host(server_id=server.id, mode="tournament", map="Castello", room_name="Scrim", owners=CAPTAINS)
    except GameRejectedError as err:
        sys.exit(f"The game server refused the game: {err}")

    print(f"Room {room.code} on {server.name}, password {room.password}")

    watcher = cops.autohost.watch().track(room.id)

    @watcher.on("player_join")
    def joined(game, player, join):
        late = join.since_room_ready is not None and join.since_room_ready > LATE_AFTER
        print(f"{player.user_id} joined{' late' if late else ''}")

    @watcher.on("match_result")
    def finished(game, result, index):
        summary = summarize_result(result)
        top = summary.top_fragger.user_id if summary.top_fragger else "nobody"
        print(f"{map_name(result.map_id)} finished {result.scores[0]}-{result.scores[1]}, top fragger {top}")
        cops.autohost.close(game.id)

    watcher.on("player_disconnect", lambda game, player: print(f"{player.user_id} disconnected"))
    watcher.on("score", lambda game, round_, scores: print(f"Round {round_}: {scores[0]} - {scores[1]}"))
    watcher.on("ended", lambda game: print("Room closed."))
    watcher.on("poll_error", lambda err: print(f"Poll failed: {err}"))
    watcher.run()
