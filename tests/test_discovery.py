"""Offline provider-contract tests and a discovery -> reviewed paper entry flow."""
import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from options_paper.account import Account
from options_paper.discovery import discover, main, pages, save_snapshot
from options_paper.engine import propose
from options_paper.market_data import AlpacaData

NOW = datetime(2026, 9, 29, 18, tzinfo=timezone.utc)
CONTRACT = 'SPY261030C00110000'


def metadata():
    return {'symbol': CONTRACT, 'underlying_symbol': 'SPY', 'root_symbol': 'SPY',
            'expiration_date': '2026-10-30', 'type': 'call', 'status': 'active',
            'tradable': True, 'strike_price': '110', 'size': '100',
            'open_interest': '700', 'open_interest_date': '2026-09-28'}


def option():
    return {'latestQuote': {'t': (NOW - timedelta(seconds=30)).isoformat(),
                            'bp': 1.45, 'ap': 1.50}, 'greeks': {'delta': 0.50}}


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'APCA_API_KEY_ID': 'fake-key', 'APCA_API_SECRET_KEY': 'fake-secret'})
        env.start()
        self.addCleanup(env.stop)
        self.calls = []
        self.contracts = [metadata()]
        self.snapshots = {CONTRACT: option()}
        self.bars = {CONTRACT: [{'t': '2026-09-28T04:00:00Z', 'v': 150}]}
        self.client = AlpacaData(transport=self.transport, clock=lambda: NOW)

    def transport(self, request, timeout):
        url = urlsplit(request.full_url)
        query = parse_qs(url.query)
        self.calls.append((url.netloc, url.path, query))
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(timeout, 10)
        self.assertIsNone(request.data)
        if url.path == '/v2/stocks/bars':
            self.assertEqual(url.netloc, 'data.alpaca.markets')
            # Eleven completed weekdays ending Monday September 28.
            dates = ['2026-09-14', '2026-09-15', '2026-09-16', '2026-09-17',
                     '2026-09-18', '2026-09-21', '2026-09-22', '2026-09-23',
                     '2026-09-24', '2026-09-25', '2026-09-28']
            raw = {'bars': {'SPY': [{'t': day + 'T04:00:00Z', 'c': 100 + n}
                                  for n, day in enumerate(dates)]}}
        elif url.path == '/v2/options/contracts':
            self.assertEqual(url.netloc, 'paper-api.alpaca.markets')
            self.assertEqual(query['expiration_date_gte'], ['2026-10-20'])
            self.assertEqual(query['expiration_date_lte'], ['2026-11-13'])
            self.assertEqual(query['strike_price_gte'], ['88.00'])
            raw = {'option_contracts': self.contracts}
        elif url.path == '/v1beta1/options/snapshots':
            self.assertEqual(url.netloc, 'data.alpaca.markets')
            self.assertEqual(query['feed'], ['opra'])
            requested = query['symbols'][0].split(',')
            raw = {'snapshots': {k: v for k, v in self.snapshots.items() if k in requested}}
        elif url.path == '/v1beta1/options/bars':
            self.assertEqual(url.netloc, 'data.alpaca.markets')
            self.assertEqual(query['start'], ['2026-09-28T00:00:00-04:00'])
            self.assertEqual(query['end'], ['2026-09-28T23:59:59.999999-04:00'])
            self.assertEqual(query['timeframe'], ['1Day'])
            requested = query['symbols'][0].split(',')
            raw = {'bars': {k: v for k, v in self.bars.items() if k in requested}}
        else:
            self.fail('Unexpected endpoint: ' + url.path)
        return io.BytesIO(json.dumps(raw).encode())

    def test_discovery_snapshot_persistence_and_paper_buy(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'entry.json'
            with patch('builtins.input', side_effect=AssertionError('Discovery must not prompt')):
                snapshot = discover(self.client)
                save_snapshot(path, snapshot)
            self.assertEqual(len(list(Path(folder).iterdir())), 1)
            saved = json.loads(path.read_text())
            self.assertEqual(saved['as_of'], option()['latestQuote']['t'])
            self.assertEqual(saved['options'][0]['volume'], 150)
            self.assertEqual(saved['options'][0]['open_interest'], 700)
            self.assertIsNone(saved['provenance']['greeks_timestamp'])
            proposal = propose(saved, now=NOW)
            self.assertEqual(proposal['contract'], CONTRACT)
            account = Account(Path(folder) / 'paper.sqlite3')
            try:
                account.buy(proposal, CONTRACT, now=NOW)
                self.assertEqual(account.status()['cash_cents'], 984935)
                with self.assertRaisesRegex(ValueError, 'already been used'):
                    account.buy(proposal, CONTRACT, now=NOW)
            finally:
                account.close()
            self.assertEqual(len(self.calls), 4)

    def test_missing_metadata_and_nonstandard_contracts_are_excluded(self):
        variants = [('type', 'put'), ('status', 'inactive'), ('tradable', False),
                    ('tradable', 'true'), ('size', '10'), ('size', '100.1'),
                    ('underlying_symbol', 'QQQ'), ('root_symbol', 'SPY1'),
                    ('strike_price', '111'), ('expiration_date', '2026-10-29'),
                    ('open_interest', None), ('open_interest', 'NaN'),
                    ('open_interest', '12.5'), ('open_interest_date', '2026-09-25'),
                    ('open_interest_date', '2026-09-30')]
        for field, value in variants:
            with self.subTest(field=field, value=value):
                self.contracts = [{**metadata(), field: value}]
                result = discover(self.client)
                self.assertEqual(result['options'], [])
                self.assertIn('rejected', result['proposal_preview'])
                self.assertEqual(result['diagnostics']['excluded']['metadata_missing_stale_or_ineligible'], 1)

    def test_invalid_quote_and_greeks_are_excluded(self):
        for field, value in [('t', (NOW - timedelta(minutes=16)).isoformat()),
                             ('t', (NOW + timedelta(seconds=1)).isoformat()),
                             ('bp', 2), ('bp', 0), ('ap', 1.501), ('bp', -1)]:
            with self.subTest(field=field, value=value):
                self.snapshots = {CONTRACT: option()}
                self.snapshots[CONTRACT]['latestQuote'][field] = value
                self.assertEqual(discover(self.client)['options'], [])
        for value in [None, {}, {'delta': 'NaN'}, {'delta': -0.5}, {'delta': 1.5}]:
            self.snapshots = {CONTRACT: {**option(), 'greeks': value}}
            self.assertEqual(discover(self.client)['options'], [])
        self.snapshots = {}
        self.assertEqual(discover(self.client)['options'], [])

    def test_missing_volume_is_not_synthesized(self):
        self.bars = {}
        result = discover(self.client)
        self.assertEqual(result['options'], [])
        self.assertIn('rejected', result['proposal_preview'])

    def test_bad_volume_date_integer_and_duplicates_abort(self):
        for bars in [[{'t': '2026-09-29T04:00:00Z', 'v': 150}],
                     [{'t': '2026-09-28T04:00:00Z', 'v': -1}],
                     [{'t': '2026-09-28T04:00:00Z', 'v': 100.5}],
                     [{'t': '2026-09-28T04:00:00Z', 'v': True}],
                     [{'t': '2026-09-28T04:00:00Z', 'v': 150}] * 2]:
            with self.subTest(bars=bars):
                self.bars = {CONTRACT: bars}
                with self.assertRaises(ValueError):
                    discover(self.client)

    def test_low_liquidity_and_delta_keep_existing_strategy_rejection(self):
        for field, value in [('volume', 99), ('open_interest', '499'), ('delta', 0.7)]:
            self.contracts, self.bars, self.snapshots = [metadata()], {CONTRACT: [{'t': '2026-09-28T04:00:00Z', 'v': 150}]}, {CONTRACT: option()}
            if field == 'volume':
                self.bars[CONTRACT][0]['v'] = value
            elif field == 'delta':
                self.snapshots[CONTRACT]['greeks']['delta'] = value
            else:
                self.contracts[0][field] = value
            result = discover(self.client)
            self.assertEqual(len(result['options']), 1)
            self.assertIn('rejected', result['proposal_preview'])

    def test_quotes_expiring_during_collection_are_removed(self):
        with patch.object(self.client, 'clock', side_effect=[NOW, NOW, NOW, NOW + timedelta(minutes=16)]):
            result = discover(self.client)
        self.assertEqual(result['options'], [])
        self.assertEqual(result['diagnostics']['excluded'], {'quote_expired_during_collection': 1})

    def test_snapshot_uses_oldest_quote_and_expires_at_paper_confirmation(self):
        second = 'SPY261030C00111000'
        self.contracts.append({**metadata(), 'symbol': second, 'strike_price': '111'})
        self.snapshots[second] = option()
        self.snapshots[second]['latestQuote']['t'] = (NOW - timedelta(minutes=14)).isoformat()
        self.bars[second] = self.bars[CONTRACT]
        result = discover(self.client)
        self.assertEqual(result['as_of'], self.snapshots[second]['latestQuote']['t'])
        proposal = propose(result, now=NOW)
        with tempfile.TemporaryDirectory() as folder:
            account = Account(Path(folder) / 'paper.sqlite3')
            try:
                with self.assertRaisesRegex(ValueError, '15 minutes'):
                    account.buy(proposal, proposal['contract'], now=NOW + timedelta(minutes=2))
                self.assertEqual(account.history(), [])
                self.assertEqual(account.status()['cash_cents'], 1000000)
            finally:
                account.close()

    def test_snapshot_and_volume_pagination_and_duplicate_detection(self):
        real_get = self.client._get
        counts = {}
        def get(path, params):
            counts[path] = counts.get(path, 0) + 1
            if path.endswith('/snapshots') or path == '/v1beta1/options/bars':
                field = 'snapshots' if path.endswith('/snapshots') else 'bars'
                if counts[path] == 1:
                    return {field: {}, 'next_page_token': 'next'}
                self.assertEqual(params['page_token'], 'next')
            return real_get(path, params)
        with patch.object(self.client, '_get', side_effect=get):
            self.assertEqual(len(discover(self.client)['options']), 1)
        with patch('options_paper.discovery.pages', return_value=iter([
                {CONTRACT: option()}, {CONTRACT: option()}])):
            from options_paper.discovery import snapshots
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                snapshots(self.client, [CONTRACT])

    def test_session_rollover_aborts_without_snapshot(self):
        with patch.object(self.client, 'clock', side_effect=[NOW, NOW, NOW, NOW + timedelta(days=1)]):
            with self.assertRaisesRegex(ValueError, 'Session date changed'):
                discover(self.client)

    def test_discovered_expensive_contract_does_not_relax_account_limit(self):
        self.snapshots[CONTRACT]['latestQuote'].update(bp=2.95, ap=3.00)
        proposal = discover(self.client)['proposal_preview']
        with tempfile.TemporaryDirectory() as folder:
            account = Account(Path(folder) / 'paper.sqlite3')
            try:
                with self.assertRaisesRegex(ValueError, 'Entry exceeds'):
                    account.buy(proposal, CONTRACT, now=NOW)
                self.assertEqual(account.history(), [])
            finally:
                account.close()

    def test_contract_duplicates_and_collection_bounds_abort(self):
        self.contracts *= 2
        with self.assertRaisesRegex(ValueError, 'Duplicate contract'):
            discover(self.client)
        self.contracts = [metadata()]
        with patch('options_paper.discovery.MAX_CONTRACTS', 0):
            with self.assertRaisesRegex(ValueError, 'contract limit'):
                discover(self.client)

    def test_sorted_batching_over_100_contracts(self):
        self.contracts, self.snapshots, self.bars = [], {}, {}
        for n in range(101):
            strike = 100 + n / 10
            symbol = f'SPY261030C{int(round(strike * 1000)):08d}'
            self.contracts.append({**metadata(), 'symbol': symbol, 'strike_price': str(strike)})
            self.snapshots[symbol] = option()
            self.bars[symbol] = [{'t': '2026-09-28T04:00:00Z', 'v': 150}]
        self.contracts.reverse()
        result = discover(self.client)
        self.assertEqual(len(result['options']), 101)
        batches = [q['symbols'][0].split(',') for _, p, q in self.calls if p.endswith('/snapshots')]
        self.assertEqual([len(b) for b in batches], [100, 1])
        self.assertEqual([x['symbol'] for x in result['options']], sorted(self.snapshots))

    def test_metadata_pagination_uses_all_pages(self):
        real_get = self.client._get
        calls = []
        def get(path, params):
            if path != '/v2/options/contracts':
                return real_get(path, params)
            calls.append(dict(params))
            return ({'option_contracts': [], 'next_page_token': 'next'} if len(calls) == 1
                    else {'option_contracts': [metadata()], 'next_page_token': None})
        with patch.object(self.client, '_get', side_effect=get):
            self.assertEqual(len(discover(self.client)['options']), 1)
        self.assertEqual(calls[1]['page_token'], 'next')

    def test_pagination_cycle_malformed_and_limit_abort(self):
        for raw in [{'snapshots': {}, 'next_page_token': 'cycle'},
                    {'snapshots': {}, 'next_page_token': 123}, {'snapshots': []}]:
            with self.subTest(raw=raw), patch.object(self.client, '_get', return_value=raw):
                with self.assertRaises(ValueError):
                    list(pages(self.client, '/v1beta1/options/snapshots', {}, 'snapshots', dict))
        values = [{'snapshots': {}, 'next_page_token': str(n)} for n in range(10)]
        with patch.object(self.client, '_get', side_effect=values):
            with self.assertRaisesRegex(ValueError, 'page limit'):
                list(pages(self.client, '/v1beta1/options/snapshots', {}, 'snapshots', dict))

    def test_read_only_allowlist_and_no_network_for_invalid_ticker(self):
        for path in ['/v2/orders', '/v2/account', 'https://evil.example', '/v2/options/contracts/../orders']:
            with self.assertRaisesRegex(ValueError, 'allowlisted'):
                self.client._get(path, {})
        for symbol in ['SPY/../orders', 'spy', '', None]:
            with self.assertRaises(ValueError):
                discover(self.client, symbol)
        self.assertEqual(self.calls, [])

    def test_cli_auth_entitlement_and_rate_errors_leave_no_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            for code in [401, 403, 429, 500, 302]:
                def failure(request, timeout):
                    raise HTTPError(request.full_url, code, 'fake-secret', {}, None)
                client = AlpacaData(transport=failure, clock=lambda: NOW)
                with patch('options_paper.discovery.AlpacaData', return_value=client), contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(['--output', str(Path(folder) / 'entry.json')]), 1)
                self.assertNotIn('fake-secret', output.getvalue())
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_cli_success_no_prompts_no_accounts_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'entry.json'
            with patch('options_paper.discovery.AlpacaData', return_value=self.client), patch('builtins.input', side_effect=AssertionError), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--output', str(path)]), 0)
                before = path.read_bytes()
                self.assertEqual(main(['--output', str(path)]), 1)
                self.assertEqual(path.read_bytes(), before)
            self.assertEqual([p.name for p in Path(folder).iterdir()], ['entry.json'])
            with self.assertRaises(FileExistsError):
                save_snapshot(path, {'overwrite': True})
            self.assertEqual(path.read_bytes(), before)

    def test_atomic_save_failure_leaves_no_partial_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'entry.json'
            with patch('options_paper.discovery.os.link', side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    save_snapshot(path, {'test': True})
            self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
