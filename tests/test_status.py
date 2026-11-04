"""O comando ``status``: o estado da coleta sem gastar uma requisicao.

Ele fecha tres lacunas de uma vez: o go/no-go por par campeao/funcao (que
``MatchReport`` achatava num inteiro so), a taxa de descarte ACUMULADA (que
``db.discard_counts()`` sabia calcular e ninguem chamava) e a impossibilidade de
ver em que ponto a coleta esta sem reexecutar um estagio.
"""

from pathlib import Path

from lolmono.__main__ import main
from lolmono.db import Database

CONFIG_PATH = Path(__file__).parent.parent / "config.example.toml"
TALON = 91


def test_cli_status_prints_the_go_no_go_numbers_per_pair(tmp_path, capsys):
    path = tmp_path / "status.sqlite"
    database = Database(path)
    database.init_schema()
    database.add_candidates("br1", ["A", "B", "C"])
    database.mark_screened("br1", "A", True)
    database.mark_screened("br1", "B", False)
    database.confirm_player("br1", "A", "A#BR1", TALON, "MIDDLE", 30, 0.6)
    database.record_discard("BR1_1", "unpaired_lanes")
    database.record_discard("BR1_2", "malformed_payload")
    database.commit()
    database.close()

    code = main(
        ["status", "--config", str(CONFIG_PATH), "--db", str(path)],
        environ={},  # no API key: status must not need one
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "br1: candidatos 3, triados 2" in out
    assert "suspeitos 1" in out
    assert "Talon MIDDLE: 1" in out
    assert "Gragas TOP: 0" in out  # the pair with no mono is stated, not absent
    assert "unpaired_lanes=1" in out and "malformed_payload=1" in out
    assert "total 2" in out


def test_cli_status_without_a_database_exits_2(tmp_path, capsys):
    code = main(
        ["status", "--config", str(CONFIG_PATH), "--db", str(tmp_path / "nope.sqlite")],
        environ={},
    )
    assert code == 2
    assert "banco nao encontrado" in capsys.readouterr().err
    assert not (tmp_path / "nope.sqlite").exists()
