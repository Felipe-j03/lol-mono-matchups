import dataclasses
from collections import Counter

import pytest

from lolmono.aggregate import Baseline, compute_baseline
from lolmono.rows import MatchRow, RunePage, TimelineRow

PAGE_A = RunePage(
    keystone=8437,
    primary_style=8400,
    primary_perks=(8437, 8446, 8444, 8451),
    secondary_style=8300,
    secondary_perks=(8345, 8347),
    shards=(5008, 5008, 5002),
)
PAGE_B = RunePage(
    keystone=8010,
    primary_style=8000,
    primary_perks=(8010, 9111, 9104, 8299),
    secondary_style=8400,
    secondary_perks=(8444, 8453),
    shards=(5005, 5008, 5001),
)
PAGE_C = dataclasses.replace(PAGE_A, keystone=8439)

# info.gameCreation of the fixtures, epoch ms (2025-11-02 00:00 UTC).
GAME_CREATED = 1_762_041_600_000

FLASH_IGNITE = (4, 14)
FLASH_TP = (4, 12)


def make_row(
    n, *, win=True, runes=PAGE_A, spells=FLASH_IGNITE, items=(3078,), created=GAME_CREATED
):
    return MatchRow(
        match_id=f"BR1_{n}",
        platform="br1",
        puuid=f"P{n}",
        game_created=created,
        champion_id=79,
        role="TOP",
        opponent_champion_id=122,
        opponent_puuid=f"OPP{n}",
        win=win,
        items=items,
        runes=runes,
        spells=spells,
    )


def make_tl(row, *, starting=(1055, 2003), skills=(1, 3, 1)):
    return TimelineRow(
        match_id=row.match_id,
        puuid=row.puuid,
        gold_at_14=None,
        cs_diff_at_14=None,
        starting_items=starting,
        item_order=(),
        skill_order=skills,
        deaths_before_10=0,
        kills_before_10=0,
    )


def tl_map(*timelines):
    return {(t.match_id, t.puuid): t for t in timelines}


def base_of(rows, timelines=None, players=2, group_win_rate=0.5):
    return compute_baseline(
        rows, timelines or {}, players=players, group_win_rate=group_win_rate
    )


def losing_majority_group():
    """5 games. Page A: 3 games, 1 win. Page B: 2 games, both wins.

    Every other field is built so that A-side habits differ from B-side
    habits: a base computed over wins only would flip every one of them.
    """
    rows = [
        make_row(1, win=True, runes=PAGE_A, spells=FLASH_IGNITE, items=(3078, 3047, 3153)),
        make_row(2, win=False, runes=PAGE_A, spells=FLASH_IGNITE, items=(3078, 3047, 3071)),
        make_row(3, win=False, runes=PAGE_A, spells=FLASH_IGNITE, items=(3078, 3047, 3071)),
        make_row(4, win=True, runes=PAGE_B, spells=FLASH_TP, items=(3078, 3158, 3153)),
        make_row(5, win=True, runes=PAGE_B, spells=FLASH_TP, items=(3156, 3158, 3153)),
    ]
    a_start, b_start = (1055, 2003, 2003), (1054, 2003)
    timelines = tl_map(
        make_tl(rows[0], starting=a_start, skills=(1, 3, 1)),
        # purchase order inside the first minute is arbitrary: same set as a_start
        make_tl(rows[1], starting=(2003, 1055, 2003), skills=(1, 3, 1)),
        make_tl(rows[2], starting=a_start, skills=(1, 3, 1)),
        make_tl(rows[3], starting=b_start, skills=(2, 1, 3)),
        make_tl(rows[4], starting=b_start, skills=(2, 1, 3)),
    )
    return rows, timelines


def test_baseline_uses_wins_and_losses_together():
    rows, timelines = losing_majority_group()
    base = base_of(rows, timelines)
    assert base.runes == PAGE_A  # most played, not most winning
    assert base.runes_games == 3
    assert base.games == 5


def test_baseline_reports_win_rate_of_its_own_configuration():
    rows, timelines = losing_majority_group()
    base = base_of(rows, timelines, group_win_rate=0.5)
    assert base.win_rate == pytest.approx(1 / 3)
    assert base.group_win_rate == 0.5


