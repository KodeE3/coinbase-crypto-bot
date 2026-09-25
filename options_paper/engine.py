"""Validated snapshot proposals; no market-data feed or broker connection."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import re


def money(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError('Expected a finite number') from exc
    if not result.is_finite():
        raise ValueError('Expected a finite number')
    return result


def timestamp(value):
    try:
        # Providers may use nanosecond RFC3339 timestamps; datetime uses microseconds.
        value = re.sub(r'(\.\d{6})\d+', r'\1', value)
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError('Timestamp must be ISO format with a timezone') from exc
    if result.tzinfo is None:
        raise ValueError('Timestamp must include a timezone')
    return result.astimezone(timezone.utc)


def fresh(value, now=None):
    observed = timestamp(value)
    age = (now or datetime.now(timezone.utc)) - observed
    if age < timedelta(0) or age > timedelta(minutes=15):
        raise ValueError('Quote is future-dated or more than 15 minutes old')
    return observed


def cents(value):
    number = money(value) * 100
    if number != number.to_integral_value() or number < 0 or number > 10**12:
        raise ValueError('Dollar amounts must be nonnegative, within limits, and have at most two decimals')
    return int(number)


def propose(snapshot, now=None, demo=False):
    """Invalid snapshots reject cleanly. Account checks happen at purchase time."""
    try:
        if not isinstance(snapshot, dict):
            raise ValueError('Snapshot must be a JSON object')
        observed = timestamp(snapshot['as_of'])
        if not demo:
            fresh(snapshot['as_of'], now)
        symbol = snapshot['symbol']
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError('Underlying symbol is required')
        if not isinstance(snapshot['closes'], list):
            raise ValueError('Completed daily closes must be a list')
        closes = [money(x) for x in snapshot['closes']]
        if len(closes) < 11 or any(x <= 0 for x in closes):
            raise ValueError('Need at least 11 positive completed daily closes')
        if not isinstance(snapshot['options'], list):
            raise ValueError('Options must be a list')
        if sum(closes[-5:]) / 5 <= sum(closes[-10:]) / 10 or closes[-1] <= closes[-2]:
            return {'rejected': 'No bullish trend and momentum signal'}
        candidates = []
        for item in snapshot['options']:
            try:
                if item['right'] != 'call' or item['underlying'] != symbol:
                    continue
                contract = item['symbol']
                if not isinstance(contract, str) or not contract.strip():
                    continue
                expiry = date.fromisoformat(item['expiry'])
                bid, ask = cents(item['bid']), cents(item['ask'])
                delta = money(item['delta'])
                integers = [item['multiplier'], item['volume'], item['open_interest']]
                if any(type(x) is not int for x in integers):
                    continue
                multiplier, volume, interest = integers
                if not (21 <= (expiry - observed.date()).days <= 45 and 0 < bid <= ask
                        and Decimal('0.35') <= delta <= Decimal('0.65')
                        and Decimal(ask-bid)/ask <= Decimal('0.10')
                        and volume >= 100 and interest >= 500 and multiplier == 100
                        and money(item['strike']) > 0):
                    continue
                candidates.append((abs(delta - Decimal('0.50')), ask-bid, contract, item, ask, bid))
            except (KeyError, ValueError, TypeError, InvalidOperation):
                continue
        if not candidates:
            return {'rejected': 'No contract passes liquidity, expiry, and delta filters'}
        _, _, contract, item, ask, bid = min(candidates, key=lambda x: x[:3])
        identity = observed.isoformat() + '|' + contract
        return {'id': hashlib.sha256(identity.encode()).hexdigest()[:24],
                'snapshot_as_of': observed.isoformat(), 'underlying': symbol,
                'contract': contract, 'expiry': item['expiry'], 'quantity': 1,
                'action': 'buy_to_open', 'ask_cents': ask, 'bid_cents': bid,
                'premium_cents': ask * 100, 'demo': demo,
                'reason': '5-day average above 10-day average and latest close rising'}
    except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
        return {'rejected': f'Invalid snapshot: {exc}'}
