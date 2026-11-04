import copy
import dataclasses
import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from lolmono.__main__ import main
from lolmono.collect import (
    CONSECUTIVE_FAILURE_LIMIT,
    ExtractionFailing,
    MatchReport,
    collect_matches,
)
from lolmono.config import load_config
from lolmono.db import Database
from lolmono.matchparse import extract_match
from lolmono.riot import RiotError

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
TALON = 91
ZED = 238
EKKO = 245

cfg = load_config(ROOT / "config.example.toml")
CLEAN = json.loads((FIXTURES / "match_clean.json").read_text(encoding="utf-8"))

HERO = "TALON_PLAYER"  # MIDDLE, team 100, in the fixture


def payload(match_id, puuid, champion_id=TALON, win=True):
    """The clean fixture with the tracked mid laner renamed and re-championed."""
    match = copy.deepcopy(CLEAN)
    match["metadata"]["matchId"] = match_id
    hero = next(p for p in match["info"]["participants"] if p["puuid"] == HERO)
    hero["puuid"] = puuid
    hero["championId"] = champion_id
    hero["win"] = win
    return match


def broken(match_id, puuid, how):
    match = payload(match_id, puuid)
    if how == "unpaired":
        top = next(p for p in match["info"]["participants"] if p["puuid"] == "TOP_200")
        top["teamPosition"] = "MIDDLE"
    elif how == "missing_position":
        next(p for p in match["info"]["participants"] if p["puuid"] == "TOP_200")[
            "teamPosition"
        ] = ""
    elif how == "wrong_queue":
        match["info"]["queueId"] = 450
    elif how == "puuid_absent":
        match["info"]["participants"] = [
            p for p in match["info"]["participants"] if p["puuid"] != puuid
        ]
    elif how == "no_info":
        del match["info"]
    elif how == "null_info":
        match["info"] = None
    elif how in ("empty_styles", "empty_selections", "platform_not_a_string"):
        participant = next(p for p in match["info"]["participants"] if p["puuid"] == puuid)
        if how == "empty_styles":
            participant["perks"]["styles"] = []
        elif how == "empty_selections":
            participant["perks"]["styles"][0]["selections"] = []
        else:
            match["info"]["platformId"] = None
    elif how == "no_perks":
        next(p for p in match["info"]["participants"] if p["puuid"] == puuid).pop("perks")
    else:
        raise AssertionError(how)
    return match


class FakeClient:
    def __init__(self, ids, matches, riot_ids=None):
        self._ids = ids
        self._matches = matches
        self._riot_ids = riot_ids or {}
        self.id_requests = []
        self.match_requests = []
        self.riot_id_requests = []
        self.watch_db = None
        self.batch_state = None  # {"inside": bool}, kept by track_batches()
        self.open_transaction_seen = False
        self.fail_on_match = None

    def _watch(self):
        if self.watch_db is not None and self.watch_db._conn.in_transaction:
            self.open_transaction_seen = True
        if self.batch_state is not None and self.batch_state["inside"]:
            self.open_transaction_seen = True

    def match_ids(self, puuid, count, queue=420):
        self._watch()
        self.id_requests.append((puuid, count, queue))
        return list(self._ids[puuid])[:count]  # the real API honours count

    def match(self, match_id):
        self._watch()
        self.match_requests.append(match_id)
        if self.fail_on_match == len(self.match_requests):
            raise RuntimeError("rede caiu")
        return self._matches[match_id]

    def riot_id(self, puuid):
        self._watch()
        self.riot_id_requests.append(puuid)
        return self._riot_ids[puuid]


def track_batches(db, fake):
    """Make ``fake`` notice any request issued while ``db.batch()`` is active.

    ``in_transaction`` alone misses a request made inside a batch before its
    first write, so the batch itself is observed too.
    """
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


