import contextlib
import copy
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from options_paper.account import Account
from options_paper.cli import main as account_main
from options_paper.discovery import main as discovery_main
from options_paper.engine import propose
from options_paper.tradier import TradierData, greek_metadata, quote_time

NOW = datetime(2026, 9, 29, 18, tzinfo=timezone.utc)
CONTRACT = 'SPY261030C00110000'


def option(now=NOW):
    return {'symbol': CONTRACT, 'type': 'option', 'option_type': 'call', 'underlying': 'SPY',
            'root_symbol': 'SPY', 'strike': 110, 'contract_size': 100,
            'expiration_date': '2026-10-30', 'bid': 1.45, 'ask': 1.50,
            'bid_date': int((now - timedelta(seconds=30)).timestamp() * 1000),
            'ask_date': int((now - timedelta(seconds=10)).timestamp() * 1000),
            'volume': 150, 'open_interest': 700,
            'greeks': {'delta': .5, 'updated_at': (now - timedelta(minutes=30)).isoformat()}}


class TradierTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'TRADIER_ACCESS_TOKEN': 'test-token'})
        env.start()
        self.addCleanup(env.stop)
        days = [14, 15, 16, 17, 18, 21, 22, 23, 24, 25, 28]
        self.history = {'history': {'day': [{'date': f'2026-09-{d}', 'close': 100 + n}
                                           for n, d in enumerate(days)]}}
        self.expiries = {'expirations': {'date': ['2026-10-02', '2026-10-30', '2027-01-15']}}
        self.chain = {'options': {'option': [option()]}}
        self.quotes = {'quotes': {'quote': option()}}
        self.calls = []
        self.client = TradierData(transport=self.transport, clock=lambda: NOW)

    def transport(self, request, timeout):
        url = urlsplit(request.full_url)
        query = parse_qs(url.query)
        self.calls.append((url.path, query))
        self.assertEqual(url.scheme, 'https')
        self.assertEqual(url.netloc, 'api.tradier.com')
        self.assertEqual(request.get_method(), 'GET')
        self.assertIsNone(request.data)
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-token')
        self.assertNotIn('test-token', request.full_url)
        self.assertEqual(timeout, 10)
        if url.path == '/v1/markets/history':
            self.assertEqual(query['end'], ['2026-09-28'])
            raw = self.history
        elif url.path == '/v1/markets/options/expirations':
            self.assertEqual(query['includeAllRoots'], ['false'])
            raw = self.expiries
        elif url.path == '/v1/markets/options/chains':
            self.assertEqual(query['greeks'], ['true'])
            self.assertEqual(query['expiration'], ['2026-10-30'])
            raw = self.chain
        elif url.path == '/v1/markets/quotes':
            self.assertEqual(query['greeks'], ['false'])
            raw = self.quotes
        else:
            self.fail('Unexpected endpoint')
        return io.BytesIO(json.dumps(raw).encode())

    def test_discovery_to_saved_snapshot_and_reviewed_paper_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'entry.json'
            with patch('options_paper.tradier.TradierData', return_value=self.client), patch('options_paper.discovery.AlpacaData', side_effect=AssertionError('No Alpaca')), patch('builtins.input', side_effect=AssertionError), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(discovery_main(['--provider', 'tradier', '--output', str(output)]), 0)
            snapshot = json.loads(output.read_text())
            self.assertEqual(snapshot['provenance']['source'], 'tradier')
            self.assertEqual(snapshot['options'][0]['volume_date'], '2026-09-29')
            self.assertIsNone(snapshot['options'][0]['open_interest_date'])
            self.assertEqual(snapshot['as_of'], (NOW - timedelta(seconds=30)).isoformat())
            self.assertEqual([p.name for p in Path(folder).iterdir()], ['entry.json'])
            account = Account(Path(folder)/'account.sqlite3')
            try:
                proposal = propose(snapshot, now=NOW)
                account.buy(proposal, CONTRACT, now=NOW)
                self.assertEqual(account.status()['cash_cents'], 984935)
                with self.assertRaisesRegex(ValueError, 'already been used'):
                    account.buy(proposal, CONTRACT, now=NOW)
            finally:
                account.close()

    def test_quotes_normalize_single_object_and_multiple_objects(self):
        quotes = self.client.option_quotes([CONTRACT])
        self.assertEqual(quotes['quotes'][0]['as_of'], (NOW - timedelta(seconds=30)).isoformat())
        self.assertEqual(quotes['source'], 'tradier')
        self.quotes['quotes']['quote'] = [option()]
        self.assertEqual(len(self.client.option_quotes([CONTRACT])['quotes']), 1)

    def test_seconds_and_milliseconds_are_explicitly_supported(self):
        epoch = int(NOW.timestamp())
        self.assertEqual(quote_time(epoch), NOW)
        self.assertEqual(quote_time(epoch * 1000), NOW)
        for invalid in [None, True, -1, 0, epoch * 1000000, 1.5, 'NaN', 'Infinity']:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                quote_time(invalid)

    def test_both_bid_and_ask_must_be_fresh(self):
        for field in ['bid_date', 'ask_date']:
            for at in [NOW - timedelta(minutes=16), NOW + timedelta(seconds=1)]:
                self.chain = {'options': {'option': [{**option(), field: int(at.timestamp()*1000)}]}}
                self.assertEqual(self.client.entry_snapshot()['options'], [])
                self.quotes = {'quotes': {'quote': self.chain['options']['option']}}
                with self.assertRaises(ValueError):
                    self.client.option_quotes([CONTRACT])

    def test_quotes_aging_during_chain_collection_are_excluded(self):
        with patch.object(self.client, 'clock', side_effect=[NOW, NOW, NOW + timedelta(minutes=16)]):
            snapshot = self.client.entry_snapshot()
        self.assertEqual(snapshot['options'], [])
        self.assertIn('rejected', snapshot['proposal_preview'])

    def test_greek_time_is_not_given_an_invented_timezone(self):
        meta = greek_metadata({'delta': '.5', 'updated_at': '2026-09-29 17:30:00'}, NOW)
        self.assertIsNone(meta['greeks_as_of'])
        self.assertEqual(meta['greeks_updated_at_raw'], '2026-09-29 17:30:00')
        self.assertEqual(meta['greeks_time_basis'], 'provider_timezone_unspecified')
        for at in ['2026-09-28 17:30:00', None, 'secret', '2026-09-29T16:00:00Z', '2026-09-29T19:00:00Z']:
            with self.subTest(at=at), self.assertRaises(ValueError):
                greek_metadata({'delta': '.5', 'updated_at': at}, NOW)

    def test_missing_greeks_or_liquidity_is_not_fabricated(self):
        for change in [{'greeks': None}, {'greeks': {'delta': 'NaN', 'updated_at': NOW.isoformat()}},
                       {'open_interest': None}, {'open_interest': True}, {'volume': 12.5},
                       {'bid': 0}, {'bid': 2}, {'ask': 1.501}]:
            self.chain = {'options': {'option': [{**option(), **change}]}}
            snapshot = self.client.entry_snapshot()
            self.assertEqual(snapshot['options'], [])
            self.assertIn('rejected', snapshot['proposal_preview'])

    def test_contract_identity_and_standard_size_are_cross_checked(self):
        for change in [{'root_symbol': 'SPY1'}, {'underlying': 'QQQ'}, {'type': 'stock'},
                       {'option_type': 'put'}, {'strike': 111}, {'contract_size': 10},
                       {'expiration_date': '2026-10-31'}, {'symbol': 'DEMO-SPY'}]:
            with self.subTest(change=change):
                self.chain = {'options': {'option': [{**option(), **change}]}}
                self.assertEqual(self.client.entry_snapshot()['options'], [])

    def test_duplicate_chain_rows_and_bounds_abort(self):
        self.chain['options']['option'] *= 2
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.client.entry_snapshot()
        self.chain = {'options': {'option': [option()]}}
        for setting in ['MAX_CHAIN_ROWS', 'MAX_CANDIDATES', 'MAX_EXPIRATIONS']:
            with patch('options_paper.tradier.' + setting, 0):
                with self.assertRaisesRegex(ValueError, 'limit'):
                    self.client.entry_snapshot()

    def test_null_and_singleton_collections(self):
        self.expiries['expirations']['date'] = '2026-10-30'
        self.chain['options']['option'] = option()
        self.assertEqual(len(self.client.entry_snapshot()['options']), 1)
        self.chain['options']['option'] = None
        self.assertEqual(self.client.entry_snapshot()['options'], [])
        self.expiries['expirations']['date'] = []
        self.assertEqual(self.client.entry_snapshot()['options'], [])

    def test_history_rejects_partial_stale_duplicate_or_malformed(self):
        original = copy.deepcopy(self.history)
        for change in [{'date': '2026-09-29'}, {'close': -1}, {'close': 'NaN'}, {'date': '2026-07-01'}]:
            self.history = copy.deepcopy(original)
            self.history['history']['day'][-1].update(change)
            with self.assertRaises(ValueError):
                self.client.daily_bars('SPY')
        self.history = copy.deepcopy(original)
        self.history['history']['day'].append(copy.deepcopy(self.history['history']['day'][0]))
        with self.assertRaises(ValueError):
            self.client.daily_bars('SPY')
        self.history = {'history': None}
        with self.assertRaises(ValueError):
            self.client.daily_bars('SPY')

    def test_requested_quote_identity_and_completeness(self):
        for value in [[], None, [option(), option()], {**option(), 'symbol': 'QQQ261030C00110000'}]:
            self.quotes = {'quotes': {'quote': value}}
            with self.assertRaises(ValueError):
                self.client.option_quotes([CONTRACT])
        self.quotes = {'quotes': {'quote': {**option(), 'bid': 0}}}
        self.assertEqual(self.client.option_quotes([CONTRACT])['quotes'][0]['bid'], '0')

    def test_allowlist_no_orders_or_token_in_url(self):
        for path in ['accounts', '../accounts/123/orders', 'https://evil.example', '/quotes']:
            with self.assertRaisesRegex(ValueError, 'allowlisted'):
                self.client._get(path, {})
        for contracts in [[], ['DEMO-SPY'], [CONTRACT, CONTRACT], [None]]:
            with self.assertRaises(ValueError):
                self.client.option_quotes(contracts)
        for symbol in ['', 'spy', 'SPY&token=secret']:
            with self.assertRaises(ValueError):
                self.client.daily_bars(symbol)
        self.assertEqual(self.calls, [])

    def test_auth_rate_redirect_network_and_payload_errors_are_redacted(self):
        for code in [401, 403, 429, 500, 302]:
            def failure(request, timeout):
                raise HTTPError(request.full_url, code, 'sensitive-body', {}, None)
            client = TradierData(transport=failure, clock=lambda: NOW)
            with self.assertRaises(ValueError) as error:
                client.daily_bars('SPY')
            self.assertNotIn('sensitive-body', str(error.exception))
        for failure in [URLError('sensitive-body'), TimeoutError('sensitive-body')]:
            with patch.object(self.client, 'transport', side_effect=failure):
                with self.assertRaisesRegex(ValueError, 'connection failed'):
                    self.client.daily_bars('SPY')
        for raw in [b'not JSON sensitive-body', b'[]', b'{"errors":"sensitive-body"}',
                    b'{"next":"https://evil.example"}', b' ' * 2_000_001]:
            with patch.object(self.client, 'transport', return_value=io.BytesIO(raw)):
                with self.assertRaises(ValueError) as error:
                    self.client.daily_bars('SPY')
                self.assertNotIn('sensitive-body', str(error.exception))

    def test_missing_or_invalid_token_fails_before_network(self):
        for value in ['', 'bad\nsecret', 'bad\x00secret']:
            with patch('options_paper.tradier.os.environ.get', return_value=value), self.assertRaisesRegex(ValueError, 'TRADIER_ACCESS_TOKEN'):
                TradierData()

    def test_discovery_failure_leaves_no_output_and_does_not_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'entry.json'
            with patch('options_paper.tradier.TradierData', side_effect=ValueError('Tradier authentication failed')), patch('options_paper.discovery.AlpacaData', side_effect=AssertionError), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(discovery_main(['--provider', 'tradier', '--output', str(output)]), 1)
            self.assertFalse(output.exists())
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                discovery_main(['--provider', 'tradier', '--stock-feed', 'iex', '--output', str(output)])

    def test_tradier_refresh_keeps_exit_reapproval_and_paper_account_rules(self):
        now = datetime.now(timezone.utc)
        snapshot = self.client.entry_snapshot()
        snapshot['as_of'] = (now - timedelta(minutes=1)).isoformat()
        snapshot['options'][0]['expiry'] = (now + timedelta(days=30)).date().isoformat()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'account.sqlite3'
            account = Account(path)
            try:
                account.buy(propose(snapshot, now=now), CONTRACT, now=now)
                def batch(bid, seconds):
                    at = (now - timedelta(seconds=seconds)).isoformat()
                    return {'as_of': at, 'quotes': [{'contract': CONTRACT, 'as_of': at, 'bid': bid, 'ask': '2.50'}]}
                args = ['--account', str(path), '--provider', 'tradier', '--refresh-quotes', '--review-exits']
                with patch('options_paper.cli.TradierData') as client, patch('options_paper.cli.AlpacaData', side_effect=AssertionError), patch('builtins.input', return_value=CONTRACT), contextlib.redirect_stdout(io.StringIO()):
                    client.return_value.option_quotes.side_effect = [batch('2.30', 2), batch('2.40', 1)]
                    self.assertEqual(account_main(args), 1)
                    self.assertEqual(len(account.history()), 1)
                    client.return_value.option_quotes.side_effect = None
                    client.return_value.option_quotes.return_value = batch('2.40', 1)
                    self.assertEqual(account_main(args), 0)
                self.assertEqual(account.status()['realized_pnl_cents'], 8870)
            finally:
                account.close()

    def test_session_rollover_aborts(self):
        with patch.object(self.client, 'clock', side_effect=[NOW, NOW, NOW + timedelta(days=1)]):
            with self.assertRaisesRegex(ValueError, 'Session changed'):
                self.client.entry_snapshot()


if __name__ == '__main__':
    unittest.main()
