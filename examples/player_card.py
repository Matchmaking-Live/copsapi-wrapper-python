import sys

from copsapi import CopsClient, account_age_label, career_totals, describe_ban

name = sys.argv[1] if len(sys.argv) > 1 else "SomePlayer"

with CopsClient() as cops:
    player = cops.profiles.find(name)
    if player is None:
        sys.exit(f"{name} does not exist.")

    ranked = career_totals(player, "ranked")
    weapons = cops.stats.top_weapons(player.user_id, limit=3)

    clan = f" [{player.clan.basic_info.tag}]" if player.clan else ""
    print(f"{player.name}{clan}, level {player.basic_info.player_level.level}")
    print(f"Account age: {account_age_label(player)}. {describe_ban(player.ban) or 'Not banned.'}")
    print(f"Rank {player.stats.ranked.rank}, {player.stats.ranked.mmr} MMR")
    print(f"Ranked career: K/D {ranked.kd}, {round(ranked.win_rate * 100)}% of {ranked.matches} matches won")
    print("Best weapons: " + ", ".join(f"{w.name} ({w.k} kills, {round(w.headshot_rate * 100)}% headshots)" for w in weapons))
