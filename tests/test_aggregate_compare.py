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

# info.gameCreation of the fixtures, epoch ms (2025-11-02 00:00 UTC).
GAME_CREATED = 1_762_041_600_000

_counter = iter(range(1, 100_000))


def game(win, boots=SERAPHINE, runes=PAGE, opponent=EKKO, extra_items=(3078,)):
    n = next(_counter)
    return MatchRow(
        match_id=f"BR1_{n}",
        platform="br1",
        puuid=f"P{n}",
        game_created=GAME_CREATED,
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


def test_headline_is_empty_when_there_is_a_divergence_and_nothing_was_skipped():
    rows = diverging_rows()
    detail = compare_matchup(rows, timelines_for(rows), EKKO, min_per_side=15)
    assert detail.divergences  # the site words the largest one from divergences[0]
    assert detail.headline is None


def test_not_compared_headline_names_no_choice_and_no_number():
    # Named for what it checks: it is the NOT-COMPARED headline that carries no
    # digit. The no-divergence headline deliberately prints "15 pontos
    # percentuais", so no-digit is not a property of every headline.
    # Divergences exist, but without timelines two fields could not be compared.
    detail = compare_matchup(diverging_rows(), {}, EKKO, min_per_side=15)
    assert detail.divergences
    assert detail.headline == (
        "Sem partidas suficientes com timeline para comparar: "
        "itens iniciais e ordem de habilidades."
    )
    assert not any(ch.isdigit() for ch in detail.headline)
    assert not any(d.label in detail.headline for d in detail.divergences)
    assert "%" not in detail.headline


def test_headline_names_only_the_fields_that_were_skipped():
    rows = diverging_rows()
    timelines = timelines_for(rows)
    for r in rows:  # every game has a starting build but none has a skill order
        timelines[(r.match_id, r.puuid)] = dataclasses.replace(
            timelines[(r.match_id, r.puuid)], skill_order=None
        )
    detail = compare_matchup(rows, timelines, EKKO, min_per_side=15)
    assert detail.headline == (
        "Sem partidas suficientes com timeline para comparar: ordem de habilidades."
    )


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
    # No timelines here, so "they chose alike" must be scoped to the two fields
    # that WERE compared. The unscoped sentence would tell the player that it
    # comes down to execution while two of the four fields were never examined.
    assert detail.headline == (
        "Vencedores e perdedores fizeram as escolhas de forma igual em botas e "
        "runas: nenhuma diferença passou de 15 pontos percentuais. "
        "Sem partidas suficientes com timeline para comparar: itens iniciais e "
        "ordem de habilidades."
    )


def test_no_divergence_claims_sameness_only_over_the_compared_fields():
    rows = group(True, (20, {})) + group(False, (20, {}))
    timelines = timelines_for(rows)
    for r in rows:  # starting items present, skill order missing everywhere
        timelines[(r.match_id, r.puuid)] = dataclasses.replace(
            timelines[(r.match_id, r.puuid)], skill_order=None
        )
    detail = compare_matchup(rows, timelines, EKKO, min_per_side=15)
    assert detail.divergences == ()
    assert "em botas, runas e itens iniciais" in detail.headline
    assert "neste confronto" not in detail.headline  # the overclaiming wording


def test_sameness_is_unscoped_only_when_every_field_was_compared():
    rows = group(True, (20, {})) + group(False, (20, {}))
    detail = compare_matchup(rows, timelines_for(rows), EKKO, min_per_side=15)
    assert detail.divergences == ()
    assert detail.headline == (
        "Vencedores e perdedores fizeram as escolhas de forma igual neste "
        "confronto: nenhuma diferença passou de 15 pontos percentuais."
    )


def test_gap_just_above_the_threshold_is_a_divergence():
    wins = group(True, (14, {"boots": SERAPHINE}), (6, {"boots": STEELCAPS}))
    losses = group(False, (10, {"boots": SERAPHINE}), (10, {"boots": STEELCAPS}))
    detail = compare_matchup(wins + losses, {}, EKKO, min_per_side=15)
    assert {d.label for d in detail.divergences} == {str(SERAPHINE), str(STEELCAPS)}
    assert all(d.gap == pytest.approx(0.2) for d in detail.divergences)


def test_the_threshold_is_fifteen_points():
    assert MIN_GAP == 0.15  # the load-bearing number, pinned apart from the probes


@pytest.mark.parametrize(
    "per_side, winners_with_sorcerers, losers_with_sorcerers",
    [
        (30, 20, 15),  # 0.667 vs 0.500: a gap of 0.167
        (45, 25, 18),  # 0.556 vs 0.400: a gap of 0.156
    ],
)
def test_gaps_just_above_the_threshold_are_divergences(
    per_side, winners_with_sorcerers, losers_with_sorcerers
):
    # Probes between 0.15 and 0.2: any threshold from 0.16 up would hide them.
    wins = group(
        True,
        (winners_with_sorcerers, {"boots": SERAPHINE}),
        (per_side - winners_with_sorcerers, {"boots": STEELCAPS}),
    )
    losses = group(
        False,
        (losers_with_sorcerers, {"boots": SERAPHINE}),
        (per_side - losers_with_sorcerers, {"boots": STEELCAPS}),
    )
    detail = compare_matchup(wins + losses, {}, EKKO, min_per_side=15)
    expected = (winners_with_sorcerers - losers_with_sorcerers) / per_side
    assert 0.15 < expected < 0.17
    found = {d.label: d for d in detail.divergences}
    assert set(found) == {str(SERAPHINE), str(STEELCAPS)}
    assert found[str(SERAPHINE)].gap == pytest.approx(expected)


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
        # The denominator of each share travels with it: boots and runes are
        # shares of all the side's games, starting items and skill order are
        # shares of its games with a usable timeline.
        "winner_games", "loser_games",
    ]
    assert [f.name for f in dataclasses.fields(MatchupDetail)] == [
        "opponent_champion_id", "wins", "losses", "comparable", "divergences",
        "winner_gold_at_14", "loser_gold_at_14",
        "winner_cs_diff_at_14", "loser_cs_diff_at_14",
        "headline",
        "winner_gold_games", "loser_gold_games",
        "winner_cs_diff_games", "loser_cs_diff_games",
        "winner_starting_items_games", "loser_starting_items_games",
        "winner_skill_order_games", "loser_skill_order_games",
        "winner_games_without_boots", "loser_games_without_boots",
    ]
    detail = compare_matchup(diverging_rows(), {}, EKKO, min_per_side=15)
    with pytest.raises(dataclasses.FrozenInstanceError):
        detail.wins = 0


