"""
Ritual overlay — automatic icon matching from poe2scout database.

No OCR. No user interaction. Detects items in ritual grid automatically
via combined template + color matching against downloaded icon database.
"""
from __future__ import annotations

import json, time, urllib.parse, urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2, numpy as np

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QBrush
from PyQt5.QtWidgets import QWidget, QApplication

DATA_DIR = Path(__file__).parent / "data"
TPL_DIR = DATA_DIR / "ritual_templates"
ICONS_DIR = DATA_DIR / "unique_icons" / "icons"
DB_PATH = DATA_DIR / "unique_icons" / "database.json"
POE2SCOUT_BASE = "https://poe2scout.com/api"

ANCHOR_THRESH = 0.55
SLOT_SIZE = 105
SLOT_COLS = 12
SLOT_ROWS = 10
MATCH_THRESH = 0.40


class RitualPriceOverlay(QWidget):
    PO2_GOLD = QColor(255, 210, 130)
    PO2_BG = QColor(15, 12, 8, 230)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.Tool | Qt.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        screen = QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())
        else:
            self.setGeometry(0, 0, 1920, 1080)
        self._hits: List[Tuple[int, int, str, float]] = []
        self.hide()

    def set_hits(self, hits):
        self._hits = hits
        if hits:
            self.show()
            self.raise_()
            self.update()
        else:
            self.hide()

    def clear(self):
        self._hits = []
        self.hide()
        self.update()

    def paintEvent(self, event):
        if not self._hits:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont("Serif", 14, QFont.Bold)
        painter.setFont(font)
        fm = QFontMetrics(font)
        for cx, cy, name, price in self._hits:
            txt = _fmt(price)
            if not txt:
                continue
            tw = fm.horizontalAdvance(txt) + 14
            th = fm.height() + 8
            lx = int(cx - tw / 2)
            ly = int(cy - th / 2)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(self.PO2_BG))
            painter.drawRoundedRect(lx, ly, tw, th, 4, 4)
            painter.setPen(QPen(self.PO2_GOLD, 1))
            painter.drawText(lx + 7, ly + fm.ascent() + 4, txt)


