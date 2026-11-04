"""Derive the boot item ids from the Data Dragon item list.

``aggregate.py`` must stay pure and offline, so the set is generated here and
pasted in as a literal. Run this after bumping ``ddragon_version`` in the config
and replace the ``BOOT_ITEM_IDS`` block in ``src/lolmono/aggregate.py`` with the
output:

    python tools/derive_boot_items.py 16.21.1

An item is a boot when **either** its ``tags`` contain "Boots" **or** its build
tree reaches Boots of Speed (1001) or Slightly Magical Footwear (2422) — and, in
both cases, only when ``maps["11"]`` is true.

The tag alone is not enough, and that is not a detail: 3172 Gunmetal Greaves is
a tier-3 upgrade built straight out of Berserker's Greaves and Riot tags it
``["AttackSpeed", "LifeSteal", "NonbootsMovement"]``, with no "Boots" anywhere.
It is the attack-speed upgrade, so it is where a Jax top main's boots end up, and
Jax top is one of the five configured targets. It is the only item in 16.21.1
that the build tree catches and the tag misses — which is exactly why the rule
must not be "simplified" back to the tag.

``maps["11"]`` is Summoner's Rift, the only map this project collects from
(ranked solo queue, queue 420). It drops two items the tag would otherwise keep,
both inert off the Rift: 1111 Jarvan I's (an event item with the tag and no build
tree) and 3005 Ghostcrawlers. The 22xxxx and 77xxxx ranges are excluded too:
those are alternate-mode ids (Arena, One for All and friends) whose values never
appear in a ranked solo queue match payload.

Hand-listing these ids is what made the set go stale once already: the nine
hand-written ids held no tier-3 upgrade, so in most Master+ games the boots
comparison saw an empty list on both sides and reported nothing at all.
"""

import json
import sys
import urllib.request

URL = "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/item.json"
ALTERNATE_MODE_RANGES = ((220_000, 230_000), (770_000, 780_000))
BOOT_ROOTS = ("1001", "2422")  # Boots of Speed, Slightly Magical Footwear
SUMMONERS_RIFT = "11"


def _builds_from_boots(key: str, items: dict, seen: frozenset[str] = frozenset()) -> bool:
    """True when `key`'s build tree reaches one of BOOT_ROOTS."""
    if key in seen:  # a malformed cycle must not recurse forever
        return False
    seen = seen | {key}
    for parent in items.get(key, {}).get("from") or []:
        if parent in BOOT_ROOTS or _builds_from_boots(parent, items, seen):
            return True
    return False


def boots(version: str) -> list[tuple[int, str, bool]]:
    """(id, name, tagged_as_boots) for every boot on Summoner's Rift."""
    with urllib.request.urlopen(URL.format(version=version), timeout=60) as handle:
        items = json.load(handle)["data"]
    found = []
    for key, item in items.items():
        item_id = int(key)
        if any(low <= item_id < high for low, high in ALTERNATE_MODE_RANGES):
            continue
        tagged = "Boots" in (item.get("tags") or [])
        if not tagged and key not in BOOT_ROOTS and not _builds_from_boots(key, items):
            continue
        # Not `.get(...)` truthiness: an absent map must not pass for false.
        if (item.get("maps") or {}).get(SUMMONERS_RIFT) is not True:
            continue
        found.append((item_id, item.get("name", ""), tagged))
    return sorted(found)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <ddragon version>", file=sys.stderr)
        return 2
    version = argv[1]
    found = boots(version)
    print(f"# Boots, derived from the Data Dragon item list of {version}:")
    print('# every Summoner\'s Rift item (maps["11"]) whose tags contain "Boots" OR')
    print("# whose build tree reaches 1001/2422, minus the alternate-mode")
    print("# (22xxxx, 77xxxx) ids. Regenerate with:")
    print(f"#     python tools/derive_boot_items.py {version}")
    print("# Do NOT hand-edit, and do NOT narrow the rule to the tag: 3172 is a")
    print("# tier-3 upgrade that Riot does not tag as boots at all.")
    print("BOOT_ITEM_IDS = frozenset(")
    print("    {")
    for item_id, name, tagged in found:
        note = "" if tagged else "  (no Boots tag; caught by the build tree)"
        print(f"        {item_id},  # {name}{note}")
    print("    }")
    print(")")
    untagged = [i for i, _, tagged in found if not tagged]
    print(f"# {len(found)} ids; {len(untagged)} from the tree only: {untagged}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
