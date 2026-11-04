import dataclasses

import pytest

from lolmono.aggregate import (
    BOOT_ITEM_IDS,
    MIN_GAP,
    Divergence,
    MatchupDetail,
    compare_matchup,
)
from lolmono.rows import MatchRow, RunePage, TimelineRow

EKKO, ZED = 245, 238
SERAPHINE, STEELCAPS, TREADS = 3020, 3047, 3111  # sorcerer's, steelcaps, mercury's

PAGE = RunePage(
    keystone=8437,
    primary_style=8400,
    primary_perks=(8437, 8446, 8444, 8451),
    secondary_style=8300,
    secondary_perks=(8345, 8347),
    shards=(5008, 5008, 5002),
)

_counter = iter(range(1, 100_000))


def game(win, boots=SERAPHINE, runes=PAGE, opponent=EKKO, extra_items=(3078,)):
    n = next(_counter)
    return MatchRow(
        match_id=f"BR1_{n}",
        platform="br1",
        puuid=f"P{n}",
        champion_id=79,
        role="TOP",
        opponent_champion_id=opponent,
        opponent_puuid=f"OPP{n}",
        win=win,
        items=(*extra_items, boots),
        runes=runes,
        spells=(4, 14),
    )


def group(win, *specs, **common):
    """Rows for one side. Each spec is (count, kwargs overriding `common`)."""
    rows = []
    for count, overrides in specs:
        rows += [game(win, **{**common, **overrides}) for _ in range(count)]
    return rows


def tl(row, gold=5000, start=(1056, 2003), skills=(1, 2, 3)):
    return TimelineRow(
        match_id=row.match_id,
        puuid=row.puuid,
        gold_at_14=gold,
        cs_diff_at_14=0,
        starting_items=start,
        item_order=(),
        skill_order=skills,
        deaths_before_10=0,
        kills_before_10=0,
    )


def timelines_for(rows, **kwargs):
    return {(r.match_id, r.puuid): tl(r, **kwargs) for r in rows}


def diverging_rows():
    """20 wins and 20 losses with three divergences of different size.

    boots: wins 16/20 sorcerer's vs losses 4/20  -> gap 0.60 (and the steelcaps mirror)
    rune 8347: wins 15/20 vs losses 10/20         -> gap 0.25
    keystone 8437 and every other perk: shared    -> no divergence
    """
    other = dataclasses.replace(PAGE, secondary_perks=(8345, 8316))
    wins = group(
        True,
        (16, {"boots": SERAPHINE}),
        (4, {"boots": STEELCAPS}),
    )
    # 15 of the 20 winners keep 8347; 5 take 8316.
    wins = [
        dataclasses.replace(r, runes=other) if i >= 15 else r
        for i, r in enumerate(wins)
    ]
    losses = group(
        False,
        (4, {"boots": SERAPHINE}),
        (16, {"boots": STEELCAPS}),
    )
    losses = [
        dataclasses.replace(r, runes=other) if i >= 10 else r
        for i, r in enumerate(losses)
    ]
    return wins + losses


def test_comparison_unavailable_below_fifteen_per_side():
    rows = group(True, (14, {})) + group(False, (20, {}))
    detail = compare_matchup(rows, {}, EKKO, min_per_side=15)
    assert detail.comparable is False and detail.divergences == ()
    assert detail.wins == 14 and detail.losses == 20
    assert detail.headline is None
    assert detail.winner_gold_at_14 is None and detail.loser_gold_at_14 is None


def test_exactly_the_minimum_per_side_is_comparable():
    rows = group(True, (15, {})) + group(False, (15, {}))
    detail = compare_matchup(rows, {}, EKKO, min_per_side=15)
    assert detail.comparable is True


def test_zero_losses_is_not_comparable_and_does_not_raise():
    detail = compare_matchup(group(True, (30, {})), {}, EKKO, min_per_side=15)
    assert detail.comparable is False
    assert (detail.wins, detail.losses) == (30, 0)
    assert detail.divergences == ()


def test_zero_wins_is_not_comparable_and_does_not_raise():
    detail = compare_matchup(group(False, (30, {})), {}, EKKO, min_per_side=15)
    assert detail.comparable is False
    assert (detail.wins, detail.losses) == (0, 30)


def test_no_games_against_the_opponent_is_not_comparable():
    detail = compare_matchup(group(True, (30, {"opponent": ZED})), {}, EKKO, 15)
    assert detail.comparable is False
    assert (detail.wins, detail.losses) == (0, 0)


