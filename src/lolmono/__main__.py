"""CLI do coletor: ``python -m lolmono <comando> --platform br1``."""

import argparse
import os
import sqlite3
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from lolmono.collect import (
    ExtractionFailing,
    collect_ladder,
    collect_matches,
    collect_timelines,
    screen_candidates,
)
from lolmono.config import ConfigError, load_config
from lolmono.db import Database, SchemaError
from lolmono.export import export_all
from lolmono.ratelimit import riot_limiter
from lolmono.riot import PLATFORM_TO_REGIONAL, RiotClient, RiotError, httpx_sender

API_KEY_VAR = "RIOT_API_KEY"
# Onde a amostra crua de timelines fica por padrao: ao lado do banco. A spec trata
# essa amostra como algo que acontece ("o cru comprimido de algumas centenas de
# partidas e mantido para conferir a extracao"), nao como um extra opcional, e um
# operador que siga os comandos documentados nao pode acabar sem nenhum payload.
RAW_SAMPLE_SUBDIR = "raw-timelines"


def _make_client(platform: str, api_key: str) -> RiotClient:
    # A chave so existe dentro do transporte HTTP.
    return RiotClient(platform, riot_limiter(), httpx_sender(api_key))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lolmono")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("ladder", "estagio 1: coleta as contas dos elos configurados"),
        ("screen", "estagio 2: peneira por maestria"),
        ("matches", "estagio 3: partidas e confirmacao de mono"),
        (
            "timelines",
            "estagio 4: timelines dos confirmados (so os numeros do early game; o JSON "
            "cru fica em amostra e o resto e descartado). ATENCAO: um banco criado "
            "antes das correcoes de esquema (timeline.skill_order NOT NULL, ou match "
            "sem game_created) e recusado; apagar o arquivo do banco e recomecar e a "
            "recuperacao prevista -- ver o README",
        ),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--platform", required=True, choices=sorted(PLATFORM_TO_REGIONAL))
        if name == "screen":
            command.add_argument(
                "--limit",
                type=int,
                default=None,
                help="tria no maximo N candidatos e para, para calibrar a peneira "
                "em minutos antes de soltar a regiao inteira; o resto fica "
                "pendente e a execucao seguinte continua de onde parou",
            )
        command.add_argument("--config", type=Path, default=Path("config.toml"))
        command.add_argument("--db", type=Path, default=Path("data/lolmono.sqlite"))
        if name == "timelines":
            command.add_argument(
                "--raw-sample-dir",
                type=Path,
                default=None,
                help=(
                    "onde guardar o JSON cru (gzip) das primeiras 200 timelines. "
                    f"Padrao: {RAW_SAMPLE_SUBDIR}/ ao lado do banco. Essa amostra e a "
                    "unica conferencia que o projeto tem sobre a propria extracao, "
                    "entao ela e guardada por padrao"
                ),
            )
            command.add_argument(
                "--no-raw-sample",
                action="store_true",
                help=(
                    "nao guarda nenhum payload cru. Sem a amostra nao ha como "
                    "conferir a extracao depois: use so se o disco for o problema"
                ),
            )
    export = commands.add_parser(
        "export",
        help="escreve os JSON do site a partir do banco (nao usa a API nem a chave)",
    )
    export.add_argument("--config", type=Path, default=Path("config.toml"))
    export.add_argument("--db", type=Path, default=Path("data/lolmono.sqlite"))
    export.add_argument("--out", type=Path, default=Path("site/data"))
    status = commands.add_parser(
        "status",
        help=(
            "estado da coleta a partir do banco: candidatos, triados, suspeitos, "
            "confirmados por par campeao/funcao e por plataforma, e descartes "
            "acumulados por motivo (nao usa a API nem a chave)"
        ),
    )
    status.add_argument("--config", type=Path, default=Path("config.toml"))
    status.add_argument("--db", type=Path, default=Path("data/lolmono.sqlite"))
    return parser


