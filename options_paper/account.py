"""Transactional paper account. Integer cents, one long call per position."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .engine import cents, fresh, timestamp

FEE = 65  # Illustrative per-contract, per-side commission in cents.
PROFILES = {
    'tutorial': {'initial': '10000', 'max_trade': 20000, 'risk_percent': 2,
                 'max_positions': 3, 'max_exposure_percent': 10, 'daily_loss': 20000},
    'small': {'initial': '200', 'max_trade': 2000, 'risk_percent': 10,
              'max_positions': 1, 'max_exposure_percent': 10, 'daily_loss': 2000},
}


class Account:
    def __init__(self, path, demo=False, starting_cash=None, profile=None):
        if profile is not None and profile not in PROFILES:
            raise ValueError('Unknown risk profile')
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
        CREATE TABLE IF NOT EXISTS marks (
            position_id TEXT PRIMARY KEY, bid_cents INTEGER NOT NULL,
            ask_cents INTEGER NOT NULL, as_of TEXT NOT NULL, assessed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS risk_profile (
            id INTEGER PRIMARY KEY CHECK(id=1), name TEXT NOT NULL);
        ''')
        existing = self.db.execute('SELECT name FROM risk_profile WHERE id=1').fetchone()
        legacy = self.db.execute('SELECT 1 FROM account WHERE id=1').fetchone()
        selected = existing['name'] if existing else 'tutorial' if legacy else profile or 'tutorial'
        if selected not in PROFILES or (profile is not None and profile != selected):
            self.db.close()
            raise ValueError('Persisted risk profile cannot change; use a separate paper account')
        self.profile = selected
        initial = cents(starting_cash if starting_cash is not None else PROFILES[selected]['initial'])
        if initial <= 0:
            raise ValueError('Starting cash must be positive')
        with self.transaction():
            self.db.execute('INSERT OR IGNORE INTO account VALUES(1,?,?,?)', (initial, initial, int(demo)))
            self.db.execute('INSERT OR IGNORE INTO risk_profile VALUES(1,?)', (selected,))
            if self.db.execute('SELECT name FROM risk_profile WHERE id=1').fetchone()[0] != selected:
                raise ValueError('Concurrent profile initialization conflict')
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
        if not self.db.in_transaction:
            with self.transaction(): return self.status()
        row = self.db.execute('SELECT * FROM account').fetchone()
        positions = [dict(x) for x in self.db.execute("SELECT * FROM positions WHERE status='open'")]
        pnl = self.db.execute('SELECT COALESCE(SUM(pnl),0) FROM positions').fetchone()[0]
        return {'mode': 'fictional demo' if self.demo else 'snapshot simulation',
                'risk_profile': self.profile,
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
            limits = PROFILES[self.profile]
            reserved_exit_fees = FEE if self.profile == 'small' else 0
            risk_cost = cost + reserved_exit_fees
            exposure = state['open_cost_cents'] + reserved_exit_fees*len(state['positions'])
            if risk_cost > min(limits['max_trade'], capital * limits['risk_percent'] // 100):
                raise ValueError(f"Entry exceeds profile full-premium risk limit (${limits['max_trade']/100:g} or {limits['risk_percent']}% of capital), including fees")
            if len(state['positions']) >= limits['max_positions'] or exposure + risk_cost > capital * limits['max_exposure_percent'] // 100:
                raise ValueError('Portfolio exposure limit reached')
            today = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date().isoformat()
            daily = self.db.execute("SELECT COALESCE(SUM(pnl_cents),0) FROM events WHERE kind='sell' AND substr(recorded_at,1,10)=?", (today,)).fetchone()[0]
            if daily <= -state['initial_cash_cents'] * 2 // 100:
                if self.profile == 'tutorial': raise ValueError('Daily realized loss limit reached')
            if self.profile == 'small':
                losses = self.db.execute("SELECT COALESCE(SUM(MAX(-pnl_cents,0)),0) FROM events WHERE kind='sell' AND substr(recorded_at,1,10)=?",(today,)).fetchone()[0]
                if losses + exposure + risk_cost > limits['daily_loss']:
                    raise ValueError('Daily loss plus full-premium exposure exceeds $20')
            decision_time = timestamp(proposal['snapshot_as_of']) if self.demo else (now or datetime.now(timezone.utc))
            if decision_time.tzinfo is None: raise ValueError('Timezone required')
            if any(p['expiry'] <= decision_time.date().isoformat() for p in state['positions']):
                raise ValueError('Expired position requires reconciliation before new entries')
            if proposal['expiry'] <= decision_time.date().isoformat():
                raise ValueError('Expired or expiry-day entry refused')
            self.db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,NULL)',
                            (proposal['id'], proposal['contract'], proposal['underlying'], proposal['expiry'],
                             proposal['snapshot_as_of'], cost, 'open'))
            self.db.execute('UPDATE account SET cash=cash-? WHERE id=1', (cost,))
            self._event('buy', proposal['id'], proposal['snapshot_as_of'], ask, None, now)
        return self.status()

    def sell(self, contract, bid, as_of, confirmation, now=None,
             expected_position_id=None, expected_quote=None):
        if confirmation != contract:
            raise ValueError('Contract confirmation did not match')
        price = cents(bid)
        observed = timestamp(as_of) if self.demo else fresh(as_of, now)
        with self.transaction():
            position = self.db.execute("SELECT * FROM positions WHERE contract=? AND status='open'", (contract,)).fetchone()
            if not position:
                raise ValueError('No open position for this contract')
            if expected_position_id is not None and position['id'] != expected_position_id:
                raise ValueError('Position changed; review the exit again')
            mark = self.db.execute('SELECT * FROM marks WHERE position_id=?', (position['id'],)).fetchone()
            if expected_quote is not None and (not mark or
                    (mark['as_of'], mark['bid_cents']) != expected_quote):
                raise ValueError('Quote changed; review the exit again')
            if mark and observed < timestamp(mark['as_of']):
                raise ValueError('Exit quote is older than the saved quote')
            if mark and observed == timestamp(mark['as_of']) and price != mark['bid_cents']:
                raise ValueError('Changed exit price requires a new quote timestamp')
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

