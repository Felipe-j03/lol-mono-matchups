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


def frame(timestamp: int, events: list | None = None, pframes: dict | None = None) -> dict:
    return {
        "timestamp": timestamp,
        "participantFrames": pframes or {},
        "events": events or [],
    }


def timeline(frames: list[dict]) -> dict:
    return {
        "metadata": {"matchId": "BR1_X", "participants": PARTICIPANTS},
        "info": {"frames": frames},
    }


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


def run(frames: list[dict]):
    """Extract from a minimal timeline; three skill points are always supplied."""
    frames = [frame(0, THREE_SKILLS)] + frames
    return extract_timeline(timeline(frames), "ME", "THEM")


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


# --- the minute-14 guard ----------------------------------------------------

AT_14 = {str(ME): stats(5000, 100, 10), str(THEM): stats(4000, 90, 8)}


def test_frame_exactly_at_minute_14_counts_as_reaching_it():
    row = run([frame(14 * MIN, pframes=AT_14)])
    assert row.gold_at_14 == 5000
    assert row.cs_diff_at_14 == 12


def test_last_frame_just_before_minute_14_is_not_reported_as_minute_14():
    row = run([frame(14 * MIN - 1, pframes=AT_14)])
    assert row.gold_at_14 is None
    assert row.cs_diff_at_14 is None


def test_frame_past_minute_14_is_not_used_for_the_value():
    early = {str(ME): stats(4000, 80, 0), str(THEM): stats(3900, 80, 0)}
    late = {str(ME): stats(9999, 300, 0), str(THEM): stats(1, 1, 0)}
    row = run([frame(13 * MIN, pframes=early), frame(14 * MIN + 500, pframes=late)])
    # Pins the stated rule: greatest timestamp <= 14:00 (here minute 13), gated
    # only on some frame being >= 14:00. A frame at 14:00.5 is never the value.
    assert row.gold_at_14 == 4000
    assert row.cs_diff_at_14 == 0


def test_jungle_creeps_count_toward_cs():
    pframes = {str(ME): stats(0, 100, 20), str(THEM): stats(0, 100, 0)}
    row = run([frame(14 * MIN, pframes=pframes)])
    assert row.cs_diff_at_14 == 20


# --- items ------------------------------------------------------------------


def test_starting_items_bound_is_the_first_minute_inclusive():
    row = run([frame(MIN, [buy(1, 0), buy(2, MIN), buy(3, MIN + 1)])])
    assert row.starting_items == (1, 2)
    assert row.item_order == (1, 2, 3)


def test_other_players_purchases_are_ignored():
    row = run([frame(MIN, [buy(1), buy(9, pid=THEM), buy(8, pid=1)])])
    assert row.starting_items == (1,)
    assert row.item_order == (1,)


def test_sale_removes_the_last_occurrence_of_the_item():
    row = run([frame(MIN, [buy(5), buy(6), buy(5), sell(5)])])
    assert row.item_order == (5, 6)


def test_undo_removes_the_last_occurrence_of_before_id():
    row = run([frame(MIN, [buy(5), buy(5), buy(6), undo(5)])])
    assert row.item_order == (5, 6)


def test_sale_or_undo_of_an_item_not_in_the_order_is_a_no_op():
    row = run([frame(MIN, [buy(5), sell(77), undo(88)])])
    assert row.item_order == (5,)


def test_other_players_sales_and_undos_do_not_touch_the_order():
    row = run([frame(MIN, [buy(5), sell(5, pid=THEM), undo(5, pid=1)])])
    assert row.item_order == (5,)


def test_item_order_stops_after_minute_15():
    frames = [
        frame(14 * MIN, pframes=AT_14),
        frame(15 * MIN, [buy(1, 15 * MIN - 5)]),
        frame(15 * MIN + 1, [buy(2, 15 * MIN + 1)]),
        frame(16 * MIN, [buy(3, 16 * MIN)]),
    ]
    assert run(frames).item_order == (1,)


# --- skills -----------------------------------------------------------------


def test_skill_order_ignores_evolves_and_other_players():
    events = [skill(4, kind="EVOLVE"), skill(2, pid=THEM), skill(1), skill(2), skill(4, kind="EVOLVE"), skill(3), skill(1)]
    row = extract_timeline(timeline([frame(0, events)]), "ME", "THEM")
    assert row.skill_order == (1, 2, 3)


def test_fewer_than_three_skill_points_is_an_error_not_a_padded_tuple():
    with pytest.raises(ValueError):
        extract_timeline(timeline([frame(0, [skill(1), skill(2)])]), "ME", "THEM")


# --- kills and deaths -------------------------------------------------------


def test_minute_10_boundary_is_exclusive():
    events = [
        kill(ME, THEM, 10 * MIN - 1),
        kill(THEM, ME, 10 * MIN - 1),
        kill(ME, THEM, 10 * MIN),
        kill(THEM, ME, 10 * MIN),
    ]
    row = run([frame(10 * MIN, events)])
    assert (row.kills_before_10, row.deaths_before_10) == (1, 1)


def test_assists_and_other_players_kills_do_not_count():
    events = [kill(1, THEM, 1000, assists=(ME,)), kill(1, 2, 2000)]
    row = run([frame(MIN, events)])
    assert (row.kills_before_10, row.deaths_before_10) == (0, 0)
