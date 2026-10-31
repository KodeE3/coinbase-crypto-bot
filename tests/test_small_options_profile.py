import json
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from options_paper.account import Account
from options_paper.engine import propose


class SmallProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'small.sqlite'
        self.a=Account(self.path,demo=True,profile='small');self.addCleanup(self.a.close)
        self.now=datetime(2026,10,1,15,tzinfo=timezone.utc)

    def proposal(self,ask=18,underlying='SPY',offset=0):
        observed=self.now+timedelta(minutes=offset)
        return {'id':str(ask)+underlying+str(offset),'contract':'DEMO-'+underlying,'demo':True,
                'quantity':1,'action':'buy_to_open','ask_cents':ask,'underlying':underlying,
                'expiry':'2026-11-01','snapshot_as_of':observed.isoformat()}

    def test_small_profile_persists_and_uses_fictional_200(self):
        self.assertEqual(self.a.status()['initial_cash_cents'],20000)
        reopened=Account(self.path,demo=True)
        try:self.assertEqual(reopened.profile,'small')
        finally:reopened.close()
        with self.assertRaisesRegex(ValueError,'cannot change'):Account(self.path,demo=True,profile='tutorial')

    def test_entire_premium_and_both_fees_fit_20(self):
        for ask in [19,20,100]:
            p=self.proposal(ask)
            with self.assertRaisesRegex(ValueError,'risk limit'):self.a.buy(p,p['contract'],self.now)
        p=self.proposal(18);s=self.a.buy(p,p['contract'],self.now)
        self.assertEqual(s['cash_cents'],18135)
        self.assertEqual(s['positions'][0]['cost'],1865)
        s=self.a.sell(p['contract'],'0',self.now.isoformat(),p['contract'],self.now)
        self.assertEqual(s['realized_pnl_cents'],-1930)

    def test_single_open_position_and_daily_loss_budget(self):
        p=self.proposal();self.a.buy(p,p['contract'],self.now)
        q=self.proposal(1,'QQQ')
        with self.assertRaisesRegex(ValueError,'exposure'):self.a.buy(q,q['contract'],self.now)
        self.a.sell(p['contract'],'0',self.now.isoformat(),p['contract'],self.now)
        with self.assertRaisesRegex(ValueError,'Daily loss'):self.a.buy(q,q['contract'],self.now)

    def test_expired_positions_block_unrelated_entries(self):
        p=self.proposal();self.a.buy(p,p['contract'],self.now)
        # Inspect expiry guard using tutorial exposure constraints in a separate account.
        other=Account(Path(self.tmp.name)/'tutorial',demo=True)
        try:
            other.buy(p,p['contract'],self.now)
            q=self.proposal(1,'QQQ');q['snapshot_as_of']='2026-11-02T15:00:00+00:00';q['expiry']='2026-12-01'
            with self.assertRaisesRegex(ValueError,'reconciliation'):other.buy(q,q['contract'],self.now+timedelta(days=32))
        finally:other.close()

    def test_legacy_account_is_not_silently_reprofiled(self):
        path=Path(self.tmp.name)/'legacy'
        old=Account(path,demo=True);old.db.execute('DROP TABLE risk_profile');old.close()
        with self.assertRaisesRegex(ValueError,'cannot change'):Account(path,demo=True,profile='small')
        old=Account(path,demo=True)
        try:self.assertEqual(old.status()['initial_cash_cents'],1000000)
        finally:old.close()
