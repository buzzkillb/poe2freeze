"""
Data source registry. Multiple backends with priority-based fallback.
Each backend implements: fetch_currency_rate, fetch_item_price, fetch_unique_price.
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple


class RateLimiter:
    def __init__(self, max_per_second: float = 4.0):
        self.min_interval = 1.0 / max_per_second
        self.last_request = 0.0

    def wait(self):
        elapsed = time.time() - self.last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request = time.time()


def http_get(url: str, headers: Dict = None, timeout: int = 15) -> Tuple[Optional[str], Optional[str], int]:
    h = {"User-Agent": "OAuth poe2ninja-tool/1.0 (contact: dev@example.com)", "Accept": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, method="GET", headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore"), None, resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        return body, f"HTTP {e.code}", e.code
    except Exception as e:
        return None, str(e), 0


def http_post(url: str, body: Dict, headers: Dict = None, timeout: int = 15) -> Tuple[Optional[Dict], Optional[str], int]:
    h = {"User-Agent": "OAuth poe2ninja-tool/1.0 (contact: dev@example.com)",
         "Accept": "application/json", "Content-Type": "application/json"}
    if headers:
        h.update(headers)
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            try:
                return json.loads(raw), None, resp.status
            except Exception:
                return None, "invalid json", resp.status
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="ignore")
        try:
            return json.loads(body_text), None, e.code
        except Exception:
            return None, f"HTTP {e.code}: {body_text[:200]}", e.code
    except Exception as e:
        return None, str(e), 0


class Poe2ScoutSource:
    """poe2scout.com - primary PoE2 source. Free, anonymous, comprehensive."""

    NAME = "poe2scout"
    BASE = "https://poe2scout.com/api"
    SUPPORTS_RARES = False
    SUPPORTS_UNIQUE_MODS = False

    def __init__(self, league: str):
        self.league = league
        self.league_encoded = urllib.parse.quote(league, safe="")
        self._items_cache = None
        self._items_cache_time = 0
        self._uniques_cache = {}
        self._reference_currencies = None
        self._reference_currencies_time = 0
        self._rate_limiter = RateLimiter(max_per_second=3.0)

    def _req(self, path: str) -> Optional[Dict]:
        self._rate_limiter.wait()
        url = f"{self.BASE}/{path}"
        body, err, status = http_get(url)
        if err or status != 200 or not body:
            return None
        try:
            return json.loads(body)
        except Exception:
            return None

    def fetch_reference_currencies(self) -> Dict[str, float]:
        """Returns dict of api_id -> relative_price_in_exalts.
        e.g. {'exalted': 1.0, 'chaos': 36.77, 'divine': 355.59}
        """
        now = time.time()
        if self._reference_currencies and (now - self._reference_currencies_time) < 300:
            return self._reference_currencies
        data = self._req(f"poe2/Leagues/{self.league_encoded}/ReferenceCurrencies")
        if not data:
            return {}
        result = {}
        for entry in data:
            api_id = entry.get("ApiId", "").lower()
            rel = entry.get("RelativePrice", 0)
            if api_id and rel > 0:
                result[api_id] = rel
        self._reference_currencies = result
        self._reference_currencies_time = now
        return result

    def fetch_items_by_category(self, category: str, endpoint: str = "Uniques") -> List[Dict]:
        now = time.time()
        cache_key = f"{endpoint}:{category}"
        if cache_key in self._uniques_cache:
            cached_time, cached_data = self._uniques_cache[cache_key]
            if (now - cached_time) < 600:
                return cached_data
        all_items = []
        page = 1
        while True:
            data = self._req(f"poe2/Leagues/{self.league_encoded}/{endpoint}/ByCategory?Category={category}&Page={page}")
            if not data:
                break
            items = data.get("Items", [])
            if not items:
                break
            all_items.extend(items)
            total_pages = data.get("Pages", 1)
            if page >= total_pages:
                break
            page += 1
        self._uniques_cache[cache_key] = (now, all_items)
        return all_items

    def fetch_all_items(self) -> List[Dict]:
        now = time.time()
        if self._items_cache and (now - self._items_cache_time) < 600:
            return self._items_cache
        data = self._req(f"poe2/Leagues/{self.league_encoded}/Items")
        if not data:
            self._items_cache = []
            self._items_cache_time = now
            return []
        self._items_cache = data
        self._items_cache_time = now
        return data

    def lookup_item_by_name(self, name: str, item_type: str = None, category: str = None) -> Optional[Dict]:
        name_lower = name.lower().strip()
        type_lower = (item_type or "").lower().strip()
        if category:
            items = self.fetch_items_by_category(category)
        else:
            items = self.fetch_all_items()
        for item in items:
            item_name = (item.get("Name") or "").lower()
            item_text = (item.get("Text") or "").lower()
            item_type_str = (item.get("Type") or "").lower()
            if name_lower == item_name or name_lower in item_text:
                if not type_lower or type_lower == item_type_str or type_lower in item_text:
                    return item
        return None

    def fetch_unique_price(self, item_name: str, base_type: str) -> Optional[Dict]:
        name_lower = (item_name or "").lower()
        base_lower = (base_type or "").lower()
        if name_lower.startswith("you cannot") or "stats will be ignored" in name_lower:
            return None
        categories = ["weapon", "armour", "accessory", "flask", "jewel", "sanctum", "map"]
        all_matches = []
        for cat in categories:
            items = self.fetch_items_by_category(cat, endpoint="Uniques")
            for item in items:
                iname = (item.get("Name") or "").lower().lstrip("the ").strip()
                iname_full = (item.get("Name") or "").lower()
                itype = (item.get("Type") or "").lower()
                if iname_full == name_lower or iname == name_lower.lstrip("the ").strip():
                    if not base_lower or base_lower in itype or itype in base_lower or base_lower == itype:
                        return {
                            "name": item.get("Name"),
                            "base": item.get("Type"),
                            "current_price_exalted": item.get("CurrentPrice", 0),
                            "current_quantity": item.get("CurrentQuantity", 0),
                            "icon": item.get("IconUrl"),
                            "source": self.NAME,
                        }
                    all_matches.append(item)
        if all_matches:
            best = all_matches[0]
            return {
                "name": best.get("Name"),
                "base": best.get("Type"),
                "current_price_exalted": best.get("CurrentPrice", 0),
                "current_quantity": best.get("CurrentQuantity", 0),
                "icon": best.get("IconUrl"),
                "source": self.NAME,
            }
        for cat in categories:
            items = self.fetch_items_by_category(cat, endpoint="Uniques")
            for item in items:
                iname_full = (item.get("Name") or "").lower()
                if iname_full == name_lower:
                    return {
                        "name": item.get("Name"),
                        "base": item.get("Type"),
                        "current_price_exalted": item.get("CurrentPrice", 0),
                        "current_quantity": item.get("CurrentQuantity", 0),
                        "icon": item.get("IconUrl"),
                        "source": self.NAME,
                    }
        return None

    def fetch_currency_price(self, currency_api_id: str) -> Optional[Dict]:
        items = self.fetch_all_items()
        api_lower = currency_api_id.lower()
        for item in items:
            api_id = (item.get("ApiId") or "").lower()
            if api_id == api_lower:
                return {
                    "name": item.get("Text") or item.get("Name"),
                    "current_price_exalted": item.get("CurrentPrice", 0),
                    "current_quantity": item.get("CurrentQuantity", 0),
                    "source": self.NAME,
                }
        for cat in ("currency", "runes", "essences", "fragments", "ultimatum", "breach",
                    "expedition", "ritual", "delirium", "uncutgems", "lineagesupportgems",
                    "incursion", "abyss", "vaultkeys", "verisium", "vaal", "idol"):
            items = self.fetch_items_by_category(cat, endpoint="Currencies")
            for item in items:
                api_id = (item.get("ApiId") or "").lower()
                if api_id == api_lower:
                    return {
                        "name": item.get("Text") or item.get("Name"),
                        "current_price_exalted": item.get("CurrentPrice", 0),
                        "current_quantity": item.get("CurrentQuantity", 0),
                        "source": self.NAME,
                    }
        return None

    def fetch_all_currency_prices(self) -> Dict[str, Dict]:
        """Bulk-fetch every category with currency-like items."""
        result = {}
        for cat in ("currency", "runes", "essences", "fragments", "ultimatum", "breach",
                    "expedition", "ritual", "delirium", "uncutgems", "lineagesupportgems",
                    "incursion", "abyss", "vaultkeys", "verisium", "vaal", "idol"):
            items = self.fetch_items_by_category(cat, endpoint="Currencies")
            for item in items:
                api_id = (item.get("ApiId") or "").lower()
                if not api_id:
                    continue
                result[api_id] = {
                    "name": item.get("Text") or item.get("Name"),
                    "current_price_exalted": item.get("CurrentPrice", 0),
                    "current_quantity": item.get("CurrentQuantity", 0),
                    "category": cat,
                }
        return result

    def fetch_all_unique_prices(self) -> Dict[str, Dict]:
        """Bulk-fetch every unique item by category."""
        result = {}
        for cat in ("weapon", "armour", "accessory", "flask", "jewel", "sanctum", "map"):
            items = self.fetch_items_by_category(cat, endpoint="Uniques")
            for item in items:
                name = item.get("Name")
                if not name:
                    continue
                result[name.lower()] = {
                    "name": name,
                    "base": item.get("Type"),
                    "current_price_exalted": item.get("CurrentPrice", 0),
                    "current_quantity": item.get("CurrentQuantity", 0),
                    "category": cat,
                }
        return result

    def fetch_waystone_price(self, base_type: str, tier: int = 0) -> Optional[Dict]:
        items = self.fetch_all_items()
        base_lower = base_type.lower()
        candidates = []
        for item in items:
            cat = (item.get("CategoryApiId") or "").lower()
            if cat != "waystones":
                continue
            itype = (item.get("Type") or "").lower()
            if base_lower in itype or itype in base_lower:
                candidates.append(item)
        if not candidates:
            return None
        best = None
        for c in candidates:
            text = c.get("Text", "")
            if tier > 0:
                if f"T{tier}" not in text and f"Tier {tier}" not in text:
                    continue
            price = c.get("CurrentPrice", 0)
            if best is None or price > best.get("CurrentPrice", 0):
                best = c
        if not best:
            return None
        return {
            "name": best.get("Text") or best.get("Name"),
            "current_price_exalted": best.get("CurrentPrice", 0),
            "current_quantity": best.get("CurrentQuantity", 0),
            "source": self.NAME,
        }


class OfficialTradeSource:
    """Official GGG trade2 API. Only source that handles rare mod-based pricing."""

    NAME = "official_trade"
    BASE = "https://www.pathofexile.com"

    def __init__(self, league: str):
        self.league = league
        self.league_encoded = urllib.parse.quote(league, safe="")
        self._rate_limiter = RateLimiter(max_per_second=1.0)
        self._last_search_time = 0
        self._search_lock = threading.Lock()

    def _req(self, method: str, path: str, body: Optional[Dict] = None) -> Tuple[Optional[Dict], int]:
        self._rate_limiter.wait()
        url = f"{self.BASE}{path}"
        for attempt in range(2):
            if method == "POST":
                data, err, status = http_post(url, body)
            else:
                raw, err, status = http_get(url)
                if not err and raw:
                    try:
                        data = json.loads(raw)
                    except Exception:
                        data = None
                else:
                    data = None
            if status == 429:
                time.sleep(5)
                continue
            return data, status
        return None, status

    def search_items(self, query: Dict) -> Optional[Dict]:
        with self._search_lock:
            elapsed = time.time() - self._last_search_time
            if elapsed < 1.5:
                time.sleep(1.5 - elapsed)
            self._last_search_time = time.time()
        body = {"query": query, "sort": {"price": "asc"}}
        data, status = self._req("POST", f"/api/trade2/search/{self.league_encoded}", body)
        return data

    def fetch_results(self, query_id: str, ids: List[str]) -> Optional[Dict]:
        if not ids:
            return None
        ids_param = ",".join(ids[:10])
        data, status = self._req("GET", f"/api/trade2/fetch/{ids_param}?query={query_id}")
        return data

    def fetch_rare_price(self, trade_id: str, stat_filters: List[Dict],
                          base_type: str = None) -> Optional[Dict]:
        query = {
            "status": {"option": "online"},
            "stats": [{"type": "and", "filters": []}],
            "filters": {
                "type_filters": {
                    "filters": {
                        "category": {"option": trade_id},
                        "rarity": {"option": "nonunique"},
                    }
                }
            }
        }
        if base_type:
            query["type"] = base_type
        if stat_filters:
            query["stats"][0]["filters"] = stat_filters
        result = self.search_items(query)
        if not result or "result" not in result or not result.get("result"):
            query_no_type = dict(query)
            query_no_type.pop("type", None)
            result = self.search_items(query_no_type)
            if not result or "result" not in result or not result.get("result"):
                return None
        ids = result["result"][:10]
        fetched = self.fetch_results(result["id"], ids)
        if not fetched or "result" not in fetched:
            return None
        prices = []
        for entry in fetched["result"]:
            if not entry:
                continue
            price_info = entry.get("listing", {}).get("price", {})
            amount = price_info.get("amount", 0)
            currency = price_info.get("currency", "")
            if amount > 0 and currency:
                prices.append((amount, currency))
        if not prices:
            return None
        return {"listings": prices, "source": self.NAME, "total_listings": result.get("total", 0)}

    def fetch_currency_exchange(self, have: str, want: str) -> Optional[List[Dict]]:
        body = {
            "engine": "new",
            "query": {
                "status": {"option": "online"},
                "have": [have],
                "want": [want],
            },
            "sort": {"have": "asc"},
        }
        data, status = self._req("POST", f"/api/trade2/exchange/{self.league_encoded}", body)
        if not data or "result" not in data:
            return None
        return list(data["result"].values())


class PoePricesSource:
    """poeprices.info - statistical predictor for rares. Free, anonymous."""

    NAME = "poeprices"
    BASE = "https://poeprices.info/api"

    def __init__(self, league: str):
        self.league = league
        self._rate_limiter = RateLimiter(max_per_second=1.0)

    def fetch_prediction(self, item_text: str) -> Optional[Dict]:
        self._rate_limiter.wait()
        encoded = urllib.parse.quote(item_text, safe="")
        url = f"{self.BASE}?l={urllib.parse.quote(self.league)}&s=poe2&i={encoded}"
        body, err, status = http_get(url)
        if err or status != 200 or not body:
            return None
        try:
            data = json.loads(body)
        except Exception:
            return None
        if data.get("error", 0) != 0:
            return None
        return {
            "min": data.get("min"),
            "max": data.get("max"),
            "mean": data.get("mean"),
            "pred": data.get("pred"),
            "confidence": data.get("confidence"),
            "source": self.NAME,
        }


class PriceConverter:
    """Convert prices between exalted, divine, chaos using live rates.
    poe2scout's ReferenceCurrencies['RelativePrice'] is 'how many exalts
    does 1 of this currency cost on the in-game exchange'. So chaos=38.2
    means 1 chaos = 38.2 ex, i.e. 1 ex = 1/38.2 = 0.026 chaos.
    """

    def __init__(self, reference_currencies: Dict[str, float]):
        self.ref = reference_currencies
        self.ex_per_unit = {}
        self.units_per_ex = {}
        for api_id, ex_price in reference_currencies.items():
            if ex_price > 0:
                self.ex_per_unit[api_id] = ex_price
                self.units_per_ex[api_id] = 1.0 / ex_price

    def from_exalted(self, exalted_amount: float) -> Dict[str, float]:
        result = {"exalted": exalted_amount}
        for api_id, units in self.units_per_ex.items():
            result[api_id] = exalted_amount * units
        return result

    def to_exalted(self, amount: float, currency_api_id: str) -> Optional[float]:
        cur_lower = currency_api_id.lower().strip()
        if cur_lower in self.ex_per_unit:
            return amount * self.ex_per_unit[cur_lower]
        return None

    def normalize_to_all(self, amount: float, currency_api_id: str) -> Dict[str, float]:
        exalted = self.to_exalted(amount, currency_api_id)
        if exalted is None:
            return {"exalted": 0, "chaos": 0, "divine": 0, "original": amount, "original_currency": currency_api_id}
        return self.from_exalted(exalted)


class DataSourceRegistry:
    """Coordinates multiple data sources with priority-based fallback."""

    def __init__(self, league: str):
        self.league = league
        self.scout = Poe2ScoutSource(league)
        self.trade = OfficialTradeSource(league)
        self.poeprices = PoePricesSource(league)
        self._converter = None
        self._converter_time = 0

    def get_converter(self) -> PriceConverter:
        now = time.time()
        if self._converter and (now - self._converter_time) < 300:
            return self._converter
        refs = self.scout.fetch_reference_currencies()
        if refs:
            self._converter = PriceConverter(refs)
            self._converter_time = now
        elif self._converter is None:
            self._converter = PriceConverter({"exalted": 1.0, "chaos": 30.0, "divine": 300.0})
        return self._converter

    def get_currency_price(self, currency_api_id: str) -> Optional[Dict]:
        result = self.scout.fetch_currency_price(currency_api_id)
        if result:
            converter = self.get_converter()
            result["normalized"] = converter.from_exalted(result["current_price_exalted"])
        return result

    def get_unique_price(self, item_name: str, base_type: str = "") -> Optional[Dict]:
        result = self.scout.fetch_unique_price(item_name, base_type)
        if result:
            converter = self.get_converter()
            result["normalized"] = converter.from_exalted(result["current_price_exalted"])
        return result

    def get_rare_price(self, trade_id: str, stat_filters: List[Dict],
                      base_type: str = "", item_text: str = "") -> Optional[Dict]:
        result = self.trade.fetch_rare_price(trade_id, stat_filters, base_type)
        if not result:
            pred = self.poeprices.fetch_prediction(item_text)
            if pred and pred.get("pred"):
                return {
                    "pred_exalted": None,
                    "pred_chaos": pred["pred"],
                    "pred_min": pred.get("min"),
                    "pred_max": pred.get("max"),
                    "confidence": pred.get("confidence"),
                    "source": "poeprices",
                }
            return None
        converter = self.get_converter()
        normalized_listings = []
        for amount, currency in result["listings"]:
            norm = converter.normalize_to_all(amount, currency)
            normalized_listings.append(norm)
        chaos_prices = sorted([n["chaos"] for n in normalized_listings if n["chaos"] > 0])
        if not chaos_prices:
            return None
        median = chaos_prices[len(chaos_prices) // 2]
        pct20 = chaos_prices[max(0, len(chaos_prices) // 5)]
        return {
            "listings_chaos": chaos_prices,
            "median_chaos": median,
            "realistic_chaos": pct20,
            "total_listings": result["total_listings"],
            "source": result["source"],
        }

    def get_waystone_price(self, base_type: str, tier: int = 0) -> Optional[Dict]:
        result = self.scout.fetch_waystone_price(base_type, tier)
        if result:
            converter = self.get_converter()
            result["normalized"] = converter.from_exalted(result["current_price_exalted"])
        return result

    def bulk_warm_cache(self):
        """Pre-fetch all major categories so first lookups are instant."""
        self.scout.fetch_reference_currencies()
        self.scout.fetch_all_currency_prices()
        self.scout.fetch_all_unique_prices()
        for cat in ("waystones",):
            self.scout.fetch_items_by_category(cat)