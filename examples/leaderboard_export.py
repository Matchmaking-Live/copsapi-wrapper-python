import asyncio
import csv

from copsapi import AsyncCopsClient, LeaderboardType


async def main() -> None:
    async with AsyncCopsClient() as cops:
        with open("elite-ops.csv", "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["position", "user_id", "name", "clan", "mmr", "wins", "losses"])
            count = 0
            async for entry in cops.leaderboards.iterate(LeaderboardType.MMR, rank=9, max_pages=20):
                clan = entry.clan.basic_info.tag if entry.clan else ""
                writer.writerow([entry.position, entry.basic_info.user_id, entry.basic_info.name, clan, entry.score, entry.ranked.wins, entry.ranked.losses])
                count += 1
        print(f"Saved {count} players. Requests left this minute: {cops.quota.remaining}")


asyncio.run(main())