def _open_readonly(args: argparse.Namespace):
    """Config and database for a command that only reads. (cfg, db) or an int."""
    try:
        cfg = load_config(args.config)
    except (ConfigError, OSError) as exc:
        print(f"configuracao invalida ({args.config}): {exc}", file=sys.stderr)
        return 2
    if not args.db.is_file():
        # Database() would create an empty file and the command would "succeed".
        print(f"banco nao encontrado: {args.db}", file=sys.stderr)
        return 2
    db = None
    try:
        db = Database(args.db)
        db.init_schema()
    except SchemaError as exc:
        db.close()
        print(f"banco incompativel ({args.db}): {exc}", file=sys.stderr)
        return 2
    except sqlite3.Error as exc:
        # A spec roda as quatro regioes em paralelo contra um arquivo so, entao
        # um banco travado e plausivel exatamente no instante em que o operador
        # chama ``status``. Vale tambem para um arquivo que nao e SQLite ("file
        # is not a database"): nenhum dos dois pode virar traceback cru. A
        # conexao pode ou nao ter sido aberta antes do erro.
        if db is not None:
            db.close()
        print(f"banco ilegivel ({args.db}): {exc}", file=sys.stderr)
        return 2
    return cfg, db


def _discards_line(counts: dict[str, int]) -> str:
    if not counts:
        return "nenhum"
    total = sum(counts.values())
    breakdown = ", ".join(f"{reason}={n}" for reason, n in sorted(counts.items()))
    return f"{breakdown} (total {total})"


def _status(args: argparse.Namespace) -> int:
    """Estado da coleta, sem gastar uma requisicao.

    Responde tres perguntas que antes exigiam reexecutar um estagio ou ler o
    banco a mao: quantos confirmados por par campeao/funcao (o go/no-go da spec,
    que e por par e nao um total), qual a taxa de descarte ACUMULADA (a
    instrumentacao que a spec nomeia, ilegivel numa coleta de varias noites se so
    o relatorio da execucao a mostra) e em que ponto cada plataforma esta.
    """
    opened = _open_readonly(args)
    if isinstance(opened, int):
        return opened
    cfg, db = opened
    try:
        print(f"banco: {args.db}")
        rows = db.candidate_counts()
        verdicts = dict((p, (c, r)) for p, c, r in db.verdict_counts())
        if not rows:
            print("candidatos: nenhum (rode o estagio 1: ladder)")
        for platform, total, screened, suspects in rows:
            confirmed, rejected = verdicts.get(platform, (0, 0))
            print(
                f"{platform}: candidatos {total}, triados {screened} "
                f"(faltam {total - screened}), suspeitos {suspects}, "
                f"confirmados {confirmed}, rejeitados {rejected} "
                f"(suspeitos sem veredito: {suspects - confirmed - rejected})"
            )

        by_target = db.confirmed_counts_by_target()
        print("confirmados por par campeao/funcao:")
        for target in cfg.targets:
            per_platform = by_target.get((target.champion_id, target.role), {})
            detail = ", ".join(
                f"{platform}={n}" for platform, n in sorted(per_platform.items())
            )
            total = sum(per_platform.values())
            label = f"{target.champion_name} {target.role}"
            print(f"  {label}: {total}" + (f" [{detail}]" if detail else ""))

        print(f"descartes acumulados: {_discards_line(db.discard_counts())}")
    finally:
        db.close()
    return 0


