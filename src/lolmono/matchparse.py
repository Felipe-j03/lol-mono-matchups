"""Turn a raw Riot match payload into a MatchRow, or reject it.

The role of the tracked player comes from `teamPosition` and from nothing else.
`individualPosition`, `lane`, `role` and participant order are never consulted:
an ambiguous match is discarded with an explicit reason, never guessed at.
"""

from collections.abc import Sequence

from lolmono.rows import MatchRow, RunePage

RANKED_SOLO_QUEUE = 420
POSITIONS = frozenset({"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"})
_BUILD_ITEM_SLOTS = 6  # item0..item5; item6 is the trinket/vision slot


class DiscardMatch(Exception):
    """The match cannot be used. `reason` is one of the four report strings:
    "missing_position", "unpaired_lanes", "wrong_queue", "puuid_absent"."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def pair_lanes(participants: Sequence[dict]) -> dict[str, tuple[dict, dict]]:
    """Pair the two participants holding each position, one per team.

    Raises DiscardMatch("missing_position") if any participant has an empty or
    absent `teamPosition`, then DiscardMatch("unpaired_lanes") unless the
    participants form exactly two teams of five that each hold the five
    positions once. Each pair is ordered by ascending teamId.
    """
    if any(not p.get("teamPosition") for p in participants):
        raise DiscardMatch("missing_position")

    teams: dict[int, dict[str, dict]] = {}
    for p in participants:
        by_position = teams.setdefault(p.get("teamId"), {})
        if p["teamPosition"] in by_position:
            raise DiscardMatch("unpaired_lanes")
        by_position[p["teamPosition"]] = p

    if len(teams) != 2 or any(set(t) != POSITIONS for t in teams.values()):
        raise DiscardMatch("unpaired_lanes")

    first, second = (teams[team_id] for team_id in sorted(teams))
    return {position: (first[position], second[position]) for position in sorted(POSITIONS)}


def extract_match(match_json: dict, puuid: str) -> MatchRow:
    """Build the MatchRow of `puuid` in this match, or raise DiscardMatch.

    Checks run in this order: queue ("wrong_queue"), presence of the puuid
    ("puuid_absent"), then lane pairing ("missing_position", "unpaired_lanes").
    """
    info = match_json["info"]
    if info["queueId"] != RANKED_SOLO_QUEUE:
        raise DiscardMatch("wrong_queue")

    participants = info["participants"]
    me = next((p for p in participants if p["puuid"] == puuid), None)
    if me is None:
        raise DiscardMatch("puuid_absent")

    pairs = pair_lanes(participants)
    role = me["teamPosition"]
    opponent = next(p for p in pairs[role] if p["teamId"] != me["teamId"])

    return MatchRow(
        match_id=match_json["metadata"]["matchId"],
        platform=info["platformId"].lower(),
        puuid=puuid,
        champion_id=me["championId"],
        role=role,
        opponent_champion_id=opponent["championId"],
        opponent_puuid=opponent["puuid"],
        win=me["win"],
        items=_build_items(me),
        runes=_rune_page(me["perks"]),
        spells=(me["summoner1Id"], me["summoner2Id"]),
    )


def _build_items(participant: dict) -> tuple[int, ...]:
    slots = (participant[f"item{i}"] for i in range(_BUILD_ITEM_SLOTS))
    return tuple(item for item in slots if item != 0)


def _rune_page(perks: dict) -> RunePage:
    primary, secondary = perks["styles"][0], perks["styles"][1]
    primary_perks = tuple(s["perk"] for s in primary["selections"])
    stats = perks["statPerks"]
    return RunePage(
        keystone=primary_perks[0],
        primary_style=primary["style"],
        primary_perks=primary_perks,
        secondary_style=secondary["style"],
        secondary_perks=tuple(s["perk"] for s in secondary["selections"]),
        shards=(stats["offense"], stats["flex"], stats["defense"]),
    )
