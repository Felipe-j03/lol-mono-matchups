"""CLI do coletor: ``python -m lolmono <comando> --platform br1``."""

import argparse
import os
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
            "cru e descartado). ATENCAO: um banco criado antes da correcao de "
            "timeline.skill_order e recusado; apague-o antes de uma coleta real",
        ),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--platform", required=True, choices=sorted(PLATFORM_TO_REGIONAL))
        command.add_argument("--config", type=Path, default=Path("config.toml"))
        command.add_argument("--db", type=Path, default=Path("data/lolmono.sqlite"))
        if name == "timelines":
            command.add_argument(
                "--raw-sample-dir",
                type=Path,
                default=None,
                help="guarda o JSON cru (gzip) das primeiras 200 timelines, para auditar a extracao",
            )
    export = commands.add_parser(
        "export",
        help="escreve os JSON do site a partir do banco (nao usa a API nem a chave)",
    )
    export.add_argument("--config", type=Path, default=Path("config.toml"))
    export.add_argument("--db", type=Path, default=Path("data/lolmono.sqlite"))
    export.add_argument("--out", type=Path, default=Path("site/data"))
    return parser


def _export(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
    except (ConfigError, OSError) as exc:
        print(f"configuracao invalida ({args.config}): {exc}", file=sys.stderr)
        return 2
    if not args.db.is_file():
        # Database() would create an empty file and the export would "succeed".
        print(f"banco nao encontrado: {args.db}", file=sys.stderr)
        return 2
    db = Database(args.db)
    try:
        try:
            db.init_schema()
        except SchemaError as exc:
            print(f"banco incompativel ({args.db}): {exc}", file=sys.stderr)
            return 2
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
    if args.command == "export":
        return _export(args)  # so le o banco: nao precisa da chave da Riot
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
                if report.discarded:
                    breakdown = ", ".join(
                        f"{reason}={n}" for reason, n in sorted(report.discarded.items())
                    )
                    print(f"descartes: {breakdown}")
                else:
                    print("descartes: nenhum")
            elif args.command == "timelines":
                report = collect_timelines(
                    client, db, args.platform, raw_sample_dir=args.raw_sample_dir
                )
                print(
                    f"timelines {args.platform}: pedidas: {report.requested}, "
                    f"extraidas: {report.extracted}, ausentes: {report.missing}, "
                    f"falhas: {report.failed}"
                )
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
                    client, db, cfg, args.platform, int(time.time() * 1000)
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
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
