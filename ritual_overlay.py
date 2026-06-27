"""
Ritual overlay — cell-grid decomposition + size-bucketed template matching.

Phase 1: Build 12x10 cell-occupancy mask using integral image (2ms)
Phase 2: Connected components on the 12x10 mask -> item regions in cell units
Phase 3: For each region, matchTemplate against icons in its size bucket
"""
from __future__ import annotations

import json, time, urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2, numpy as np
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QBrush
from PyQt5.QtWidgets import QWidget

DATA_DIR = Path(__file__).parent / "data"
ICON_DIR = DATA_DIR / "ritual_icons"
TPL_DIR = DATA_DIR / "ritual_templates"
POE2SCOUT_BASE = "https://poe2scout.com/api"
PRICE_CACHE_TTL = 30 * 60
SCHEDULED_REFRESH_MINUTE = 1
SCHEDULED_REFRESH_WINDOW_SECS = 30

SLOT_SIZE = 105
SLOT_COLS = 12
SLOT_ROWS = 10
ANCHOR_MATCH_THRESHOLD = 0.85
MATCH_THRESHOLD = 0.45
CELL_MEAN_THRESHOLD = 25  # cell is "occupied" if mean brightness > this
NMS_RADIUS = 35
MAX_HITS = 15


class RitualPriceOverlay(QWidget):
    PO2_GOLD_BRIGHT = QColor(255, 210, 130)
    PO2_BG = QColor(15, 12, 8, 220)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setGeometry(0, 0, 8000, 8000)
        self._hits: List[Tuple[int, int, str, float]] = []
        self.hide()

    def set_hits(self, hits): self._hits = hits; self.show() if hits else None; self.update()
    def clear(self): self._hits = []; self.hide()

    def paintEvent(self, event):
        if not self._hits: return
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        font = QFont("Serif", 13, QFont.Bold); painter.setFont(font); fm = QFontMetrics(font)
        for cx, cy, _n, p in self._hits:
            txt = _fmt(p); tw = fm.horizontalAdvance(txt) + 14; th = fm.height() + 6
            lx, ly = int(cx - tw / 2), int(cy - th / 2)
            painter.setPen(Qt.NoPen); painter.setBrush(QBrush(self.PO2_BG))
            painter.drawRoundedRect(lx, ly, tw, th, 4, 4)
            painter.setPen(QPen(self.PO2_GOLD_BRIGHT, 1))
            painter.drawText(lx + 7, ly + fm.ascent() + 3, txt)


