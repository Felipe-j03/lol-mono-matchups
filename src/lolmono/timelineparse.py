"""Reduce a raw Riot match timeline to a TimelineRow.

Timelines are the heaviest payload in the project and the caller discards the
raw JSON right after this runs, so anything not extracted here is gone. Only
frames up to minute 15 are walked; later frames are never looked into.
"""

from lolmono.rows import TimelineRow

MINUTE_MS = 60_000
DEFAULT_FRAME_INTERVAL_MS = MINUTE_MS
SNAPSHOT_MS = 14 * MINUTE_MS  # the moment the matchup comparison is made at
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

    The minute-14 frame is chosen by index, never by timestamp: frames come one
    per `info.frameInterval` ms from index 0 = time 0, and their timestamps sit
    slightly above the minute mark, so a timestamp cutoff would pick minute 13.
    `gold_at_14` and `cs_diff_at_14` come from `frames[14 * 60_000 // interval]`,
    and are None when the timeline has no such frame, or when that frame's
    timestamp is below 14:00 (the match ended before minute 14 and the frame
    is Riot's truncated end-of-game frame; it must not be passed off as 14).

    Frames are walked up to and including the one after that (minute 15), so
    `item_order` covers the first 15 minutes only. It is NOT the full build
    path: the final build comes from the match payload (see matchparse). Sales
    and undos remove the last occurrence of the item, from `item_order` and,
    when they happen inside the first minute, from `starting_items` too; an
    unknown item is ignored.

    `skill_order` is None when the player has fewer than three NORMAL
    level-ups (a short game); it is never padded.

    Raises ValueError if either puuid is not in metadata.participants.
    """
    pid = _participant_id(timeline_json, puuid)
    opp_pid = _participant_id(timeline_json, opponent_puuid)

    info = timeline_json["info"]
    frames = info["frames"]
    interval = info.get("frameInterval", DEFAULT_FRAME_INTERVAL_MS)
    snapshot_idx = SNAPSHOT_MS // interval

    starting_items: list[int] = []
    item_order: list[int] = []
    skill_order: list[int] = []
    kills = deaths = 0

    for frame in frames[: snapshot_idx + 2]:
        for event in frame["events"]:
            kind = event["type"]
            if kind == "ITEM_PURCHASED":
                if event["participantId"] == pid:
                    item_order.append(event["itemId"])
                    if event["timestamp"] <= STARTING_ITEMS_MS:
                        starting_items.append(event["itemId"])
            elif kind in ("ITEM_SOLD", "ITEM_UNDO"):
                if event["participantId"] == pid:
                    gone = event["itemId"] if kind == "ITEM_SOLD" else event["beforeId"]
                    _remove_last(item_order, gone)
                    if event["timestamp"] <= STARTING_ITEMS_MS:
                        _remove_last(starting_items, gone)
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

    gold_at_14 = cs_diff_at_14 = None
    # The timestamp floor rejects Riot's extra end-of-game frame: a game that
    # ended at 13:40 has that frame at index 14, but it is not a minute-14 frame.
    if len(frames) > snapshot_idx and frames[snapshot_idx]["timestamp"] >= SNAPSHOT_MS:
        stats = frames[snapshot_idx]["participantFrames"]
        mine = stats[str(pid)]
        theirs = stats[str(opp_pid)]
        gold_at_14 = mine["totalGold"]
        cs_diff_at_14 = _creep_score(mine) - _creep_score(theirs)

    return TimelineRow(
        match_id=timeline_json["metadata"]["matchId"],
        puuid=puuid,
        gold_at_14=gold_at_14,
        cs_diff_at_14=cs_diff_at_14,
        starting_items=tuple(starting_items),
        item_order=tuple(item_order),
        skill_order=(
            (skill_order[0], skill_order[1], skill_order[2])
            if len(skill_order) == SKILL_POINTS
            else None
        ),
        deaths_before_10=deaths,
        kills_before_10=kills,
    )
