import unittest
from notion_sync import plan_fill_sync, notion_approval_is_execution_authority

F = dict(unique_fill_key='Coinbase|p|BTC-USD|t1', pair='BTC-USD', side='BUY', quantity='0.1', price='100', fee='0.9', fee_currency='USD', trade_time='2026-10-26T00:00:00Z')

class SyncTests(unittest.TestCase):
    def test_new(self):
        result=plan_fill_sync([F],[])
        self.assertEqual(len(result['creates']),1)
    def test_existing(self):
        result=plan_fill_sync([F],[dict(F)])
        self.assertEqual(result['unchanged'],1)
    def test_conflict(self):
        result=plan_fill_sync([F],[dict(F, price='101')])
        self.assertEqual(len(result['conflicts']),1)
    def test_duplicate_notion(self):
        result=plan_fill_sync([F],[dict(F),dict(F)])
        self.assertEqual(len(result['conflicts']),1)
    def test_duplicate_input(self):
        result=plan_fill_sync([F,F],[])
        self.assertEqual(len(result['conflicts']),1)
    def test_invalid(self):
        result=plan_fill_sync([dict(F, fee='NaN')],[])
        self.assertEqual(len(result['creates']),0)
    def test_no_approval_authority(self):
        for status in ('Approved','Pending','Open'):
            self.assertFalse(notion_approval_is_execution_authority(status))

if __name__ == '__main__': unittest.main()
