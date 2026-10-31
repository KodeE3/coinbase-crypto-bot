"""Paper-only trade approval gate. No brokerage or exchange execution functions."""
import sqlite3
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

D = Decimal
SCHEMA = '''
CREATE TABLE IF NOT EXISTS proposals (
 id TEXT PRIMARY KEY, pair TEXT NOT NULL, entry TEXT NOT NULL, stop TEXT NOT NULL,
 target TEXT NOT NULL, quantity TEXT NOT NULL, expires TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Pending', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, proposal_id TEXT NOT NULL, kind TEXT NOT NULL,
 at TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fills (
 proposal_id TEXT PRIMARY KEY, price TEXT NOT NULL, quantity TEXT NOT NULL,
 fee TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS paper_account (
 id INTEGER PRIMARY KEY CHECK(id=1), initial TEXT NOT NULL, cash TEXT NOT NULL,
 fee_rate TEXT NOT NULL, slippage TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS exits (
 proposal_id TEXT PRIMARY KEY, price TEXT NOT NULL, quantity TEXT NOT NULL,
 fee TEXT NOT NULL, proceeds TEXT NOT NULL, pnl TEXT NOT NULL,
 quote_at TEXT NOT NULL, at TEXT NOT NULL, reason TEXT NOT NULL);
'''

class GateError(ValueError): pass

def utcnow(): return datetime.now(timezone.utc)
def parse_time(s):
    dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
    if dt.tzinfo is None: raise GateError('Timezone required')
    return dt.astimezone(timezone.utc)

def money(x):
    try: v = D(str(x))
    except (InvalidOperation, ValueError): raise GateError('Invalid number')
    if not v.is_finite(): raise GateError('Nonfinite number')
    return v

def clock(now=None):
    now = now or utcnow()
    if now.tzinfo is None: raise GateError('Timezone required')
    return now.astimezone(timezone.utc)

def fresh_quote(value, now):
    if value is None: raise GateError('Fresh quote timestamp required')
    stamp = parse_time(value)
    if not timedelta(0) <= now-stamp <= timedelta(seconds=60):
        raise GateError('Quote must be no more than 60 seconds old and not future-dated')
    return stamp