def test_only_games_against_the_requested_opponent_count():
    rows = diverging_rows() + group(True, (50, {"opponent": ZED}))
    detail = compare_matchup(rows, {}, EKKO, min_per_side=15)
    assert (detail.wins, detail.losses) == (20, 20)
    assert detail.opponent_champion_id == EKKO


def test_reports_boot_divergence_with_both_shares():
    detail = compare_matchup(diverging_rows(), {}, EKKO, min_per_side=15)
    boots = next(
        d for d in detail.divergences if d.field == "boots" and d.label == str(SERAPHINE)
    )
    assert boots.winner_share == pytest.approx(0.8)
    assert boots.loser_share == pytest.approx(0.2)
    assert boots.gap == pytest.approx(0.6)


def test_boots_are_only_the_boot_items():
    assert SERAPHINE in BOOT_ITEM_IDS and STEELCAPS in BOOT_ITEM_IDS
    assert 3078 not in BOOT_ITEM_IDS
    detail = compare_matchup(diverging_rows(), {}, EKKO, min_per_side=15)
    labels = {d.label for d in detail.divergences if d.field == "boots"}
    assert labels == {str(SERAPHINE), str(STEELCAPS)}  # never the shared 3078


def test_choices_shared_by_both_groups_are_omitted():
    detail = compare_matchup(diverging_rows(), {}, EKKO, min_per_side=15)
    assert detail.divergences  # the fixture does diverge
    assert all(d.gap > 0 for d in detail.divergences)
    assert all(d.gap > MIN_GAP for d in detail.divergences)
    rune_labels = {d.label for d in detail.divergences if d.field == "rune"}
    assert "8437" not in rune_labels  # keystone both groups took 100% of the time
    assert "8345" not in rune_labels


def test_divergences_sorted_by_gap_descending():
    detail = compare_matchup(diverging_rows(), {}, EKKO, min_per_side=15)
    gaps = [d.gap for d in detail.divergences]
    assert len(gaps) >= 3
    assert gaps == sorted(gaps, reverse=True)
    assert detail.divergences[-1].field == "rune"  # the 0.25 gap is the smallest


def test_runes_are_compared_perk_by_perk_not_as_whole_pages():
    detail = compare_matchup(diverging_rows(), {}, EKKO, min_per_side=15)
    runes = {d.label: d for d in detail.divergences if d.field == "rune"}
    # The two pages differ in a single perk. The divergence names that perk
    # (and its counterpart), not "a different page".
    assert set(runes) == {"8347", "8316"}
    assert runes["8347"].winner_share == pytest.approx(0.75)
    assert runes["8347"].loser_share == pytest.approx(0.5)
    assert runes["8316"].winner_share == pytest.approx(0.25)
    assert runes["8316"].loser_share == pytest.approx(0.5)


def test_headline_names_the_largest_divergence():
    detail = compare_matchup(diverging_rows(), {}, EKKO, min_per_side=15)
    top = detail.divergences[0]
    assert top.field == "boots"
    assert str(top.label) in detail.headline
    assert "80%" in detail.headline or "20%" in detail.headline


def test_identical_groups_produce_no_divergence_and_say_so():
    rows = group(True, (20, {})) + group(False, (20, {}))
    detail = compare_matchup(rows, timelines_for(rows), EKKO, min_per_side=15)
    assert detail.divergences == ()
    assert detail.comparable is True
    assert "igual" in detail.headline


def test_gap_of_exactly_the_threshold_is_not_a_divergence():
    # 13/20 vs 10/20 = 0.15 exactly (0.65 - 0.5 is 0.15000000000000002 in floats).
    wins = group(True, (13, {"boots": SERAPHINE}), (7, {"boots": STEELCAPS}))
    losses = group(False, (10, {"boots": SERAPHINE}), (10, {"boots": STEELCAPS}))
    detail = compare_matchup(wins + losses, {}, EKKO, min_per_side=15)
    assert detail.divergences == ()
    assert "igual" in detail.headline


def test_gap_just_above_the_threshold_is_a_divergence():
    wins = group(True, (14, {"boots": SERAPHINE}), (6, {"boots": STEELCAPS}))
    losses = group(False, (10, {"boots": SERAPHINE}), (10, {"boots": STEELCAPS}))
    detail = compare_matchup(wins + losses, {}, EKKO, min_per_side=15)
    assert {d.label for d in detail.divergences} == {str(SERAPHINE), str(STEELCAPS)}
    assert all(d.gap == pytest.approx(0.2) for d in detail.divergences)