def world():
    """TALONER is a real Talon mono; ZEDDER plays a champion nobody tracks."""
    ids, matches = {}, {}

    def add(puuid, prefix, count, champion_id):
        ids.setdefault(puuid, [])
        for i in range(count):
            mid = f"BR1_{prefix}{i:03d}"
            ids[puuid].append(mid)
            matches[mid] = payload(mid, puuid, champion_id)

    add("TALONER", "T", 30, TALON)
    add("TALONER", "TO", 30, EKKO)
    add("ZEDDER", "Z", 40, ZED)
    return FakeClient(ids, matches, {"TALONER": "Talonero#BR1"}), ids, matches


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "lol.db")
    database.init_schema()
    yield database
    database.close()


def suspects(db, *puuids, platform="br1"):
    db.add_candidates(platform, list(puuids))
    for puuid in puuids:
        db.mark_screened(platform, puuid, True)
    db.commit()


def test_collect_matches_confirms_and_rejects_players(db):
    fake, _, _ = world()
    suspects(db, "TALONER", "ZEDDER")
    report = collect_matches(fake, db, cfg, "br1")
    assert report.players == 2
    assert report.confirmed == 1
    assert db.confirmed_matches(TALON, "MIDDLE")
    assert db.pending_suspects("br1") == []


def test_confirmed_player_is_stored_with_target_games_share_and_riot_id(db):
    fake, _, _ = world()
    suspects(db, "TALONER", "ZEDDER")
    collect_matches(fake, db, cfg, "br1")
    [player] = db.confirmed_players(TALON, "MIDDLE")
    assert (player.puuid, player.riot_id, player.role) == ("TALONER", "Talonero#BR1", "MIDDLE")
    assert (player.games, player.share) == (30, 0.5)
    assert len(db.confirmed_matches(TALON, "MIDDLE")) == 30


def test_rejected_player_matches_are_excluded_from_aggregation(db):
    fake, _, _ = world()
    suspects(db, "TALONER", "ZEDDER")
    report = collect_matches(fake, db, cfg, "br1")
    assert db.confirmed_matches(ZED, "MIDDLE") == []
    assert db.confirmed_player_count(ZED, "MIDDLE") == 0
    assert db.confirmed_players(ZED, "MIDDLE") == []
    assert db.confirmed_group_win_rate(ZED, "MIDDLE") == 0.0
    assert db.matches_awaiting_timeline() == [
        (m, "TALONER", "EKKO_PLAYER") for m in sorted(db_ids(db, "TALONER", TALON))
    ]
    # Still on disk (they were fetched and paid for), just never aggregated.
    assert db.match_exists("BR1_Z000", "ZEDDER")
    assert report.matches == 100


def db_ids(db, puuid, champion_id):
    return [m.match_id for m in db.confirmed_matches(champion_id, "MIDDLE") if m.puuid == puuid]


def test_riot_id_is_requested_only_for_confirmed_players(db):
    fake, _, _ = world()
    suspects(db, "TALONER", "ZEDDER")
    collect_matches(fake, db, cfg, "br1")
    assert fake.riot_id_requests == ["TALONER"]


def test_requests_the_configured_window_of_ranked_solo_matches(db):
    fake, _, _ = world()
    suspects(db, "TALONER", "ZEDDER")
    collect_matches(fake, db, cfg, "br1")
    assert sorted(fake.id_requests) == sorted(
        [("TALONER", cfg.window_games, 420), ("ZEDDER", cfg.window_games, 420)]
    )


def test_the_window_decides_by_recency_order_of_the_ids(db):
    # 25 Talon games, but only after 60 newer Ekko games: outside the window.
    ids = {"OLDMONO": [f"BR1_N{i:03d}" for i in range(60)] + [f"BR1_O{i:03d}" for i in range(25)]}
    matches = {m: payload(m, "OLDMONO", EKKO) for m in ids["OLDMONO"][:60]}
    matches.update({m: payload(m, "OLDMONO", TALON) for m in ids["OLDMONO"][60:]})
    fake = FakeClient(ids, matches)
    suspects(db, "OLDMONO")
    report = collect_matches(fake, db, cfg, "br1")
    assert report.confirmed == 0
    assert fake.riot_id_requests == []


