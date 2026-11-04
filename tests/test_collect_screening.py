import dataclasses
import subprocess
import sys
from pathlib import Path

import pytest

from lolmono.__main__ import main
from lolmono.collect import BATCH_SIZE, ScreenReport, collect_ladder, screen_candidates
from lolmono.config import load_config
from lolmono.db import Database
from lolmono.riot import Mastery, RiotError

ROOT = Path(__file__).resolve().parent.parent
TALON = 91
ZED = 238
DAY_MS = 24 * 60 * 60 * 1000
now_ms = 1_750_000_000_000

cfg = load_config(ROOT / "config.example.toml")


class FakeClient:
    """Dicionario no lugar da API; conta cada requisicao de maestria."""

    def __init__(self, puuids, masteries, fail_on_call=None):
        self._puuids = puuids
        self._masteries = masteries
        self._fail_on_call = fail_on_call
        self.ladder_calls = []
        self.mastery_requests = []
        self.watch_db = None
        self.open_transaction_seen = False

    @property
    def mastery_calls(self):
        return len(self.mastery_requests)

    def _watch(self):
        # Le o estado da conexao do banco no instante da requisicao (atributo
        # privado: nao ha API publica para isso).
        if self.watch_db is not None and self.watch_db._conn.in_transaction:
            self.open_transaction_seen = True

    def ladder_puuids(self, tiers):
        self._watch()
        self.ladder_calls.append(tuple(tiers))
        return list(self._puuids)

    def top_masteries(self, puuid, count):
        self._watch()
        self.mastery_requests.append((puuid, count))
        if self._fail_on_call == len(self.mastery_requests):
            raise RuntimeError("rede caiu")
        return self._masteries[puuid]


def three_player_client():
    return FakeClient(
        ["MONO", "OTHER", "STALE"],
        {
            "MONO": [Mastery(TALON, 500_000, now_ms - 3 * DAY_MS)],
            "OTHER": [Mastery(ZED, 900_000, now_ms - DAY_MS)],
            "STALE": [Mastery(TALON, 500_000, now_ms - 400 * DAY_MS)],
        },
    )


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "lol.db")
    database.init_schema()
    yield database
    database.close()


def reopened(db_path):
    other = Database(db_path)
    return other


def test_collect_ladder_stores_candidates_once(db):
    fake = three_player_client()
    assert collect_ladder(fake, db, cfg, "br1") == 3
    assert collect_ladder(fake, db, cfg, "br1") == 0
    assert db.pending_candidates("br1") == ["MONO", "OTHER", "STALE"]


def test_collect_ladder_scans_the_configured_tiers(db):
    fake = three_player_client()
    collect_ladder(fake, db, cfg, "br1")
    assert fake.ladder_calls == [cfg.tiers]


def test_collect_ladder_counts_only_new_ones_when_some_were_already_screened(db):
    fake = three_player_client()
    collect_ladder(fake, db, cfg, "br1")
    screen_candidates(fake, db, cfg, "br1", now_ms)
    fake._puuids = ["MONO", "OTHER", "STALE", "NEW"]
    assert collect_ladder(fake, db, cfg, "br1") == 1


def test_collect_ladder_is_committed(db, tmp_path):
    collect_ladder(three_player_client(), db, cfg, "br1")
    other = reopened(tmp_path / "lol.db")
    try:
        assert other.pending_candidates("br1") == ["MONO", "OTHER", "STALE"]
    finally:
        other.close()


def test_screen_marks_suspects_and_rejects(db):
    fake = three_player_client()
    collect_ladder(fake, db, cfg, "br1")
    report = screen_candidates(fake, db, cfg, "br1", now_ms)
    assert report == ScreenReport(screened=3, suspects=1)
    assert db.pending_suspects("br1") == ["MONO"]


def test_screen_report_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        ScreenReport(1, 0).screened = 2


def test_screening_resumes_without_rescreening(db):
    fake = three_player_client()
    collect_ladder(fake, db, cfg, "br1")
    screen_candidates(fake, db, cfg, "br1", now_ms)
    assert screen_candidates(fake, db, cfg, "br1", now_ms).screened == 0
    assert fake.mastery_calls == 3


