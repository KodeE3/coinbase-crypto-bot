"""Public HTTPS GET only, bounded responses and no redirects or credentials."""
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from .model import iso

KALSHI = "https://external-api.kalshi.com/trade-api/v2"
COINBASE = "https://api.exchange.coinbase.com"


class DataError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DataError("provider redirect refused")


class PublicData:
    def __init__(self, opener=None):
        self.opener = opener or build_opener(NoRedirect())

    def _get(self, base, path, params=None):
        if base not in (KALSHI, COINBASE):
            raise DataError("unapproved provider")
        url = base + path + ("?" + urlencode(params) if params else "")
        request = Request(url, method="GET", headers={
            "User-Agent": "prediction-paper/0.1", "Accept": "application/json",
            "Cache-Control": "no-cache"})
        started = time.monotonic()
        try:
            with self.opener.open(request, timeout=10) as response:
                if response.status != 200:
                    raise DataError("provider returned a non-200 response")
                if int(response.headers.get("Age", "0")) > 15:
                    raise DataError("cached provider response is stale")
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000 or time.monotonic() - started > 10:
                raise DataError("provider response exceeded size/time limit")
            return json.loads(raw)
        except HTTPError as exc:
            raise DataError(f"provider HTTP {exc.code}; request failed") from None
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise DataError("provider unavailable or invalid JSON; request failed") from None

    @staticmethod
    def _ticker(ticker):
        if not isinstance(ticker, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,150}", ticker):
            raise DataError("invalid ticker")
        return ticker

    def markets(self, series):
        self._ticker(series)
        result, cursor, seen = [], "", set()
        for _ in range(10):
            page = self._get(KALSHI, "/markets", {"series_ticker": series, "status": "open",
                                               "limit": 100, "cursor": cursor})
            if not isinstance(page, dict) or not isinstance(page.get("markets"), list):
                raise DataError("invalid markets response")
            result.extend(page["markets"])
            cursor = page.get("cursor", "")
            if not cursor:
                return result
            if not isinstance(cursor, str) or cursor in seen:
                raise DataError("invalid or repeated pagination cursor")
            seen.add(cursor)
        raise DataError("market pagination limit reached; scan incomplete")

    def market(self, ticker):
        result = self._get(KALSHI, "/markets/" + self._ticker(ticker))
        if not isinstance(result, dict) or not isinstance(result.get("market"), dict):
            raise DataError("invalid market response")
        if result["market"].get("ticker") != ticker:
            raise DataError("market ticker mismatch")
        return result["market"]

    def candles(self):
        # Explicit completed-minute windows avoid the stale default CDN snapshot.
        # Keep the cache-age guard: never relabel cached candles as fresh.
        end = int(time.time() // 60) * 60
        rows = self._get(COINBASE, "/products/BTC-USD/candles", {
            "granularity": 60, "start": iso(end - 240 * 60), "end": iso(end)})
        if not isinstance(rows, list) or len(rows) > 300:
            raise DataError("invalid candle response")
        return rows