def test_a_player_meeting_only_the_share_condition_is_rejected(db):
    ids = {"FEW": [f"BR1_F{i:03d}" for i in range(12)]}
    matches = {m: payload(m, "FEW", TALON) for m in ids["FEW"]}  # 100% but 12 games
    fake = FakeClient(ids, matches)
    suspects(db, "FEW")
    assert collect_matches(fake, db, cfg, "br1").confirmed == 0
    assert db.confirmed_matches(TALON, "MIDDLE") == []


def test_a_player_meeting_only_the_absolute_minimum_is_rejected(db):
    ids = {"DIFFUSE": [f"BR1_D{i:03d}" for i in range(60)]}
    matches = {
        m: payload(m, "DIFFUSE", TALON if i < 25 else EKKO)
        for i, m in enumerate(ids["DIFFUSE"])
    }
    fake = FakeClient(ids, matches)
    suspects(db, "DIFFUSE")
    assert collect_matches(fake, db, cfg, "br1").confirmed == 0


def test_discarded_matches_are_counted_not_raised(db):
    fake, ids, matches = world()
    matches["BR1_Z000"] = broken("BR1_Z000", "ZEDDER", "unpaired")
    suspects(db, "TALONER", "ZEDDER")
    report = collect_matches(fake, db, cfg, "br1")
    assert report.discarded["unpaired_lanes"] == 1
    assert report.matches == 99
    assert db.discard_counts() == {"unpaired_lanes": 1}


@pytest.mark.parametrize(
    "how, reason",
    [
        ("unpaired", "unpaired_lanes"),
        ("missing_position", "missing_position"),
        ("wrong_queue", "wrong_queue"),
        ("puuid_absent", "puuid_absent"),
        ("no_info", "malformed_payload"),
        ("null_info", "malformed_payload"),
        ("no_perks", "malformed_payload"),
        ("empty_styles", "malformed_payload"),
        ("empty_selections", "malformed_payload"),
        ("platform_not_a_string", "malformed_payload"),
    ],
)
def test_every_failure_kind_is_a_counted_discard_and_the_run_continues(db, how, reason):
    fake, ids, matches = world()
    matches["BR1_Z000"] = broken("BR1_Z000", "ZEDDER", how)
    suspects(db, "ZEDDER", "TALONER")
    report = collect_matches(fake, db, cfg, "br1")
    assert report.discarded == {reason: 1}
    assert db.discard_counts() == {reason: 1}
    assert report.players == 2 and report.confirmed == 1  # the run went on
    # Both players were decided: a deterministic bad payload must not leave a
    # player pending, or every rerun would die at the same one.
    assert db.pending_suspects("br1") == []


def test_discards_are_broken_down_by_reason(db):
    fake, ids, matches = world()
    matches["BR1_Z000"] = broken("BR1_Z000", "ZEDDER", "unpaired")
    matches["BR1_Z001"] = broken("BR1_Z001", "ZEDDER", "no_info")
    matches["BR1_Z002"] = broken("BR1_Z002", "ZEDDER", "no_info")
    suspects(db, "ZEDDER")
    report = collect_matches(fake, db, cfg, "br1")
    assert report.discarded == {"unpaired_lanes": 1, "malformed_payload": 2}


def test_a_clean_run_reports_no_discards(db):
    fake, _, _ = world()
    suspects(db, "TALONER")
    assert collect_matches(fake, db, cfg, "br1").discarded == {}


def test_malformed_payload_is_not_confused_with_a_player_level_failure(db):
    # A broken payload for the *only* match: no rows, player rejected, no crash.
    ids = {"X": ["BR1_X000"]}
    fake = FakeClient(ids, {"BR1_X000": broken("BR1_X000", "X", "no_info")})
    suspects(db, "X")
    report = collect_matches(fake, db, cfg, "br1")
    assert (report.players, report.confirmed, report.matches) == (1, 0, 0)
    assert report.discarded == {"malformed_payload": 1}


class NameFails(FakeClient):
    def riot_id(self, puuid):
        super().riot_id(puuid)
        raise RiotError("HTTP 404 for /riot/account/v1/accounts/by-puuid/x")


