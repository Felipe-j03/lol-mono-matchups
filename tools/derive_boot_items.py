"""Derive the boot item ids from the Data Dragon item list.

``aggregate.py`` must stay pure and offline, so the set is generated here and
pasted in as a literal. Run this after bumping ``ddragon_version`` in the config
and replace the ``BOOT_ITEM_IDS`` block in ``src/lolmono/aggregate.py`` with the
output:

    python tools/derive_boot_items.py 16.21.1

A boot is any item whose ``tags`` contain "Boots". The 22xxxx and 77xxxx ranges
are alternate game modes (Arena, One for All and friends) whose ids never appear
in a ranked solo queue match payload, so they are excluded: keeping them would
only inflate the set with ids the collector can never see.

Hand-listing these ids is what made the set go stale once already: the nine
hand-written ids held no tier-3 upgrade, so in most Master+ games the boots
comparison saw an empty list on both sides and reported nothing at all.
"""

import json
import sys
import urllib.request

URL = "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/item.json"
ALTERNATE_MODE_RANGES = ((220_000, 230_000), (770_000, 780_000))


def boots(version: str) -> list[tuple[int, str]]:
    with urllib.request.urlopen(URL.format(version=version), timeout=60) as handle:
        items = json.load(handle)["data"]
    found = []
    for key, item in items.items():
        item_id = int(key)
        if "Boots" not in (item.get("tags") or []):
            continue
        if any(low <= item_id < high for low, high in ALTERNATE_MODE_RANGES):
            continue
        found.append((item_id, item.get("name", "")))
    return sorted(found)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <ddragon version>", file=sys.stderr)
        return 2
    version = argv[1]
    found = boots(version)
    print(f"# Boots, derived from the Data Dragon item list of {version}:")
    print("# every item whose tags contain \"Boots\", minus the alternate-mode")
    print("# (22xxxx, 77xxxx) ids. Regenerate with:")
    print(f"#     python tools/derive_boot_items.py {version}")
    print("# Do NOT hand-edit: a missing tier-3 upgrade makes the boots")
    print("# comparison silently see nothing in most Master+ games.")
    print("BOOT_ITEM_IDS = frozenset(")
    print("    {")
    for item_id, name in found:
        print(f"        {item_id},  # {name}")
    print("    }")
    print(")")
    print(f"# {len(found)} ids", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
