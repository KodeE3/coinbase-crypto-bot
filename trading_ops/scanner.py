"""Opt-in, unvalidated daily breakout research. Creates Pending paper proposals only."""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from pathlib import Path

from coinbase_paper.gate import PaperGate, clock, fresh_quote, money, parse_time
from .spot import SpotData, completed_daily_rows

STRATEGY = 'daily-breakout-v1'
WINDOW = 21
QUANTUM = Decimal('0.00000001')  # Simulation precision, not exchange order increments.
SCAN_SCHEMA = '''
CREATE TABLE IF NOT EXISTS spot_scan_runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, strategy TEXT NOT NULL, pair TEXT NOT NULL,
 at TEXT NOT NULL, candle_end TEXT NOT NULL, outcome TEXT NOT NULL, detail TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS spot_scan_latest ON spot_scan_runs(strategy,pair,id);
'''


def candle_end(now):
    return clock(now).replace(hour=0, minute=0, second=0, microsecond=0)


def proposal_id(pair, now):
    return f'{STRATEGY}:{pair}:{candle_end(now).date().isoformat()}'


def build_candidate(pair, rows, quote, capacity, fee_rate, slippage, now):
    """A falsifiable research rule, with all arithmetic in Decimal.

    Last completed daily close must exceed all 20 previous highs. A current bid
    must still hold that breakout; the ask must be within 1% above that close.
    Stop is the last five completed days' low, target is 2.5 net R after costs.
    """
    now=clock(now)
    if pair not in SpotData.PAIRS: raise ValueError('unsupported pair')
    bars=completed_daily_rows(rows, WINDOW, now)
    breakout=max(money(row[2]) for row in bars[:-1])
    close=money(bars[-1][4])
    if close<=breakout:
        return {'status':'no_breakout','close':str(close),'breakout_level':str(breakout)}
    if quote is None: return {'status':'quote_required'}
    observed=fresh_quote(quote['at'],now)
    if observed<candle_end(now): raise ValueError('quote predates signal')
    bid,entry=money(quote['bid']),money(quote['ask'])
    if not 0<bid<=entry or (entry-bid)/entry>Decimal('0.005'):
        raise ValueError('invalid or wide quote')
    if bid<=breakout: return {'status':'breakout_not_held'}
    if entry>close*Decimal('1.01'): return {'status':'price_extended'}
    stop=min(money(row[1]) for row in bars[-5:])
    fee,slip=money(fee_rate),money(slippage)
    if not 0<=fee<1 or not 0<=slip<1 or not 0<stop<entry:
        raise ValueError('invalid cost or stop model')
    unit_cost=entry*(1+slip)*(1+fee)
    unit_stop=stop*(1-slip)*(1-fee)
    unit_risk=unit_cost-unit_stop
    # Capacity is the gate's current $1/$3 budgets and available fictional cash.
    risk_budget=min(Decimal('1'),money(capacity['max_new_risk_usd']))
    buying_power=min(Decimal('100'),money(capacity['buying_power_usd']))
    if risk_budget<=0 or buying_power<=0: return {'status':'risk_budget_exhausted'}
    quantity=min(risk_budget/unit_risk,buying_power/unit_cost).quantize(QUANTUM,rounding=ROUND_DOWN)
    if quantity<=0: return {'status':'quantity_below_simulation_precision'}
    target=((unit_cost+Decimal('2.5')*unit_risk)/((1-slip)*(1-fee))).quantize(QUANTUM,rounding=ROUND_UP)
    risk=quantity*unit_risk
    gain=quantity*(target*(1-slip)*(1-fee)-unit_cost)
    expires=min(now+timedelta(hours=4),candle_end(now)+timedelta(days=1))
    evidence={'strategy':STRATEGY,'classification':'unvalidated_research',
        'source':'Coinbase Exchange public candles/ticker','signal_end':candle_end(now).isoformat(),
        'observed_at':now.isoformat(),'candles':bars,'quote':{'bid':str(bid),'ask':str(entry),'at':quote['at']},
        'quote_time_basis':'latest trade; not an independent bid/ask timestamp',
        'entry_floor':str(breakout),'fee_rate':str(fee),'slippage':str(slip),
        'planned_loss_usd':str(risk),'modeled_net_gain_usd':str(gain),
        'modeled_net_reward_risk':str(gain/risk),'entry_cost_usd':str(quantity*unit_cost),
        'capacity':capacity,'quantity_precision':str(QUANTUM)}
    return {'status':'candidate','id':proposal_id(pair,now),'pair':pair,'entry':str(entry),
        'stop':str(stop),'target':str(target),'quantity':str(quantity),
        'expires':expires.isoformat(),'evidence':evidence}


