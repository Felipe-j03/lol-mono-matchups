"""SQLite storage and resume bookkeeping.

Writes do not commit on their own: callers call ``commit()`` once per batch,
so an interruption loses at most the current batch.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from lolmono.rows import MatchRow, PlayerRow, RunePage, TimelineRow

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candidate (
    platform TEXT NOT NULL,
    puuid TEXT NOT NULL,
    screened INTEGER NOT NULL DEFAULT 0,
    suspect INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (platform, puuid)
);
CREATE TABLE IF NOT EXISTS player (
    platform TEXT NOT NULL,
    puuid TEXT NOT NULL,
    riot_id TEXT NOT NULL DEFAULT '',
    champion_id INTEGER,
    role TEXT,
    games INTEGER NOT NULL DEFAULT 0,
    share REAL NOT NULL DEFAULT 0,
    confirmed INTEGER NOT NULL,
    PRIMARY KEY (platform, puuid)
);
CREATE TABLE IF NOT EXISTS "match" (
    match_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    puuid TEXT NOT NULL,
    champion_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    opponent_champion_id INTEGER NOT NULL,
    opponent_puuid TEXT NOT NULL,
    win INTEGER NOT NULL,
    items TEXT NOT NULL,
    runes TEXT NOT NULL,
    spells TEXT NOT NULL,
    PRIMARY KEY (match_id, puuid)
);
CREATE TABLE IF NOT EXISTS timeline (
    match_id TEXT NOT NULL,
    puuid TEXT NOT NULL,
    gold_at_14 INTEGER,
    cs_diff_at_14 INTEGER,
    starting_items TEXT NOT NULL,
    item_order TEXT NOT NULL,
    skill_order TEXT,
    deaths_before_10 INTEGER NOT NULL,
    kills_before_10 INTEGER NOT NULL,
    PRIMARY KEY (match_id, puuid)
);
-- Pairs whose timeline will not be requested again: Riot has none ('not_found',
-- a normal 404) or we could not read it ('parse_error', our bug, not Riot's).
-- A marker is NOT a timeline: aggregation never sees these pairs. Deleting the
-- 'parse_error' rows re-queues them after the parser is fixed.
CREATE TABLE IF NOT EXISTS timeline_missing (
    match_id TEXT NOT NULL,
    puuid TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY (match_id, puuid)
);
CREATE TABLE IF NOT EXISTS discard (
    match_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY (match_id, reason)
);
"""

# A match counts only when its player is confirmed for that exact champion/role.
_CONFIRMED_JOIN = """
FROM "match" m
JOIN player p ON p.platform = m.platform AND p.puuid = m.puuid
WHERE p.confirmed = 1
  AND p.champion_id = m.champion_id AND p.role = m.role
  AND m.champion_id = ? AND m.role = ?
"""


class SchemaError(Exception):
    """The database file was created by an incompatible earlier schema."""


def _match_from_row(r: sqlite3.Row) -> MatchRow:
    runes = json.loads(r["runes"])
    return MatchRow(
        match_id=r["match_id"],
        platform=r["platform"],
        puuid=r["puuid"],
        champion_id=r["champion_id"],
        role=r["role"],
        opponent_champion_id=r["opponent_champion_id"],
        opponent_puuid=r["opponent_puuid"],
        win=bool(r["win"]),
        items=tuple(json.loads(r["items"])),
        runes=RunePage(
            keystone=runes["keystone"],
            primary_style=runes["primary_style"],
            primary_perks=tuple(runes["primary_perks"]),
            secondary_style=runes["secondary_style"],
            secondary_perks=tuple(runes["secondary_perks"]),
            shards=tuple(runes["shards"]),
        ),
        spells=tuple(json.loads(r["spells"])),
    )


def _timeline_from_row(r: sqlite3.Row) -> TimelineRow:
    return TimelineRow(
        match_id=r["match_id"],
        puuid=r["puuid"],
        gold_at_14=r["gold_at_14"],
        cs_diff_at_14=r["cs_diff_at_14"],
        starting_items=tuple(json.loads(r["starting_items"])),
        item_order=tuple(json.loads(r["item_order"])),
        skill_order=(
            None if r["skill_order"] is None else tuple(json.loads(r["skill_order"]))
        ),
        deaths_before_10=r["deaths_before_10"],
        kills_before_10=r["kills_before_10"],
    )


