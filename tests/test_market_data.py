import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from options_paper.market_data import AlpacaData, NoRedirect
from options_paper.account import Account
from options_paper.engine import propose
from options_paper.cli import main

NOW = datetime(2026,9,23,18,tzinfo=timezone.utc)
CONTRACT = 'SPY261023C00110000'


def response(data):
    return io.BytesIO(json.dumps(data).encode())


class DataTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'APCA_API_KEY_ID':'test-key', 'APCA_API_SECRET_KEY':'test-secret'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def client(self, data):
        return AlpacaData(transport=lambda req, timeout: response(data), clock=lambda: NOW)

    def quote(self, time=NOW):
        return {'quotes': {CONTRACT: {'bp':1.80, 'ap':1.90, 't':time.isoformat()}}}

    def test_normalizes_quotes_and_fixed_get(self):
        def transport(req, timeout):
            url=urlsplit(req.full_url)
            self.assertEqual(url.netloc,'data.alpaca.markets')
            self.assertEqual(url.path,'/v1beta1/options/quotes/latest')
            self.assertEqual(parse_qs(url.query)['feed'], ['opra'])
            self.assertEqual(req.get_method(),'GET')
            self.assertEqual(timeout,10)
            self.assertEqual(req.get_header('Apca-api-secret-key'),'test-secret')
            return response(self.quote())
        result=AlpacaData(transport=transport,clock=lambda:NOW).option_quotes([CONTRACT])
        self.assertEqual(result['quotes'][0]['bid'],'1.8')
        self.assertEqual(result['feed'],'opra')
        self.assertEqual(result['quotes'][0]['as_of'], NOW.isoformat())

    def test_missing_stale_future_and_invalid_quotes(self):
        data=self.quote()
        data['quotes'][CONTRACT]['bp']=2
        for raw in [{'quotes':{}}, self.quote(NOW-timedelta(minutes=16)), self.quote(NOW+timedelta(seconds=1)), data]:
            with self.assertRaises(ValueError):
                self.client(raw).option_quotes([CONTRACT])
        with self.assertRaises(ValueError):
            self.client({}).option_quotes(['DEMO-SPY'])

    def test_nanosecond_provider_timestamp(self):
        raw = self.quote()
        raw['quotes'][CONTRACT]['t'] = '2026-09-23T17:59:59.123456789Z'
        quote = self.client(raw).option_quotes([CONTRACT])['quotes'][0]
        self.assertEqual(quote['as_of'], '2026-09-23T17:59:59.123456+00:00')

    def test_redacted_errors_and_credentials(self):
        for code in [401,403,429,500,302]:
            def transport(req,timeout):
                raise HTTPError(req.full_url,code,'test-secret',{},None)
            with self.assertRaises(ValueError) as error:
                AlpacaData(transport=transport).option_quotes([CONTRACT])
            self.assertNotIn('test-secret',str(error.exception))
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError,'APCA_API_KEY_ID'):
                AlpacaData()
        def offline(req,timeout):
            raise URLError('test-secret')
        with self.assertRaisesRegex(ValueError, 'timed out'):
            AlpacaData(transport=offline).option_quotes([CONTRACT])
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'https://example.com'))

    def test_daily_bar_pagination_and_completed_days(self):
        calls=[]
        def transport(req,timeout):
            query=parse_qs(urlsplit(req.full_url).query)
            calls.append(query)
            end=datetime.fromisoformat(query['end'][0])
            self.assertEqual(end.date().isoformat(),'2026-09-22')
            start=0 if len(calls)==1 else 6
            bars=[{'t':(NOW-timedelta(days=n+1)).isoformat(),'c':100+n} for n in range(start,start+6)]
            return response({'bars':{'SPY':bars}, 'next_page_token':'page2' if len(calls)==1 else None})
        data=AlpacaData(transport=transport,clock=lambda:NOW).daily_bars()
        self.assertEqual(len(data['closes']),12)
        self.assertEqual(calls[1]['page_token'],['page2'])
        self.assertEqual(data['bars'][-1]['as_of'],(NOW-timedelta(days=1)).isoformat())
        bars=[{'t':(NOW-timedelta(days=n)).isoformat(),'c':100} for n in range(12)]
        with self.assertRaisesRegex(ValueError,'incomplete'):
            self.client({'bars':{'SPY':bars}}).daily_bars()

    def test_refresh_preview_and_changed_price_reapproval(self):
        now=datetime.now(timezone.utc)
        sample=json.loads((Path(__file__).resolve().parents[1]/'options_paper/sample_snapshot.json').read_text())
        sample['as_of']=(now-timedelta(minutes=1)).isoformat()
        sample['options'][0].update(symbol=CONTRACT,expiry=(now+timedelta(days=30)).date().isoformat())
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'account.sqlite3'
            account=Account(path)
            try:
                proposal=propose(sample,now=now)
                account.buy(proposal,CONTRACT,now=now)
                def batch(bid, seconds):
                    at=(now-timedelta(seconds=seconds)).isoformat()
                    return {'as_of':at,'quotes':[{'contract':CONTRACT,'as_of':at,'bid':bid,'ask':'2.50'}]}
                with patch('options_paper.cli.AlpacaData') as provider, patch('builtins.input',return_value=CONTRACT), contextlib.redirect_stdout(io.StringIO()) as output:
                    provider.return_value.option_quotes.side_effect=[batch('2.30',2),batch('2.40',1)]
                    self.assertEqual(main(['--account',str(path),'--refresh-quotes','--review-exits']),1)
                    self.assertIn('changed during approval',output.getvalue())
                self.assertEqual(len(account.history()),1)
                with patch('options_paper.cli.AlpacaData') as provider, patch('builtins.input',return_value=CONTRACT), contextlib.redirect_stdout(io.StringIO()):
                    provider.return_value.option_quotes.return_value=batch('2.40',1)
                    self.assertEqual(main(['--account',str(path),'--refresh-quotes','--review-exits']),0)
                self.assertEqual(account.status()['realized_pnl_cents'],8870)
            finally:
                account.close()


if __name__=='__main__':
    unittest.main()