def _export(args: argparse.Namespace) -> int:
    opened = _open_readonly(args)
    if isinstance(opened, int):
        return opened
    cfg, db = opened
    try:
        export_all(db, cfg, args.out)
    finally:
        db.close()
    print(f"export: arquivos escritos em {args.out}")
    return 0


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    client_factory=_make_client,
) -> int:
    args = _parser().parse_args(argv)
    # Estes dois so leem o banco: nao precisam da chave da Riot.
    if args.command == "export":
        return _export(args)
    if args.command == "status":
        return _status(args)
    environ = os.environ if environ is None else environ

    api_key = environ.get(API_KEY_VAR)
    if not api_key:
        print(f"{API_KEY_VAR} nao definida: exporte a chave da Riot nessa variavel.", file=sys.stderr)
        return 2
    try:
        cfg = load_config(args.config)
    except (ConfigError, OSError) as exc:
        print(f"configuracao invalida ({args.config}): {exc}", file=sys.stderr)
        return 2

    args.db.parent.mkdir(parents=True, exist_ok=True)
    db = Database(args.db)
    try:
        try:
            db.init_schema()
        except SchemaError as exc:
            print(f"banco incompativel ({args.db}): {exc}", file=sys.stderr)
            return 2
        client = client_factory(args.platform, api_key)
        try:
            if args.command == "ladder":
                added = collect_ladder(client, db, cfg, args.platform)
                print(f"ladder {args.platform}: candidatos novos: {added}")
            elif args.command == "matches":
                report = collect_matches(client, db, cfg, args.platform)
                print(
                    f"matches {args.platform}: jogadores: {report.players}, "
                    f"confirmados: {report.confirmed}, partidas: {report.matches}, "
                    f"sem nome: {report.unnamed}"
                )
                # Por par, porque o go/no-go da spec e por par: 60 confirmados
                # que sao todos Talon mid nao respondem por Gragas top.
                for target in cfg.targets:
                    n = report.confirmed_by_target.get(
                        (target.champion_id, target.role), 0
                    )
                    print(f"  {target.champion_name} {target.role}: {n}")
                print(f"descartes nesta execucao: {_discards_line(report.discarded)}")
                # Acumulado, porque a coleta atravessa varias noites e e a taxa
                # acumulada que a spec manda vigiar.
                print(f"descartes acumulados: {_discards_line(db.discard_counts())}")
            elif args.command == "timelines":
                # A amostra crua vem ligada: e a unica conferencia do projeto
                # sobre a propria extracao, e --no-raw-sample e a recusa explicita.
                raw_dir = (
                    None
                    if args.no_raw_sample
                    else (args.raw_sample_dir or args.db.parent / RAW_SAMPLE_SUBDIR)
                )
                report = collect_timelines(
                    client, db, args.platform, raw_sample_dir=raw_dir
                )
                print(
                    f"timelines {args.platform}: pedidas: {report.requested}, "
                    f"extraidas: {report.extracted}, ausentes: {report.missing}, "
                    f"falhas: {report.failed}"
                )
                if raw_dir is None:
                    print(
                        "amostra crua: desligada (--no-raw-sample); nao havera "
                        "payload para conferir a extracao depois"
                    )
                else:
                    print(f"amostra crua: {raw_dir}")
                if report.failed:
                    # Ausente e a Riot nao ter dado (normal); falha e a nossa
                    # extracao nao entender um payload: precisa de olho humano.
                    print(
                        f"ATENCAO: {report.failed} timeline(s) com falha na extracao "
                        "(defeito do parser, nao ausencia na Riot). Foram marcadas "
                        "(parse_error) e nao serao pedidas de novo; use "
                        "--raw-sample-dir para inspecionar.",
                        file=sys.stderr,
                    )
            else:
                report = screen_candidates(
                    client, db, cfg, args.platform, int(time.time() * 1000), limit=args.limit
                )
                print(
                    f"screen {args.platform}: triados: {report.screened}, "
                    f"suspeitos: {report.suspects}"
                )
        except ExtractionFailing as exc:
            print(
                f"{args.command} {args.platform}: coleta interrompida porque a extracao "
                f"esta falhando de forma sistematica ({exc}). Nada foi marcado como "
                "falha para essas partidas: elas continuam na fila e serao pedidas de "
                "novo depois que o parser for conferido. O que ja tinha sido extraido "
                "foi mantido. Use --raw-sample-dir para guardar os payloads e inspecionar.",
                file=sys.stderr,
            )
            return 1
        except RiotError as exc:
            # Chave de desenvolvimento expira em 24h. Em ladder/screen/matches o lote
            # em andamento foi descartado; em timelines ele ja foi gravado antes de
            # o erro subir. Os anteriores estao gravados; basta reexecutar.
            print(
                f"{args.command} {args.platform}: falha na API da Riot ({exc}). "
                "O progresso ja gravado foi mantido; confira a chave e reexecute.",
                file=sys.stderr,
            )
            return 1
        except sqlite3.OperationalError as exc:
            # A spec roda as quatro regioes em paralelo contra um banco so, e esse
            # e o erro que isso produz ("database is locked") depois de esgotar o
            # timeout da conexao. Mesma recuperacao do RiotError: o commitado
            # ficou, basta reexecutar -- mas com mensagem propria, para nao virar
            # um traceback no fim de uma noite de coleta.
            print(
                f"{args.command} {args.platform}: falha do banco ({exc}). "
                "O progresso ja gravado foi mantido; se as regioes rodam em "
                "paralelo contra o mesmo arquivo, reexecute esta.",
                file=sys.stderr,
            )
            return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
