"""
Pricing engine. Routes items to the correct pricer based on type,
uses DataSourceRegistry for multi-source pricing with normalized display.
"""
import json
import re
import time
from datetime import datetime, timezone
import time
from pathlib import Path
from typing import Dict, List, Optional

from cache import cache_price, find_price_by_name, get_price
from config import (
    CACHE_TTL,
    CATEGORY_TO_TRADE_ID,
    CURRENCY_TAGS,
)
from data_sources import DataSourceRegistry
from item_parser import parse_item
from mod_matcher import build_query_stat_filter, match_mods


_registry: Optional[DataSourceRegistry] = None


def get_registry() -> DataSourceRegistry:
    global _registry
    if _registry is None:
        from config import LEAGUE
        _registry = DataSourceRegistry(LEAGUE)
    return _registry


def identify_item(item: Dict) -> str:
    if item["rarity_tag"] == "currency":
        return "currency"
    if item["rarity_tag"] == "divcard":
        return "divination_card"
    if item["rarity_tag"] == "gem":
        return "gem"
    if item["rarity_tag"] == "quest":
        return "quest"
    if item["rarity_tag"] == "unique":
        return "unique"
    if item["rarity_tag"] == "rare":
        cls = (item.get("item_class") or "").lower()
        if "waystone" in cls:
            return "waystone"
        if "tablet" in cls:
            return "tablet"
        if "map" in cls:
            return "map"
        return "rare"
    if item["rarity_tag"] == "magic":
        return "magic"
    if item["rarity_tag"] == "normal":
        cls = (item.get("item_class") or "").lower()
        if "waystone" in cls:
            return "waystone"
        if "tablet" in cls:
            return "tablet"
        if "map" in cls:
            return "map"
        return "normal"
    return "unknown"


def price_item(item: Dict) -> Dict:
    kind = identify_item(item)
    registry = get_registry()
    if kind == "currency":
        return price_currency(item, registry)
    if kind == "divination_card":
        return price_divination_card(item, registry)
    if kind == "unique":
        return price_unique(item, registry)
    if kind == "rare":
        return price_rare(item, registry)
    if kind == "gem":
        return price_gem(item, registry)
    if kind == "waystone":
        return price_waystone(item, registry)
    if kind == "map":
        return price_map(item, registry)
    if kind == "tablet":
        return price_tablet(item, registry)
    if kind == "magic":
        return price_magic(item, registry)
    if kind == "normal":
        return {"kind": "normal", "name": item.get("base", ""), "chaos": 0,
                "note": "normal items not priced"}
    return {"kind": kind, "error": f"no pricer for kind={kind}", "item_base": item.get("base", "")}


def _normalize_currency_tag(name: str) -> str:
    name_lower = name.lower().strip()
    if name_lower in CURRENCY_TAGS:
        return CURRENCY_TAGS[name_lower]
    for key, tag in sorted(CURRENCY_TAGS.items(), key=lambda x: -len(x[0])):
        if key in name_lower:
            return tag
    return name_lower.replace(" ", "-").replace("'", "").replace(" orb", "")


def price_currency(item: Dict, registry: DataSourceRegistry) -> Dict:
    name = item.get("base") or item.get("name", "")
    tag = _normalize_currency_tag(name)
    cached = find_price_by_name(name, "currency")
    if cached:
        converter = registry.get_converter()
        ex_v = cached.get("exalted", 0) or 0
        normalized = converter.from_exalted(ex_v) if ex_v else {}
        return {
            "kind": "currency",
            "name": name,
            "tag": tag,
            "normalized": normalized,
            "cached": True,
            "age_seconds": cached["age_seconds"],
            "source": "cache",
        }
    result = registry.get_currency_price(tag)
    if not result:
        return {"kind": "currency", "name": name, "error": f"no price for '{name}' (tag: {tag})"}
    converter = registry.get_converter()
    normalized = converter.from_exalted(result["current_price_exalted"])
    cache_price(
        key=f"currency:{tag}",
        kind="currency",
        base=name,
        name=name,
        chaos=normalized.get("chaos", 0),
        divine=normalized.get("divine", 0),
        exalted=normalized.get("exalted", 0),
        listing_count=result.get("current_quantity", 0),
        detail={"tag": tag, "source": result["source"]},
        ttl_seconds=CACHE_TTL["currency"],
    )
    return {
        "kind": "currency",
        "name": name,
        "tag": tag,
        "normalized": normalized,
        "cached": False,
        "source": result["source"],
        "listing_count": result.get("current_quantity", 0),
    }


