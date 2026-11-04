import json
from pathlib import Path

import pytest

from lolmono.timelineparse import extract_timeline

FIXTURES = Path(__file__).parent / "fixtures"
MIN = 60_000

# "ME" is participant 3 and "THEM" is participant 8: neither is first, so a
# parser that assumed pid 1 or the list order would read the wrong frames.
PARTICIPANTS = ["P1", "P2", "ME", "P4", "P5", "P6", "P7", "THEM", "P9", "P10"]
ME, THEM = 3, 8


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def stats(gold: int, cs: int = 0, jungle: int = 0) -> dict:
    return {"totalGold": gold, "minionsKilled": cs, "jungleMinionsKilled": jungle}


def buy(item: int, ts: int = 0, pid: int = ME) -> dict:
    return {"type": "ITEM_PURCHASED", "timestamp": ts, "participantId": pid, "itemId": item}


def sell(item: int, ts: int = 1, pid: int = ME) -> dict:
    return {"type": "ITEM_SOLD", "timestamp": ts, "participantId": pid, "itemId": item}


def undo(before: int, ts: int = 1, pid: int = ME) -> dict:
    return {"type": "ITEM_UNDO", "timestamp": ts, "participantId": pid, "beforeId": before, "afterId": 0}


def skill(slot: int, ts: int = 1, pid: int = ME, kind: str = "NORMAL") -> dict:
    return {"type": "SKILL_LEVEL_UP", "timestamp": ts, "participantId": pid, "skillSlot": slot, "levelUpType": kind}


def kill(killer: int, victim: int, ts: int, assists: tuple[int, ...] = ()) -> dict:
    return {
        "type": "CHAMPION_KILL",
        "timestamp": ts,
        "killerId": killer,
        "victimId": victim,
        "assistingParticipantIds": list(assists),
    }


THREE_SKILLS = [skill(1), skill(3), skill(1)]


def series(count: int, events: dict[int, list] | None = None, interval: int = MIN, drift: int = 0) -> dict:
    """A timeline of `count` frames, one per `interval` ms from index 0.

    Frame i carries ME gold 1000*i, ME cs 10*i + i jungle, THEM cs 8*i, so every
    frame is distinguishable: gold at index 14 is 14000, cs diff 3*14 = 42.
    `drift` adds i*drift ms to frame i's timestamp, as Riot's frames sit a few
    ms above the minute mark and the error accumulates. `events` maps a frame
    index to the events inside that frame; three skill points are always added.
    """
    by_index: dict[int, list] = {0: list(THREE_SKILLS)}
    for index, evs in (events or {}).items():
        by_index.setdefault(index, []).extend(evs)
    frames = [
        {
            "timestamp": i * interval + i * drift,
            "participantFrames": {
                str(ME): stats(1000 * i, 10 * i, i),
                str(THEM): stats(900 * i, 8 * i, 0),
            },
            "events": by_index.get(i, []),
        }
        for i in range(max(count, max(by_index) + 1))
    ]
    return timeline(frames, interval)


def timeline(frames: list[dict], interval: int | None = MIN) -> dict:
    info: dict = {"frames": frames}
    if interval is not None:
        info["frameInterval"] = interval
    return {"metadata": {"matchId": "BR1_X", "participants": PARTICIPANTS}, "info": info}


def run(count: int = 1, events: dict[int, list] | None = None):
    return extract_timeline(series(count, events), "ME", "THEM")


# --- the brief's tests, against the fixtures -------------------------------


def test_extracts_gold_and_cs_difference_at_minute_14():
    row = extract_timeline(load("timeline_full.json"), "ME", "THEM")
    assert row.gold_at_14 == 5200
    assert row.cs_diff_at_14 == 12


def test_extracts_starting_items_from_first_purchases():
    row = extract_timeline(load("timeline_full.json"), "ME", "THEM")
    assert row.starting_items == (1055, 2003, 2003)


def test_item_order_lists_purchases_in_sequence_ignoring_sales():
    row = extract_timeline(load("timeline_full.json"), "ME", "THEM")
    assert row.item_order == (1055, 3134, 6692)


def test_skill_order_is_first_three_points():
    row = extract_timeline(load("timeline_full.json"), "ME", "THEM")
    assert row.skill_order == (1, 3, 1)


def test_counts_deaths_and_kills_before_minute_10():
    row = extract_timeline(load("timeline_full.json"), "ME", "THEM")
    assert row.deaths_before_10 == 2
    assert row.kills_before_10 == 1


