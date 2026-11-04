import dataclasses
import sqlite3

import pytest

from lolmono.db import Database, SchemaError
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


def test_timeline_roundtrip_keeps_none_skill_order(db):
    # A short game (remake): no minute-14 numbers and fewer than three skill points.
    tl = dataclasses.replace(
        make_timeline(), gold_at_14=None, cs_diff_at_14=None, skill_order=None
    )
    db.insert_timeline(tl)
    back = db.timelines_for(["BR1_1"])[("BR1_1", "P1")]
    assert back == tl
    assert back.skill_order is None


def test_timeline_roundtrip_skill_order_comes_back_as_a_tuple(db):
    db.insert_timeline(make_timeline())
    back = db.timelines_for(["BR1_1"])[("BR1_1", "P1")]
    assert back.skill_order == (1, 2, 3)
    assert isinstance(back.skill_order, tuple)


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


def test_confirmed_player_count_excludes_players_without_stored_matches(db):
    db.insert_match(make_row(match_id="BR1_1", puuid="P1"))
    db.confirm_player("br1", "P1", "A#BR1", 79, "TOP", 30, 0.6)
    db.confirm_player("br1", "P2", "B#BR1", 79, "TOP", 30, 0.6)  # no matches
    assert db.confirmed_player_count(79, "TOP") == 1


def test_record_discard_twice_counts_once(db):
    db.record_discard("BR1_1", "unpaired_lanes")
    db.record_discard("BR1_1", "unpaired_lanes")
    assert db.discard_counts() == {"unpaired_lanes": 1}


def test_batch_commits_on_clean_exit(tmp_path):
    path = tmp_path / "b.db"
    first = Database(path)
    first.init_schema()
    with first.batch():
        first.add_candidates("br1", ["A"])
    second = Database(path)
    assert second.pending_candidates("br1") == ["A"]
    second.close()
    first.close()


def test_batch_does_not_commit_or_swallow_on_exception(tmp_path):
    path = tmp_path / "b.db"
    first = Database(path)
    first.init_schema()
    first.commit()
    with pytest.raises(RuntimeError):
        with first.batch():
            first.add_candidates("br1", ["A"])
            raise RuntimeError("boom")
    first.close()
    second = Database(path)
    assert second.pending_candidates("br1") == []
    second.close()


def test_batch_rollback_prevents_later_commit_on_same_database(tmp_path):
    path = tmp_path / "b.db"
    first = Database(path)
    first.init_schema()
    first.commit()
    with pytest.raises(RuntimeError):
        with first.batch():
            first.add_candidates("br1", ["A"])
            raise RuntimeError("boom")
    first.commit()  # caller carries on; the aborted batch must be gone
    assert first.pending_candidates("br1") == []
    first.close()


def test_close_without_commit_discards_writes(tmp_path):
    path = tmp_path / "c.db"
    first = Database(path)
    first.init_schema()
    first.commit()
    first.add_candidates("br1", ["A"])
    first.close()
    second = Database(path)
    assert second.pending_candidates("br1") == []
    second.close()


def test_reconfirming_for_another_pair_keeps_one_row(db):
    top = make_row(match_id="BR1_1", champion_id=79, role="TOP")
    mid = make_row(match_id="BR1_2", champion_id=79, role="MIDDLE")
    db.insert_match(top)
    db.insert_match(mid)
    db.confirm_player("br1", "P1", "A#BR1", 79, "TOP", 30, 0.6)
    db.confirm_player("br1", "P1", "A#BR1", 79, "MIDDLE", 25, 0.5)
    n = db._conn.execute("SELECT COUNT(*) FROM player").fetchone()[0]
    assert n == 1
    assert db.confirmed_matches(79, "TOP") == []
    assert db.confirmed_matches(79, "MIDDLE") == [mid]
    assert db.confirmed_player_count(79, "TOP") == 0
    assert db.confirmed_player_count(79, "MIDDLE") == 1


def test_last_verdict_wins_reject_then_confirm(db):
    row = make_row()
    db.insert_match(row)
    db.reject_player("br1", "P1")
    db.confirm_player("br1", "P1", "A#BR1", 79, "TOP", 30, 0.6)
    assert db.confirmed_matches(79, "TOP") == [row]
    db.reject_player("br1", "P1")
    assert db.confirmed_matches(79, "TOP") == []