def test_a_failing_name_lookup_confirms_the_player_with_an_empty_name(db):
    fake, ids, matches = world()
    fake = NameFails(ids, matches, {"TALONER": "unused"})
    suspects(db, "TALONER", "ZEDDER")
    report = collect_matches(fake, db, cfg, "br1")
    assert (report.players, report.confirmed, report.unnamed) == (2, 1, 1)
    [player] = db.confirmed_players(TALON, "MIDDLE")
    assert (player.puuid, player.riot_id, player.games) == ("TALONER", "", 30)
    assert len(db.confirmed_matches(TALON, "MIDDLE")) == 30
    assert db.pending_suspects("br1") == []


class NameBodyMalformed(FakeClient):
    def riot_id(self, puuid):
        super().riot_id(puuid)
        raise KeyError("gameName")  # what RiotClient.riot_id raises on a bad body


def test_a_malformed_name_response_confirms_the_player_with_an_empty_name(db):
    fake, ids, matches = world()
    fake = NameBodyMalformed(ids, matches, {"TALONER": "unused"})
    suspects(db, "TALONER", "ZEDDER")
    report = collect_matches(fake, db, cfg, "br1")
    assert (report.players, report.confirmed, report.unnamed) == (2, 1, 1)
    [player] = db.confirmed_players(TALON, "MIDDLE")
    assert (player.puuid, player.riot_id, player.games) == ("TALONER", "", 30)
    assert len(db.confirmed_matches(TALON, "MIDDLE")) == 30
    assert db.pending_suspects("br1") == []


class NameBodyNotJson(FakeClient):
    def riot_id(self, puuid):
        super().riot_id(puuid)
        raise ValueError("Expecting value: line 1 column 1")  # json.JSONDecodeError's base


def test_a_non_json_name_response_confirms_the_player_with_an_empty_name(db):
    fake, ids, matches = world()
    fake = NameBodyNotJson(ids, matches, {"TALONER": "unused"})
    suspects(db, "TALONER", "ZEDDER")
    report = collect_matches(fake, db, cfg, "br1")
    assert (report.players, report.confirmed, report.unnamed) == (2, 1, 1)
    [player] = db.confirmed_players(TALON, "MIDDLE")
    assert (player.puuid, player.riot_id, player.games) == ("TALONER", "", 30)
    assert len(db.confirmed_matches(TALON, "MIDDLE")) == 30
    assert db.pending_suspects("br1") == []


def test_named_players_are_not_counted_as_unnamed(db):
    fake, _, _ = world()
    suspects(db, "TALONER")
    assert collect_matches(fake, db, cfg, "br1").unnamed == 0


def test_matches_already_stored_are_not_requested_again(db):
    fake, ids, matches = world()
    stored = extract_match(matches["BR1_Z000"], "ZEDDER")
    db.insert_match(stored)
    db.commit()
    suspects(db, "ZEDDER")
    collect_matches(fake, db, cfg, "br1")
    assert "BR1_Z000" not in fake.match_requests
    assert len(fake.match_requests) == 39


def test_two_tracked_players_in_the_same_match_each_get_their_own_row(db):
    shared = payload("BR1_S000", "ALPHA", TALON)
    # The opposing mid laner of the fixture is the second tracked player.
    next(p for p in shared["info"]["participants"] if p["puuid"] == "EKKO_PLAYER")["puuid"] = "BETA"
    fake = FakeClient({"ALPHA": ["BR1_S000"], "BETA": ["BR1_S000"]}, {"BR1_S000": shared})
    suspects(db, "ALPHA", "BETA")
    report = collect_matches(fake, db, cfg, "br1")
    assert report.matches == 2
    assert fake.match_requests == ["BR1_S000", "BR1_S000"]
    assert db.match_exists("BR1_S000", "ALPHA") and db.match_exists("BR1_S000", "BETA")


def test_resuming_does_not_reprocess_decided_players(db):
    fake, _, _ = world()
    suspects(db, "TALONER", "ZEDDER")
    collect_matches(fake, db, cfg, "br1")
    again = FakeClient({}, {})
    report = collect_matches(again, db, cfg, "br1")
    assert report == MatchReport(players=0, confirmed=0, matches=0, discarded={})
    assert again.id_requests == [] and again.match_requests == []


