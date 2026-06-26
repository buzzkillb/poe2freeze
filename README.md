# PoE2 Ninja Pricer

A controller-friendly Path of Exile 2 price checker. Polls the clipboard, prices any item that was Ctrl+C'd in-game, and shows the result in a PoE2-styled tooltip near your cursor. Also includes a live currency exchange rates panel in the top-left corner.

## Features

- **Press Ctrl+C on an item in PoE2** → price popup appears next to cursor (with rarity color, mods, listing count)
- **Top-left currency panel** with 8 main trading currencies (Perfect Exalted, Perfect Chaos, Divine, Annul, Exalted, Chaos, Vaal, Alchemy), auto-sorted by current value, smart conversions shown (ex always, chaos if ≥1c, divine if ≥1d)
- **Top-right status window** with Test button and last-priced item info
- All data sources: poe2scout (primary), poe2db (base types), official trade2 (rare mod matching), poeprices.info (fallback)
- 5-min currency refresh, 2-hour item cache, rate-limit aware
- No OAuth, no game memory reading, fully GGG-policy compliant

## Setup

1. **Install Python 3.12+** from https://www.python.org/downloads/
2. **Run `start.bat`** (or `bash start.sh` on WSL):
   - First run: installs dependencies, warms cache (~30s)
   - Subsequent runs: starts overlay + auto-refresher
3. **Map a controller button to Ctrl+C via Steam Input**:
   - In Steam → Library → right-click PoE2 → Properties → Controller → Edit Layout
   - Pick any button (back paddle, LB, etc) → map to keyboard `Ctrl+C`
   - Single press copies hovered item + triggers price check

## Files

- `overlay.py` — main entry point, pynput + Qt polling
- `overlay_widget.py` — PoE2-styled price popup (dark gradient, gold border, rarity colors)
- `currency_panel.py` — top-left currency rates with icons
- `pricer.py` — routing engine: dispatches to correct pricer per item type
- `data_sources.py` — poe2scout / trade2 / poeprices API wrappers
- `poe2db_data.py` — local poe2db lookup for base types
- `item_parser.py` — PoE2 clipboard text → structured fields
- `mod_matcher.py` — mod text → trade2 stat IDs
- `cache.py` — SQLite-backed price cache
- `clipboard.py` — Windows clipboard reader
- `data/` — bundled data: `items.ndjson` (EE2 mod translations), `stats.ndjson` (poe2scout cache)
- `start.bat`, `stop.bat`, `reset_cache.bat` — Windows launchers

## Data Sources

- **poe2scout.com** (primary, anonymous) — currency rates, unique prices, full currency listings
- **poe2db.tw** data dumps (local) — base type → trade category mapping
- **Official GGG trade2 API** (anonymous) — rare mod-based searches
- **poeprices.info** (fallback) — statistical predictor for rares when trade2 returns no data

All requests respect rate limits:
- poe2scout: 1.5s spacing between search calls
- trade2: 1.5s minimum between searches, 1 req/sec rate-limited
- Item cache TTL: 2 hours (currency: 5 min)
- Currency rates: refresh every 5 minutes

## License

MIT. Not affiliated with or endorsed by Grinding Gear Games.

Data sources:
- poe2scout.com (currency/unique prices)
- pathofexile.com/trade (rare mod search)
- poe2db.tw (base type data)
- Local: GitHub: LocalIdentity/poe2-data (poe2scout data dumps)
