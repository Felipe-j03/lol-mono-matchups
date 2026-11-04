import json
from pathlib import Path

import pytest

from lolmono.__main__ import main
from lolmono.config import load_config
from lolmono.db import Database
from lolmono.export import SCHEMA_VERSION, export_all
from lolmono.rows import MatchRow, RunePage, TimelineRow

CONFIG_PATH = Path(__file__).parent.parent / "config.example.toml"
TALON, GRAGAS, EKKO, ZED = 91, 79, 245, 238
KNOWN_PUUID = "PUUID-TALON-MONO-0001"
OPPONENT_PUUID = "PUUID-OPPONENT-SECRET"
PAGE = RunePage(
    keystone=8112,
    primary_style=8100,
    primary_perks=(8112, 8126, 8138, 8135),
    secondary_style=8000,
    secondary_perks=(9111, 9104),
    shards=(5008, 5008, 5002),
)


@pytest.fixture
def cfg():
    return load_config(CONFIG_PATH)


def _match(n, win, opponent, boots, puuid=KNOWN_PUUID):
    return MatchRow(
        match_id=f"BR1_{n}",
        platform="br1",
        puuid=puuid,
        champion_id=TALON,
        role="MIDDLE",
        opponent_champion_id=opponent,
        opponent_puuid=OPPONENT_PUUID,
        win=win,
        items=(3142, boots),
        runes=PAGE,
        spells=(4, 14),
    )


def _timeline(n, gold):
    return TimelineRow(
        match_id=f"BR1_{n}",
        puuid=KNOWN_PUUID,
        gold_at_14=gold,
        cs_diff_at_14=3,
        starting_items=(1055, 2003),
        item_order=(3142,),
        skill_order=(1, 2, 3),
        deaths_before_10=0,
        kills_before_10=1,
    )


@pytest.fixture
def db(tmp_path):
    """Talon mid has data; the other four configured targets have none at all."""
    database = Database(tmp_path / "test.sqlite")
    database.init_schema()
    database.confirm_player("br1", KNOWN_PUUID, "Mono#BR1", TALON, "MIDDLE", 40, 0.8)
    n = 0
    # 40 games against Ekko: 20 wins and 20 losses, boots split by outcome.
    for win in (True, False):
        for i in range(20):
            n += 1
            boots = (3020 if i < 16 else 3047) if win else (3020 if i < 4 else 3047)
            database.insert_match(_match(n, win, EKKO, boots))
            database.insert_timeline(_timeline(n, 5200 if win else 4000))
    # 5 games against Zed: below the matchup floor of 30.
    for i in range(5):
        n += 1
        database.insert_match(_match(n, i < 3, ZED, 3020))
    database.commit()
    yield database
    database.close()


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_export_writes_index_and_per_target_files(db, cfg, tmp_path):
    out = tmp_path / "out"
    export_all(db, cfg, out)
    index = _read(out / "index.json")
    assert index["schema_version"] == 1 == SCHEMA_VERSION
    assert index["ddragon_version"] == cfg.ddragon_version
    assert len(index["targets"]) == 5
    assert (out / "talon-middle.json").exists()


def test_index_marks_targets_with_data(db, cfg, tmp_path):
    out = tmp_path / "out"
    export_all(db, cfg, out)
    targets = {(t["champion_name"], t["role"]): t for t in _read(out / "index.json")["targets"]}
    talon = targets[("Talon", "MIDDLE")]
    assert talon == {
        "champion_id": TALON,
        "champion_name": "Talon",
        "role": "MIDDLE",
        "has_data": True,
        "file": "talon-middle.json",
        "players": 1,
        "games": 45,
    }


def test_target_without_confirmed_matches_does_not_break_the_export(db, cfg, tmp_path):
    out = tmp_path / "out"
    export_all(db, cfg, out)  # compute_baseline([]) raises; the export must not
    targets = {(t["champion_name"], t["role"]): t for t in _read(out / "index.json")["targets"]}
    empty = targets[("Gragas", "TOP")]
    assert empty["has_data"] is False
    assert empty["file"] is None
    assert empty["games"] == 0 and empty["players"] == 0
    assert not (out / "gragas-top.json").exists()
    assert sorted(p.name for p in out.glob("*-top.json")) == []


def test_export_of_an_empty_database_still_produces_an_index(tmp_path, cfg):
    empty = Database(tmp_path / "empty.sqlite")
    empty.init_schema()
    out = tmp_path / "out"
    export_all(empty, cfg, out)
    index = _read(out / "index.json")
    assert len(index["targets"]) == 5
    assert not any(t["has_data"] for t in index["targets"])
    assert [p.name for p in out.iterdir()] == ["index.json"]
    empty.close()


def test_target_file_has_baseline_matchups_and_players(db, cfg, tmp_path):
    out = tmp_path / "out"
    export_all(db, cfg, out)
    data = _read(out / "talon-middle.json")
    assert data["champion_id"] == TALON and data["role"] == "MIDDLE"
    base = data["baseline"]
    assert base["games"] == 45
    assert base["players"] == 1
    assert base["runes"]["keystone"] == 8112
    assert base["runes_games"] == 45
    assert base["spells"] == [4, 14]
    assert base["starting_items"] == [1055, 2003]
    assert base["starting_items_games"] == 40
    assert base["skill_order"] == [1, 2, 3]
    assert {"item_id": 3142, "games": 45} in base["item_frequency"]
    opponents = [m["opponent_champion_id"] for m in data["matchups"]]
    assert set(opponents) == {EKKO, ZED}


