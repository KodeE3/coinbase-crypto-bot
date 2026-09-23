import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from options_paper.engine import propose
from options_paper.account import Account

SAMPLE = json.loads((Path(__file__).resolve().parents[1] / 'options_paper/sample_snapshot.json').read_text())
NOW = datetime(2026, 9, 22, 20, 0, tzinfo=timezone.utc)


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'account.sqlite3'
        self.account = Account(self.path, demo=True)
        self.proposal = propose(SAMPLE, demo=True)

    def tearDown(self):
        self.account.close()
        self.tmp.cleanup()

    def buy(self, proposal=None):
        p = proposal or self.proposal
        return self.account.buy(p, p['contract'], now=NOW)

    def test_round_trip_persistence_and_fees(self):
        self.assertEqual(self.buy()['cash_cents'], 984935)
        self.account.close()
        self.account = Account(self.path, demo=True)
        self.assertEqual(len(self.account.status()['positions']), 1)
        p = self.proposal
        state = self.account.sell(p['contract'], '1.80', SAMPLE['as_of'], p['contract'], now=NOW)
        self.assertEqual(state['cash_cents'], 1002870)
        self.assertEqual(state['realized_pnl_cents'], 2870)
        self.assertEqual(state['positions'], [])
        self.assertEqual(len(self.account.history()), 2)
        with self.assertRaises(ValueError):
            self.account.sell(p['contract'], '1.80', SAMPLE['as_of'], p['contract'])
        with self.assertRaises(ValueError):
            self.buy()

    def test_repeat_entry_different_timestamp_blocked(self):
        self.buy()
        p = dict(self.proposal, id='new-timestamp')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.buy(p)
        self.assertEqual(len(self.account.history()), 1)
        self.assertEqual(self.account.status()['cash_cents'], 984935)

    def test_wrong_confirmation_and_insufficient_cash_do_not_write(self):
        with self.assertRaises(ValueError):
            self.account.buy(self.proposal, 'wrong')
        poor = Account(Path(self.tmp.name)/'poor.sqlite3', demo=True, starting_cash='100')
        try:
            with self.assertRaisesRegex(ValueError, 'Insufficient'):
                poor.buy(self.proposal, self.proposal['contract'])
            self.assertEqual(poor.status()['cash_cents'], 10000)
            self.assertEqual(poor.history(), [])
        finally:
            poor.close()

    def test_risk_limits_and_fee_inclusion(self):
        with self.assertRaisesRegex(ValueError, '2%'):
            self.buy(dict(self.proposal, ask_cents=200))
        for n in range(3):
            self.buy(dict(self.proposal, id=str(n), underlying=str(n), contract=str(n)))
        with self.assertRaisesRegex(ValueError, 'exposure'):
            self.buy(dict(self.proposal, id='four', underlying='four'))

    def test_stale_approval_and_mode_isolation(self):
        real = Account(Path(self.tmp.name)/'snapshot.sqlite3')
        try:
            p = propose(SAMPLE, now=NOW)
            with self.assertRaisesRegex(ValueError, '15 minutes'):
                real.buy(p, p['contract'], now=NOW+timedelta(minutes=16))
            self.assertEqual(real.history(), [])
        finally:
            real.close()
        with self.assertRaisesRegex(ValueError, 'different database'):
            Account(self.path, demo=False)

    def test_invalid_snapshots_and_filters(self):
        for data in [{}, None, dict(SAMPLE, closes=['NaN']), dict(SAMPLE, options=None)]:
            self.assertIn('rejected', propose(data, demo=True))
        data = copy.deepcopy(SAMPLE)
        data['options'][0]['volume'] = 0
        self.assertIn('rejected', propose(data, demo=True))
        self.assertIn('rejected', propose(SAMPLE, now=NOW+timedelta(days=1)))
        self.assertIn('rejected', propose(SAMPLE, now=NOW-timedelta(seconds=1)))

    def test_invalid_close_does_not_change_account(self):
        self.buy()
        for bid, as_of in [('NaN', SAMPLE['as_of']), ('-1', SAMPLE['as_of']),
                           ('1.2', '2026-09-21T20:00:00Z'), ('1.2', '2026-10-23T20:00:00Z')]:
            with self.assertRaises(ValueError):
                self.account.sell(self.proposal['contract'], bid, as_of, self.proposal['contract'])
        self.assertEqual(len(self.account.history()), 1)

    def test_loss_and_daily_stop(self):
        for n in range(2):
            p = dict(self.proposal, id=str(n), underlying=str(n), contract=str(n))
            self.buy(p)
            self.account.sell(p['contract'], '0', SAMPLE['as_of'], p['contract'], now=NOW)
        self.assertEqual(self.account.status()['realized_pnl_cents'], -30260)
        with self.assertRaisesRegex(ValueError, 'Daily'):
            self.buy()

    def test_two_connections_cannot_repeat_position(self):
        other = Account(self.path, demo=True)
        try:
            self.buy()
            with self.assertRaises(ValueError):
                other.buy(self.proposal, self.proposal['contract'])
            self.assertEqual(other.status()['cash_cents'], 984935)
        finally:
            other.close()


if __name__ == '__main__':
    unittest.main()
