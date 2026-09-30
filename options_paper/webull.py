"""Bounded Webull production-data reads. No accounts, orders, or token creation.

Wire schemas and signature algorithm: official Webull v3 docs, checked 2026-09-30.
Only existing standard equity/ETF option contracts can be quoted in this milestone.
"""
import argparse
import base64
from collections import deque
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import hmac
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener
import uuid
from zoneinfo import ZoneInfo

from .engine import cents, fresh, money
from .market_data import NoRedirect

HOST = 'api.webull.com'
CONTRACTS_PATH = '/trading/instruments/options/contracts/list'
SNAPSHOTS_PATH = '/market-data/options/snapshots/list'
PARAMETERS = {
    CONTRACTS_PATH: {'category', 'option_symbols', 'status', 'show_deliverables', 'pagination_key'},
    SNAPSHOTS_PATH: {'category', 'symbols'},
}
MAX_CONTRACTS = 100
BATCH_SIZE = 20
MAX_PAGES = 10
MAX_RESPONSE_BYTES = 2_000_000
MAX_QUOTE_AGE_SECONDS = 60
NY = ZoneInfo('America/New_York')


def signature(path, params, headers, secret, body=''):
    """Official v3 canonicalization; body support exists for the published test vector.

    The network transport below is GET-only and never sends a body.
    """
    values = dict(params)
    values.update({key: headers[key] for key in (
        'host', 'x-app-key', 'x-signature-algorithm', 'x-signature-version',
        'x-signature-nonce', 'x-timestamp')})
    canonical = path + '&' + '&'.join(f'{key}={values[key]}' for key in sorted(values))
    if body:
        canonical += '&' + hashlib.md5(body.encode()).hexdigest().upper()
    digest = hmac.new((secret + '&').encode(), quote(canonical, safe='').encode(), hashlib.sha1)
    return base64.b64encode(digest.digest()).decode('ascii')


def credential(name, optional=False):
    value = os.environ.get(name, '')
    if optional and not value:
        return ''
    if not isinstance(value, str) or not re.fullmatch(r'[\x21-\x7e]{1,4096}', value):
        raise ValueError(f'Set {name} through runtime environment secrets; do not paste credentials into chat')
    return value


def identity(contract):
    match = re.fullmatch(r'([A-Z]{1,6})([0-9]{6})([CP])([0-9]{8})', contract) if isinstance(contract, str) else None
    if not match:
        raise ValueError('Use standard OCC option symbols, not demo or adjusted-root symbols')
    try:
        expiry = date(2000 + int(match[2][:2]), int(match[2][2:4]), int(match[2][4:]))
        strike = Decimal(match[4]) / 1000
        if strike <= 0:
            raise ValueError
    except ValueError:
        raise ValueError('Invalid option expiry or strike') from None
    return {'underlying': match[1], 'expiry': expiry.isoformat(),
            'right': 'CALL' if match[3] == 'C' else 'PUT', 'strike': strike}


def epoch_milliseconds(value):
    # This endpoint explicitly documents int64 milliseconds. Do not guess other units.
    if type(value) is not int or not 10**12 <= value < 10**13:
        raise ValueError('Webull quote_time must be epoch milliseconds')
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=value)


def quote_cents(value):
    number = money(value)
    if number < 0 or number > 10**10 or number != number.quantize(Decimal('.01')):
        raise ValueError('Webull price is out of range or has sub-cent precision')
    return cents(number)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Webull returned duplicate JSON keys')
        result[key] = value
    return result


def _invalid_number(value):
    raise ValueError('Webull returned a non-finite number')


def contract_metadata(item, requested):
    """Require one physical, standard 100-share deliverable, including after CA events."""
    try:
        contract = item['symbol']
        if contract not in requested:
            raise ValueError('Webull returned an unexpected contract')
        parsed = identity(contract)
        underlying, right = parsed['underlying'], parsed['right']
        deliverables = item['deliverables']
        if (item['root_symbol'] != underlying or item['underlying_symbol'] != underlying
                or item['expiration_date'] != parsed['expiry'] or item['option_type'] != right
                or money(item['strike_price']) != parsed['strike']
                or money(item['multiplier']) != 100 or item['status'] != 'LISTING'
                or item['tradable_status'] not in ('OC', 'CO')
                or item['underlying_type'] not in (f'EQUITY_{right}_OPTION', f'ETF_{right}_OPTION')
                or item['style'] != 'AMERICAN' or item['settlement_method'] != 'PHYSICAL'
                or item['def_type'] != 'STANDARD' or item['currency'] != 'USD'
                or not isinstance(deliverables, list) or len(deliverables) != 1):
            raise ValueError('Webull contract is inconsistent or not a supported standard option')
        instrument = item['instrument_id']
        underlying_id = item['underlying_instrument_id']
        if any(not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,32}', value)
               for value in (instrument, underlying_id)):
            raise ValueError('Webull returned an invalid instrument identifier')
        delivery = deliverables[0]
        if (delivery['asset_type'] != 'EQUITY' or delivery['symbol'] != underlying
                or delivery['instrument_id'] != underlying_id or money(delivery['amount']) != 100
                or money(delivery['allocation_percentage']) != 100
                or delivery['settlement_method'] != 'PHYSICAL'
                or delivery['settlement_status'] != 'REGULAR'):
            raise ValueError('Webull returned a nonstandard or uncertain deliverable')
        return {**parsed, 'instrument_id': instrument, 'multiplier': 100,
                'currency': 'USD', 'tradable_status': item['tradable_status']}
    except (KeyError, TypeError):
        raise ValueError('Webull contract metadata is missing or malformed') from None


