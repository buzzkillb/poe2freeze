"""Identify tablets in your clipboard, check prices, suggest list values.

Usage:
    python sell_tabs.py                    # Read clipboard, analyze all tablets
    python sell_tabs.py --ilvl 80         # Filter to ilvl >= 80
    python sell_tabs.py --min-price 50     # Only show worth > 50c
    python sell_tabs.py --copy             # Copy best listing to clipboard
    python sell_tabs.py --league Runes of Aldur
"""
import argparse
import json
import re
import sys
import urllib.request
from typing import Optional

import clipboard  # our own module


# PoE2 item parsing: extract base type and item level
BASE_TYPE_RE = re.compile(r"Rarity:.*?\n(.+?)\n--------", re.DOTALL)
ITEM_LEVEL_RE = re.compile(r"Item Level: (\d+)")


def parse_tablet_text(text: str) -> Optional[dict]:
    """Parse PoE2 clipboard text to extract tablet info."""
    if "Tower Augmentation" not in text and "Tablet" not in text:
        return None

    name_m = re.search(r"Rarity: \w+\n(.+)", text)
    if not name_m:
        return None
    name = name_m.group(1).strip()

    base_m = re.search(r"--------\n(.+?)\n", text)
    if not base_m:
        return None
    base = base_m.group(1).strip()

    ilvl_m = ITEM_LEVEL_RE.search(text)
    ilvl = int(ilvl_m.group(1)) if ilvl_m else None

    # Item class
    is_tablet = "Tower Augmentation" in text or "Tablet" in base
    if not is_tablet:
        return None

    # Corruption
    corrupted = "Corrupted" in text

    # Implicit/explicit mods
    mods_section = text.split("--------\n")
    mods = []
    for section in mods_section:
        for line in section.split("\n"):
            line = line.strip()
            if line and (line.startswith("{") or "increased" in line.lower() or "modifier" in line.lower()):
                mods.append(line)

    # Detect type by modifiers
    ptype = detect_tablet_type(name, base, mods)

    return {
        "name": name,
        "base": base,
        "ilvl": ilvl,
        "corrupted": corrupted,
        "type": ptype,
        "mods": mods[:8],
        "raw": text,
    }


def detect_tablet_type(name: str, base: str, mods: list) -> str:
    """Detect what type of tablet this is based on name/mods."""
    n = (name + " " + base).lower()
    for kw, ptype in [
        ("abyss", "Abyss"),
        ("breach", "Breach"),
        ("ritual", "Ritual"),
        ("precursor", "Precursor"),
        ("expedition", "Expedition"),
        ("delirium", "Delirium"),
        ("expedition", "Expedition"),
    ]:
        if kw in n:
            return ptype
    return "Unknown"


def get_prices(league: str) -> dict:
    """Fetch current prices from poe2scout. Returns {api_id: chaos_price}."""
    le = urllib.parse.quote(league, safe="")
    url = f"https://poe2scout.com/api/poe2/Leagues/{le}/Items?perPage=2000"
    req = urllib.request.Request(url, headers={"User-Agent": "mypoeapp/1.0"})
    prices = {}
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            for it in json.loads(resp.read()):
                name = it.get("Name") or ""
                price = it.get("CurrentPrice")
                if name and price is not None:
                    prices[name] = price
    except Exception as e:
        print(f"price fetch error: {e}", file=sys.stderr)
    return prices


