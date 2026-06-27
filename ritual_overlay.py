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
# Assumption: poe2scout pushes a full update at the top of each hour,
# so refreshing 1 minute after catches both HH:00 and HH:02 cycles.
SCHEDULED_REFRESH_MINUTE = 1
SCHEDULED_REFRESH_WINDOW_SECS = 30

# Slot grid calibration (from user's 1502x1440 screenshot).
# These are pixel offsets relative to the offer-button anchor's top-left corner.
# Anchor (offer_button.png) top-left is at (200, 1410).
# Grid slot 0,0 origin is at (157, 337) -> delta from anchor = (-43, -1073).
GRID_OFFSET_FROM_ANCHOR = (-43, -1073)
SLOT_SIZE = 105
SLOT_COLS = 11
SLOT_ROWS = 8

# pHash match threshold: minimum margin (top1 - top2) to accept a slot match.
# Multi-tile matches (2x1, 2x2 etc) need a bigger margin because they have
# more pixels of "stuff" that could randomly match.
MATCH_MARGIN_THRESHOLD = 8
MATCH_MARGIN_THRESHOLD_MULTI = 18

# Empty-slot filter: skip slots whose mean brightness is below this.
# Empty grid squares (dark quatrefoil pattern) average ~9-15; real item
# slots with blue background + bright icon average ~22-100.
EMPTY_SLOT_BRIGHTNESS = 22

