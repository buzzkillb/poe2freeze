"""
Local PoE2 data from poe2db.tw data dumps (GitHub: LocalIdentity/poe2-data).
Used for: authoritative base type → item class mapping, currency IDs,
uniques list, item metadata. No network calls after initial load.
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


DATA_DIR = Path(__file__).parent / "data" / "poe2db"


_base_types: Optional[Dict] = None
_item_classes: Optional[Dict] = None
_currency_exchange: Optional[List] = None
_currency_items: Optional[Dict] = None
_skill_gems: Optional[Dict] = None
_base_type_index: Optional[Dict] = None


def _load_json(filename: str):
    path = DATA_DIR / filename
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _ensure_loaded():
    global _base_types, _item_classes, _currency_exchange, _currency_items
    global _skill_gems, _base_type_index
    if _base_types is not None:
        return
    _item_classes = {
        c["Id"]: c for c in (_load_json("itemclasses.json") or [])
        if not (c.get("Id") or "").startswith("DONOTUSE")
    }
    _base_types = _load_json("baseitemtypes.json") or []
    _currency_exchange = _load_json("currencyexchange.json") or []
    _currency_items = _load_json("currencyitems.json") or []
    _skill_gems = [
        g for g in (_load_json("skillgems.json") or [])
        if "Unknown" not in str((g.get("BaseItemTypesKey") or {}).get("Id", ""))
    ]
    _base_type_index = {}
    for entry in _base_types:
        name = entry.get("Name", "")
        if not name:
            continue
        key = name.lower()
        _base_type_index[key] = entry
        clean_key = re.sub(r"[^a-z0-9]", "", name.lower())
        if clean_key and clean_key not in _base_type_index:
            _base_type_index[clean_key] = entry


def get_item_class_name(class_id: str) -> str:
    _ensure_loaded()
    cls = _item_classes.get(class_id, {})
    return cls.get("Name", class_id)


def get_all_item_classes() -> List[Dict]:
    _ensure_loaded()
    return list(_item_classes.values())


def find_base_type_by_name(name: str) -> Optional[Dict]:
    _ensure_loaded()
    if not name:
        return None
    key = name.lower().strip()
    if key in _base_type_index:
        return _base_type_index[key]
    clean_key = re.sub(r"[^a-z0-9]", "", key)
    if clean_key in _base_type_index:
        return _base_type_index[clean_key]
    candidates = []
    for entry in _base_types:
        entry_name = (entry.get("Name") or "").lower()
        if not entry_name:
            continue
        if entry_name == key:
            return entry
        if entry_name in key and len(entry_name) >= len(key) - 3:
            candidates.append((len(entry_name), entry))
        if key in entry_name and len(key) >= len(entry_name) - 3:
            candidates.append((len(key) - len(entry_name), entry))
    if candidates:
        candidates.sort(key=lambda x: (abs(x[0]), x[0]))
        return candidates[0][1]
    return None


def get_base_type_trade_id(name: str) -> str:
    """
    Map a PoE2 item base type name to its trade2 category ID.
    Uses the poe2db data to look up the actual ItemClass.
    """
    entry = find_base_type_by_name(name)
    if not entry:
        return ""
    cls = entry.get("ItemClassesKey", {})
    class_id = cls.get("Id", "")
    return _class_id_to_trade_id(class_id)


_CLASS_TO_TRADE_ID = {
    "Amulet": "accessory.amulet",
    "Ring": "accessory.ring",
    "Belt": "accessory.belt",
    "Body Armour": "armour.chest",
    "Boots": "armour.boots",
    "Gloves": "armour.gloves",
    "Helmet": "armour.helmet",
    "Shield": "armour.shield",
    "Quiver": "armour.quiver",
    "Focus": "armour.focus",
    "Buckler": "armour.buckler",
    "Bow": "weapon.bow",
    "Crossbow": "weapon.crossbow",
    "Claw": "weapon.claw",
    "Dagger": "weapon.dagger",
    "One Hand Sword": "weapon.onesword",
    "One Hand Axe": "weapon.oneaxe",
    "One Hand Mace": "weapon.onemace",
    "Two Hand Sword": "weapon.twosword",
    "Two Hand Axe": "weapon.twoaxe",
    "Two Hand Mace": "weapon.twomace",
    "Wand": "weapon.wand",
    "Staff": "weapon.staff",
    "Spear": "weapon.spear",
    "Flail": "weapon.flail",
    "Sceptre": "weapon.sceptre",
    "TrapTool": "weapon.trap",
    "Talisman": "weapon.talisman",
    "LifeFlask": "flask.life",
    "ManaFlask": "flask.mana",
    "UtilityFlask": "flask.charm",
    "Jewel": "jewel",
    "AbyssJewel": "jewel.abyss",
    "Active Skill Gem": "gem.activegem",
    "Support Skill Gem": "gem.supportgem",
    "Map": "map.waystone",
    "MapFragment": "map.fragment",
    "TowerAugmentation": "map.tablet",
    "MiscMapItem": "map.misc",
    "PantheonSoul": "soulcore.pantheon",
    "DivinationCard": "divcard",
    "Currency": "currency",
    "StackableCurrency": "currency",
    "SoulCore": "soulcore",
    "Rune": "rune",
}


def _class_id_to_trade_id(class_id: str) -> str:
    return _CLASS_TO_TRADE_ID.get(class_id, "")


def get_currency_items() -> List[Dict]:
    _ensure_loaded()
    return _currency_items


def get_currency_exchange_entries() -> List[Dict]:
    _ensure_loaded()
    return _currency_exchange


def get_skill_gems() -> List[Dict]:
    _ensure_loaded()
    return _skill_gems


def find_currency_by_name(name: str) -> Optional[Dict]:
    _ensure_loaded()
    name_lower = name.lower().strip()
    # Build id→name index from base_types
    name_by_id = {}
    for b in _base_types:
        bid = (b.get("BaseItemTypesKey") or {}).get("Id") or b.get("Id", "")
        bname = b.get("Name", "")
        if bid and bname:
            name_by_id[bid] = bname
    for entry in _currency_items:
        meta_id = (entry.get("BaseItemTypesKey") or {}).get("Id", "")
        cname = name_by_id.get(meta_id, "")
        if cname.lower() == name_lower:
            return entry
    return None


def find_unique_by_name(name: str) -> Optional[Dict]:
    _ensure_loaded()
    name_lower = name.lower().strip()
    for entry in _base_types:
        if (entry.get("Name") or "").lower() == name_lower:
            site_vis = entry.get("SiteVisibility", 0)
            if site_vis >= 1:
                return entry
    return None


def get_all_currency_names() -> List[str]:
    _ensure_loaded()
    name_by_id = {}
    for b in _base_types:
        bid = (b.get("BaseItemTypesKey") or {}).get("Id") or b.get("Id", "")
        bname = b.get("Name", "")
        if bid and bname:
            name_by_id[bid] = bname
    result = []
    for e in _currency_items:
        meta_id = (e.get("BaseItemTypesKey") or {}).get("Id", "")
        cname = name_by_id.get(meta_id, "")
        if cname:
            result.append(cname)
    return result


def get_all_unique_names() -> List[str]:
    _ensure_loaded()
    return [e.get("Name") for e in _base_types
            if e.get("Name") and e.get("SiteVisibility", 0) >= 1]