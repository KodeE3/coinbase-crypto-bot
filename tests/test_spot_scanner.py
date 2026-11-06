import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from coinbase_paper.gate import GateError, PaperGate
from trading_ops.scanner import build_candidate, candle_end, proposal_id, scan_cycle
from trading_ops.spot import SpotData, completed_daily_rows
from trading_ops.worker import run_cycle, spot_cycle
from trading_ops.demo import run_demo

NOW = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)


def candles(now=NOW, breakout=True):
    end=int(candle_end(now).timestamp())
    rows=[[end-(21-i)*86400, '99', '101', '100', '100', '10'] for i in range(21)]
    if breakout: rows[-1]=[end-86400, '100', '104', '100', '103', '12']
    return rows


def quote(now=NOW, bid='102.9', ask='103'):
    return {'bid':bid,'ask':ask,'at':now.isoformat()}


class FixtureProvider:
    def __init__(self, signals=('BTC-USD',), now=NOW):
        self.signals=signals;self.now=now;self.calls=[]

    def daily_candles(self,pair,count=21,now=None):
        self.calls.append(('candles',pair))
        return candles(now or self.now,pair in self.signals)

    def quote(self,pair):
        self.calls.append(('quote',pair))
        return quote(self.now)

    def completed_candle(self,pair):
        return candle_end(self.now).isoformat()


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'coinbase.sqlite';self.stop=self.root/'STOP'
        self.g=PaperGate(self.path);self.addCleanup(self.g.close)

    def candidate(self,rows=None,observation=None,capacity=None):
        return build_candidate('BTC-USD',rows if rows is not None else candles(),
            observation if observation is not None else quote(),
            capacity or self.g.entry_capacity(NOW),self.g.fee_rate,self.g.slippage,NOW)

    def test_full_demo_is_offline_and_uses_disposable_account(self):
        before=self.g.status()
        with patch('socket.socket',side_effect=AssertionError('network')),\
             patch('builtins.input',side_effect=AssertionError('prompt')):
            result=run_demo()
        self.assertEqual(result['account']['closed_trades'],1)
        self.assertTrue(result['duplicate_exit_prevented'])
        self.assertEqual(self.g.status(),before)

    def test_fee_aware_risk_cash_and_target_at_multiple_price_scales(self):
        for scale in ('0.01','1','1000'):
            factor=Decimal(scale)
            rows=[[row[0],*[str(Decimal(x)*factor) for x in row[1:5]],row[5]] for row in candles()]
            c=self.candidate(rows,quote(bid=str(Decimal('102.9')*factor),ask=str(Decimal('103')*factor)))
            e,s,t,q=map(Decimal,(c['entry'],c['stop'],c['target'],c['quantity']))
            cost=e*Decimal('1.001')*Decimal('1.009')*q
            stop_proceeds=s*Decimal('.999')*Decimal('.991')*q
            target_proceeds=t*Decimal('.999')*Decimal('.991')*q
            self.assertLessEqual(cost-stop_proceeds,1)
            self.assertLessEqual(cost,100)
            self.assertGreaterEqual((target_proceeds-cost)/(cost-stop_proceeds),Decimal('2.5'))
            self.assertGreaterEqual(self.g._risk(e,s,t,q),0)

    def test_sizing_respects_reduced_cash_and_remaining_daily_risk(self):
        for capacity in ({'buying_power_usd':'2','max_new_risk_usd':'1'},
                         {'buying_power_usd':'100','max_new_risk_usd':'.05'}):
            c=self.candidate(capacity=capacity)
            self.assertLessEqual(Decimal(c['evidence']['entry_cost_usd']),Decimal(capacity['buying_power_usd']))
            self.assertLessEqual(Decimal(c['evidence']['planned_loss_usd']),Decimal(capacity['max_new_risk_usd']))

    def test_no_breakout_does_not_need_quote(self):
        result=build_candidate('BTC-USD',candles(breakout=False),None,self.g.entry_capacity(NOW),'.009','.001',NOW)
        self.assertEqual(result['status'],'no_breakout')

    def test_current_incomplete_candle_never_changes_signal(self):
        rows=candles();rows.append([int(candle_end(NOW).timestamp()),'1','10000','100','9999','12'])
        self.assertEqual(self.candidate(rows),self.candidate())
        neutral=candles(breakout=False)+rows[-1:]
        self.assertEqual(self.candidate(neutral)['status'],'no_breakout')

    def test_unsorted_and_extra_earlier_candles_are_normalized(self):
        rows=candles();rows.insert(0,[rows[0][0]-86400,'1','2','1','2','1'])
        self.assertEqual(self.candidate(rows[::-1]),self.candidate())

    def test_missing_duplicate_future_misaligned_or_invalid_bars_fail_closed(self):
        variants=[candles()[1:],candles()+candles()[:1],candles(NOW-timedelta(days=1))]
        for index,value in [(0,int(candle_end(NOW).timestamp())+86400),(0,1),
                            (1,'NaN'),(2,'98'),(4,'Infinity'),(5,'-1')]:
            rows=candles();rows[-1][index]=value;variants.append(rows)
        for rows in variants:
            with self.subTest(rows=rows[-1]),self.assertRaises((ValueError,RuntimeError)):
                self.candidate(rows)

    def test_stale_future_crossed_wide_and_nonfinite_quotes_fail_closed(self):
        bad=[quote(NOW-timedelta(seconds=61)),quote(NOW+timedelta(seconds=1)),
             quote(bid='104'),quote(bid='100'),quote(ask='NaN'),quote(bid='-1')]
        for q in bad:
            with self.subTest(q=q),self.assertRaises((ValueError,RuntimeError)):
                self.candidate(observation=q)

    def test_failed_breakout_and_extended_price_are_skipped(self):
        self.assertEqual(self.candidate(observation=quote(bid='100.99',ask='101.1'))['status'],'breakout_not_held')
        self.assertEqual(self.candidate(observation=quote(bid='104.9',ask='105'))['status'],'price_extended')

    def test_scan_creates_pending_with_transactional_evidence_and_no_fill(self):
        with patch('socket.socket',side_effect=AssertionError('unexpected network')):
            r=scan_cycle(self.path,self.stop,FixtureProvider(),NOW)
        self.assertEqual(r['results'][0]['status'],'Pending')
        self.assertEqual(self.g.status()['cash_usd'],'100')
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM fills').fetchone()[0],0)
        event=json.loads(self.g.db.execute("SELECT detail FROM events WHERE kind='PROPOSE'").fetchone()[0])
        self.assertEqual(len(event['evidence']['candles']),21)
        pid=r['results'][0]['id']
        with self.assertRaisesRegex(GateError,'Approval required'):
            self.g.simulate_entry(pid,103,candle_end(NOW).isoformat(),NOW,quote_utc=NOW.isoformat())

    def test_approved_candidate_opens_closes_and_reconciles(self):
        r=scan_cycle(self.path,self.stop,FixtureProvider(),NOW);c=r['results'][0]
        later=NOW+timedelta(seconds=10)
        self.g.decide(c['id'],True,later)
        with self.assertRaisesRegex(GateError,'follow explicit approval'):
            self.g.simulate_entry(c['id'],103,candle_end(NOW).isoformat(),later,quote_utc=NOW.isoformat())
        self.g.simulate_entry(c['id'],103,candle_end(NOW).isoformat(),later,quote_utc=later.isoformat())
        result=self.g.evaluate_exit(c['id'],c['target'],later.isoformat(),later)
        self.assertEqual(result['status'],'Closed')
        self.assertTrue(self.g.status()['reconciled'])
        self.assertEqual(Decimal(result['pnl_usd']),Decimal(c['evidence']['modeled_net_gain_usd']))

    def test_approved_signal_cannot_enter_below_breakout_even_above_stop(self):
        scan_cycle(self.path,self.stop,FixtureProvider(),NOW);pid=proposal_id('BTC-USD',NOW)
        self.g.decide(pid,True,NOW)
        with self.assertRaisesRegex(GateError,'signal no longer held'):
            self.g.simulate_entry(pid,'100.5',candle_end(NOW).isoformat(),NOW,quote_utc=NOW.isoformat())
        self.assertEqual(self.g.status()['cash_usd'],'100')

    def test_restart_and_rejected_signal_never_recreate_same_proposal(self):
        p=FixtureProvider();scan_cycle(self.path,self.stop,p,NOW)
        self.assertEqual(scan_cycle(self.path,self.stop,p,NOW)['status'],'blocked')
        self.g.decide(proposal_id('BTC-USD',NOW),False,NOW)
        result=scan_cycle(self.path,self.stop,p,NOW+timedelta(hours=2))
        self.assertEqual(result['results'][0]['status'],'already_processed')
        self.assertEqual(sum(pair=='BTC-USD' and kind=='candles' for kind,pair in p.calls),1)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM proposals').fetchone()[0],1)

    def test_expired_signal_is_not_recreated_and_next_day_has_new_identity(self):
        p=FixtureProvider();scan_cycle(self.path,self.stop,p,NOW)
        r=scan_cycle(self.path,self.stop,p,NOW+timedelta(hours=5))
        self.assertEqual(r['results'][0]['proposal_status'],'Expired')
        tomorrow=NOW+timedelta(days=1)
        r=scan_cycle(self.path,self.stop,FixtureProvider(now=tomorrow),tomorrow)
        self.assertEqual(r['results'][0]['status'],'Pending')
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM proposals').fetchone()[0],2)

    def test_expiry_never_extends_past_next_daily_signal(self):
        late=NOW.replace(hour=23,minute=30)
        r=scan_cycle(self.path,self.stop,FixtureProvider(now=late),late)
        self.assertEqual(r['results'][0]['expires'],(candle_end(late)+timedelta(days=1)).isoformat())

    def test_stop_before_requests_after_candles_and_after_quote(self):
        for phase in ('before','candles','quote'):
            with self.subTest(phase=phase):
                self.stop.unlink(missing_ok=True);p=FixtureProvider()
                if phase=='before':self.stop.touch()
                else:
                    method='daily_candles' if phase=='candles' else 'quote'
                    original=getattr(p,method)
                    def stopped(*args,**kwargs):
                        self.stop.touch();return original(*args,**kwargs)
                    setattr(p,method,stopped)
                scan_cycle(self.path,self.stop,p,NOW)
                self.assertEqual(self.g.db.execute('SELECT count(*) FROM proposals').fetchone()[0],0)
                if phase=='before':self.assertEqual(p.calls,[])

    def test_no_breakout_cached_until_next_day_without_quote_polling(self):
        p=FixtureProvider(signals=())
        scan_cycle(self.path,self.stop,p,NOW)
        r=scan_cycle(self.path,self.stop,p,NOW+timedelta(hours=2))
        self.assertEqual(len(p.calls),3)
        self.assertTrue(all(x['status']=='cached_no_breakout' for x in r['results']))

    def test_error_cooldown_survives_restart_and_redacts_provider_message(self):
        p=FixtureProvider()
        p.daily_candles=lambda *a,**kw:(_ for _ in ()).throw(ValueError('secret-provider-token'))
        r=scan_cycle(self.path,self.stop,p,NOW)
        self.assertEqual(r['status'],'error')
        p=FixtureProvider(signals=())
        r=scan_cycle(self.path,self.stop,p,NOW+timedelta(minutes=1))
        self.assertEqual(p.calls,[])
        self.assertTrue(all(x['status']=='cooldown' for x in r['results']))
        scan_cycle(self.path,self.stop,p,NOW+timedelta(hours=1))
        self.assertEqual(len(p.calls),3)
        details=''.join(x[0] for x in self.g.db.execute('SELECT detail FROM spot_scan_runs'))
        self.assertNotIn('secret-provider-token',details)

    def test_one_failed_asset_does_not_hide_another_signal(self):
        p=FixtureProvider(signals=('ETH-USD',));original=p.daily_candles
        def fetch(pair,**kwargs):
            if pair=='BTC-USD':raise ValueError('bad data')
            return original(pair,**kwargs)
        p.daily_candles=fetch
        r=scan_cycle(self.path,self.stop,p,NOW)
        self.assertEqual(r['status'],'error')
        self.assertEqual(r['results'][-1]['pair'],'ETH-USD')
        self.assertEqual(r['results'][-1]['status'],'Pending')

    def test_exhausted_realized_loss_budget_prevents_scan_network_calls(self):
        self.g.propose('loss','BTC-USD',100,95,120,'.1',(NOW+timedelta(hours=1)).isoformat(),NOW)
        self.g.decide('loss',True,NOW)
        self.g.simulate_entry('loss',100,NOW.isoformat(),NOW,quote_utc=NOW.isoformat())
        self.g.evaluate_exit('loss',1,NOW.isoformat(),NOW)
        p=FixtureProvider();r=scan_cycle(self.path,self.stop,p,NOW)
        self.assertEqual(r['reason'],'risk_budget_exhausted');self.assertEqual(p.calls,[])

    def test_queue_created_during_network_request_is_rechecked_atomically(self):
        p=FixtureProvider();original=p.quote
        def fetch(pair):
            self.g.propose('manual','ETH-USD',100,95,120,'.1',(NOW+timedelta(hours=1)).isoformat(),NOW)
            return original(pair)
        p.quote=fetch
        scan_cycle(self.path,self.stop,p,NOW)
        self.assertEqual([x[0] for x in self.g.db.execute('SELECT id FROM proposals')],['manual'])

    def test_concurrent_scans_queue_only_one_proposal(self):
        barrier=threading.Barrier(2)
        def scan(_):
            p=FixtureProvider();original=p.daily_candles
            def fetch(pair,**kwargs):
                if pair=='BTC-USD':barrier.wait(timeout=5)
                return original(pair,**kwargs)
            p.daily_candles=fetch
            return scan_cycle(self.path,self.stop,p,NOW)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(scan,range(2)))
        self.assertEqual(sum(x['status']=='Pending' for r in results for x in r['results']),1)
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM proposals').fetchone()[0],1)

    def test_evidence_failure_rolls_back_proposal(self):
        with patch('coinbase_paper.gate.PaperGate._event',side_effect=OSError('disk')):
            r=scan_cycle(self.path,self.stop,FixtureProvider(),NOW)
        self.assertEqual(r['status'],'error')
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM proposals').fetchone()[0],0)

    def test_default_worker_scanner_disabled_and_opt_in_only_queues(self):
        now=datetime.now(timezone.utc);p=FixtureProvider(now=now)
        r=run_cycle(self.root,spot_provider=p)
        self.assertEqual(r['components']['spot_scanner']['status'],'disabled');self.assertEqual(p.calls,[])
        r=run_cycle(self.root,spot_provider=p,scan_spot=True)
        self.assertEqual(r['components']['spot_scanner']['results'][0]['status'],'Pending')
        self.assertEqual(self.g.status()['cash_usd'],'100')

    def test_exit_checked_before_older_broken_entry(self):
        now=datetime.now(timezone.utc)-timedelta(seconds=2)
        for pid,pair in [('older','BTC-USD'),('open','ETH-USD')]:
            self.g.propose(pid,pair,100,95,120,'.1',(now+timedelta(hours=1)).isoformat(),now)
            self.g.decide(pid,True,now)
        self.g.simulate_entry('open',100,now.isoformat(),now,quote_utc=now.isoformat())
        p=FixtureProvider(now=datetime.now(timezone.utc))
        def fetch(pair):
            if pair=='BTC-USD':raise ValueError('secret-token')
            return quote(datetime.now(timezone.utc),'120','120')
        p.quote=fetch
        r=spot_cycle(self.path,self.stop,p)
        self.assertEqual(r['actions'][0]['status'],'Closed')
        self.assertEqual(r['account']['closed_trades'],1)
        self.assertEqual(r['status'],'error')
        self.assertNotIn('secret-token',json.dumps(r))

    def test_blocked_entry_does_not_prevent_next_approved_entry(self):
        now=datetime.now(timezone.utc)-timedelta(seconds=2)
        for pid,pair in [('bad','BTC-USD'),('good','ETH-USD')]:
            self.g.propose(pid,pair,100,95,120,'.1',(now+timedelta(hours=1)).isoformat(),now)
            self.g.decide(pid,True,now)
        p=FixtureProvider(now=datetime.now(timezone.utc))
        p.quote=lambda pair:quote(datetime.now(timezone.utc),*(['94','94'] if pair=='BTC-USD' else ['100','100']))
        r=spot_cycle(self.path,self.stop,p)
        self.assertEqual(r['actions'][0]['status'],'blocked_by_entry_gate')
        self.assertEqual(r['actions'][1]['status'],'Open')

    def test_expiration_is_idempotent_and_never_closes_open_position(self):
        for pid in ('pending','approved','open'):
            self.g.propose(pid,'BTC-USD',100,95,120,'.1',(NOW+timedelta(hours=1)).isoformat(),NOW)
        for pid in ('approved','open'):self.g.decide(pid,True,NOW)
        self.g.simulate_entry('open',100,NOW.isoformat(),NOW,quote_utc=NOW.isoformat())
        self.assertEqual(set(self.g.expire_queued(NOW+timedelta(hours=2))),{'pending','approved'})
        self.assertEqual(self.g.expire_queued(NOW+timedelta(hours=2)),[])
        self.assertEqual(self.g.db.execute("SELECT status FROM proposals WHERE id='open'").fetchone()[0],'Open')

    def test_adapter_requests_bounded_daily_window_and_validates_before_network(self):
        data=SpotData()
        with patch.object(data,'_get',return_value=candles()[::-1]) as get:
            self.assertEqual(data.daily_candles('BTC-USD',now=NOW),candles())
            self.assertEqual(get.call_args.args[:2],('BTC-USD','candles'))
            self.assertEqual(get.call_args.args[2]['granularity'],86400)
        for count in (0,300,True,1.5):
            with patch.object(data,'_get',side_effect=AssertionError('network')):
                with self.assertRaises(RuntimeError):data.daily_candles('BTC-USD',count=count,now=NOW)


if __name__=='__main__':unittest.main()