def test_baseline_passes_players_and_group_win_rate_through():
    rows, timelines = losing_majority_group()
    base = base_of(rows, timelines, players=17, group_win_rate=0.4321)
    assert base.players == 17
    assert base.group_win_rate == 0.4321


def test_spells_use_the_exact_most_played_set_over_all_games():
    rows, timelines = losing_majority_group()
    base = base_of(rows, timelines)
    assert base.spells == FLASH_IGNITE
    assert base.spells_games == 3


def test_spells_are_a_set_so_slot_order_does_not_split_the_group():
    rows = [
        make_row(1, spells=(4, 12)),
        make_row(2, spells=(4, 12)),
        make_row(3, spells=(4, 14)),
        make_row(4, spells=(4, 14)),
        make_row(5, spells=(14, 4)),
        make_row(6, spells=(14, 4)),
    ]
    base = base_of(rows)
    # As raw tuples all three orderings tie at 2 games; as sets Flash+Ignite
    # (4 games) clearly beats Flash+Teleport (2 games).
    assert base.spells == (4, 14)
    assert base.spells_games == 4


def test_build_is_aggregated_item_by_item_in_descending_count():
    rows, timelines = losing_majority_group()
    base = base_of(rows, timelines)
    # 3078 is in 4 of the 5 builds; no six-item set repeats at all
    assert base.item_frequency[0] == (3078, 4)
    counts = [count for _, count in base.item_frequency]
    assert counts == sorted(counts, reverse=True)
    assert dict(base.item_frequency) == {
        3078: 4,
        3047: 3,
        3153: 3,
        3071: 2,
        3158: 2,
        3156: 1,
    }


def _first_seen_order(rows):
    """Items in the order a Counter over the rows would first see them."""
    return list(Counter(item for row in rows for item in dict.fromkeys(row.items)))


def test_item_frequency_ties_break_by_item_id_ascending():
    # One item per game, so the order in which a Counter first sees the items
    # is exactly the row order and does not depend on set iteration. That
    # order (3500, 3100, 3300, 3400, 3200) differs from the expected one, so
    # dropping the tie-break gives the wrong answer.
    rows = [
        make_row(n, items=(item,))
        for n, item in enumerate((3500, 3500, 3100, 3100, 3300, 3300, 3400, 3200))
    ]
    expected = ((3100, 2), (3300, 2), (3500, 2), (3200, 1), (3400, 1))
    assert _first_seen_order(rows) != [item for item, _ in expected]
    assert base_of(rows).item_frequency == expected


def test_item_frequency_tie_break_also_holds_within_multi_item_builds():
    rows = [
        make_row(1, items=(3500, 3100, 3300)),
        make_row(2, items=(3500, 3100, 3300)),
        make_row(3, items=(3400, 3200)),
    ]
    expected = ((3100, 2), (3300, 2), (3500, 2), (3200, 1), (3400, 1))
    # Precondition that makes this test able to fail without a tie-break: count
    # the way the implementation does (one set per game, whose iteration order
    # for small ints is an accident of hashing) and stable-sort by count alone.
    # If that ever happens to equal the expected order, this assert says so
    # instead of letting the test silently stop testing anything.
    counts = Counter(item for row in rows for item in set(row.items))
    untied = sorted(counts.items(), key=lambda pair: -pair[1])
    assert tuple(untied) != expected
    assert base_of(rows).item_frequency == expected


def test_item_frequency_counts_games_not_copies():
    rows = [make_row(1, items=(2003, 2003, 3078)), make_row(2, items=(3078,))]
    base = base_of(rows)
    assert dict(base.item_frequency) == {3078: 2, 2003: 1}


def test_starting_items_use_exact_set():
    rows, timelines = losing_majority_group()
    base = base_of(rows, timelines)
    assert base.starting_items == (1055, 2003, 2003)
    assert base.starting_items_games == 3


def test_skill_order_uses_first_three_points():
    rows, timelines = losing_majority_group()
    base = base_of(rows, timelines)
    assert base.skill_order == (1, 3, 1)
    assert base.skill_order_games == 3