def test_screening_uses_one_request_per_candidate(db):
    fake = three_player_client()
    collect_ladder(fake, db, cfg, "br1")
    screen_candidates(fake, db, cfg, "br1", now_ms)
    assert fake.mastery_calls == 3
    assert sorted(fake.mastery_requests) == sorted(
        [("MONO", cfg.mastery_top_n), ("OTHER", cfg.mastery_top_n), ("STALE", cfg.mastery_top_n)]
    )


def test_screening_only_touches_the_requested_platform(db):
    fake = three_player_client()
    db.add_candidates("kr", ["KR1"])
    db.commit()
    collect_ladder(fake, db, cfg, "br1")
    screen_candidates(fake, db, cfg, "br1", now_ms)
    assert db.pending_candidates("kr") == ["KR1"]


def test_screening_is_committed(db, tmp_path):
    fake = three_player_client()
    collect_ladder(fake, db, cfg, "br1")
    screen_candidates(fake, db, cfg, "br1", now_ms)
    other = reopened(tmp_path / "lol.db")
    try:
        assert other.pending_candidates("br1") == []
        assert other.pending_suspects("br1") == ["MONO"]
    finally:
        other.close()


def many_players(n):
    puuids = [f"P{i:03d}" for i in range(n)]
    masteries = {p: [Mastery(ZED, 1_000, now_ms)] for p in puuids}
    masteries["P000"] = [Mastery(TALON, 1_000, now_ms)]
    return puuids, masteries


def test_interrupted_screening_keeps_every_completed_batch(db, tmp_path):
    puuids, masteries = many_players(BATCH_SIZE * 2 + 20)
    failing_call = BATCH_SIZE + 10  # cai no meio do segundo lote
    fake = FakeClient(puuids, masteries, fail_on_call=failing_call)
    collect_ladder(fake, db, cfg, "br1")

    with pytest.raises(RuntimeError):
        screen_candidates(fake, db, cfg, "br1", now_ms)

    other = reopened(tmp_path / "lol.db")
    try:
        pending = other.pending_candidates("br1")
        assert pending == puuids[BATCH_SIZE:]
        assert other.pending_suspects("br1") == ["P000"]
    finally:
        other.close()

    # Retomando: gasta requisicoes so com quem faltou.
    resumed = FakeClient(puuids, masteries)
    report = screen_candidates(resumed, db, cfg, "br1", now_ms)
    assert report.screened == len(puuids) - BATCH_SIZE
    assert resumed.mastery_calls == len(puuids) - BATCH_SIZE
    assert db.pending_candidates("br1") == []


def test_no_write_transaction_is_open_during_network_calls(db):
    # Regioes rodam em paralelo no mesmo banco: uma transacao de escrita aberta
    # enquanto o limitador espera travaria a outra ("database is locked").
    puuids, masteries = many_players(BATCH_SIZE * 2 + 5)
    fake = FakeClient(puuids, masteries)
    fake.watch_db = db
    collect_ladder(fake, db, cfg, "br1")
    screen_candidates(fake, db, cfg, "br1", now_ms)
    assert fake.mastery_calls == len(puuids)
    assert not fake.open_transaction_seen
    assert not db._conn.in_transaction


def test_report_counts_span_all_batches(db):
    puuids, masteries = many_players(BATCH_SIZE + 5)
    fake = FakeClient(puuids, masteries)
    collect_ladder(fake, db, cfg, "br1")
    report = screen_candidates(fake, db, cfg, "br1", now_ms)
    assert report == ScreenReport(screened=BATCH_SIZE + 5, suspects=1)


# --- CLI -----------------------------------------------------------------


def cli(args, tmp_path, client=None, environ=None):
    env = {"RIOT_API_KEY": "chave-de-teste"} if environ is None else environ
    keys = []

    def factory(platform, api_key):
        keys.append(api_key)
        return client

    argv = [*args, "--config", str(ROOT / "config.example.toml"), "--db", str(tmp_path / "cli.db")]
    code = main(argv, environ=env, client_factory=factory)
    return code, keys