def get_ref_currencies(league: str) -> dict:
    """Get reference currency rates (chaos per unit)."""
    le = urllib.parse.quote(league, safe="")
    url = f"https://poe2scout.com/api/poe2/Leagues/{le}/ReferenceCurrencies"
    req = urllib.request.Request(url, headers={"User-Agent": "mypoeapp/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {e["ApiId"]: e["RelativePrice"] for e in json.loads(resp.read())}
    except Exception as e:
        print(f"ref currency error: {e}", file=sys.stderr)
        return {}


def price_to_chaos(amount: float, currency: str, refs: dict) -> float:
    """Convert a price to chaos using the reference rates."""
    cur = currency.lower()
    if cur == "chaos":
        return amount
    if cur not in refs:
        return 0
    # refs[cur] = how many ex to buy 1 of cur
    ex_amt = amount * refs[cur]
    if "chaos" in refs:
        return ex_amt / refs["chaos"]
    return 0


def suggest_list_price(chaos_value: float, undercut_pct: float = 5) -> dict:
    """Suggest a competitive list price slightly below market."""
    if chaos_value <= 0:
        return {"chaos": 0, "divine": 0, "note": "no market data"}
    # Undercut by undercut_pct
    chaos = chaos_value * (1 - undercut_pct / 100)
    divine = chaos / 40  # approx, will be refined
    if chaos >= 200:  # >= ~5 divine, list in divine
        return {"chaos": round(chaos, 0), "divine": round(divine, 1),
                "currency": "divine", "note": f"market {chaos_value:.0f}c, undercut {undercut_pct}%"}
    else:
        return {"chaos": round(chaos, 0), "divine": round(divine, 1),
                "currency": "chaos", "note": f"market {chaos_value:.0f}c, undercut {undercut_pct}%"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="Runes of Aldur")
    ap.add_argument("--ilvl", type=int, default=None, help="Min item level filter")
    ap.add_argument("--min-price", type=float, default=0,
                    help="Min market price in chaos to display")
    ap.add_argument("--copy", action="store_true",
                    help="Copy best listing to clipboard")
    ap.add_argument("--undercut", type=float, default=5,
                    help="Undercut %% for price suggestions (default 5)")
    args = ap.parse_args()

    # Get clipboard
    text = clipboard.get_clipboard_text_safe()
    if not text:
        print("Clipboard empty or no PoE2 item found. Ctrl+C a tablet in PoE2 first.")
        return

    # Parse
    items = []
    # Split by "Rarity:" to handle multiple items in one paste
    for chunk in re.split(r"(?=Rarity:\s*RARE|^Rarity:\s*UNIQUE)", text, flags=re.MULTILINE):
        chunk = chunk.strip()
        if not chunk:
            continue
        parsed = parse_tablet_text(chunk)
        if parsed:
            items.append(parsed)

    if not items:
        print("No tablets found in clipboard.")
        return

    # Fetch prices
    print(f"Fetching prices for {args.league}...", file=sys.stderr)
    prices = get_prices(args.league)
    refs = get_ref_currencies(args.league)
    chaos_per_ex = refs.get("chaos", 40)

    # Print
    print(f"\n{'NAME':<40} {'TYPE':<10} {'ILVL':<5} {'CORR':<5} "
          f"{'MARKET':<12} {'SUGGEST':<14}")
    print("=" * 100)
    best = None
    best_val = 0
    for item in items:
        ilvl = item["ilvl"] or 0
        if args.ilvl and ilvl < args.ilvl:
            continue
        market = prices.get(item["name"], 0)
        if market and chaos_per_ex:
            market_chaos = market / chaos_per_ex
        else:
            market_chaos = 0
        if market_chaos < args.min_price:
            continue
        sug = suggest_list_price(market_chaos, args.undercut)
        if market_chaos > best_val:
            best_val = market_chaos
            best = (item, sug)
        cor = "Yes" if item["corrupted"] else "No"
        sug_str = ""
        if sug.get("currency") == "divine":
            sug_str = f"{sug['divine']}d"
        else:
            sug_str = f"{sug['chaos']:.0f}c"
        print(f"{item['name'][:40]:<40} {item['type']:<10} {ilvl:<5} {cor:<5} "
              f"{market_chaos:<12.0f}c {sug_str:<14}  ({sug['note']})")

    print()
    if best:
        item, sug = best
        if sug.get("currency") == "divine":
            price_text = f"{sug['divine']}d"
        else:
            price_text = f"{sug['chaos']:.0f}c"
        print(f"Best deal: {item['name']} (ilvl {item['ilvl']}) — list at {price_text}")
        if args.copy:
            import pyperclip
            note = f"Price: {price_text} (market {best_val:.0f}c)"
            pyperclip.copy(item["raw"] + "\n\n" + note)
            print("Copied to clipboard.")


if __name__ == "__main__":
    main()