def test_input_order_does_not_change_the_result():
    rows = diverging_rows()
    forward = compare_matchup(rows, {}, EKKO, min_per_side=15)
    backward = compare_matchup(list(reversed(rows)), {}, EKKO, min_per_side=15)
    assert forward == backward


def test_gold_at_14_averages_skip_rows_without_the_field():
    wins = group(True, (20, {}))
    losses = group(False, (20, {}))
    timelines = timelines_for(wins, gold=5200)
    timelines.update(timelines_for(losses, gold=4000))
    # One winner is a remake: no gold at 14. Another winner has no timeline at all.
    remake = wins[0]
    timelines[(remake.match_id, remake.puuid)] = dataclasses.replace(
        timelines[(remake.match_id, remake.puuid)], gold_at_14=None
    )
    del timelines[(wins[1].match_id, wins[1].puuid)]
    detail = compare_matchup(wins + losses, timelines, EKKO, min_per_side=15)
    assert detail.winner_gold_at_14 == pytest.approx(5200.0)
    assert detail.loser_gold_at_14 == pytest.approx(4000.0)
    assert (detail.winner_gold_games, detail.loser_gold_games) == (18, 20)


def test_gold_needs_the_floor_on_both_sides_or_both_averages_are_none():
    wins = group(True, (20, {}))
    losses = group(False, (20, {}))
    # Every winner has a timeline, only 14 losers do: 14 < 15.
    timelines = timelines_for(wins, gold=5200)
    timelines.update(timelines_for(losses[:14], gold=4000))
    detail = compare_matchup(wins + losses, timelines, EKKO, min_per_side=15)
    assert detail.winner_gold_at_14 is None
    assert detail.loser_gold_at_14 is None
    assert (detail.winner_gold_games, detail.loser_gold_games) == (20, 14)
    # Everything that does not depend on timelines is unaffected.
    assert detail.comparable is True
    assert (detail.wins, detail.losses) == (20, 20)
    assert detail.headline


def test_thin_timelines_leave_match_counts_and_non_timeline_divergences_alone():
    rows = diverging_rows()
    wins = [r for r in rows if r.win]
    losses = [r for r in rows if not r.win]
    timelines = timelines_for(wins, gold=5200)
    timelines.update(timelines_for(losses[:3], gold=4000))
    thin = compare_matchup(rows, timelines, EKKO, min_per_side=15)
    none = compare_matchup(rows, {}, EKKO, min_per_side=15)
    assert thin.winner_gold_at_14 is None and thin.loser_gold_at_14 is None
    assert (thin.wins, thin.losses) == (20, 20)
    assert thin.divergences == none.divergences
    assert {d.field for d in thin.divergences} == {"boots", "rune"}


def test_gold_floor_is_exactly_min_per_side():
    wins = group(True, (20, {}))
    losses = group(False, (20, {}))
    timelines = timelines_for(wins, gold=5200)
    timelines.update(timelines_for(losses[:15], gold=4000))
    detail = compare_matchup(wins + losses, timelines, EKKO, min_per_side=15)
    assert detail.winner_gold_at_14 == pytest.approx(5200.0)
    assert detail.loser_gold_at_14 == pytest.approx(4000.0)


def test_timeline_counts_match_the_timelines_supplied():
    wins = group(True, (20, {}))
    losses = group(False, (20, {}))
    timelines = timelines_for(wins[:18])  # 18 winners with a timeline
    timelines.update(timelines_for(losses[:16]))  # 16 losers with a timeline
    # One loser's timeline is a short game: no skill order. One winner has no
    # starting items recorded and no gold.
    short = losses[0]
    timelines[(short.match_id, short.puuid)] = dataclasses.replace(
        timelines[(short.match_id, short.puuid)], skill_order=None
    )
    odd = wins[0]
    timelines[(odd.match_id, odd.puuid)] = dataclasses.replace(
        timelines[(odd.match_id, odd.puuid)], starting_items=(), gold_at_14=None
    )
    detail = compare_matchup(wins + losses, timelines, EKKO, min_per_side=15)
    assert (detail.winner_gold_games, detail.loser_gold_games) == (17, 16)
    assert (detail.winner_starting_items_games, detail.loser_starting_items_games) == (17, 16)
    assert (detail.winner_skill_order_games, detail.loser_skill_order_games) == (18, 15)


