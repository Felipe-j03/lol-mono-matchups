"""Writes the aggregated data as the JSON files the static site reads.

Layout of the output directory (flat, names in lowercase):

    index.json                              the targets and how much data each has
    <champion>-<role>.json                  one per target that has confirmed games
    <champion>-<role>-vs-<opponent id>.json one per matchup at or above the floor

Rules that hold for every file:

* No ``puuid`` is ever written. It is a permanent account identifier and a
  static site has no use for it. Reference players carry the Riot ID only.
* Every object that states a rate or a choice also states the number of games
  behind it.
* Every file carries ``schema_version``. The site fetches the target and matchup
  files directly and caches them one by one, so per-file versioning is how it
  notices that a cached file predates a schema change.
* The output is a pure function of the database and the config: keys in a fixed
  order, no timestamps, UTF-8 with Unix newlines. Re-running changes no byte.
  The collection window in the index is a pair of dates computed from the
  matches themselves, never from the clock.
* Nothing is read from the environment.

A target with no confirmed games is listed in the index with ``has_data: false``
and gets no file of its own.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from lolmono.aggregate import (
    Baseline,
    MatchupDetail,
    MatchupSummary,
    compare_matchup,
    compute_baseline,
    rank_matchups,
)
from lolmono.config import Config, Target
from lolmono.db import Database
from lolmono.rows import PlayerRow, RunePage

SCHEMA_VERSION = 1


def _slug(target: Target) -> str:
    name = re.sub(r"[^a-z0-9]", "", target.champion_name.lower())
    return f"{name}-{target.role.lower()}"


def _write(path: Path, data: dict) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def _utc_date(epoch_ms: int) -> str:
    """The UTC calendar date of an epoch-millisecond timestamp, as YYYY-MM-DD.

    A date and not a timestamp: the export must not change byte for byte between
    two runs over the same data, and the day is the resolution a patch window is
    read at anyway.
    """
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).date().isoformat()


def _runes(page: RunePage) -> dict:
    return {
        "keystone": page.keystone,
        "primary_style": page.primary_style,
        "primary_perks": list(page.primary_perks),
        "secondary_style": page.secondary_style,
        "secondary_perks": list(page.secondary_perks),
        "shards": list(page.shards),
    }


def _baseline(base: Baseline) -> dict:
    return {
        "games": base.games,
        "players": base.players,
        "group_win_rate": base.group_win_rate,
        "runes": _runes(base.runes),
        "runes_games": base.runes_games,
        "runes_win_rate": base.win_rate,
        "spells": list(base.spells),
        "spells_games": base.spells_games,
        "item_frequency": [
            {"item_id": item, "games": games} for item, games in base.item_frequency
        ],
        "starting_items": (
            None if base.starting_items is None else list(base.starting_items)
        ),
        "starting_items_games": base.starting_items_games,
        "skill_order": None if base.skill_order is None else list(base.skill_order),
        "skill_order_games": base.skill_order_games,
    }


def _matchup(summary: MatchupSummary, file: str | None) -> dict:
    return {
        "opponent_champion_id": summary.opponent_champion_id,
        "games": summary.games,
        "wins": summary.wins,
        "win_rate": summary.win_rate,
        "below_floor": summary.below_floor,
        "file": file,
    }


def _player(player: PlayerRow) -> dict:
    # Deliberately not the puuid.
    return {
        "riot_id": player.riot_id,
        "platform": player.platform,
        "games": player.games,
        "share": player.share,
        "win_rate": player.win_rate,
    }


def _detail(target: Target, detail: MatchupDetail, min_per_side: int) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "champion_id": target.champion_id,
        "champion_name": target.champion_name,
        "role": target.role,
        "opponent_champion_id": detail.opponent_champion_id,
        "games": detail.wins + detail.losses,
        "wins": detail.wins,
        "losses": detail.losses,
        "min_per_side": min_per_side,
        "comparable": detail.comparable,
        "headline": detail.headline,
        "winner_gold_at_14": detail.winner_gold_at_14,
        "loser_gold_at_14": detail.loser_gold_at_14,
        "winner_cs_diff_at_14": detail.winner_cs_diff_at_14,
        "loser_cs_diff_at_14": detail.loser_cs_diff_at_14,
        # Games each timeline-derived figure rests on, per side. Not the match
        # counts above: a game without a usable timeline is not counted here.
        "timeline_games": {
            "gold_at_14": {
                "winners": detail.winner_gold_games,
                "losers": detail.loser_gold_games,
            },
            "cs_diff_at_14": {
                "winners": detail.winner_cs_diff_games,
                "losers": detail.loser_cs_diff_games,
            },
            "starting_items": {
                "winners": detail.winner_starting_items_games,
                "losers": detail.loser_starting_items_games,
            },
            "skill_order": {
                "winners": detail.winner_skill_order_games,
                "losers": detail.loser_skill_order_games,
            },
        },
        # Games whose final build held no recognised boot item. When one of these
        # equals that side's game count, the boots comparison saw nothing on that
        # side (a boot id newer than aggregate.BOOT_ITEM_IDS, most likely), and
        # the absence of a boots divergence means nothing.
        "games_without_boots": {
            "winners": detail.winner_games_without_boots,
            "losers": detail.loser_games_without_boots,
        },
        "divergences": [
            {
                "field": d.field,
                "label": d.label,
                "winner_share": d.winner_share,
                "loser_share": d.loser_share,
                "gap": d.gap,
                # The denominator of each share, which differs by field: all the
                # games of the side for boots and runes, only the games with a
                # usable timeline for starting items and skill order. Carried
                # here so the site never renders a share against the wrong one.
                "winner_games": d.winner_games,
                "loser_games": d.loser_games,
            }
            for d in detail.divergences
        ],
    }


def export_all(db: Database, cfg: Config, out_dir: Path) -> None:
    """Write index.json, one file per target with data, one per reliable matchup."""
    out_dir.mkdir(parents=True, exist_ok=True)
    index_targets = []
    # The oldest and newest game actually aggregated, in epoch ms. The index
    # states them as dates so a reader can tell which patches the base covers,
    # and so a base built from two collections months apart cannot pass for one.
    oldest: int | None = None
    newest: int | None = None

    for target in cfg.targets:
        rows = db.confirmed_matches(target.champion_id, target.role)
        entry = {
            "champion_id": target.champion_id,
            "champion_name": target.champion_name,
            "role": target.role,
            "has_data": bool(rows),
            "file": None,
            "players": 0,
            "games": 0,
        }
        index_targets.append(entry)
        if not rows:
            # compute_baseline needs at least one game. The collection may
            # legitimately confirm no mono for a configured target.
            continue

        dates = [r.game_created for r in rows]
        oldest = min([oldest, *dates]) if oldest is not None else min(dates)
        newest = max([newest, *dates]) if newest is not None else max(dates)

        slug = _slug(target)
        players = db.confirmed_player_count(target.champion_id, target.role)
        timelines = db.timelines_for(sorted({r.match_id for r in rows}))
        base = compute_baseline(
            rows,
            timelines,
            players,
            db.confirmed_group_win_rate(target.champion_id, target.role),
        )

        matchups = []
        for summary in rank_matchups(rows, cfg.matchup_min_games):
            file = None
            if not summary.below_floor:
                file = f"{slug}-vs-{summary.opponent_champion_id}.json"
                detail = compare_matchup(
                    rows,
                    timelines,
                    summary.opponent_champion_id,
                    cfg.delta_min_per_side,
                )
                _write(out_dir / file, _detail(target, detail, cfg.delta_min_per_side))
            matchups.append(_matchup(summary, file))

        players_list = sorted(
            db.confirmed_players(target.champion_id, target.role),
            key=lambda p: (p.riot_id, p.platform),
        )
        _write(
            out_dir / f"{slug}.json",
            {
                "schema_version": SCHEMA_VERSION,
                "champion_id": target.champion_id,
                "champion_name": target.champion_name,
                "role": target.role,
                "baseline": _baseline(base),
                "matchups": matchups,
                "reference_players": [_player(p) for p in players_list],
            },
        )
        entry["file"] = f"{slug}.json"
        entry["players"] = players
        entry["games"] = base.games

    _write(
        out_dir / "index.json",
        {
            "schema_version": SCHEMA_VERSION,
            "ddragon_version": cfg.ddragon_version,
            # The window the aggregated matches span, as UTC dates, or null when
            # nothing was aggregated. Two collections months apart show up here
            # as a wide window instead of passing for one patch in silence.
            "collected_from": None if oldest is None else _utc_date(oldest),
            "collected_through": None if newest is None else _utc_date(newest),
            "targets": index_targets,
        },
    )
