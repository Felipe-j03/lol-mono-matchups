from lolmono.config import Target
from lolmono.riot import Mastery
from lolmono.screen import is_suspect

TALON = 91
ZED = 238
GRAGAS = 79
ZED_FILLER = [10, 11, 12, 13, 14, 15, 16]

DAY_MS = 24 * 60 * 60 * 1000
now_ms = 1_750_000_000_000
targets = [Target(TALON, "Talon", "MIDDLE")]


def days(n: int) -> int:
    return n * DAY_MS


def test_suspect_when_target_champion_is_top_and_recent():
    masteries = [Mastery(TALON, 500_000, now_ms - days(3))]
    assert is_suspect(masteries, targets, top_n=7, max_days=30, now_ms=now_ms)


def test_not_suspect_when_target_not_played_recently():
    masteries = [Mastery(TALON, 500_000, now_ms - days(400))]
    assert not is_suspect(masteries, targets, top_n=7, max_days=30, now_ms=now_ms)


def test_not_suspect_when_no_target_champion_present():
    masteries = [Mastery(ZED, 900_000, now_ms)]
    assert not is_suspect(masteries, targets, top_n=7, max_days=30, now_ms=now_ms)


def test_only_the_first_top_n_entries_count():
    # alvo na oitava posicao por pontos, top_n=7
    masteries = [
        Mastery(champion_id, 900_000 - i * 1_000, now_ms)
        for i, champion_id in enumerate(ZED_FILLER)
    ]
    masteries.append(Mastery(TALON, 1_000, now_ms))
    assert len(masteries) == 8
    assert not is_suspect(masteries, targets, top_n=7, max_days=30, now_ms=now_ms)


def test_target_in_last_counted_top_n_position_is_suspect():
    # alvo na setima posicao por pontos, top_n=7: ainda conta
    masteries = [
        Mastery(champion_id, 900_000 - i * 1_000, now_ms)
        for i, champion_id in enumerate(ZED_FILLER[:6])
    ]
    masteries.append(Mastery(TALON, 1_000, now_ms))
    assert len(masteries) == 7
    assert is_suspect(masteries, targets, top_n=7, max_days=30, now_ms=now_ms)


def test_role_is_not_considered_at_this_stage():
    # a maestria nao traz funcao; um unico alvo com aquele champion_id basta,
    # qualquer que seja a role configurada
    masteries = [Mastery(GRAGAS, 400_000, now_ms)]
    assert is_suspect(masteries, [Target(GRAGAS, "Gragas", "TOP")], 7, 30, now_ms)
