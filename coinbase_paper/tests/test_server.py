from datetime import datetime, timezone
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from gate import PaperGate
from server import dispatch

class TestApi(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.gate = PaperGate(Path(self.tmp.name) / 'db.sqlite')
    def tearDown(self):
        self.gate.db.close()
        self.tmp.cleanup()
    def test_health(self):
        self.assertEqual(dispatch(self.gate, 'GET', '/health', {})[0], 200)
    def test_reject_unknown(self):
        self.assertEqual(dispatch(self.gate, 'POST', '/orders', {})[0], 404)
    def test_approval_requires_boolean(self):
        self.assertEqual(dispatch(self.gate, 'POST', '/proposals/x/decision', {'approve':'true'})[0], 400)
    def test_simulation_requires_approval(self):
        code, obj = dispatch(self.gate, 'POST', '/proposals/x/simulate', {'market_price': '1', 'candle_utc':datetime.now(timezone.utc).isoformat(), 'quote_utc':datetime.now(timezone.utc).isoformat()})
        self.assertEqual(code, 400)
        self.assertIn('Approval', obj['error'])

if __name__ == '__main__': unittest.main()
