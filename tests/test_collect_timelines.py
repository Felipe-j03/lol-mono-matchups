import copy
import dataclasses
import gzip
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

from lolmono.__main__ import RAW_SAMPLE_SUBDIR, main
from lolmono.collect import (
    CONSECUTIVE_FAILURE_LIMIT,
    ExtractionFailing,
    TimelineReport,
    collect_timelines,
)
from lolmono.db import Database
from lolmono.riot import RiotError
from lolmono.rows import MatchRow, RunePage

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
FULL = json.loads((FIXTURES / "timeline_full.json").read_text(encoding="utf-8"))

# timeline_full.json has "ME" and "THEM" in metadata.participants.
# info.gameCreation of the fixtures, epoch ms (2025-11-02 00:00 UTC).
GAME_CREATED = 1_762_041_600_000

HERO, FOE = "ME", "THEM"


def timeline_payload(match_id):
    payload = copy.deepcopy(FULL)
    payload["metadata"]["matchId"] = match_id
    return payload


def match_row(
    match_id, puuid=HERO, opponent=FOE, platform="br1", champion_id=91,
    created=GAME_CREATED,
):
    return MatchRow(
        match_id=match_id,
        platform=platform,
        puuid=puuid,
        game_created=created,
        champion_id=champion_id,
        role="MIDDLE",
        opponent_champion_id=245,
        opponent_puuid=opponent,
        win=True,
        items=(3068,),
        runes=RunePage(8112, 8100, (8112, 8126, 8138), 8200, (8226, 8236), (5008, 5008, 5002)),
        spells=(4, 14),
    )


class FakeClient:
    """Serves timelines by match id; None means Riot answered 404."""

    def __init__(self, payloads):
        self._payloads = payloads
        self.timeline_calls = []
        self.watch_db = None
        self.batch_state = None
        self.open_transaction_seen = False
        self.fail_on_call = None

    def timeline(self, match_id):
        if self.watch_db is not None and self.watch_db._conn.in_transaction:
            self.open_transaction_seen = True
        if self.batch_state is not None and self.batch_state["inside"]:
            self.open_transaction_seen = True
        self.timeline_calls.append(match_id)
        if self.fail_on_call == len(self.timeline_calls):
            raise RiotError("HTTP 403 for /lol/match/v5/matches/x/timeline")
        return self._payloads.get(match_id)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "lol.db")
    database.init_schema()
    yield database
    database.close()


def seed(db, *match_ids, puuid=HERO, opponent=FOE, platform="br1"):
    """Confirm ``puuid`` and store one match row per id."""
    for match_id in match_ids:
        db.insert_match(match_row(match_id, puuid, opponent, platform))
    db.confirm_player(platform, puuid, "x#BR1", 91, "MIDDLE", 30, 0.6)
    db.commit()


def served(*match_ids):
    return FakeClient({m: timeline_payload(m) for m in match_ids})


def track_batches(db, fake):
    state = {"inside": False}
    original = db.batch

    @contextmanager
    def tracked():
        state["inside"] = True
        try:
            with original():
                yield
        finally:
            state["inside"] = False

    db.batch = tracked
    fake.batch_state = state


def test_only_confirmed_matches_get_timelines(db):
    seed(db, "BR1_confirmed")
    db.insert_match(match_row("BR1_other", puuid="STRANGER", opponent="FOE2"))
    db.reject_player("br1", "STRANGER")
    db.commit()
    fake = served("BR1_confirmed", "BR1_other")
    report = collect_timelines(fake, db, "br1")
    assert fake.timeline_calls == ["BR1_confirmed"]
    assert report.requested == 1


def test_extracted_timeline_is_stored_as_a_row(db):
    seed(db, "BR1_1")
    report = collect_timelines(served("BR1_1"), db, "br1")
    assert report == TimelineReport(requested=1, extracted=1, missing=0, failed=0)
    [row] = db.timelines_for(["BR1_1"]).values()
    assert (row.match_id, row.puuid) == ("BR1_1", HERO)


def test_missing_timeline_is_counted_not_fatal(db):
    seed(db, "BR1_1")
    report = collect_timelines(FakeClient({}), db, "br1")  # Riot answers 404
    assert report == TimelineReport(requested=1, extracted=0, missing=1, failed=0)


