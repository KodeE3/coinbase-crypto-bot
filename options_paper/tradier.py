"""Tradier production market data only; no accounts, orders, or sandbox fallback."""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from .discovery import NY, whole
from .engine import cents, fresh, money, propose, timestamp
from .market_data import NoRedirect

BASE = 'https://api.tradier.com/v1/markets/'
PATHS = {'history', 'options/expirations', 'options/chains', 'quotes'}
MAX_EXPIRATIONS = 20
MAX_CHAIN_ROWS = 10000
MAX_CANDIDATES = 1000


def rows(value):
    """Tradier uses null, one object, or a list for repeated response elements."""
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(x, dict) for x in value):
        return value
    raise ValueError('Tradier returned an invalid collection')


def quote_time(value):
    number = money(value)
    if number != number.to_integral_value():
        raise ValueError('Invalid Tradier quote timestamp')
    # Current official examples use milliseconds; older API examples use seconds.
    if 10**12 <= number < 10**13:
        number /= 1000
    elif not 10**9 <= number < 10**10:
        raise ValueError('Invalid Tradier quote timestamp units')
    try:
        return datetime.fromtimestamp(float(number), timezone.utc)
    except (ValueError, OverflowError, OSError):
        raise ValueError('Invalid Tradier quote timestamp') from None


def normalized_quote(item, now, allow_zero_bid=False):
    bid_at, ask_at = quote_time(item['bid_date']), quote_time(item['ask_date'])
    fresh(bid_at.isoformat(), now)
    fresh(ask_at.isoformat(), now)
    bid, ask = cents(item['bid']), cents(item['ask'])
    if ask <= 0 or bid > ask or (bid == 0 and not allow_zero_bid):
        raise ValueError('Tradier returned an invalid bid/ask market')
    return {'contract': item['symbol'], 'as_of': min(bid_at, ask_at).isoformat(),
            'bid': str(Decimal(bid)/100), 'ask': str(Decimal(ask)/100),
            'bid_as_of': bid_at.isoformat(), 'ask_as_of': ask_at.isoformat()}


