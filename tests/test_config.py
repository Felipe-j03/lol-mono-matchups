from pathlib import Path

import pytest

from lolmono.config import Config, ConfigError, Target, load_config

EXAMPLE = Path(__file__).resolve().parent.parent / "config.example.toml"


def tmp_toml(tmp_path=None, **overrides):
    """Write a valid config to a temp file, with top-level overrides."""
    values = {
        "regions": '["br1"]',
        "window_games": "60",
        "min_share": "0.5",
        "min_games": "25",
        "min_tier": '"MASTER"',
        "mastery_top_n": "7",
        "mastery_max_days": "30",
        "matchup_min_games": "30",
        "delta_min_per_side": "15",
        "ddragon_version": '"16.21.1"',
    }
    role = overrides.pop("role", "MIDDLE")
    targets = overrides.pop("targets", None)
    for k, v in overrides.items():
        values[k] = repr(v) if not isinstance(v, str) else f'"{v}"'
        if isinstance(v, list):
            values[k] = "[" + ", ".join(f'"{x}"' for x in v) + "]"
    lines = [f"{k} = {v}" for k, v in values.items()]
    if targets is None:
        targets = [(91, "Talon", role)]
    for cid, name, r in targets:
        lines += [
            "[[targets]]",
            f"champion_id = {cid}",
            f'champion_name = "{name}"',
            f'role = "{r}"',
        ]
    path = tmp_path / "c.toml"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_loads_example_config_with_spec_defaults():
    cfg = load_config(EXAMPLE)
    assert cfg.window_games == 60
    assert cfg.min_share == 0.50
    assert cfg.min_games == 25
    assert cfg.min_tier == "DIAMOND"
    assert cfg.matchup_min_games == 20
    assert cfg.delta_min_per_side == 10
    assert cfg.regions == ("br1", "kr", "euw1", "na1")
    assert Target(91, "Talon", "MIDDLE") in cfg.targets
    assert len(cfg.targets) == 5
    assert cfg.tiers == ("CHALLENGER", "GRANDMASTER", "MASTER", "DIAMOND")


def test_config_is_frozen_and_hashable():
    cfg = load_config(EXAMPLE)
    assert isinstance(cfg, Config)
    hash(cfg)
    with pytest.raises(Exception):
        cfg.window_games = 1


def test_rejects_unknown_role(tmp_path):
    with pytest.raises(ConfigError, match="role"):
        load_config(tmp_toml(tmp_path, role="SUPPORT"))


def test_rejects_share_outside_unit_interval(tmp_path):
    with pytest.raises(ConfigError, match="min_share"):
        load_config(tmp_toml(tmp_path, min_share=1.5))
    with pytest.raises(ConfigError, match="min_share"):
        load_config(tmp_toml(tmp_path, min_share=0))


def test_accepts_share_of_exactly_one(tmp_path):
    assert load_config(tmp_toml(tmp_path, min_share=1.0)).min_share == 1.0


def test_rejects_non_positive_integer(tmp_path):
    with pytest.raises(ConfigError, match="min_games"):
        load_config(tmp_toml(tmp_path, min_games=0))


def test_rejects_empty_regions(tmp_path):
    with pytest.raises(ConfigError, match="regions"):
        load_config(tmp_toml(tmp_path, regions=[]))


def test_rejects_duplicate_champion_role_pair(tmp_path):
    targets = [(91, "Talon", "MIDDLE"), (91, "Talon", "MIDDLE")]
    with pytest.raises(ConfigError, match="targets"):
        load_config(tmp_toml(tmp_path, targets=targets))


def test_allows_same_champion_in_different_roles(tmp_path):
    targets = [(79, "Gragas", "MIDDLE"), (79, "Gragas", "TOP")]
    cfg = load_config(tmp_toml(tmp_path, targets=targets))
    assert len(cfg.targets) == 2


def test_rejects_unknown_min_tier(tmp_path):
    with pytest.raises(ConfigError, match="min_tier"):
        load_config(tmp_toml(tmp_path, min_tier="GOLD"))


def test_min_tier_diamond_includes_all_tiers(tmp_path):
    cfg = load_config(tmp_toml(tmp_path, min_tier="DIAMOND"))
    assert cfg.tiers == ("CHALLENGER", "GRANDMASTER", "MASTER", "DIAMOND")


def test_rejects_missing_field(tmp_path):
    p = tmp_toml(tmp_path)
    p.write_text(p.read_text().replace("window_games = 60\n", ""), encoding="utf-8")
    with pytest.raises(ConfigError, match="window_games"):
        load_config(p)
