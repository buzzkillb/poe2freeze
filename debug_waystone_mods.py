"""Test exactly what mods the waystone parser extracts from a real waystone text."""
import sys
sys.path.insert(0, r'C:\Users\travanx\Dropbox\projects\poe2\ninja')
from pricer import _extract_waystone_mods, _build_waystone_query, _extract_tier
import json

# Simulate a T15 corrupted waystone with the user's mods
# (similar to what the user Ctrl+C'd from PoE2)
text = """Item Class: Waystones
Rarity: Rare
Dark Crosscut
Waystone (Tier 15)
--------
Item Rarity: +46% (augmented)
Pack Size: +19% (augmented)
Monster Effectiveness: +44% (augmented)
Waystone Drop Chance: +145% (augmented)
--------
Item Level: 80
--------
Area has patches of Ignited Ground
Players are periodically Cursed with Enfeeble
-8% maximum Player Resistances
Monsters have 229% increased Critical Hit Chance
Monsters have +21% Critical Damage Bonus
Monsters deal 18% of Damage as Extra Chaos
Monsters have 97% increased Stun Buildup
Monster Damage Penetrates 13% Elemental Resistances
Players have 38% less Recovery Rate of Life and Energy Shield
--------
Corrupted"""

# Also try with the labels actually in the text
print("Raw lines:")
lines = text.split('\n')
for line in lines:
    if line.strip():
        print(f"  {line.strip()[:80]}")

print()
print("Extracted mods:")
mods = _extract_waystone_mods({"raw_lines": lines})
print(json.dumps(mods, indent=2))

print()
print("Query that would be sent to trade2:")
query = _build_waystone_query("Dark Crosscut", 15, mods)
print(json.dumps(query, indent=2))