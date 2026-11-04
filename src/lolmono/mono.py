"""The mono criterion: who counts as a specialist of a target champion and role.

This is the real decision. The mastery screen before it is deliberately loose;
what `qualify` accepts is what every number the product shows is computed from.
"""

from collections import Counter
from collections.abc import Sequence

from lolmono.config import Target
from lolmono.rows import MatchRow


def qualify(
    rows: Sequence[MatchRow],
    targets: Sequence[Target],
    window_games: int,
    min_share: float,
    min_games: int,
    *,
    window_size: int,
) -> tuple[Target, int, float] | None:
    """Return ``(target, games, share)`` for the target this player is mono of.

    ``rows`` must be ordered most recent first: only the first ``window_games``
    count. A target qualifies only if it meets **both** conditions: at least
    ``min_games`` games in the window, and a share of at least ``min_share``,
    where share is ``games / window_size`` (the spec's "responde por >= 50% das
    partidas"). Dividing by the configured ``window_games`` instead would reject
    low-volume specialists.

    ``window_size`` is how many ranked games the player actually PLAYED in the
    window, which is not the same as ``len(rows)``: a match the collector could
    not parse (no clean lane pairing, a broken payload) produces no row but was
    still played. Counting only parsed rows inflates every share, always upward
    and in proportion to the discard rate — 25 Talon games of 60 played with 10
    discarded would read 25/50 = 0.50 and qualify instead of 25/60 = 0.42 and be
    rejected. The caller therefore passes the number of games fetched, and the
    discarded ones stay in the denominator. It is clamped up to the number of
    rows in the window, so a caller that under-reports cannot make a share
    exceed 1.

    Each ``(champion_id, role)`` is its own target, so the same champion in two
    roles is counted separately; an evenly split 26 TOP + 26 MIDDLE player is
    50% each and qualifies at ``min_share=0.5``, and is excluded by raising it.

    Above ``min_share = 0.5`` two targets cannot both qualify. At exactly 0.5
    they can (26 TOP + 26 MIDDLE Gragas are 50% each), and below 0.5 more can.
    The target with the highest count wins; on a tie the one listed first in the
    config wins, so the order of ``[[targets]]`` is significant at those values.
    """
    window = rows[:window_games]
    if not window:
        return None
    played = min(max(window_size, len(window)), window_games)
    counts = Counter((row.champion_id, row.role) for row in window)

    best: tuple[Target, int, float] | None = None
    for target in targets:
        games = counts[(target.champion_id, target.role)]
        share = games / played
        if games < min_games or share < min_share:
            continue
        if best is None or games > best[1]:
            best = (target, games, share)
    return best