class RitualDetector:

    def __init__(self, league: str = "Runes of Aldur"):
        self.league = league
        self._anchor_template = cv2.imread(str(TPL_DIR / "favours_header.png"))
        self._offer_template = None
        op = TPL_DIR / "offer_button.png"
        if op.exists(): self._offer_template = cv2.imread(str(op))
        self._icon_data: Dict[str, Dict] = {}
        self._icon_buckets: Dict[Tuple[int, int], List[str]] = {}
        self._prices: Dict[str, float] = {}
        self._prices_fetched_at = 0.0
        self._last_scheduled_hour = -1
        self._chaos_per_ex = 1.0
        self._load_icons()
        self._fetch_prices()

    def _load_icons(self):
        """Load icons as BGR + bucket by shape (cols, rows)."""
        for p in ICON_DIR.glob("*.png"):
            stem = p.stem
            img = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if img is None: continue
            ih, iw = img.shape[:2]
            cols = min(3, max(1, round(iw / SLOT_SIZE)))
            rows = min(4, max(1, round(ih / SLOT_SIZE)))
            target_w = SLOT_SIZE * cols
            target_h = SLOT_SIZE * rows
            fitted = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_AREA)
            self._icon_data[stem] = {
                "icon": fitted,
                "cols": cols, "rows": rows,
            }
            self._icon_buckets.setdefault((cols, rows), []).append(stem)
        print(f"[ritual] {len(self._icon_data)} icons, "
              f"buckets={ {k: len(v) for k, v in sorted(self._icon_buckets.items())} }",
              flush=True)

    def _fetch_prices(self):
        league_enc = urllib.parse.quote(self.league, safe="")
        try:
            r = urllib.request.Request(f"{POE2SCOUT_BASE}/poe2/Leagues/{league_enc}/ReferenceCurrencies",
                                       headers={"User-Agent": "mypoeapp/1.0"})
            with urllib.request.urlopen(r, timeout=15) as resp:
                for e in json.loads(resp.read()):
                    if e.get("ApiId") == "chaos":
                        self._chaos_per_ex = float(e.get("RelativePrice", 1.0))
        except Exception as e: print(f"[ritual] ref fail {e}", flush=True)
        fetched = 0
        try:
            for page in range(1, 5):
                u = f"{POE2SCOUT_BASE}/poe2/Leagues/{league_enc}/Currencies/ByCategory?Category=ritual&Page={page}"
                r = urllib.request.Request(u, headers={"User-Agent": "mypoeapp/1.0"})
                with urllib.request.urlopen(r, timeout=15) as resp:
                    for it in json.loads(resp.read()).get("Items", []):
                        aid = it.get("ApiId")
                        if aid and it.get("CurrentPrice") is not None:
                            raw = float(it["CurrentPrice"])
                            if raw >= 10 and self._chaos_per_ex > 1: raw /= self._chaos_per_ex
                            self._prices[aid] = raw; fetched += 1
            r = urllib.request.Request(f"{POE2SCOUT_BASE}/poe2/Leagues/{league_enc}/Items?perPage=2000",
                                       headers={"User-Agent": "mypoeapp/1.0"})
            with urllib.request.urlopen(r, timeout=15) as resp:
                for it in json.loads(resp.read()):
                    n = it.get("Name") or ""
                    aid = n.lower().replace("'", "").replace(" ", "-")
                    if aid and it.get("CurrentPrice") is not None and aid not in self._prices:
                        self._prices[aid] = float(it["CurrentPrice"]); fetched += 1
        except Exception as e: print(f"[ritual] price fail {e}", flush=True)
        self._prices_fetched_at = time.time()
        print(f"[ritual] {fetched} prices (c/ex={self._chaos_per_ex:.2f})", flush=True)

    def refresh_prices_if_scheduled(self):
        now = datetime.now()
        if (now.minute == SCHEDULED_REFRESH_MINUTE and now.second < SCHEDULED_REFRESH_WINDOW_SECS
                and now.hour != self._last_scheduled_hour):
            self._last_scheduled_hour = now.hour; self._fetch_prices()
        elif time.time() - self._prices_fetched_at > PRICE_CACHE_TTL:
            self._fetch_prices()

    def find_anchor(self, screen):
        if screen is None: return None
        h, w = screen.shape[:2]
        if self._offer_template is not None and h >= self._offer_template.shape[0] and w >= self._offer_template.shape[1]:
            r = cv2.matchTemplate(screen, self._offer_template, cv2.TM_CCOEFF_NORMED)
            _, v, _, loc = cv2.minMaxLoc(r)
            if v >= ANCHOR_MATCH_THRESHOLD: return (loc[0] + 62, loc[1] - 1180)
        if h >= self._anchor_template.shape[0] and w >= self._anchor_template.shape[1]:
            r = cv2.matchTemplate(screen, self._anchor_template, cv2.TM_CCOEFF_NORMED)
            _, v, _, loc = cv2.minMaxLoc(r)
            if v >= ANCHOR_MATCH_THRESHOLD: return (loc[0] - 315, loc[1] + 288)
        return None

    # -----------------------------------------------------------------
    def _cell_mask(self, screen, anchor):
        """Build 12x10 boolean mask of occupied cells using integral image.
        Each cell is 105x105. Returns (mask[H][W], gray_image) where
        mask[r][c] = True if cell (r,c) is occupied (mean brightness > threshold)."""
        ax, ay = anchor
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        # Crop just the grid area
        x0 = max(0, ax); y0 = max(0, ay)
        x1 = min(screen.shape[1], ax + SLOT_SIZE * SLOT_COLS)
        y1 = min(screen.shape[0], ay + SLOT_SIZE * SLOT_ROWS)
        if x1 <= x0 or y1 <= y0:
            return None, None, x0, y0
        grid_gray = gray[y0:y1, x0:x1]
        # Integral image: sum over each cell = integral[y0,y1,x0,x1] lookup
        integral = cv2.integral(grid_gray)
        mask = np.zeros((SLOT_ROWS, SLOT_COLS), dtype=bool)
        for r in range(SLOT_ROWS):
            for c in range(SLOT_COLS):
                y_top = r * SLOT_SIZE; y_bot = y_top + SLOT_SIZE
                x_left = c * SLOT_SIZE; x_right = x_left + SLOT_SIZE
                if y_bot > grid_gray.shape[0] or x_right > grid_gray.shape[1]:
                    continue
                mean = (integral[y_bot, x_right] - integral[y_top, x_right]
                        - integral[y_bot, x_left] + integral[y_top, x_left]) / (SLOT_SIZE * SLOT_SIZE)
                if mean > CELL_MEAN_THRESHOLD:
                    mask[r, c] = True
        return mask, grid_gray, x0, y0

    def _components_from_mask(self, mask):
        """4-connected components capped at 2x6 (largest real item shape).
        Oversized components (e.g. column of stacked 1x1 items) are split
        into individual 1x1 cells."""
        MAX_W, MAX_H = 2, 6
        visited = np.zeros_like(mask, dtype=bool)
        comps = []
        for r in range(mask.shape[0]):
            for c in range(mask.shape[1]):
                if not mask[r, c] or visited[r, c]: continue
                stack = [(r, c)]; cells = []
                while stack:
                    cr, cc = stack.pop()
                    if cr < 0 or cr >= mask.shape[0] or cc < 0 or cc >= mask.shape[1]: continue
                    if visited[cr, cc] or not mask[cr, cc]: continue
                    visited[cr, cc] = True; cells.append((cr, cc))
                    stack.extend([(cr+1,cc),(cr-1,cc),(cr,cc+1),(cr,cc-1)])
                if not cells: continue
                rs = [x[0] for x in cells]; cs = [x[1] for x in cells]
                w = max(cs) - min(cs) + 1; h = max(rs) - min(rs) + 1
                if w > MAX_W or h > MAX_H:
                    # Split into individual 1x1 cells
                    for cr, cc in cells:
                        comps.append((cr, cc, 1, 1, {(cr, cc)}))
                else:
                    comps.append((min(rs), min(cs), w, h, set(cells)))
        return comps

    def scan(self, screen, anchor):
        """Phase 1: cell mask to find occupied shapes.
        Phase 2: matchTemplate on full grid ROI, but only for icons of detected shapes."""
        if anchor is None: return []
        mask, grid_gray, gx, gy = self._cell_mask(screen, anchor)
        if mask is None: return []
        comps = self._components_from_mask(mask)
        if not comps: return []

        # Collect unique shapes from components
        detected_shapes = set((w, h) for r, c, w, h, _ in comps)
        # Gather all icon names matching detected shapes
        icons_to_try = []
        for shape in detected_shapes:
            icons_to_try.extend(self._icon_buckets.get(shape, []))
        if not icons_to_try: return []

        # Full grid ROI for matchTemplate (allows best alignment)
        ax, ay = anchor
        x1 = max(0, ax - 5); y1 = max(0, ay - 5)
        x2 = min(screen.shape[1], ax + SLOT_SIZE * SLOT_COLS + 5)
        y2 = min(screen.shape[0], ay + SLOT_SIZE * SLOT_ROWS + 5)
        roi = screen[y1:y2, x1:x2]

        candidates = []
        for name in icons_to_try:
            tpl = self._icon_data[name]["icon"]
            th, tw = tpl.shape[:2]
            if th > roi.shape[0] or tw > roi.shape[1]: continue
            result = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(result)
            if score < MATCH_THRESHOLD: continue
            api_id = name.replace("unique_", "")
            price = self._prices.get(api_id, 0.0)
            cx = x1 + loc[0] + tw // 2
            cy = y1 + loc[1] + th // 2
            candidates.append((cx, cy, tw, th, api_id, price, float(score)))

        # NMS: prefer higher score * area
        candidates.sort(key=lambda c: -(c[6] * c[2] * c[3]))
        hits = []
        for cx, cy, tw, th, name, price, score in candidates:
            if any(abs(cx - h[0]) < NMS_RADIUS and abs(cy - h[1]) < NMS_RADIUS for h in hits): continue
            hits.append((cx, cy, name, price))
            if len(hits) >= MAX_HITS: break
        return hits


