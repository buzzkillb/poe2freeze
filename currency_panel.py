"""
Currency rates panel. Smart display: shows value in exalts,
adds chaos/divine equivalents when relevant. Auto-sorted by value.
"""
import os
import urllib.request
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, QPoint
from PyQt5.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QBrush, QPixmap
from PyQt5.QtWidgets import QLabel, QWidget, QVBoxLayout, QHBoxLayout

from data_sources import Poe2ScoutSource


class CurrencyRatesPanel(QWidget):
    PO2_BG_TOP = QColor(40, 32, 22)
    PO2_BG_BOT = QColor(22, 18, 12)
    PO2_BORDER = QColor(120, 95, 65)
    PO2_BORDER_DARK = QColor(80, 60, 38)
    PO2_GOLD = QColor(205, 165, 95)
    PO2_GOLD_BRIGHT = QColor(255, 210, 130)
    PO2_DIVINE = QColor(190, 140, 230)
    PO2_CHAOS = QColor(170, 230, 255)
    PO2_EXALTED = QColor(255, 200, 100)
    PO2_DIM = QColor(140, 130, 115)
    PO2_TEXT = QColor(200, 190, 170)
    ICON_SIZE = 40

    ICON_CACHE_DIR = Path(__file__).parent / "data" / "icons"

    def __init__(self, league: str = "Runes of Aldur"):
        super().__init__()
        self.league = league
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)

        self._data = {}
        self._currency_keys = [
            "perfect-exalted-orb",
            "perfect-chaos-orb",
            "divine",
            "annul",
            "exalted",
            "chaos",
            "vaal",
            "alch",
        ]
        self._display_names = {
            "perfect-exalted-orb": "Perfect Exalted",
            "perfect-chaos-orb": "Perfect Chaos",
            "divine": "Divine",
            "annul": "Annul",
            "exalted": "Exalted",
            "chaos": "Chaos",
            "vaal": "Vaal",
            "alch": "Alchemy",
        }
        self._icons = {k: None for k in self._currency_keys}
        self._row_widgets = {}  # key -> {"icon": QLabel, "text": QLabel, "layout": QHBoxLayout}
        self._current_order = list(self._currency_keys)  # current display order

        self.ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(20, 16, 20, 16)
        self._main_layout.setSpacing(6)

        self._title = QLabel("Currency Exchange")
        self._title.setStyleSheet(self._title_style())
        self._title.setAlignment(Qt.AlignCenter)
        self._main_layout.addWidget(self._title)

        for key in self._currency_keys:
            self._build_row(key)
            self._main_layout.addLayout(self._row_widgets[key]["layout"])

        self._update_label = QLabel("updating...")
        self._update_label.setStyleSheet(self._update_style())
        self._update_label.setAlignment(Qt.AlignRight)
        self._main_layout.addWidget(self._update_label)

        self.adjustSize()
        self.setFixedSize(self.size())

        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._refresh)
        self._update_timer.start(5 * 60 * 1000)

        self._scout = Poe2ScoutSource(league)
        self._refresh()

    def _row_style(self):
        return (
            "QLabel { background: transparent; color: #c8baa0; "
            "font-family: Serif; font-size: 16px; }"
        )

    def _title_style(self):
        return (
            f"QLabel {{ background: transparent; color: #ffd282; "
            f"font-family: Serif; font-size: 18px; font-weight: bold; }}"
        )

    def _update_style(self):
        return (
            "QLabel { background: transparent; color: #8c8273; "
            "font-family: Serif; font-size: 11px; }"
        )

    def _build_row(self, key: str):
        row = QHBoxLayout()
        row.setSpacing(10)
        icon_label = QLabel()
        icon_label.setFixedSize(self.ICON_SIZE, self.ICON_SIZE)
        icon_label.setStyleSheet("background: transparent;")
        row.addWidget(icon_label)
        text_label = QLabel("loading...")
        text_label.setStyleSheet(self._row_style())
        row.addWidget(text_label)
        row.addStretch()
        self._row_widgets[key] = {"icon": icon_label, "text": text_label, "layout": row}

    def move_to_top_left(self, margin: int = 20):
        from PyQt5.QtWidgets import QApplication
        screen = QApplication.primaryScreen().geometry()
        self.move(QPoint(margin, margin))

    def _refresh(self):
        try:
            self._update_icons()
            self._update_display()
            from datetime import datetime
            self._update_label.setText(f"updated {datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            self._update_label.setText(f"err: {str(e)[:30]}")

    def _update_icons(self):
        for page in range(1, 4):
            url = f"poe2/Leagues/{self._scout.league_encoded}/Currencies/ByCategory?Category=currency&Page={page}"
            data = self._scout._req(url)
            if not data:
                break
            for item in data.get("Items", []):
                api_id = (item.get("ApiId") or "").lower()
                icon_url = item.get("IconUrl")
                if api_id in self._icons and icon_url and self._icons[api_id] is None:
                    self._load_icon(api_id, icon_url)

    def _load_icon(self, api_id: str, url: str):
        try:
            cache_path = self.ICON_CACHE_DIR / f"{api_id}.png"
            if not cache_path.exists():
                req = urllib.request.Request(url, headers={"User-Agent": "mypoeapp/1.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                cache_path.write_bytes(data)
            pixmap = QPixmap(str(cache_path))
            if pixmap.isNull():
                return
            scaled = pixmap.scaled(
                self.ICON_SIZE, self.ICON_SIZE,
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self._icons[api_id] = scaled
            self._row_widgets[api_id]["icon"].setPixmap(scaled)
        except Exception as e:
            print(f"[currency_panel] icon load fail {api_id}: {e}", flush=True)

    def _update_display(self):
        item_by_api = {}
        for page in range(1, 4):
            url = f"poe2/Leagues/{self._scout.league_encoded}/Currencies/ByCategory?Category=currency&Page={page}"
            data = self._scout._req(url)
            if not data:
                break
            for item in data.get("Items", []):
                api = (item.get("ApiId") or "").lower()
                if api in self._currency_keys:
                    price = item.get("CurrentPrice", 0)
                    if price > 0:
                        item_by_api[api] = price
        refs = self._scout.fetch_reference_currencies()
        if not refs:
            self._update_label.setText("rates unavailable")
            return
        chaos_per_ex = refs.get("chaos", 1)
        divine_per_ex = refs.get("divine", 1)
        if chaos_per_ex <= 1 or divine_per_ex <= 1:
            self._update_label.setText("rates incomplete")
        sorted_keys = sorted(
            [k for k in self._currency_keys if k in item_by_api],
            key=lambda k: item_by_api[k],
            reverse=True,
        )
        for key in self._currency_keys:
            if key not in item_by_api:
                continue
            widgets = self._row_widgets[key]
            ex_price = item_by_api[key]
            name = self._display_names.get(key, key)
            parts = [f"<b>{name}:</b>"]
            parts.append(f"<span style='color:{self._color_to_hex(self.PO2_GOLD_BRIGHT)}'>{ex_price:.1f}ex</span>")
            if ex_price >= chaos_per_ex:
                chaos_amt = ex_price / chaos_per_ex
                parts.append(f"<span style='color:{self._color_to_hex(self.PO2_CHAOS)}'>{chaos_amt:.0f}c</span>")
            if ex_price >= divine_per_ex:
                divine_amt = ex_price / divine_per_ex
                parts.append(f"<span style='color:{self._color_to_hex(self.PO2_DIVINE)}'>{divine_amt:.1f}d</span>")
            widgets["text"].setText("  ".join(parts))
        if sorted_keys != self._current_order:
            self._reorder_rows(sorted_keys)
            self._current_order = sorted_keys

    def _reorder_rows(self, new_order):
        title_index = self._main_layout.indexOf(self._title)
        for i, key in enumerate(new_order):
            layout = self._row_widgets[key]["layout"]
            self._main_layout.removeItem(layout)
            self._main_layout.insertLayout(title_index + 1 + i, layout)
        update_index = self._main_layout.indexOf(self._update_label)
        self._main_layout.removeWidget(self._update_label)
        self._main_layout.addWidget(self._update_label)
        self._main_layout.update()
        self.adjustSize()
        self.setFixedSize(self.size())

    def _color_to_hex(self, color: QColor) -> str:
        return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        bg_gradient = QLinearGradient(0, 0, 0, h)
        bg_gradient.setColorAt(0, QColor(40, 32, 22, 245))
        bg_gradient.setColorAt(1, QColor(22, 18, 12, 245))
        painter.setBrush(QBrush(bg_gradient))
        painter.setPen(QPen(self.PO2_BORDER, 2))
        painter.drawRoundedRect(1, 1, w - 2, h - 2, 4, 4)

        painter.setPen(QPen(self.PO2_BORDER_DARK, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(5, 5, w - 10, h - 10, 2, 2)

        accent = QLinearGradient(0, 0, w, 0)
        accent.setColorAt(0, QColor(255, 215, 130, 0))
        accent.setColorAt(0.3, QColor(255, 215, 130, 200))
        accent.setColorAt(0.7, QColor(255, 215, 130, 200))
        accent.setColorAt(1, QColor(255, 215, 130, 0))
        painter.setPen(QPen(accent, 1))
        painter.drawLine(8, 5, w - 8, 5)
        painter.drawLine(8, h - 5, w - 8, h - 5)