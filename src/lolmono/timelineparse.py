"""Reduce a raw Riot match timeline to a TimelineRow.

Timelines are the heaviest payload in the project and the caller discards the
raw JSON right after this runs, so anything not extracted here is gone. Only
frames up to minute 15 are walked; later frames are never looked into.
"""

from lolmono.rows import TimelineRow

MINUTE_MS = 60_000
GAME_FRAME_MS = 14 * MINUTE_MS  # the snapshot the matchup comparison is made at
FRAME_WINDOW_MS = 15 * MINUTE_MS  # frames after this are not traversed
STARTING_ITEMS_MS = 60_000  # pre-game shop sits at ~0; nobody shops twice in a minute
KILL_WINDOW_MS = 10 * MINUTE_MS  # kills/deaths strictly before this count
SKILL_POINTS = 3


def _participant_id(timeline_json: dict, puuid: str) -> int:
    """Index of `puuid` in metadata.participants, plus one."""
    return timeline_json["metadata"]["participants"].index(puuid) + 1


def _creep_score(stats: dict) -> int:
    return stats["minionsKilled"] + stats["jungleMinionsKilled"]


def _remove_last(items: list[int], item_id: int) -> None:
    """Drop the last occurrence of item_id; do nothing if it is not there."""
    for i in range(len(items) - 1, -1, -1):
        if items[i] == item_id:
            del items[i]
            return


def extract_timeline(timeline_json: dict, puuid: str, opponent_puuid: str) -> TimelineRow:
    """Extract the early-game numbers of `puuid` against `opponent_puuid`.

    `gold_at_14` and `cs_diff_at_14` come from the frame with the greatest
    timestamp <= 14:00, and only if the timeline holds a frame at or after
    14:00. A match that ended earlier still has a last frame below 14:00, and
    reporting it as "gold at 14" would be false, so both fields are None then.

    `item_order` covers the first 15 minutes only, because that is as far as
    frames are traversed. It is NOT the full build path: the final build comes
    from the match payload (see matchparse). Sales and undos remove the last
    occurrence of the item from the order; an unknown item is ignored.

    Raises ValueError if either puuid is not in metadata.participants or the
    player has fewer than three NORMAL skill points in the first 15 minutes.
    """
    pid = _participant_id(timeline_json, puuid)
    opp_pid = _participant_id(timeline_json, opponent_puuid)

    reached_14 = False
    frame_14_ms = -1
    frame_14_stats: dict | None = None
    purchases: list[tuple[int, int]] = []  # (itemId, timestamp), for starting_items
    item_order: list[int] = []
    skill_order: list[int] = []
    kills = deaths = 0

    for frame in timeline_json["info"]["frames"]:
        ts = frame["timestamp"]
        if ts > FRAME_WINDOW_MS:
            reached_14 = True  # a frame past 15:00 proves the game got to 14:00
            break
        if ts >= GAME_FRAME_MS:
            reached_14 = True
        if frame_14_ms < ts <= GAME_FRAME_MS:
            frame_14_ms = ts
            frame_14_stats = frame["participantFrames"]

        for event in frame["events"]:
            kind = event["type"]
            if kind == "ITEM_PURCHASED":
                if event["participantId"] == pid:
                    purchases.append((event["itemId"], event["timestamp"]))
                    item_order.append(event["itemId"])
            elif kind == "ITEM_SOLD":
                if event["participantId"] == pid:
                    _remove_last(item_order, event["itemId"])
            elif kind == "ITEM_UNDO":
                if event["participantId"] == pid:
                    _remove_last(item_order, event["beforeId"])
            elif kind == "SKILL_LEVEL_UP":
                if (
                    event["participantId"] == pid
                    and event["levelUpType"] == "NORMAL"
                    and len(skill_order) < SKILL_POINTS
                ):
                    skill_order.append(event["skillSlot"])
            elif kind == "CHAMPION_KILL":
                if event["timestamp"] < KILL_WINDOW_MS:
                    if event["victimId"] == pid:
                        deaths += 1
                    if event.get("killerId") == pid:
                        kills += 1

    if len(skill_order) < SKILL_POINTS:
        raise ValueError(
            f"expected {SKILL_POINTS} skill points in the first 15 minutes, found {len(skill_order)}"
        )

    gold_at_14 = cs_diff_at_14 = None
    if reached_14 and frame_14_stats is not None:
        mine = frame_14_stats[str(pid)]
        theirs = frame_14_stats[str(opp_pid)]
        gold_at_14 = mine["totalGold"]
        cs_diff_at_14 = _creep_score(mine) - _creep_score(theirs)

    return TimelineRow(
        match_id=timeline_json["metadata"]["matchId"],
        puuid=puuid,
        gold_at_14=gold_at_14,
        cs_diff_at_14=cs_diff_at_14,
        starting_items=tuple(item for item, ts in purchases if ts <= STARTING_ITEMS_MS),
        item_order=tuple(item_order),
        skill_order=(skill_order[0], skill_order[1], skill_order[2]),
        deaths_before_10=deaths,
        kills_before_10=kills,
    )