def test_match_ending_before_minute_14_has_no_gold_or_cs():
    row = extract_timeline(load("timeline_remake.json"), "ME", "THEM")
    assert row.gold_at_14 is None
    assert row.cs_diff_at_14 is None
    assert row.deaths_before_10 == 0  # os outros campos seguem preenchidos
    assert row.kills_before_10 == 0
    assert row.starting_items == (1055, 2003)
    assert row.item_order == (1055, 2003)
    assert row.skill_order == (1, 3, 1)


def test_row_identifies_match_and_player():
    row = extract_timeline(load("timeline_full.json"), "ME", "THEM")
    assert row.match_id == "BR1_1001"
    assert row.puuid == "ME"


# --- participant resolution -------------------------------------------------


def test_swapping_roles_flips_the_sign_and_reads_the_other_frame():
    row = extract_timeline(load("timeline_full.json"), "THEM", "ME")
    assert row.gold_at_14 == 4900
    assert row.cs_diff_at_14 == -12


# --- the minute-14 frame is chosen by index ---------------------------------


def test_frame_index_14_is_the_minute_14_snapshot():
    row = run(count=15)
    assert row.gold_at_14 == 14_000
    assert row.cs_diff_at_14 == 42  # (140 + 14) - 112: jungle counted, ME minus THEM


def test_timeline_one_frame_short_of_minute_14_has_no_snapshot():
    row = run(count=14)  # indices 0..13: the match ended during minute 13
    assert row.gold_at_14 is None
    assert row.cs_diff_at_14 is None


def test_truncated_final_frame_at_index_14_is_not_a_minute_14_frame():
    # The game ended at 13:40: frames 0..13 sit on minute marks and Riot's extra
    # end-of-game frame lands at index 14 with a timestamp below 14:00.
    timeline_json = series(14)
    last = dict(timeline_json["info"]["frames"][13])
    last["timestamp"] = 820_000
    last["events"] = []
    timeline_json["info"]["frames"].append(last)
    assert len(timeline_json["info"]["frames"]) == 15
    row = extract_timeline(timeline_json, "ME", "THEM")
    assert row.gold_at_14 is None
    assert row.cs_diff_at_14 is None
    assert row.skill_order == (1, 3, 1)  # everything else is still populated


def test_unknown_tracked_puuid_raises():
    with pytest.raises(ValueError):
        extract_timeline(series(1), "NOBODY", "THEM")


def test_unknown_opponent_puuid_raises():
    with pytest.raises(ValueError):
        extract_timeline(series(1), "ME", "NOBODY")


def test_jittered_timestamps_still_select_the_minute_14_frame():
    # Frames sit above the minute mark and the error accumulates: index 14 is at
    # 840_168 ms, past the 14:00 cutoff. A "greatest timestamp <= 14:00" rule
    # would take index 13 (13_000 gold) here; the index rule takes index 14.
    timeline_json = series(16, drift=12)
    frames = timeline_json["info"]["frames"]
    assert frames[13]["timestamp"] < 14 * MIN < frames[14]["timestamp"]
    row = extract_timeline(timeline_json, "ME", "THEM")
    assert row.gold_at_14 == 14_000
    assert row.cs_diff_at_14 == 42


def test_snapshot_index_follows_the_frame_interval():
    row = extract_timeline(series(29, interval=30_000, drift=7), "ME", "THEM")
    assert row.gold_at_14 == 28_000  # 14 min / 30 s = index 28
    short = extract_timeline(series(28, interval=30_000, drift=7), "ME", "THEM")
    assert short.gold_at_14 is None


def test_missing_frame_interval_defaults_to_one_minute():
    timeline_json = series(15)
    del timeline_json["info"]["frameInterval"]
    assert extract_timeline(timeline_json, "ME", "THEM").gold_at_14 == 14_000


# --- items ------------------------------------------------------------------


def test_starting_items_bound_is_the_first_minute_inclusive():
    row = run(events={1: [buy(1, 0), buy(2, MIN), buy(3, MIN + 1)]})
    assert row.starting_items == (1, 2)
    assert row.item_order == (1, 2, 3)


def test_other_players_purchases_are_ignored():
    row = run(events={1: [buy(1), buy(9, pid=THEM), buy(8, pid=1)]})
    assert row.starting_items == (1,)
    assert row.item_order == (1,)


def test_sale_removes_the_last_occurrence_of_the_item():
    row = run(events={1: [buy(5), buy(6), buy(5), sell(5)]})
    assert row.item_order == (5, 6)