class PaperGate:
    def __init__(self, path='paper_gate.sqlite', fee_rate='0.009', slippage='0.001'):
        self.db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.fee_rate, self.slippage = money(fee_rate), money(slippage)
        if not (0 <= self.fee_rate < 1 and 0 <= self.slippage < 1):
            self.db.close()
            raise GateError('Fee/slippage rates must be between zero and one')
        try:
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                account = self.db.execute('SELECT * FROM paper_account WHERE id=1').fetchone()
                if account:
                    if (money(account['fee_rate']),money(account['slippage'])) != (self.fee_rate,self.slippage):
                        raise GateError('Persisted fee/slippage settings cannot change')
                else:
                    # Upgrade v0.6 without resetting or crediting pre-existing entries twice.
                    spent = sum((money(r['price'])*money(r['quantity'])+money(r['fee'])
                                 for r in self.db.execute('SELECT * FROM fills')), D('0'))
                    proceeds = sum((money(r[0]) for r in self.db.execute('SELECT proceeds FROM exits')), D('0'))
                    cash = D('100')-spent+proceeds
                    if cash < 0: raise GateError('Legacy fills exceed initial cash; reconcile before migration')
                    self.db.execute('INSERT INTO paper_account VALUES(1,?,?,?,?)',
                                    ('100',str(cash),str(self.fee_rate),str(self.slippage)))
        except Exception:
            self.db.close()
            raise

    def close(self): self.db.close()

    def status(self):
        if not self.db.in_transaction:
            with self.db:
                self.db.execute('BEGIN')
                return self.status()
        account = self.db.execute('SELECT * FROM paper_account WHERE id=1').fetchone()
        pnl = sum((money(r[0]) for r in self.db.execute('SELECT pnl FROM exits')),D('0'))
        cost = sum((money(r['price'])*money(r['quantity'])+money(r['fee']) for r in self.db.execute(
            "SELECT f.* FROM fills f JOIN proposals p ON p.id=f.proposal_id WHERE p.status='Open'")),D('0'))
        cash, initial = money(account['cash']),money(account['initial'])
        if cash+cost != initial+pnl: raise GateError('Cash ledger reconciliation failed')
        return {'mode':'PAPER_ONLY','initial_usd':str(initial),'cash_usd':str(cash),
                'open_cost_usd':str(cost),'realized_pnl_usd':str(pnl),
                'equity_at_cost_usd':str(cash+cost),'reconciled':True,
                'closed_trades':self.db.execute('SELECT count(*) FROM exits').fetchone()[0]}

    def _event(self, pid, kind, detail, at):
        self.db.execute('INSERT INTO events(proposal_id,kind,at,detail) VALUES (?,?,?,?)',
                        (pid,kind,at.isoformat(),json.dumps(detail,sort_keys=True)))

    def _risk(self, entry, stop, target, qty):
        if not (entry > stop > 0 and target > entry and qty > 0):
            raise GateError('Long-only positive entry > stop and target > entry required')
        buy = entry * (1+self.slippage)
        sell_stop = stop * (1-self.slippage)
        sell_target = target * (1-self.slippage)
        fees_stop = self.fee_rate * (buy+sell_stop)*qty
        fees_target = self.fee_rate * (buy+sell_target)*qty
        loss = (buy-sell_stop)*qty+fees_stop
        gain = (sell_target-buy)*qty-fees_target
        if loss <= 0 or gain/loss < 2: raise GateError('Net reward/risk below 2:1')
        if loss > D('1'): raise GateError('Planned risk exceeds $1')
        if buy*qty*(1+self.fee_rate) > D('100'): raise GateError('Exceeds $100 paper cash including fees')
        return loss

    def propose(self, pid, pair, entry, stop, target, quantity, expires, now=None):
        now=clock(now); expiry=parse_time(expires)
        if now.tzinfo is None: raise GateError('Timezone required')
        if expiry <= now: raise GateError('Expired at creation')
        if pair not in ('BTC-USD','ETH-USD','SOL-USD'): raise GateError('Unsupported pair')
        e,s,t,q=map(money,(entry,stop,target,quantity))
        risk=self._risk(e,s,t,q)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.db.execute("SELECT 1 FROM proposals WHERE status='Open'").fetchone(): raise GateError('Open position exists')
            if self.db.execute('SELECT 1 FROM proposals WHERE id=?',(pid,)).fetchone(): raise GateError('Duplicate proposal')
            self.db.execute('INSERT INTO proposals VALUES (?,?,?,?,?,?,?,?,?)',
                            (pid,pair,str(e),str(s),str(t),str(q),expiry.isoformat(),'Pending',now.isoformat()))
            self._event(pid,'PROPOSE',{'risk':str(risk)},now)
        return {'id':pid,'status':'Pending','planned_loss_usd':str(risk)}

    def decide(self, pid, approve, now=None):
        now=clock(now)
        if type(approve) is not bool: raise GateError('Approval must be boolean')
        if now.tzinfo is None: raise GateError('Timezone required')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            p=self.db.execute('SELECT * FROM proposals WHERE id=?',(pid,)).fetchone()
            if not p: raise GateError('Unknown proposal')
            if p['status']!='Pending': raise GateError('Only pending proposals may be decided')
            status='Approved' if approve and parse_time(p['expires'])>now else 'Expired' if approve else 'Rejected'
            self.db.execute('UPDATE proposals SET status=? WHERE id=?',(status,pid))
            self._event(pid,status.upper(),{},now)
        return status

    def simulate_entry(self, pid, market_price, candle_utc, now=None, *, quote_utc=None):
        """Explicit paper simulation; no Coinbase trading code or external side effects."""
        now=clock(now); price=money(market_price)
        if now.tzinfo is None: raise GateError('Timezone required')
        if now-parse_time(candle_utc) > timedelta(hours=48): raise GateError('Stale candle')
        if parse_time(candle_utc)>now: raise GateError('Future candle')
        observed = fresh_quote(quote_utc,now)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            p=self.db.execute('SELECT * FROM proposals WHERE id=?',(pid,)).fetchone()
            if not p or p['status']!='Approved': raise GateError('Approval required')
            if parse_time(p['expires'])<=now: raise GateError('Approval expired')
            decision=self.db.execute("SELECT at FROM events WHERE proposal_id=? AND kind='APPROVED' ORDER BY id DESC LIMIT 1",(pid,)).fetchone()
            if not decision or observed<parse_time(decision['at']): raise GateError('Quote must follow explicit approval')
            if self.db.execute("SELECT 1 FROM proposals WHERE status='Open'").fetchone(): raise GateError('Open position exists')
            e,s,t,q=map(money,(p['entry'],p['stop'],p['target'],p['quantity']))
            # Only fill a limit-style entry when market is at or below approved entry.
            if price>e: raise GateError('Entry trigger not met')
            if price<=s: raise GateError('Market price already at or below stop')
            risk=self._risk(price,s,t,q)
            today=now.date().isoformat()
            spent=D('0')
            for row in self.db.execute("SELECT detail FROM events WHERE kind='OPEN' AND substr(at,1,10)=?",(today,)):
                spent+=money(json.loads(row['detail'])['planned_loss_usd'])
            if spent+risk>D('3'): raise GateError('Daily planned loss cap exceeded')
            fill_price=price*(1+self.slippage)
            fee=fill_price*q*self.fee_rate
            cost=fill_price*q+fee
            state=self.status()
            if cost>money(state['cash_usd']): raise GateError('Insufficient available paper cash')
            realized_losses=sum((max(-money(r[0]),D('0')) for r in self.db.execute(
                'SELECT pnl FROM exits WHERE substr(at,1,10)=?',(today,))),D('0'))
            if realized_losses+risk>D('3'): raise GateError('Daily realized loss budget exceeded')
            self.db.execute('INSERT INTO fills VALUES (?,?,?,?,?)',(pid,str(fill_price),str(q),str(fee),now.isoformat()))
            self.db.execute('UPDATE paper_account SET cash=? WHERE id=1',(str(money(state['cash_usd'])-cost),))
            self.db.execute("UPDATE proposals SET status='Open' WHERE id=?",(pid,))
            self._event(pid,'OPEN',{'planned_loss_usd':str(risk),'paper_only':True,'quote_at':observed.isoformat()},now)
        return {'proposal_id':pid,'paper_fill_price':str(fill_price),'fee_usd':str(fee),'status':'Open'}

    def evaluate_exit(self, pid, market_price, quote_utc, now=None):
        """Automatically simulate a stop/target exit, never submit a broker order.

        A gap fills at the observed adverse price. A favorable target gap fills
        no better than the target. This is point-in-time sampling, not OHLC replay.
        """
        now=clock(now); price=money(market_price); observed=fresh_quote(quote_utc,now)
        if price<=0: raise GateError('Positive quote required')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            prior=self.db.execute('SELECT * FROM exits WHERE proposal_id=?',(pid,)).fetchone()
            if prior: return {'status':'Closed','duplicate':True,'pnl_usd':prior['pnl']}
            p=self.db.execute('SELECT * FROM proposals WHERE id=?',(pid,)).fetchone()
            fill=self.db.execute('SELECT * FROM fills WHERE proposal_id=?',(pid,)).fetchone()
            if not p or p['status']!='Open' or not fill: raise GateError('Open paper position required')
            if observed<parse_time(fill['at']): raise GateError('Exit quote predates entry')
            stop,target,q=map(money,(p['stop'],p['target'],fill['quantity']))
            if price>stop and price<target: return {'status':'Open','reason':'no_exit_trigger'}
            reason='stop' if price<=stop else 'target'
            exit_price=min(price,target)*(1-self.slippage)
            gross=exit_price*q; fee=gross*self.fee_rate; proceeds=gross-fee
            pnl=proceeds-money(fill['price'])*q-money(fill['fee'])
            state=self.status()
            self.db.execute('INSERT INTO exits VALUES(?,?,?,?,?,?,?,?,?)',
                (pid,str(exit_price),str(q),str(fee),str(proceeds),str(pnl),observed.isoformat(),now.isoformat(),reason))
            self.db.execute('UPDATE paper_account SET cash=? WHERE id=1',(str(money(state['cash_usd'])+proceeds),))
            self.db.execute("UPDATE proposals SET status='Closed' WHERE id=?",(pid,))
            self._event(pid,'CLOSE',{'paper_only':True,'reason':reason,'pnl_usd':str(pnl)},now)
        return {'status':'Closed','reason':reason,'paper_exit_price':str(exit_price),
                'fee_usd':str(fee),'pnl_usd':str(pnl),'duplicate':False}