def test_only_suspects_of_the_requested_platform_are_processed(db):
    fake, _, _ = world()
    suspects(db, "TALONER", platform="kr")
    report = collect_matches(fake, db, cfg, "br1")
    assert report.players == 0
    assert fake.id_requests == []


def test_unscreened_candidates_and_non_suspects_are_ignored(db):
    fake, _, _ = world()
    db.add_candidates("br1", ["TALONER", "ZEDDER"])
    db.mark_screened("br1", "ZEDDER", False)
    db.commit()
    assert collect_matches(fake, db, cfg, "br1").players == 0


def test_no_write_transaction_is_open_during_network_calls(db):
    fake, _, _ = world()
    fake.watch_db = db
    track_batches(db, fake)
    suspects(db, "TALONER", "ZEDDER")
    collect_matches(fake, db, cfg, "br1")
    assert len(fake.match_requests) == 100
    assert fake.riot_id_requests == ["TALONER"]
    assert not fake.open_transaction_seen
    assert not db._conn.in_transaction


def test_the_watcher_notices_a_request_made_inside_a_batch(db):
    # Guards the guard: a riot_id fetched inside the write batch must be caught.
    fake, _, _ = world()
    track_batches(db, fake)
    with db.batch():
        fake.riot_id("TALONER")
    assert fake.open_transaction_seen


def test_a_low_volume_specialist_is_confirmed_end_to_end(db):
    # Only 26 ranked games exist, all Talon: share 1.0. Under a window_games
    # divisor this would be 26/60 = 0.43 and the player would be lost.
    ids = {"LOWVOL": [f"BR1_L{i:03d}" for i in range(26)]}
    matches = {m: payload(m, "LOWVOL", TALON) for m in ids["LOWVOL"]}
    fake = FakeClient(ids, matches, {"LOWVOL": "Low#BR1"})
    suspects(db, "LOWVOL")
    assert collect_matches(fake, db, cfg, "br1").confirmed == 1
    [player] = db.confirmed_players(TALON, "MIDDLE")
    assert (player.games, player.share) == (26, 1.0)


def test_a_player_is_committed_whole_and_the_interrupted_one_not_at_all(db, tmp_path):
    fake, _, _ = world()
    suspects(db, "TALONER", "ZEDDER")
    fake.fail_on_match = 60 + 10  # TALONER has 60 matches; dies inside ZEDDER's
    with pytest.raises(RuntimeError):
        collect_matches(fake, db, cfg, "br1")

    other = Database(tmp_path / "lol.db")
    try:
        assert other.pending_suspects("br1") == ["ZEDDER"]
        assert len(other.confirmed_matches(TALON, "MIDDLE")) == 30
        assert not other.match_exists("BR1_Z000", "ZEDDER")  # nothing half-written
    finally:
        other.close()

    resumed, _, _ = world()
    report = collect_matches(resumed, db, cfg, "br1")
    assert report.players == 1
    assert resumed.id_requests == [("ZEDDER", cfg.window_games, 420)]


def test_match_report_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        MatchReport(1, 0, 0, {}).players = 2


# --- CLI -----------------------------------------------------------------


def cli(args, tmp_path, client=None):
    argv = [*args, "--config", str(ROOT / "config.example.toml"), "--db", str(tmp_path / "cli.db")]
    return main(argv, environ={"RIOT_API_KEY": "chave-de-teste"}, client_factory=lambda p, k: client)


def seed_cli_db(tmp_path, *puuids):
    seeded = Database(tmp_path / "cli.db")
    seeded.init_schema()
    suspects(seeded, *puuids)
    seeded.close()