def test_cli_without_key_names_the_variable_and_exits_2(tmp_path, capsys):
    code, keys = cli(["ladder", "--platform", "br1"], tmp_path, environ={})
    assert code == 2
    assert "RIOT_API_KEY" in capsys.readouterr().err
    assert keys == []
    assert not (tmp_path / "cli.db").exists()


def test_cli_without_key_exits_2_as_a_real_process(tmp_path):
    env = {k: v for k, v in __import__("os").environ.items() if k != "RIOT_API_KEY"}
    result = subprocess.run(
        [sys.executable, "-m", "lolmono", "ladder", "--platform", "br1"],
        cwd=tmp_path,
        env={**env, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "RIOT_API_KEY" in result.stderr


def test_cli_ladder_prints_the_number_of_new_candidates(tmp_path, capsys):
    fake = three_player_client()
    code, keys = cli(["ladder", "--platform", "br1"], tmp_path, client=fake)
    out = capsys.readouterr().out
    assert code == 0
    assert "3" in out and "br1" in out
    assert keys == ["chave-de-teste"]
    assert "chave-de-teste" not in out


def test_cli_screen_prints_screened_and_suspects(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("lolmono.__main__.time.time", lambda: now_ms / 1000)
    fake = three_player_client()
    cli(["ladder", "--platform", "br1"], tmp_path, client=fake)
    capsys.readouterr()
    code, _ = cli(["screen", "--platform", "br1"], tmp_path, client=fake)
    captured = capsys.readouterr()
    assert code == 0
    assert "triados: 3" in captured.out
    assert "suspeitos: 1" in captured.out
    assert "chave-de-teste" not in captured.out + captured.err
    assert fake.mastery_calls == 3


def test_cli_persists_between_invocations(tmp_path, capsys):
    fake = three_player_client()
    cli(["ladder", "--platform", "br1"], tmp_path, client=fake)
    cli(["screen", "--platform", "br1"], tmp_path, client=fake)
    capsys.readouterr()
    cli(["screen", "--platform", "br1"], tmp_path, client=fake)
    assert "triados: 0" in capsys.readouterr().out
    assert fake.mastery_calls == 3


def test_cli_reports_a_missing_config_instead_of_a_traceback(tmp_path, capsys):
    code = main(
        ["ladder", "--platform", "br1", "--config", str(tmp_path / "nope.toml"),
         "--db", str(tmp_path / "x.db")],
        environ={"RIOT_API_KEY": "k"},
        client_factory=lambda p, k: three_player_client(),
    )
    assert code == 2
    assert "nope.toml" in capsys.readouterr().err


def test_cli_riot_error_exits_1_with_a_message_and_no_key(tmp_path, capsys):
    class ExpiredKey(FakeClient):
        def ladder_puuids(self, tiers):
            raise RiotError("HTTP 403 for /lol/league/v4/masterleagues/by-queue/RANKED_SOLO_5x5")

    code, keys = cli(["ladder", "--platform", "br1"], tmp_path, client=ExpiredKey([], {}))
    captured = capsys.readouterr()
    assert code == 1
    assert keys == ["chave-de-teste"]
    assert "HTTP 403" in captured.err
    assert "chave-de-teste" not in captured.out + captured.err


def test_cli_riot_error_mid_screening_keeps_committed_batches(tmp_path, capsys):
    class ExpiresMidRun(FakeClient):
        def top_masteries(self, puuid, count):
            if len(self.mastery_requests) == BATCH_SIZE + 3:
                raise RiotError("HTTP 403 for /lol/champion-mastery/v4/x")
            return super().top_masteries(puuid, count)

    puuids, masteries = many_players(BATCH_SIZE * 2)
    fake = ExpiresMidRun(puuids, masteries)
    assert cli(["ladder", "--platform", "br1"], tmp_path, client=fake)[0] == 0
    code, _ = cli(["screen", "--platform", "br1"], tmp_path, client=fake)
    assert code == 1
    assert "chave-de-teste" not in capsys.readouterr().err
    other = reopened(tmp_path / "cli.db")
    try:
        assert other.pending_candidates("br1") == puuids[BATCH_SIZE:]
    finally:
        other.close()