def test_undo_removes_the_last_occurrence_of_before_id():
    row = run(events={1: [buy(5), buy(5), buy(6), undo(5)]})
    assert row.item_order == (5, 6)


def test_sale_or_undo_of_an_item_not_in_the_order_is_a_no_op():
    row = run(events={1: [buy(5), sell(77), undo(88)]})
    assert row.item_order == (5,)
    assert row.starting_items == (5,)


def test_other_players_sales_and_undos_do_not_touch_the_order():
    row = run(events={1: [buy(5), sell(5, pid=THEM), undo(5, pid=1)]})
    assert row.item_order == (5,)
    assert row.starting_items == (5,)


def test_undoing_a_starting_purchase_removes_it_from_both_lists():
    row = run(events={1: [buy(1055), buy(2003), undo(2003, ts=5_000)]})
    assert row.starting_items == (1055,)
    assert row.item_order == (1055,)


def test_selling_a_starting_item_in_the_first_minute_removes_it_from_both_lists():
    row = run(events={1: [buy(1055), buy(2003), sell(2003, ts=30_000)]})
    assert row.starting_items == (1055,)
    assert row.item_order == (1055,)


def test_selling_a_starting_item_later_keeps_it_in_starting_items():
    row = run(events={1: [buy(1055), buy(2003)], 5: [sell(2003, ts=5 * MIN)]})
    assert row.starting_items == (1055, 2003)
    assert row.item_order == (1055,)


def test_item_order_includes_the_minute_15_frame_and_stops_there():
    row = run(count=17, events={15: [buy(1, 15 * MIN - 5)], 16: [buy(2, 15 * MIN + 5)]})
    assert row.item_order == (1,)


def test_item_order_reads_jittered_frame_15():
    # Same cut-off under drift: frame 15 starts at 900_180, past 15:00, and its
    # minute 14-15 events must still be read.
    timeline_json = series(17, events={15: [buy(1, 15 * MIN - 5)], 16: [buy(2)]}, drift=12)
    assert extract_timeline(timeline_json, "ME", "THEM").item_order == (1,)


# --- skills -----------------------------------------------------------------


def test_skill_order_ignores_evolves_and_other_players():
    events = [skill(4, kind="EVOLVE"), skill(2, pid=THEM), skill(1), skill(2), skill(4, kind="EVOLVE"), skill(3), skill(1)]
    row = extract_timeline(timeline([{"timestamp": 0, "participantFrames": {}, "events": events}]), "ME", "THEM")
    assert row.skill_order == (1, 2, 3)


def test_fewer_than_three_skill_points_gives_none_not_a_padded_tuple():
    events = [skill(1), skill(2), skill(4, kind="EVOLVE"), skill(3, pid=THEM)]
    row = extract_timeline(timeline([{"timestamp": 0, "participantFrames": {}, "events": events}]), "ME", "THEM")
    assert row.skill_order is None
    assert row.item_order == ()  # the rest of the row is still produced


# --- kills and deaths -------------------------------------------------------


def test_minute_10_boundary_is_exclusive():
    events = [
        kill(ME, THEM, 10 * MIN - 1),
        kill(THEM, ME, 10 * MIN - 1),
        kill(ME, THEM, 10 * MIN),
        kill(THEM, ME, 10 * MIN),
    ]
    row = run(events={10: events})
    assert (row.kills_before_10, row.deaths_before_10) == (1, 1)


def test_assists_and_other_players_kills_do_not_count():
    events = [kill(1, THEM, 1000, assists=(ME,)), kill(1, 2, 2000)]
    row = run(events={1: events})
    assert (row.kills_before_10, row.deaths_before_10) == (0, 0)


# --- a frame interval that cannot be used falls back to the default ---------


@pytest.mark.parametrize("bad", [0, -60_000, "60000", 1.5, True])
def test_a_frame_interval_that_cannot_be_used_falls_back_to_the_default(bad):
    # Zero would be a ZeroDivisionError and, under the caller's broad catch,
    # parse_error on every payload: a systematic abort with a confusing cause.
    # A string or a float would be a TypeError in the same place. The default
    # (one frame per minute) is the interval of every timeline ever seen.
    payload = series(16)
    payload["info"]["frameInterval"] = bad
    row = extract_timeline(payload, "ME", "THEM")
    assert row == run(16)


def test_a_usable_frame_interval_is_still_honoured():
    # The clamp must not flatten a real non-default interval: at 30s a frame,
    # minute 14 is index 28, not index 14.
    half = series(32, interval=30_000)
    row = extract_timeline(half, "ME", "THEM")
    assert row.gold_at_14 == 1000 * 28
