"""
Ground loot price overlay.
Shows prices on filter-highlighted drops using poe2filter.com color rules.

How it works:
1. Scans screen for the filter's highlight colors (purple, brown, red, orange, etc.)
2. For each highlight, captures the region and OCRs the item name text
3. Looks up the price from pre-cached poe2scout database
4. Draws price labels on a transparent Qt overlay
5. Prices persist until the item disappears (picked up)

No game memory reading. Uses the poe2filter visual output as the trigger.
"""
from __future__ import annotations

import os
import sys
import time
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QBrush
from PyQt5.QtWidgets import QApplication, QWidget

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from data_sources import Poe2ScoutSource


# ── Filter highlight colors ──────────────────────────────────────
# These are the poe2filter.com color ranges (HSV)
FILTER_RANGES = [
    ("purple",   np.array([130, 80, 150]), np.array([160, 255, 255])),  # S-tier
    ("brown",    np.array([5, 80, 120]),   np.array([20, 255, 230])),   # Excellent unique
    ("red",      np.array([170, 100, 100]),np.array([10, 255, 200])),   # A-tier
    ("orange",   np.array([7, 80, 120]),   np.array([25, 255, 230])),   # Good tier
    ("yellow",   np.array([25, 80, 150]),  np.array([40, 255, 255])),   # Currency
    ("white",    np.array([0, 0, 180]),    np.array([180, 30, 255])),   # D-tier
]

TMPDIR = Path(tempfile.gettempdir()) / "poe2_loot_ocr"
TMPDIR.mkdir(exist_ok=True)
OCR_WORKER = str(ROOT / "ocr_worker.py")


def ocr_image(img: np.ndarray) -> str:
    """Run EasyOCR via subprocess to avoid PyQt5 DLL conflict."""
    if img.size == 0 or img.shape[0] < 10 or img.shape[1] < 10:
        return ""
    path = TMPDIR / "loot_crop.png"
    cv2.imwrite(str(path), img)
    try:
        import subprocess
        r = subprocess.run([sys.executable, OCR_WORKER, "ocr", str(path)],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            text = r.stdout.strip()
            return text
    except Exception as e:
        pass
    return ""


class LootOverlay(QWidget):
    """Transparent overlay showing price labels on ground items."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
            Qt.Tool | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        screen = QApplication.primaryScreen()
        geo = screen.geometry() if screen else (0, 0, 1920, 1080)
        self.setGeometry(geo)

        self._labels: List[Tuple[int, int, str, float]] = []
        self.show()

    def set_labels(self, labels: List[Tuple[int, int, str, float]]):
        self._labels = labels
        self.update()

    def paintEvent(self, event):
        if not self._labels:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont("Serif", 13, QFont.Bold)
        painter.setFont(font)
        fm = QFontMetrics(font)
        for x, y, name, price in self._labels:
            txt = _fmt(price) if price > 0 else name[:20]
            tw = fm.horizontalAdvance(txt) + 14
            th = fm.height() + 8
            lx, ly = x - tw // 2, y - th - 4
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(15, 12, 8, 230)))
            painter.drawRoundedRect(lx, ly, tw, th, 4, 4)
            painter.setPen(QPen(QColor(255, 210, 130), 1))
            painter.drawText(lx + 7, ly + fm.ascent() + 4, txt)


def _fmt(p: float) -> str:
    if p <= 0:
        return ""
    if p >= 10000:
        return f"{p/1000:.1f}k ex"
    if p >= 100:
        return f"{p:.0f} ex"
    if p >= 1:
        return f"{p:.1f} ex"
    return f"{p:.2f} ex"


class GroundPriceScanner:
    """Main loop: capture, detect, OCR, price lookup, display."""

    def __init__(self, league="Runes of Aldur"):
        self._overlay = LootOverlay()

        # Price DB
        self._scout = Poe2ScoutSource(league)
        self._prices: Dict[str, float] = {}
        self._refresh_prices()
        self._last_refresh = time.time()

        # Tracked items (persist across frames)
        self._items: Dict[str, Tuple[Tuple[int, int, int, int], float]] = {}

        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    def _refresh_prices(self):
        # Fetch current ritual + unique prices
        try:
            # Get all currency (runes, essences, etc)
            for api, entry in self._scout.fetch_all_currency_prices().items():
                if entry.get("current_price_exalted"):
                    self._prices[entry.get("name", "").lower()] = float(entry["current_price_exalted"])
            # Get all uniques
            for api, entry in self._scout.fetch_all_unique_prices().items():
                if entry.get("current_price_exalted"):
                    self._prices[api.lower()] = float(entry["current_price_exalted"])
        except Exception as e:
            print(f"[loot] price refresh: {e}", flush=True)

    def lookup(self, name: str) -> float:
        n = name.lower().strip()
        # Direct match
        if n in self._prices:
            return self._prices[n]
        # Try slugified match
        slug = n.replace(" ", "-").replace("'", "")
        if slug in self._prices:
            return self._prices[slug]
        # Try partial match
        for k, v in self._prices.items():
            if n in k or k in n:
                return v
        return 0.0

    def _tick(self):
        # Refresh prices on the hour mark
        if time.time() - self._last_refresh > 3600:
            be = int(time.time()) % 3600
            if be < 120:  # within 2 min of hour
                self._refresh_prices()
                self._last_refresh = time.time()

        import mss
        try:
            with mss.mss() as sct:
                raw = np.array(sct.grab(sct.monitors[1]))
                frame = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
        except Exception as e:
            return

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        found_names = []

        # Scan for each filter color
        for name, lo, hi in FILTER_RANGES:
            mask = cv2.inRange(hsv, lo, hi)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                if w * h < 500:
                    continue
                # Expand region to capture text around the color
                ox = max(0, x - 30)
                oy = max(0, y - 30)
                ow = min(frame.shape[1] - ox, w + 60)
                oh = min(frame.shape[0] - oy, h + 60)
                region = frame[oy:oy + oh, ox:ox + ow]
                if region.size == 0:
                    continue

                text = ocr_image(region)
                if not text or len(text) < 3:
                    continue

                price = self.lookup(text)
                # Also try first "word" as item name (filter text sometimes includes tier info)
                first_word = text.split()[0] if text.split() else text
                if price == 0 and first_word != text:
                    price = self.lookup(first_word)

                key = text.lower().strip()
                self._items[key] = ((ox, oy, ow, oh), price)
                found_names.append(key)

        # Remove items no longer visible
        to_remove = []
        for key, (bbox, price) in self._items.items():
            bx, by, bw, bh = bbox
            if 0 <= by < frame.shape[0] and 0 <= bx < frame.shape[1]:
                crop = frame[by:min(by + bh, frame.shape[0]), bx:min(bx + bw, frame.shape[1])]
                if crop.size > 0:
                    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                    if gray.mean() > 30:
                        continue
            to_remove.append(key)

        for key in to_remove:
            del self._items[key]

        # Build display labels
        labels = []
        for key, (bbox, price) in self._items.items():
            bx, by, bw, bh = bbox
            cx, cy = bx + bw // 2, by + bh // 2
            labels.append((cx, cy, key, price))

        self._overlay.set_labels(labels)


def main():
    app = QApplication(sys.argv)
    scanner = GroundPriceScanner()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
