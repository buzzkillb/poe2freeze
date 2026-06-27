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

# Price cache TTL in seconds. Prices on poe2scout fluctuate;
# 30 minutes is a reasonable balance.
PRICE_CACHE_TTL = 30 * 60

# Slot grid calibration (from user's 1502x1440 screenshot).
# These are pixel offsets relative to the offer-button anchor's top-left corner.
# Anchor (offer_button.png) top-left is at (200, 1410).
# Grid slot 0,0 origin is at (157, 337) -> delta from anchor = (-43, -1073).
GRID_OFFSET_FROM_ANCHOR = (-43, -1073)
SLOT_SIZE = 105
SLOT_COLS = 12
SLOT_ROWS = 10

# pHash match threshold: minimum margin (top1 - top2) to accept a slot match.
MATCH_MARGIN_THRESHOLD = 8

# Empty-slot filter: skip slots whose mean brightness is below this.
# Dark altar/candle areas average ~10-20; real item slots with blue
# background + icon average ~50-100+.
EMPTY_SLOT_BRIGHTNESS = 28

# Empty-slot variance filter: skip slots whose grayscale std is below this.
# Empty quatrefoil patterns have low variance (~10); real icons have ~25+.
EMPTY_SLOT_VARIANCE = 20

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
        self._chaos_per_ex: float = 1.0
        self._load_icon_hashes()
        self._fetch_prices()

    def _load_icon_hashes(self):
        for icon_path in ICON_DIR.glob("*.png"):
            icon_pil = Image.open(icon_path).convert("RGB").resize((128, 128), Image.LANCZOS)
            self._icon_data[icon_path.stem] = {
                "phash": imagehash.phash(icon_pil, hash_size=16),
                "dhash": imagehash.dhash(icon_pil, hash_size=16),
                "whash": imagehash.whash(icon_pil, hash_size=16),
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
            self._prices_fetched_at = time.time()
            print(f"[ritual] fetched {fetched} prices (chaos/ex={self._chaos_per_ex:.2f})", flush=True)
        except Exception as e:
            print(f"[ritual] price fetch failed: {e}", flush=True)

    def refresh_prices_if_stale(self):
        """Refresh prices if cache is older than PRICE_CACHE_TTL."""
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

    def match_slot(self, slot_img: np.ndarray) -> Optional[Tuple[str, float, int]]:
        """Match a cropped slot via pHash. Returns (api_id, price, margin) or None."""
        if slot_img is None or slot_img.shape[0] < SLOT_SIZE or slot_img.shape[1] < SLOT_SIZE:
            return None
        pil = Image.fromarray(cv2.cvtColor(slot_img, cv2.COLOR_BGR2RGB)).resize((128, 128), Image.LANCZOS)
        phash = imagehash.phash(pil, hash_size=16)
        dhash = imagehash.dhash(pil, hash_size=16)
        whash = imagehash.whash(pil, hash_size=16)
        best_name, best_total = None, None
        second_total = None
        for name, data in self._icon_data.items():
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
        if margin < MATCH_MARGIN_THRESHOLD:
            return None
        api_id = best_name.replace("unique_", "")
        price = self._prices.get(api_id, 0.0)
        return api_id, price, margin

    def scan_slots(self, screen: np.ndarray, anchor: Tuple[int, int]) -> List[Tuple[int, int, str, float]]:
        """Sweep slot grid; return list of (center_x, center_y, name, price)."""
        if anchor is None:
            return []
        ax, ay = anchor
        ox, oy = GRID_OFFSET_FROM_ANCHOR
        hits: List[Tuple[int, int, str, float]] = []
        for row in range(SLOT_ROWS):
            for col in range(SLOT_COLS):
                sx = ax + ox + col * SLOT_SIZE
                sy = ay + oy + row * SLOT_SIZE
                if sx < 0 or sy < 0 or sx + SLOT_SIZE > screen.shape[1] or sy + SLOT_SIZE > screen.shape[0]:
                    continue
                slot = screen[sy:sy+SLOT_SIZE, sx:sx+SLOT_SIZE]
                gray = cv2.cvtColor(slot, cv2.COLOR_BGR2GRAY)
                if float(gray.mean()) < EMPTY_SLOT_BRIGHTNESS:
                    continue
                if float(gray.std()) < EMPTY_SLOT_VARIANCE:
                    continue
                match = self.match_slot(slot)
                if match is None:
                    continue
                api_id, price, _margin = match
                cx = sx + SLOT_SIZE // 2
                cy = sy + SLOT_SIZE // 2
                hits.append((cx, cy, api_id, price))
        return hits


class RitualWatcher:
    """Periodically captures the screen, detects ritual UI, and updates the overlay."""

    def __init__(self, overlay: RitualPriceOverlay, detector: RitualDetector,
                 refresh_seconds: float = 1.0):
        self.overlay = overlay
        self.detector = detector
        self.refresh_seconds = refresh_seconds
        self._timer: Optional[QTimer] = None
        self._screen_capture = _build_screen_capture()
        self._last_present = False

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

    def _tick(self):
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
        hits = self.detector.scan_slots(screen, anchor)
        self.overlay.set_hits(hits)
        self._last_present = True
        if hits:
            summary = ", ".join(f"{n}={p:.1f}x" for _, _, n, p in hits)
            print(f"[ritual] {len(hits)} hits: {summary}", flush=True)


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