class Database:
    def __init__(self, path: Path):
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")

    def commit(self) -> None:
        self._conn.commit()

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Commit on clean exit; on an exception, roll back and re-raise."""
        try:
            yield
        except BaseException:
            self._conn.rollback()
            raise
        self.commit()

    def close(self) -> None:
        """Close the connection; uncommitted writes are discarded."""
        self._conn.close()

    def init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._refuse_old_timeline_schema()

    def _refuse_old_timeline_schema(self) -> None:
        # Early builds declared skill_order NOT NULL. insert_timeline is INSERT OR
        # IGNORE, so a short game (skill_order None) would be dropped silently and
        # its match re-requested on every run. There is no migration: refuse.
        for column in self._conn.execute("PRAGMA table_info(timeline)"):
            if column["name"] == "skill_order" and column["notnull"]:
                raise SchemaError(
                    "o banco foi criado com um esquema antigo (timeline.skill_order "
                    "NOT NULL): timelines de partidas curtas seriam descartadas em "
                    "silencio e pedidas de novo a cada execucao. Nao ha migracao; "
                    "apague o arquivo do banco e recomece a coleta."
                )

    def table_names(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [r["name"] for r in rows]

    # --- candidate screening progress -------------------------------------

    def add_candidates(self, platform: str, puuids: list[str]) -> None:
        self._conn.executemany(
            "INSERT OR IGNORE INTO candidate (platform, puuid) VALUES (?, ?)",
            [(platform, p) for p in puuids],
        )

    def pending_candidates(self, platform: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT puuid FROM candidate WHERE platform = ? AND screened = 0 "
            "ORDER BY rowid",
            (platform,),
        )
        return [r["puuid"] for r in rows]

    def mark_screened(self, platform: str, puuid: str, suspect: bool) -> None:
        self._conn.execute(
            "UPDATE candidate SET screened = 1, suspect = ? "
            "WHERE platform = ? AND puuid = ?",
            (int(suspect), platform, puuid),
        )

    def pending_suspects(self, platform: str) -> list[str]:
        """Screened suspects not yet confirmed or rejected."""
        rows = self._conn.execute(
            "SELECT c.puuid FROM candidate c "
            "LEFT JOIN player p ON p.platform = c.platform AND p.puuid = c.puuid "
            "WHERE c.platform = ? AND c.screened = 1 AND c.suspect = 1 "
            "AND p.puuid IS NULL ORDER BY c.rowid",
            (platform,),
        )
        return [r["puuid"] for r in rows]

    # --- player verdicts ---------------------------------------------------

    def confirm_player(
        self,
        platform: str,
        puuid: str,
        riot_id: str,
        champion_id: int,
        role: str,
        games: int,
        share: float,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO player "
            "(platform, puuid, riot_id, champion_id, role, games, share, confirmed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (platform, puuid, riot_id, champion_id, role, games, share),
        )

    def reject_player(self, platform: str, puuid: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO player (platform, puuid, confirmed) "
            "VALUES (?, ?, 0)",
            (platform, puuid),
        )

    # --- matches -----------------------------------------------------------

    def insert_match(self, row: MatchRow) -> None:
        r = row.runes
        runes = {
            "keystone": r.keystone,
            "primary_style": r.primary_style,
            "primary_perks": list(r.primary_perks),
            "secondary_style": r.secondary_style,
            "secondary_perks": list(r.secondary_perks),
            "shards": list(r.shards),
        }
        self._conn.execute(
            'INSERT OR IGNORE INTO "match" (match_id, platform, puuid, champion_id, '
            "role, opponent_champion_id, opponent_puuid, win, items, runes, spells) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row.match_id,
                row.platform,
                row.puuid,
                row.champion_id,
                row.role,
                row.opponent_champion_id,
                row.opponent_puuid,
                int(row.win),
                json.dumps(list(row.items)),
                json.dumps(runes),
                json.dumps(list(row.spells)),
            ),
        )

    def match_exists(self, match_id: str, puuid: str) -> bool:
        return (
            self._conn.execute(
                'SELECT 1 FROM "match" WHERE match_id = ? AND puuid = ?',
                (match_id, puuid),
            ).fetchone()
            is not None
        )

    def confirmed_matches(self, champion_id: int, role: str) -> list[MatchRow]:
        rows = self._conn.execute(
            "SELECT m.* " + _CONFIRMED_JOIN + " ORDER BY m.match_id, m.puuid",
            (champion_id, role),
        )
        return [_match_from_row(r) for r in rows]

    # --- discards ----------------------------------------------------------

    def record_discard(self, match_id: str, reason: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO discard (match_id, reason) VALUES (?, ?)",
            (match_id, reason),
        )

    def discard_counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT reason, COUNT(*) AS n FROM discard GROUP BY reason"
        )
        return {r["reason"]: r["n"] for r in rows}

    # --- timelines ---------------------------------------------------------

    def insert_timeline(self, row: TimelineRow) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO timeline (match_id, puuid, gold_at_14, "
            "cs_diff_at_14, starting_items, item_order, skill_order, "
            "deaths_before_10, kills_before_10) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row.match_id,
                row.puuid,
                row.gold_at_14,
                row.cs_diff_at_14,
                json.dumps(list(row.starting_items)),
                json.dumps(list(row.item_order)),
                None if row.skill_order is None else json.dumps(list(row.skill_order)),
                row.deaths_before_10,
                row.kills_before_10,
            ),
        )

    def mark_timeline_missing(self, match_id: str, puuid: str, reason: str) -> None:
        """Remember that this pair's timeline must not be requested again.

        Deliberately not a TimelineRow: no numbers are invented for aggregation.
        """
        self._conn.execute(
            "INSERT OR IGNORE INTO timeline_missing (match_id, puuid, reason) "
            "VALUES (?, ?, ?)",
            (match_id, puuid, reason),
        )

    def matches_awaiting_timeline(
        self, platform: str | None = None
    ) -> list[tuple[str, str, str]]:
        """(match_id, puuid, opponent_puuid) for confirmed players still to fetch.

        Excludes pairs that already have a timeline and pairs marked missing, so a
        404 or an unreadable payload is never paid for twice. With ``platform``,
        only that platform's matches: a client talks to one regional host and
        would 404 another region's matches.
        """
        query = (
            'SELECT m.match_id, m.puuid, m.opponent_puuid FROM "match" m '
            "JOIN player p ON p.platform = m.platform AND p.puuid = m.puuid "
            "WHERE p.confirmed = 1 AND p.champion_id = m.champion_id "
            "AND p.role = m.role "
            "AND NOT EXISTS (SELECT 1 FROM timeline t "
            "WHERE t.match_id = m.match_id AND t.puuid = m.puuid) "
            "AND NOT EXISTS (SELECT 1 FROM timeline_missing x "
            "WHERE x.match_id = m.match_id AND x.puuid = m.puuid) "
        )
        params: tuple = ()
        if platform is not None:
            query += "AND m.platform = ? "
            params = (platform,)
        rows = self._conn.execute(query + "ORDER BY m.match_id, m.puuid", params)
        return [(r[0], r[1], r[2]) for r in rows]

    def timelines_for(
        self, match_ids: list[str]
    ) -> dict[tuple[str, str], TimelineRow]:
        wanted = list(match_ids)
        result: dict[tuple[str, str], TimelineRow] = {}
        for i in range(0, len(wanted), 500):  # stay under SQLite's variable limit
            chunk = wanted[i : i + 500]
            marks = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                f"SELECT * FROM timeline WHERE match_id IN ({marks})", chunk
            )
            for r in rows:
                tl = _timeline_from_row(r)
                result[(tl.match_id, tl.puuid)] = tl
        return result

    # --- aggregates --------------------------------------------------------

    def confirmed_player_count(self, champion_id: int, role: str) -> int:
        return self._conn.execute(
            "SELECT COUNT(DISTINCT m.platform || char(0) || m.puuid) "
            + _CONFIRMED_JOIN,
            (champion_id, role),
        ).fetchone()[0]

    def confirmed_group_win_rate(self, champion_id: int, role: str) -> float:
        row = self._conn.execute(
            "SELECT AVG(m.win) " + _CONFIRMED_JOIN, (champion_id, role)
        ).fetchone()
        return float(row[0]) if row[0] is not None else 0.0

    def confirmed_players(self, champion_id: int, role: str) -> list[PlayerRow]:
        rows = self._conn.execute(
            "SELECT p.platform, p.puuid, p.riot_id, p.champion_id, p.role, "
            "p.games, p.share, COALESCE(AVG(m.win), 0.0) AS win_rate "
            "FROM player p LEFT JOIN \"match\" m ON m.platform = p.platform "
            "AND m.puuid = p.puuid AND m.champion_id = p.champion_id "
            "AND m.role = p.role "
            "WHERE p.confirmed = 1 AND p.champion_id = ? AND p.role = ? "
            "GROUP BY p.platform, p.puuid ORDER BY p.riot_id",
            (champion_id, role),
        )
        return [
            PlayerRow(
                platform=r["platform"],
                puuid=r["puuid"],
                riot_id=r["riot_id"],
                champion_id=r["champion_id"],
                role=r["role"],
                games=r["games"],
                share=r["share"],
                win_rate=float(r["win_rate"]),
            )
            for r in rows
        ]
