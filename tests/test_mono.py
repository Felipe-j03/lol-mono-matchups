from lolmono.config import Target
from lolmono.mono import qualify
from lolmono.rows import MatchRow, RunePage

TALON_MID = Target(91, "Talon", "MIDDLE")
GRAGAS_TOP = Target(79, "Gragas", "TOP")
GRAGAS_MID = Target(79, "Gragas", "MIDDLE")
JAX_TOP = Target(24, "Jax", "TOP")
targets = (TALON_MID, GRAGAS_MID, GRAGAS_TOP, JAX_TOP)

_RUNES = RunePage(8010, 8000, (8010, 9111, 9104, 8299), 8400, (8446, 8451), (5005, 5008, 5011))


def row(champion_id, role, n=0):
    return MatchRow(
        match_id=f"BR1_{n}",
        platform="br1",
        puuid="P",
        champion_id=champion_id,
        role=role,
        opponent_champion_id=1,
        opponent_puuid="O",
        win=True,
        items=(),
        runes=_RUNES,
        spells=(4, 14),
    )


def talon_mid():
    return row(91, "MIDDLE")


def other():
    return row(1, "MIDDLE")


def gragas_top():
    return row(79, "TOP")


def gragas_mid():
    return row(79, "MIDDLE")


def test_qualifies_when_share_and_absolute_minimum_are_met():
    rows = [talon_mid()] * 30 + [other()] * 30
    assert qualify(rows, targets, 60, 0.50, 25) == (TALON_MID, 30, 0.5)


def test_rejects_high_share_with_too_few_absolute_games():
    rows = [talon_mid()] * 8 + [other()] * 4  # 67%, mas 8 partidas
    assert qualify(rows, targets, 60, 0.50, 25) is None


def test_rejects_enough_absolute_games_with_low_share():
    # 25 na janela de 60 satisfaz o minimo absoluto, mas 0.4167 < 0.50
    rows = [talon_mid()] * 25 + [other()] * 35
    assert qualify(rows, targets, 60, 0.50, 25) is None


def test_same_champion_in_two_roles_counts_separately():
    rows = [gragas_top()] * 26 + [gragas_mid()] * 26
    # nenhum dos dois pares atinge 50% isolado
    assert qualify(rows, targets, 60, 0.50, 25) is None


def test_only_the_window_most_recent_games_count():
    # Mais recentes primeiro: 60 de outro campeao enchem a janela e os 25 Talon
    # antigos ficam de fora.
    rows = [other()] * 60 + [talon_mid()] * 25
    assert qualify(rows, targets, 60, 0.50, 25) is None


def test_share_is_measured_against_the_window_not_against_games_played():
    # 80 partidas disponiveis, 30 Talon recentes + 30 outras na janela, 20 antigas.
    rows = [talon_mid()] * 30 + [other()] * 30 + [talon_mid()] * 20
    assert qualify(rows, targets, 60, 0.50, 25) == (TALON_MID, 30, 0.5)


def test_share_is_measured_against_the_configured_window_even_for_short_histories():
    # Only 40 games exist: 26/40 = 0.65 of what was played, but 26/60 = 0.433 of
    # the window. The denominator is the window, so this player is not mono.
    rows = [talon_mid()] * 26 + [other()] * 14
    assert qualify(rows, targets, 60, 0.50, 25) is None


def test_short_history_still_qualifies_when_the_window_share_is_met():
    rows = [talon_mid()] * 30 + [other()] * 5
    assert qualify(rows, targets, 60, 0.50, 25) == (TALON_MID, 30, 0.5)


def test_player_with_no_matches_does_not_qualify():
    assert qualify([], targets, 60, 0.50, 25) is None


def test_champion_outside_the_targets_never_qualifies():
    assert qualify([other()] * 60, targets, 60, 0.50, 25) is None


def test_gragas_top_is_distinguished_from_gragas_mid():
    rows = [gragas_top()] * 40 + [gragas_mid()] * 20
    assert qualify(rows, targets, 60, 0.50, 25) == (GRAGAS_TOP, 40, 40 / 60)


def test_below_half_share_returns_the_target_with_the_highest_count():
    rows = [talon_mid()] * 20 + [row(24, "TOP")] * 30 + [other()] * 10
    assert qualify(rows, targets, 60, 0.30, 15) == (JAX_TOP, 30, 0.5)


def test_exactly_at_both_thresholds_qualifies():
    rows = [talon_mid()] * 25 + [other()] * 25
    assert qualify(rows, targets, 50, 0.50, 25) == (TALON_MID, 25, 0.5)
