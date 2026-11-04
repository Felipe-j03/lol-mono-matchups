import dataclasses

import pytest

from lolmono.aggregate import MatchupSummary, rank_matchups
from lolmono.rows import MatchRow, RunePage

EKKO, SYLAS, AHRI, ZED, YONE = 245, 517, 103, 238, 777

PAGE = RunePage(
    keystone=8437,
    primary_style=8400,
    primary_perks=(8437, 8446, 8444, 8451),
    secondary_style=8300,
    secondary_perks=(8345, 8347),
    shards=(5008, 5008, 5002),
)

_counter = iter(range(1, 10_000))


def games_vs(opponent, wins, losses):
    rows = []
    for won in [True] * wins + [False] * losses:
        n = next(_counter)
        rows.append(
            MatchRow(
                match_id=f"BR1_{n}",
                platform="br1",
                puuid=f"P{n}",
                champion_id=79,
                role="TOP",
                opponent_champion_id=opponent,
                opponent_puuid=f"OPP{n}",
                win=won,
                items=(3078,),
                runes=PAGE,
                spells=(4, 14),
            )
        )
    return rows


def by_opponent(ranked):
    return {m.opponent_champion_id: m for m in ranked}


def mixed_rows():
    """Ekko 40g 30%, Sylas 35g 60%, Ahri 10g 100%, Zed 5g 0%."""
    return (
        games_vs(SYLAS, wins=21, losses=14)
        + games_vs(AHRI, wins=10, losses=0)
        + games_vs(EKKO, wins=12, losses=28)
        + games_vs(ZED, wins=0, losses=5)
    )


def test_matchups_sorted_worst_first():
    ranked = rank_matchups(mixed_rows(), min_games=30)
    assert [m.opponent_champion_id for m in ranked][:2] == [EKKO, SYLAS]
    assert ranked[0].win_rate == pytest.approx(0.30)
    assert ranked[1].win_rate == pytest.approx(0.60)


def test_matchups_below_floor_are_flagged_and_sorted_last():
    ranked = rank_matchups(mixed_rows(), min_games=30)
    assert ranked[-1].below_floor is True
    assert all(not m.below_floor for m in ranked[:2])
    assert all(m.below_floor for m in ranked[2:])


def test_below_floor_matchups_are_not_mixed_in_by_win_rate():
    # Zed is 0% and would be "worst" if sorted with the others
    ranked = rank_matchups(mixed_rows(), min_games=30)
    assert [m.opponent_champion_id for m in ranked].index(ZED) > 1


def test_below_floor_matchups_are_ordered_by_games_descending():
    ranked = rank_matchups(mixed_rows(), min_games=30)
    # Ahri 10 games at 100% precedes Zed 5 games at 0%: not by win rate
    assert [m.opponent_champion_id for m in ranked] == [EKKO, SYLAS, AHRI, ZED]


def test_floor_is_inclusive_games_equal_to_min_are_not_below():
    rows = games_vs(EKKO, wins=10, losses=20) + games_vs(SYLAS, wins=10, losses=19)
    ranked = by_opponent(rank_matchups(rows, min_games=30))
    assert ranked[EKKO].games == 30 and ranked[EKKO].below_floor is False
    assert ranked[SYLAS].games == 29 and ranked[SYLAS].below_floor is True


def test_floor_is_a_parameter_not_a_constant():
    rows = mixed_rows()
    low = by_opponent(rank_matchups(rows, min_games=5))
    assert not any(m.below_floor for m in low.values())
    high = by_opponent(rank_matchups(rows, min_games=100))
    assert all(m.below_floor for m in high.values())


def test_counts_games_and_wins_per_opponent():
    ranked = by_opponent(rank_matchups(mixed_rows(), min_games=30))
    assert (ranked[EKKO].games, ranked[EKKO].wins) == (40, 12)
    assert (ranked[SYLAS].games, ranked[SYLAS].wins) == (35, 21)
    assert (ranked[AHRI].games, ranked[AHRI].wins) == (10, 10)
    assert (ranked[ZED].games, ranked[ZED].wins) == (5, 0)


def test_matchup_with_zero_wins_does_not_raise():
    all_losses_vs_ekko = games_vs(EKKO, wins=0, losses=4)
    ranked = rank_matchups(all_losses_vs_ekko, min_games=1)
    assert ranked[0].win_rate == 0.0
    assert ranked[0].wins == 0 and ranked[0].games == 4


def test_matchup_with_zero_games_is_absent_not_zero():
    ranked = rank_matchups(mixed_rows(), min_games=1)
    assert all(m.games > 0 for m in ranked)
    assert YONE not in {m.opponent_champion_id for m in ranked}


def test_no_rows_gives_empty_ranking():
    assert rank_matchups([], min_games=30) == []


def test_ties_in_win_rate_break_by_more_games_then_opponent_id():
    rows = (
        games_vs(SYLAS, wins=15, losses=15)  # 0.5, 30 games
        + games_vs(EKKO, wins=20, losses=20)  # 0.5, 40 games
        + games_vs(ZED, wins=15, losses=15)  # 0.5, 30 games, higher id than Ahri
        + games_vs(AHRI, wins=15, losses=15)  # 0.5, 30 games
    )
    ranked = rank_matchups(rows, min_games=30)
    assert [m.opponent_champion_id for m in ranked] == [EKKO, AHRI, ZED, SYLAS]


def test_below_floor_ties_in_games_break_by_opponent_id():
    rows = games_vs(ZED, wins=1, losses=2) + games_vs(AHRI, wins=2, losses=1)
    ranked = rank_matchups(rows, min_games=30)
    assert [m.opponent_champion_id for m in ranked] == [AHRI, ZED]


def test_ranking_does_not_depend_on_input_order():
    rows = mixed_rows()
    forward = rank_matchups(rows, min_games=30)
    backward = rank_matchups(list(reversed(rows)), min_games=30)
    assert forward == backward


def test_summary_is_frozen():
    ranked = rank_matchups(mixed_rows(), min_games=30)
    assert isinstance(ranked[0], MatchupSummary)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ranked[0].games = 1  # type: ignore[misc]