def test_skill_order_keeps_point_order():
    rows = [make_row(1), make_row(2), make_row(3)]
    timelines = tl_map(
        make_tl(rows[0], skills=(1, 3, 1)),
        make_tl(rows[1], skills=(3, 1, 1)),
        make_tl(rows[2], skills=(3, 1, 1)),
    )
    assert base_of(rows, timelines).skill_order == (3, 1, 1)


def test_baseline_ignores_rows_without_timeline_for_timeline_fields():
    rows, _ = losing_majority_group()
    base = base_of(rows, {}, players=1)
    assert base.skill_order is None and base.starting_items is None
    assert base.skill_order_games == 0 and base.starting_items_games == 0
    # the match-derived fields are still there
    assert base.runes == PAGE_A
    assert base.item_frequency[0] == (3078, 4)


def test_timeline_fields_only_count_rows_that_have_a_timeline():
    rows, full = losing_majority_group()
    # only the two B games were extracted
    timelines = {k: v for k, v in full.items() if k[0] in ("BR1_4", "BR1_5")}
    base = base_of(rows, timelines)
    assert base.starting_items == (1054, 2003)
    assert base.starting_items_games == 2
    assert base.skill_order == (2, 1, 3)
    assert base.skill_order_games == 2
    # rune base is unaffected by which games have timelines
    assert base.runes == PAGE_A


def test_timeline_for_another_player_in_same_match_is_not_used():
    rows = [make_row(1)]
    other = dataclasses.replace(make_tl(rows[0]), puuid="SOMEONE-ELSE")
    base = base_of(rows, tl_map(other))
    assert base.skill_order is None and base.starting_items is None


def test_skill_order_none_in_some_timelines_is_skipped_not_counted():
    rows = [make_row(1), make_row(2), make_row(3)]
    timelines = tl_map(
        make_tl(rows[0], skills=None),
        make_tl(rows[1], skills=None),
        make_tl(rows[2], skills=(1, 2, 3)),
    )
    base = base_of(rows, timelines)
    assert base.skill_order == (1, 2, 3)
    assert base.skill_order_games == 1
    # starting items still come from all three timelines
    assert base.starting_items_games == 3


def test_skill_order_none_in_every_timeline_stays_none_with_zero_games():
    rows = [make_row(1), make_row(2)]
    timelines = tl_map(make_tl(rows[0], skills=None), make_tl(rows[1], skills=None))
    base = base_of(rows, timelines)
    assert base.skill_order is None and base.skill_order_games == 0
    assert base.starting_items is not None


def test_empty_starting_items_are_not_a_configuration():
    rows = [make_row(1), make_row(2), make_row(3)]
    timelines = tl_map(
        make_tl(rows[0], starting=()),
        make_tl(rows[1], starting=()),
        make_tl(rows[2], starting=(1055,)),
    )
    base = base_of(rows, timelines)
    assert base.starting_items == (1055,)
    assert base.starting_items_games == 1


def test_all_empty_starting_items_means_none():
    rows = [make_row(1)]
    base = base_of(rows, tl_map(make_tl(rows[0], starting=())))
    assert base.starting_items is None and base.starting_items_games == 0


def test_ties_between_configurations_resolve_deterministically():
    pages = [PAGE_A, PAGE_C, PAGE_C, PAGE_A]
    forward = [make_row(i, runes=p) for i, p in enumerate(pages)]
    backward = list(reversed(forward))
    first = base_of(forward)
    second = base_of(backward)
    assert first.runes == second.runes
    assert first.runes_games == 2


def test_baseline_win_rate_with_all_wins_and_all_losses():
    wins = [make_row(1, win=True), make_row(2, win=True)]
    losses = [make_row(1, win=False), make_row(2, win=False)]
    assert base_of(wins).win_rate == 1.0
    assert base_of(losses).win_rate == 0.0


def test_empty_rows_are_refused_rather_than_invented():
    with pytest.raises(ValueError):
        base_of([])


def test_baseline_is_frozen():
    rows, timelines = losing_majority_group()
    base = base_of(rows, timelines)
    assert isinstance(base, Baseline)
    with pytest.raises(dataclasses.FrozenInstanceError):
        base.games = 99  # type: ignore[misc]
