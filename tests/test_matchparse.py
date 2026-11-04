import copy
import json
from pathlib import Path

import pytest

from lolmono.matchparse import DiscardMatch, extract_match, pair_lanes
from lolmono.rows import MatchRow, RunePage

FIXTURES = Path(__file__).parent / "fixtures"

TALON = 91
EKKO = 245
POSITIONS = {"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"}


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def variant(**info_overrides) -> dict:
    """Fresh copy of the clean match; info-level fields can be overridden."""
    match = copy.deepcopy(load("match_clean.json"))
    match["info"].update(info_overrides)
    return match


def find(match: dict, puuid: str) -> dict:
    return next(p for p in match["info"]["participants"] if p["puuid"] == puuid)


clean = load("match_clean.json")
unpaired = load("match_unpaired.json")


# ---------------------------------------------------------------- pair_lanes


def test_pair_lanes_returns_five_pairs():
    pairs = pair_lanes(clean["info"]["participants"])
    assert set(pairs) == POSITIONS


def test_each_pair_holds_one_participant_from_each_team_in_that_position():
    pairs = pair_lanes(clean["info"]["participants"])
    for position, (a, b) in pairs.items():
        assert a["teamPosition"] == b["teamPosition"] == position
        assert {a["teamId"], b["teamId"]} == {100, 200}


def test_each_pair_is_ordered_by_ascending_team_id():
    pairs = pair_lanes(clean["info"]["participants"])
    for a, b in pairs.values():
        assert a["teamId"] < b["teamId"]


def test_pair_order_does_not_depend_on_participant_order():
    match = variant()
    match["info"]["participants"].reverse()
    pairs = pair_lanes(match["info"]["participants"])
    for a, b in pairs.values():
        assert (a["teamId"], b["teamId"]) == (100, 200)


def test_team_of_six_with_all_five_positions_plus_a_repeat_is_discarded():
    # Eleven participants: team 100 holds all five positions and a second TOP.
    # Every position is present, so only the repeat itself can reveal the problem.
    match = variant()
    extra = copy.deepcopy(find(match, "TOP_100"))
    extra["puuid"] = "TOP2_100"
    match["info"]["participants"].append(extra)
    with pytest.raises(DiscardMatch) as exc:
        pair_lanes(match["info"]["participants"])
    assert exc.value.reason == "unpaired_lanes"


def test_empty_team_position_is_discarded():
    match = variant()
    find(match, "TALON_PLAYER")["teamPosition"] = ""
    with pytest.raises(DiscardMatch) as exc:
        pair_lanes(match["info"]["participants"])
    assert exc.value.reason == "missing_position"


def test_absent_team_position_key_is_discarded():
    match = variant()
    del find(match, "EKKO_PLAYER")["teamPosition"]
    with pytest.raises(DiscardMatch) as exc:
        pair_lanes(match["info"]["participants"])
    assert exc.value.reason == "missing_position"


def test_other_position_fields_never_stand_in_for_team_position():
    # individualPosition, lane and role all say MIDDLE; teamPosition is blank.
    match = variant()
    talon = find(match, "TALON_PLAYER")
    talon["teamPosition"] = ""
    talon["individualPosition"] = "MIDDLE"
    talon["lane"] = "MIDDLE"
    talon["role"] = "SOLO"
    with pytest.raises(DiscardMatch) as exc:
        pair_lanes(match["info"]["participants"])
    assert exc.value.reason == "missing_position"


def test_other_position_fields_never_override_team_position():
    # teamPosition is what counts, even when the other fields disagree with it.
    match = variant()
    for p in match["info"]["participants"]:
        p["individualPosition"] = "TOP"
        p["lane"] = "TOP"
        p["role"] = "SOLO"
    pairs = pair_lanes(match["info"]["participants"])
    assert set(pairs) == POSITIONS


def test_duplicated_position_in_one_team_is_discarded():
    # dois MIDDLE no time 100, nenhum JUNGLE
    with pytest.raises(DiscardMatch) as exc:
        pair_lanes(unpaired["info"]["participants"])
    assert exc.value.reason == "unpaired_lanes"


def test_unknown_position_value_is_discarded_as_unpaired():
    match = variant()
    find(match, "JG_100")["teamPosition"] = "Invalid"
    with pytest.raises(DiscardMatch) as exc:
        pair_lanes(match["info"]["participants"])
    assert exc.value.reason == "unpaired_lanes"


def test_wrong_number_of_participants_is_discarded_as_unpaired():
    participants = clean["info"]["participants"][:-1]
    with pytest.raises(DiscardMatch) as exc:
        pair_lanes(participants)
    assert exc.value.reason == "unpaired_lanes"


def test_ten_participants_on_one_team_is_discarded_as_unpaired():
    match = variant()
    for p in match["info"]["participants"]:
        p["teamId"] = 100
    with pytest.raises(DiscardMatch) as exc:
        pair_lanes(match["info"]["participants"])
    assert exc.value.reason == "unpaired_lanes"


