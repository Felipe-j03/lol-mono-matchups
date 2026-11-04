"""Estagios do coletor: escada (todas as contas do elo), peneira, partidas e timelines.

A peneira gasta uma unica requisicao de maestria por conta e descarta quase
todas; so os suspeitos seguem para o estagio caro de partidas, onde o criterio
de mono decide de verdade. Todos os estagios sao retomaveis: o progresso fica no
banco e e confirmado por lote (peneira), por jogador (partidas) ou por lote de
partidas (timelines).
"""

import gzip
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from lolmono.matchparse import DiscardMatch, extract_match
from lolmono.mono import qualify
from lolmono.screen import is_suspect
from lolmono.timelineparse import extract_timeline

BATCH_SIZE = 50
RAW_SAMPLE_LIMIT = 200  # timelines cruas guardadas para auditar a extracao
# Falhas de extracao seguidas que abortam a coleta (estagios 3 e 4): o parser
# quebrou em tudo (formato novo da Riot ou defeito nosso) e continuar so gastaria
# requisicoes para nao guardar nada. No estagio 3 o estrago seria pior que gastar:
# cada suspeito varrido receberia o veredito "rejeitado", e ``pending_suspects``
# exclui quem ja tem linha em ``player``, entao consertar o parser depois nao os
# devolveria para a fila -- a recuperacao seria apagar o banco e repagar o
# estagio caro.
CONSECUTIVE_FAILURE_LIMIT = 20


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
    # Confirmados por par (champion_id, role) NESTA execucao. O go/no-go da spec
    # e por par, nao um total: 60 confirmados que sao todos Talon mid nao
    # responde se ha mono de Gragas top. O acumulado esta no comando ``status``.
    confirmed_by_target: dict[tuple[int, str], int] = field(default_factory=dict)


@dataclass(frozen=True)
class TimelineReport:
    """Resultado de uma execucao do estagio 4.

    ``requested`` conta requisicoes de timeline (a unidade de custo). As demais
    contam pares (partida, jogador): uma partida com dois monos rastreados custa
    uma requisicao e rende dois pares. ``missing`` e a Riot nao ter timeline (404,
    normal); ``failed`` e a timeline existir e a nossa extracao nao a entender, o
    que e defeito nosso e fica separado para nao se esconder em ``missing``.
    """

    requested: int
    extracted: int
    missing: int
    failed: int


