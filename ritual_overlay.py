"""
Ritual overlay module.

Detects the Ritual UI via the "OFFER TRIBUTE TO THE KING" anchor (template match),
then sweeps a calibrated slot grid in the ritual UI for known icons using pHash.
For each matched slot, draws a centered price label via PyQt5.

Hidden items (which span 2x2, 2x3, 2x4, etc.) are ignored - the player cannot
see them so price overlays would not be useful.
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import imagehash
import numpy as np
from PIL import Image

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QBrush
from PyQt5.QtWidgets import QWidget

DATA_DIR = Path(__file__).parent / "data"
ICON_DIR = DATA_DIR / "ritual_icons"
TPL_DIR = DATA_DIR / "ritual_templates"

# poe2scout API base
POE2SCOUT_BASE = "https://poe2scout.com/api"

# Price cache TTL in seconds. poe2scout updates roughly every 2 hours;
# 30 minutes is a fallback for cases where we miss the scheduled refresh.
PRICE_CACHE_TTL = 30 * 60

# Scheduled refresh: HH:01:00 every hour, in a 30-second window.
SCHEDULED_REFRESH_MINUTE = 1
SCHEDULED_REFRESH_WINDOW_SECS = 30

# Template matching threshold (cv2.TM_CCOEFF_NORMED score 0..1).
# Below this we don't consider a match.
ICON_MATCH_THRESHOLD = 0.55

# Slot grid calibration (from user's 1645x1443 screenshot).
# Anchor: FAVOURS header template (favours_header.png).
# Anchor top-left: (600, 5) in the user's screen.
# Grid slot 0,0 origin is at (285, 293) -> delta from anchor = (-315, 288).
# Grid is 10 rows x 12 cols, each cell 105px.
GRID_OFFSET_FROM_ANCHOR = (-315, 288)
SLOT_SIZE = 105
SLOT_COLS = 12
SLOT_ROWS = 10

MATCH_MARGIN_THRESHOLD = 8

# Empty-slot filter: skip slots whose mean brightness is below this.
# Empty grid squares (dark quatrefoil pattern) average ~9-15; real item
# slots with blue background + bright icon average ~22-100.
# Lowered from 22 to 18 to allow multi-tile items (Hollow Mask 2x2,
# Lycosidae 2x4) which have slightly lower mean brightness due to dark
# background areas in the larger region.
EMPTY_SLOT_BRIGHTNESS = 18

# Empty-slot variance filter: skip slots whose grayscale std is below this.
# Empty quatrefoil patterns have low variance (~10); real icons have ~24+.
# Lowered from 22 to 16 for same multi-tile reason.
EMPTY_SLOT_VARIANCE = 16

# Anchor match threshold: minimum score to consider ritual UI present.
ANCHOR_MATCH_THRESHOLD = 0.85


class RitualPriceOverlay(QWidget):
    """Transparent click-through overlay showing prices on ritual items."""

    PO2_GOLD_BRIGHT = QColor(255, 210, 130)
    PO2_BG = QColor(15, 12, 8, 220)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setGeometry(0, 0, 8000, 8000)
        self._hits: List[Tuple[int, int, str, float]] = []  # (cx, cy, name, price)
        self.hide()

    def set_hits(self, hits: List[Tuple[int, int, str, float]]):
        self._hits = hits
        if hits:
            if not self.isVisible():
                self.show()
        self.update()

    def clear(self):
        self._hits = []
        if self.isVisible():
            self.hide()

    def paintEvent(self, event):
        if not self._hits:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont("Serif", 13, QFont.Bold)
        painter.setFont(font)
        fm = QFontMetrics(font)
        for cx, cy, _name, price in self._hits:
            label_text = _format_price(price)
            tw = fm.horizontalAdvance(label_text) + 14
            th = fm.height() + 6
            # Center the label directly on the icon (overlapping it).
            lx = int(cx - tw / 2)
            ly = int(cy - th / 2)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(self.PO2_BG))
            painter.drawRoundedRect(lx, ly, tw, th, 4, 4)
            painter.setPen(QPen(self.PO2_GOLD_BRIGHT, 1))
            painter.drawText(lx + 7, ly + fm.ascent() + 3, label_text)


class RitualDetector:
    """Detects ritual UI, sweeps the slot grid, matches icons by pHash.

    Prices are fetched live from poe2scout and cached in memory for
    PRICE_CACHE_TTL seconds (default 30 min).
    """

    def __init__(self, league: str = "Runes of Aldur"):
        self.league = league

        favours_path = TPL_DIR / "favours_header.png"
        if not favours_path.exists():
            raise FileNotFoundError(f"FAVOURS anchor template missing: {favours_path}")
        self._anchor_template = cv2.imread(str(favours_path))
        # Fallback: also keep the offer button for detecting if ritual UI is open
        self._offer_template = None
        offer_path = TPL_DIR / "offer_button.png"
        if offer_path.exists():
            self._offer_template = cv2.imread(str(offer_path))

        self._icon_data: Dict[str, Dict] = {}
        self._prices: Dict[str, float] = {}
        self._prices_fetched_at: float = 0.0
        self._last_scheduled_hour: int = -1
        self._chaos_per_ex: float = 1.0
        print(f"[ritual] loading icons...", flush=True)
        self._load_icon_hashes()
        print(f"[ritual] {len(self._icon_data)} icons loaded", flush=True)
        self._fetch_prices()

    def _load_icon_hashes(self):
        """Load icons and compute pHash for multi-tile fragment matching.

        """
        for icon_path in ICON_DIR.glob("*.png"):
            stem = icon_path.stem
            icon_pil = Image.open(icon_path).convert("RGB")
            iw, ih = icon_pil.size
            cols = max(1, round(iw / SLOT_SIZE))
            rows = max(1, round(ih / SLOT_SIZE))
            cols = min(cols, 3)
            rows = min(rows, 4)

            target_w = SLOT_SIZE * cols
            target_h = SLOT_SIZE * rows
            fitted = icon_pil.resize((target_w, target_h), Image.LANCZOS)
            hash_w = 128 * cols
            hash_h = 128 * rows
            pil = fitted.resize((hash_w, hash_h), Image.LANCZOS)
            self._icon_data[stem] = {
                "phash": imagehash.phash(pil, hash_size=16),
                "dhash": imagehash.dhash(pil, hash_size=16),
                "whash": imagehash.whash(pil, hash_size=16),
                "cols": cols,
                "rows": rows,
            }

    def _fetch_prices(self):
        """Fetch live prices + ReferenceCurrencies from poe2scout.

        Normalizes all prices to exalts. poe2scout returns CurrentPrice in
        different units (chaos vs exalts) based on size. Threshold: if the
        raw value is >= 10, we treat it as chaos and divide by chaos_per_ex.
        """
        league_enc = urllib.parse.quote(self.league, safe="")
        # First: fetch the chaos_per_ex ratio so we can normalize prices.
        # The endpoint returns a list of {ApiId, RelativePrice} objects.
        try:
            ref_url = f"{POE2SCOUT_BASE}/poe2/Leagues/{league_enc}/ReferenceCurrencies"
            req = urllib.request.Request(ref_url, headers={"User-Agent": "mypoeapp/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                ref = json.loads(resp.read())
            for entry in ref:
                if entry.get("ApiId") == "chaos":
                    self._chaos_per_ex = float(entry.get("RelativePrice", 1.0))
                    break
        except Exception as e:
            print(f"[ritual] reference fetch failed: {e}", flush=True)

        # Now fetch ritual category prices (paginated).
        try:
            fetched = 0
            for page in range(1, 5):
                url = f"{POE2SCOUT_BASE}/poe2/Leagues/{league_enc}/Currencies/ByCategory?Category=ritual&Page={page}"
                req = urllib.request.Request(url, headers={"User-Agent": "mypoeapp/1.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read())
                page_items = data.get("Items", [])
                if not page_items:
                    break
                for item in page_items:
                    api_id = item.get("ApiId")
                    if api_id and item.get("CurrentPrice") is not None:
                        raw = float(item["CurrentPrice"])
                        # Normalize to exalts. poe2scout's web app uses raw value
                        # as-is when small (< ~10), then displays in chaos for larger.
                        # Since we always show in exalts, divide chaos amounts.
                        if raw >= 10 and self._chaos_per_ex > 1:
                            normalized = raw / self._chaos_per_ex
                        else:
                            normalized = raw
                        self._prices[api_id] = normalized
                        fetched += 1

            # Also fetch unique items so prices for things like Igniferis, Birthright
            # Buckle etc. are populated. The Items endpoint returns CurrentPrice in
            # exalts already (these are unique items, priced in ex).
            try:
                items_url = f"{POE2SCOUT_BASE}/poe2/Leagues/{league_enc}/Items?perPage=2000"
                req = urllib.request.Request(items_url, headers={"User-Agent": "mypoeapp/1.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    items = json.loads(resp.read())
                # Build api_id from Name (lowercase, hyphens)
                def name_to_api_id(name: str) -> str:
                    if not name:
                        return ""
                    return name.lower().replace("'", "").replace(" ", "-")
                for it in items:
                    name = it.get("Name") or ""
                    api_id = name_to_api_id(name)
                    if api_id and it.get("CurrentPrice") is not None and api_id not in self._prices:
                        self._prices[api_id] = float(it["CurrentPrice"])
                        fetched += 1
            except Exception as e:
                print(f"[ritual] items fetch failed: {e}", flush=True)

            self._prices_fetched_at = time.time()
            print(f"[ritual] fetched {fetched} prices (chaos/ex={self._chaos_per_ex:.2f})", flush=True)
        except Exception as e:
            print(f"[ritual] price fetch failed: {e}", flush=True)

    def refresh_prices_if_stale(self):
        """Refresh prices if cache is older than PRICE_CACHE_TTL."""
        if time.time() - self._prices_fetched_at > PRICE_CACHE_TTL:
            self._fetch_prices()

    def refresh_prices_if_scheduled(self):
        """Refresh prices if we're within the scheduled HH:01:00 window
        and we haven't already refreshed this hour. Falls back to TTL check
        so we still update if the scheduler misses (e.g., app was idle).
        """
        now = datetime.now()
        # Scheduled window check
        if (now.minute == SCHEDULED_REFRESH_MINUTE
                and now.second < SCHEDULED_REFRESH_WINDOW_SECS
                and now.hour != self._last_scheduled_hour):
            self._last_scheduled_hour = now.hour
            print(f"[ritual] scheduled refresh at {now.strftime('%H:%M:%S')}", flush=True)
            self._fetch_prices()
            return
        # TTL fallback
        if time.time() - self._prices_fetched_at > PRICE_CACHE_TTL:
            self._fetch_prices()

    def find_anchor(self, screen: np.ndarray) -> Optional[Tuple[int, int]]:
        """Find the ritual UI and return the grid (0,0) top-left pixel coords.

        Uses the offer button as the primary anchor (always at the bottom of
        the ritual), then derives the grid origin from a known offset.
        Falls back to FAVOURS header if offer button isn't found.
        """
        if screen is None:
            return None
        ow, oh = screen.shape[1], screen.shape[0]
        # Try offer button first: at the bottom of the ritual grid
        if self._offer_template is not None:
            if oh >= self._offer_template.shape[0] and ow >= self._offer_template.shape[1]:
                result = cv2.matchTemplate(screen, self._offer_template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(result)
                if max_val >= ANCHOR_MATCH_THRESHOLD:
                    # Offer button found. The grid is above it, offset
                    # proportionally to screen width. Original calibration:
                    # screen 1645w, offer at x=223, grid at x=285 → grid_x = offer_x + 62
                    # screen 1645w, offer at y=1473, grid at y=293 → grid_y = offer_y - 1180
                    offer_x, offer_y = max_loc
                    return (offer_x + 62, offer_y - 1180)
        # Fallback: FAVOURS header
        if self._anchor_template is not None:
            if oh >= self._anchor_template.shape[0] and ow >= self._anchor_template.shape[1]:
                result = cv2.matchTemplate(screen, self._anchor_template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(result)
                if max_val >= ANCHOR_MATCH_THRESHOLD:
                    return (max_loc[0] - 315, max_loc[1] + 288)
        return None

    def match_region(self, region_img: np.ndarray, cols: int, rows: int) -> Optional[Tuple[str, float, int]]:
        """Label a multi-tile region by its shape.

        Since we have limited multi-tile icons (one per shape), we label
        occupied regions by (cols x rows). As the database grows, we can
        switch to fragment-based pHash voting.

        Returns (api_id, price, margin) or None.
        """
        if region_img is None:
            return None
        target_w = SLOT_SIZE * cols
        target_h = SLOT_SIZE * rows
        if region_img.shape[0] < target_h or region_img.shape[1] < target_w:
            return None
        region = region_img[:target_h, :target_w]
        # Check if region matches any icon of this shape
        best_name = None
        best_score = 9999
        second_score = 9999
        for name, data in self._icon_data.items():
            if data["cols"] != cols or data["rows"] != rows:
                continue
            # pHash the full region against the icon (works for all shapes)
            try:
                hash_w = 128 * cols
                hash_h = 128 * rows
                pil = Image.fromarray(cv2.cvtColor(region, cv2.COLOR_BGR2RGB)).resize((hash_w, hash_h), Image.LANCZOS)
            except Exception:
                continue
            phash = imagehash.phash(pil, hash_size=16)
            dhash = imagehash.dhash(pil, hash_size=16)
            whash = imagehash.whash(pil, hash_size=16)
            score = (phash - data["phash"]) + (dhash - data["dhash"]) + (whash - data["whash"])
            if score < best_score:
                second_score = best_score
                best_score = score
                best_name = name
            elif score < second_score:
                second_score = score

        if best_name is None:
            return None
        # Margin + absolute quality check for ALL shapes
        if second_score < 9999:
            if best_score > 300:
                return None  # too dissimilar
            margin = second_score - best_score
            if margin < MATCH_MARGIN_THRESHOLD:
                return None
        else:
            return None
        api_id = best_name.replace("unique_", "")
        price = self._prices.get(api_id, 0.0)
        return api_id, price, 1

    def find_all_items(self, screen: np.ndarray, anchor: Tuple[int, int]) -> List[Tuple[int, int, int, int, str, float]]:
        """For each icon in the database, pHash-match against the
        pre-defined slot grid in the ritual area.

        Multi-tile items (2x1, 2x2, 2x4) are matched at their natural
        shape. NMS suppresses overlapping smaller matches.
        """
        if anchor is None:
            return []
        ax, ay = anchor  # anchor is now the grid (0,0) origin

        candidates = []
        # Only include shapes that have at least 2 icons in the database.
        # Shapes with 1 icon produce false positive floods.
        enabled_shapes = []
        for sc, sr in [(1, 1), (2, 1), (1, 2), (2, 2), (2, 3), (2, 4), (1, 3), (1, 4)]:
            count = sum(1 for d in self._icon_data.values() if d["cols"] == sc and d["rows"] == sr)
            if count >= 2:  # all shapes now have enough competition
                enabled_shapes.append((sc, sr))
        for row in range(SLOT_ROWS):
            for col in range(SLOT_COLS):
                for shape_cols, shape_rows in enabled_shapes:
                    sx = ax + col * SLOT_SIZE
                    sy = ay + row * SLOT_SIZE
                    w = SLOT_SIZE * shape_cols
                    h = SLOT_SIZE * shape_rows
                    if sx + w > screen.shape[1] or sy + h > screen.shape[0]:
                        continue
                    region = screen[sy:sy+h, sx:sx+w]
                    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
                    if float(gray.mean()) < 25:
                        continue
                    if float(gray.std()) < 15:
                        continue
                    match = self.match_region(region, shape_cols, shape_rows)
                    if match is None:
                        continue
                    api_id, price, score = match
                    candidates.append((row, col, shape_cols, shape_rows, api_id, price, score))

        candidates.sort(key=lambda c: (-(c[2] * c[3]), -c[6]))
        consumed = set()
        hits: List[Tuple[int, int, int, int, str, float]] = []
        for row, col, sc, sr, api_id, price, score in candidates:
            slots = set()
            for r in range(row, row + sr):
                for c in range(col, col + sc):
                    slots.add((r, c))
            if slots & consumed:
                continue
            consumed |= slots
            cx = ax + (col + sc / 2) * SLOT_SIZE
            cy = ay + (row + sr / 2) * SLOT_SIZE
            hits.append((row, col, int(cx), int(cy), api_id, price))
        return hits

    def scan_slots(self, screen: np.ndarray, anchor: Tuple[int, int]) -> List[Tuple[int, int, int, int, str, float]]:
        """Compatibility shim - delegates to find_all_items."""
        return self.find_all_items(screen, anchor)


class RitualWatcher:
    """Periodically captures the screen, detects ritual UI, and updates the overlay.

    Stability: each match slot has a "confidence counter" that increments
    on consecutive matches and resets on misses. Only slots with count >=
    STABILITY_THRESHOLD are shown. When a slot stops matching, it lingers
    for LINGER_FRAMES more frames before disappearing. This stops the
    "bouncing" caused by pHash scores hovering around the threshold.
    """

    STABILITY_THRESHOLD = 2   # require N consecutive matches before showing
    LINGER_FRAMES = 3         # keep showing for N frames after last match

    def __init__(self, overlay: RitualPriceOverlay, detector: RitualDetector,
                 refresh_seconds: float = 1.0):
        self.overlay = overlay
        self.detector = detector
        self.refresh_seconds = refresh_seconds
        self._timer: Optional[QTimer] = None
        self._screen_capture = _build_screen_capture()
        self._last_present = False
        # Stability tracking: key = (row, col), value = (match_tuple, hit_count, miss_count)
        self._stable: Dict[Tuple[int, int], Tuple[Tuple, int, int]] = {}

    def start(self):
        if self._timer is not None:
            return
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(int(self.refresh_seconds * 1000))
        self._tick()

    def stop(self):
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self.overlay.clear()
        self._stable.clear()

    def _tick(self):
        # Refresh prices if scheduled (HH:01:00) or TTL exceeded.
        self.detector.refresh_prices_if_scheduled()

        try:
            screen = self._screen_capture()
        except Exception as e:
            print(f"[ritual] capture fail: {e}", flush=True)
            return
        anchor = self.detector.find_anchor(screen)
        if anchor is None:
            if self._last_present:
                self.overlay.clear()
                self._last_present = False
            return

        raw_hits = self.detector.scan_slots(screen, anchor)
        # Build map of current frame's matches by (row, col)
        current: Dict[Tuple[int, int], Tuple] = {}
        for row, col, cx, cy, name, price in raw_hits:
            current[(row, col)] = (cx, cy, name, price)

        # Update stability counters
        new_stable: Dict[Tuple[int, int], Tuple[Tuple, int, int]] = {}
        for key, match in current.items():
            old = self._stable.get(key)
            if old and old[0] == match:
                # Same match as before - increment hit count
                new_stable[key] = (match, old[1] + 1, 0)
            else:
                # New or changed match - start counter
                new_stable[key] = (match, 1, 0)
        # Carry over old matches that aren't in current (might be lingering)
        for key, (match, hit_count, miss_count) in self._stable.items():
            if key not in current:
                new_miss = miss_count + 1
                if new_miss <= self.LINGER_FRAMES:
                    new_stable[key] = (match, hit_count, new_miss)

        self._stable = new_stable

        # Only display matches that hit the stability threshold
        stable_hits = []
        for key, (match, hit_count, _) in self._stable.items():
            if hit_count >= self.STABILITY_THRESHOLD:
                stable_hits.append(match)

        self.overlay.set_hits(stable_hits)
        self._last_present = True
        if stable_hits:
            summary = ", ".join(f"{n}={p:.1f}x" for _, _, n, p in stable_hits)
            print(f"[ritual] {len(stable_hits)} stable hits: {summary}", flush=True)


def _format_price(price: float) -> str:
    if price >= 1000:
        return f"{price/1000:.1f}kx"
    if price >= 10:
        return f"{price:.0f}x"
    if price >= 1:
        return f"{price:.1f}x"
    if price >= 0.01:
        return f"{price:.2f}x"
    return f"{price:.3f}x"


def _build_screen_capture():
    try:
        import mss
        sct = mss.mss()
        def capture():
            monitor = sct.monitors[1]
            img = np.array(sct.grab(monitor))
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        return capture
    except ImportError:
        from PIL import ImageGrab
        def capture():
            img = ImageGrab.grab()
            arr = np.array(img)
            return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        return capture