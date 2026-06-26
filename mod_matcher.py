"""
Match PoE2 item mods against EE2's mod_translations table.
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).parent
TRANSLATIONS_FILE = ROOT / "data" / "mod_translations.json"

_cache = None


def load_translations() -> Dict:
    global _cache
    if _cache is None:
        with open(TRANSLATIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        compiled = {}
        for key, entry in data.items():
            regex = entry.get("regex")
            if regex:
                entry["compiled"] = re.compile(regex)
            compiled[key] = entry
        _cache = compiled
    return _cache


def match_mod(mod_text: str) -> Optional[Dict]:
    """
    Try to match a mod text against the translation table.
    Returns dict with trade_id, trade_type, ref, value (the number from the mod), better.
    """
    translations = load_translations()
    clean = re.sub(r"\s*\(augmented\)\s*", "", mod_text)
    clean = re.sub(r"\s*\(rune\)\s*", "", clean)
    clean = re.sub(r"\s*\(desecrated\)\s*", "", clean)
    clean = re.sub(r"\s*\(implicit\)\s*", "", clean)
    clean = clean.strip()
    candidates = [clean]
    if "(" in clean and ")" in clean:
        first_paren = clean.find("(")
        before = clean[:first_paren].rstrip()
        num_match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*$", before)
        if num_match:
            outer_value = num_match.group(1)
            no_paren = re.sub(r"\s*\([^)]+\)", "", clean, count=1).strip()
            no_paren = re.sub(r"\s+", " ", no_paren)
            if no_paren and no_paren != clean:
                candidates.insert(0, no_paren)
        no_paren_all = re.sub(r"\s*\([^)]+\)", "", clean).strip()
        no_paren_all = re.sub(r"\s+", " ", no_paren_all)
        if no_paren_all and no_paren_all != clean and no_paren_all not in candidates:
            candidates.append(no_paren_all)
    for c in candidates:
        for key, entry in translations.items():
            if key.startswith("__ref__"):
                continue
            compiled = entry.get("compiled")
            if not compiled:
                continue
            m = compiled.match(c)
            if m:
                value = None
                if m.groups():
                    try:
                        value = float(m.group(1))
                    except (ValueError, IndexError):
                        pass
                return {
                    "trade_id": entry["trade_id"],
                    "trade_type": entry["trade_type"],
                    "ref": entry["ref"],
                    "value": value,
                    "better": entry["better"],
                    "alt_ids": entry.get("alt_ids", []),
                }
    return None


def match_mods(mods: List[str]) -> List[Dict]:
    """
    Match a list of mod texts. Returns list of matched dicts (skipping unmatched).
    """
    results = []
    for mod in mods:
        m = match_mod(mod)
        if m:
            results.append(m)
    return results


def build_query_stat_filter(matched: Dict, priority_min: int = 0) -> Optional[Dict]:
    """
    Convert a matched mod into a trade2 stat filter object.
    """
    if matched["value"] is None:
        return None
    value = matched["value"]
    better = matched["better"]
    if better > 0:
        return {
            "id": matched["trade_id"],
            "value": {"min": value},
            "disabled": False,
        }
    elif better < 0:
        return {
            "id": matched["trade_id"],
            "value": {"max": value},
            "disabled": False,
        }
    else:
        return {
            "id": matched["trade_id"],
            "value": {"min": value, "max": value},
            "disabled": False,
        }