"""
PoE2 Ninja Pricer - main entry point.
Polls clipboard for changes, prices, shows.
"""
import sys
import time
import threading
from typing import Dict

from PyQt5.QtCore import QPoint, QTimer, Qt
from PyQt5.QtGui import QColor, QCursor
from PyQt5.QtWidgets import (QApplication, QLabel, QMenu, QSystemTrayIcon,
                              QWidget, QVBoxLayout, QPushButton)

# pynput was previously imported here for a key listener; the
# architecture is now polling-based via Pricer._poll(), so no key
# listener is needed. pynput is no longer a runtime dependency.

from cache import init_db
from clipboard import get_clipboard_text_safe
from config import DEFAULT_HOTKEY, LEAGUE
from overlay_widget import PriceOverlay
from pricer import price_text
from currency_panel import CurrencyRatesPanel


def _format_display(result: Dict) -> tuple:
    if "error" in result and "normalized" not in result:
        return f"ERR: {result['error']}", QColor(255, 100, 100)
    parsed = result.get("parsed_item", {})
    name = parsed.get("name") or ""
    base = parsed.get("base") or ""
    rarity = parsed.get("rarity", "?")
    display_name = name if name else base
    display_base = base if name else ""
    normalized = result.get("normalized", {})
    age = result.get("age_seconds", 0)
    cached = result.get("cached", False)
    count = result.get("listing_count", 0)
    corrupted = parsed.get("corrupted", False) or result.get("corrupted", False)
    tier = result.get("tier", 0)
    gem_level = parsed.get("level", 0)
    quality = parsed.get("quality", 0)
    source = result.get("source", "unknown")
    if not normalized:
        return f"{display_name} [{rarity}]\nno price data", QColor(180, 180, 180)
    chaos = normalized.get("chaos", 0)
    divine = normalized.get("divine", 0)
    exalted = normalized.get("exalted", 0)
    age_str = "fresh" if age == 0 else f"{age // 60}m" if age < 3600 else f"{age // 3600}h"
    cache_marker = " *" if cached else ""
    parts = [f"{display_name} [{rarity}]"]
    if display_base and display_base != display_name:
        parts.append(f"({display_base})")
    if corrupted:
        parts.append("(corrupted)")
    if tier:
        parts.append(f"Tier {tier}")
    if gem_level:
        parts.append(f"L{gem_level}/Q{quality}")
    parts.append(f"{_fmt_currency(exalted)}ex  ({_fmt_currency(chaos)}c / {_fmt_currency(divine)}d)")
    parts.append(f"n={count} {age_str}{cache_marker} [{source}]")
    listings = result.get("listings", [])
    if listings:
        parts.append("---")
        for i, l in enumerate(listings[:10]):
            px = _fmt_currency(l["price_exalted"])
            rel = l.get("time_ago", "?")
            parts.append(f"  {i+1}. {px}ex ({l['amount']} {l['currency']}) {rel}")
    text = "\n".join(parts)
    if exalted >= 100:
        color = QColor(255, 75, 75)
    elif exalted >= 10:
        color = QColor(255, 165, 0)
    elif exalted >= 1:
        color = QColor(255, 255, 100)
    else:
        color = QColor(150, 150, 150)
    return text, color


def _fmt_currency(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}m"
    if value >= 10_000:
        return f"{value / 1000:.1f}k"
    if value >= 100:
        return f"{value:.0f}"
    if value >= 10:
        return f"{value:.1f}"
    if value >= 1:
        return f"{value:.2f}"
    return f"{value:.3f}"


class StatusWindow(QWidget):
    def __init__(self, hotkey: str):
        super().__init__()
        self.setWindowTitle("PoE2 Ninja Pricer")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        layout = QVBoxLayout()
        hotkey_display = "Ctrl+C" if hotkey == "ctrl_c" else hotkey.upper()
        self.label = QLabel(f"READY - press <b>{hotkey_display}</b> in PoE2 on an item")
        self.label.setStyleSheet("padding: 8px; font-size: 12px;")
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.setLayout(layout)
        self.adjustSize()
        self.setFixedWidth(360)
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - self.width() - 20, 20)