def scan_cycle(db, stop, provider=None, now=None):
    """Scan fixed BTC/ETH/SOL priority, with at most one unresolved proposal.

    Persist one-hour attempt cooldowns across restarts, and cache a no-breakout
    result until the next UTC day. Rejected/expired signals are never recreated.
    The single-worker lock belongs to the supervisor; the gate additionally
    enforces the empty approval queue inside its write transaction.
    """
    provider=provider or SpotData()
    at=lambda:clock(now)  # Real calls recheck time after I/O; tests may inject a clock.
    gate=PaperGate(db)
    try:
        gate.db.executescript(SCAN_SCHEMA)
        gate.expire_queued(at())
        if Path(stop).exists(): return {'status':'blocked','reason':'stop_file'}
        if gate.db.execute("SELECT 1 FROM proposals WHERE status IN ('Pending','Approved','Open')").fetchone():
            return {'status':'blocked','reason':'unresolved_proposal_or_open_position'}
        capacity=gate.entry_capacity(at())
        if money(capacity['max_new_risk_usd'])<=0 or money(capacity['buying_power_usd'])<=0:
            return {'status':'blocked','reason':'risk_budget_exhausted'}
        results=[]
        for pair in SpotData.PAIRS:
            started=at();end=candle_end(started);pid=proposal_id(pair,started)
            if Path(stop).exists():
                results.append({'pair':pair,'status':'blocked_by_stop_file'});break
            existing=gate.db.execute('SELECT status FROM proposals WHERE id=?',(pid,)).fetchone()
            if existing:
                results.append({'pair':pair,'status':'already_processed','proposal_status':existing['status'],'id':pid});continue
            previous=gate.db.execute('SELECT * FROM spot_scan_runs WHERE strategy=? AND pair=? ORDER BY id DESC LIMIT 1',
                (STRATEGY,pair)).fetchone()
            if previous:
                elapsed=started-parse_time(previous['at'])
                if elapsed<timedelta(0):
                    results.append({'pair':pair,'status':'error','error_type':'FutureScanTimestamp'});continue
                if previous['candle_end']==end.isoformat() and previous['outcome']=='no_breakout':
                    results.append({'pair':pair,'status':'cached_no_breakout'});continue
                if elapsed<timedelta(hours=1):
                    results.append({'pair':pair,'status':'cooldown'});continue
            try:
                rows=provider.daily_candles(pair,count=WINDOW,now=started)
                result=build_candidate(pair,rows,None,capacity,gate.fee_rate,gate.slippage,at())
                if result['status']=='quote_required':
                    if Path(stop).exists():
                        results.append({'pair':pair,'status':'blocked_by_stop_file'});break
                    quote=provider.quote(pair)
                    result=build_candidate(pair,rows,quote,gate.entry_capacity(at()),gate.fee_rate,gate.slippage,at())
                if Path(stop).exists():
                    results.append({'pair':pair,'status':'blocked_by_stop_file'});break
                if result['status']=='candidate':
                    gate.propose(result['id'],pair,result['entry'],result['stop'],result['target'],
                        result['quantity'],result['expires'],at(),evidence=result['evidence'],require_empty_queue=True)
                    result={**result,'status':'Pending'}
            except Exception as exc:
                # Provider exceptions may contain secrets or HTTP payloads.
                result={'status':'error','error_type':type(exc).__name__}
            gate.db.execute('INSERT INTO spot_scan_runs(strategy,pair,at,candle_end,outcome,detail) VALUES(?,?,?,?,?,?)',
                (STRATEGY,pair,at().isoformat(),end.isoformat(),result['status'],json.dumps(result,sort_keys=True,allow_nan=False)))
            results.append({'pair':pair,**result})
            if result['status']=='Pending':break
        return {'status':'error' if any(r['status']=='error' for r in results) else 'ok',
                'strategy':STRATEGY,'approval_required':True,'results':results}
    finally:
        gate.close()
