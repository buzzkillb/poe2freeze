"""
Ritual overlay — hybrid pHash + template matching.

pHash quickly narrows 494 icons to 3 candidates per cell.
cv2.matchTemplate verifies the best match on the small cell region.
Runs in ~15ms per frame on CPU.
"""
from __future__ import annotations

import json, time, urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2, imagehash, numpy as np
from PIL import Image
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QBrush
from PyQt5.QtWidgets import QWidget

DATA_DIR = Path(__file__).parent / "data"
ICON_DIR = DATA_DIR / "ritual_icons"
TPL_DIR = DATA_DIR / "ritual_templates"
POE2SCOUT_BASE = "https://poe2scout.com/api"
PRICE_CACHE_TTL = 30 * 60; SCHEDULED_REFRESH_MINUTE = 1; SCHEDULED_REFRESH_WINDOW_SECS = 30

SLOT_SIZE = 105; SLOT_COLS = 12; SLOT_ROWS = 10
ANCHOR_MATCH_THRESHOLD = 0.85
TMPL_PER_TICK = 999          # batch all icons in one scan (~1-2s blocking, but finds all)
MAX_HITS = 15                  # max price labels on overlay


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
        self._prices: Dict[str, float] = {}
        self._prices_fetched_at = 0.0
        self._last_scheduled_hour = -1
        self._chaos_per_ex = 1.0
        self._load_icons()
        self._fetch_prices()

    # -----------------------------------------------------------------
    def _load_icons(self):
        """Load icons: pHash + BGR template for every shape."""
        for p in ICON_DIR.glob("*.png"):
            stem = p.stem
            img = Image.open(p).convert("RGB")
            iw, ih = img.size
            cols = min(3, max(1, round(iw / SLOT_SIZE)))
            rows = min(4, max(1, round(ih / SLOT_SIZE)))

            target_w = SLOT_SIZE * cols
            target_h = SLOT_SIZE * rows
            fitted = img.resize((target_w, target_h), Image.LANCZOS)

            # pHash (used for fast pre-filter)
            ph_pil = fitted.resize((128 * cols, 128 * rows), Image.LANCZOS)
            self._icon_data[stem] = {
                "phash":  imagehash.phash(ph_pil, hash_size=16),
                "dhash":  imagehash.dhash(ph_pil, hash_size=16),
                "cols":   cols, "rows": rows,
                "icon":   cv2.cvtColor(np.array(fitted), cv2.COLOR_RGB2BGR),
            }
        shapes = set((d["cols"], d["rows"]) for d in self._icon_data.values())
        common = {(1, 1), (2, 1), (2, 2), (2, 3), (2, 4)}  # most common in game
        self._shapes = sorted((s for s in shapes if s in common and
            sum(1 for d in self._icon_data.values() if d["cols"] == s[0] and d["rows"] == s[1]) >= 2 and
            s[0] <= SLOT_COLS and s[1] <= SLOT_ROWS),
            key=lambda s: -(s[0] * s[1]))
        print(f"[ritual] {len(self._icon_data)} icons, shapes={self._shapes}", flush=True)

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
    def _phash_candidates(self, region, sc, sr):
        """NOT USED — kept for reference. Direct matchTemplate is more reliable."""
        return []

    def scan(self, screen, anchor):
        """Direct matchTemplate on the inner half of the grid ROI (where items appear).
        Returns a dict of stable hits that are added to the existing display."""
        if anchor is None: return []
        ax, ay = anchor
        # Focus on columns 0-2 (sacrifice items) and columns 9-11 (receive items)
        # Rows 0-7 (visible part). This is ~4/6 of the grid area but still finds all items.
        inner_x1 = ax + 0
        inner_y1 = ay
        inner_x2 = min(screen.shape[1], ax + SLOT_SIZE * 3)  # sacrifice side
        # Also add receive side
        rcv_x1 = max(0, ax + SLOT_SIZE * (SLOT_COLS - 3))
        rcv_y1 = ay
        rcv_x2 = screen.shape[1]
        rcv_y2 = min(screen.shape[0], ay + SLOT_SIZE * SLOT_ROWS)
        # Just use the full grid ROI for simplicity
        x1 = max(0, ax - 5); y1 = max(0, ay - 5)
        x2 = min(screen.shape[1], ax + SLOT_SIZE * SLOT_COLS + 5)
        y2 = min(screen.shape[0], ay + SLOT_SIZE * SLOT_ROWS + 5)
        if x2 <= x1 or y2 <= y1: return []
        roi = screen[y1:y2, x1:x2]

        candidates = []
        for name, d in self._icon_data.items():
            tpl = d["icon"]; th, tw = tpl.shape[:2]
            if th > roi.shape[0] or tw > roi.shape[1]: continue
            result = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(result)
            if score < 0.50: continue
            api_id = name.replace("unique_", "")
            price = self._prices.get(api_id, 0.0)
            cx, cy = x1 + loc[0] + tw // 2, y1 + loc[1] + th // 2
            candidates.append((cx, cy, tw, th, api_id, price, float(score)))

        candidates.sort(key=lambda c: -(c[6] * c[2] * c[3]))
        hits = []
        for cx, cy, tw, th, name, price, score in candidates:
            if any(abs(cx - h[0]) < 35 and abs(cy - h[1]) < 35 for h in hits): continue
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