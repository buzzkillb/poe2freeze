"""
Background price refresher. Runs alongside the overlay.
Refreshes currency rates every 5 min, currencies every 15 min,
and full cache every 30 min. Conservative rate limits.
"""
import sys
import time
import signal
from datetime import datetime

from data_sources import DataSourceRegistry


class Refresher:
    def __init__(self, league: str):
        self.registry = DataSourceRegistry(league)
        self.running = True
        self.last_rates = 0
        self.last_currencies = 0
        self.last_full = 0

    def stop(self):
        self.running = False

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {msg}", flush=True)

    def refresh_rates(self):
        try:
            refs = self.registry.scout.fetch_reference_currencies()
            if refs:
                self.log(f"rates: 1ex = {refs.get('chaos', '?'):.2f}c / {refs.get('divine', '?'):.2f}d")
            self.last_rates = time.time()
            return True
        except Exception as e:
            self.log(f"rates FAIL: {e}")
            return False

    def refresh_currencies(self):
        try:
            n = len(self.registry.scout.fetch_all_currency_prices())
            self.log(f"currencies: {n} items updated")
            self.last_currencies = time.time()
            return True
        except Exception as e:
            self.log(f"currencies FAIL: {e}")
            return False

    def refresh_uniques(self):
        try:
            n = len(self.registry.scout.fetch_all_unique_prices())
            self.log(f"uniques: {n} items updated")
            return True
        except Exception as e:
            self.log(f"uniques FAIL: {e}")
            return False

    def refresh_full(self):
        self.log("full warm starting...")
        ok1 = self.refresh_rates()
        time.sleep(2)
        ok2 = self.refresh_currencies()
        time.sleep(2)
        ok3 = self.refresh_uniques()
        if ok1 and ok2 and ok3:
            self.log("full warm complete")
        else:
            self.log("full warm completed with errors")
        self.last_full = time.time()

    def run(self):
        self.log("refresher starting (rates=5min, currencies=15min, uniques/full=30min)")
        self.refresh_full()
        while self.running:
            now = time.time()
            if now - self.last_rates >= 300:
                self.refresh_rates()
                time.sleep(2)
            if now - self.last_currencies >= 900:
                self.refresh_currencies()
                time.sleep(2)
            if now - self.last_full >= 1800:
                self.refresh_full()
            for _ in range(30):
                if not self.running:
                    break
                time.sleep(1)
        self.log("refresher stopped")


def main():
    if len(sys.argv) < 2:
        print("Usage: python refresh.py <league>")
        sys.exit(1)
    league = sys.argv[1]

    r = Refresher(league)

    def handle_sigint(sig, frame):
        r.stop()
    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    try:
        r.run()
    except KeyboardInterrupt:
        r.stop()


if __name__ == "__main__":
    main()