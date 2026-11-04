import tomllib
from dataclasses import dataclass
from pathlib import Path

ROLES = frozenset({"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"})
TIER_ORDER = ("CHALLENGER", "GRANDMASTER", "MASTER", "DIAMOND")

_INT_FIELDS = (
    "window_games",
    "min_games",
    "mastery_top_n",
    "mastery_max_days",
    "matchup_min_games",
    "delta_min_per_side",
)


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Target:
    champion_id: int
    champion_name: str
    role: str


@dataclass(frozen=True)
class Config:
    regions: tuple[str, ...]
    targets: tuple[Target, ...]
    window_games: int
    min_share: float
    min_games: int
    min_tier: str
    tiers: tuple[str, ...]
    mastery_top_n: int
    mastery_max_days: int
    matchup_min_games: int
    delta_min_per_side: int
    ddragon_version: str


def _require(data: dict, key: str):
    if key not in data:
        raise ConfigError(f"missing field: {key}")
    return data[key]


def _positive_int(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{field} must be a positive integer, got {value!r}")
    return value


def _parse_target(raw) -> Target:
    if not isinstance(raw, dict):
        raise ConfigError("targets entries must be tables")
    champion_id = _positive_int(_require(raw, "champion_id"), "champion_id")
    name = _require(raw, "champion_name")
    if not isinstance(name, str) or not name:
        raise ConfigError("champion_name must be a non-empty string")
    role = _require(raw, "role")
    if role not in ROLES:
        raise ConfigError(f"role must be one of {sorted(ROLES)}, got {role!r}")
    return Target(champion_id, name, role)


def load_config(path: Path) -> Config:
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML: {e}") from e

    regions = _require(data, "regions")
    if (
        not isinstance(regions, list)
        or not regions
        or not all(isinstance(r, str) and r for r in regions)
    ):
        raise ConfigError("regions must be a non-empty list of strings")

    raw_targets = _require(data, "targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise ConfigError("targets must be a non-empty list")
    targets = tuple(_parse_target(t) for t in raw_targets)
    pairs = [(t.champion_id, t.role) for t in targets]
    if len(set(pairs)) != len(pairs):
        raise ConfigError("targets contains duplicate (champion_id, role) pair")

    ints = {f: _positive_int(_require(data, f), f) for f in _INT_FIELDS}

    min_share = _require(data, "min_share")
    if (
        isinstance(min_share, bool)
        or not isinstance(min_share, (int, float))
        or not 0 < min_share <= 1
    ):
        raise ConfigError(f"min_share must be in (0, 1], got {min_share!r}")

    min_tier = _require(data, "min_tier")
    if min_tier not in TIER_ORDER:
        raise ConfigError(f"min_tier must be one of {list(TIER_ORDER)}, got {min_tier!r}")
    tiers = TIER_ORDER[: TIER_ORDER.index(min_tier) + 1]

    version = _require(data, "ddragon_version")
    if not isinstance(version, str) or not version:
        raise ConfigError("ddragon_version must be a non-empty string")

    return Config(
        regions=tuple(regions),
        targets=targets,
        min_share=float(min_share),
        min_tier=min_tier,
        tiers=tiers,
        ddragon_version=version,
        **ints,
    )