def greek_metadata(greeks, now):
    delta = money(greeks['delta'])
    if not 0 <= delta <= 1:
        raise ValueError('Invalid call delta')
    raw_time = greeks.get('updated_at')
    if not isinstance(raw_time, str) or not re.fullmatch(r'[0-9T Z:+.\-]{10,40}', raw_time):
        raise ValueError('Missing or invalid Greek update time')
    try:
        parsed = datetime.fromisoformat(raw_time.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Invalid Greek update time') from None
    if parsed.tzinfo is None:
        # Official examples include timezone-free values. Do not invent an offset.
        if parsed.date() != now.astimezone(NY).date():
            raise ValueError('Undated-timezone Greeks must at least match the current session date')
        normalized = None
        basis = 'provider_timezone_unspecified'
    else:
        normalized = timestamp(raw_time).isoformat()
        age = now - timestamp(normalized)
        if age < timedelta(0) or age > timedelta(minutes=90):
            raise ValueError('Known Greek time is future-dated or more than 90 minutes old')
        basis = 'provider_timezone_explicit'
    return {'delta': str(delta), 'greeks_updated_at_raw': raw_time,
            'greeks_as_of': normalized, 'greeks_time_basis': basis}


class TradierData:
    def __init__(self, transport=None, clock=None):
        self.token = os.environ.get('TRADIER_ACCESS_TOKEN', '')
        if not re.fullmatch(r'[A-Za-z0-9._~+/=\-]+', self.token):
            raise ValueError('Set TRADIER_ACCESS_TOKEN as an environment secret using a production data token; do not paste it into chat')
        self.transport = transport or build_opener(NoRedirect()).open
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _get(self, path, params):
        if path not in PATHS:
            raise ValueError('Only allowlisted Tradier market-data reads are supported')
        request = Request(BASE + path + '?' + urlencode(params), method='GET',
                          headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json'})
        try:
            with self.transport(request, timeout=10) as response:
                body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise ValueError('Tradier response exceeded size limit')
            result = json.loads(body, parse_float=Decimal)
            if not isinstance(result, dict) or result.get('errors') or result.get('fault'):
                raise ValueError('Tradier returned an invalid or unsuccessful response')
            if result.get('next') or result.get('next_page_token'):
                raise ValueError('Unexpected Tradier pagination; no partial collection accepted')
            return result
        except HTTPError as exc:
            messages = {401: 'Tradier authentication failed; use a valid production data token',
                        403: 'Tradier market-data access denied; verify account/data access',
                        429: 'Tradier rate limit reached; wait before rerunning'}
            raise ValueError(messages.get(exc.code, f'Tradier returned HTTP {exc.code}; collection stopped')) from None
        except (URLError, TimeoutError, OSError):
            raise ValueError('Tradier connection failed or timed out') from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError('Tradier returned invalid JSON') from None

    def daily_bars(self, symbol):
        if not isinstance(symbol, str) or not re.fullmatch(r'[A-Z]{1,6}', symbol):
            raise ValueError('Use an uppercase stock ticker')
        now = self.clock()
        day = now.astimezone(NY).date()
        start, end = day - timedelta(days=60), day - timedelta(days=1)
        raw = self._get('history', {'symbol': symbol, 'interval': 'daily',
                                   'start': start.isoformat(), 'end': end.isoformat()})
        try:
            values = rows(raw['history']['day'])
            if len(values) > 60:
                raise ValueError('Too many daily bars')
            bars = {}
            for item in values:
                session, close = date.fromisoformat(item['date']), money(item['close'])
                if not start <= session <= end or close <= 0 or session in bars:
                    raise ValueError('Invalid, incomplete or duplicate Tradier daily bar')
                bars[session] = str(close)
        except (KeyError, TypeError):
            raise ValueError('Tradier returned missing or malformed daily history') from None
        ordered = sorted(bars)[-30:]
        if len(ordered) < 11 or (day - ordered[-1]).days > 7:
            raise ValueError('Need at least 11 completed daily bars and a recent last session')
        return {'symbol': symbol, 'source': 'tradier', 'fetched_at': now.isoformat(),
                'bars': [{'session_date': d.isoformat(), 'close': bars[d]} for d in ordered],
                'closes': [bars[d] for d in ordered]}

    def option_quotes(self, contracts):
        if (not isinstance(contracts, list) or not 1 <= len(contracts) <= 100
                or any(not isinstance(s, str) or not re.fullmatch(r'[A-Z]{1,6}[0-9]{6}[CP][0-9]{8}', s) for s in contracts)
                or len(set(contracts)) != len(contracts)):
            raise ValueError('Request 1 to 100 unique standard option symbols')
        raw = self._get('quotes', {'symbols': ','.join(contracts), 'greeks': 'false'})
        now, found = self.clock(), {}
        try:
            for item in rows(raw['quotes']['quote']):
                contract = item['symbol']
                if contract not in contracts or contract in found or item['type'] != 'option':
                    raise ValueError('Unexpected or duplicate Tradier quote identity')
                found[contract] = normalized_quote(item, now, allow_zero_bid=True)
        except (KeyError, TypeError):
            raise ValueError('Tradier returned malformed option quotes') from None
        if set(found) != set(contracts):
            raise ValueError('Tradier did not return every requested option quote')
        return {'as_of': now.isoformat(), 'source': 'tradier', 'feed': 'production',
                'quotes': [found[c] for c in contracts]}

    def entry_snapshot(self, symbol='SPY'):
        started = self.clock()
        day = started.astimezone(NY).date()
        underlying = self.daily_bars(symbol)
        raw = self._get('options/expirations', {'symbol': symbol, 'includeAllRoots': 'false'})
        try:
            values = raw['expirations']['date']
            if isinstance(values, str):
                values = [values]
            if not isinstance(values, list) or len(values) > 500 or len(values) != len(set(values)):
                raise ValueError('Invalid Tradier expiration collection')
            expiries = sorted(d for d in values if 21 <= (date.fromisoformat(d) - day).days <= 45)
        except (KeyError, TypeError):
            raise ValueError('Tradier returned missing or malformed expirations') from None
        if len(expiries) > MAX_EXPIRATIONS:
            raise ValueError('Expiration limit exceeded; no partial scan saved')
        reference = money(underlying['closes'][-1])
        low, high = reference * Decimal('.8'), reference * Decimal('1.2')
        candidates, seen, rejected, count = [], set(), Counter(), 0
        for expiry in expiries:
            raw = self._get('options/chains', {'symbol': symbol, 'expiration': expiry, 'greeks': 'true'})
            try:
                chain = rows(raw['options']['option'])
            except (KeyError, TypeError):
                raise ValueError('Tradier returned a missing or malformed option chain') from None
            count += len(chain)
            if count > MAX_CHAIN_ROWS:
                raise ValueError('Chain row limit exceeded; no partial scan saved')
            for item in chain:
                contract = item.get('symbol')
                if not isinstance(contract, str) or contract in seen:
                    raise ValueError('Invalid or duplicate Tradier contract identity')
                seen.add(contract)
                try:
                    match = re.fullmatch(r'([A-Z]{1,6})([0-9]{6})C([0-9]{8})', contract)
                    strike = money(item['strike'])
                    if (not match or match[1] != symbol or match[2] != date.fromisoformat(expiry).strftime('%y%m%d')
                            or Decimal(match[3])/1000 != strike or item['expiration_date'] != expiry
                            or item['type'] != 'option' or item['option_type'] != 'call'
                            or item['underlying'] != symbol or item['root_symbol'] != symbol
                            or whole(item['contract_size']) != 100 or not low <= strike <= high):
                        raise ValueError('Ineligible instrument')
                    candidates.append(item)
                except (KeyError, ValueError, TypeError):
                    rejected['contract_ineligible_or_invalid'] += 1
            if len(candidates) > MAX_CANDIDATES:
                raise ValueError('Candidate limit exceeded; no partial scan saved')
        finished = self.clock()
        if finished.astimezone(NY).date() != day:
            raise ValueError('Session changed during collection; rerun')
        options = []
        for item in sorted(candidates, key=lambda x: x['symbol']):
            try:
                quote = normalized_quote(item, finished)
                greek = greek_metadata(item['greeks'], finished)
                options.append({'symbol': item['symbol'], 'underlying': symbol, 'right': 'call',
                                'expiry': item['expiration_date'], 'strike': str(money(item['strike'])),
                                'multiplier': 100, 'bid': quote['bid'], 'ask': quote['ask'],
                                'quote_as_of': quote['as_of'], 'bid_as_of': quote['bid_as_of'],
                                'ask_as_of': quote['ask_as_of'], **greek,
                                'volume': whole(item['volume']), 'volume_date': day.isoformat(),
                                'open_interest': whole(item['open_interest']), 'open_interest_date': None})
            except (KeyError, ValueError, TypeError):
                rejected['quote_greeks_or_liquidity_invalid'] += 1
        as_of = min((timestamp(o['quote_as_of']) for o in options), default=finished)
        snapshot = {'schema_version': 1, 'symbol': symbol, 'as_of': as_of.isoformat(),
                    'closes': underlying['closes'], 'options': options,
                    'provenance': {'source': 'tradier', 'feed': 'production',
                                   'policy_id': 'tradier-intraday-v1', 'started_at': started.isoformat(),
                                   'fetched_at': finished.isoformat(), 'underlying_bars': underlying['bars'],
                                   'history_adjustment': 'provider_reported_not_guaranteed',
                                   'volume_basis': 'provider_current_day', 'open_interest_date': None,
                                   'greeks_source': 'ORATS via Tradier; hourly',
                                   'discovery_dte': [21, 45], 'strike_ratio': ['0.8', '1.2'],
                                   'limitations': ['Open-interest reporting date is not supplied.',
                                                   'Timezone-free Greek timestamps are preserved without assuming an offset.',
                                                   'Intraday volume differs from Alpaca completed-session volume.']},
                    'diagnostics': {'chain_rows_seen': count, 'contracts_in_universe': len(candidates),
                                    'options_assembled': len(options), 'excluded': dict(sorted(rejected.items()))}}
        snapshot['proposal_preview'] = propose(snapshot, now=finished)
        return snapshot