def test_missing_position_outranks_unpaired_lanes():
    # Both defects at once: a blank position AND a duplicated one in the other team.
    match = variant()
    find(match, "TALON_PLAYER")["teamPosition"] = ""
    find(match, "JG_200")["teamPosition"] = "TOP"
    with pytest.raises(DiscardMatch) as exc:
        pair_lanes(match["info"]["participants"])
    assert exc.value.reason == "missing_position"


# -------------------------------------------------------------- extract_match


def test_extract_match_identifies_opponent_in_same_position():
    row = extract_match(clean, puuid="TALON_PLAYER")
    assert row.role == "MIDDLE"
    assert row.opponent_champion_id == EKKO
    assert row.opponent_puuid == "EKKO_PLAYER"
    assert row.win is True


def test_extract_match_returns_complete_row():
    row = extract_match(clean, puuid="TALON_PLAYER")
    assert isinstance(row, MatchRow)
    assert row.match_id == "BR1_2900000001"
    assert row.platform == "br1"
    assert row.puuid == "TALON_PLAYER"
    assert row.champion_id == TALON
    assert row.spells == (4, 14)


def test_opponent_is_found_from_the_other_side_too():
    # Same match seen from Ekko: the opponent must be Talon, and the loss is Ekko's own.
    row = extract_match(clean, puuid="EKKO_PLAYER")
    assert row.champion_id == EKKO
    assert row.role == "MIDDLE"
    assert row.opponent_champion_id == TALON
    assert row.opponent_puuid == "TALON_PLAYER"
    assert row.win is False
    assert row.spells == (4, 12)


def test_opponent_is_never_a_teammate_whatever_the_participant_order():
    # Team 200 listed first; the player is still matched against the other team.
    match = variant()
    match["info"]["participants"].reverse()
    row = extract_match(match, puuid="TALON_PLAYER")
    assert row.opponent_puuid == "EKKO_PLAYER"
    row = extract_match(match, puuid="TOP_200")
    assert row.role == "TOP"
    assert row.opponent_puuid == "TOP_100"
    assert row.opponent_champion_id == 58


def test_opponent_is_chosen_by_position_not_by_slot():
    # Lane opponent of the junglers is the other jungler, not the player at the same index.
    row = extract_match(clean, puuid="JG_100")
    assert row.role == "JUNGLE"
    assert row.opponent_puuid == "JG_200"
    assert row.opponent_champion_id == 60


def test_role_and_opponent_ignore_individual_position_lane_and_role():
    # Every participant carries decoys that differ from the true teamPosition.
    # Only teamPosition may decide the stored role and the lane opponent.
    match = variant()
    decoy = {
        "TOP": ("JUNGLE", "BOTTOM", "SUPPORT"),
        "JUNGLE": ("TOP", "MIDDLE", "NONE"),
        "MIDDLE": ("JUNGLE", "TOP", "SOLO"),  # Talon: really MIDDLE
        "BOTTOM": ("UTILITY", "MIDDLE", "CARRY"),
        "UTILITY": ("BOTTOM", "JUNGLE", "SUPPORT"),
    }
    for p in match["info"]["participants"]:
        individual, lane, role = decoy[p["teamPosition"]]
        p["individualPosition"] = individual
        p["lane"] = lane
        p["role"] = role
    talon = find(match, "TALON_PLAYER")
    assert (talon["individualPosition"], talon["lane"]) == ("JUNGLE", "TOP")

    row = extract_match(match, puuid="TALON_PLAYER")
    assert row.role == "MIDDLE"
    assert row.opponent_puuid == "EKKO_PLAYER"
    assert row.opponent_champion_id == EKKO

    row = extract_match(match, puuid="EKKO_PLAYER")
    assert row.role == "MIDDLE"
    assert row.opponent_puuid == "TALON_PLAYER"
    assert row.opponent_champion_id == TALON


def test_win_comes_from_the_participants_own_field():
    match = variant()
    find(match, "TALON_PLAYER")["win"] = False
    find(match, "EKKO_PLAYER")["win"] = True
    assert extract_match(match, puuid="TALON_PLAYER").win is False
    assert extract_match(match, puuid="EKKO_PLAYER").win is True


def test_items_drop_zeros_and_the_trinket_slot_and_keep_slot_order():
    # item0..item6 = 3142, 0, 6693, 3158, 0, 6694, 3363(trinket)
    row = extract_match(clean, puuid="TALON_PLAYER")
    assert row.items == (3142, 6693, 3158, 6694)


def test_items_are_not_sorted():
    match = variant()
    talon = find(match, "TALON_PLAYER")
    for slot, item in enumerate([6694, 3158, 0, 6693, 0, 3142, 3363]):
        talon[f"item{slot}"] = item
    row = extract_match(match, puuid="TALON_PLAYER")
    assert row.items == (6694, 3158, 6693, 3142)