def price_divination_card(item: Dict, registry: DataSourceRegistry) -> Dict:
    name = item.get("base") or item.get("name", "")
    cached = find_price_by_name(name, "divination_card")
    if cached:
        converter = registry.get_converter()
        exalted_v = cached.get("exalted", 0) or 0
        return {
            "kind": "divination_card",
            "name": name,
            "normalized": converter.from_exalted(exalted_v) if exalted_v else {},
            "cached": True,
            "age_seconds": cached["age_seconds"],
            "source": "cache",
        }
    query = {
        "status": {"option": "online"},
        "type": "divcard",
        "name": name,
    }
    result = registry.trade.search_items(query)
    if not result or "result" not in result or not result.get("result"):
        return {"kind": "divination_card", "name": name, "error": f"divination card '{name}' not found on trade"}
    ids = result["result"][:10]
    fetched = registry.trade.fetch_results(result["id"], ids)
    if not fetched:
        return {"kind": "divination_card", "name": name, "error": "fetch failed"}
    converter = registry.get_converter()
    prices_exalted = []
    for entry in fetched.get("result", []):
        if not entry:
            continue
        price_info = entry.get("listing", {}).get("price", {})
        amount = price_info.get("amount", 0)
        currency = price_info.get("currency", "")
        if amount > 0 and currency:
            norm = converter.normalize_to_all(amount, currency)
            if norm.get("exalted", 0) > 0:
                prices_exalted.append(norm["exalted"])
    if not prices_exalted:
        return {"kind": "divination_card", "name": name, "error": "no prices in results"}
    prices_exalted.sort()
    idx = max(0, len(prices_exalted) // 5)
    median_exalted = prices_exalted[idx]
    normalized = converter.from_exalted(median_exalted)
    cache_price(
        key=f"divcard:{name}",
        kind="divination_card",
        base=name,
        name=name,
        chaos=normalized.get("chaos", 0),
        divine=normalized.get("divine", 0),
        exalted=median_exalted,
        listing_count=len(prices_exalted),
        detail={"source": "trade2"},
        ttl_seconds=CACHE_TTL["currency"],
    )
    return {
        "kind": "divination_card",
        "name": name,
        "normalized": normalized,
        "cached": False,
        "source": "trade2",
        "listing_count": len(prices_exalted),
    }


def price_unique(item: Dict, registry: DataSourceRegistry) -> Dict:
    name = item.get("name") or item.get("base", "")
    base = item.get("base", "")
    cached = find_price_by_name(name, "unique")
    if cached:
        converter = registry.get_converter()
        chaos_v = cached.get("chaos", 0)
        exalted_v = cached.get("exalted", 0)
        if exalted_v > 0:
            normalized = converter.from_exalted(exalted_v)
        elif chaos_v > 0:
            ex = converter.to_exalted(chaos_v, "chaos") or 0
            normalized = converter.from_exalted(ex)
        else:
            normalized = {}
        return {
            "kind": "unique",
            "name": name,
            "base": base,
            "normalized": normalized,
            "cached": True,
            "age_seconds": cached["age_seconds"],
            "source": "cache",
            "corrupted": item.get("corrupted", False),
        }
    result = registry.get_unique_price(name, base)
    if not result:
        return {"kind": "unique", "name": name, "base": base, "error": f"unique '{name}' not found"}
    normalized = result["normalized"]
    cache_price(
        key=f"unique:{name}",
        kind="unique",
        base=base,
        name=name,
        chaos=normalized.get("chaos", 0),
        divine=normalized.get("divine", 0),
        exalted=normalized.get("exalted", 0),
        listing_count=result.get("current_quantity", 0),
        detail={"source": result["source"], "icon": result.get("icon")},
        ttl_seconds=CACHE_TTL["unique"],
    )
    return {
        "kind": "unique",
        "name": name,
        "base": base,
        "normalized": normalized,
        "cached": False,
        "source": result["source"],
        "listing_count": result.get("current_quantity", 0),
        "corrupted": item.get("corrupted", False),
    }


def price_rare(item: Dict, registry: DataSourceRegistry) -> Dict:
    base = item.get("base", "")
    name = item.get("name", "")
    explicit = item.get("explicit_mods", [])
    matched = match_mods(explicit)
    priority_mods = _prioritize_mods(matched, item.get("item_class", ""))
    stat_filters = []
    for m in priority_mods[:3]:
        f = build_query_stat_filter(m)
        if f:
            stat_filters.append(f)
    trade_id = _base_to_trade_id(base, item.get("item_class", ""))
    cache_key = _rare_cache_key(base, item)
    cached = get_price(cache_key)
    if cached:
        converter = registry.get_converter()
        return _format_rare_result(cached, item, converter, from_cache=True)
    item_text = "\n".join(item.get("raw_lines", []))
    result = registry.get_rare_price(trade_id, stat_filters, base, item_text) if trade_id else None
    if result and "realistic_chaos" in result:
        converter = registry.get_converter()
        ex_amount = converter.to_exalted(result["realistic_chaos"], "chaos") or 0
        normalized = converter.from_exalted(ex_amount)
        cache_price(
            key=cache_key,
            kind="rare",
            base=base,
            name=name,
            chaos=result["realistic_chaos"],
            divine=normalized.get("divine", 0),
            exalted=normalized.get("exalted", 0),
            listing_count=result["total_listings"],
            detail={"filters": stat_filters, "trade_id": trade_id, "source": result["source"]},
            ttl_seconds=CACHE_TTL["rare"],
        )
        return {
            "kind": "rare",
            "name": name,
            "base": base,
            "normalized": normalized,
            "cached": False,
            "listing_count": result["total_listings"],
            "corrupted": item.get("corrupted", False),
            "source": result["source"],
        }
    if result and "pred_chaos" in result:
        converter = registry.get_converter()
        ex_amount = converter.to_exalted(result["pred_chaos"], "chaos") or 0
        normalized = converter.from_exalted(ex_amount)
        return {
            "kind": "rare",
            "name": name,
            "base": base,
            "normalized": normalized,
            "cached": False,
            "listing_count": 0,
            "corrupted": item.get("corrupted", False),
            "source": "poeprices",
            "confidence": result.get("confidence"),
            "pred_min": result.get("pred_min"),
            "pred_max": result.get("pred_max"),
        }
    base_avg = _get_base_type_average(base, registry)
    if base_avg:
        return {
            "kind": "rare",
            "name": name,
            "base": base,
            "normalized": base_avg,
            "cached": False,
            "source": "poe2scout_base_avg",
            "note": f"mod search unavailable for {base}; showing base-type average",
            "corrupted": item.get("corrupted", False),
        }
    return {
        "kind": "rare",
        "name": name,
        "base": base,
        "error": f"no pricing for {base} (trade2 type '{trade_id}' unsupported, no base avg)",
    }


def _get_base_type_average(base: str, registry: DataSourceRegistry) -> Optional[Dict]:
    """Fallback: get average price of all items with this base type from poe2scout."""
    try:
        items = registry.scout.fetch_all_items()
    except Exception:
        return None
    candidates = []
    base_lower = base.lower()
    for item in items:
        item_type = (item.get("Type") or "").lower()
        if item_type == base_lower:
            price = item.get("CurrentPrice", 0)
            if price > 0:
                candidates.append(price)
    if not candidates:
        for item in items:
            item_type = (item.get("Type") or "").lower()
            if base_lower in item_type or item_type in base_lower:
                price = item.get("CurrentPrice", 0)
                if price > 0:
                    candidates.append(price)
    if not candidates:
        return None
    candidates.sort()
    median = candidates[len(candidates) // 2]
    converter = registry.get_converter()
    return converter.from_exalted(median)


def _format_rare_result(cached: Dict, item: Dict, converter, from_cache: bool) -> Dict:
    exalted = cached.get("exalted", 0) or 0
    normalized = converter.from_exalted(exalted) if exalted else {}
    return {
        "kind": "rare",
        "name": item.get("name", ""),
        "base": item.get("base", ""),
        "normalized": normalized,
        "cached": from_cache,
        "age_seconds": cached.get("age_seconds", 0),
        "listing_count": cached.get("listing_count", 0),
        "corrupted": item.get("corrupted", False),
        "source": "cache",
    }


def _prioritize_mods(matched: List[Dict], item_class: str) -> List[Dict]:
    priority_keywords = [
        "maximum life", "to maximum life",
        "fire resistance", "cold resistance", "lightning resistance", "all elemental resistances",
        "chaos resistance",
        "critical strike chance", "critical strike multiplier",
        "attack speed", "cast speed",
        "physical damage", "added physical damage",
        "increased physical damage", "increased elemental damage",
        "spell damage", "spell skills",
        "spirit",
        "movement speed",
        "rune sockets",
        "gem level",
        "skill level",
    ]
    is_weapon = any(w in item_class.lower() for w in ["sword", "axe", "mace", "bow", "crossbow", "dagger", "wand", "staff", "spear"])
    if is_weapon:
        priority_keywords = [
            "physical damage", "increased physical damage", "attacks per second",
            "critical strike chance", "critical strike multiplier", "added damage",
            "elemental damage", "fire damage", "cold damage", "lightning damage",
            "attack speed",
        ] + priority_keywords
    def score(m: Dict) -> int:
        ref = (m.get("ref") or "").lower()
        for i, kw in enumerate(priority_keywords):
            if kw in ref:
                return i
        return 999
    return sorted(matched, key=score)


def _rare_cache_key(base: str, item: Dict) -> str:
    mods = []
    for m in item.get("explicit_mods", []):
        nums = re.findall(r"[+-]?\d+(?:\.\d+)?", m)
        mods.append(f"{m}|{','.join(nums)}")
    mods.sort()
    return f"rare:{base}:{item.get('ilvl', 0)}:{'|'.join(mods)}"


def _base_to_trade_id(base: str, item_class: str) -> str:
    from poe2db_data import get_base_type_trade_id
    trade_id = get_base_type_trade_id(base)
    if trade_id:
        return trade_id
    cls_lower = (item_class or "").lower().rstrip("s")
    if cls_lower in CATEGORY_TO_TRADE_ID:
        return CATEGORY_TO_TRADE_ID[cls_lower]
    if (item_class or "").lower() in CATEGORY_TO_TRADE_ID:
        return CATEGORY_TO_TRADE_ID[(item_class or "").lower()]
    base_lower = base.lower()
    for key, tid in CATEGORY_TO_TRADE_ID.items():
        if key in base_lower or key in (item_class or "").lower():
            return tid
    return ""


def price_gem(item: Dict, registry: DataSourceRegistry) -> Dict:
    name = item.get("base") or item.get("name", "")
    level = item.get("gem_level", 0)
    quality = item.get("quality", 0)
    cached = find_price_by_name(f"{name}|{level}|{quality}", "gem")
    if cached:
        converter = registry.get_converter()
        return {
            "kind": "gem",
            "name": name,
            "level": level,
            "quality": quality,
            "normalized": converter.from_exalted(cached.get("exalted", 0) or 0),
            "cached": True,
            "age_seconds": cached["age_seconds"],
            "corrupted": item.get("corrupted", False),
        }
    for cat in ("uncutgems", "lineagesupportgems"):
        items = registry.scout.fetch_items_by_category(cat)
        for gem in items:
            text = (gem.get("Text") or "").lower()
            name_lower = name.lower()
            if name_lower and (name_lower in text or text in name_lower):
                converter = registry.get_converter()
                normalized = converter.from_exalted(gem.get("CurrentPrice", 0))
                cache_price(
                    key=f"gem:{name}|{level}|{quality}",
                    kind="gem",
                    base=name,
                    name=f"{name} (lvl {level}, q{quality})",
                    chaos=normalized.get("chaos", 0),
                    divine=normalized.get("divine", 0),
                    exalted=normalized.get("exalted", 0),
                    listing_count=gem.get("CurrentQuantity", 0),
                    detail={"level": level, "quality": quality, "source": "poe2scout"},
                    ttl_seconds=CACHE_TTL["gem"],
                )
                return {
                    "kind": "gem",
                    "name": name,
                    "level": level,
                    "quality": quality,
                    "normalized": normalized,
                    "cached": False,
                    "source": "poe2scout",
                    "listing_count": gem.get("CurrentQuantity", 0),
                    "corrupted": item.get("corrupted", False),
                }
    return {"kind": "gem", "name": name, "error": f"gem '{name}' not found in uncutgems/lineagesupportgems"}


def price_waystone(item: Dict, registry: DataSourceRegistry) -> Dict:
    base = item.get("base", "")
    tier = _extract_tier(item)
    mods = _extract_waystone_mods(item)
    cache_key = _waystone_cache_key(base, tier, mods)
    name = f"{base} T{tier}" if tier else base
    print(f"[waystone] {name}, mods={mods}, cache_key={cache_key[:16]}", flush=True)
    cached = get_price(cache_key)
    if cached:
        print(f"[waystone] cache HIT, price={cached.get('exalted')}ex", flush=True)
        converter = registry.get_converter()
        stored = json.loads(cached.get("detail_json", "{}")).get("listings", [])
        return {
            "kind": "waystone",
            "name": name,
            "tier": tier,
            "mods": mods,
            "normalized": converter.from_exalted(cached.get("exalted", 0) or 0),
            "cached": True,
            "age_seconds": cached["age_seconds"],
            "listing_count": cached.get("listing_count", 0),
            "listings": stored,
            "corrupted": item.get("corrupted", False),
        }
    if mods:
        query = _build_waystone_query(base, tier, mods)
        result = registry.trade.search_items(query)
        total = result.get("total", 0) if result else 0
        n_ids = len(result.get("result", [])) if result else 0
        if result and result.get("result"):
            ids = result["result"][:10]
            fetched = registry.trade.fetch_results(result["id"], ids)
            if fetched:
                converter = registry.get_converter()
                listings = []
                for entry in fetched.get("result", []):
                    if not entry:
                        continue
                    p = entry.get("listing", {})
                    price_info = p.get("price", {})
                    amount = price_info.get("amount", 0)
                    currency = price_info.get("currency", "")
                    indexed = p.get("indexed", "")
                    account = p.get("account", {}).get("name", "?")
                    if amount > 0 and currency:
                        norm = converter.normalize_to_all(amount, currency)
                        if norm.get("chaos", 0) > 0:
                            listings.append({
                                "price_exalted": norm.get("exalted", 0),
                                "amount": amount,
                                "currency": currency,
                                "account": account,
                                "indexed": indexed,
                                "time_ago": _time_ago(indexed) if indexed else "",
                            })
                if listings:
                    cache_price(
                        key=cache_key,
                        kind="waystone",
                        base=base,
                        name=name,
                        chaos=listings[0]["price_exalted"],
                        divine=0,
                        exalted=listings[0]["price_exalted"],
                        listing_count=len(listings),
                        detail={"tier": tier, "mods": mods, "source": "trade2", "listings": listings},
                        ttl_seconds=CACHE_TTL["default"],
                    )
                    return {
                        "kind": "waystone",
                        "name": name,
                        "tier": tier,
                        "mods": mods,
                        "normalized": converter.from_exalted(listings[0]["price_exalted"]),
                        "cached": False,
                        "source": "trade2",
                        "listing_count": len(listings),
                        "listings": listings,
                        "corrupted": item.get("corrupted", False),
                    }
    sc_result = registry.get_waystone_price(base, tier)
    if sc_result and sc_result.get("current_price_exalted", 0) > 0:
        normalized = sc_result["normalized"]
        cache_price(
            key=cache_key,
            kind="waystone",
            base=base,
            name=name,
            chaos=normalized.get("chaos", 0),
            divine=normalized.get("divine", 0),
            exalted=normalized.get("exalted", 0),
            listing_count=sc_result.get("current_quantity", 0),
            detail={"tier": tier, "mods": mods, "source": sc_result["source"]},
            ttl_seconds=CACHE_TTL["default"],
        )
        return {
            "kind": "waystone",
            "name": name,
            "tier": tier,
            "mods": mods,
            "normalized": normalized,
            "cached": False,
            "source": sc_result["source"],
            "listing_count": sc_result.get("current_quantity", 0),
            "corrupted": item.get("corrupted", False),
        }
    return {
        "kind": "waystone",
        "name": name,
        "tier": tier,
        "mods": mods,
        "error": f"no listings for {base} T{tier} (market may be quiet)",
    }


def price_map(item: Dict, registry: DataSourceRegistry) -> Dict:
    return price_waystone(item, registry)


def _extract_tablet_stats(item: Dict) -> List[Dict]:
    """Extract tablet mod stats for trade2 query.

    Tablets use the stats array (not map_filters like waystones).
    Each matched mod gets a stat filter with the ACTUAL rolled value
    as the max constraint (matches EE2 behavior).
    """
    from mod_matcher import match_mod
    stats = []
    for mod_text in item.get("explicit_mods", []):
        m = match_mod(mod_text)
        if not m:
            continue
        import re
        match = re.search(r"^(\d+(?:\.\d+)?)", mod_text)
        if not m.get("value"):
            continue
        rolled_value = int(m["value"])
        stats.append({
            "id": m["trade_id"],
            "value": {"max": rolled_value},
            "disabled": False,
        })
    return stats


def price_tablet(item: Dict, registry: DataSourceRegistry) -> Dict:
    base = item.get("base", "")
    name = item.get("name", base)
    stats = _extract_tablet_stats(item)
    cache_key = f"tablet:{base}:{hash(tuple((s['id'], s['value']['min'], s['value']['max']) for s in stats))}"
    cached = get_price(cache_key)
    if cached:
        converter = registry.get_converter()
        stored = json.loads(cached.get("detail_json", "{}")).get("listings", [])
        return {
            "kind": "tablet",
            "name": name,
            "base": base,
            "normalized": converter.from_exalted(cached.get("exalted", 0) or 0),
            "cached": True,
            "age_seconds": cached["age_seconds"],
            "listing_count": cached.get("listing_count", 0),
            "listings": stored,
        }

    query = {
        "status": {"option": "online"},
        "stats": [{"type": "and", "filters": stats}] if stats else [{"type": "and", "filters": []}],
        "filters": {
            "type_filters": {
                "filters": {
                    "category": {"option": "map.tablet"},
                }
            },
        }
    }
    if item.get("rarity", "").upper() == "RARE":
        query["filters"]["type_filters"]["filters"]["rarity"] = {"option": "nonunique"}

    result = registry.trade.search_items(query)
    if result and result.get("result"):
        ids = result["result"][:10]
        fetched = registry.trade.fetch_results(result["id"], ids)
        if fetched:
            converter = registry.get_converter()
            listings = []
            for entry in fetched.get("result", []):
                if not entry:
                    continue
                p = entry.get("listing", {})
                price_info = p.get("price", {})
                amount = price_info.get("amount", 0)
                currency = price_info.get("currency", "")
                indexed = p.get("indexed", "")
                if amount > 0 and currency:
                    norm = converter.normalize_to_all(amount, currency)
                    if norm.get("chaos", 0) > 0:
                        listings.append({
                            "price_exalted": norm.get("exalted", 0),
                            "amount": amount,
                            "currency": currency,
                            "indexed": indexed,
                            "time_ago": _time_ago(indexed) if indexed else "",
                        })
            if listings:
                cache_price(
                    key=cache_key,
                    kind="tablet",
                    base=base,
                    name=name,
                    chaos=listings[0]["price_exalted"],
                    divine=0,
                    exalted=listings[0]["price_exalted"],
                    listing_count=len(listings),
                    detail={"source": "trade2", "listings": listings},
                    ttl_seconds=CACHE_TTL["default"],
                )
                return {
                    "kind": "tablet",
                    "name": name,
                    "base": base,
                    "normalized": converter.from_exalted(listings[0]["price_exalted"]),
                    "cached": False,
                    "source": "trade2",
                    "listing_count": len(listings),
                    "listings": listings,
                }
    sc_result = registry.scout.lookup_item_by_name(base, item_type=None, category="map")
    if sc_result:
        converter = registry.get_converter()
        normalized = converter.from_exalted(sc_result.get("CurrentPrice", 0))
        return {
            "kind": "tablet",
            "name": name,
            "base": base,
            "normalized": normalized,
            "source": "poe2scout",
            "listing_count": sc_result.get("CurrentQuantity", 0),
        }
    return {"kind": "tablet", "name": name, "base": base, "error": "not found"}


def price_magic(item: Dict, registry: DataSourceRegistry) -> Dict:
    return {"kind": "magic", "name": item.get("base", ""), "chaos": 0,
            "note": "magic items not priced (identify to check value)"}


def _extract_tier(item: Dict) -> int:
    for line in item.get("raw_lines", []):
        if "Tier:" in line or "Waystone (Tier" in line:
            m = re.search(r"Tier\s*(\d+)", line)
            if m:
                return int(m.group(1))
    return 0


def _extract_waystone_mods(item: Dict) -> Dict[str, int]:
    """Extract numeric values for the waystone's rolled mod filters.

    Maps waystone property text -> trade2 map_filters field names.
    Source: data/client_strings.js (canonical labels) + EE2's
    known-working trade2 fields.

    Trade2-filterable (sent in query body):
        "Waystone Tier: "      -> map_tier       (T1-T16)
        "Waystone Packsize: "  -> map_packsize   (Pack Size)
        "Waystone IIR: "       -> map_iir         (Item Rarity)
        "Magic Monsters: "     -> map_magic_monsters
        "Rare Monsters: "      -> map_rare_monsters
        "Waystone Drop Chance: " -> map_bonus     (IIQ)
        "Waystone Revives: "   -> map_revives     (Portals)

    Display-only (no trade2 field exists):
        "Monster Effectiveness: " — no `map_effectiveness` field
        "Monster Rarity: "      — only on items, not waystones
        "Waystone Experience: " — no field
        "Waystone Gold: "       — no field
    """
    mod_map = {
        "Waystone Tier: ": "map_tier",
        "Pack Size: ": "map_packsize",
        "Item Rarity: ": "map_iir",
        "Magic Monsters: ": "map_magic_monsters",
        "Rare Monsters: ": "map_rare_monsters",
        "Waystone Drop Chance: ": "map_bonus",
        "Revives Available: ": "map_revives",
    }
    found = {}
    raw_lines = item.get("raw_lines", [])
    for line in raw_lines:
        s = line.strip()
        if not s:
            continue
        for label, field in mod_map.items():
            if s.startswith(label):
                nums = re.findall(r"([+-]?\d+(?:\.\d+)?)", s)
                if nums:
                    try:
                        val = int(round(float(nums[0])))
                        found[field] = max(found.get(field, 0), val)
                    except ValueError:
                        pass
                break
    raw_text = "\n".join(raw_lines)
    found["corrupted"] = "Corrupted" in raw_text and item.get("corrupted", False)
    return found


# Mods that actually drive price differences for waystones — what
# EE2 includes in the trade2 search body. Keep this list short:
_HIGH_IMPACT_WAYSTONE_MODS = (
    "map_packsize",
    "map_magic_monsters",
    "map_rare_monsters",
    "map_iir",
    "map_bonus",
    "map_revives",
)


def _build_waystone_query(base: str, tier: int, mods: Dict[str, int]) -> Dict:
    """Build a trade2 search body for a waystone with given mods.

    Only sends the high-impact mods to trade2 so we don't get an
    over-restrictive filter that returns zero listings. Includes the
    corrupted filter from the misc_filters block.
    """
    query = {
        "status": {"option": "online"},
        "stats": [{"type": "and", "filters": []}],
        "filters": {
            "type_filters": {
                "filters": {
                    "category": {"option": "map.waystone"}
                }
            },
            "map_filters": {"filters": {}},
        }
    }
    if mods.get("corrupted"):
        query["filters"]["misc_filters"] = {
            "filters": {"corrupted": {"option": "true"}}
        }
    if tier:
        query["filters"]["map_filters"]["filters"]["map_tier"] = {
            "min": tier, "max": tier
        }
    for field in _HIGH_IMPACT_WAYSTONE_MODS:
        value = mods.get(field, 0)
        if value > 0:
            query["filters"]["map_filters"]["filters"][field] = {"min": value}
    if mods.get("corrupted"):
        query["filters"]["misc_filters"] = {
            "filters": {"corrupted": {"option": "true"}}
        }
    return query

def _waystone_cache_key(base: str, tier: int, mods: Dict[str, int]) -> str:
    """Stable cache key for waystone mod combinations."""
    import hashlib
    mod_str = "|".join(f"{k}={v}" for k, v in sorted(mods.items()))
    raw = f"waystone:{base}:T{tier}:{mod_str}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def price_text(text: str) -> Dict:
    item = parse_item(text)
    if not item.get("rarity"):
        return {"error": "no rarity found - is this an item?"}
    result = price_item(item)
    result["parsed_item"] = {
        "rarity": item["rarity"],
        "base": item.get("base", ""),
        "name": item.get("name", ""),
        "item_class": item.get("item_class", ""),
        "ilvl": item.get("ilvl", 0),
        "corrupted": item.get("corrupted", False),
        "level": item.get("gem_level", 0),
        "quality": item.get("quality", 0),
    }
    return result


def _time_ago(iso_str: str) -> str:
    t = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    delta = datetime.now(timezone.utc) - t
    seconds = delta.total_seconds()
    if seconds < 3600:
        return f"{int(seconds / 60)}m"
    if seconds < 86400:
        return f"{int(seconds / 3600)}h"
    if seconds < 604800:
        return f"{int(seconds / 86400)}d"
    return f"{int(seconds / 604800)}w"
