"""Public Coinbase Exchange candles; hourly UTC buckets only."""
import csv
import json
import math
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Candle:
    time: int
    low: float
    high: float
    open: float
    close: float
    volume: float


def validate(candles):
    if not candles:
        raise ValueError('No candles returned')
    previous = None
    for c in candles:
        if c.time < 0 or c.time % 3600 or not all(math.isfinite(v) for v in asdict(c).values()):
            raise ValueError('Invalid candle timestamp or non-finite value')
        if not (0 < c.low <= min(c.open, c.close) <= max(c.open, c.close) <= c.high) or c.volume < 0:
            raise ValueError('Invalid OHLCV candle')
        if previous is not None and c.time != previous + 3600:
            raise ValueError('Missing, duplicate, or unordered hourly candles')
        previous = c.time
    return candles


def get_json(url):
    for attempt in range(4):
        try:
            request = Request(url, headers={'User-Agent': 'coinbase-crypto-bot/0.1'})
            with urlopen(request, timeout=20) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code != 429 and exc.code < 500:
                raise
            if attempt == 3:
                raise
        except (URLError, TimeoutError):
            if attempt == 3:
                raise
        time.sleep(2 ** attempt)


def fetch(start, end):
    if start % 3600 or end % 3600 or start >= end or end > int(time.time()) // 3600 * 3600:
        raise ValueError('Range must contain completed hourly candles, aligned to UTC hours')
    result = {}
    cursor = start
    while cursor < end:
        stop = min(end, cursor + 299 * 3600)
        iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat()
        query = urlencode({'start': iso(cursor), 'end': iso(stop), 'granularity': 3600})
        rows = get_json('https://api.exchange.coinbase.com/products/BTC-USD/candles?' + query)
        if not isinstance(rows, list):
            raise ValueError('Unexpected Coinbase response')
        for row in rows:
            if len(row) != 6 or float(row[0]) != int(row[0]):
                raise ValueError('Malformed Coinbase candle')
            c = Candle(int(row[0]), *map(float, row[1:]))
            if cursor <= c.time < stop:
                if c.time in result and result[c.time] != c:
                    raise ValueError('Conflicting duplicate candles')
                result[c.time] = c
        cursor = stop
        time.sleep(0.2)
    candles = validate(sorted(result.values(), key=lambda c: c.time))
    if candles[0].time != start or candles[-1].time != end - 3600:
        raise ValueError('Coinbase returned an incomplete requested range')
    return candles


def write_csv(path, candles):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(candles[0])))
        writer.writeheader()
        writer.writerows(map(asdict, candles))


def read_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        return validate([Candle(int(r['time']), *(float(r[k]) for k in ('low', 'high', 'open', 'close', 'volume'))) for r in csv.DictReader(f)])
