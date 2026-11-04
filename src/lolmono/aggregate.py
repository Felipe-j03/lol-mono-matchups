"""Aggregation of collected matches. Pure computation: rows in, dataclasses out.

Two things are computed here:

* the base: what a champion's specialists do by default. It covers ALL their
  games, wins and losses together, because it describes the group's habit and
  not what wins. The win rate of the chosen configuration is reported beside
  it as information, never used to choose it.
* the matchup ranking: opponents ordered worst-first.

Fields aggregate differently on purpose. Runes, summoner spells and starting
items are chosen all at once before the game, so each is the single most
frequent complete combination. The final build is counted item by item, since
the exact six-item set is nearly unique per game. The skill order is the first
three points only, where the matchup decision lives.

Ties are always resolved the same way (more games first, then the smaller
key), so the same rows give the same output whatever order they arrive in.
"""

from collections import Counter
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import astuple, dataclass

from lolmono.rows import MatchRow, RunePage, TimelineRow


@dataclass(frozen=True)
class Baseline:
    games: int
    players: int
    win_rate: float  # of the chosen rune configuration, not of the whole group
    group_win_rate: float
    runes: RunePage
    runes_games: int
    spells: tuple[int, int]
    spells_games: int
    item_frequency: tuple[tuple[int, int], ...]
    starting_items: tuple[int, ...] | None
    starting_items_games: int
    skill_order: tuple[int, int, int] | None
    skill_order_games: int


@dataclass(frozen=True)
class MatchupSummary:
    opponent_champion_id: int
    games: int
    wins: int
    win_rate: float
    below_floor: bool


def _most_common(keys: Iterable[Hashable]) -> tuple[Hashable, int] | None:
    """The most frequent key and its count; ties go to the smallest key."""
    counts = Counter(keys)
    if not counts:
        return None
    return min(counts.items(), key=lambda item: (-item[1], item[0]))


def compute_baseline(
    rows: Sequence[MatchRow],
    timelines: Mapping[tuple[str, str], TimelineRow],
    players: int,
    group_win_rate: float,
) -> Baseline:
    """The default configuration of one champion's specialists.

    `rows` are every game of the group (wins and losses). `timelines` is keyed by
    (match_id, puuid); rows without an entry simply do not contribute to the two
    timeline-derived fields, which are None (with a games count of 0) when no
    row contributes. `players` and `group_win_rate` come from the caller.
    """
    if not rows:
        raise ValueError("compute_baseline needs at least one game")

    # Runes: the exact complete page. The tuple form is the tie-break key.
    pages = {astuple(row.runes): row.runes for row in rows}
    rune_key, runes_games = _most_common(astuple(row.runes) for row in rows)
    runes = pages[rune_key]
    page_wins = sum(1 for row in rows if row.runes == runes and row.win)

    # Spells: a set. The slot (D or F) a spell sits in does not split the group.
    spell_set, spells_games = _most_common(tuple(sorted(row.spells)) for row in rows)

    # Build: item by item, each item counted once per game it appears in.
    item_games = Counter(item for row in rows for item in set(row.items))
    item_frequency = tuple(
        sorted(item_games.items(), key=lambda pair: (-pair[1], pair[0]))
    )

    own_timelines = [
        timelines[(row.match_id, row.puuid)]
        for row in rows
        if (row.match_id, row.puuid) in timelines
    ]

    # Starting items: the exact multiset, so purchase order inside the first
    # minute does not split the group. An empty tuple is no configuration.
    starting = _most_common(
        tuple(sorted(tl.starting_items)) for tl in own_timelines if tl.starting_items
    )
    # Skill order: the first three points, in order. None means too short a game.
    skills = _most_common(
        tl.skill_order for tl in own_timelines if tl.skill_order is not None
    )

    return Baseline(
        games=len(rows),
        players=players,
        win_rate=page_wins / runes_games,
        group_win_rate=group_win_rate,
        runes=runes,
        runes_games=runes_games,
        spells=spell_set,
        spells_games=spells_games,
        item_frequency=item_frequency,
        starting_items=starting[0] if starting else None,
        starting_items_games=starting[1] if starting else 0,
        skill_order=skills[0] if skills else None,
        skill_order_games=skills[1] if skills else 0,
    )


def rank_matchups(rows: Sequence[MatchRow], min_games: int) -> list[MatchupSummary]:
    """Opponents worst-first. An opponent with no games is absent, never zero.

    Matchups with at least `min_games` come first, by win rate ascending (more
    games first on a tie). Those below the floor follow, by games descending.
    """
    games: Counter[int] = Counter()
    wins: Counter[int] = Counter()
    for row in rows:
        games[row.opponent_champion_id] += 1
        if row.win:
            wins[row.opponent_champion_id] += 1

    summaries = [
        MatchupSummary(
            opponent_champion_id=opponent,
            games=played,
            wins=wins[opponent],
            win_rate=wins[opponent] / played,
            below_floor=played < min_games,
        )
        for opponent, played in games.items()
    ]
    reliable = sorted(
        (m for m in summaries if not m.below_floor),
        key=lambda m: (m.win_rate, -m.games, m.opponent_champion_id),
    )
    thin = sorted(
        (m for m in summaries if m.below_floor),
        key=lambda m: (-m.games, m.opponent_champion_id),
    )
    return reliable + thin
