"""Scan trade2 for tablet deals priced >= 1 divine (~38 chaos).

Usage:
    python scan_tabs.py                    # All tablets, min 1 divine
    python scan_tabs.py --min 50           # Custom min price in chaos
    python scan_tabs.py --type Abyss       # Only Abyss tablets
    python scan_tabs.py --type Breach
    python scan_tabs.py --type Ritual
    python scan_tabs.py --type Precursor
    python scan_tabs.py --top 20           # Top 20 results
    python scan_tabs.py --json             # JSON output
"""
import argparse
import json
import sys
import time
from typing import List, Dict, Any
from urllib.parse import quote

import urllib.request

# trade2 API base URL
TRADE2_BASE = "https://www.pathofexile.com/api/trade2"

# Tablet category (all tablets: abyss, breach, ritual, etc.)
TABLET_CATEGORY = "map.tablet"

# Chaos per divine (updated from poe2scout at startup)
CHAOS_PER_DIVINE = 40  # reasonable default


def fetch_chaos_per_divine(league: str) -> float:
    """Get current chaos per divine rate from poe2scout."""
    try:
        url = f"https://poe2scout.com/api/poe2/Leagues/{quote(league, safe='')}/ReferenceCurrencies"
        req = urllib.request.Request(url, headers={"User-Agent": "mypoeapp/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            for e in json.loads(resp.read()):
                if e.get("ApiId") == "divine":
                    return float(e.get("RelativePrice", CHAOS_PER_DIVINE))
    except Exception:
        pass
    return CHAOS_PER_DIVINE


def search_tablets(
    league: str,
    min_price_chaos: float,
    type_filter: str = None,
    top: int = 50,
) -> List[Dict[str, Any]]:
    """Search trade2 for tablets priced >= min_price_chaos, sorted cheapest first."""
    # Build query
    query = {
        "status": {"option": "online"},
        "type": TABLET_CATEGORY,
        "filters": {
            "trade_filters": {
                "price": {
                    "min": min_price_chaos,
                    "option": "chaos",
                }
            }
        }
    }
    if type_filter:
        # Build name regex for the tablet type
        # e.g. "Abyss.*" matches "Abyssal Coil", "Abyssal Sceptre", etc.
        query["name"] = type_filter

    body = {"query": query, "sort": {"price": "asc"}}

    # Search
    le = quote(league, safe="")
    search_url = f"{TRADE2_BASE}/search/{le}"
    req = urllib.request.Request(
        search_url,
        data=json.dumps(body).encode("utf-8"),
        headers={"User-Agent": "mypoeapp/1.0", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"trade2 search error: {e}", file=sys.stderr)
        return []

    ids = data.get("result", [])[:top]
    if not ids:
        return []

    # Fetch listing details
    fetch_url = f"{TRADE2_BASE}/fetch/{','.join(ids)}?query={data.get('id', '')}"
    req = urllib.request.Request(
        fetch_url,
        headers={"User-Agent": "mypoeapp/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"trade2 fetch error: {e}", file=sys.stderr)
        return []

    results = []
    for entry in data.get("result", []):
        if not entry:
            continue
        item = entry.get("item", {})
        listing = entry.get("listing", {})
        price = listing.get("price", {})
        results.append({
            "name": item.get("name", "?"),
            "base": item.get("baseType", item.get("typeLine", "?")),
            "ilvl": item.get("ilvl"),
            "corrupted": item.get("corrupted", False),
            "price_amount": price.get("amount"),
            "price_currency": price.get("currency"),
            "account": listing.get("account", {}).get("name", "?"),
            "indexed": listing.get("indexed", ""),
            "mods": [m.get("tier") or m.get("name", "") for m in item.get("explicitMods", [])[:6]],
            "id": entry.get("id", ""),
        })
    return results


def format_price(amount, currency):
    if amount is None or currency is None:
        return "?"
    if currency == "chaos":
        return f"{amount:.0f}c"
    if currency == "divine":
        return f"{amount:.1f}d"
    if currency == "exalted":
        return f"{amount:.1f}ex"
    return f"{amount} {currency}"


def format_row(r):
    price = format_price(r["price_amount"], r["price_currency"])
    ilvl = r["ilvl"] or "?"
    corr = "C" if r["corrupted"] else "-"
    name = r["name"][:40] if r["name"] else "?"
    mods = " | ".join(m for m in r["mods"] if m)[:60]
    return f"{price:>10}  L{ilvl:<3} {corr}  {name:<40}  {mods}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="Runes of Aldur")
    ap.add_argument("--min", type=float, default=None,
                    help="Min price in chaos (default: 1 divine in chaos)")
    ap.add_argument("--divine", type=float, default=None,
                    help="Alternative: min price in divine")
    ap.add_argument("--type", choices=["Abyss", "Breach", "Ritual", "Precursor", "Expedition", "Delirium"],
                    help="Filter by tablet name prefix")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    args = ap.parse_args()

    if args.min is not None:
        min_chaos = args.min
    elif args.divine is not None:
        min_chaos = args.divine * fetch_chaos_per_divine(args.league)
    else:
        # Default: 1 divine
        min_chaos = fetch_chaos_per_divine(args.league)

    type_filter = f"^{args.type}" if args.type else None

    results = search_tablets(args.league, min_chaos, type_filter, args.top)

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        print(f"Tablets >= {min_chaos:.0f}c  |  league: {args.league}")
        if args.type:
            print(f"Filter: name starts with '{args.type}'")
        print("=" * 100)
        if not results:
            print("(no results)")
        for r in results:
            print(format_row(r))


if __name__ == "__main__":
    main()
