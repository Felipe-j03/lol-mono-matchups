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
) -> tuple[Target, int, float] | None:
    """Return ``(target, games, share)`` for the target this player is mono of.

    ``rows`` must be ordered most recent first: only the first ``window_games``
    count. A target qualifies only if it meets **both** conditions: at least
    ``min_games`` games in the window, and a share of at least ``min_share``,
    where share is ``games / window_games``. The denominator is the configured
    window, not the games the player happens to have: a player with a short
    history is not promoted to mono by a small denominator. Each
    ``(champion_id, role)`` is its own target, so the same champion in two roles
    is counted separately (26 TOP + 26 MIDDLE qualifies for neither).

    With ``min_share >= 0.5`` two targets cannot both qualify; below that, the
    target with the highest count wins (the first listed, on a tie).
    """
    window = rows[:window_games]
    if not window:
        return None
    counts = Counter((row.champion_id, row.role) for row in window)

    best: tuple[Target, int, float] | None = None
    for target in targets:
        games = counts[(target.champion_id, target.role)]
        share = games / window_games
        if games < min_games or share < min_share:
            continue
        if best is None or games > best[1]:
            best = (target, games, share)
    return best