def test_cli_matches_prints_the_four_figures_and_the_discard_breakdown(tmp_path, capsys):
    fake, ids, matches = world()
    matches["BR1_Z000"] = broken("BR1_Z000", "ZEDDER", "unpaired")
    matches["BR1_Z001"] = broken("BR1_Z001", "ZEDDER", "no_info")
    seed_cli_db(tmp_path, "TALONER", "ZEDDER")
    code = cli(["matches", "--platform", "br1"], tmp_path, client=fake)
    out = capsys.readouterr().out
    assert code == 0
    assert "br1" in out
    assert "jogadores: 2" in out
    assert "sem nome: 0" in out
    assert "confirmados: 1" in out
    assert "partidas: 98" in out
    assert "unpaired_lanes=1" in out
    assert "malformed_payload=1" in out
    assert "chave-de-teste" not in out


def test_cli_matches_says_so_when_nothing_was_discarded(tmp_path, capsys):
    fake, _, _ = world()
    seed_cli_db(tmp_path, "TALONER")
    cli(["matches", "--platform", "br1"], tmp_path, client=fake)
    out = capsys.readouterr().out
    # Per run and cumulative: a multi-night collection is judged on the
    # cumulative discard rate, which the per-run line alone never shows.
    assert "descartes nesta execucao: nenhum" in out
    assert "descartes acumulados: nenhum" in out


def test_cli_matches_riot_error_exits_1_and_keeps_finished_players(tmp_path, capsys):
    class ExpiresMidRun(FakeClient):
        def match(self, match_id):
            if len(self.match_requests) == 65:
                raise RiotError("HTTP 403 for /lol/match/v5/matches/x")
            return super().match(match_id)

    fake, ids, matches = world()
    fake = ExpiresMidRun(ids, matches, {"TALONER": "Talonero#BR1"})
    seed_cli_db(tmp_path, "TALONER", "ZEDDER")
    code = cli(["matches", "--platform", "br1"], tmp_path, client=fake)
    err = capsys.readouterr().err
    assert code == 1
    assert "HTTP 403" in err and "chave-de-teste" not in err
    reopened = Database(tmp_path / "cli.db")
    try:
        assert reopened.pending_suspects("br1") == ["ZEDDER"]
        assert reopened.confirmed_players(TALON, "MIDDLE")
    finally:
        reopened.close()


# --- discarded games stay in the mono-share denominator ----------------------


def border_world(discards):
    """25 Talon mid, 25 other, plus `discards` unreadable games, one player."""
    ids, matches = {"BORDER": []}, {}
    for i in range(25):
        mid = f"BR1_B{i:03d}"
        ids["BORDER"].append(mid)
        matches[mid] = payload(mid, "BORDER", TALON)
    for i in range(25):
        mid = f"BR1_C{i:03d}"
        ids["BORDER"].append(mid)
        matches[mid] = payload(mid, "BORDER", EKKO)
    for i in range(discards):
        mid = f"BR1_D{i:03d}"
        ids["BORDER"].append(mid)
        matches[mid] = broken(mid, "BORDER", "no_info")
    return FakeClient(ids, matches, {"BORDER": "Border#BR1"})


def test_discarded_games_keep_a_borderline_player_out(db):
    # 60 ranked games fetched, 10 unparseable, 25 Talon mid among the 50 that
    # parsed. Over the parsed rows the share reads 25/50 = 0.50 and the player
    # qualifies; over the games actually played it is 25/60 = 0.4167 and the
    # spec rejects him. The bias is always upward and is as large as the
    # discard rate, the quantity the spec names as its silent-failure signal.
    fake = border_world(discards=10)
    suspects(db, "BORDER")
    report = collect_matches(fake, db, cfg, "br1")
    assert report.discarded == {"malformed_payload": 10}
    assert report.confirmed == 0
    assert db.confirmed_players(TALON, "MIDDLE") == []


def test_the_same_player_is_confirmed_when_nothing_is_discarded(db):
    # The control for the test above: no discards, so the share is 25/50.
    fake = border_world(discards=0)
    suspects(db, "BORDER")
    report = collect_matches(fake, db, cfg, "br1")
    assert report.confirmed == 1
    [player] = db.confirmed_players(TALON, "MIDDLE")
    assert player.share == pytest.approx(0.5)