class WebullData:
    def __init__(self, transport=None, clock=None, monotonic=None):
        self.key = credential('WEBULL_APP_KEY')
        self.secret = credential('WEBULL_APP_SECRET')
        self.token = credential('WEBULL_ACCESS_TOKEN', optional=True)
        self.transport = transport or build_opener(NoRedirect()).open
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.monotonic = monotonic or time.monotonic
        self.requests = {path: deque() for path in PARAMETERS}

    def _get(self, path, params):
        if (path not in PARAMETERS or not isinstance(params, dict)
                or not set(params) <= PARAMETERS[path]
                or any(not isinstance(v, str) or len(v) > 4096 for v in params.values())):
            raise ValueError('Only allowlisted Webull data reads and parameters are supported')
        # Conservative per-instance budget, no retries; Webull shares its quota across
        # all callers using an app key. A server 429 still stops the collection.
        now = self.monotonic()
        requests = self.requests[path]
        while requests and now - requests[0] >= 60:
            requests.popleft()
        if len(requests) >= 50:
            raise ValueError('Webull local request budget reached; wait before rerunning')
        requests.append(now)
        headers = {'host': HOST, 'x-app-key': self.key, 'x-version': 'v3',
                   'x-timestamp': self.clock().astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                   'x-signature-algorithm': 'HMAC-SHA1', 'x-signature-version': '1.0',
                   'x-signature-nonce': uuid.uuid4().hex, 'Accept': 'application/json'}
        headers['x-signature'] = signature(path, params, headers, self.secret)
        if self.token:
            headers['x-access-token'] = self.token
        request = Request('https://' + HOST + path + '?' + urlencode(params), method='GET', headers=headers)
        try:
            with self.transport(request, timeout=10) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise ValueError('Webull response exceeded size limit')
            result = json.loads(payload, parse_float=Decimal, parse_constant=_invalid_number,
                                object_pairs_hook=_unique_object)
            if not isinstance(result, (dict, list)) or (isinstance(result, dict) and 'error_code' in result):
                raise ValueError('Webull returned an invalid or unsuccessful response')
            return result
        except HTTPError as exc:
            messages = {401: 'Webull authentication failed; verify credentials and any required 2FA access token',
                        403: 'Webull data access denied; verify OpenAPI OPRA entitlement',
                        429: 'Webull rate limit reached; wait before rerunning'}
            raise ValueError(messages.get(exc.code, f'Webull returned HTTP {exc.code}; collection stopped')) from None
        except (URLError, OSError, HTTPException):
            raise ValueError('Webull connection failed or timed out') from None
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
            raise ValueError('Webull returned invalid JSON') from None

    def _contracts(self, contracts):
        params = {'category': 'US_OPTION', 'option_symbols': ','.join(contracts),
                  'status': 'LISTING', 'show_deliverables': 'true'}
        found, seen, ids = {}, set(), set()
        for _ in range(MAX_PAGES):
            raw = self._get(CONTRACTS_PATH, params)
            if not isinstance(raw, dict) or not isinstance(raw.get('data'), list):
                raise ValueError('Webull returned an invalid contract collection')
            if any(raw.get(key) for key in ('next', 'next_page_token', 'has_more')):
                raise ValueError('Webull returned unsupported pagination')
            for item in raw['data']:
                metadata = contract_metadata(item, contracts)
                contract = item['symbol']
                if contract in found or metadata['instrument_id'] in ids:
                    raise ValueError('Webull returned duplicate contract identity')
                found[contract] = metadata
                ids.add(metadata['instrument_id'])
            token = raw.get('pagination_key')
            if token is None or token == '':
                if set(found) != set(contracts):
                    raise ValueError('Webull did not return metadata for every requested contract')
                return found
            if (not isinstance(token, str) or not 1 <= len(token) <= 4096 or token in seen
                    or not re.fullmatch(r'[\x21-\x7e]+', token)):
                raise ValueError('Webull returned invalid or repeated pagination')
            seen.add(token)
            params['pagination_key'] = token
        raise ValueError('Webull contract page limit exceeded; no partial batch accepted')

    def option_quotes(self, contracts):
        if (not isinstance(contracts, list) or not 1 <= len(contracts) <= MAX_CONTRACTS
                or any(not isinstance(s, str) for s in contracts)
                or len(set(contracts)) != len(contracts)):
            raise ValueError('Request 1 to 100 unique standard option symbols')
        started = self.clock()
        day = started.astimezone(NY).date()
        for contract in contracts:
            if date.fromisoformat(identity(contract)['expiry']) <= day:
                raise ValueError('Webull research requires contracts expiring after today')
        quotes, instrument_ids = [], set()
        for offset in range(0, len(contracts), BATCH_SIZE):
            batch = contracts[offset:offset + BATCH_SIZE]
            metadata = self._contracts(batch)
            batch_ids = {item['instrument_id'] for item in metadata.values()}
            if instrument_ids & batch_ids:
                raise ValueError('Webull reused an instrument identifier across batches')
            instrument_ids.update(batch_ids)
            raw = self._get(SNAPSHOTS_PATH, {'category': 'US_OPTION', 'symbols': ','.join(batch)})
            if not isinstance(raw, list) or len(raw) != len(batch):
                raise ValueError('Webull did not return exactly one snapshot per requested contract')
            found = {}
            try:
                for item in raw:
                    contract = item['symbol']
                    if not isinstance(contract, str) or contract not in metadata or contract in found:
                        raise ValueError('Webull returned unexpected or duplicate quote identity')
                    meta = metadata[contract]
                    if (item['instrument_id'] != meta['instrument_id']
                            or money(item['strike_price']) != meta['strike']):
                        raise ValueError('Webull snapshot identity disagrees with the contract catalog')
                    at = epoch_milliseconds(item['quote_time'])
                    bid, ask = quote_cents(item['bid']), quote_cents(item['ask'])
                    if ask <= 0 or bid > ask:
                        raise ValueError('Webull returned an invalid bid/ask market')
                    found[contract] = {
                        'contract': contract, 'as_of': at.isoformat(),
                        'bid': str(Decimal(bid)/100), 'ask': str(Decimal(ask)/100),
                        'instrument_id': meta['instrument_id'], 'underlying': meta['underlying'],
                        'expiry': meta['expiry'], 'right': meta['right'].lower(),
                        'strike': str(meta['strike']), 'multiplier': 100, 'currency': 'USD',
                        'tradable_status': meta['tradable_status'],
                        'quote_time_raw': item['quote_time'], 'bid_as_of': None, 'ask_as_of': None,
                    }
            except (KeyError, TypeError):
                raise ValueError('Webull returned missing or malformed option snapshots') from None
            quotes.extend(found[c] for c in batch)
        finished = self.clock()
        if finished.astimezone(NY).date() != day:
            raise ValueError('Webull collection crossed the session date; rerun')
        for item in quotes:
            observed = fresh(item['as_of'], finished)
            if finished - observed > timedelta(seconds=MAX_QUOTE_AGE_SECONDS):
                raise ValueError('Webull quote is more than 60 seconds old')
        return {'schema_version': 1, 'as_of': finished.isoformat(), 'source': 'webull',
                'environment': 'production', 'feed': 'opra_entitlement_required',
                'policy_id': 'webull-standard-option-quotes-v1',
                'started_at': started.isoformat(), 'fetched_at': finished.isoformat(),
                'quote_time_basis': 'provider_snapshot_generation',
                'limitations': ['Separate bid and ask event timestamps are not supplied.',
                                'The response does not identify the entitled feed or its delay.',
                                'Sub-cent quotes are rejected by the integer-cent paper ledger.'],
                'quotes': quotes}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Capture Webull production option quotes; no trades or account access')
    parser.add_argument('--contracts', nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True, help='new immutable JSON observation path')
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise ValueError('Output already exists; choose a new observation path')
        snapshot = WebullData().option_quotes(args.contracts)
        from .discovery import save_snapshot
        save_snapshot(args.output, snapshot)
        print(json.dumps({'saved': str(args.output), 'source': 'webull', 'environment': 'production',
                          'quotes': len(snapshot['quotes']), 'as_of': snapshot['as_of'],
                          'trades_recorded': False}, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(f'Webull data unavailable: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
