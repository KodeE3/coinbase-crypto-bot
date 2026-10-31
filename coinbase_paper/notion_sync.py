"""Safe, pure Notion reconciliation planner. No network calls or trade execution.

Only produces proposed operations. Caller must review/apply with a separate
credentialed worker and persist idempotency/checkpoints.
"""
from decimal import Decimal, InvalidOperation

ALLOWED = {'BTC-USD', 'ETH-USD', 'SOL-USD'}

class SyncConflict(ValueError):
    pass


def _numeric(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise SyncConflict('Invalid numeric value') from exc
    if not result.is_finite():
        raise SyncConflict('Nonfinite numeric value')
    return result


def plan_fill_sync(imported, notion_rows):
    """Return (creates, conflicts), with no writes and no trade approvals.

    Imported rows require stable `unique_fill_key`, `pair`, `quantity`, `price`,
    `fee`, `fee_currency`, `side`, and `trade_time` fields. Notion rows must
    have the same normalized fields to establish an exact match. Missing keys,
    conflicting values and duplicate Notion keys are quarantined.
    """
    by_key = {}
    conflicts = []
    for row in notion_rows:
        key = row.get('unique_fill_key')
        if not isinstance(key, str) or not key.strip():
            conflicts.append({'key': None, 'reason': 'Notion row missing key'})
            continue
        if key in by_key:
            conflicts.append({'key': key, 'reason': 'Duplicate Notion key'})
            by_key[key] = None
        else:
            by_key[key] = row
    creates = []
    seen = set()
    for row in imported:
        key = row.get('unique_fill_key')
        if not isinstance(key, str) or not key.strip():
            conflicts.append({'key': None, 'reason': 'Imported fill missing key'})
            continue
        if key in seen:
            conflicts.append({'key': key, 'reason': 'Duplicate input key'})
            continue
        seen.add(key)
        if row.get('pair') not in ALLOWED or row.get('side') not in {'BUY', 'SELL'}:
            conflicts.append({'key': key, 'reason': 'Unsupported pair or side'})
            continue
        try:
            if _numeric(row.get('quantity')) <= 0 or _numeric(row.get('price')) <= 0 or _numeric(row.get('fee')) < 0:
                raise SyncConflict('Invalid fill amount')
            if not row.get('fee_currency') or not row.get('trade_time'):
                raise SyncConflict('Missing fee currency or timestamp')
        except SyncConflict as exc:
            conflicts.append({'key': key, 'reason': str(exc)})
            continue
        existing = by_key.get(key, 'ABSENT')
        if existing is None:
            continue  # Duplicate Notion key already recorded above
        elif existing == 'ABSENT':
            creates.append(dict(row))
        else:
            fields = ('pair', 'side', 'quantity', 'price', 'fee', 'fee_currency', 'trade_time')
            equal = all((_numeric(row[f]) == _numeric(existing[f]) if f in {'quantity','price','fee'} else row[f] == existing[f]) for f in fields if f in row and f in existing)
            complete = all(f in existing for f in fields)
            if not complete or not equal:
                conflicts.append({'key': key, 'reason': 'Existing Notion fill differs or is incomplete'})
    return {'creates': creates, 'conflicts': conflicts, 'unchanged': len(seen)-len(creates)-len([c for c in conflicts if c['key'] in seen])}


def notion_approval_is_execution_authority(_notion_status):
    """Notion is a review surface, NEVER an execution authorization channel."""
    return False
