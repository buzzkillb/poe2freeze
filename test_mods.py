import sys
sys.path.insert(0, r'C:\Users\travanx\Dropbox\projects\poe2\ninja')
from mod_matcher import match_mod
tests = [
    'Monster Effectiveness: +42%',
    'Item Rarity: +46%',
    'Pack Size: +19%',
    'Waystone Drop Chance: +145%',
    'Monster Rarity: +44%',
    'Revives Available: 0',
    'Area has patches of Ignited Ground',
    'Players are periodically Cursed with Enfeeble',
    'Monsters have 21% increased Critical Hit Chance',
    '+1 to Level of all Strength Skill Gems',
    'Gain 41 Mana per enemy killed',
]
for t in tests:
    m = match_mod(t)
    if m:
        ref = m['ref'][:50]
        print(f'  MATCH: {t[:45]:45} -> {m["trade_id"]} (ref: {ref})')
    else:
        print(f'  NO MATCH: {t}')