# How to use sell_tabs.py — full workflow

## The basic idea

PoE2 already has a "copy item" feature built in. When you **Ctrl+C** an item in-game, it copies the entire item text to your clipboard. Our tool reads that clipboard, identifies tablets, looks up current market prices, and tells you what to list them for.

## Step-by-step

### 1. Open your stash in PoE2
Navigate to the tab with your tablets (Abyss, Breach, Ritual, etc).

### 2. Click on a tablet
Left-click the tablet in your stash to highlight/select it.

### 3. Ctrl+C to copy
This copies the full item text to your Windows clipboard. The text looks like:
```
Rarity: RARE
Precursor Tablet: Overseer
--------
Tower Augmentation
--------
Requires: Level 50
--------
Item Level: 80
--------
{ Tablet Modifier — ... }
{ Tablet Modifier — ... }
--------
Note: <whatever you typed>
```

You don't have to do anything else in-game. The clipboard now has the item.

### 4. Run the tool
Switch to your terminal (don't alt-tab if you have FPS cap issues, just alt-tab once quickly) and run:

```bash
python sell_tabs.py
```

### 5. Read the output
You'll see something like:
```
NAME                                  TYPE       ILVL  CORR  MARKET       SUGGEST
====================================================================
Precursor Tablet: Overseer           Precursor  80    No    215c         204c

Best deal: Precursor Tablet: Overseer (ilvl 80) — list at 204c
```

The `SUGGEST` column is what you should list it for in trade2.

### 6. List it in trade2
- Open trade2 in browser (https://www.pathofexile.com/trade2)
- Go to Sell tab
- Make sure your character is on the right league
- Set your stash tab
- Put a price note like "204c" or "~5d" 
- List it

## Flags for different situations

```bash
# Only show tablets worth listing (skip vendor trash)
python sell_tabs.py --min-price 30

# Only high-ilvl tablets (more valuable)
python sell_tabs.py --ilvl 80

# Undercut by more (sells faster)
python sell_tabs.py --undercut 10

# Copy item + suggested price to clipboard (then paste in trade2)
python sell_tabs.py --copy
```

## Batch mode (multiple items at once)

PoE2 lets you Ctrl+A then Ctrl+C in your stash tab to copy ALL items. Then:

```bash
python sell_tabs.py
```

It parses every item, filters to tablets, and shows a list sorted by value:

```
NAME                                  TYPE       ILVL  CORR  MARKET       SUGGEST
====================================================================
Precursor Tablet: Overseer           Precursor  80    No    215c         204c
Breach Catalyst Fragment              Breach     82    No    89c          84c
Abyssal Echoes of the Fallen          Abyss      83    No    127c         120c
Ritual Vessel: Tribute               Ritual     79    Yes   45c          42c
```

## How it decides what to suggest

1. **Looks up your tablet by name** in poe2scout's live database (~1,272 items)
2. **Gets the current median price** in exalts
3. **Converts to chaos** using current exchange rates
4. **Undercuts by 5%** (configurable) so your listing looks competitive
5. **Recommends divine for high-value** (>=5 divine) or chaos for cheaper

## Tips

- **ilvl matters** — a Precursor Tablet at ilvl 78 is worth way less than the same at ilvl 84. The tool shows ilvl so you can decide.
- **Corrupted = 20% quality loss** in PoE2. The tool flags corruption. You can still list corrupted tablets, just expect less.
- **Mods matter more than base type** — the tool uses the name for lookup, so "Precursor Tablet: Overseer" vs "Precursor Tablet: Dominus" will have different prices based on the implicit mod.
- **You can also check the EXACT mod roll** — paste your tablet's mod line into poe2scout.com to see if it's a high-tier roll.

## Related tool

- `scan_tabs.py` — does the OPPOSITE: searches trade2 for cheap tablets to BUY
- `clipboard pricer` (main app) — shows prices as you Ctrl+C anything

## The full cycle

```
1. Ctrl+C item in stash
2. Run: python sell_tabs.py
3. See suggested price
4. (optional) Run: python sell_tabs.py --copy
5. Paste in trade2 with the note as the price
6. Repeat for next tablet
```
