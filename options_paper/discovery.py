"""Bounded, read-only discovery and entry snapshots. Never opens a paper account."""
import argparse
from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import tempfile
from zoneinfo import ZoneInfo

from .engine import cents, fresh, money, propose, timestamp
from .market_data import AlpacaData

NY = ZoneInfo('America/New_York')
MAX_PAGES = 10
MAX_CONTRACTS = 1000


def pages(client, path, params, field, kind):
    """Exhaust pagination or fail; never silently rank a truncated universe."""
    params = dict(params)
    seen = set()
    for _ in range(MAX_PAGES):
        raw = client._get(path, params)
        if not isinstance(raw.get(field), kind):
            raise ValueError('Provider returned an invalid discovery collection')
        yield raw[field]
        token = raw.get('next_page_token')
        if token is None or token == '':
            return
        if not isinstance(token, str) or len(token) > 4096 or token in seen:
            raise ValueError('Invalid discovery pagination token')
        seen.add(token)
        params['page_token'] = token
    raise ValueError('Discovery page limit exceeded; no snapshot saved')


def whole(value):
    number = money(value)
    if number < 0 or number != number.to_integral_value() or number > 10**12:
        raise ValueError('Invalid nonnegative integer')
    return int(number)


def contract_metadata(item, symbol, day, session, low, high):
    """Cross-check standard OCC identity against provider metadata."""
    contract = item['symbol']
    match = re.fullmatch(r'([A-Z]{1,6})([0-9]{6})C([0-9]{8})', contract)
    expiry = date.fromisoformat(item['expiration_date'])
    strike = money(item['strike_price'])
    interest_date = date.fromisoformat(item['open_interest_date'])
    if (not match or match[1] != symbol or match[2] != expiry.strftime('%y%m%d')
            or Decimal(match[3]) / 1000 != strike
            or item['root_symbol'] != symbol or item['underlying_symbol'] != symbol
            or item['type'] != 'call' or item['status'] != 'active'
            or item['tradable'] is not True or whole(item['size']) != 100
            or not 21 <= (expiry - day).days <= 45 or not low <= strike <= high
            or not session <= interest_date <= day):
        raise ValueError('Ineligible or stale contract metadata')
    return {'symbol': contract, 'underlying': symbol, 'right': 'call',
            'expiry': expiry.isoformat(), 'strike': str(strike), 'multiplier': 100,
            'open_interest': whole(item['open_interest']),
            'open_interest_date': interest_date.isoformat()}


def snapshots(client, contracts):
    result = {}
    for batch in pages(client, '/v1beta1/options/snapshots',
                       {'symbols': ','.join(contracts), 'feed': 'opra', 'limit': 100},
                       'snapshots', dict):
        for contract, value in batch.items():
            if contract not in contracts or contract in result:
                raise ValueError('Unexpected or duplicate option snapshot')
            result[contract] = value
    return result


def volumes(client, contracts, session):
    start = datetime.combine(session, time.min, NY)
    end = start + timedelta(days=1) - timedelta(microseconds=1)
    result = {}
    for batch in pages(client, '/v1beta1/options/bars',
                       {'symbols': ','.join(contracts), 'timeframe': '1Day',
                        'start': start.isoformat(), 'end': end.isoformat(),
                        'limit': 1000, 'sort': 'asc'}, 'bars', dict):
        for contract, bars in batch.items():
            if contract not in contracts or not isinstance(bars, list):
                raise ValueError('Invalid option volume collection')
            for bar in bars:
                try:
                    at = timestamp(bar['t'])
                    volume = whole(bar['v'])
                except (KeyError, TypeError, ValueError):
                    raise ValueError('Invalid option volume bar') from None
                if at.astimezone(NY).date() != session or contract in result:
                    raise ValueError('Unexpected date or duplicate option volume bar')
                result[contract] = volume
    return result


