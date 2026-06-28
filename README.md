# PoE2 Ninja Pricer

A Path of Exile 2 real-time pricing overlay. Two independent systems:

1. **Clipboard pricer** — Ctrl+C any item in PoE2, price pops up near cursor
2. **Ritual overlay** — automatic icon matching detects items in ritual menus, draws prices on every item without any user interaction (94% accuracy, 1272 icons)

No OAuth, no game memory reading, fully GGG-policy compliant.

## Features

### Clipboard Pricer
- Press Ctrl+C on an item → PoE2-styled tooltip with rarity color, mods, listing count
- Supports uniques, rares (mod-based trade2 search), currency, gems, waystones, tablets, maps
- Pricing sources: poe2scout (primary), official trade2 API, poeprices.info (fallback)
- 5-min currency refresh, 2-hour item cache, rate-limit aware

### Ritual Overlay
- Opens automatically when the ritual menu is detected in-game
- Matches item icons against 1272 downloaded unique/currency icons from poe2scout
- Combined template matching + color similarity scoring with size-bucketed filtering
- Draws price labels at each item's center — no hovering, no OCR, no interaction needed
- Re-scans every 2 seconds when the menu changes

### Currency Panel
- Top-left floating panel: 8 trading currencies sorted by value
- Smart conversions: exalts always shown, chaos if >= 1c, divine if >= 1d
- Icons loaded from local cache, refreshes every 5 minutes

## Setup

1. Install Python 3.12+ from https://www.python.org/downloads/
2. Install dependencies: `pip install PyQt5 opencv-python numpy mss pillow`
3. Run `python overlay.py`
4. Map a controller button to Ctrl+C via Steam Input for controller use

## Files

| File | Purpose |
|------|---------|
| `overlay.py` | Main entry point, QTimer-based clipboard polling + ritual watcher |
| `overlay_widget.py` | PoE2-styled price popup (dark gradient, gold border, rarity colors) |
| `ritual_overlay.py` | Ritual icon matcher: 1272 icons, template+color scoring, size-bucketed |
| `currency_panel.py` | Top-left currency rates panel with icons |
| `pricer.py` | Routing engine: dispatches to correct pricer per item type |
| `data_sources.py` | poe2scout / trade2 / poeprices API wrappers with retry/backoff |
| `poe2db_data.py` | Local poe2db lookup for base types and trade category mapping |
| `item_parser.py` | PoE2 clipboard text → structured fields |
| `mod_matcher.py` | Mod text → trade2 stat IDs |
| `cache.py` | SQLite-backed price cache (WAL mode, periodic eviction) |
| `clipboard.py` | Windows clipboard reader |
| `download_unique_icons.py` | Fetches all 1272 item icons from poe2scout CDN |
| `ocr_worker.py` | Subprocess OCR fallback (EasyOCR, avoids PyQt5 DLL conflict) |
| `data/unique_icons/` | 1272 pre-composited item icons + database.json |
| `data/ritual_templates/` | Favours header templates for ritual grid anchor detection |

## Data Sources

- **poe2scout.com** (primary, anonymous) — currency rates, unique prices, ritual items
- **poe2db.tw** data dumps (local) — base type → trade category mapping
- **Official GGG trade2 API** (anonymous) — rare mod-based searches
- **poeprices.info** (fallback) — statistical predictor for rares

### Rate Limiting
- poe2scout: 3 req/s with exponential backoff on 429/5xx
- trade2: 1.5s minimum between searches
- Item cache TTL: 2 hours (currency: 5 min)
- SQLite WAL mode for concurrent reads, periodic expired row eviction

## Ritual Overlay Accuracy

Tested on 14 ritual screenshots at 4K (3840x2160):

| Metric | Value |
|--------|-------|
| Icons in database | 1,272 |
| Total slots tested | 366 |
| Slots matched | 343 |
| Match rate | **94%** |
| Typical scan time | ~4s (12 items) |

The remaining 6% are maps, tablets, and non-unique items not covered by the unique icon database.

## License

MIT. Not affiliated with or endorsed by Grinding Gear Games.
