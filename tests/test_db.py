import pytest

from lolmono.db import Database
from lolmono.rows import MatchRow, RunePage, TimelineRow


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "lol.db")
    database.init_schema()
    yield database
    database.close()


def make_row(match_id="BR1_1", puuid="P1", champion_id=79, role="TOP", win=True):
    return MatchRow(
        match_id=match_id,
        platform="br1",
        puuid=puuid,
        champion_id=champion_id,
        role=role,
        opponent_champion_id=122,
        opponent_puuid="OPP-" + puuid,
        win=win,
        items=(3068, 3075, 3143),
        runes=RunePage(
            keystone=8437,
            primary_style=8400,
            primary_perks=(8446, 8444, 8451),
            secondary_style=8300,
            secondary_perks=(8345, 8347),
            shards=(5008, 5008, 5002),
        ),
        spells=(4, 12),
    )


def make_timeline(match_id="BR1_1", puuid="P1"):
    return TimelineRow(
        match_id=match_id,
        puuid=puuid,
        gold_at_14=4500,
        cs_diff_at_14=None,
        starting_items=(1054,),
        item_order=(3068, 3075),
        skill_order=(1, 2, 3),
        deaths_before_10=0,
        kills_before_10=1,
    )


def test_init_schema_is_idempotent(db):
    db.init_schema()
    db.init_schema()
    tables = db.table_names()
    assert {"candidate", "player", "match", "timeline", "discard"} <= set(tables)
    assert not any(t.startswith("sqlite_") for t in tables)


def test_wal_mode_enabled(db):
    assert db._conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_candidate_lifecycle_tracks_progress(db):
    db.add_candidates("br1", ["A", "B"])
    assert set(db.pending_candidates("br1")) == {"A", "B"}
    db.mark_screened("br1", "A", suspect=True)
    assert db.pending_candidates("br1") == ["B"]
    assert db.pending_suspects("br1") == ["A"]


def test_add_candidates_is_idempotent_on_rerun(db):
    db.add_candidates("br1", ["A"])
    db.add_candidates("br1", ["A"])
    assert db.pending_candidates("br1") == ["A"]


def test_add_candidates_does_not_reset_screened_state(db):
    db.add_candidates("br1", ["A"])
    db.mark_screened("br1", "A", suspect=True)
    db.add_candidates("br1", ["A"])
    assert db.pending_candidates("br1") == []
    assert db.pending_suspects("br1") == ["A"]


def test_candidates_are_scoped_by_platform(db):
    db.add_candidates("br1", ["A"])
    db.add_candidates("na1", ["B"])
    assert db.pending_candidates("br1") == ["A"]


def test_confirmed_or_rejected_suspect_leaves_pending_suspects(db):
    db.add_candidates("br1", ["A", "B"])
    db.mark_screened("br1", "A", suspect=True)
    db.mark_screened("br1", "B", suspect=True)
    db.confirm_player("br1", "A", "A#BR1", 79, "TOP", 30, 0.6)
    db.reject_player("br1", "B")
    assert db.pending_suspects("br1") == []


def test_match_roundtrip_preserves_runes_and_items(db):
    row = make_row()
    db.insert_match(row)
    assert db.confirmed_matches(row.champion_id, row.role) == []
    db.confirm_player("br1", row.puuid, "Mono#BR1", row.champion_id, row.role, 30, 0.6)
    assert db.confirmed_matches(row.champion_id, row.role) == [row]


def test_match_exists_is_keyed_by_match_and_puuid(db):
    db.insert_match(make_row(match_id="BR1_1", puuid="P1"))
    assert db.match_exists("BR1_1", "P1")
    assert not db.match_exists("BR1_1", "P2")


def test_same_match_can_hold_two_tracked_players(db):
    db.insert_match(make_row(match_id="BR1_1", puuid="P1"))
    db.insert_match(make_row(match_id="BR1_1", puuid="P2"))
    assert db.match_exists("BR1_1", "P1") and db.match_exists("BR1_1", "P2")


def test_insert_match_twice_is_idempotent(db):
    row = make_row()
    db.insert_match(row)
    db.insert_match(row)
    db.confirm_player("br1", row.puuid, "M#BR1", row.champion_id, row.role, 30, 0.6)
    assert db.confirmed_matches(row.champion_id, row.role) == [row]


def test_confirmed_matches_filters_by_the_players_own_pair(db):
    top = make_row(match_id="BR1_1", puuid="P1", champion_id=79, role="TOP")
    mid = make_row(match_id="BR1_2", puuid="P2", champion_id=79, role="MIDDLE")
    db.insert_match(top)
    db.insert_match(mid)
    db.confirm_player("br1", "P1", "A#BR1", 79, "TOP", 30, 0.6)
    assert db.confirmed_matches(79, "TOP") == [top]
    assert db.confirmed_matches(79, "MIDDLE") == []


