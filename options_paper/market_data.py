"""Read-only Alpaca market data. Fixed host, GET only, no broker/order endpoints."""
import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, HTTPRedirectHandler, build_opener
from zoneinfo import ZoneInfo
from .engine import cents, fresh, money, timestamp

BASE = 'https://data.alpaca.markets'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class AlpacaData:
    def __init__(self, transport=None, clock=None):
        self.key = os.environ.get('APCA_API_KEY_ID', '')
        self.secret = os.environ.get('APCA_API_SECRET_KEY', '')
        if not self.key or not self.secret:
            raise ValueError('Set APCA_API_KEY_ID and APCA_API_SECRET_KEY in your environment or Codespaces secrets; do not paste keys into chat.')
        self.transport = transport or build_opener(NoRedirect()).open
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _get(self, path, params):
        request = Request(BASE + path + '?' + urlencode(params), method='GET', headers={
            'APCA-API-KEY-ID': self.key, 'APCA-API-SECRET-KEY': self.secret,
            'Accept': 'application/json'})
        try:
            with self.transport(request, timeout=10) as response:
                payload = response.read(2_000_001)
            if len(payload) > 2_000_000:
                raise ValueError('Market-data response exceeded size limit')
            result = json.loads(payload, parse_float=Decimal)
            if not isinstance(result, dict):
                raise ValueError('Market-data response must be an object')
            return result
        except HTTPError as exc:
            messages = {401: 'Alpaca authentication failed; check your API credentials.',
                        403: 'Alpaca denied this feed. Verify your data entitlements; OPRA options access is required.',
                        429: 'Alpaca rate limit reached. Wait before running the command again.'}
            # Never echo provider bodies, request headers, or credential-bearing errors.
            raise ValueError(messages.get(exc.code, f'Alpaca returned HTTP {exc.code}; no quote update was saved.')) from None
        except (URLError, TimeoutError, OSError):
            raise ValueError('Market-data connection failed or timed out; no quote update was saved.') from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError('Alpaca returned invalid JSON') from None

    def option_quotes(self, contracts):
        if not 1 <= len(contracts) <= 100 or len(set(contracts)) != len(contracts):
            raise ValueError('Request 1 to 100 unique option contracts')
        if any(not re.fullmatch(r'[A-Z]{1,6}[0-9]{6}[CP][0-9]{8}', s) for s in contracts):
            raise ValueError('Use standard option contract symbols, not DEMO symbols')
        raw = self._get('/v1beta1/options/quotes/latest', {'symbols': ','.join(contracts), 'feed': 'opra'})
        now = self.clock()
        result = []
        try:
            for contract in contracts:
                quote = raw['quotes'][contract]
                observed = fresh(quote['t'], now)
                bid, ask = cents(quote['bp']), cents(quote['ap'])
                if ask <= 0 or bid > ask:
                    raise ValueError('Provider returned an invalid bid/ask market')
                result.append({'contract': contract, 'as_of': observed.isoformat(),
                               'bid': str(Decimal(bid)/100), 'ask': str(Decimal(ask)/100)})
        except (KeyError, TypeError):
            raise ValueError('Alpaca did not return valid quotes for every requested contract') from None
        return {'as_of': now.isoformat(), 'source': 'alpaca', 'feed': 'opra', 'quotes': result}

    def daily_bars(self, symbol='SPY', feed='iex'):
        if not re.fullmatch(r'[A-Z]{1,6}', symbol) or feed not in ('iex', 'sip'):
            raise ValueError('Use a stock ticker and an iex or sip feed')
        now = self.clock()
        local_day = now.astimezone(ZoneInfo('America/New_York')).date()
        end = datetime.combine(local_day, datetime.min.time(), ZoneInfo('America/New_York')) - timedelta(microseconds=1)
        params = {'symbols': symbol, 'timeframe': '1Day', 'start': (end-timedelta(days=60)).isoformat(),
                  'end': end.isoformat(), 'feed': feed, 'adjustment': 'split', 'sort': 'desc', 'limit': 30}
        bars, seen = {}, set()
        for _ in range(10):
            raw = self._get('/v2/stocks/bars', params)
            try:
                for bar in raw['bars'][symbol]:
                    at = timestamp(bar['t'])
                    close = money(bar['c'])
                    if at.astimezone(ZoneInfo('America/New_York')).date() >= local_day or close <= 0:
                        raise ValueError('Provider returned an incomplete daily bar or invalid close')
                    if at in bars and bars[at] != str(close):
                        raise ValueError('Provider returned conflicting daily bars')
                    bars[at] = str(close)
            except (KeyError, TypeError):
                raise ValueError('Alpaca returned missing or invalid daily bars') from None
            token = raw.get('next_page_token')
            if not token or len(bars) >= 30:
                break
            if not isinstance(token, str) or token in seen:
                raise ValueError('Invalid market-data pagination token')
            seen.add(token)
            params['page_token'] = token
        if len(bars) < 11:
            raise ValueError('Need at least 11 completed daily bars')
        ordered = sorted(bars)[-30:]
        if now - ordered[-1] > timedelta(days=7):
            raise ValueError('Latest completed daily bar is more than seven days old')
        return {'symbol': symbol, 'source': 'alpaca', 'feed': feed, 'fetched_at': now.isoformat(),
                'bars': [{'as_of': t.isoformat(), 'close': bars[t]} for t in ordered],
                'closes': [bars[t] for t in ordered]}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only market data diagnostic; no orders or account changes')
    parser.add_argument('--symbol', default='SPY')
    parser.add_argument('--stock-feed', choices=['iex', 'sip'], default='iex')
    parser.add_argument('--contracts', nargs='+', help='optional standard option contract symbols; requires OPRA access')
    args = parser.parse_args(argv)
    try:
        client = AlpacaData()
        result = {'underlying': client.daily_bars(args.symbol, args.stock_feed)}
        if args.contracts:
            result['options'] = client.option_quotes(args.contracts)
        print(json.dumps(result, indent=2))
        return 0
    except ValueError as exc:
        print(f'Data unavailable: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