class RitualDetector:
    def __init__(self, league="Runes of Aldur"):
        self.league = league

        # Anchor templates
        t = cv2.imread(str(TPL_DIR / "favours_header.png"))
        self._anchor_tpl = t
        if t is not None:
            self._anchor_tpl_h, self._anchor_tpl_w = t.shape[:2]

        # Icon database for matching
        self._icons: Dict[str, dict] = {}
        self._load_icons()

        # Prices
        self._prices: Dict[str, float] = {}
        self._chaos_per_ex = 1.0
        self._fetch_prices()

        # Cached anchor for reliability
        self._cached_anchor: Optional[Tuple[int, int]] = None

    def _load_icons(self):
        if not DB_PATH.exists():
            return
        with open(DB_PATH) as f:
            items = json.load(f).get("items", [])
        icon_list = []
        for item in items:
            name = item.get("name") or item.get("apiId") or ""
            icon_rel = item.get("iconLocal", "")
            if not icon_rel:
                continue
            if not name:
                fname = Path(icon_rel).stem
                name = fname.replace("-", " ").replace("_", " ")
            path = ICONS_DIR / Path(icon_rel).name
            if not path.exists():
                continue
            img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if img is None:
                continue
            if img.shape[-1] == 4:
                b, g, r, a = cv2.split(img)
                m = (a > 40).astype(np.uint8) * 255
                fg = cv2.merge([b, g, r])
                bg = np.full(img.shape[:2] + (3,), (12, 10, 8), dtype=np.uint8)
                comp = fg.copy()
                comp[m == 0] = bg[m == 0]
                img = comp
            h, wi = img.shape[:2]
            icon_list.append({
                "name": name,
                "img": img,
                "gray": cv2.cvtColor(img, cv2.COLOR_BGR2GRAY),
                "price": item.get("currentPrice", 0),
                "aspect": float(wi) / h if h > 0 else 1.0,
                "area": h * wi,
            })
        self._icons = icon_list
        print(f"[ritual] Loaded {len(self._icons)} icon templates", flush=True)

    def _fetch_prices(self):
        le = urllib.parse.quote(self.league, safe="")
        try:
            r = urllib.request.Request(
                f"{POE2SCOUT_BASE}/poe2/Leagues/{le}/ReferenceCurrencies",
                headers={"User-Agent": "mypoeapp/1.0"},
            )
            with urllib.request.urlopen(r, timeout=15) as resp:
                for e in json.loads(resp.read()):
                    if e.get("ApiId") == "chaos":
                        self._chaos_per_ex = float(e.get("RelativePrice", 1.0))
        except Exception:
            pass

        fetched = 0
        try:
            for page in range(1, 5):
                u = f"{POE2SCOUT_BASE}/poe2/Leagues/{le}/Currencies/ByCategory?Category=ritual&Page={page}"
                r = urllib.request.Request(u, headers={"User-Agent": "mypoeapp/1.0"})
                with urllib.request.urlopen(r, timeout=15) as resp:
                    for it in json.loads(resp.read()).get("Items", []):
                        aid = it.get("ApiId")
                        if aid and it.get("CurrentPrice") is not None:
                            raw = float(it["CurrentPrice"])
                            if raw >= 10 and self._chaos_per_ex > 1:
                                raw /= self._chaos_per_ex
                            self._prices[aid] = raw
                            fetched += 1
            r = urllib.request.Request(
                f"{POE2SCOUT_BASE}/poe2/Leagues/{le}/Items?perPage=2000",
                headers={"User-Agent": "mypoeapp/1.0"},
            )
            with urllib.request.urlopen(r, timeout=15) as resp:
                for it in json.loads(resp.read()):
                    n = it.get("Name") or ""
                    aid = n.lower().replace("'", "").replace(" ", "-")
                    if aid and it.get("CurrentPrice") is not None and aid not in self._prices:
                        raw = float(it["CurrentPrice"])
                        if raw >= 10 and self._chaos_per_ex > 1:
                            raw /= self._chaos_per_ex
                        self._prices[aid] = raw
                        fetched += 1
        except Exception as e:
            print(f"[ritual] Price fetch error: {e}", flush=True)
        print(f"[ritual] {fetched} prices (c/ex={self._chaos_per_ex:.2f})", flush=True)

    def find_anchor(self, screen):
        """Find ritual grid top-left corner. Uses template matching + known offsets for 4K."""
        if screen is None:
            return None
        h, w = screen.shape[:2]

        # For 4K (3840x2160), the grid has been consistently at (453, 682)
        # Try known position first with verification
        for ax, ay in [(453, 682), (400, 680), (350, 680)]:
            if ax < 0 or ay < 0 or ax + 200 >= w or ay + 300 >= h:
                continue
            check = screen[ay : ay + 300, ax : ax + 200]
            gray = cv2.cvtColor(check, cv2.COLOR_BGR2GRAY)
            # A grid with items should have some bright spots
            if gray.mean() > 20:
                return (ax, ay)

        # Template-based fallback
        if self._anchor_tpl is not None:
            th, tw = self._anchor_tpl.shape[:2]
            if h >= th and w >= tw:
                r = cv2.matchTemplate(screen, self._anchor_tpl, cv2.TM_CCOEFF_NORMED)
                _, v, _, loc = cv2.minMaxLoc(r)
                if v >= ANCHOR_THRESH:
                    ax = loc[0] - 315
                    ay = loc[1] + 288
                    if 0 <= ax < w - 100 and 0 <= ay < h - 100:
                        return (ax, ay)

        return None

    def find_occupied_slots(self, screen, anchor):
        ax, ay = anchor
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        slots = []
        for row in range(SLOT_ROWS):
            for col in range(SLOT_COLS):
                x = ax + col * SLOT_SIZE + 5
                y = ay + row * SLOT_SIZE + 5
                w = min(95, screen.shape[1] - x)
                h = min(95, screen.shape[0] - y)
                if w < 10 or h < 10:
                    continue
                crop = gray[y : y + h, x : x + w]
                if crop.size > 0 and crop.mean() > 22:
                    cx = ax + col * SLOT_SIZE + SLOT_SIZE // 2
                    cy = ay + row * SLOT_SIZE + SLOT_SIZE // 2
                    slots.append((row, col, cx, cy))
        return slots

    def match_slot(self, screen, anchor, row, col):
        """Match one slot against icon database. Returns (name, score, price)."""
        ax, ay = anchor
        x = ax + col * SLOT_SIZE + 5
        y = ay + row * SLOT_SIZE + 5
        crop = screen[y : y + 95, x : x + 95]
        cg = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(cg, 30, 255, cv2.THRESH_BINARY)
        if np.count_nonzero(mask) < 100:
            return None, 0, 0

        # Compute item shape for size bucketing
        ys, xs = np.where(mask > 0)
        item_h = ys.max() - ys.min() + 1 if len(ys) > 0 else 95
        item_w = xs.max() - xs.min() + 1 if len(xs) > 0 else 95
        item_aspect = float(item_w) / item_h if item_h > 0 else 1.0
        item_area = item_w * item_h

        best_name, best_score, best_price = None, 0.0, 0.0
        second_score = 0.0
        for data in self._icons:
            # Fast size filter
            ar_diff = abs(data["aspect"] - item_aspect)
            if ar_diff > 1.5:
                continue
            area_ratio = data["area"] / max(item_area, 1)
            if area_ratio < 0.3 or area_ratio > 3.0:
                continue

            ig = cv2.resize(data["gray"], (cg.shape[1], cg.shape[0]))
            tm = cv2.matchTemplate(cg, ig, cv2.TM_CCOEFF_NORMED)[0][0]

            sm = crop.copy()
            sm[mask == 0] = [0, 0, 0]
            im = cv2.resize(data["img"], (crop.shape[1], crop.shape[0]))
            im[mask == 0] = [0, 0, 0]
            cs = max(
                0,
                1.0
                - np.linalg.norm(
                    np.array(cv2.mean(sm, mask=mask)[:3])
                    - np.array(cv2.mean(im, mask=mask)[:3])
                )
                / 255,
            )
            score = tm * 0.5 + cs * 0.5
            if score > best_score:
                second_score = best_score
                best_score = score
                best_name = data["name"]
                best_price = data["price"]
            elif score > second_score:
                second_score = score

        accept = False
        if best_name and best_score >= MATCH_THRESH:
            accept = True
        elif best_name and best_score >= 0.35 and (best_score - second_score) > 0.03:
            # Close match with clear winner — accept below threshold
            accept = True

        if accept:
            price = best_price
            api_id = best_name.lower().replace(" ", "-").replace("'", "")
            if api_id in self._prices:
                price = self._prices[api_id]
            elif price > 0 and price >= 10 and self._chaos_per_ex > 1:
                price /= self._chaos_per_ex
            return best_name, best_score, price
        return None, best_score, 0

    def match_all_slots(self, screen, anchor, slot_keys):
        """Match all occupied slots. Returns list of (cx, cy, name, price)."""
        results = []
        for row, col, cx, cy in slot_keys:
            name, score, price = self.match_slot(screen, anchor, row, col)
            if name:
                results.append((cx, cy, name, price))
        return results


