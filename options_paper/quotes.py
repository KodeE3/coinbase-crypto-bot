"""Saved snapshot valuations and human-approved exit proposals; no live feed."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from .account import FEE
from .engine import cents, fresh, timestamp

# Tutorial assumptions, not optimized or personalized trading parameters.
STOP_LOSS_PERCENT = 25
PROFIT_TARGET_PERCENT = 50
MAX_HOLD_DAYS = 7
EXPIRY_BUFFER_DAYS = 2


def save_quotes(account, snapshot, now=None):
    """Validate the complete batch before committing any marks. Partial coverage allowed."""
    try:
        if not isinstance(snapshot, dict):
            raise ValueError('Quote snapshot must be an object')
        assessed = timestamp(snapshot['as_of'])
        clock = assessed if account.demo else (now or datetime.now(timezone.utc))
        fresh(snapshot['as_of'], clock)
        quotes = snapshot['quotes']
        if not isinstance(quotes, list) or not quotes:
            raise ValueError('quotes must be a nonempty list')
        parsed, seen = [], set()
        for quote in quotes:
            contract = quote['contract']
            if not isinstance(contract, str) or not contract.strip() or contract in seen:
                raise ValueError('Quote contracts must be nonempty and unique')
            seen.add(contract)
            observed = fresh(quote['as_of'], clock)
            if observed > assessed:
                raise ValueError('Quote time cannot follow snapshot time')
            bid, ask = cents(quote['bid']), cents(quote['ask'])
            if ask <= 0 or bid > ask:
                raise ValueError('Quote requires 0 <= bid <= ask and ask > 0')
            parsed.append((contract, observed, bid, ask))
        with account.transaction():
            latest = account.db.execute('SELECT MAX(assessed_at) FROM marks').fetchone()[0]
            if latest and assessed < timestamp(latest):
                raise ValueError('Snapshot time cannot move backward')
            for contract, observed, bid, ask in parsed:
                position = account.db.execute("SELECT * FROM positions WHERE contract=? AND status='open'", (contract,)).fetchone()
                if not position:
                    raise ValueError(f'No open position for {contract}')
                if observed < timestamp(position['opened_as_of']):
                    raise ValueError('Quote predates entry')
                previous = account.db.execute('SELECT * FROM marks WHERE position_id=?', (position['id'],)).fetchone()
                if previous:
                    if observed < timestamp(previous['as_of']):
                        raise ValueError('Quote cannot replace a newer saved quote')
                    if observed == timestamp(previous['as_of']) and (bid, ask) != (previous['bid_cents'], previous['ask_cents']):
                        raise ValueError('Changed prices require a new quote timestamp')
                account.db.execute('INSERT OR REPLACE INTO marks VALUES(?,?,?,?,?)',
                                   (position['id'], bid, ask, observed.isoformat(), assessed.isoformat()))
        return valuation(account, now=clock)
    except (KeyError, TypeError) as exc:
        raise ValueError('Each quote needs contract, bid, ask, and timezone-aware as_of') from exc


def valuation(account, now=None):
    """No invented prices: missing/stale marks make total estimated equity unavailable."""
    state = account.status()
    latest = account.db.execute('SELECT MAX(assessed_at) FROM marks').fetchone()[0]
    clock = now or (timestamp(latest) if account.demo and latest else datetime.now(timezone.utc))
    result = {'as_of': clock.isoformat(), 'historical_demo': account.demo, 'positions': [],
              'estimated_equity_cents': None, 'unrealized_pnl_cents': None}
    total_value, total_pnl, complete = 0, 0, True
    for position in state['positions']:
        mark = account.db.execute('SELECT * FROM marks WHERE position_id=?', (position['id'],)).fetchone()
        item = {'position_id': position['id'], 'contract': position['contract'], 'reasons': [],
                'quote_as_of': mark['as_of'] if mark else None, 'usable': False}
        try:
            if not mark:
                raise ValueError('Missing quote')
            fresh(mark['as_of'], clock)
            if clock.date() >= date.fromisoformat(position['expiry']):
                raise ValueError('Expiry-day or expired position: settlement is not modeled')
            value = mark['bid_cents'] * 100 - FEE
            pnl = value - position['cost']
            item.update(usable=True, bid_cents=mark['bid_cents'],
                        net_liquidation_cents=value, unrealized_pnl_cents=pnl)
            # Integer comparisons avoid rounding errors at rule boundaries.
            if pnl * 100 <= -position['cost'] * STOP_LOSS_PERCENT:
                item['reasons'].append('stop_loss: estimated loss reached 25% of entry cost')
            if pnl * 100 >= position['cost'] * PROFIT_TARGET_PERCENT:
                item['reasons'].append('profit_target: estimated gain reached 50% of entry cost')
            if clock - timestamp(position['opened_as_of']) >= timedelta(days=MAX_HOLD_DAYS):
                item['reasons'].append('holding_time: position held at least 7 calendar days')
            if (date.fromisoformat(position['expiry']) - clock.date()).days <= EXPIRY_BUFFER_DAYS:
                item['reasons'].append('expiration: 2 or fewer calendar days until expiry')
            total_value += value
            total_pnl += pnl
        except ValueError as exc:
            item['unavailable_reason'] = str(exc)
            complete = False
        result['positions'].append(item)
    if complete:
        result['estimated_equity_cents'] = state['cash_cents'] + total_value
        result['unrealized_pnl_cents'] = total_pnl
    return result


def approve_exit(account, candidate, confirmation, now=None):
    """Re-evaluate freshness/rules, then atomically match the position and quoted bid."""
    current = next((x for x in valuation(account, now)['positions']
                    if x['position_id'] == candidate['position_id']), None)
    if not current or not current['usable'] or not current['reasons']:
        raise ValueError('Exit is no longer actionable; update quotes and review again')
    if (candidate['quote_as_of'], candidate['bid_cents']) != (current['quote_as_of'], current['bid_cents']):
        raise ValueError('Quote changed; review the exit again')
    return account.sell(current['contract'], Decimal(current['bid_cents']) / 100,
                        current['quote_as_of'], confirmation, now=now,
                        expected_position_id=current['position_id'],
                        expected_quote=(current['quote_as_of'], current['bid_cents']))
