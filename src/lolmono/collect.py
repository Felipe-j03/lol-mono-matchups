"""Estagios do coletor: escada (todas as contas do elo), peneira e partidas.

A peneira gasta uma unica requisicao de maestria por conta e descarta quase
todas; so os suspeitos seguem para o estagio caro de partidas, onde o criterio
de mono decide de verdade. Todos os estagios sao retomaveis: o progresso fica no
banco e e confirmado por lote (peneira) ou por jogador (partidas).
"""

from collections import Counter
from dataclasses import dataclass

from lolmono.matchparse import DiscardMatch, extract_match
from lolmono.mono import qualify
from lolmono.screen import is_suspect

BATCH_SIZE = 50


@dataclass(frozen=True)
class ScreenReport:
    screened: int
    suspects: int


@dataclass(frozen=True)
class MatchReport:
    """Resultado de uma execucao do estagio 3.

    ``discarded`` conta, por motivo, as partidas buscadas nesta execucao e
    descartadas (uma por par jogador/partida); so aparecem motivos ocorridos.
    """

    players: int
    confirmed: int
    matches: int
    discarded: dict[str, int]
    # Confirmados cujo nome nao pode ser obtido (gravados com nome vazio).
    unnamed: int = 0


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
        # A rede (e o limitador) fica fora da transacao: so a escrita do lote
        # abre uma, e curta, para que regioes em paralelo no mesmo banco nao
        # esbarrem em "database is locked".
        verdicts = []
        for puuid in pending[start : start + BATCH_SIZE]:
            masteries = client.top_masteries(puuid, cfg.mastery_top_n)
            verdicts.append(
                (
                    puuid,
                    is_suspect(
                        masteries, cfg.targets, cfg.mastery_top_n, cfg.mastery_max_days, now_ms
                    ),
                )
            )
        with db.batch():
            for puuid, suspect in verdicts:
                db.mark_screened(platform, puuid, suspect)
        screened += len(verdicts)
        suspects += sum(suspect for _, suspect in verdicts)
    return ScreenReport(screened=screened, suspects=suspects)


def collect_matches(client, db, cfg, platform: str) -> MatchReport:
    """Baixa as partidas de cada suspeito pendente e decide se e mono.

    Cada jogador e gravado inteiro, numa transacao curta ao final dele: partidas,
    descartes e veredito, ou nada. Toda a rede (partidas e o nome de quem foi
    confirmado) acontece antes dela, para que regioes em paralelo no mesmo banco
    nao esbarrem em "database is locked".
    """
    players = 0
    confirmed = 0
    stored = 0
    unnamed = 0
    discarded: Counter[str] = Counter()

    for puuid in db.pending_suspects(platform):
        rows = []  # mais recente primeiro, na ordem em que a Riot devolve
        discards = []
        for match_id in client.match_ids(puuid, cfg.window_games):
            if db.match_exists(match_id, puuid):
                continue
            payload = client.match(match_id)
            try:
                rows.append(extract_match(payload, puuid))
            except DiscardMatch as exc:
                discards.append((match_id, exc.reason))
            except (KeyError, TypeError, IndexError, AttributeError, StopIteration):
                # Payload estruturalmente quebrado: o extrator deixa a
                # classificacao para ca. Uma partida corrompida nao derruba uma
                # coleta de horas, mas entra no relatorio de descartes. A lista
                # e larga de proposito: uma excecao nao capturada aqui deixaria o
                # jogador sem veredito e toda nova execucao morreria nele.
                discards.append((match_id, "malformed_payload"))

        verdict = qualify(
            rows, cfg.targets, cfg.window_games, cfg.min_share, cfg.min_games
        )
        # Uma requisicao por confirmado; rejeitados nao custam nenhuma. O nome
        # e cosmetico: falhar nele nao pode jogar fora as partidas ja pagas.
        riot_id = ""
        if verdict is not None:
            try:
                riot_id = client.riot_id(puuid)
            except Exception:
                # Captura larga de proposito, so aqui: o nome e puramente
                # cosmetico (alimenta so a lista de jogadores de referencia), o
                # fallback e definido e CONTADO em ``unnamed`` (nada fica oculto),
                # e a alternativa e uma coleta de horas morta num loop: um corpo
                # sem gameName/tagLine (KeyError), nao-JSON (ValueError), erro de
                # rede... cada tipo novo reproduziria o mesmo travamento.
                # ``Exception`` nao pega KeyboardInterrupt nem SystemExit, entao
                # interromper a mao continua funcionando. NAO estreitar de volta.
                # (A captura de malformed_payload e uma tupla explicita, de
                # proposito: la o alarme e a taxa de descartes.)
                unnamed += 1

        with db.batch():
            for row in rows:
                db.insert_match(row)
            for match_id, reason in discards:
                db.record_discard(match_id, reason)
            if verdict is None:
                db.reject_player(platform, puuid)
            else:
                target, games, share = verdict
                db.confirm_player(
                    platform, puuid, riot_id, target.champion_id, target.role, games, share
                )

        players += 1
        confirmed += verdict is not None
        stored += len(rows)
        discarded.update(reason for _, reason in discards)

    return MatchReport(
        players=players,
        confirmed=confirmed,
        matches=stored,
        discarded=dict(discarded),
        unnamed=unnamed,
    )