def test_missing_timeline_stores_no_fabricated_row(db):
    seed(db, "BR1_1")
    collect_timelines(FakeClient({}), db, "br1")
    assert db.timelines_for(["BR1_1"]) == {}


def test_a_404_is_never_requested_again(db):
    seed(db, "BR1_1")
    collect_timelines(FakeClient({}), db, "br1")
    again = FakeClient({"BR1_1": timeline_payload("BR1_1")})
    report = collect_timelines(again, db, "br1")
    assert report.requested == 0
    assert again.timeline_calls == []


def test_a_parse_failure_is_counted_as_failed_not_missing(db):
    seed(db, "BR1_1")
    broken = timeline_payload("BR1_1")
    del broken["info"]
    report = collect_timelines(FakeClient({"BR1_1": broken}), db, "br1")
    assert report == TimelineReport(requested=1, extracted=0, missing=0, failed=1)
    assert db.timelines_for(["BR1_1"]) == {}


def test_a_parse_failure_is_never_requested_again(db):
    seed(db, "BR1_1")
    broken = timeline_payload("BR1_1")
    del broken["info"]
    collect_timelines(FakeClient({"BR1_1": broken}), db, "br1")
    again = served("BR1_1")
    assert collect_timelines(again, db, "br1").requested == 0
    assert again.timeline_calls == []


def test_a_payload_without_the_tracked_player_is_a_failure(db):
    seed(db, "BR1_1", puuid="NOT_IN_PAYLOAD")
    report = collect_timelines(served("BR1_1"), db, "br1")
    assert (report.extracted, report.missing, report.failed) == (0, 0, 1)


def test_one_bad_payload_does_not_stop_the_run(db):
    seed(db, "BR1_1", "BR1_2", "BR1_3")
    broken = timeline_payload("BR1_2")
    broken["metadata"] = None
    fake = FakeClient(
        {"BR1_1": timeline_payload("BR1_1"), "BR1_2": broken, "BR1_3": timeline_payload("BR1_3")}
    )
    report = collect_timelines(fake, db, "br1")
    assert (report.requested, report.extracted, report.failed) == (3, 2, 1)


def test_resumes_without_refetching_extracted_timelines(db):
    seed(db, "BR1_1", "BR1_2")
    collect_timelines(served("BR1_1", "BR1_2"), db, "br1")
    again = served("BR1_1", "BR1_2")
    assert collect_timelines(again, db, "br1").requested == 0
    assert again.timeline_calls == []


def test_only_the_given_platform_is_requested(db):
    seed(db, "BR1_1")
    seed(db, "KR_1", puuid="KRPLAYER", platform="kr")
    fake = served("BR1_1", "KR_1")
    collect_timelines(fake, db, "br1")
    assert fake.timeline_calls == ["BR1_1"]
    # The other platform is still waiting for its own run.
    assert db.matches_awaiting_timeline("kr") == [("KR_1", "KRPLAYER", FOE)]


def test_a_match_with_two_tracked_players_is_requested_once(db):
    seed(db, "BR1_1")
    db.insert_match(match_row("BR1_1", puuid=FOE, opponent=HERO))
    db.confirm_player("br1", FOE, "y#BR1", 91, "MIDDLE", 30, 0.6)
    db.commit()
    fake = served("BR1_1")
    report = collect_timelines(fake, db, "br1")
    assert fake.timeline_calls == ["BR1_1"]
    assert report.extracted == 2
    assert set(db.timelines_for(["BR1_1"])) == {("BR1_1", HERO), ("BR1_1", FOE)}


def test_raw_sample_is_written_when_directory_given(db, tmp_path):
    seed(db, "BR1_1")
    sample = tmp_path / "raw"
    collect_timelines(served("BR1_1"), db, "br1", raw_sample_dir=sample)
    [path] = sample.glob("*.json.gz")
    assert json.loads(gzip.decompress(path.read_bytes())) == timeline_payload("BR1_1")