class RitualWatcher:
    STABILITY = 2; LINGER = 3

    def __init__(self, overlay, detector, refresh_seconds=1.0):
        self.overlay = overlay; self.detector = detector
        self._timer = None; self._cap = _build_screen_capture()
        self._last_present = False
        self._stable: Dict[Tuple[int, int], Tuple[Tuple, int, int]] = {}

    def start(self):
        if self._timer: return
        self._timer = QTimer(); self._timer.timeout.connect(self._tick); self._timer.start(1000)

    def stop(self):
        if self._timer: self._timer.stop(); self._timer = None
        self.overlay.clear(); self._stable.clear()

    def _tick(self):
        self.detector.refresh_prices_if_scheduled()
        try: screen = self._cap()
        except Exception as e: print(f"[ritual] cap fail: {e}", flush=True); return
        anchor = self.detector.find_anchor(screen)
        if anchor is None:
            if self._last_present: self.overlay.clear()
            self._last_present = False; return
        raw = self.detector.scan(screen, anchor)
        cur = {}
        for cx, cy, n, p in raw: cur[(cx // 60, cy // 60)] = (cx, cy, n, p)
        ns = {}
        for k, m in cur.items():
            old = self._stable.get(k)
            ns[k] = (m, old[1] + 1, 0) if (old and old[0] == m) else (m, 1, 0)
        for k, (m, hc, mc) in self._stable.items():
            if k not in cur:
                nm = mc + 1
                if nm <= self.LINGER: ns[k] = (m, hc, nm)
        self._stable = ns
        out = [m for (m, hc, _) in self._stable.values() if hc >= self.STABLE]
        self.overlay.set_hits(out)
        self._last_present = True
        if out:
            s = ", ".join(f"{n}={p:.1f}x" for _, _, n, p in out)
            print(f"[ritual] {len(out)} hits: {s}", flush=True)


def _fmt(price: float) -> str:
    if price >= 1000: return f"{price/1000:.1f}kx"
    if price >= 10: return f"{price:.0f}x"
    if price >= 1: return f"{price:.1f}x"
    if price >= 0.01: return f"{price:.2f}x"
    return f"{price:.3f}x"


def _build_screen_capture():
    try:
        import mss; sct = mss.mss()
        def capture(): return cv2.cvtColor(np.array(sct.grab(sct.monitors[1])), cv2.COLOR_BGRA2BGR)
        return capture
    except ImportError:
        from PIL import ImageGrab
        def capture(): return cv2.cvtColor(np.array(ImageGrab.grab()), cv2.COLOR_RGB2BGR)
        return capture