class RitualWatcher:
    TICK_MS = 2000  # Match every 2 seconds

    def __init__(self, overlay, detector):
        self.overlay = overlay
        self.detector = detector
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._cap = _build_capture()
        self._last_hash = 0
        self._menu_open = False

    def start(self):
        self._timer.start(self.TICK_MS)

    def stop(self):
        self._timer.stop()
        self.overlay.clear()

    def _tick(self):
        try:
            screen = self._cap()
        except Exception:
            return

        anchor = self.detector.find_anchor(screen)
        if anchor is None:
            if self._menu_open:
                self.overlay.clear()
                self._menu_open = False
            return

        self._menu_open = True

        slots = self.detector.find_occupied_slots(screen, anchor)
        h = hash(tuple(sorted((r, c) for r, c, _, _ in slots)))

        if h != self._last_hash:
            self._last_hash = h
            t0 = time.time()
            hits = self.detector.match_all_slots(screen, anchor, slots)
            print(
                f"[ritual] {len(hits)}/{len(slots)} items matched in {time.time()-t0:.1f}s",
                flush=True,
            )
            self.overlay.set_hits(hits)


def _fmt(price):
    if price <= 0:
        return ""
    if price >= 1000:
        return f"{price/1000:.1f}kx"
    if price >= 10:
        return f"{price:.0f}c"
    if price >= 1:
        return f"{price:.1f}c"
    if price >= 0.01:
        return f"{price:.2f}c"
    return f"{price:.3f}c"


def _build_capture():
    try:
        import mss

        sct = mss.mss()

        def cap():
            return cv2.cvtColor(
                np.array(sct.grab(sct.monitors[1])), cv2.COLOR_BGRA2BGR
            )

        return cap
    except ImportError:
        from PIL import ImageGrab

        def cap():
            return cv2.cvtColor(
                np.array(ImageGrab.grab()), cv2.COLOR_RGB2BGR
            )

        return cap