def test_player_confirmed_for_one_pair_does_not_leak_into_another(db):
    # P1 is confirmed mono Gragas-TOP but also has a Gragas-MIDDLE match stored.
    top = make_row(match_id="BR1_1", puuid="P1", champion_id=79, role="TOP")
    mid = make_row(match_id="BR1_2", puuid="P1", champion_id=79, role="MIDDLE")
    db.insert_match(top)
    db.insert_match(mid)
    db.confirm_player("br1", "P1", "A#BR1", 79, "TOP", 30, 0.6)
    assert db.confirmed_matches(79, "MIDDLE") == []
    assert db.confirmed_player_count(79, "MIDDLE") == 0
    assert db.confirmed_players(79, "MIDDLE") == []


def test_rejected_player_matches_are_excluded(db):
    row = make_row()
    db.insert_match(row)
    db.confirm_player("br1", row.puuid, "M#BR1", row.champion_id, row.role, 30, 0.6)
    db.reject_player("br1", row.puuid)
    assert db.confirmed_matches(row.champion_id, row.role) == []
    assert db.confirmed_player_count(row.champion_id, row.role) == 0


def test_confirmed_players_exposes_reference_list_without_puuid_leak(db):
    row = make_row()
    db.insert_match(row)
    db.confirm_player("br1", row.puuid, "Mono#BR1", row.champion_id, row.role, 30, 0.6)
    players = db.confirmed_players(row.champion_id, row.role)
    assert [p.riot_id for p in players] == ["Mono#BR1"]
    assert players[0].platform == "br1"
    assert players[0].games == 30
    assert players[0].share == 0.6
    assert players[0].win_rate == 1.0


def test_player_win_rate_is_computed_from_stored_matches(db):
    for i, win in enumerate([True, False, False, True]):
        db.insert_match(make_row(match_id=f"BR1_{i}", win=win))
    db.confirm_player("br1", "P1", "M#BR1", 79, "TOP", 30, 0.6)
    assert db.confirmed_players(79, "TOP")[0].win_rate == 0.5


def test_confirmed_group_win_rate_and_count(db):
    db.insert_match(make_row(match_id="BR1_1", puuid="P1", win=True))
    db.insert_match(make_row(match_id="BR1_2", puuid="P1", win=False))
    db.insert_match(make_row(match_id="BR1_3", puuid="P2", win=True))
    db.insert_match(make_row(match_id="BR1_4", puuid="P3", win=False))  # unconfirmed
    db.confirm_player("br1", "P1", "A#BR1", 79, "TOP", 30, 0.6)
    db.confirm_player("br1", "P2", "B#BR1", 79, "TOP", 30, 0.6)
    assert db.confirmed_player_count(79, "TOP") == 2
    assert db.confirmed_group_win_rate(79, "TOP") == pytest.approx(2 / 3)


def test_confirmed_group_win_rate_without_matches_is_zero(db):
    assert db.confirmed_group_win_rate(79, "TOP") == 0.0


def test_discard_counts_group_by_reason(db):
    db.record_discard("BR1_1", "unpaired_lanes")
    db.record_discard("BR1_2", "unpaired_lanes")
    db.record_discard("BR1_3", "missing_position")
    assert db.discard_counts() == {"unpaired_lanes": 2, "missing_position": 1}


def test_timeline_roundtrip_keeps_none_and_tuples(db):
    tl = make_timeline()
    db.insert_timeline(tl)
    assert db.timelines_for(["BR1_1"]) == {("BR1_1", "P1"): tl}


def test_timelines_for_ignores_other_matches_and_empty_input(db):
    db.insert_timeline(make_timeline("BR1_1", "P1"))
    db.insert_timeline(make_timeline("BR1_2", "P1"))
    assert set(db.timelines_for(["BR1_2"])) == {("BR1_2", "P1")}
    assert db.timelines_for([]) == {}


def test_matches_awaiting_timeline_excludes_already_extracted(db):
    for mid in ("BR1_1", "BR1_2"):
        db.insert_match(make_row(match_id=mid, puuid="P1"))
    db.insert_match(make_row(match_id="BR1_3", puuid="P9"))  # unconfirmed player
    db.confirm_player("br1", "P1", "A#BR1", 79, "TOP", 30, 0.6)
    assert sorted(db.matches_awaiting_timeline()) == [
        ("BR1_1", "P1", "OPP-P1"),
        ("BR1_2", "P1", "OPP-P1"),
    ]
    db.insert_timeline(make_timeline("BR1_1", "P1"))
    assert db.matches_awaiting_timeline() == [("BR1_2", "P1", "OPP-P1")]


def test_matches_awaiting_timeline_is_per_puuid(db):
    db.insert_match(make_row(match_id="BR1_1", puuid="P1"))
    db.insert_match(make_row(match_id="BR1_1", puuid="P2"))
    db.confirm_player("br1", "P1", "A#BR1", 79, "TOP", 30, 0.6)
    db.confirm_player("br1", "P2", "B#BR1", 79, "TOP", 30, 0.6)
    db.insert_timeline(make_timeline("BR1_1", "P1"))
    assert db.matches_awaiting_timeline() == [("BR1_1", "P2", "OPP-P2")]


def test_commit_persists_across_connections(tmp_path):
    path = tmp_path / "x.db"
    first = Database(path)
    first.init_schema()
    first.add_candidates("br1", ["A"])
    first.commit()
    second = Database(path)
    assert second.pending_candidates("br1") == ["A"]
    second.close()
    first.close()
