from lolmono.config import Target
from lolmono.mono import qualify as _qualify
from lolmono.rows import MatchRow, RunePage

# info.gameCreation of the fixtures, epoch ms (2025-11-02 00:00 UTC).
GAME_CREATED = 1_762_041_600_000


def qualify(rows, targets, window_games, min_share, min_games, window_size=None):
    """``qualify`` for a player whose games were ALL parsed.

    The real ``qualify`` requires ``window_size``, the number of games the player
    actually played in the window, because a discarded game must stay in the
    share's denominator. With nothing discarded that is just the rows, which is
    what every test below assumes; the discard cases pass ``window_size``
    themselves.
    """
    if window_size is None:
        window_size = min(len(rows), window_games)
    return _qualify(
        rows, targets, window_games, min_share, min_games, window_size=window_size
    )


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
        game_created=GAME_CREATED,
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


def test_even_two_role_split_meets_a_half_share_threshold():
    # Follows from the spec's ">= 50% das partidas": 26/52 = 0.50 qualifies, for
    # the first matching target. The roles are counted separately (neither role
    # is credited with the other's games), but each reaches the threshold alone.
    rows = [gragas_top()] * 26 + [gragas_mid()] * 26
    assert qualify(rows, targets, 60, 0.50, 25) == (GRAGAS_MID, 26, 0.5)


def test_raising_min_share_excludes_an_evenly_split_two_role_player():
    rows = [gragas_top()] * 26 + [gragas_mid()] * 26
    assert qualify(rows, targets, 60, 0.60, 25) is None


def test_same_champion_in_two_roles_is_not_pooled():
    # 20 TOP + 20 MIDDLE of 40 games: pooled Gragas would be 100%, per role it
    # is 50% with 20 games each, below min_games.
    rows = [gragas_top()] * 20 + [gragas_mid()] * 20
    assert qualify(rows, targets, 60, 0.50, 25) is None


def test_low_volume_specialist_qualifies_on_the_games_actually_played():
    # 30 Talon out of 40 games: share 0.75. Under a window_games divisor the
    # player still qualifies (30/60 = 0.5) but with the wrong share, 0.5.
    rows = [talon_mid()] * 30 + [other()] * 10
    assert qualify(rows, targets, 60, 0.50, 25) == (TALON_MID, 30, 0.75)


def test_low_volume_specialist_below_the_window_is_not_lost():
    # Fails under a window_games divisor: 25/60 = 0.417 < 0.50.
    rows = [talon_mid()] * 25 + [other()] * 5  # 25 of 30 games = 0.833
    assert qualify(rows, targets, 60, 0.50, 25) == (TALON_MID, 25, 25 / 30)


def test_min_games_rejects_a_high_share_on_a_tiny_sample():
    rows = [talon_mid()] * 8 + [other()] * 4  # 0.67, but 8 < 25
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


# --- discarded games stay in the denominator ---------------------------------


def test_discarded_games_stay_in_the_share_denominator():
    # 60 ranked games played, 10 of them discarded by the extractor, 25 Talon
    # mid among the 50 that parsed. Counting only the parsed rows gives
    # 25/50 = 0.50 and qualifies; the truth is 25/60 = 0.4167 and the spec
    # rejects it. The bias is always upward and grows with the discard rate.
    rows = [talon_mid()] * 25 + [other()] * 25
    assert _qualify(
        rows, targets, 60, 0.50, 25, window_size=60
    ) is None


def test_the_same_player_qualifies_when_nothing_was_discarded():
    # The control for the test above: same rows, no discards.
    rows = [talon_mid()] * 25 + [other()] * 25
    assert _qualify(rows, targets, 60, 0.50, 25, window_size=50) == (
        TALON_MID,
        25,
        0.5,
    )


def test_the_published_share_is_the_one_over_games_played():
    rows = [talon_mid()] * 30 + [other()] * 10
    # 40 parsed of 50 played: 30/50, not 30/40.
    verdict = _qualify(rows, targets, 60, 0.50, 25, window_size=50)
    assert verdict == (TALON_MID, 30, 0.6)


def test_window_size_cannot_push_a_share_above_one():
    # A caller that under-reports (fewer played than parsed) is a bug, not a
    # reason to publish a share greater than 1.
    rows = [talon_mid()] * 30
    target, games, share = _qualify(rows, targets, 60, 0.50, 25, window_size=3)
    assert (target, games) == (TALON_MID, 30)
    assert share == 1.0


def test_window_size_is_capped_by_the_window():
    # Riot returning more ids than asked must not shrink the share below the
    # window it is defined over.
    rows = [talon_mid()] * 40 + [other()] * 20
    assert _qualify(rows, targets, 60, 0.50, 25, window_size=200) == (
        TALON_MID,
        40,
        40 / 60,
    )