def discover(client, symbol='SPY', stock_feed='iex'):
    """Assemble the existing entry schema with provenance and rejection counts."""
    if not isinstance(symbol, str) or not re.fullmatch(r'[A-Z]{1,6}', symbol):
        raise ValueError('Use an uppercase stock ticker')
    if stock_feed not in ('iex', 'sip'):
        raise ValueError('Use an iex or sip stock feed')
    started = client.clock()
    day = started.astimezone(NY).date()
    underlying = client.daily_bars(symbol, stock_feed)
    session = timestamp(underlying['bars'][-1]['as_of']).astimezone(NY).date()
    if not 1 <= (day - session).days <= 7:
        raise ValueError('Completed underlying session is unavailable or stale')
    reference = money(underlying['closes'][-1])
    low = (reference * Decimal('0.80')).quantize(Decimal('0.01'))
    high = (reference * Decimal('1.20')).quantize(Decimal('0.01'))
    filters = {'underlying_symbols': symbol, 'root_symbol': symbol, 'type': 'call',
               'status': 'active', 'expiration_date_gte': (day + timedelta(days=21)).isoformat(),
               'expiration_date_lte': (day + timedelta(days=45)).isoformat(),
               'strike_price_gte': str(low), 'strike_price_lte': str(high), 'limit': 100}
    eligible, seen, rejected = {}, set(), Counter()
    for batch in pages(client, '/v2/options/contracts', filters, 'option_contracts', list):
        for item in batch:
            if not isinstance(item, dict) or not isinstance(item.get('symbol'), str):
                raise ValueError('Provider returned invalid contract identity')
            contract = item['symbol']
            if contract in seen:
                raise ValueError('Duplicate contract in discovery')
            seen.add(contract)
            if len(seen) > MAX_CONTRACTS:
                raise ValueError('Discovery contract limit exceeded; no snapshot saved')
            try:
                eligible[contract] = contract_metadata(item, symbol, day, session, low, high)
            except (KeyError, TypeError, ValueError):
                rejected['metadata_missing_stale_or_ineligible'] += 1
    options = []
    contracts = sorted(eligible)
    for offset in range(0, len(contracts), 100):
        batch = contracts[offset:offset + 100]
        daily_volume = volumes(client, batch, session)
        latest = snapshots(client, batch)
        for contract in batch:
            try:
                raw = latest[contract]
                quote = raw['latestQuote']
                observed = fresh(quote['t'], client.clock())
                bid, ask = cents(quote['bp']), cents(quote['ap'])
                delta = money(raw['greeks']['delta'])
                if not 0 < bid <= ask or not 0 <= delta <= 1:
                    raise ValueError('Invalid call quote or delta')
                options.append({**eligible[contract], 'bid': str(Decimal(bid) / 100),
                                'ask': str(Decimal(ask) / 100), 'delta': str(delta),
                                'quote_as_of': observed.isoformat(),
                                'volume': daily_volume[contract], 'volume_date': session.isoformat()})
            except (KeyError, TypeError, ValueError):
                rejected['quote_greeks_or_volume_missing_or_invalid'] += 1
    finished = client.clock()
    if finished.astimezone(NY).date() != day:
        raise ValueError('Session date changed during discovery; run again')
    # Recheck after all pages: slow collection must never rejuvenate old quotes.
    valid = []
    for item in options:
        try:
            fresh(item['quote_as_of'], finished)
            valid.append(item)
        except ValueError:
            rejected['quote_expired_during_collection'] += 1
    as_of = min((timestamp(x['quote_as_of']) for x in valid), default=finished)
    snapshot = {'schema_version': 1, 'as_of': as_of.isoformat(), 'symbol': symbol,
                'closes': underlying['closes'], 'options': valid,
                'provenance': {'source': 'alpaca', 'option_feed': 'opra',
                               'contract_environment': 'paper', 'stock_feed': stock_feed,
                               'started_at': started.isoformat(), 'fetched_at': finished.isoformat(),
                               'underlying_bars': underlying['bars'], 'discovery_filters': filters,
                               'volume_basis': 'latest_completed_underlying_session',
                               'greeks_timestamp': None,
                               'greeks_note': 'Provider snapshot greeks have no independent timestamp.'},
                'diagnostics': {'contracts_seen': len(seen), 'options_assembled': len(valid),
                                'excluded': dict(sorted(rejected.items()))}}
    snapshot['proposal_preview'] = propose(snapshot, now=finished)
    return snapshot


def save_snapshot(path, snapshot):
    """Publish a complete JSON file atomically, refusing existing destinations."""
    path = Path(path)
    content = json.dumps(snapshot, indent=2, allow_nan=False) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.entry-', suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        # Same-filesystem hard link is atomic and cannot replace an existing file.
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Discover options and save an entry snapshot; no trades')
    parser.add_argument('--symbol', default='SPY')
    parser.add_argument('--stock-feed', choices=['iex', 'sip'], default='iex')
    parser.add_argument('--output', required=True, type=Path, help='new JSON path; existing files are never overwritten')
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise ValueError('Output already exists; choose a new snapshot filename')
        snapshot = discover(AlpacaData(), args.symbol, args.stock_feed)
        save_snapshot(args.output, snapshot)
        print(json.dumps({'saved': str(args.output), 'diagnostics': snapshot['diagnostics'],
                          'proposal_preview': snapshot['proposal_preview'], 'trades_recorded': 0}, indent=2))
        return 0
    except ValueError as exc:
        # Adapter validation errors are deliberately redacted at the source.
        print(f'Discovery unavailable: {exc}. No trades recorded.')
        return 1
    except OSError:
        print('Unable to save snapshot; choose a new writable path on a filesystem '
              'supporting hard links. No trades recorded.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
