"""
PoE2-styled price overlay. Custom-painted background with QLabel for text.
"""
from PyQt5.QtCore import QPoint, Qt, QTimer
from PyQt5.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPen, QBrush,
                          QLinearGradient)
from PyQt5.QtWidgets import QLabel, QWidget


class PriceOverlay(QWidget):
    PO2_BG_TOP = QColor(40, 32, 22)
    PO2_BG_BOT = QColor(22, 18, 12)
    PO2_BORDER = QColor(120, 95, 65)
    PO2_BORDER_DARK = QColor(80, 60, 38)
    PO2_GOLD = QColor(205, 165, 95)
    PO2_GOLD_BRIGHT = QColor(255, 210, 130)
    PO2_UNIQUE = QColor(195, 130, 60)
    PO2_RARE = QColor(225, 200, 100)
    PO2_MAGIC = QColor(110, 160, 220)
    PO2_NORMAL = QColor(200, 200, 200)
    PO2_CURRENCY = QColor(170, 230, 255)
    PO2_CORRUPTED = QColor(210, 40, 40)
    PO2_GEM = QColor(80, 220, 180)
    PO2_DIVINE = QColor(190, 140, 230)
    PO2_TEXT = QColor(200, 190, 170)
    PO2_DIM = QColor(140, 130, 115)
    PO2_ACCENT = QColor(255, 215, 130)

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

        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._label.setWordWrap(False)
        self._label.setTextInteractionFlags(Qt.NoTextInteraction)
        font = QFont("Serif", 16, QFont.Bold)
        self._label.setFont(font)
        self._label.setStyleSheet("QLabel { background: transparent; }")

        self._lines = []
        self._title_color = self.PO2_GOLD_BRIGHT
        self._padding = 22

        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)

        self._current_text = ""
        self.hide()
        self.setMinimumWidth(200)

    def show_at(self, pos: QPoint, text: str, duration_ms: int = 3500):
        if text == self._current_text and self.isVisible():
            self.hide_timer.start(duration_ms)
            return

        self._current_text = text
        self._lines = text.split("\n") if text else []
        if self._lines:
            self._title_color = self._rarity_color(self._lines[0])

        self._label.setText(self._format_html(text))
        self._label.adjustSize()
        self._update_size()
        self.move(pos + QPoint(20, 20))

        if not self.isVisible():
            self.show()
        self.raise_()

        if self.hide_timer.isActive():
            self.hide_timer.stop()
        self.hide_timer.start(duration_ms)

    def _update_size(self):
        if not self._lines:
            return
        font = QFont("Serif", 16, QFont.Bold)
        fm = QFontMetrics(font)
        max_w = max(fm.horizontalAdvance(line) for line in self._lines) + self._padding * 2
        line_h = fm.height() + 4
        h = line_h * len(self._lines) + self._padding * 2
        self.resize(max_w, h)
        self._label.setGeometry(self._padding, self._padding,
                                max_w - self._padding * 2,
                                h - self._padding * 2)

    def _rarity_color(self, line: str) -> QColor:
        if "[UNIQUE]" in line:
            return self.PO2_UNIQUE
        if "[RARE]" in line:
            return self.PO2_RARE
        if "[CURRENCY]" in line:
            return self.PO2_CURRENCY
        if "[GEM]" in line:
            return self.PO2_GEM
        if "[DIVINATION CARD]" in line:
            return self.PO2_DIVINE
        if "[MAGIC]" in line:
            return self.PO2_MAGIC
        return self.PO2_GOLD_BRIGHT

    def _format_html(self, text: str) -> str:
        if not text:
            return ""
        lines = text.split("\n")
        if not lines:
            return ""
        title_color = self._color_to_hex(self._title_color)
        title = self._esc(lines[0])
        html = f'<div style="color: {title_color}; font-size: 24px; font-weight: bold; margin-bottom: 8px; font-family: Serif;">{title}</div>'
        for line in lines[1:]:
            if "corrupted" in line.lower():
                line_color = self.PO2_CORRUPTED
            elif "ex" in line and "/" in line and "Tier" not in line:
                line_color = self.PO2_ACCENT
            elif line.startswith("  "):
                line_color = self.PO2_DIM
            else:
                line_color = self.PO2_TEXT
            html += f'<div style="color: {self._color_to_hex(line_color)}; font-family: Serif; font-size: 15px;">{self._esc(line)}</div>'
        return html

    def _color_to_hex(self, color: QColor) -> str:
        return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"

    def _esc(self, text: str) -> str:
        return (text.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;"))

    def paintEvent(self, event):
        if not self._lines:
            return
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