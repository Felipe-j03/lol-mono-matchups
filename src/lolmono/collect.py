"""Estagios 1 e 2 do coletor: escada (todas as contas do elo) e peneira.

A peneira gasta uma unica requisicao de maestria por conta e descarta quase
todas; so os suspeitos seguem para o estagio caro de partidas. Ambos os
estagios sao retomaveis: o progresso fica no banco e e confirmado por lote.
"""

from dataclasses import dataclass

from lolmono.screen import is_suspect

BATCH_SIZE = 50


@dataclass(frozen=True)
class ScreenReport:
    screened: int
    suspects: int


def collect_ladder(client, db, cfg, platform: str) -> int:
    """Grava as contas da escada de ``cfg.tiers``; devolve quantas eram novas."""
    puuids = client.ladder_puuids(cfg.tiers)
    with db.batch():
        before = len(db.pending_candidates(platform))
        db.add_candidates(platform, puuids)
        after = len(db.pending_candidates(platform))
    # Candidatos novos nascem pendentes e os ja conhecidos nao mudam de estado,
    # entao a diferenca de pendentes e exatamente o numero de novos.
    return after - before


def screen_candidates(client, db, cfg, platform: str, now_ms: int) -> ScreenReport:
    """Triagem por maestria dos candidatos pendentes, com commit a cada lote."""
    pending = db.pending_candidates(platform)
    screened = 0
    suspects = 0
    for start in range(0, len(pending), BATCH_SIZE):
        with db.batch():
            for puuid in pending[start : start + BATCH_SIZE]:
                masteries = client.top_masteries(puuid, cfg.mastery_top_n)
                suspect = is_suspect(
                    masteries, cfg.targets, cfg.mastery_top_n, cfg.mastery_max_days, now_ms
                )
                db.mark_screened(platform, puuid, suspect)
                screened += 1
                suspects += suspect
    return ScreenReport(screened=screened, suspects=suspects)
