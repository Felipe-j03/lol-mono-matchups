from collections.abc import Sequence

from lolmono.config import Target
from lolmono.riot import Mastery

_MS_PER_DAY = 24 * 60 * 60 * 1000


def is_suspect(
    masteries: Sequence[Mastery],
    targets: Sequence[Target],
    top_n: int,
    max_days: int,
    now_ms: int,
) -> bool:
    """Pre-filtro barato: o jogador merece ver partidas? Nao prova mono-champion."""
    target_ids = {t.champion_id for t in targets}
    cutoff_ms = now_ms - max_days * _MS_PER_DAY
    top = sorted(masteries, key=lambda m: m.points, reverse=True)[:top_n]
    return any(
        m.champion_id in target_ids and m.last_play_ms >= cutoff_ms
        for m in top
    )