def test_the_published_share_counts_the_discarded_games(db):
    # 40 Talon mid of 60 fetched, with 10 of the rest unreadable: the share the
    # export publishes must be 40/60, not 40/50.
    ids, matches = {"MONO": []}, {}
    for prefix, count, champion in (("M", 40, TALON), ("O", 10, EKKO)):
        for i in range(count):
            mid = f"BR1_{prefix}{i:03d}"
            ids["MONO"].append(mid)
            matches[mid] = payload(mid, "MONO", champion)
    for i in range(10):
        mid = f"BR1_X{i:03d}"
        ids["MONO"].append(mid)
        matches[mid] = broken(mid, "MONO", "no_info")
    fake = FakeClient(ids, matches, {"MONO": "Mono#BR1"})
    suspects(db, "MONO")
    collect_matches(fake, db, cfg, "br1")
    [player] = db.confirmed_players(TALON, "MIDDLE")
    assert player.games == 40
    assert player.share == pytest.approx(40 / 60)


# --- stage 3 circuit breaker -------------------------------------------------


def all_broken(puuids, per_player):
    ids, matches = {}, {}
    for puuid in puuids:
        ids[puuid] = []
        for i in range(per_player):
            mid = f"BR1_{puuid}{i:03d}"
            ids[puuid].append(mid)
            matches[mid] = broken(mid, puuid, "no_info")
    return FakeClient(ids, matches, {p: f"{p}#BR1" for p in puuids})


def test_a_systematically_broken_parser_aborts_instead_of_rejecting_everyone(db):
    # Without the breaker: about 60 requests per suspect, every player
    # rejected, exit 0. And because pending_suspects excludes anyone with a
    # player row, fixing the parser would NOT re-queue them -- recovery would
    # mean deleting the database and re-paying the most expensive stage.
    fake = all_broken(["A", "B", "C"], 30)
    suspects(db, "A", "B", "C")
    with pytest.raises(ExtractionFailing):
        collect_matches(fake, db, cfg, "br1")
    # No verdict was written, so every suspect is still queued.
    assert set(db.pending_suspects("br1")) == {"A", "B", "C"}
    assert db.confirmed_players(TALON, "MIDDLE") == []


def test_the_breaker_stops_after_the_limit_not_after_the_whole_queue(db):
    fake = all_broken(["A", "B", "C"], 30)
    suspects(db, "A", "B", "C")
    with pytest.raises(ExtractionFailing):
        collect_matches(fake, db, cfg, "br1")
    assert len(fake.match_requests) == CONSECUTIVE_FAILURE_LIMIT


def test_a_streak_below_the_limit_still_decides_the_player(db):
    # Isolated corruption is not a broken parser: the run goes on and the
    # malformed games stay counted as discards.
    fake, ids, matches = world()
    for i in range(CONSECUTIVE_FAILURE_LIMIT - 1):
        mid = f"BR1_Z{i:03d}"
        matches[mid] = broken(mid, "ZEDDER", "no_info")
    suspects(db, "ZEDDER", "TALONER")
    report = collect_matches(fake, db, cfg, "br1")
    assert report.discarded["malformed_payload"] == CONSECUTIVE_FAILURE_LIMIT - 1
    assert report.players == 2 and report.confirmed == 1
    assert db.pending_suspects("br1") == []


def test_a_readable_payload_resets_the_streak(db):
    # 19 broken, one readable, 19 broken, one readable: 38 failures, never 20
    # in a row.
    ids, matches = {"MIX": []}, {}
    pattern = ([False] * (CONSECUTIVE_FAILURE_LIMIT - 1) + [True]) * 2
    for i, ok in enumerate(pattern):
        mid = f"BR1_MIX{i:03d}"
        ids["MIX"].append(mid)
        matches[mid] = (
            payload(mid, "MIX", TALON) if ok else broken(mid, "MIX", "no_info")
        )
    fake = FakeClient(ids, matches, {"MIX": "Mix#BR1"})
    suspects(db, "MIX")
    report = collect_matches(fake, db, cfg, "br1")  # must not raise
    assert report.discarded["malformed_payload"] == 2 * (CONSECUTIVE_FAILURE_LIMIT - 1)
    assert report.players == 1


