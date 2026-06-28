"""
Ritual overlay — automatic icon matching from poe2scout database.

No OCR. No user interaction. Detects items in ritual grid automatically
via combined template + color matching against downloaded icon database.
"""
from __future__ import annotations

import json, time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2, numpy as np
import threading

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
CROP_SIZE = 95
MATCH_THRESH = 0.40
FALLBACK_THRESH = 0.35
SECOND_MARGIN = 0.03
ALPHA_THRESH = 40
MASK_THRESH = 30
MASK_MIN_PIXELS = 100
OCCUPIED_MEAN_THRESH = 22
GRID_MEAN_THRESH = 20
ASPECT_TOLERANCE = 1.5
AREA_MIN_RATIO = 0.3
AREA_MAX_RATIO = 3.0
BG_COLOR = (12, 10, 8)


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
        screens = QApplication.screens()
        if screens:
            # Cover all screens for multi-monitor
            x0 = min(s.geometry().x() for s in screens)
            y0 = min(s.geometry().y() for s in screens)
            x1 = max(s.geometry().x() + s.geometry().width() for s in screens)
            y1 = max(s.geometry().y() + s.geometry().height() for s in screens)
            self.setGeometry(x0, y0, x1 - x0, y1 - y0)
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
    def __init__(self, scout, league=None):
        import config
        self.league = league or config.LEAGUE
        self._scout = scout

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
        self._fetch_prices()

    def _load_icons(self):
        if not DB_PATH.exists():
            print("[ritual] WARNING: icon database not found", flush=True)
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
                m = (a > ALPHA_THRESH).astype(np.uint8) * 255
                fg = cv2.merge([b, g, r])
                bg = np.full(img.shape[:2] + (3,), BG_COLOR, dtype=np.uint8)
                comp = fg.copy()
                comp[m == 0] = bg[m == 0]
                img = comp
            h, wi = img.shape[:2]
            # Pre-resize to standard crop size for fast matching
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            gray_rs = cv2.resize(gray, (CROP_SIZE, CROP_SIZE))
            img_rs = cv2.resize(img, (CROP_SIZE, CROP_SIZE))
            # Precompute template stats for normalized correlation
            t_mean = float(gray_rs.mean())
            t_std = float(gray_rs.std())
            icon_list.append({
                "name": name,
                "img": img_rs,
                "gray": gray_rs,
                "gray_flat": gray_rs.ravel().astype(np.float32) - t_mean,
                "gray_std": t_std if t_std > 0 else 1.0,
                "price": item.get("currentPrice", 0),
                "aspect": float(wi) / h if h > 0 else 1.0,
                "area": h * wi,
            })
        self._icons = icon_list
        print(f"[ritual] Loaded {len(self._icons)} icon templates", flush=True)

    def _fetch_prices(self):
        fetched = 0
        try:
            for it in self._scout.fetch_items_by_category("ritual", "Currencies"):
                aid = it.get("ApiId")
                if aid and it.get("CurrentPrice") is not None:
                    self._prices[aid] = float(it["CurrentPrice"])
                    fetched += 1
            for it in self._scout.fetch_all_items():
                n = it.get("Name") or ""
                aid = n.lower().replace("'", "").replace(" ", "-")
                if aid and it.get("CurrentPrice") is not None and aid not in self._prices:
                    self._prices[aid] = float(it["CurrentPrice"])
                    fetched += 1
        except Exception as e:
            print(f"[ritual] Price fetch error: {e}", flush=True)
        print(f"[ritual] {fetched} prices loaded", flush=True)

    def find_anchor(self, screen):
        """Find ritual grid top-left corner. Uses known positions scaled to screen resolution."""
        if screen is None:
            return None
        h, w = screen.shape[:2]
        # Scale known 4K anchor positions to current resolution
        sx = w / 3840
        sy = h / 2160
        for ax, ay in [(453, 682), (400, 680), (350, 680)]:
            ax = int(ax * sx)
            ay = int(ay * sy)
            if ax < 0 or ay < 0 or ax + 200 >= w or ay + 300 >= h:
                continue
            check = screen[ay : ay + 300, ax : ax + 200]
            gray = cv2.cvtColor(check, cv2.COLOR_BGR2GRAY)
            if gray.mean() > GRID_MEAN_THRESH:
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
                w = min(CROP_SIZE, screen.shape[1] - x)
                h = min(CROP_SIZE, screen.shape[0] - y)
                if w < 10 or h < 10:
                    continue
                crop = gray[y : y + h, x : x + w]
                if crop.size > 0 and crop.mean() > OCCUPIED_MEAN_THRESH:
                    cx = ax + col * SLOT_SIZE + SLOT_SIZE // 2
                    cy = ay + row * SLOT_SIZE + SLOT_SIZE // 2
                    slots.append((row, col, cx, cy))
        return slots

    def match_slot(self, screen, anchor, row, col):
        """Match one slot against icon database. Returns (name, score, price)."""
        ax, ay = anchor
        x = ax + col * SLOT_SIZE + 5
        y = ay + row * SLOT_SIZE + 5
        cw = min(CROP_SIZE, screen.shape[1] - x)
        ch = min(CROP_SIZE, screen.shape[0] - y)
        if cw < 10 or ch < 10:
            return None, 0, 0
        crop = screen[y : y + ch, x : x + cw]
        cg = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(cg, MASK_THRESH, 255, cv2.THRESH_BINARY)
        if np.count_nonzero(mask) < MASK_MIN_PIXELS:
            return None, 0, 0

        # Compute item shape for size bucketing
        ys, xs = np.where(mask > 0)
        item_h = ys.max() - ys.min() + 1 if len(ys) > 0 else CROP_SIZE
        item_w = xs.max() - xs.min() + 1 if len(xs) > 0 else CROP_SIZE
        item_aspect = float(item_w) / item_h if item_h > 0 else 1.0
        item_area = item_w * item_h

        # Resize crop and mask to match precomputed icon size
        cg_rs = cv2.resize(cg, (CROP_SIZE, CROP_SIZE))
        crop_rs = cv2.resize(crop, (CROP_SIZE, CROP_SIZE))
        mask_rs = cv2.resize(mask, (CROP_SIZE, CROP_SIZE))

        best_name, best_score, best_price = None, 0.0, 0.0
        second_score = 0.0

        # Precompute crop stats once per slot for fast correlation
        crop_f = cg_rs.ravel().astype(np.float32)
        c_mean = float(crop_f.mean())
        c_norm = float(crop_f.std()) or 1.0
        c_centered = crop_f - c_mean

        for data in self._icons:
            ar_diff = abs(data["aspect"] - item_aspect)
            if ar_diff > ASPECT_TOLERANCE:
                continue
            area_ratio = data["area"] / max(item_area, 1)
            if area_ratio < AREA_MIN_RATIO or area_ratio > AREA_MAX_RATIO:
                continue

            # Fast correlation using precomputed template stats
            num = np.dot(data["gray_flat"], c_centered)
            den = data["gray_std"] * c_norm * len(c_centered)
            tm = num / den if den > 1e-9 else 0.0

            # Early exit: skip expensive color calc if TM can't beat threshold
            max_possible = tm * 0.5 + 0.5  # best-case CS=1.0
            if max_possible < MATCH_THRESH and max_possible < best_score:
                continue

            # Color similarity using resized mask on resized crop
            cs = max(0, 1.0 - np.linalg.norm(
                np.array(cv2.mean(crop_rs, mask=mask_rs)[:3]) -
                np.array(cv2.mean(data["img"], mask=mask_rs)[:3])
            ) / 255)
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
        elif best_name and best_score >= FALLBACK_THRESH and (best_score - second_score) > SECOND_MARGIN:
            accept = True

        if accept:
            price = best_price
            api_id = best_name.lower().replace(" ", "-").replace("'", "")
            if api_id in self._prices:
                price = self._prices[api_id]
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
    TICK_MS = 2000

    def __init__(self, overlay, detector):
        self.overlay = overlay
        self.detector = detector
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._cap = _build_capture()
        self._last_hash = 0
        self._menu_open = False
        self._matching = False
        self._match_ready: Optional[Tuple[int, List]] = None

    def start(self):
        self._timer.start(self.TICK_MS)

    def stop(self):
        self._timer.stop()
        self.overlay.clear()

    def _tick(self):
        try:
            screen = self._cap()
        except Exception as e:
            if not hasattr(self, "_cap_err_count"):
                self._cap_err_count = 0
            self._cap_err_count += 1
            if self._cap_err_count <= 1:
                print(f"[ritual] Screen capture error: {e}", flush=True)
            return
        else:
            self._cap_err_count = 0

        anchor = self.detector.find_anchor(screen)
        if anchor is None:
            if self._menu_open:
                self.overlay.clear()
                self._menu_open = False
            return

        self._menu_open = True

        slots = self.detector.find_occupied_slots(screen, anchor)
        h = hash(tuple(sorted((r, c) for r, c, _, _ in slots)))

        # Pick up completed background match results (only if hash matches)
        if self._match_ready is not None:
            ready_hash, hits = self._match_ready
            self._match_ready = None
            if ready_hash == h:
                print(f"[ritual] {len(hits)}/{len(slots)} items matched", flush=True)
                self.overlay.set_hits(hits)

        # Kick off new match if grid changed and not already matching
        if h != self._last_hash:
            self._last_hash = h
            if not self._matching:
                self._matching = True
                screen_copy = screen.copy()
                anchor_copy = anchor
                slots_copy = list(slots)
                tag_hash = h

                def match_worker():
                    try:
                        hits = self.detector.match_all_slots(
                            screen_copy, anchor_copy, slots_copy
                        )
                        self._match_ready = (tag_hash, hits)
                    finally:
                        self._matching = False

                threading.Thread(target=match_worker, daemon=True).start()


def _fmt(price):
    if price <= 0:
        return ""
    if price >= 1000:
        return f"{price/1000:.1f}kx"
    if price >= 10:
        return f"{price:.0f}"
    if price >= 1:
        return f"{price:.1f}"
    if price >= 0.01:
        return f"{price:.2f}"
    return f"{price:.3f}"


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