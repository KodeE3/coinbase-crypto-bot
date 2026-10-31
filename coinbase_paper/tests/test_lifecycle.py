import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from gate import PaperGate,GateError

class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'account.sqlite'
        self.g=PaperGate(self.path);self.addCleanup(self.g.close)
        self.now=datetime(2026,10,31,15,tzinfo=timezone.utc)

    def entry(self,pid='p',now=None):
        now=now or self.now
        self.g.propose(pid,'BTC-USD',100,95,120,'0.1',(now+timedelta(hours=3)).isoformat(),now)
        self.g.decide(pid,True,now)
        return self.g.simulate_entry(pid,100,now.isoformat(),now,quote_utc=now.isoformat())

    def test_target_cash_costs_and_restart(self):
        self.entry()
        self.assertEqual(Decimal(self.g.status()['cash_usd']),Decimal('89.89991'))
        now=self.now+timedelta(seconds=20)
        r=self.g.evaluate_exit('p',125,now.isoformat(),now)
        self.assertEqual(r['paper_exit_price'],'119.880')
        self.assertEqual(Decimal(r['pnl_usd']),Decimal('1.780018'))
        other=PaperGate(self.path)
        try:
            self.assertEqual(Decimal(other.status()['cash_usd']),Decimal('101.780018'))
            self.assertTrue(other.status()['reconciled'])
            self.assertTrue(other.evaluate_exit('p',125,now.isoformat(),now)['duplicate'])
            self.assertEqual(other.status()['closed_trades'],1)
        finally:other.close()

    def test_stop_gap_uses_actual_lower_price_and_blocks_next_entry(self):
        self.entry();later=self.now+timedelta(seconds=1)
        result=self.g.evaluate_exit('p',1,later.isoformat(),later)
        self.assertLess(Decimal(result['pnl_usd']),Decimal('-3'))
        self.g.propose('q','BTC-USD',100,95,120,'0.1',(later+timedelta(hours=1)).isoformat(),later)
        self.g.decide('q',True,later)
        with self.assertRaisesRegex(GateError,'realized loss'):
            self.g.simulate_entry('q',100,later.isoformat(),later,quote_utc=later.isoformat())

    def test_missing_stale_future_quote_never_opens(self):
        self.g.propose('p','BTC-USD',100,95,120,'.1',(self.now+timedelta(hours=1)).isoformat(),self.now)
        self.g.decide('p',True,self.now)
        for quote in [None,(self.now-timedelta(seconds=61)).isoformat(),(self.now+timedelta(seconds=1)).isoformat()]:
            with self.subTest(quote=quote),self.assertRaises(GateError):
                self.g.simulate_entry('p',100,self.now.isoformat(),self.now,quote_utc=quote)
        self.assertEqual(self.g.status()['cash_usd'],'100')

    def test_no_trigger_or_invalid_exit_cannot_change_cash(self):
        self.entry();before=self.g.status()
        self.assertEqual(self.g.evaluate_exit('p',105,self.now.isoformat(),self.now)['status'],'Open')
        for value in ['NaN','Infinity',0,-1,'bad']:
            with self.assertRaises(GateError):self.g.evaluate_exit('p',value,self.now.isoformat(),self.now)
        with self.assertRaises(GateError):self.g.evaluate_exit('p',95,(self.now-timedelta(seconds=1)).isoformat(),self.now)
        self.assertEqual(before,self.g.status())

    def test_exit_failure_rolls_back_cash_position_and_journal(self):
        self.entry();before=self.g.status()
        with patch.object(self.g,'_event',side_effect=OSError('disk')):
            with self.assertRaises(OSError):self.g.evaluate_exit('p',95,self.now.isoformat(),self.now)
        self.assertEqual(before,self.g.status())
        self.assertEqual(self.g.db.execute('SELECT count(*) FROM exits').fetchone()[0],0)

    def test_concurrent_exit_credits_once(self):
        self.entry()
        def close_once(_):
            g=PaperGate(self.path)
            try:return g.evaluate_exit('p',120,self.now.isoformat(),self.now)
            finally:g.close()
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(close_once,range(2)))
        self.assertEqual(sum(not r['duplicate'] for r in results),1)
        self.assertEqual(self.g.status()['closed_trades'],1)

    def test_legacy_migration_debits_existing_fill_once(self):
        self.entry()
        self.g.db.execute('DROP TABLE paper_account')
        for _ in range(2):
            other=PaperGate(self.path)
            try:self.assertEqual(Decimal(other.status()['cash_usd']),Decimal('89.89991'))
            finally:other.close()

    def test_persisted_cost_model_cannot_change(self):
        with self.assertRaisesRegex(GateError,'Persisted'):PaperGate(self.path,fee_rate='0')
        for value in ['NaN','-0.1','1','bad']:
            with self.assertRaises(GateError):PaperGate(':memory:',slippage=value)

    def test_database_tampering_is_detected(self):
        self.g.db.execute("UPDATE paper_account SET cash='999'")
        with self.assertRaisesRegex(GateError,'reconciliation'):self.g.status()

    def test_timezone_and_boolean_approval(self):
        with self.assertRaises(GateError):self.g.decide('none','true',self.now)
        with self.assertRaises(GateError):self.g.decide('none',True,self.now.replace(tzinfo=None))
