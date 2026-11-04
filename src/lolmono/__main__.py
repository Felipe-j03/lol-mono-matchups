"""CLI do coletor: ``python -m lolmono <comando> --platform br1``."""

import argparse
import os
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from lolmono.collect import collect_ladder, collect_matches, screen_candidates
from lolmono.config import ConfigError, load_config
from lolmono.db import Database
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
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--platform", required=True, choices=sorted(PLATFORM_TO_REGIONAL))
        command.add_argument("--config", type=Path, default=Path("config.toml"))
        command.add_argument("--db", type=Path, default=Path("data/lolmono.sqlite"))
    return parser


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    client_factory=_make_client,
) -> int:
    args = _parser().parse_args(argv)
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
        db.init_schema()
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
            else:
                report = screen_candidates(
                    client, db, cfg, args.platform, int(time.time() * 1000)
                )
                print(
                    f"screen {args.platform}: triados: {report.screened}, "
                    f"suspeitos: {report.suspects}"
                )
        except RiotError as exc:
            # Chave de desenvolvimento expira em 24h: o lote em andamento foi
            # descartado, os anteriores estao gravados; basta reexecutar.
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