def test_timelines_for_crosses_chunk_boundary(db):
    ids = [f"BR1_{i}" for i in range(1203)]
    for mid in ids:
        db.insert_timeline(make_timeline(mid, "P1"))
    result = db.timelines_for(ids)
    assert len(result) == 1203
    assert result[("BR1_1202", "P1")].match_id == "BR1_1202"


# --- timelines Riot has none of, or that we could not parse ------------------


def test_marked_missing_timeline_is_no_longer_awaiting(db):
    for mid in ("BR1_1", "BR1_2"):
        db.insert_match(make_row(match_id=mid, puuid="P1"))
    db.confirm_player("br1", "P1", "A#BR1", 79, "TOP", 30, 0.6)
    db.mark_timeline_missing("BR1_1", "P1", "not_found")
    assert db.matches_awaiting_timeline() == [("BR1_2", "P1", "OPP-P1")]


def test_marking_missing_is_per_puuid_and_idempotent(db):
    db.insert_match(make_row(match_id="BR1_1", puuid="P1"))
    db.insert_match(make_row(match_id="BR1_1", puuid="P2"))
    db.confirm_player("br1", "P1", "A#BR1", 79, "TOP", 30, 0.6)
    db.confirm_player("br1", "P2", "B#BR1", 79, "TOP", 30, 0.6)
    db.mark_timeline_missing("BR1_1", "P1", "not_found")
    db.mark_timeline_missing("BR1_1", "P1", "parse_error")  # no error, no duplicate
    assert db.matches_awaiting_timeline() == [("BR1_1", "P2", "OPP-P2")]


def test_missing_marker_does_not_create_a_timeline_row(db):
    db.insert_match(make_row(match_id="BR1_1", puuid="P1"))
    db.mark_timeline_missing("BR1_1", "P1", "not_found")
    assert db.timelines_for(["BR1_1"]) == {}


def test_missing_marker_survives_a_new_connection(tmp_path):
    first = Database(tmp_path / "a.db")
    first.init_schema()
    first.insert_match(make_row(match_id="BR1_1", puuid="P1"))
    first.confirm_player("br1", "P1", "A#BR1", 79, "TOP", 30, 0.6)
    first.mark_timeline_missing("BR1_1", "P1", "not_found")
    first.commit()
    first.close()
    second = Database(tmp_path / "a.db")
    try:
        assert second.matches_awaiting_timeline() == []
    finally:
        second.close()


def test_matches_awaiting_timeline_can_be_limited_to_a_platform(db):
    db.insert_match(make_row(match_id="BR1_1", puuid="P1"))
    db.insert_match(dataclasses.replace(make_row(match_id="KR_1", puuid="P2"), platform="kr"))
    db.confirm_player("br1", "P1", "A#BR1", 79, "TOP", 30, 0.6)
    db.confirm_player("kr", "P2", "B#KR", 79, "TOP", 30, 0.6)
    assert db.matches_awaiting_timeline("br1") == [("BR1_1", "P1", "OPP-P1")]
    assert db.matches_awaiting_timeline("kr") == [("KR_1", "P2", "OPP-P2")]
    assert len(db.matches_awaiting_timeline()) == 2


def test_init_schema_refuses_a_timeline_table_from_before_the_skill_order_fix(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE timeline (match_id TEXT NOT NULL, puuid TEXT NOT NULL, "
        "gold_at_14 INTEGER, cs_diff_at_14 INTEGER, starting_items TEXT NOT NULL, "
        "item_order TEXT NOT NULL, skill_order TEXT NOT NULL, "
        "deaths_before_10 INTEGER NOT NULL, kills_before_10 INTEGER NOT NULL, "
        "PRIMARY KEY (match_id, puuid));"
    )
    old.close()
    stale = Database(path)
    try:
        with pytest.raises(SchemaError, match="skill_order"):
            stale.init_schema()
        # Refused before anything is created: the file is left as it was found.
        assert stale.table_names() == ["timeline"]
    finally:
        stale.close()