def test_every_exported_object_carries_its_sample_size(db, cfg, tmp_path):
    out = tmp_path / "out"
    export_all(db, cfg, out)
    data = _read(out / "talon-middle.json")
    assert data["baseline"]["games"] > 0
    assert all("games" in m for m in data["matchups"])
    assert all("games" in p for p in data["reference_players"])
    assert all(
        "games" in i for i in data["baseline"]["item_frequency"]
    )
    for key in ("runes_games", "spells_games", "starting_items_games", "skill_order_games"):
        assert key in data["baseline"]
    detail = _read(out / f"talon-middle-vs-{EKKO}.json")
    assert detail["games"] == 40 and detail["wins"] == 20 and detail["losses"] == 20


def test_matchup_files_exist_only_above_the_floor(db, cfg, tmp_path):
    out = tmp_path / "out"
    export_all(db, cfg, out)
    assert (out / f"talon-middle-vs-{EKKO}.json").exists()
    assert not (out / f"talon-middle-vs-{ZED}.json").exists()
    matchups = {m["opponent_champion_id"]: m for m in _read(out / "talon-middle.json")["matchups"]}
    assert matchups[EKKO]["file"] == f"talon-middle-vs-{EKKO}.json"
    assert matchups[ZED]["file"] is None
    assert matchups[ZED]["below_floor"] is True and matchups[ZED]["games"] == 5


def test_matchup_file_carries_the_comparison(db, cfg, tmp_path):
    out = tmp_path / "out"
    export_all(db, cfg, out)
    detail = _read(out / f"talon-middle-vs-{EKKO}.json")
    assert detail["comparable"] is True
    assert detail["min_per_side"] == cfg.delta_min_per_side
    assert detail["winner_gold_at_14"] == pytest.approx(5200.0)
    assert detail["loser_gold_at_14"] == pytest.approx(4000.0)
    boots = [d for d in detail["divergences"] if d["field"] == "boots"]
    assert {d["label"] for d in boots} == {"3020", "3047"}
    assert set(boots[0]) == {"field", "label", "winner_share", "loser_share", "gap"}
    assert [d["gap"] for d in detail["divergences"]] == sorted(
        (d["gap"] for d in detail["divergences"]), reverse=True
    )
    assert detail["headline"]


def test_exports_reference_player_list_with_name_and_region(db, cfg, tmp_path):
    out = tmp_path / "out"
    export_all(db, cfg, out)
    data = _read(out / "talon-middle.json")
    player = data["reference_players"][0]
    assert player["riot_id"] == "Mono#BR1"
    assert player["platform"] == "br1"
    assert "win_rate" in player
    assert set(player) == {"riot_id", "platform", "games", "share", "win_rate"}
    assert player["games"] == 40 and player["share"] == pytest.approx(0.8)


def test_exported_files_never_contain_puuids(db, cfg, tmp_path):
    out = tmp_path / "out"
    export_all(db, cfg, out)
    files = list(out.rglob("*.json"))
    assert len(files) >= 3
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert KNOWN_PUUID not in text
        assert OPPONENT_PUUID not in text
        assert "puuid" not in text.lower()


def test_exported_files_never_contain_the_api_key(db, cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("RIOT_API_KEY", "SECRET-KEY")
    out = tmp_path / "out"
    export_all(db, cfg, out)
    for path in out.rglob("*.json"):
        assert "SECRET-KEY" not in path.read_text(encoding="utf-8")


def test_export_is_deterministic_across_runs(db, cfg, tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    export_all(db, cfg, first)
    export_all(db, cfg, second)
    names = sorted(p.name for p in first.iterdir())
    assert names == sorted(p.name for p in second.iterdir())
    for name in names:
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_rerunning_into_the_same_directory_changes_nothing(db, cfg, tmp_path):
    out = tmp_path / "out"
    export_all(db, cfg, out)
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    export_all(db, cfg, out)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before


def test_export_creates_the_output_directory(db, cfg, tmp_path):
    out = tmp_path / "deep" / "site" / "data"
    export_all(db, cfg, out)
    assert (out / "index.json").exists()


def test_files_are_utf8_with_unix_newlines(db, cfg, tmp_path):
    out = tmp_path / "out"
    export_all(db, cfg, out)
    raw = (out / "index.json").read_bytes()
    assert b"\r\n" not in raw and raw.endswith(b"\n")


def test_cli_export_needs_no_api_key_and_no_platform(db, cfg, tmp_path):
    db.close()
    out = tmp_path / "cli-out"
    code = main(
        [
            "export",
            "--config", str(CONFIG_PATH),
            "--db", str(tmp_path / "test.sqlite"),
            "--out", str(out),
        ],
        environ={},
    )
    assert code == 0
    assert (out / "talon-middle.json").exists()


def test_cli_export_refuses_a_missing_database(tmp_path, capsys):
    code = main(
        ["export", "--config", str(CONFIG_PATH), "--db", str(tmp_path / "nope.sqlite"),
         "--out", str(tmp_path / "o")],
        environ={},
    )
    assert code == 2
    assert not (tmp_path / "nope.sqlite").exists()
    assert not (tmp_path / "o").exists()