def test_timeline_counts_are_reported_even_when_not_comparable():
    wins = group(True, (14, {}))
    losses = group(False, (20, {}))
    timelines = timelines_for(wins[:9])
    detail = compare_matchup(wins + losses, timelines, EKKO, min_per_side=15)
    assert detail.comparable is False
    assert detail.winner_gold_at_14 is None
    assert (detail.winner_gold_games, detail.loser_gold_games) == (9, 0)
    assert (detail.winner_skill_order_games, detail.loser_skill_order_games) == (9, 0)


def test_gold_is_none_when_no_timeline_has_it():
    rows = group(True, (16, {})) + group(False, (16, {}))
    detail = compare_matchup(rows, {}, EKKO, min_per_side=15)
    assert detail.winner_gold_at_14 is None and detail.loser_gold_at_14 is None
    assert (detail.winner_gold_games, detail.loser_gold_games) == (0, 0)


def test_starting_items_compared_item_by_item():
    wins = group(True, (20, {}))
    losses = group(False, (20, {}))
    timelines = timelines_for(wins, start=(1056, 2003))  # Doran's Ring + potion
    timelines.update(timelines_for(losses[:5], start=(1056, 2003)))
    timelines.update(timelines_for(losses[5:], start=(1055, 2003)))  # Doran's Blade
    detail = compare_matchup(wins + losses, timelines, EKKO, min_per_side=15)
    starting = {d.label: d for d in detail.divergences if d.field == "starting_items"}
    assert set(starting) == {"1056", "1055"}  # the shared potion 2003 is omitted
    assert starting["1056"].winner_share == pytest.approx(1.0)
    assert starting["1056"].loser_share == pytest.approx(0.25)


def test_skill_order_divergence_uses_readable_label():
    wins = group(True, (20, {}))
    losses = group(False, (20, {}))
    timelines = timelines_for(wins, skills=(1, 2, 3))
    timelines.update(timelines_for(losses, skills=(2, 1, 3)))
    detail = compare_matchup(wins + losses, timelines, EKKO, min_per_side=15)
    skills = {d.label: d for d in detail.divergences if d.field == "skill_order"}
    assert set(skills) == {"Q > W > E", "W > Q > E"}
    assert skills["Q > W > E"].winner_share == pytest.approx(1.0)
    assert skills["Q > W > E"].loser_share == pytest.approx(0.0)


def test_timeline_fields_are_not_compared_on_too_few_timelines():
    wins = group(True, (20, {}))
    losses = group(False, (20, {}))
    # Only 3 timelines per side: 100% vs 0% on three games must not be published.
    timelines = timelines_for(wins[:3], skills=(1, 2, 3))
    timelines.update(timelines_for(losses[:3], skills=(2, 1, 3)))
    detail = compare_matchup(wins + losses, timelines, EKKO, min_per_side=15)
    assert not any(d.field in ("starting_items", "skill_order") for d in detail.divergences)
    assert detail.comparable is True


def test_games_without_a_skill_order_are_not_counted_as_a_choice():
    wins = group(True, (20, {}))
    losses = group(False, (20, {}))
    timelines = timelines_for(wins, skills=(1, 2, 3))
    timelines.update(timelines_for(losses, skills=(1, 2, 3)))
    short = losses[0]
    timelines[(short.match_id, short.puuid)] = dataclasses.replace(
        timelines[(short.match_id, short.puuid)], skill_order=None
    )
    detail = compare_matchup(wins + losses, timelines, EKKO, min_per_side=15)
    assert not [d for d in detail.divergences if d.field == "skill_order"]


def test_detail_and_divergence_are_frozen_with_the_agreed_fields():
    assert [f.name for f in dataclasses.fields(Divergence)] == [
        "field", "label", "winner_share", "loser_share", "gap",
    ]
    assert [f.name for f in dataclasses.fields(MatchupDetail)] == [
        "opponent_champion_id", "wins", "losses", "comparable", "divergences",
        "winner_gold_at_14", "loser_gold_at_14", "headline",
        "winner_gold_games", "loser_gold_games",
        "winner_starting_items_games", "loser_starting_items_games",
        "winner_skill_order_games", "loser_skill_order_games",
    ]
    detail = compare_matchup(diverging_rows(), {}, EKKO, min_per_side=15)
    with pytest.raises(dataclasses.FrozenInstanceError):
        detail.wins = 0
