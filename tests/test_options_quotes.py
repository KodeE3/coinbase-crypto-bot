import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from options_paper.account import Account
from options_paper.engine import propose
from options_paper.quotes import save_quotes, valuation, approve_exit

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = json.loads((ROOT/'options_paper/sample_snapshot.json').read_text())
NOW = datetime(2026, 9, 23, 20, tzinfo=timezone.utc)


def quotes(contract, bid='1.80', when=NOW):
    return {'as_of': when.isoformat(), 'quotes': [
        {'contract': contract, 'bid': bid, 'ask': str(Decimal(bid)+Decimal('0.10')), 'as_of': when.isoformat()}]}


class QuoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'demo.sqlite3'
        self.account = Account(self.path, demo=True)
        self.p = propose(SAMPLE, demo=True)
        self.account.buy(self.p, self.p['contract'])

    def tearDown(self):
        self.account.close()
        self.tmp.cleanup()

    def save(self, bid='1.80', when=NOW):
        return save_quotes(self.account, quotes(self.p['contract'], bid, when))

    def test_valuation_persists_without_changing_cash(self):
        report = self.save()
        self.assertEqual(report['estimated_equity_cents'], 1002870)
        self.assertEqual(report['unrealized_pnl_cents'], 2870)
        self.assertEqual(report['positions'][0]['reasons'], [])
        self.assertEqual(self.account.status()['cash_cents'], 984935)
        self.assertEqual(len(self.account.history()), 1)
        self.account.close()
        self.account = Account(self.path, demo=True)
        self.assertEqual(valuation(self.account), report)

    def test_stop_target_and_confirmation(self):
        report = self.save('1.00')
        self.assertTrue(report['positions'][0]['reasons'][0].startswith('stop_loss'))
        with self.assertRaises(ValueError):
            approve_exit(self.account, report['positions'][0], 'wrong')
        report = self.save('2.30', NOW+timedelta(minutes=1))
        candidate = report['positions'][0]
        self.assertTrue(candidate['reasons'][0].startswith('profit_target'))
        state = approve_exit(self.account, candidate, self.p['contract'])
        self.assertEqual(state['realized_pnl_cents'], 7870)
        self.assertEqual(state['cash_cents'], 1007870)
        with self.assertRaises(ValueError):
            approve_exit(self.account, candidate, self.p['contract'])

    def test_holding_and_expiration_rules(self):
        report = self.save('1.50', datetime(2026,9,29,20,tzinfo=timezone.utc))
        self.assertTrue(any(x.startswith('holding_time') for x in report['positions'][0]['reasons']))
        report = self.save('1.50', datetime(2026,10,21,20,tzinfo=timezone.utc))
        self.assertTrue(any(x.startswith('expiration') for x in report['positions'][0]['reasons']))
        report = self.save('1.50', datetime(2026,10,23,20,tzinfo=timezone.utc))
        self.assertFalse(report['positions'][0]['usable'])
        self.assertIsNone(report['estimated_equity_cents'])

    def test_missing_partial_and_stale_quotes_hide_total(self):
        self.assertIsNone(valuation(self.account)['estimated_equity_cents'])
        self.save()
        stale = valuation(self.account, NOW+timedelta(minutes=16))
        self.assertIsNone(stale['estimated_equity_cents'])
        self.assertFalse(stale['positions'][0]['usable'])
        second = dict(self.p, id='second', contract='second', underlying='QQQ')
        self.account.buy(second, 'second')
        report = valuation(self.account)
        self.assertIsNone(report['estimated_equity_cents'])
        self.assertEqual(sum(p['usable'] for p in report['positions']), 1)

    def test_bad_batch_rolls_back_all_marks(self):
        batch = quotes(self.p['contract'])
        batch['quotes'].append(dict(batch['quotes'][0], contract='UNKNOWN'))
        with self.assertRaises(ValueError):
            save_quotes(self.account, batch)
        self.assertEqual(self.account.db.execute('SELECT COUNT(*) FROM marks').fetchone()[0], 0)
        for patch in [{'bid': 'NaN'}, {'bid': '-1'}, {'bid': '9.99'}, {'as_of': 'bad'}]:
            batch = quotes(self.p['contract'])
            batch['quotes'][0].update(patch)
            with self.assertRaises(ValueError):
                save_quotes(self.account, batch)
        for batch in [None, {}, {'as_of': NOW.isoformat(), 'quotes': []}]:
            with self.assertRaises(ValueError):
                save_quotes(self.account, batch)

    def test_older_and_conflicting_quotes_rejected(self):
        self.save()
        for bid, when in [('1.90', NOW), ('1.80', NOW-timedelta(minutes=1))]:
            with self.assertRaises(ValueError):
                self.save(bid, when)
        self.assertEqual(self.save()['estimated_equity_cents'], 1002870)

    def test_changed_quote_invalidates_exit_and_manual_backdating(self):
        candidate = self.save('2.30')['positions'][0]
        self.save('2.40', NOW+timedelta(minutes=1))
        with self.assertRaisesRegex(ValueError, 'changed'):
            approve_exit(self.account, candidate, self.p['contract'])
        with self.assertRaisesRegex(ValueError, 'older'):
            self.account.sell(self.p['contract'], '2.30', NOW.isoformat(), self.p['contract'])
        self.assertEqual(len(self.account.history()), 1)

    def test_snapshot_freshness_rechecked_at_exit(self):
        acc = Account(Path(self.tmp.name)/'snapshot.sqlite3')
        try:
            p = propose(SAMPLE, now=datetime(2026,9,22,20,tzinfo=timezone.utc))
            acc.buy(p, p['contract'], now=datetime(2026,9,22,20,tzinfo=timezone.utc))
            data = quotes(p['contract'], '2.30')
            for clock in [NOW-timedelta(seconds=1), NOW+timedelta(minutes=16)]:
                with self.assertRaises(ValueError):
                    save_quotes(acc, data, now=clock)
            candidate = save_quotes(acc, data, now=NOW)['positions'][0]
            with self.assertRaises(ValueError):
                approve_exit(acc, candidate, p['contract'], now=NOW+timedelta(minutes=16))
            self.assertEqual(len(acc.history()), 1)
        finally:
            acc.close()

    def test_atomic_expected_quote_guard(self):
        candidate = self.save('2.30')['positions'][0]
        self.save('2.40', NOW+timedelta(minutes=1))
        with self.assertRaisesRegex(ValueError, 'Quote changed'):
            self.account.sell(self.p['contract'], '2.30', candidate['quote_as_of'], self.p['contract'],
                              expected_position_id=self.p['id'],
                              expected_quote=(candidate['quote_as_of'], candidate['bid_cents']))

    def test_cli_preview_skip_then_approve(self):
        def run(*args, answer=''):
            result = subprocess.run([sys.executable, '-m', 'options_paper.cli', '--demo', '--account', str(self.path), *args],
                                    cwd=ROOT, text=True, input=answer, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            return result.stdout
        file = str(ROOT/'options_paper/sample_exit_quotes.json')
        self.assertIn('EXIT SUGGESTION: profit_target', run('--quotes', file))
        self.assertEqual(len(self.account.history()), 1)
        self.assertIn('Skipped', run('--quotes', file, '--review-exits', answer='\n'))
        self.assertEqual(len(self.account.history()), 1)
        self.assertIn('$10,078.70', run('--quotes', file, '--review-exits', answer=self.p['contract']+'\n'))
        self.assertEqual(self.account.status()['positions'], [])


if __name__ == '__main__':
    unittest.main()
