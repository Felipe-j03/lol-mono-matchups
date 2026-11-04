import pytest

from lolmono.ratelimit import RateLimiter, riot_limiter


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def advance_recording(self, slept):
        def sleep(seconds):
            slept.append(seconds)
            self.t += seconds

        return sleep


def make(limits=None):
    clock, slept = FakeClock(), []
    sleep = clock.advance_recording(slept)
    if limits is None:
        rl = riot_limiter(now=clock.now, sleep=sleep)
    else:
        rl = RateLimiter(limits, now=clock.now, sleep=sleep)
    return rl, clock, slept


def test_allows_burst_up_to_shortest_window():
    rl, _, slept = make()
    for _ in range(20):
        rl.acquire()
    assert slept == []


def test_sleeps_when_one_second_window_full():
    # A 21a requisicao espera a janela de 1s abrir INTEIRA: as 20 primeiras
    # saem todas em t=0, entao a mais antiga so sai da janela em t=1.0. Um
    # intervalo ("maior que zero, no maximo 1s") aceitaria 0.001 e deixaria o
    # limitador estourar o limite da Riot sem nenhum teste reclamar.
    rl, _, slept = make()
    for _ in range(20):
        rl.acquire()
    rl.acquire()
    assert slept == [pytest.approx(1.0)]


def test_enforces_two_minute_window_as_well():
    # 100 requisicoes: 20 por segundo, das quais a ultima leva o relogio a
    # t=4.0. A 101a espera 116s, o que falta para a PRIMEIRA (em t=0) sair da
    # janela de 2 minutos. A janela de 1 segundo tambem esta cheia nesse
    # instante (as 20 ultimas sairam todas em t=4.0); quem manda e a espera
    # maior das duas.
    rl, clock, slept = make()
    for _ in range(100):
        rl.acquire()
    assert clock.now() == pytest.approx(4.0)
    slept.clear()
    rl.acquire()
    assert slept == [pytest.approx(116.0)]
    assert clock.now() == pytest.approx(120.0)


def test_rechecks_all_windows_after_sleeping():
    # acordar pela janela curta nao basta: a longa continua cheia
    rl, clock, slept = make([(1, 1.0), (2, 10.0)])
    rl.acquire()
    rl.acquire()  # dorme 1s pela janela curta
    rl.acquire()  # janela curta livre, mas a longa esta cheia
    assert slept == [pytest.approx(1.0), pytest.approx(9.0)]
    assert clock.now() == pytest.approx(10.0)


def test_penalize_blocks_until_retry_after_elapses():
    rl, _, slept = make()
    rl.penalize(5.0)
    rl.acquire()
    assert slept[-1] == pytest.approx(5.0)


def test_penalize_alone_consumes_no_slot():
    rl, _, slept = make([(1, 10.0)])
    rl.penalize(5.0)
    rl.acquire()
    assert slept == [pytest.approx(5.0)]
