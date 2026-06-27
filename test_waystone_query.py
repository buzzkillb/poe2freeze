import requests
import json
import time

LEAGUE = "Runes of Aldur"
SEARCH_URL = f"https://www.pathofexile.com/api/trade2/search/{LEAGUE}"
FETCH_URL = "https://www.pathofexile.com/api/trade2/fetch/"
HEADERS = {
    "User-Agent": "OAuth poe2ninja/1.0",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

EXALT = 1.0
DIVINE = 372.0
CHAOS = 1.0 / 36.81


def convert_price(item):
    price_info = item.get("listing", {}).get("price", {})
    if not price_info:
        return "no price listed"
    amount = price_info.get("amount", 0)
    currency = price_info.get("currency", "?")
    if currency == "exalted":
        return f"{amount} ex"
    elif currency == "divine":
        return f"{amount} div = {amount * DIVINE:.1f} ex"
    elif currency == "chaos":
        return f"{amount} chaos = {amount * CHAOS:.2f} ex"
    else:
        return f"{amount} {currency}"


# Field names observed to work in the trade2 API via pricer.py:
#   map_tier, map_packsize, map_iir, map_bonus, map_magic_monsters,
#   map_rare_monsters, map_revives
#
# For T15 corrupted waystone with Pack Size 19+ / Item Rarity 46+ / 
# Waystone Drop Chance 145+ / Corrupted, the map_filters are:
map_filter_fields = {
    "map_tier": {"min": 15, "max": 15},
    "map_packsize": {"min": 19},
    "map_iir": {"min": 46},
    "map_bonus": {"min": 145},
}

# Tests based on _build_waystone_query() structure from pricer.py:709
# The full body sent is {"query": query, "sort": {"price": "asc"}} but
# we focus on the `query` dict content since sort is always the same.

tests = {}

# Test A: Just map_filters + basic type + trade collapse (current pricer format)
tests["Test A: pricer exact format"] = {
    "status": {"option": "online"},
    "stats": [{"type": "and", "filters": []}],
    "filters": {
        "type_filters": {
            "filters": {"category": {"option": "map.waystone"}}
        },
        "map_filters": {
            "filters": map_filter_fields
        },
        "trade_filters": {
            "filters": {"collapse": {"option": "true"}}
        },
        "misc_filters": {
            "filters": {"corrupted": {"option": "true"}}
        },
    },
}

# Test B: Same as A but WITHOUT corrupted filter
tests["Test B: pricer format, no corrupted"] = {
    "status": {"option": "online"},
    "stats": [{"type": "and", "filters": []}],
    "filters": {
        "type_filters": {
            "filters": {"category": {"option": "map.waystone"}}
        },
        "map_filters": {
            "filters": map_filter_fields
        },
        "trade_filters": {
            "filters": {"collapse": {"option": "true"}}
        },
    },
}

# Test C: Same as A but WITHOUT type_filters
tests["Test C: no type_filters"] = {
    "status": {"option": "online"},
    "stats": [{"type": "and", "filters": []}],
    "filters": {
        "map_filters": {
            "filters": map_filter_fields
        },
        "trade_filters": {
            "filters": {"collapse": {"option": "true"}}
        },
        "misc_filters": {
            "filters": {"corrupted": {"option": "true"}}
        },
    },
}

# Test D: Same as A but WITHOUT trade_filters (collapse)
tests["Test D: no collapse"] = {
    "status": {"option": "online"},
    "stats": [{"type": "and", "filters": []}],
    "filters": {
        "type_filters": {
            "filters": {"category": {"option": "map.waystone"}}
        },
        "map_filters": {
            "filters": map_filter_fields
        },
        "misc_filters": {
            "filters": {"corrupted": {"option": "true"}}
        },
    },
}

# Test E: Only map_filters + misc_filters, no stats, no type, no collapse
tests["Test E: minimal (map_filters + corrupted only)"] = {
    "status": {"option": "online"},
    "filters": {
        "map_filters": {
            "filters": map_filter_fields
        },
        "misc_filters": {
            "filters": {"corrupted": {"option": "true"}}
        },
    },
}

# Test F: No stats, just filters
tests["Test F: no stats array"] = {
    "status": {"option": "online"},
    "filters": {
        "type_filters": {
            "filters": {"category": {"option": "map.waystone"}}
        },
        "map_filters": {
            "filters": map_filter_fields
        },
        "trade_filters": {
            "filters": {"collapse": {"option": "true"}}
        },
        "misc_filters": {
            "filters": {"corrupted": {"option": "true"}}
        },
    },
}


def run_test(name, query):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

    body = {"query": query, "sort": {"price": "asc"}}
    print(f"  Body: {json.dumps(body)[:300]}")

    try:
        resp = requests.post(SEARCH_URL, headers=HEADERS, json=body, timeout=30)
    except Exception as e:
        print(f"  Request failed: {e}")
        return None, 0

    status = resp.status_code
    print(f"  HTTP Status: {status}")

    if status != 200:
        try:
            print(f"  Response: {resp.text[:500]}")
        except:
            pass
        return None, 0

    data = resp.json()
    total = data.get("total", 0)
    result_ids = data.get("result", [])
    query_id = data.get("id", "")

    print(f"  Total result count: {total}")
    print(f"  Result IDs returned: {len(result_ids)}")

    if not result_ids:
        return total, 0

    fetch_ids = ",".join(result_ids[:5])
    fetch_endpoint = f"{FETCH_URL}{fetch_ids}?query={query_id}"
    try:
        resp2 = requests.get(fetch_endpoint, headers=HEADERS, timeout=30)
    except Exception as e:
        print(f"  Fetch failed: {e}")
        return total, len(result_ids)

    if resp2.status_code != 200:
        print(f"  Fetch HTTP: {resp2.status_code}")
        return total, len(result_ids)

    fetch_data = resp2.json()
    results = fetch_data.get("result", [])
    print(f"  First 5 prices:")
    for i, item in enumerate(results):
        price_str = convert_price(item)
        print(f"    {i+1}. {price_str}")

    return total, len(result_ids)


def main():
    results = {}
    test_names = list(tests.keys())
    for idx, name in enumerate(test_names):
        total, num_ids = run_test(name, tests[name])
        results[name] = {"total": total, "num_ids": num_ids}
        if idx < len(test_names) - 1:
            print("\n  (waiting 2s...)")
            time.sleep(2)

    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    target = 5
    best = None
    best_diff = float("inf")
    for name, r in results.items():
        t = r["total"]
        diff = abs((t or 0) - target)
        print(f"  {name}: total={t}, ids={r['num_ids']}")
        if t is not None and diff < best_diff:
            best_diff = diff
            best = name

    if best:
        print(f"\n  >>> Best match: {best} (total={results[best]['total']})")


if __name__ == "__main__":
    main()
