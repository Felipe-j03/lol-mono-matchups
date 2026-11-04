"""Frozen record types shared across the project. Standard library only."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RunePage:
    keystone: int
    primary_style: int
    primary_perks: tuple[int, ...]
    secondary_style: int
    secondary_perks: tuple[int, ...]
    shards: tuple[int, int, int]


@dataclass(frozen=True)
class MatchRow:
    match_id: str
    platform: str
    puuid: str
    champion_id: int
    role: str
    opponent_champion_id: int
    opponent_puuid: str
    win: bool
    items: tuple[int, ...]
    runes: RunePage
    spells: tuple[int, int]


@dataclass(frozen=True)
class TimelineRow:
    match_id: str
    puuid: str
    gold_at_14: int | None
    cs_diff_at_14: int | None
    starting_items: tuple[int, ...]
    item_order: tuple[int, ...]
    skill_order: tuple[int, int, int] | None
    deaths_before_10: int
    kills_before_10: int


@dataclass(frozen=True)
class PlayerRow:
    platform: str
    puuid: str
    riot_id: str
    champion_id: int
    role: str
    games: int
    share: float
    win_rate: float
