# PoE2 Ninja Pricer

A real-time Path of Exile 2 pricing overlay. Two independent systems share a single rate-limited API client:

1. **Clipboard pricer** — Ctrl+C any item, price pops up near cursor with rarity-styled formatting
2. **Ritual overlay** — automatic icon matching detects items in ritual menus, draws prices at each item's center with zero user interaction

Fully GGG-policy compliant — no game memory reading, no OAuth required.

## Quick Start

```bash
pip install PyQt5 opencv-python numpy mss pillow
python overlay.py
```

Map a controller button to Ctrl+C via Steam Input for controller use.

## Clipboard Pricer

Press Ctrl+C on any item in PoE2 and a tooltip appears next to your cursor showing:

- Item name, base type, rarity (color-coded)
- Price in exalts with chaos/divine equivalents
- Listing count, data freshness, source
- Top 10 trade listings with prices and time ago

Supports: uniques, rares (mod-based trade2 search), currency, gems, waystones, tablets, maps, divination cards. Falls back from trade2 → poe2scout → poeprices.info automatically.

## Ritual Overlay

When the ritual menu opens in-game, the overlay automatically:

1. Detects the grid via FAVOURS header anchor (resolution-scaled)
2. Finds all occupied item slots
3. Matches each item's rendered icon against 1,272 pre-downloaded poe2scout icons
4. Draws a price label at each item's center

**No hovering, OCR, or user interaction needed.** Matching runs in a background thread so the UI stays responsive. Re-scans when the menu changes.

### Matching Pipeline

| Stage | Technique |
|-------|-----------|
| Icon loading | Alpha-composited over dark background, pre-resized to 95×95 |
| Template correlation | Batch matmul via precomputed centered vectors + standard deviations |
| Color similarity | Precomputed icon opaque-pixel colors vs slot item color |
| Size filtering | Aspect ratio (±1.5) and area ratio (0.3–3.0) bucketing |
| Early exit | Skip color calc when TM score can't beat threshold |
| Score threshold | 0.40 primary, 0.35 fallback with >0.03 margin to 2nd place |

### Accuracy

Tested on 14 ritual screenshots at 4K (3840×2160):

| Metric | Value |
|--------|-------|
| Icons in database | 1,272 |
| Total slots tested | 366 |
| Slots matched | 343 |
| **Match rate** | **94%** |
| Typical scan time | ~4s (12 items) |

The remaining 6% are maps, tablets, and non-unique items not covered by the icon database.

## Currency Panel

Top-left floating panel with 8 trading currencies sorted by current value. Shows exalts always, chaos equivalents when ≥1c, and divine equivalents when ≥1d. Icons cached locally, refreshes every 5 minutes.

## Architecture

```
overlay.py ──┬── CurrencyRatesPanel ────┐
             │                           ├── Poe2ScoutSource (shared, 3 req/s, retry/backoff)
             ├── Pricer ── DataSourceRegistry ──┤
             │                           │      ├── OfficialTradeSource (1 req/s)
             └── RitualDetector ─────────┘      └── PoePricesSource (fallback)
                    │
                    ├── 1,272 icon templates (pre-resized, batch matrix)
                    └── RitualWatcher (background thread matching)
```

A single `Poe2ScoutSource` instance is shared across the currency panel, clipboard pricer, and ritual detector — one rate limiter, one set of caches. Warmup threads pre-fetch all currency and unique prices at startup. Lookups use O(1) indexes built from the cached bulk data.

## Data Sources

| Source | Purpose | Rate Limit |
|--------|---------|------------|
| [poe2scout.com](https://poe2scout.com) | Currency rates, unique/ritual prices, icon CDN | 3 req/s, exponential backoff on 429/5xx |
| [pathofexile.com/trade2](https://pathofexile.com/trade2) | Rare mod-based searches | 1 req/s, 1.5s search spacing |
| [poeprices.info](https://poeprices.info) | Statistical fallback for rares | 1 req/s |
| [poe2db.tw](https://poe2db.tw) | Local JSON dumps for base type mapping | Offline |

Cache TTLs: currency 5 min, items 2 hours. SQLite with WAL mode, shared connection, 7-day request log eviction, expired price eviction on startup.

## Files

| File | Purpose |
|------|---------|
| `overlay.py` | Main entry — clipboard polling (10Hz), ritual watcher startup, shared scout wiring |
| `ritual_overlay.py` | Icon matcher: 1,272 templates, batch matmul, size-bucketed, background thread |
| `overlay_widget.py` | PoE2-styled price popup (dark gradient, gold border, rarity colors) |
| `currency_panel.py` | Currency rates panel with shared scout, auto-sorted by value |
| `pricer.py` | Routing engine per item type + trade2 search/result handling |
| `data_sources.py` | API wrappers with retry/backoff, rate limiting, bulk index builders |
| `cache.py` | SQLite cache — WAL mode, shared connection, auto-eviction |
| `poe2db_data.py` | Local data loader — base types, item classes, currency IDs |
| `item_parser.py` | Clipboard text → structured item fields |
| `mod_matcher.py` | Item mod text → trade2 stat ID translation |
| `clipboard.py` | Win32 clipboard reader (module-level FFI setup) |
| `download_unique_icons.py` | One-time: fetches all 1,272 icons + builds database.json |
| `data/unique_icons/` | Pre-composited 95×95 PNGs + database.json |
| `data/ritual_templates/` | FAVOURS header + offer button templates for grid detection |
| `data/poe2db/` | Local JSON: base types, item classes, currency items, skill gems |

## License

MIT. Not affiliated with or endorsed by Grinding Gear Games.