# --- boots: the set is derived, and its blindness is reported ----------------

TIER_THREE = 3170  # Swiftmarch, a tier-3 upgrade; absent from the hand-made set


def test_tier_three_boots_are_recognised():
    # The hand-written predecessor of BOOT_ITEM_IDS stopped at 3158 and knew no
    # tier-3 upgrade. A tier-3 consumes the tier-2 boots, so in most Master+
    # games the final build held exactly the id the set did not have.
    assert TIER_THREE in BOOT_ITEM_IDS
    for upgrade in (3005, 3008, 3010, 3013, 3168, 3171, 3173, 3174, 3175, 3176):
        assert upgrade in BOOT_ITEM_IDS
    # Derived from the whole item list, not a handful of remembered ids.
    assert len(BOOT_ITEM_IDS) >= 20
    # Alternate-mode ids (Arena and friends) never reach a ranked solo payload.
    assert not any(220_000 <= i < 230_000 or 770_000 <= i < 780_000 for i in BOOT_ITEM_IDS)


def test_tier_three_boots_produce_a_divergence():
    wins = group(True, (16, {"boots": TIER_THREE}), (4, {"boots": STEELCAPS}))
    losses = group(False, (4, {"boots": TIER_THREE}), (16, {"boots": STEELCAPS}))
    detail = compare_matchup(wins + losses, {}, EKKO, min_per_side=15)
    boots = {d.label: d for d in detail.divergences if d.field == "boots"}
    assert str(TIER_THREE) in boots
    assert boots[str(TIER_THREE)].winner_share == pytest.approx(0.8)
    assert detail.winner_games_without_boots == 0
    assert detail.loser_games_without_boots == 0


def test_games_without_a_recognised_boot_are_counted():
    # 3078 is a Trinity Force: a build with only that holds no boots at all.
    wins = group(True, (12, {"boots": SERAPHINE}), (8, {"boots": 3078}))
    losses = group(False, (20, {"boots": 3078}))
    detail = compare_matchup(wins + losses, {}, EKKO, min_per_side=15)
    assert detail.winner_games_without_boots == 8
    assert detail.loser_games_without_boots == 20