class ExtractionFailing(Exception):
    """A extracao falha de forma sistematica; a coleta foi abortada.

    Vale para os dois estagios que extraem payload: partidas (estagio 3) e
    timelines (estagio 4). Em nenhum dos dois a sequencia que disparou o aborto e
    gravada: o trabalho continua na fila para depois do conserto do parser.
    """


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

    O denominador da proporcao de mono e quantas partidas da janela foram
    BUSCADAS, nao quantas o extrator conseguiu ler: um descarte continua contando
    como partida jogada. Dividir pelas lidas inflaria toda proporcao para cima,
    na medida exata da taxa de descarte -- justamente o sinal que a spec usa para
    detectar erro silencioso.

    ``CONSECUTIVE_FAILURE_LIMIT`` payloads seguidos com ``malformed_payload``
    abortam a coleta com ``ExtractionFailing``, SEM gravar o jogador em curso:
    nenhum veredito e escrito a partir de um parser quebrado, e os suspeitos
    continuam na fila (gravar as partidas sem o veredito seria pior: na nova
    execucao ``match_exists`` as pularia e a proporcao sairia errada).
    """
    players = 0
    confirmed = 0
    stored = 0
    unnamed = 0
    discarded: Counter[str] = Counter()
    by_target: Counter[tuple[int, str]] = Counter()
    # Payloads seguidos que o extrator nao conseguiu ler, atravessando jogadores.
    streak = 0

    for puuid in db.pending_suspects(platform):
        rows = []  # mais recente primeiro, na ordem em que a Riot devolve
        discards = []
        window_ids = list(client.match_ids(puuid, cfg.window_games))[: cfg.window_games]
        for match_id in window_ids:
            if db.match_exists(match_id, puuid):
                continue
            payload = client.match(match_id)
            try:
                rows.append(extract_match(payload, puuid))
            except DiscardMatch as exc:
                # O extrator LEU o payload e recusou a partida por regra (fila
                # errada, rota sem par): o parser esta funcionando.
                discards.append((match_id, exc.reason))
                streak = 0
            except Exception:
                # Captura larga de proposito: o payload nao foi entendido. A
                # visibilidade vem do nome do balde, nao do tipo da excecao --
                # ``malformed_payload`` e um motivo proprio, contado e
                # deduplicado, e um pico nele fala mais alto que uma coleta
                # morta. A tupla enumerada que ficava aqui so comprava o modo de
                # falha que o disjuntor abaixo agora cobre, e deixava qualquer
                # tipo novo matar o jogador em toda nova execucao.
                # ``Exception`` nao pega KeyboardInterrupt nem SystemExit, entao
                # interromper a mao continua funcionando. NAO estreitar de volta.
                discards.append((match_id, "malformed_payload"))
                streak += 1
                if streak >= CONSECUTIVE_FAILURE_LIMIT:
                    raise ExtractionFailing(
                        f"{streak} partidas seguidas falharam na extracao "
                        f"(a ultima: {match_id}): a falha e sistematica. Nenhum "
                        "veredito foi gravado para este jogador; os suspeitos "
                        "continuam na fila."
                    ) from None
            else:
                streak = 0

        verdict = qualify(
            rows,
            cfg.targets,
            cfg.window_games,
            cfg.min_share,
            cfg.min_games,
            window_size=len(window_ids),
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
        if verdict is not None:
            by_target[(verdict[0].champion_id, verdict[0].role)] += 1
        stored += len(rows)
        discarded.update(reason for _, reason in discards)

    return MatchReport(
        players=players,
        confirmed=confirmed,
        matches=stored,
        discarded=dict(discarded),
        unnamed=unnamed,
        confirmed_by_target=dict(by_target),
    )


def _save_raw_sample(directory: Path, match_id: str, payload) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / f"{match_id}.json.gz"
    partial = directory / f"{match_id}.json.gz.tmp"  # nao casa com *.json.gz
    with gzip.open(partial, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)
    partial.replace(final)


def collect_timelines(
    client, db, platform: str, raw_sample_dir: Path | None = None
) -> TimelineReport:
    """Baixa a timeline de cada partida de confirmado, extrai e descarta o cru.

    E a requisicao mais cara do projeto, entao nenhuma e repetida: o que foi
    extraido vira linha de ``timeline``; 404 e payload ilegivel viram marca em
    ``timeline_missing`` (motivos ``not_found`` e ``parse_error``) e saem da fila.
    Uma partida com dois pares rastreados e pedida uma vez so.

    Rede e extracao acontecem em memoria; a escrita e uma transacao curta a cada
    ``BATCH_SIZE`` partidas, nunca aberta durante uma requisicao. Se a coleta
    morre no meio (chave expirada, rede), o que ja foi pago e gravado antes de
    a excecao subir.

    ``CONSECUTIVE_FAILURE_LIMIT`` falhas de extracao seguidas abortam a coleta com
    ``ExtractionFailing``. As falhas ainda nao confirmadas por um sucesso seguinte
    (a sequencia que disparou o aborto) NAO sao marcadas: ficam na fila para serem
    refeitas quando o parser for consertado. So uma falha seguida de um sucesso
    (ou o fim da fila, com a sequencia abaixo do limite) vira ``parse_error``.
    Um 404 nao e extracao: nao zera nem aumenta a sequencia.

    Com ``raw_sample_dir``, o JSON cru comprimido das primeiras
    ``RAW_SAMPLE_LIMIT`` timelines (contando as de execucoes anteriores) fica
    em disco para auditoria, inclusive as que a extracao nao entendeu. O resto
    e descartado.
    """
    by_match: dict[str, list[tuple[str, str]]] = {}
    for match_id, puuid, opponent_puuid in db.matches_awaiting_timeline(platform):
        by_match.setdefault(match_id, []).append((puuid, opponent_puuid))

    sampled = 0
    if raw_sample_dir is not None and raw_sample_dir.is_dir():
        sampled = len(list(raw_sample_dir.glob("*.json.gz")))

    requested = extracted = missing = failed = 0
    # Por partida: (match_id, linhas extraidas, puuids ausentes).
    pending: list[tuple[str, list, list[str]]] = []
    # Falhas ainda nao confirmadas (nenhum sucesso depois delas); nao sao gravadas.
    streak: list[tuple[str, str]] = []
    # Falhas confirmadas por um sucesso posterior, a gravar no proximo lote.
    confirmed_failures: list[tuple[str, str]] = []

    def flush() -> None:
        nonlocal extracted, missing, failed
        if not pending and not confirmed_failures:
            return
        with db.batch():
            for match_id, rows, absent in pending:
                for row in rows:
                    db.insert_timeline(row)
                for puuid in absent:
                    db.mark_timeline_missing(match_id, puuid, "not_found")
            for match_id, puuid in confirmed_failures:
                db.mark_timeline_missing(match_id, puuid, "parse_error")
        for _, rows, absent in pending:
            extracted += len(rows)
            missing += len(absent)
        failed += len(confirmed_failures)
        pending.clear()
        confirmed_failures.clear()

    try:
        for match_id, pairs in by_match.items():
            payload = client.timeline(match_id)
            requested += 1

            if payload is not None and raw_sample_dir is not None and sampled < RAW_SAMPLE_LIMIT:
                _save_raw_sample(raw_sample_dir, match_id, payload)
                sampled += 1

            rows, absent = [], []
            for puuid, opponent_puuid in pairs:
                if payload is None:
                    absent.append(puuid)
                    continue
                try:
                    row = extract_timeline(payload, puuid, opponent_puuid)
                except Exception:
                    # Captura larga de proposito: um payload estranho nao pode
                    # matar uma coleta de horas. Mas aqui a contagem e a
                    # evidencia: vai para ``failed`` (nunca para ``missing``) e
                    # para a tabela com motivo ``parse_error``, e o CLI avisa.
                    # Nao e gravada ja: so depois de um sucesso (ver docstring).
                    streak.append((match_id, puuid))
                    if len(streak) >= CONSECUTIVE_FAILURE_LIMIT:
                        # Guarda o que esta partida ja rendeu antes de abortar.
                        pending.append((match_id, rows, absent))
                        raise ExtractionFailing(
                            f"{len(streak)} timelines seguidas falharam na extracao "
                            f"(a partir de {streak[0][0]}): a falha e sistematica"
                        ) from None
                    continue
                rows.append(row)
                confirmed_failures.extend(streak)
                streak.clear()
            pending.append((match_id, rows, absent))

            if len(pending) >= BATCH_SIZE:
                flush()
        # Fim da fila com uma sequencia curta de falhas: sao falhas reais e isoladas.
        confirmed_failures.extend(streak)
        streak.clear()
    except BaseException:
        # Nao perde o que ja foi pago. Se a propria gravacao falhar, a excecao
        # original (a que importa) continua sendo a que sobe.
        try:
            flush()
        except Exception:
            pass
        raise
    flush()

    return TimelineReport(
        requested=requested, extracted=extracted, missing=missing, failed=failed
    )