def test_player_with_only_a_trinket_has_no_items():
    match = variant()
    talon = find(match, "TALON_PLAYER")
    for slot in range(6):
        talon[f"item{slot}"] = 0
    talon["item6"] = 3340
    assert extract_match(match, puuid="TALON_PLAYER").items == ()


def test_extract_match_keeps_full_rune_page():
    row = extract_match(clean, puuid="TALON_PLAYER")
    assert row.runes.keystone == 8112
    assert len(row.runes.primary_perks) == 4
    assert len(row.runes.shards) == 3


def test_rune_page_maps_every_field_to_the_right_source():
    row = extract_match(clean, puuid="TALON_PLAYER")
    assert row.runes == RunePage(
        keystone=8112,
        primary_style=8100,
        primary_perks=(8112, 8126, 8138, 8135),
        secondary_style=8200,
        secondary_perks=(8226, 8210),
        shards=(5005, 5008, 5001),  # (offense, flex, defense)
    )


def test_rune_page_of_another_participant_uses_its_own_styles():
    row = extract_match(clean, puuid="EKKO_PLAYER")
    assert row.runes.primary_style == 8200
    assert row.runes.keystone == 8229
    assert row.runes.secondary_style == 8300
    assert row.runes.secondary_perks == (8304, 8347)


# ------------------------------------------------------- extract_match discards


def test_non_ranked_solo_queue_is_discarded():
    aram = variant(queueId=450)
    with pytest.raises(DiscardMatch) as exc:
        extract_match(aram, puuid="TALON_PLAYER")
    assert exc.value.reason == "wrong_queue"


def test_ranked_flex_queue_is_discarded():
    flex = variant(queueId=440)
    with pytest.raises(DiscardMatch) as exc:
        extract_match(flex, puuid="TALON_PLAYER")
    assert exc.value.reason == "wrong_queue"


def test_puuid_not_in_match_is_discarded():
    with pytest.raises(DiscardMatch) as exc:
        extract_match(clean, puuid="STRANGER")
    assert exc.value.reason == "puuid_absent"


def test_blank_position_in_match_is_discarded_by_extract_match():
    match = variant()
    find(match, "BOT_200")["teamPosition"] = ""
    with pytest.raises(DiscardMatch) as exc:
        extract_match(match, puuid="TALON_PLAYER")
    assert exc.value.reason == "missing_position"


def test_unpaired_match_is_discarded_by_extract_match():
    with pytest.raises(DiscardMatch) as exc:
        extract_match(unpaired, puuid="TALON_PLAYER")
    assert exc.value.reason == "unpaired_lanes"


def test_blank_position_of_a_bystander_still_discards_the_players_match():
    # The player's own position is fine; a participant elsewhere is blank. Lanes are
    # ambiguous, so the match goes.
    match = variant()
    find(match, "SUP_100")["teamPosition"] = ""
    with pytest.raises(DiscardMatch) as exc:
        extract_match(match, puuid="EKKO_PLAYER")
    assert exc.value.reason == "missing_position"


def test_wrong_queue_outranks_every_other_defect():
    match = variant(queueId=450)
    find(match, "TALON_PLAYER")["teamPosition"] = ""
    find(match, "JG_100")["teamPosition"] = "MIDDLE"
    with pytest.raises(DiscardMatch) as exc:
        extract_match(match, puuid="STRANGER")
    assert exc.value.reason == "wrong_queue"


def test_puuid_absent_outranks_missing_position():
    match = variant()
    find(match, "TOP_100")["teamPosition"] = ""
    with pytest.raises(DiscardMatch) as exc:
        extract_match(match, puuid="STRANGER")
    assert exc.value.reason == "puuid_absent"


def test_puuid_absent_outranks_unpaired_lanes():
    with pytest.raises(DiscardMatch) as exc:
        extract_match(unpaired, puuid="STRANGER")
    assert exc.value.reason == "puuid_absent"


def test_missing_position_outranks_unpaired_lanes_in_extract_match():
    match = variant()
    find(match, "TALON_PLAYER")["teamPosition"] = ""
    find(match, "JG_200")["teamPosition"] = "TOP"
    with pytest.raises(DiscardMatch) as exc:
        extract_match(match, puuid="TALON_PLAYER")
    assert exc.value.reason == "missing_position"


def test_payload_without_info_raises_key_error_not_discard():
    # Deliberate boundary: malformed payloads are not one of the four discard
    # reasons. The caller (Task 9) wraps the call and classifies them.
    with pytest.raises(KeyError):
        extract_match({"metadata": clean["metadata"]}, puuid="TALON_PLAYER")


def test_participant_without_perks_raises_key_error_not_discard():
    match = variant()
    del find(match, "TALON_PLAYER")["perks"]
    with pytest.raises(KeyError):
        extract_match(match, puuid="TALON_PLAYER")


def test_discard_match_is_an_exception_with_a_reason_attribute():
    err = DiscardMatch("wrong_queue")
    assert isinstance(err, Exception)
    assert err.reason == "wrong_queue"
