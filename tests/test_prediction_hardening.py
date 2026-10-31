import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch
from prediction_paper.providers import PublicData,DataError,COINBASE,KALSHI
from prediction_paper.model import number,rules_hash
from prediction_paper.cli import demo_events
from prediction_paper.strategy import candidate
from prediction_paper.account import Account

class Response(BytesIO):
    status=200
    headers={}

class HardeningTests(unittest.TestCase):
    def test_duplicate_or_nonfinite_json_rejected(self):
        for body in [b'{"markets":[],"markets":[]}',b'{"markets":NaN}']:
            with patch('urllib.request.OpenerDirector.open',return_value=Response(body)):
                with self.assertRaises(DataError):PublicData().markets('BTC')

    def test_endpoint_allowlist_blocks_account_or_order_paths(self):
        for base,path in [(KALSHI,'/portfolio/orders'),(COINBASE,'/accounts'),(KALSHI,'/markets/../../orders')]:
            with self.assertRaises(DataError):PublicData()._get(base,path)

    def test_duplicate_market_pages_rejected(self):
        pages=[{'markets':[{'ticker':'A'}],'cursor':'b'},{'markets':[{'ticker':'A'}]}]
        with patch.object(PublicData,'_get',side_effect=pages):
            with self.assertRaisesRegex(DataError,'duplicate'):PublicData().markets('BTC')

    def test_boolean_not_numeric_and_event_binding(self):
        with self.assertRaises(ValueError):number(True)
        self.assertNotEqual(rules_hash({'event_ticker':'A'}),rules_hash({'event_ticker':'B'}))

    def test_past_close_or_nonfinite_settlement_cannot_change_cash(self):
        cfg,events=demo_events();event=events[0]
        trade,_=candidate(event['snapshot'],cfg,event['at'])
        a=Account(':memory:')
        try:
            with self.assertRaisesRegex(ValueError,'already closed'):a.enter(trade,cfg,trade['closes'])
            a.enter(trade,cfg,event['at'])
            before=a.report()
            with self.assertRaises(ValueError):a.settle(events[2]['market'],float('nan'))
            self.assertEqual(a.report(),before)
            a.db.execute('UPDATE balance SET cash=cash+1')
            with self.assertRaisesRegex(ValueError,'reconciliation'):a.report()
        finally:a.close()