class Pricer:
    def __init__(self, overlay, app, status):
        self.overlay = overlay
        self.app = app
        self.status = status
        self._last_clipboard_hash = None
        self._busy = False
        self._current_job = 0
        self._pending_show_text = None
        self._pending_show_event = threading.Event()
        self._pending_lock = threading.Lock()
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(100)

    def _poll(self):
        if self._busy:
            return
        text = get_clipboard_text_safe()
        if not text or "Rarity:" not in text:
            return
        text_hash = hash(text)
        if text_hash == self._last_clipboard_hash:
            return
        self._last_clipboard_hash = text_hash
        self._current_job += 1
        self._busy = True
        job = self._current_job
        preview = text.split('\n')[1] if len(text.split('\n')) > 1 else ''
        print(f"[poll] new item detected, job {job}, {preview[:30]!r}", flush=True)
        if self.status:
            self.status.label.setText(f"Last: pricing {preview[:30]}...")
        self.overlay.show_at(QCursor.pos(), "Pricing...", 30000)
        threading.Thread(target=self._price, args=(text, job), daemon=True).start()

    def _price(self, text, job):
        try:
            result = price_text(text)
            display, color = _format_display(result)
            with self._pending_lock:
                if self._current_job == job:
                    self._pending_show_text = (display, color)
                    self._pending_show_event.set()
                    print(f"[price] job {job} ready: {display[:60]!r}", flush=True)
                else:
                    print(f"[price] job {job} superseded", flush=True)
        except Exception as e:
            import traceback
            print(f"[price] CRASH: {e}\n{traceback.format_exc()}", flush=True)
            err_msg = f"PRICING FAILED\n{type(e).__name__}: {str(e)[:100]}"
            with self._pending_lock:
                if self._current_job == job:
                    self._pending_show_text = (err_msg, None)
                    self._pending_show_event.set()
        finally:
            self._busy = False

    def check_pending(self):
        if self._pending_show_event.is_set():
            with self._pending_lock:
                data = self._pending_show_text
                self._pending_show_text = None
            self._pending_show_event.clear()
            if data:
                display, color = data
                self.overlay.show_at(QCursor.pos(), display, 3500)
                if self.status:
                    self.status.label.setText(f"Last: {display.split(chr(10))[0]}")


def main(hotkey: str = None):
    init_db()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    overlay = PriceOverlay()
    overlay.show_at(QPoint(100, 100), "PoE2 Ninja Pricer\nREADY", 2000)

    currency_panel = CurrencyRatesPanel(LEAGUE)
    currency_panel.move_to_top_left()
    currency_panel.show()

    if hotkey is None:
        hotkey = DEFAULT_HOTKEY

    print(f"[overlay] starting, mode=poll-clipboard", flush=True)

    status = StatusWindow(hotkey)
    status.show()
    status.raise_()

    pricer = Pricer(overlay, app, status)

    pending_timer = QTimer()
    pending_timer.timeout.connect(pricer.check_pending)
    pending_timer.start(50)

    ritual_overlay_w = None
    ritual_watcher = None

    def _start_ritual_watcher():
        global ritual_overlay_w, ritual_watcher
        try:
            from ritual_overlay import RitualPriceOverlay, RitualDetector, RitualWatcher
            print("[overlay] importing ritual detector...", flush=True)
            ritual_detector = RitualDetector(LEAGUE)
            print("[overlay] ritual detector ready", flush=True)
            ritual_overlay_w = RitualPriceOverlay()
            ritual_watcher = RitualWatcher(ritual_overlay_w, ritual_detector)
            ritual_watcher.start()
            print(f"[overlay] ritual watcher armed (hover+OCR)", flush=True)
        except Exception as e:
            import traceback
            print(f"[overlay] ritual watcher disabled: {e}", flush=True)
            print(traceback.format_exc(), flush=True)

    # Defer the ritual watcher initialization to allow other libraries to settle
    QTimer.singleShot(2000, _start_ritual_watcher)

    if QSystemTrayIcon.isSystemTrayAvailable():
        try:
            tray = QSystemTrayIcon()
            tray.setIcon(app.style().standardIcon(app.style().SP_ComputerIcon))
            menu = QMenu()
            menu.addAction("PoE2 Ninja Pricer").setEnabled(False)
            menu.addSeparator()
            menu.addAction("Quit").triggered.connect(app.quit)
            tray.setContextMenu(menu)
            tray.setToolTip("PoE2 Ninja Pricer")
            tray.show()
        except Exception:
            pass

    print(f"[overlay] READY. Hover item in PoE2 + Ctrl+C.", flush=True)
    sys.exit(app.exec_())


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--hotkey", default=DEFAULT_HOTKEY)
    args = parser.parse_args()
    main(args.hotkey)