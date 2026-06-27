"""
Anonymous client for PoE2's trade2 API.
"""
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

from config import LEAGUE, TRADE_BASE, USER_AGENT
from cache import log_request


class RateLimiter:
    def __init__(self, max_per_second: float = 4.0):
        self.min_interval = 1.0 / max_per_second
        self.last_request = 0.0

    def wait(self):
        elapsed = time.time() - self.last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request = time.time()


_limiter = RateLimiter(max_per_second=4.0)


def _request(
    method: str,
    path: str,
    body: Optional[Dict] = None,
    timeout: int = 15,
    max_retries: int = 2,
) -> Tuple[Optional[Dict], Optional[str], int]:
    url = TRADE_BASE + path
    data = None
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if body is not None:
        import json
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    for attempt in range(max_retries + 1):
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        _limiter.wait()
        start = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
                raw = resp.read()
                latency = int((time.time() - start) * 1000)
                log_request(path, status, latency)
                if status == 429:
                    retry_after = int(resp.headers.get("Retry-After", "5"))
                    time.sleep(min(retry_after, 30))
                    continue
                try:
                    import json
                    return json.loads(raw), None, status
                except Exception:
                    return None, f"invalid json from {path}", status
        except urllib.error.HTTPError as e:
            latency = int((time.time() - start) * 1000)
            log_request(path, e.code, latency)
            body_text = e.read().decode("utf-8", errors="ignore")
            if e.code == 429:
                retry_after = int(e.headers.get("Retry-After", "5"))
                time.sleep(min(retry_after, 30))
                continue
            return None, f"HTTP {e.code}: {body_text[:200]}", e.code
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            log_request(path, 0, latency)
            return None, str(e), 0
        return None, "exhausted retries", 0


def exchange_search(have: List[str], want: List[str], league: str = None) -> Optional[Dict]:
    league = league or LEAGUE
    encoded_league = urllib.parse.quote(league, safe="")
    body = {
        "engine": "new",
        "query": {
            "status": {"option": "online"},
            "have": have,
            "want": want,
        },
        "sort": {"have": "asc"},
    }
    data, err, status = _request("POST", f"/api/trade2/exchange/{encoded_league}", body)
    return data


def search_items(query: Dict, league: str = None) -> Optional[Dict]:
    league = league or LEAGUE
    encoded_league = urllib.parse.quote(league, safe="")
    body = {"query": query, "sort": {"price": "asc"}}
    data, err, status = _request("POST", f"/api/trade2/search/{encoded_league}", body)
    return data


def fetch_results(query_id: str, ids: List[str], league: str = None) -> Optional[Dict]:
    league = league or LEAGUE
    encoded_league = urllib.parse.quote(league, safe="")
    if not ids:
        return None
    ids_param = ",".join(ids[:10])
    data, err, status = _request("GET", f"/api/trade2/fetch/{ids_param}?query={query_id}")
    return data