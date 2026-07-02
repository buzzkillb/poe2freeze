import urllib.request, json, os, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).parent
ICON_DB_DIR = ROOT / "data" / "unique_icons"
ICON_DB_DIR.mkdir(exist_ok=True)

POE2SCOUT_BASE = "https://poe2scout.com/api"
LEAGUE = "Runes of Aldur"
LEAGUE_ENC = "Runes%20of%20Aldur"

# All categories from poe2scout
CURRENCY_CATEGORIES = [
    "currency", "runes", "essences", "fragments", "ultimatum", "breach",
    "expedition", "delirium", "uncutgems", "lineagesupportgems",
    "incursion", "abyss", "vaultkeys", "verisium", "vaal", "idol",
    "waystones", "maps", "tablets"
]

def fetch_items_by_category(category: str, endpoint: str = "Currencies") -> list:
    all_items = []
    for page in range(1, 50):
        url = f"{POE2SCOUT_BASE}/poe2/Leagues/{LEAGUE_ENC}/{endpoint}/ByCategory?Category={category}&Page={page}"
        try:
            r = urllib.request.Request(url, headers={"User-Agent": "mypoeapp/1.0"})
            with urllib.request.urlopen(r, timeout=15) as resp:
                data = json.loads(resp.read())
                items = data.get("Items", [])
                if not items:
                    break
                all_items.extend(items)
                total_pages = data.get("Pages", 1)
                if page >= total_pages:
                    break
        except Exception as e:
            print(f"  [{category} p{page}] ERROR: {e}")
            break
        time.sleep(0.25)
    return all_items


def fetch_all_items() -> list:
    """Fetch from /Items first (uniques), then all currency categories."""
    all_items = []

    # Core /Items (uniques etc)
    print("Fetching /Items...")
    url = f"{POE2SCOUT_BASE}/poe2/Leagues/{LEAGUE_ENC}/Items?perPage=2000"
    try:
        r = urllib.request.Request(url, headers={"User-Agent": "mypoeapp/1.0"})
        with urllib.request.urlopen(r, timeout=30) as resp:
            data = json.loads(resp.read())
        print(f"  /Items returned {len(data)} items")
        for item in data:
            item["_category"] = "items"
        all_items.extend(data)
    except Exception as e:
        print(f"  /Items ERROR: {e}")

    # Currency/category items
    for cat in CURRENCY_CATEGORIES:
        print(f"Fetching {cat}...", flush=True)
        items = fetch_items_by_category(cat, "Currencies")
        print(f"  Got {len(items)} items")
        for item in items:
            item["_category"] = cat
        all_items.extend(items)

    return all_items


def download_icon(url: str, dest_path: Path) -> bool:
    if dest_path.exists():
        return True
    try:
        r = urllib.request.Request(url, headers={"User-Agent": "mypoeapp/1.0"})
        with urllib.request.urlopen(r, timeout=15) as resp:
            data = resp.read()
        dest_path.write_bytes(data)
        return True
    except Exception as e:
        return False


def build_full_icon_database():
    icons_dir = ICON_DB_DIR / "icons"
    icons_dir.mkdir(exist_ok=True)
    db_path = ICON_DB_DIR / "database.json"

    # Load existing
    existing = {}
    if db_path.exists():
        try:
            existing_list = json.loads(db_path.read_text()).get("items", [])
            # Strip absolute iconPath from old entries (migration)
            for item in existing_list:
                item.pop("iconPath", None)
            existing = {item["apiId"]: item for item in existing_list if item.get("apiId")}
        except:
            pass

    print("Fetching all items from poe2scout...")
    all_items = fetch_all_items()
    print(f"Total items fetched: {len(all_items)}")

    # Build items list
    items_to_download = []
    seen_ids = set(existing.keys())

    for item in all_items:
        name = item.get("Name") or item.get("Text") or ""
        if not name:
            continue
        icon_url = item.get("IconUrl", "")
        api_id = item.get("ApiId", "") or name.lower().replace(" ", "-").replace("'", "")
        category = item.get("_category", "unknown")

        if api_id in seen_ids:
            continue
        seen_ids.add(api_id)

        if not icon_url:
            continue

        fname = icon_url.split("/")[-1]
        if "?" in fname:
            fname = fname.split("?")[0]
        if not fname.endswith((".png", ".webp")):
            fname = fname + ".png"

        local_path = icons_dir / fname
        items_to_download.append({
            "apiId": api_id,
            "name": name,
            "category": category,
            "iconUrl": icon_url,
            "iconLocal": f"icons/{fname}",
            "currentPrice": item.get("CurrentPrice"),
            "currentQuantity": item.get("CurrentQuantity"),
        })

    print(f"New items to download: {len(items_to_download)}")
    if not items_to_download:
        print("Nothing new to download.")
        return

    # Download
    print("Downloading icons...")
    downloaded = 0
    failed = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {}
        for item in items_to_download:
            dest = icons_dir / Path(item["iconLocal"]).name
            fut = ex.submit(download_icon, item["iconUrl"], dest)
            futures[fut] = item["name"]
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                if fut.result():
                    downloaded += 1
                else:
                    failed.append(name)
            except Exception as e:
                failed.append(f"{name}: {e}")

    print(f"Downloaded: {downloaded}, Failed: {len(failed)}")

    # Merge with existing and save
    all_db_items = list(existing.values()) + items_to_download
    db_data = {"items": all_db_items}
    db_path.write_text(json.dumps(db_data, indent=2))
    print(f"Saved {len(all_db_items)} items to {db_path}")


if __name__ == "__main__":
    build_full_icon_database()