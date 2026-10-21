from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from conftest import player, profile, result
from copsapi import (
    AutohostResult,
    Ban,
    Profile,
    career_totals,
    describe_ban,
    game_mode,
    input_devices,
    is_hostable,
    kd,
    map_id,
    map_name,
    modes_for,
    random_password,
    region_of,
    season_totals,
    summarize_result,
)
from copsapi.cli import main as cli_main
from copsapi.models import from_dict

ROOT = Path(__file__).resolve().parent.parent


def test_maps_resolve_by_name_id_or_numeric_string():
    assert map_id("Castello") == 15391
    assert map_id(" canals ") == 613
    assert map_id("613") == 613
    assert map_id(1) is None
    assert map_name(8427) == "Soar"


def test_game_modes_resolve_by_key_name_or_id():
    assert game_mode("tournament").id == 15847
    assert game_mode("Team Deathmatch").key == "tdm"
    assert game_mode("manhunt z").id == 18596
    assert game_mode(15777).name == "Team Deathmatch"
    assert game_mode("nope") is None


def test_hostable_combinations():
    assert is_hostable("tournament", "Castello")
    assert not is_hostable("tournament", "Heat")
    assert not is_hostable("wingman", "Grounded")
    assert [m.key for m in modes_for("Purify")] == ["defuse", "tdm", "manhunt", "rush", "manhuntz"]


def test_input_devices_and_bans():
    assert input_devices(1) == ["keyboard_mouse"]
    assert input_devices(6) == ["touch", "gamepad"]
    assert describe_ban(None) is None
    assert describe_ban(Ban(type=0, reason=2)) == "Permanently banned (Hacking)"
    assert describe_ban(Ban(type=1, reason=4, days_left=1)) == "Banned for 1 more day (Verbal abuse)"


def test_totals():
    p = from_dict(Profile, profile(1))
    ranked = career_totals(p, "ranked")
    assert (ranked.kills, ranked.deaths, ranked.kd, ranked.wins, ranked.losses, ranked.matches, ranked.win_rate) == (30, 15, 2.0, 5, 3, 8, 0.625)
    assert season_totals(p, scope="ranked").kills == 20
    assert season_totals(p, 7) is None
    assert kd(5, 0) == 5


def test_summarize_result():
    r = from_dict(
        AutohostResult,
        result(
            winning_team=1,
            scores=[5, 7],
            team_factions=[1, 0],
            started_at=100,
            ended_at=1300,
            players=[player(1, team=0, kills=9), player(2, team=1, kills=20), player(3, team=1, kills=4, left_match=True, leave_reason="Left"), player(4, team=-1, kills=50)],
        ),
    )
    s = summarize_result(r)
    assert (s.map, s.winning_team, s.draw, s.duration) == ("Canals", 1, False, 1200)
    assert [(t.team, t.score, t.won, [p.user_id for p in t.players]) for t in s.teams] == [(0, 5, False, [1]), (1, 7, True, [2, 3])]
    assert s.top_fragger.user_id == 2
    assert [p.user_id for p in s.leavers] == [3]


def test_passwords_and_regions():
    pw = random_password(10)
    assert len(pw) == 10 and not set(pw) & set("01IO")
    assert region_of("Europe/DE-1") == "EU"
    assert region_of("NA-East") == "NA"
    assert region_of("Singapore") == "AS"
    assert region_of("Mars-1") is None


def test_cli_catalog_needs_no_token(capsys, monkeypatch):
    monkeypatch.delenv("COPS_API_TOKEN", raising=False)
    assert cli_main(["catalog"]) == 0
    assert "Tournament Mode (tournament, 15847)" in capsys.readouterr().out


def test_cli_explains_a_missing_token(capsys, monkeypatch):
    monkeypatch.delenv("COPS_API_TOKEN", raising=False)
    assert cli_main(["servers"]) == 1
    assert "missing_token" in capsys.readouterr().err


def test_sync_client_is_generated_from_the_async_source():
    check = subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_sync.py"), "--check"], capture_output=True, text=True)
    assert check.returncode == 0, check.stdout


def test_no_comments_in_package_code():
    for path in (ROOT / "src" / "copsapi").glob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            assert not stripped.startswith("#"), f"{path.name}:{number}"
            assert '"""' not in stripped, f"{path.name}:{number}"