def test_nothing_is_written_when_no_directory_is_given(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seed(db, "BR1_1")
    collect_timelines(served("BR1_1"), db, "br1")
    assert list(tmp_path.rglob("*.json.gz")) == []


def test_raw_sample_keeps_only_the_first_200(db, tmp_path):
    ids = [f"BR1_{i:04d}" for i in range(205)]
    seed(db, *ids)
    sample = tmp_path / "raw"
    collect_timelines(served(*ids), db, "br1", raw_sample_dir=sample)
    assert len(list(sample.glob("*.json.gz"))) == 200


def test_raw_sample_limit_counts_files_from_earlier_runs(db, tmp_path):
    sample = tmp_path / "raw"
    sample.mkdir()
    for i in range(200):
        (sample / f"OLD_{i}.json.gz").write_bytes(b"")
    seed(db, "BR1_1")
    collect_timelines(served("BR1_1"), db, "br1", raw_sample_dir=sample)
    assert not (sample / "BR1_1.json.gz").exists()


def test_raw_sample_includes_payloads_that_failed_to_parse(db, tmp_path):
    seed(db, "BR1_1")
    broken = timeline_payload("BR1_1")
    del broken["info"]
    sample = tmp_path / "raw"
    collect_timelines(FakeClient({"BR1_1": broken}), db, "br1", raw_sample_dir=sample)
    assert len(list(sample.glob("*.json.gz"))) == 1


def test_no_write_transaction_is_held_across_a_request(db):
    ids = [f"BR1_{i:03d}" for i in range(120)]
    seed(db, *ids)
    fake = served(*ids)
    fake.watch_db = db
    track_batches(db, fake)
    collect_timelines(fake, db, "br1")
    assert len(fake.timeline_calls) == 120
    assert fake.open_transaction_seen is False


def test_writes_are_committed_in_batches_of_fifty(db):
    ids = [f"BR1_{i:03d}" for i in range(120)]
    seed(db, *ids)
    batches = []
    original = db.batch

    @contextmanager
    def counting():
        batches.append(1)
        with original():
            yield

    db.batch = counting
    collect_timelines(served(*ids), db, "br1")
    assert len(batches) == 3  # 50 + 50 + 20


def test_a_riot_error_keeps_what_was_already_paid_for(db):
    ids = ["BR1_1", "BR1_2", "BR1_3", "BR1_4"]
    seed(db, *ids)
    fake = served(*ids)
    fake.fail_on_call = 3
    with pytest.raises(RiotError):
        collect_timelines(fake, db, "br1")
    assert set(db.timelines_for(ids)) == {("BR1_1", HERO), ("BR1_2", HERO)}
    resumed = served(*ids)
    report = collect_timelines(resumed, db, "br1")
    assert resumed.timeline_calls == ["BR1_3", "BR1_4"]
    assert report.requested == 2


def marked(db):
    return {
        (r["match_id"], r["puuid"]): r["reason"]
        for r in db._conn.execute("SELECT match_id, puuid, reason FROM timeline_missing")
    }


def broken_payload(match_id):
    payload = timeline_payload(match_id)
    del payload["info"]
    return payload


def test_markers_carry_the_right_reason_for_404_and_for_parse_failure(db):
    seed(db, "BR1_404", "BR1_BAD", "BR1_OK")
    fake = FakeClient({"BR1_BAD": broken_payload("BR1_BAD"), "BR1_OK": timeline_payload("BR1_OK")})
    collect_timelines(fake, db, "br1")
    assert marked(db) == {
        ("BR1_404", HERO): "not_found",
        ("BR1_BAD", HERO): "parse_error",
    }


def test_consecutive_extraction_failures_abort_without_marking_them(db):
    good = [f"BR1_{i:03d}" for i in range(3)]
    bad = [f"BR1_{i:03d}" for i in range(3, 3 + CONSECUTIVE_FAILURE_LIMIT + 5)]
    seed(db, *good, *bad)
    fake = FakeClient(
        {**{m: timeline_payload(m) for m in good}, **{m: broken_payload(m) for m in bad}}
    )
    with pytest.raises(ExtractionFailing):
        collect_timelines(fake, db, "br1")
    # It stops paying as soon as the limit is hit.
    assert len(fake.timeline_calls) == len(good) + CONSECUTIVE_FAILURE_LIMIT
    # What was fine is kept; the failures that tripped it are not marked...
    assert set(db.timelines_for(good + bad)) == {(m, HERO) for m in good}
    assert marked(db) == {}
    # ...so they stay queued, along with the matches never requested.
    assert [m for m, _, _ in db.matches_awaiting_timeline("br1")] == bad


def test_failures_interleaved_with_successes_do_not_abort(db):
    limit = CONSECUTIVE_FAILURE_LIMIT
    ids = [f"BR1_{i:03d}" for i in range(2 * limit + 5)]
    good = {ids[limit - 1], ids[2 * limit - 1]}  # streaks of limit - 1, then 5 at the end
    seed(db, *ids)
    fake = FakeClient(
        {m: timeline_payload(m) if m in good else broken_payload(m) for m in ids}
    )
    report = collect_timelines(fake, db, "br1")
    assert report == TimelineReport(
        requested=len(ids), extracted=2, missing=0, failed=len(ids) - 2
    )
    # A short failure streak at the very end is real: those are marked.
    assert len(marked(db)) == len(ids) - 2
    assert db.matches_awaiting_timeline("br1") == []


def test_a_404_does_not_reset_the_failure_streak(db):
    ids = [f"BR1_{i:03d}" for i in range(CONSECUTIVE_FAILURE_LIMIT + 1)]
    seed(db, *ids)
    payloads = {m: broken_payload(m) for m in ids}
    del payloads[ids[5]]  # Riot answers 404 for this one
    with pytest.raises(ExtractionFailing):
        collect_timelines(FakeClient(payloads), db, "br1")


def test_cli_aborts_on_systematic_extraction_failure(tmp_path, capsys):
    ids = [f"BR1_{i:03d}" for i in range(CONSECUTIVE_FAILURE_LIMIT + 3)]
    seed_cli_db(tmp_path, *ids)
    fake = FakeClient({m: broken_payload(m) for m in ids})
    code = cli(["timelines", "--platform", "br1"], tmp_path, client=fake)
    err = capsys.readouterr().err
    assert code == 1
    assert "sistematica" in err
    assert "Nada foi marcado" in err
    reopened = Database(tmp_path / "cli.db")
    try:
        assert marked(reopened) == {}
        assert len(reopened.matches_awaiting_timeline("br1")) == len(ids)
    finally:
        reopened.close()


def test_timeline_report_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        TimelineReport(1, 1, 0, 0).requested = 2


# --- CLI -----------------------------------------------------------------


def cli(args, tmp_path, client=None):
    argv = [*args, "--config", str(ROOT / "config.example.toml"), "--db", str(tmp_path / "cli.db")]
    return main(argv, environ={"RIOT_API_KEY": "chave-de-teste"}, client_factory=lambda p, k: client)


def seed_cli_db(tmp_path, *match_ids):
    seeded = Database(tmp_path / "cli.db")
    seeded.init_schema()
    seed(seeded, *match_ids)
    seeded.close()


def test_cli_timelines_prints_the_four_figures(tmp_path, capsys):
    seed_cli_db(tmp_path, "BR1_1", "BR1_2", "BR1_3")
    broken = timeline_payload("BR1_3")
    del broken["info"]
    fake = FakeClient({"BR1_1": timeline_payload("BR1_1"), "BR1_3": broken})
    code = cli(["timelines", "--platform", "br1"], tmp_path, client=fake)
    captured = capsys.readouterr()
    assert code == 0
    assert "br1" in captured.out
    assert "pedidas: 3" in captured.out
    assert "extraidas: 1" in captured.out
    assert "ausentes: 1" in captured.out
    assert "falhas: 1" in captured.out
    assert "chave-de-teste" not in captured.out + captured.err


def test_cli_warns_on_stderr_when_extractions_failed(tmp_path, capsys):
    seed_cli_db(tmp_path, "BR1_1")
    broken = timeline_payload("BR1_1")
    del broken["info"]
    cli(["timelines", "--platform", "br1"], tmp_path, client=FakeClient({"BR1_1": broken}))
    assert "falha" in capsys.readouterr().err.lower()


def test_cli_does_not_warn_when_nothing_failed(tmp_path, capsys):
    seed_cli_db(tmp_path, "BR1_1")
    cli(["timelines", "--platform", "br1"], tmp_path, client=served("BR1_1"))
    assert capsys.readouterr().err == ""


def test_cli_raw_sample_dir_flag(tmp_path):
    seed_cli_db(tmp_path, "BR1_1")
    sample = tmp_path / "raw"
    cli(
        ["timelines", "--platform", "br1", "--raw-sample-dir", str(sample)],
        tmp_path,
        client=served("BR1_1"),
    )
    assert len(list(sample.glob("*.json.gz"))) == 1


def test_cli_timelines_riot_error_exits_1_and_keeps_progress(tmp_path, capsys):
    seed_cli_db(tmp_path, "BR1_1", "BR1_2")
    fake = served("BR1_1", "BR1_2")
    fake.fail_on_call = 2
    code = cli(["timelines", "--platform", "br1"], tmp_path, client=fake)
    err = capsys.readouterr().err
    assert code == 1
    assert "HTTP 403" in err and "chave-de-teste" not in err
    reopened = Database(tmp_path / "cli.db")
    try:
        assert set(reopened.timelines_for(["BR1_1", "BR1_2"])) == {("BR1_1", HERO)}
    finally:
        reopened.close()


def test_cli_refuses_a_database_with_the_old_timeline_schema(tmp_path, capsys):
    old = sqlite3.connect(tmp_path / "cli.db")
    old.executescript(
        "CREATE TABLE timeline (match_id TEXT NOT NULL, puuid TEXT NOT NULL, "
        "gold_at_14 INTEGER, cs_diff_at_14 INTEGER, starting_items TEXT NOT NULL, "
        "item_order TEXT NOT NULL, skill_order TEXT NOT NULL, "
        "deaths_before_10 INTEGER NOT NULL, kills_before_10 INTEGER NOT NULL, "
        "PRIMARY KEY (match_id, puuid));"
    )
    old.close()
    fake = FakeClient({})
    code = cli(["timelines", "--platform", "br1"], tmp_path, client=fake)
    err = capsys.readouterr().err
    assert code == 2
    assert "skill_order" in err
    assert fake.timeline_calls == []


# --- the raw sample is kept by default --------------------------------------


def test_cli_keeps_the_raw_sample_without_being_asked(tmp_path, capsys):
    # The spec treats the compressed raw sample as something that happens, not
    # as an extra: it is the project's only check on its own extraction. An
    # operator following the documented commands must not end up with zero
    # payloads.
    seed_cli_db(tmp_path, "BR1_1")
    code = cli(["timelines", "--platform", "br1"], tmp_path, client=served("BR1_1"))
    assert code == 0
    default = tmp_path / RAW_SAMPLE_SUBDIR
    assert len(list(default.glob("*.json.gz"))) == 1
    assert str(default) in capsys.readouterr().out  # and it says where


def test_cli_no_raw_sample_is_an_explicit_opt_out(tmp_path, capsys):
    seed_cli_db(tmp_path, "BR1_1")
    code = cli(
        ["timelines", "--platform", "br1", "--no-raw-sample"],
        tmp_path,
        client=served("BR1_1"),
    )
    assert code == 0
    assert not (tmp_path / RAW_SAMPLE_SUBDIR).exists()
    assert "desligada" in capsys.readouterr().out  # the loss is stated


def test_cli_raw_sample_dir_overrides_the_default(tmp_path):
    seed_cli_db(tmp_path, "BR1_1")
    sample = tmp_path / "elsewhere"
    cli(
        ["timelines", "--platform", "br1", "--raw-sample-dir", str(sample)],
        tmp_path,
        client=served("BR1_1"),
    )
    assert len(list(sample.glob("*.json.gz"))) == 1
    assert not (tmp_path / RAW_SAMPLE_SUBDIR).exists()


def test_cli_a_locked_database_is_reported_not_a_traceback(tmp_path, capsys):
    # The spec runs four regions in parallel against one file. After the
    # connection timeout this is the exception they produce.
    seed_cli_db(tmp_path, "BR1_1")

    class Locked:
        def timeline(self, match_id):
            raise sqlite3.OperationalError("database is locked")

    code = cli(["timelines", "--platform", "br1"], tmp_path, client=Locked())
    err = capsys.readouterr().err
    assert code == 1
    assert "database is locked" in err
    assert "paralelo" in err
    assert "chave-de-teste" not in err