def test_a_legitimate_discard_resets_the_streak_too(db):
    # wrong_queue means the extractor READ the payload and refused the match by
    # rule: the parser works, so the breaker must not count it.
    ids, matches = {"Q": []}, {}
    for i in range(CONSECUTIVE_FAILURE_LIMIT + 10):
        mid = f"BR1_Q{i:03d}"
        ids["Q"].append(mid)
        matches[mid] = broken(mid, "Q", "wrong_queue")
    fake = FakeClient(ids, matches, {"Q": "Q#BR1"})
    suspects(db, "Q")
    report = collect_matches(fake, db, cfg, "br1")  # must not raise
    assert report.discarded == {"wrong_queue": CONSECUTIVE_FAILURE_LIMIT + 10}
    assert report.confirmed == 0


def test_a_player_with_no_matches_at_all_is_still_rejected(db):
    # An empty match list is not a parser failure: it is a rejection, and it
    # must stay one or the player would be re-fetched on every run.
    fake = FakeClient({"EMPTY": []}, {})
    suspects(db, "EMPTY")
    report = collect_matches(fake, db, cfg, "br1")
    assert (report.players, report.confirmed) == (1, 0)
    assert db.pending_suspects("br1") == []


def test_an_unexpected_exception_type_is_a_counted_discard(db, monkeypatch):
    # The extractor raising a type outside the old
    # (KeyError, TypeError, IndexError, AttributeError, StopIteration) tuple
    # used to kill the player, and with it every rerun, because the player was
    # left without a verdict. The visibility lives in the bucket name, not in
    # the exception type.
    def boom(payload, puuid):
        raise ZeroDivisionError("um tipo fora da tupla antiga")

    monkeypatch.setattr("lolmono.collect.extract_match", boom)
    # Five games, well under the breaker's limit: isolated failures, a verdict.
    ids = {"ONE": [f"BR1_ONE{i:03d}" for i in range(5)]}
    matches = {mid: payload(mid, "ONE", TALON) for mid in ids["ONE"]}
    fake = FakeClient(ids, matches, {"ONE": "One#BR1"})
    suspects(db, "ONE")
    report = collect_matches(fake, db, cfg, "br1")
    assert report.discarded == {"malformed_payload": 5}
    assert db.pending_suspects("br1") == []


def test_an_unexpected_exception_type_also_trips_the_breaker(db, monkeypatch):
    def boom(payload, puuid):
        raise ZeroDivisionError("um tipo fora da tupla antiga")

    monkeypatch.setattr("lolmono.collect.extract_match", boom)
    fake, _, _ = world()
    suspects(db, "ZEDDER", "TALONER")
    with pytest.raises(ExtractionFailing):
        collect_matches(fake, db, cfg, "br1")
    assert set(db.pending_suspects("br1")) == {"ZEDDER", "TALONER"}


# --- the per-pair breakdown the go/no-go needs -------------------------------


def test_report_breaks_confirmations_down_by_champion_and_role(db):
    fake, _, _ = world()
    suspects(db, "TALONER", "ZEDDER")
    report = collect_matches(fake, db, cfg, "br1")
    assert report.confirmed_by_target == {(TALON, "MIDDLE"): 1}
    assert report.confirmed == sum(report.confirmed_by_target.values())


def test_cli_matches_prints_the_confirmations_per_pair(tmp_path, capsys):
    fake, _, _ = world()
    seed_cli_db(tmp_path, "TALONER", "ZEDDER")
    cli(["matches", "--platform", "br1"], tmp_path, client=fake)
    out = capsys.readouterr().out
    assert "Talon MIDDLE: 1" in out
    assert "Gragas TOP: 0" in out  # every configured pair is listed, zero or not


def test_cli_matches_exits_1_when_the_extraction_is_systematically_broken(
    tmp_path, capsys
):
    fake = all_broken(["A", "B"], 30)
    seed_cli_db(tmp_path, "A", "B")
    code = cli(["matches", "--platform", "br1"], tmp_path, client=fake)
    assert code == 1
    assert "sistematica" in capsys.readouterr().err
