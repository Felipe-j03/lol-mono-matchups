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

The matchup detail compares what the winners of one matchup did against what the
losers did. It reports a choice only where the two groups disagree by more than
MIN_GAP in share: a choice both groups made alike is not a lesson. Nothing here
touches the filesystem; export.py owns the writing.
"""

from collections import Counter
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import astuple, dataclass
from typing import Any

from lolmono.rows import MatchRow, RunePage, TimelineRow


# Absolute difference in share (0 to 1) above which winners and losers are said to
# disagree on a choice. A difference of exactly this size is not enough.
MIN_GAP = 0.15

# Boots, DERIVED from the Data Dragon item list of 16.21.1 (the version
# config.example.toml pins): every Summoner's Rift item (maps["11"]) whose tags
# contain "Boots" OR whose build tree reaches 1001/2422, minus the alternate-mode
# (22xxxx, 77xxxx) ids, which never appear in a ranked solo queue payload.
# Regenerate after bumping ddragon_version and paste the output here:
#
#     python tools/derive_boot_items.py <version>
#
# Do NOT hand-edit, and do NOT narrow the rule back to the tag: 3172 Gunmetal
# Greaves is a tier-3 upgrade built straight out of Berserker's Greaves that Riot
# tags ["AttackSpeed", "LifeSteal", "NonbootsMovement"], with no "Boots" at all.
# It is the attack-speed upgrade, so it is where a Jax top main's boots end up,
# and Jax top is one of the five configured targets. It is the only id here that
# the tag misses.
#
# The hand-written predecessor of this set held no tier-3 upgrade, and a tier-3
# consumes the tier-2 boots it was bought over: in most Master+ games the final
# build held an id the set did not know, the boots lookup returned an empty list
# for BOTH groups, and the first field of the matchup screen silently reported
# nothing.
BOOT_ITEM_IDS = frozenset(
    {
        1001,  # Boots
        2422,  # Slightly Magical Footwear
        3006,  # Berserker's Greaves
        3008,  # Gluttonous Greaves
        3009,  # Boots of Swiftness
        3010,  # Symbiotic Soles
        3013,  # Synchronized Souls
        3020,  # Sorcerer's Shoes
        3047,  # Plated Steelcaps
        3111,  # Mercury's Treads
        3117,  # Mobility Boots
        3158,  # Ionian Boots of Lucidity
        3168,  # Immortal Path
        3170,  # Swiftmarch
        3171,  # Crimson Lucidity
        3172,  # Gunmetal Greaves  (no Boots tag; caught by the build tree)
        3173,  # Chainlaced Crushers
        3174,  # Armored Advance
        3175,  # Spellslinger's Shoes
        3176,  # Forever Forward
    }
)

# Share of a side's games that must have ended with a recognised boot item for
# "boots" to count as a compared field. A single leftover tier-2 game is NOT
# evidence that the boots of a matchup were compared: with 19 of 20 games on a
# boot id this build does not know, the one game that it does know would restore
# the "they chose alike on boots" sentence for a matchup whose boots were never
# seen. Strictly greater, like MIN_GAP, so an even split is not a majority.
MIN_BOOTS_SHARE = 0.5

_SKILL_KEYS = {1: "Q", 2: "W", 3: "E", 4: "R"}


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


@dataclass(frozen=True)
class Divergence:
    """A choice winners and losers made at clearly different rates.

    `label` identifies the choice: an item id or a rune perk id as a string (the
    site resolves the name from the Data Dragon), or a readable skill order such
    as "Q > W > E".

    `winner_games`/`loser_games` are the denominators of the two shares, and they
    are NOT the same for every field: boots and runes are shares of every game of
    that side, while starting items and skill order are shares of the games of
    that side which had a usable timeline. The denominator therefore travels with
    the number instead of being inferred from the matchup's win/loss counts.
    """

    field: str  # "boots", "rune", "starting_items" or "skill_order"
    label: str
    winner_share: float
    loser_share: float
    gap: float  # abs(winner_share - loser_share)
    winner_games: int  # denominator of winner_share
    loser_games: int  # denominator of loser_share


@dataclass(frozen=True)
class MatchupDetail:
    opponent_champion_id: int
    wins: int
    losses: int
    comparable: bool
    divergences: tuple[Divergence, ...]  # largest gap first; the site words it
    winner_gold_at_14: float | None
    loser_gold_at_14: float | None
    # Farm difference against the lane opponent at minute 14. The spec names it
    # beside the gold as the mitigation for "the win rate measures the whole
    # game": a negative mean says the lane was lost, not just the game.
    winner_cs_diff_at_14: float | None
    loser_cs_diff_at_14: float | None
    # Free text, never names a choice. None when there is nothing to add to the
    # divergences: not comparable, or divergences exist and every field was compared.
    headline: str | None
    # Games each timeline-derived figure rests on, per side (distinct from
    # wins/losses: a game without a usable timeline does not count here).
    winner_gold_games: int
    loser_gold_games: int
    winner_cs_diff_games: int
    loser_cs_diff_games: int
    winner_starting_items_games: int
    loser_starting_items_games: int
    winner_skill_order_games: int
    loser_skill_order_games: int
    # Games of each side whose final build held NO id in BOOT_ITEM_IDS. When one
    # of these equals that side's game count, the boots comparison saw nothing on
    # that side: the absence is reported instead of passing for agreement.
    winner_games_without_boots: int
    loser_games_without_boots: int


def _rune_perks(page: RunePage) -> set[int]:
    # The keystone is also the first primary perk; a set counts it once.
    return {page.keystone, *page.primary_perks, *page.secondary_perks, *page.shards}


def _divergences(
    field: str,
    winners: Sequence[Iterable[Hashable]],
    losers: Sequence[Iterable[Hashable]],
    label: Callable[[Any], str],
) -> list[Divergence]:
    """Options chosen at clearly different rates by the two groups.

    Each element of `winners`/`losers` is the options one game took; a game counts
    once per option. Shares are over the games given, per side, and each
    Divergence carries those two counts as its denominators.
    """
    won = Counter(option for game in winners for option in set(game))
    lost = Counter(option for game in losers for option in set(game))
    found = []
    for option in won.keys() | lost.keys():
        winner_share = won[option] / len(winners)
        loser_share = lost[option] / len(losers)
        gap = abs(winner_share - loser_share)
        # Rounded so that a gap of exactly MIN_GAP is not pushed over it by
        # floating point (0.65 - 0.5 is 0.15000000000000002).
        if round(gap, 9) > MIN_GAP:
            found.append(
                Divergence(
                    field,
                    label(option),
                    winner_share,
                    loser_share,
                    gap,
                    winner_games=len(winners),
                    loser_games=len(losers),
                )
            )
    return found


def _mean(values: list[int]) -> float | None:
    return sum(values) / len(values) if values else None


def _skill_label(order: tuple[int, ...]) -> str:
    return " > ".join(_SKILL_KEYS.get(slot, str(slot)) for slot in order)


def _join_pt(names: Sequence[str]) -> str:
    """"a", "a e b", "a, b e c" — the Portuguese the headline is written in."""
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " e " + names[-1]


def compare_matchup(
    rows: Sequence[MatchRow],
    timelines: Mapping[tuple[str, str], TimelineRow],
    opponent_champion_id: int,
    min_per_side: int,
) -> MatchupDetail:
    """What winners did differently from losers against one opponent.

    `rows` may hold games against other opponents too; only those against
    `opponent_champion_id` are used. With fewer than `min_per_side` games on
    either side (zero included) the matchup is not comparable: the counts are
    reported and nothing else (plus the per-side timeline counts). Boots and runes
    come from the match rows. Starting items, skill order and the gold- and
    cs-diff-at-14 averages come from the timelines and appear only when both sides
    have at least `min_per_side` games with that data, so a few timelines cannot
    produce a 100% against 0%, or a confident average, that means nothing. Each
    pair of averages is both present or both None. The counts of games behind
    every figure are always reported.

    The headline's "they chose alike" sentence names the fields that were in fact
    compared. Boots count as compared only when more than `MIN_BOOTS_SHARE` of
    EACH side's games ended with a recognised boot item: an unknown boot id (a
    patch newer than BOOT_ITEM_IDS) leaves those games with an empty list, which
    must not read as agreement, and a handful of games that happen to use a known
    id is not evidence that the matchup's boots were compared.
    `winner_games_without_boots`/`loser_games_without_boots` report it in numbers
    whether or not the comparison happened.
    """
    games = [r for r in rows if r.opponent_champion_id == opponent_champion_id]
    winners = [r for r in games if r.win]
    losers = [r for r in games if not r.win]
    wins, losses = len(winners), len(losers)

    floor = max(min_per_side, 1)  # a side with no games can never be compared

    winner_tls = [
        timelines[(r.match_id, r.puuid)]
        for r in winners
        if (r.match_id, r.puuid) in timelines
    ]
    loser_tls = [
        timelines[(r.match_id, r.puuid)]
        for r in losers
        if (r.match_id, r.puuid) in timelines
    ]
    starts_w = [tl.starting_items for tl in winner_tls if tl.starting_items]
    starts_l = [tl.starting_items for tl in loser_tls if tl.starting_items]
    skills_w = [tl.skill_order for tl in winner_tls if tl.skill_order is not None]
    skills_l = [tl.skill_order for tl in loser_tls if tl.skill_order is not None]
    golds_w = [tl.gold_at_14 for tl in winner_tls if tl.gold_at_14 is not None]
    golds_l = [tl.gold_at_14 for tl in loser_tls if tl.gold_at_14 is not None]
    cs_w = [tl.cs_diff_at_14 for tl in winner_tls if tl.cs_diff_at_14 is not None]
    cs_l = [tl.cs_diff_at_14 for tl in loser_tls if tl.cs_diff_at_14 is not None]

    def boots_of(row: MatchRow) -> list[int]:
        return [item for item in row.items if item in BOOT_ITEM_IDS]

    boots_w = [boots_of(r) for r in winners]
    boots_l = [boots_of(r) for r in losers]

    # How many games each figure rests on, per side. Reported even when the
    # matchup is not comparable, so the absence is explained.
    counts = {
        "winner_gold_games": len(golds_w),
        "loser_gold_games": len(golds_l),
        "winner_cs_diff_games": len(cs_w),
        "loser_cs_diff_games": len(cs_l),
        "winner_starting_items_games": len(starts_w),
        "loser_starting_items_games": len(starts_l),
        "winner_skill_order_games": len(skills_w),
        "loser_skill_order_games": len(skills_l),
        "winner_games_without_boots": sum(1 for b in boots_w if not b),
        "loser_games_without_boots": sum(1 for b in boots_l if not b),
    }

    if wins < floor or losses < floor:
        return MatchupDetail(
            opponent_champion_id,
            wins,
            losses,
            False,
            (),
            None,
            None,
            None,
            None,
            None,
            **counts,
        )

    found: list[Divergence] = []
    # Boots are compared only when a clear majority of the games on EACH side
    # ended with an id this build recognises. One leftover tier-2 game among
    # twenty on a boot the set does not know is not evidence that the boots were
    # compared: the empty lists would mostly agree by construction and the
    # comparison would report silence as sameness. The counts are exported
    # either way, so the site can see this for itself.
    boots_seen = (
        sum(1 for b in boots_w if b) / wins > MIN_BOOTS_SHARE
        and sum(1 for b in boots_l if b) / losses > MIN_BOOTS_SHARE
    )
    compared: list[str] = []
    not_compared_timeline: list[str] = []
    if boots_seen:
        found += _divergences("boots", boots_w, boots_l, str)
        compared.append("botas")
    found += _divergences(
        "rune",
        [_rune_perks(r.runes) for r in winners],
        [_rune_perks(r.runes) for r in losers],
        str,
    )
    compared.append("runas")  # a match row always carries a rune page

    gold_ok = len(golds_w) >= floor and len(golds_l) >= floor
    cs_ok = len(cs_w) >= floor and len(cs_l) >= floor
    if len(starts_w) >= floor and len(starts_l) >= floor:
        found += _divergences("starting_items", starts_w, starts_l, str)
        compared.append("itens iniciais")
    else:
        not_compared_timeline.append("itens iniciais")
    if len(skills_w) >= floor and len(skills_l) >= floor:
        found += _divergences(
            "skill_order",
            [[order] for order in skills_w],
            [[order] for order in skills_l],
            _skill_label,
        )
        compared.append("ordem de habilidades")
    else:
        not_compared_timeline.append("ordem de habilidades")

    # Gap first, then the positive statement: of two mirrored options tied on gap
    # ("winners bought X" against "losers bought Y"), the one the winners took
    # more often comes first, because the site builds its sentence from
    # divergences[0] and "winners bought X" teaches more than its sibling. Field
    # and label keep the order total, so input order never matters.
    found.sort(key=lambda d: (-d.gap, -d.winner_share, d.field, d.label))

    # The headline is free text for the player, so it never names a choice: ids
    # are not names and the site would have to parse prose to resolve them. The
    # largest difference is built by the site from divergences[0]. The headline
    # only says what the divergences cannot: that there were none, which fields
    # could not be compared, and whether the boots lookup saw anything.
    parts = []
    if not found:
        # Scoped to the fields actually examined. Claiming they "did everything
        # the same" while starting items or boots were never looked at would be
        # the same fabrication the sample sizes exist to prevent.
        where = (
            "neste confronto"
            if not not_compared_timeline and boots_seen
            else "em " + _join_pt(compared)
        )
        parts.append(
            f"Vencedores e perdedores fizeram as escolhas de forma igual {where}: "
            f"nenhuma diferença passou de {MIN_GAP * 100:.0f} pontos percentuais."
        )
    if not_compared_timeline:
        parts.append(
            "Sem partidas suficientes com timeline para comparar: "
            + _join_pt(not_compared_timeline)
            + "."
        )
    if not boots_seen:
        parts.append(
            "Poucas partidas terminaram com um item de botas reconhecido, "
            "então as botas não foram comparadas."
        )
    headline = " ".join(parts) or None

    return MatchupDetail(
        opponent_champion_id=opponent_champion_id,
        wins=wins,
        losses=losses,
        comparable=True,
        divergences=tuple(found),
        # Both averages or neither: a gap needs both sides on solid ground.
        winner_gold_at_14=_mean(golds_w) if gold_ok else None,
        loser_gold_at_14=_mean(golds_l) if gold_ok else None,
        winner_cs_diff_at_14=_mean(cs_w) if cs_ok else None,
        loser_cs_diff_at_14=_mean(cs_l) if cs_ok else None,
        headline=headline,
        **counts,
    )
