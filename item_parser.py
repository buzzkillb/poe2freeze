"""
Parse PoE2 clipboard item text into structured fields.
"""
import re
from typing import Dict, List, Optional, Tuple

NUM_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)")
_MOD_HAS_IMPLICIT_TAG = re.compile(r"\(implicit\)\s*$", re.IGNORECASE)


def _mod_has_implicit_tag(s: str) -> bool:
    return _MOD_HAS_IMPLICIT_TAG.search(s) is not None


def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def extract_numbers(s: str) -> List[float]:
    return [float(m.group(1)) for m in NUM_RE.finditer(s)]


def parse_item(text: str) -> Dict:
    """
    Parse PoE2 clipboard item text into structured fields.
    Returns dict with: rarity, base, name, item_class, ilvl, mods, quality,
    gem_level, sockets, corrupted, identified, stack_size, properties.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    result = {
        "rarity": "",
        "base": "",
        "name": "",
        "item_class": "",
        "ilvl": 0,
        "quality": 0,
        "gem_level": 0,
        "sockets": 0,
        "links": 0,
        "corrupted": False,
        "identified": True,
        "stack_size": 1,
        "rarity_tag": "normal",
        "mods": [],
        "implicit_mods": [],
        "explicit_mods": [],
        "rune_mods": [],
        "desecrated_mods": [],
        "properties": {},
        "raw_lines": lines,
    }
    if not lines:
        return result
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("Item Class:"):
            result["item_class"] = line[len("Item Class:"):].strip()
        elif line.startswith("Rarity:"):
            rarity_text = line[len("Rarity:"):].strip().upper()
            result["rarity"] = rarity_text
            result["rarity_tag"] = _rarity_to_tag(rarity_text)
        elif line.startswith("Item Level:"):
            try:
                result["ilvl"] = int(line[len("Item Level:"):].strip())
            except ValueError:
                pass
        elif line.startswith("Stack Size:"):
            nums = extract_numbers(line)
            if nums:
                result["stack_size"] = int(nums[0])
        elif line.startswith("Quality:"):
            nums = extract_numbers(line)
            if nums:
                result["quality"] = int(nums[0])
        elif line.startswith("Level:"):
            nums = extract_numbers(line)
            if nums:
                result["gem_level"] = int(nums[0])
        elif line.startswith("Sockets:"):
            nums = extract_numbers(line)
            if nums:
                result["sockets"] = int(nums[0])
        elif "Corrupted" in line and line.strip() == "Corrupted":
            result["corrupted"] = True
        elif "Unidentified" in line:
            result["identified"] = False
        i += 1
    base_candidates = []
    found_rarity = False
    for idx, line in enumerate(lines):
        s = line.strip()
        if s.startswith("Rarity:"):
            found_rarity = True
            continue
        if not found_rarity or not s:
            continue
        if s.startswith("--------"):
            break
        if s.startswith("Item Class:") or s.startswith("Item Level:"):
            continue
        base_candidates.append(s)
    if base_candidates:
        first = base_candidates[0]
        if "you cannot use" in first.lower() or "stats will be ignored" in first.lower():
            result["base"] = first
            result["name"] = ""
        elif len(base_candidates) >= 2 and result["rarity"] in ("RARE", "UNIQUE"):
            result["name"] = base_candidates[0]
            result["base"] = base_candidates[1]
        elif len(base_candidates) >= 3 and result["rarity"] == "RARE":
            result["name"] = base_candidates[0]
            result["base"] = base_candidates[1]
        else:
            result["base"] = base_candidates[0]
            if result["rarity"] == "UNIQUE" and base_candidates:
                result["name"] = base_candidates[0]
    mod_sections = _extract_mod_sections(lines)
    result["implicit_mods"] = mod_sections.get("implicit", [])
    result["explicit_mods"] = mod_sections.get("explicit", [])
    result["rune_mods"] = mod_sections.get("rune", [])
    result["desecrated_mods"] = mod_sections.get("desecrated", [])
    result["mods"] = (
        result["implicit_mods"]
        + result["explicit_mods"]
        + result["rune_mods"]
        + result["desecrated_mods"]
    )
    return result


def _rarity_to_tag(rarity: str) -> str:
    mapping = {
        "NORMAL": "normal",
        "MAGIC": "magic",
        "RARE": "rare",
        "UNIQUE": "unique",
        "GEM": "gem",
        "CURRENCY": "currency",
        "DIVINATION CARD": "divcard",
        "QUEST": "quest",
    }
    return mapping.get(rarity, rarity.lower())


def _extract_mod_sections(lines: List[str]) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {
        "implicit": [],
        "explicit": [],
        "rune": [],
        "desecrated": [],
    }
    current = None
    in_section = False
    saw_separator = 0
    last_header = ""
    for line in lines:
        s = line.strip()
        if s == "--------":
            saw_separator += 1
            current = None
            in_section = True
            last_header = ""
            continue
        if not in_section or not s:
            continue
        if s.startswith("Item Class:") or s.startswith("Rarity:"):
            continue
        if s.startswith("Item Level:") or s.startswith("Requires"):
            continue
        if s.startswith("Stack Size:") or s.startswith("Quality:") or s.startswith("Level:"):
            continue
        if s.startswith("Sockets:") or s == "Corrupted":
            continue
        if s.startswith("Augmented"):
            continue
        if s.startswith("Unidentified"):
            continue
        if s.startswith("Item Level:") or s.startswith("Map Tier:"):
            continue
        if s.startswith("Waystone Tier:") or s.startswith("Tier:"):
            continue
        if s.startswith("Monster Level:") or s.startswith("Talisman Tier:"):
            continue
        if s.startswith("Area Level:") or s.startswith("Corpse Level:"):
            continue
        if s.startswith("Boots:") or s.startswith("Gloves:") or s.startswith("Helmet:"):
            continue
        if s.startswith("Body Armour:") or s.startswith("Shield:") or s.startswith("Quiver:"):
            continue
        if s.startswith("Armour:") or s.startswith("Evasion Rating:"):
            continue
        if s.startswith("Energy Shield:") or s.startswith("Ward:"):
            continue
        if s.startswith("Spirit:"):
            continue
        if s.startswith("Attacks per Second:") or s.startswith("Critical Strike Chance:"):
            continue
        if s.startswith("Physical Damage:") or s.startswith("Elemental Damage:"):
            continue
        if s.startswith("Chaos Damage:"):
            continue
        if s.startswith("Reload Time:"):
            continue
        if s.startswith("Block:"):
            continue
        if s.startswith("Radius:") or s.startswith("Limit:"):
            continue
        if s.startswith("Stored Experiences:"):
            continue
        if s.startswith("Offering:"):
            continue
        if "Right click to drink" in s or "Right-click to drink" in s:
            continue
        if "Right click to remove" in s or "Right-click to remove" in s:
            continue
        if "Shift click to unstack" in s:
            continue
        if s.startswith("Place into an "):
            continue
        if s.startswith("Acquisition:"):
            continue
        if s.startswith("Sell Price:"):
            continue
        if s.startswith("Travel to the "):
            continue
        if s.startswith("Can be used in"):
            continue
        if s.startswith("Waystones can only be used once"):
            continue
        if s.startswith("Maps can only be used once"):
            continue
        if s.startswith("Flavour Text:"):
            continue
        if "Note:" in s and not s.startswith("+") and not s.startswith("-"):
            continue
        if s.startswith("You must be level"):
            continue
        if s.startswith("Requires Level"):
            continue
        if s.startswith("Requires "):
            continue
        if s.startswith("{") and s.endswith("}"):
            last_header = s
            continue
        if s.startswith("[") and s.endswith("]"):
            continue
        if s.startswith("Preview:"):
            break
        if current is None and saw_separator >= 2:
            if _looks_like_implicit(s, last_header):
                current = "implicit"
            else:
                current = "explicit"
        if current is None:
            current = "explicit"
        if s.startswith("(augmented)") or s.startswith("(rune)"):
            tag = "rune"
            s = s.split(")")[0].strip() if ")" in s else s
            sections[tag].append(s)
        elif s.startswith("(desecrated)"):
            tag = "desecrated"
            s = s.split(")")[0].strip() if ")" in s else s
            sections[tag].append(s)
        else:
            sections[current].append(s)
    sections["implicit"] = _join_multiline_implicit_mods(sections["implicit"])
    return sections


_IMPLICIT_CONTINUATION_TAIL = re.compile(
    r"\s+(to a Map|to your Maps|in your Maps|in Map|in Area)$", re.IGNORECASE
)


def _join_multiline_implicit_mods(lines: List[str]) -> List[str]:
    """Join multi-line implicit mods (tablets) into single strings.

    Tablet implicits render as two lines, e.g.:
        Adds Irradiated to a Map
        10 uses remaining
    match_mod expects the joined form with a literal '\\n' between them.
    We join a tail-ending line with its immediate numeric/completion
    follow-up. A pending line flushes as soon as we encounter a non-tail
    line (single-line implicit mods never tail-match).
    """
    if len(lines) < 2:
        return lines
    out: List[str] = []
    pending: Optional[str] = None
    for s in lines:
        if pending is not None:
            out.append(pending + "\n" + s)
            pending = None
            continue
        if _IMPLICIT_CONTINUATION_TAIL.search(s):
            pending = s
            continue
        out.append(s)
    if pending is not None:
        out.append(pending)
    return out


def _looks_like_implicit(mod_line: str, last_header: str = "") -> bool:
    """Detect whether a section is implicit.

    Two signals:
    1. The section header (e.g. "{ Implicit Modifier }") explicitly
       names the section as implicit. Tablets and other PoE2 items use
       this convention.
    2. The mod text itself ends with "(implicit)" — used by weapons,
       armour, jewellery, etc.
    """
    header_lower = (last_header or "").lower()
    if "implicit" in header_lower and "explicit" not in header_lower:
        return True
    return _mod_has_implicit_tag(mod_line)