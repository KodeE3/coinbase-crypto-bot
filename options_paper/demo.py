"""Finite, offline fictional trade cycle in a disposable account; no user input."""
import json
import sqlite3
import tempfile
from pathlib import Path

from .account import Account
from .engine import propose, timestamp
from .quotes import approve_exit, save_quotes


def run_demo():
    """Exercise entry, restart, valuation and exit without touching user accounts."""
    fixtures = Path(__file__).parent
    snapshot = json.loads((fixtures / 'sample_snapshot.json').read_text(encoding='utf-8'))
    quotes = json.loads((fixtures / 'sample_exit_quotes.json').read_text(encoding='utf-8'))
    proposal = propose(snapshot, demo=True)
    if 'rejected' in proposal:
        raise ValueError(proposal['rejected'])
    with tempfile.TemporaryDirectory(prefix='options-fictional-demo-') as directory:
        path = Path(directory) / 'account.sqlite3'
        account = Account(path, demo=True)
        try:
            opened = account.buy(proposal, proposal['contract'], now=timestamp(snapshot['as_of']))
        finally:
            account.close()
        # Reopen the database to demonstrate persistence between the two operations.
        account = Account(path, demo=True)
        try:
            report = save_quotes(account, quotes)
            candidate = next(p for p in report['positions'] if p['contract'] == proposal['contract'])
            closed = approve_exit(account, candidate, proposal['contract'], now=timestamp(quotes['as_of']))
            return {
                'mode': 'offline fictional demo',
                'account_storage': 'temporary; deleted after this run',
                'real_orders': False,
                'contract': proposal['contract'],
                'initial_cash_cents': opened['initial_cash_cents'],
                'cash_after_entry_cents': opened['cash_cents'],
                'exit_reasons': candidate['reasons'],
                'final_cash_cents': closed['cash_cents'],
                'realized_pnl_cents': closed['realized_pnl_cents'],
                'open_positions': len(closed['positions']),
                'events': account.history(),
                'notice': 'Invented prices demonstrate accounting, not strategy profitability.',
            }
        finally:
            account.close()


def main():
    try:
        print(json.dumps(run_demo(), indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f'Unable to complete fictional demo: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
