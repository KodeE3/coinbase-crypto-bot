"""Transactional paper account. Integer cents, one long call per position."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .engine import cents, fresh, timestamp

FEE = 65  # Illustrative per-contract, per-side commission in cents.


class Account:
    def __init__(self, path, demo=False, starting_cash='10000'):
        self.demo = demo
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS account (
            id INTEGER PRIMARY KEY CHECK(id=1), cash INTEGER NOT NULL CHECK(cash>=0),
            initial INTEGER NOT NULL, demo INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS positions (
            id TEXT PRIMARY KEY, contract TEXT NOT NULL, underlying TEXT NOT NULL,
            expiry TEXT NOT NULL, opened_as_of TEXT NOT NULL,
            cost INTEGER NOT NULL, status TEXT NOT NULL, pnl INTEGER);
        CREATE UNIQUE INDEX IF NOT EXISTS one_open_underlying
            ON positions(underlying) WHERE status='open';
        CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY, recorded_at TEXT NOT NULL, kind TEXT NOT NULL,
            position_id TEXT NOT NULL, quote_as_of TEXT NOT NULL,
            price_cents INTEGER NOT NULL, fee_cents INTEGER NOT NULL, pnl_cents INTEGER);
        ''')
        initial = cents(starting_cash)
        if initial <= 0:
            raise ValueError('Starting cash must be positive')
        with self.transaction():
            self.db.execute('INSERT OR IGNORE INTO account VALUES(1,?,?,?)', (initial, initial, int(demo)))
        if bool(self.db.execute('SELECT demo FROM account').fetchone()[0]) != demo:
            self.db.close()
            raise ValueError('Demo and snapshot accounts must use different database files')

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def status(self):
        row = self.db.execute('SELECT * FROM account').fetchone()
        positions = [dict(x) for x in self.db.execute("SELECT * FROM positions WHERE status='open'")]
        pnl = self.db.execute('SELECT COALESCE(SUM(pnl),0) FROM positions').fetchone()[0]
        return {'mode': 'fictional demo' if self.demo else 'snapshot simulation',
                'cash_cents': row['cash'], 'initial_cash_cents': row['initial'],
                'realized_pnl_cents': pnl, 'open_cost_cents': sum(x['cost'] for x in positions),
                'positions': positions}

    def buy(self, proposal, confirmation, now=None):
        if confirmation != proposal['contract']:
            raise ValueError('Contract confirmation did not match')
        if proposal['demo'] != self.demo:
            raise ValueError('Account mode does not match proposal')
        if proposal['quantity'] != 1 or proposal['action'] != 'buy_to_open':
            raise ValueError('Only one-contract long purchases are supported')
        ask = proposal['ask_cents']
        if type(ask) is not int or ask <= 0:
            raise ValueError('Invalid premium')
        if not self.demo:
            fresh(proposal['snapshot_as_of'], now)
        cost = ask * 100 + FEE
        with self.transaction():
            state = self.status()
            if self.db.execute('SELECT 1 FROM positions WHERE id=?', (proposal['id'],)).fetchone():
                raise ValueError('This proposal has already been used')
            if any(x['underlying'] == proposal['underlying'] for x in state['positions']):
                raise ValueError('An open position already exists for this underlying')
            if cost > state['cash_cents']:
                raise ValueError('Insufficient paper cash')
            # Cost-basis capital, NOT a live equity/NAV estimate.
            capital = state['initial_cash_cents'] + state['realized_pnl_cents']
            if cost > min(20000, capital * 2 // 100):
                raise ValueError('Entry exceeds $200 or 2% of capital, including fee')
            if len(state['positions']) >= 3 or state['open_cost_cents'] + cost > capital // 10:
                raise ValueError('Portfolio exposure limit reached')
            today = (now or datetime.now(timezone.utc)).date().isoformat()
            daily = self.db.execute("SELECT COALESCE(SUM(pnl_cents),0) FROM events WHERE kind='sell' AND substr(recorded_at,1,10)=?", (today,)).fetchone()[0]
            if daily <= -state['initial_cash_cents'] * 2 // 100:
                raise ValueError('Daily realized loss limit reached')
            self.db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,NULL)',
                            (proposal['id'], proposal['contract'], proposal['underlying'], proposal['expiry'],
                             proposal['snapshot_as_of'], cost, 'open'))
            self.db.execute('UPDATE account SET cash=cash-? WHERE id=1', (cost,))
            self._event('buy', proposal['id'], proposal['snapshot_as_of'], ask, None, now)
        return self.status()

    def sell(self, contract, bid, as_of, confirmation, now=None):
        if confirmation != contract:
            raise ValueError('Contract confirmation did not match')
        price = cents(bid)
        observed = timestamp(as_of) if self.demo else fresh(as_of, now)
        with self.transaction():
            position = self.db.execute("SELECT * FROM positions WHERE contract=? AND status='open'", (contract,)).fetchone()
            if not position:
                raise ValueError('No open position for this contract')
            if observed < timestamp(position['opened_as_of']):
                raise ValueError('Exit quote predates entry')
            if observed.date().isoformat() >= position['expiry']:
                raise ValueError('Expiry-day settlement is not modeled; use a pre-expiry quote')
            proceeds = price * 100 - FEE
            cash = self.db.execute('SELECT cash FROM account').fetchone()[0]
            if cash + proceeds < 0:
                raise ValueError('Insufficient cash for exit fee')
            pnl = proceeds - position['cost']
            self.db.execute("UPDATE positions SET status='closed',pnl=? WHERE id=?", (pnl, position['id']))
            self.db.execute('UPDATE account SET cash=cash+? WHERE id=1', (proceeds,))
            self._event('sell', position['id'], observed.isoformat(), price, pnl, now)
        return self.status()

    def _event(self, kind, position, as_of, price, pnl, now):
        recorded = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        self.db.execute('INSERT INTO events(recorded_at,kind,position_id,quote_as_of,price_cents,fee_cents,pnl_cents) VALUES(?,?,?,?,?,?,?)',
                        (recorded, kind, position, as_of, price, FEE, pnl))

    def history(self):
        return [dict(x) for x in self.db.execute('SELECT * FROM events ORDER BY seq')]