# Empty-slot variance filter: skip slots whose grayscale std is below this.
# Empty quatrefoil patterns have low variance (~10); real icons have ~24+.
EMPTY_SLOT_VARIANCE = 22

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

        anchor_path = TPL_DIR / "offer_button.png"
        if not anchor_path.exists():
            raise FileNotFoundError(f"Anchor template missing: {anchor_path}")
        self._anchor_template = cv2.imread(str(anchor_path))

        self._icon_data: Dict[str, Dict] = {}
        self._prices: Dict[str, float] = {}
        self._prices_fetched_at: float = 0.0
        self._last_scheduled_hour: int = -1
        self._chaos_per_ex: float = 1.0
        self._load_icon_hashes()
        self._fetch_prices()

    def _load_icon_hashes(self):
        """Load icon hashes grouped by tile shape (cols x rows).

        Icon aspect ratio determines its shape. For example:
          108x108  -> 1x1 (square)
          212x108  -> 2x1 (wide)
          212x420  -> 2x4 (very tall shield)
        We render the icon into a synthetic tile-region the same shape, then
        pHash it. At match time we extract the same-shaped region from the
        screenshot and pHash-match against the right group.
        """
        for icon_path in ICON_DIR.glob("*.png"):
            icon_pil = Image.open(icon_path).convert("RGB")
            iw, ih = icon_pil.size
            # Determine tile shape from aspect ratio. The base slot is
            # SLOT_SIZE x SLOT_SIZE pixels; a 2-wide tile is 2*SLOT_SIZE.
            # Compute cols/rows as the closest integers to (iw/SLOT_SIZE)
            # and (ih/SLOT_SIZE).
            cols = max(1, round(iw / SLOT_SIZE))
            rows = max(1, round(ih / SLOT_SIZE))
            # Sanity clamp
            cols = min(cols, 3)
            rows = min(rows, 4)
            # Render the icon into a (cols*SLOT_SIZE) x (rows*SLOT_SIZE) region
            target_w = SLOT_SIZE * cols
            target_h = SLOT_SIZE * rows
            fitted = icon_pil.resize((target_w, target_h), Image.LANCZOS)
            # pHash for matching
            hash_target_w = 128 * cols
            hash_target_h = 128 * rows
            pil_for_hash = fitted.resize((hash_target_w, hash_target_h), Image.LANCZOS)
            self._icon_data[icon_path.stem] = {
                "phash": imagehash.phash(pil_for_hash, hash_size=16),
                "dhash": imagehash.dhash(pil_for_hash, hash_size=16),
                "whash": imagehash.whash(pil_for_hash, hash_size=16),
                "cols": cols,
                "rows": rows,
                "iw": iw,
                "ih": ih,
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
        if self._anchor_template is None or screen is None:
            return None
        if screen.shape[0] < self._anchor_template.shape[0] or \
           screen.shape[1] < self._anchor_template.shape[1]:
            return None
        result = cv2.matchTemplate(screen, self._anchor_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val >= ANCHOR_MATCH_THRESHOLD:
            return max_loc
        return None

    def match_region(self, region_img: np.ndarray, cols: int, rows: int) -> Optional[Tuple[str, float, int]]:
        """Match a multi-tile region. Returns (api_id, price, margin) or None."""
        if region_img is None:
            return None
        target_w = SLOT_SIZE * cols
        target_h = SLOT_SIZE * rows
        if region_img.shape[0] < target_h or region_img.shape[1] < target_w:
            return None
        # Crop to exact region size
        region = region_img[:target_h, :target_w]
        # Compute hashes
        pil = Image.fromarray(cv2.cvtColor(region, cv2.COLOR_BGR2RGB))
        hash_target_w = 128 * cols
        hash_target_h = 128 * rows
        pil = pil.resize((hash_target_w, hash_target_h), Image.LANCZOS)
        phash = imagehash.phash(pil, hash_size=16)
        dhash = imagehash.dhash(pil, hash_size=16)
        whash = imagehash.whash(pil, hash_size=16)
        # Match against icons with this exact shape
        best_name, best_total = None, None
        second_total = None
        for name, data in self._icon_data.items():
            if data["cols"] != cols or data["rows"] != rows:
                continue
            p_dist = phash - data["phash"]
            d_dist = dhash - data["dhash"]
            w_dist = whash - data["whash"]
            total = p_dist + d_dist + w_dist
            if best_total is None or total < best_total:
                second_total = best_total
                best_total = total
                best_name = name
            elif second_total is None or total < second_total:
                second_total = total
        if best_name is None or best_total is None or second_total is None:
            return None
        margin = second_total - best_total
        # Multi-tile matches need a higher margin threshold.
        threshold = MATCH_MARGIN_THRESHOLD if (cols == 1 and rows == 1) else MATCH_MARGIN_THRESHOLD_MULTI
        if margin < threshold:
            return None
        api_id = best_name.replace("unique_", "")
        price = self._prices.get(api_id, 0.0)
        return api_id, price, margin

    def scan_slots(self, screen: np.ndarray, anchor: Tuple[int, int]) -> List[Tuple[int, int, int, int, str, float]]:
        """Sweep slot grid; return list of (row, col, center_x, center_y, name, price).

        Items can be 1x1, 2x1 (wide), 1x2 (tall), 2x2, 2x3, 2x4, etc.
        We try matching every (row, col) anchor at every shape, but only
        place a multi-tile match if no smaller match consumes the same slots.
        """
        if anchor is None:
            return []
        ax, ay = anchor
        ox, oy = GRID_OFFSET_FROM_ANCHOR

        # Collect all shape candidates: list of (row, col, cols, rows, api_id, price, margin)
        candidates = []
        for row in range(SLOT_ROWS):
            for col in range(SLOT_COLS):
                for shape_cols, shape_rows in [(1, 1), (2, 1), (1, 2), (2, 2), (2, 3), (2, 4), (1, 3), (1, 4)]:
                    sx = ax + ox + col * SLOT_SIZE
                    sy = ay + oy + row * SLOT_SIZE
                    w = SLOT_SIZE * shape_cols
                    h = SLOT_SIZE * shape_rows
                    if sx + w > screen.shape[1] or sy + h > screen.shape[0]:
                        continue
                    region = screen[sy:sy+h, sx:sx+w]
                    # Brightness/variance check on the full region
                    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
                    if float(gray.mean()) < EMPTY_SLOT_BRIGHTNESS:
                        continue
                    if float(gray.std()) < EMPTY_SLOT_VARIANCE:
                        continue
                    match = self.match_region(region, shape_cols, shape_rows)
                    if match is None:
                        continue
                    api_id, price, margin = match
                    candidates.append((row, col, shape_cols, shape_rows, api_id, price, margin))

        # Non-max suppression: prefer larger matches, suppress smaller matches
        # whose slots are consumed by a larger one.
        # Sort by area desc, then margin desc
        candidates.sort(key=lambda c: (-(c[2] * c[3]), -c[6]))
        consumed = set()
        hits: List[Tuple[int, int, int, int, str, float]] = []
        for row, col, sc, sr, api_id, price, margin in candidates:
            slots = set()
            for r in range(row, row + sr):
                for c in range(col, col + sc):
                    slots.add((r, c))
            if slots & consumed:
                continue
            consumed |= slots
            cx = ax + ox + (col + sc / 2) * SLOT_SIZE
            cy = ay + oy + (row + sr / 2) * SLOT_SIZE
            hits.append((row, col, int(cx), int(cy), api_id, price))
        return hits


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
                self._stable.clear()
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