def test_no_recognised_boots_at_all_is_reported_not_passed_off_as_sameness():
    # What a patch newer than BOOT_ITEM_IDS looks like: every build holds a boot
    # id we do not know, so boots_of returns [] on both sides. The groups did
    # NOT agree on boots; we simply could not see them.
    unknown_a, unknown_b = 9_990_001, 9_990_002
    assert unknown_a not in BOOT_ITEM_IDS and unknown_b not in BOOT_ITEM_IDS
    wins = group(True, (20, {"boots": unknown_a}))
    losses = group(False, (20, {"boots": unknown_b}))
    detail = compare_matchup(wins + losses, {}, EKKO, min_per_side=15)
    assert detail.winner_games_without_boots == 20
    assert detail.loser_games_without_boots == 20
    assert not [d for d in detail.divergences if d.field == "boots"]
    # The headline says boots were not compared, and does not claim sameness
    # over them.
    assert "botas não foram comparadas" in detail.headline
    assert "igual em runas" in detail.headline


def test_divergences_carry_their_own_denominators():
    # 20 wins and 20 losses, but only 16 winner and 15 loser timelines: the
    # starting-item shares are over those, the boots shares over all 40 games.
    wins = group(True, (16, {"boots": SERAPHINE}), (4, {"boots": STEELCAPS}))
    losses = group(False, (4, {"boots": SERAPHINE}), (16, {"boots": STEELCAPS}))
    timelines = timelines_for(wins[:16], start=(1055,))
    timelines.update(timelines_for(losses[:15], start=(1056,)))
    detail = compare_matchup(wins + losses, timelines, EKKO, min_per_side=15)
    by_field = {}
    for d in detail.divergences:
        by_field.setdefault(d.field, d)
    assert (by_field["boots"].winner_games, by_field["boots"].loser_games) == (20, 20)
    starts = by_field["starting_items"]
    assert (starts.winner_games, starts.loser_games) == (16, 15)
    # The two denominators really do differ, which is the whole point.
    assert starts.winner_games != by_field["boots"].winner_games


def test_mirrored_options_tied_on_gap_put_the_winners_choice_first():
    # The two boots mirror each other exactly: same gap, 0.6. The site builds
    # its sentence from divergences[0], so the option the WINNERS took must come
    # first. Here the winners took Steelcaps, whose label "3047" sorts AFTER the
    # losers' "3020": a sort on (gap, field, label) alone would put the losers'
    # choice first and the site would state the negative.
    wins = group(True, (16, {"boots": STEELCAPS}), (4, {"boots": SERAPHINE}))
    losses = group(False, (4, {"boots": STEELCAPS}), (16, {"boots": SERAPHINE}))
    detail = compare_matchup(wins + losses, {}, EKKO, min_per_side=15)
    first = detail.divergences[0]
    assert first.field == "boots"
    assert first.label == str(STEELCAPS)
    assert first.winner_share > first.loser_share


def test_cs_diff_at_14_is_averaged_beside_the_gold():
    wins = group(True, (20, {}))
    losses = group(False, (20, {}))
    timelines = {}
    for row in wins:
        timelines[(row.match_id, row.puuid)] = dataclasses.replace(
            tl(row), cs_diff_at_14=10
        )
    for row in losses:
        timelines[(row.match_id, row.puuid)] = dataclasses.replace(
            tl(row), cs_diff_at_14=-6
        )
    detail = compare_matchup(wins + losses, timelines, EKKO, min_per_side=15)
    assert detail.winner_cs_diff_at_14 == pytest.approx(10.0)
    assert detail.loser_cs_diff_at_14 == pytest.approx(-6.0)
    assert detail.winner_cs_diff_games == 20 and detail.loser_cs_diff_games == 20


def test_cs_diff_averages_need_the_floor_on_both_sides():
    wins = group(True, (20, {}))
    losses = group(False, (20, {}))
    timelines = timelines_for(wins)
    for row in losses[:14]:  # only 14 losers have the figure
        timelines[(row.match_id, row.puuid)] = tl(row)
    detail = compare_matchup(wins + losses, timelines, EKKO, min_per_side=15)
    assert detail.winner_cs_diff_at_14 is None
    assert detail.loser_cs_diff_at_14 is None
    assert detail.winner_cs_diff_games == 20 and detail.loser_cs_diff_games == 14
