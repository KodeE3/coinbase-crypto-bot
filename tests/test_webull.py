import contextlib
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
from options_paper.engine import propose
from options_paper.webull import (WebullData, CONTRACTS_PATH, SNAPSHOTS_PATH,
                                  epoch_milliseconds, main, signature)

NOW = datetime(2026, 9, 30, 18, tzinfo=timezone.utc)
CONTRACT = 'SPY261030C00110000'
ROOT = Path(__file__).resolve().parents[1]


def metadata(contract=CONTRACT, instrument='123'):
    root = contract[:-15]
    right = 'CALL' if contract[-9] == 'C' else 'PUT'
    return {'symbol': contract, 'instrument_id': instrument, 'status': 'LISTING',
            'tradable_status': 'OC', 'expiration_date': '2026-10-30',
            'root_symbol': root, 'underlying_symbol': root, 'underlying_instrument_id': '456',
            'underlying_type': 'ETF_' + right + '_OPTION', 'option_type': right,
            'style': 'AMERICAN', 'strike_price': str(int(contract[-8:])/1000),
            'multiplier': '100', 'settlement_method': 'PHYSICAL', 'currency': 'USD',
            'def_type': 'STANDARD', 'deliverables': [
                {'asset_type': 'EQUITY', 'symbol': root, 'instrument_id': '456', 'amount': '100',
                 'allocation_percentage': '100', 'settlement_method': 'PHYSICAL',
                 'settlement_status': 'REGULAR'}]}


def snapshot(contract=CONTRACT, instrument='123', now=NOW, bid='1.45', ask='1.50'):
    return {'symbol': contract, 'instrument_id': instrument, 'strike_price': str(int(contract[-8:])/1000),
            'bid': bid, 'ask': ask, 'quote_time': int((now-timedelta(seconds=10)).timestamp()*1000),
            # Last trade is deliberately stale: quote_time is the documented quote clock.
            'last_trade_time': int((now-timedelta(days=1)).timestamp()*1000)}


class WebullTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'WEBULL_APP_KEY': 'test-key', 'WEBULL_APP_SECRET': 'test-secret',
                                     'WEBULL_ACCESS_TOKEN': 'test-token'})
        env.start()
        self.addCleanup(env.stop)
        self.contracts = {'data': [metadata()]}
        self.snapshots = [snapshot()]
        self.calls = []
        self.client = WebullData(transport=self.transport, clock=lambda: NOW)

    def transport(self, request, timeout):
        url = urlsplit(request.full_url)
        params = parse_qs(url.query)
        self.calls.append((url.path, params))
        self.assertEqual(url.scheme, 'https')
        self.assertEqual(url.netloc, 'api.webull.com')
        self.assertEqual(request.get_method(), 'GET')
        self.assertIsNone(request.data)
        self.assertEqual(timeout, 10)
        headers = {k.lower(): v for k, v in request.header_items()}
        self.assertEqual(headers['x-version'], 'v3')
        self.assertEqual(headers['x-access-token'], 'test-token')
        self.assertNotIn('test-secret', str(headers))
        self.assertNotIn('test-', request.full_url)
        self.assertEqual(params['category'], ['US_OPTION'])
        if url.path == CONTRACTS_PATH:
            self.assertEqual(params['show_deliverables'], ['true'])
            payload = self.contracts
        elif url.path == SNAPSHOTS_PATH:
            self.assertLessEqual(len(params['symbols'][0].split(',')), 20)
            payload = self.snapshots
        else:
            self.fail('Unexpected endpoint')
        return io.BytesIO(json.dumps(payload).encode())

    def test_signature_matches_official_known_answer(self):
        # Public example credentials from the signature documentation, not user secrets.
        headers = {'x-app-key': '776da210ab4a452795d74e726ebd74b6',
                   'x-timestamp': '2022-01-04T03:55:31Z', 'x-signature-version': '1.0',
                   'x-signature-algorithm': 'HMAC-SHA1',
                   'x-signature-nonce': '48ef5afed43d4d91ae514aaeafbc29ba', 'host': 'api.webull.com'}
        result = signature('/trade/place_order', {'a1': 'webull', 'a2': '123', 'a3': 'xxx', 'q1': 'yyy'},
                           headers, '0f50a2e853334a9aae1a783bee120c1f',
                           '{"k1":123,"k2":"this is the api request body","k3":true,"k4":{"foo":[1,2]}}')
        self.assertEqual(result, 'kvlS6opdZDhEBo5jq40nHYXaLvM=')

    def test_quote_identity_time_and_provenance(self):
        result = self.client.option_quotes([CONTRACT])
        self.assertEqual(result['source'], 'webull')
        self.assertEqual(result['environment'], 'production')
        self.assertEqual(result['quote_time_basis'], 'provider_snapshot_generation')
        self.assertEqual(result['quotes'][0]['as_of'], (NOW-timedelta(seconds=10)).isoformat())
        self.assertIsNone(result['quotes'][0]['bid_as_of'])
        self.assertEqual(result['quotes'][0]['multiplier'], 100)
        self.assertEqual([x[0] for x in self.calls], [CONTRACTS_PATH, SNAPSHOTS_PATH])

    def test_invalid_requests_do_not_reach_network(self):
        for contracts in [[], None, 'SPY', [None], [CONTRACT, CONTRACT], ['DEMO-SPY'],
                          ['SPY260930C00110000'], ['SPY260231C00110000'],
                          ['SPY261030C00000000'], ['SPY1261030C00110000'], [CONTRACT]*101]:
            with self.subTest(contracts=contracts), self.assertRaises(ValueError):
                self.client.option_quotes(contracts)
        self.assertEqual(self.calls, [])

    def test_contract_validation_rejects_identity_and_nonstandard_deliverables(self):
        patches = [{'root_symbol': 'SPY1'}, {'underlying_symbol': 'QQQ'}, {'expiration_date': '2026-10-31'},
                   {'option_type': 'PUT'}, {'strike_price': '111'}, {'multiplier': '10'},
                   {'currency': 'EUR'}, {'def_type': 'FLEX'}, {'status': 'DELISTING'},
                   {'tradable_status': 'NT'}, {'underlying_type': 'INDEX_CALL_OPTION'},
                   {'style': 'EUROPEAN'}, {'settlement_method': 'CASH'}, {'instrument_id': None},
                   {'deliverables': []}, {'deliverables': [metadata()['deliverables'][0]] * 2}]
        for change in patches:
            self.contracts = {'data': [{**metadata(), **change}]}
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.client.option_quotes([CONTRACT])
        for change in [{'symbol': 'QQQ'}, {'amount': '0'}, {'amount': True}, {'asset_type': 'CASH'},
                       {'instrument_id': '789'}, {'allocation_percentage': '50'},
                       {'settlement_status': 'DELAYED'}, {'settlement_method': 'CASH'}]:
            item = metadata()
            item['deliverables'][0].update(change)
            self.contracts = {'data': [item]}
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.client.option_quotes([CONTRACT])

    def test_put_and_liquidate_only_quotes_are_supported(self):
        contract = CONTRACT.replace('C', 'P')
        self.contracts = {'data': [{**metadata(contract), 'tradable_status': 'CO'}]}
        self.snapshots = [snapshot(contract)]
        self.assertEqual(self.client.option_quotes([contract])['quotes'][0]['right'], 'put')

    def test_snapshot_identity_completeness_and_cent_precision(self):
        for change in [{'symbol': 'QQQ261030C00110000'}, {'instrument_id': '456'},
                       {'strike_price': '109'}, {'bid': '1.501'}, {'ask': '1.501'},
                       {'bid': '-1'}, {'bid': '2'}, {'ask': '0'}, {'bid': 'NaN'}, {'ask': True},
                       {'bid': '1e999999999'}, {'bid': '1.450000000000000000000000000000001'}]:
            self.snapshots = [{**snapshot(), **change}]
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.client.option_quotes([CONTRACT])
        for raw in [[], [snapshot(), snapshot()], {}, [None], [{'symbol': CONTRACT}]]:
            self.snapshots = raw
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.client.option_quotes([CONTRACT])
        self.snapshots = [{**snapshot(), 'bid': '0'}]
        self.assertEqual(self.client.option_quotes([CONTRACT])['quotes'][0]['bid'], '0')

    def test_timestamp_units_staleness_future_and_no_trade_time_fallback(self):
        for value in [None, True, int(NOW.timestamp()), int(NOW.timestamp()*10**6),
                      str(int(NOW.timestamp()*1000)), 1.5, -1]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                epoch_milliseconds(value)
        for seconds in [-1, 61, 900]:
            self.snapshots = [{**snapshot(), 'quote_time': int((NOW-timedelta(seconds=seconds)).timestamp()*1000)}]
            with self.assertRaises(ValueError):
                self.client.option_quotes([CONTRACT])
        self.snapshots = [snapshot()]
        del self.snapshots[0]['quote_time']
        self.snapshots[0]['last_trade_time'] = int(NOW.timestamp()*1000)
        with self.assertRaises(ValueError):
            self.client.option_quotes([CONTRACT])
        self.snapshots = [{**snapshot(), 'quote_time': int((NOW-timedelta(seconds=60)).timestamp()*1000)}]
        self.client.option_quotes([CONTRACT])

    def test_collection_rechecks_freshness_and_session_date(self):
        for finish in [NOW+timedelta(seconds=51), NOW+timedelta(days=1)]:
            with patch.object(self.client, 'clock', side_effect=[NOW, NOW, NOW, finish]):
                with self.assertRaises(ValueError):
                    self.client.option_quotes([CONTRACT])

    def test_contract_pagination_completes_or_rejects(self):
        second = CONTRACT.replace('00110000', '00111000')
        pages = [{'data': [metadata()], 'pagination_key': 'cursor+/='},
                 {'data': [metadata(second, '124')]}]
        self.snapshots = [snapshot(), snapshot(second, '124')]
        original = self.transport
        def paginated(request, timeout):
            if urlsplit(request.full_url).path == CONTRACTS_PATH:
                return io.BytesIO(json.dumps(pages.pop(0)).encode())
            return original(request, timeout)
        self.client.transport = paginated
        self.assertEqual(len(self.client.option_quotes([CONTRACT, second])['quotes']), 2)
        self.client.transport = self.transport
        for raw in [{'data': []}, {'data': None}, {'data': [metadata(), metadata()]},
                    {'data': [None]}, {'data': [metadata()], 'next': 'secret'},
                    {'data': [metadata()], 'pagination_key': True}]:
            self.contracts = raw
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.client.option_quotes([CONTRACT])
        self.contracts = {'data': [], 'pagination_key': 'repeat'}
        with self.assertRaisesRegex(ValueError, 'repeated'):
            self.client.option_quotes([CONTRACT])
        with patch('options_paper.webull.MAX_PAGES', 1):
            with self.assertRaisesRegex(ValueError, 'page limit'):
                self.client.option_quotes([CONTRACT])

    def test_batches_never_exceed_twenty_and_late_failure_returns_no_partial(self):
        contracts = [f'SPY261030C{110000+n*1000:08d}' for n in range(21)]
        sizes = []
        def batched(request, timeout):
            url = urlsplit(request.full_url)
            params = parse_qs(url.query)
            symbols = params['option_symbols' if url.path == CONTRACTS_PATH else 'symbols'][0].split(',')
            sizes.append(len(symbols))
            ids = {s: str(100+contracts.index(s)) for s in symbols}
            raw = {'data': [metadata(s, ids[s]) for s in symbols]} if url.path == CONTRACTS_PATH else [snapshot(s, ids[s]) for s in symbols]
            return io.BytesIO(json.dumps(raw).encode())
        self.client.transport = batched
        result = self.client.option_quotes(contracts)
        self.assertEqual([q['contract'] for q in result['quotes']], contracts)
        self.assertEqual(sizes, [20, 20, 1, 1])
        def failing(request, timeout):
            if contracts[-1] in request.full_url:
                raise URLError('sensitive-secret')
            return batched(request, timeout)
        self.client.transport = failing
        with self.assertRaisesRegex(ValueError, 'connection failed'):
            self.client.option_quotes(contracts)

    def test_only_allowlisted_read_requests_can_be_sent(self):
        for path in ['/trading/orders/place', '/trading/accounts/list', '/auth/tokens/create',
                     'https://evil.example', CONTRACTS_PATH + '/../orders']:
            with self.assertRaisesRegex(ValueError, 'allowlisted'):
                self.client._get(path, {})
        with self.assertRaisesRegex(ValueError, 'allowlisted'):
            self.client._get(CONTRACTS_PATH, {'host': 'evil.example'})
        self.assertEqual(self.calls, [])

    def test_auth_rate_network_redirect_and_json_errors_are_redacted(self):
        for code in [301, 302, 401, 403, 417, 429, 500]:
            with patch.object(self.client, 'transport', side_effect=HTTPError('secret-url', code, 'secret-body', {}, None)):
                with self.assertRaises(ValueError) as error:
                    self.client.option_quotes([CONTRACT])
                self.assertNotIn('secret', str(error.exception))
        for error in [URLError('secret'), TimeoutError('secret'), OSError('secret')]:
            with patch.object(self.client, 'transport', side_effect=error):
                with self.assertRaisesRegex(ValueError, 'connection failed'):
                    self.client.option_quotes([CONTRACT])
        for payload in [b'not json secret', b'{"error_code":"secret"}', b'{"data":[],"data":[]}',
                        b'{"data":NaN}', b'null', b' ' * 2_000_001]:
            with patch.object(self.client, 'transport', return_value=io.BytesIO(payload)):
                with self.assertRaises(ValueError) as error:
                    self.client.option_quotes([CONTRACT])
                self.assertNotIn('secret', str(error.exception))

    def test_missing_credentials_and_control_characters_fail_before_network(self):
        for name in ['WEBULL_APP_KEY', 'WEBULL_APP_SECRET', 'WEBULL_ACCESS_TOKEN']:
            for value in ['', 'bad\nsecret', '\x00secret', 'bad secret']:
                if name == 'WEBULL_ACCESS_TOKEN' and value == '':
                    continue
                with patch('options_paper.webull.os.environ.get', side_effect=lambda key, default='', n=name, v=value: v if key == n else 'test'):
                    with self.assertRaisesRegex(ValueError, name):
                        WebullData()

    def test_optional_access_token_nonce_and_get_signature(self):
        captured = []
        def transport(request, timeout):
            captured.append({k.lower(): v for k, v in request.header_items()})
            return io.BytesIO(b'[]')
        with patch.dict(os.environ, {'WEBULL_ACCESS_TOKEN': ''}):
            client = WebullData(transport=transport, clock=lambda: NOW)
        for _ in range(2):
            client._get(SNAPSHOTS_PATH, {'category': 'US_OPTION', 'symbols': CONTRACT})
        self.assertNotIn('x-access-token', captured[0])
        self.assertNotEqual(captured[0]['x-signature-nonce'], captured[1]['x-signature-nonce'])
        self.assertNotEqual(captured[0]['x-signature'], captured[1]['x-signature'])

    def test_local_rate_budget_is_bounded_without_retrying(self):
        with patch.object(self.client, 'transport', return_value=None) as transport:
            self.client.requests[SNAPSHOTS_PATH].extend([self.client.monotonic()] * 50)
            with self.assertRaisesRegex(ValueError, 'budget'):
                self.client._get(SNAPSHOTS_PATH, {})
            transport.assert_not_called()

    def test_capture_is_immutable_and_does_not_create_accounts_or_prompt(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'observation.json'
            with patch('options_paper.webull.WebullData', return_value=self.client), \
                    patch('builtins.input', side_effect=AssertionError), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--contracts', CONTRACT, '--output', str(output)]), 0)
                original = output.read_bytes()
                self.assertEqual(main(['--contracts', CONTRACT, '--output', str(output)]), 1)
            self.assertEqual(output.read_bytes(), original)
            self.assertEqual([p.name for p in Path(folder).iterdir()], ['observation.json'])
            self.assertNotIn('test-secret', output.read_text())
            self.assertEqual(json.loads(output.read_text())['source'], 'webull')

    def test_capture_error_creates_no_output(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'observation.json'
            self.snapshots = []
            with patch('options_paper.webull.WebullData', return_value=self.client), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--contracts', CONTRACT, '--output', str(output)]), 1)
            self.assertFalse(output.exists())

    def test_paper_refresh_reapproval_and_confirmed_exit_end_to_end(self):
        now = datetime.now(timezone.utc)
        expiry = (now+timedelta(days=30)).date()
        contract = 'SPY' + expiry.strftime('%y%m%d') + 'C00110000'
        self.client.clock = lambda: now
        self.contracts = {'data': [{**metadata(contract), 'expiration_date': expiry.isoformat()}]}
        self.snapshots = [snapshot(contract, now=now, bid='2.30', ask='2.50')]
        source = json.loads((ROOT/'options_paper/sample_snapshot.json').read_text())
        source['as_of'] = (now-timedelta(minutes=1)).isoformat()
        source['options'][0].update(symbol=contract, expiry=expiry.isoformat())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'paper.sqlite3'
            account = Account(path)
            try:
                proposal = propose(source, now=now)
                account.buy(proposal, contract, now=now)
                args = ['--provider', 'webull', '--refresh-quotes', '--account', str(path)]
                with patch('options_paper.cli.WebullData', return_value=self.client), \
                        patch('options_paper.cli.AlpacaData', side_effect=AssertionError), \
                        patch('options_paper.cli.TradierData', side_effect=AssertionError), \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(account_main(args), 0)
                    self.assertEqual(len(account.history()), 1)
                    def change_price(prompt):
                        self.snapshots[0].update(bid='2.40', quote_time=int((now-timedelta(seconds=5)).timestamp()*1000))
                        return contract
                    with patch('builtins.input', side_effect=change_price):
                        self.assertEqual(account_main(args+['--review-exits']), 1)
                    self.assertEqual(len(account.history()), 1)
                    with patch('builtins.input', return_value=contract):
                        self.assertEqual(account_main(args+['--review-exits']), 0)
                self.assertEqual(account.status()['realized_pnl_cents'], 8870)
                self.assertEqual(account.status()['positions'], [])
            finally:
                account.close()

    def test_no_positions_no_provider_and_demo_incompatible(self):
        with tempfile.TemporaryDirectory() as folder, patch('options_paper.cli.WebullData', side_effect=AssertionError), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(account_main(['--provider', 'webull', '--refresh-quotes', '--account', str(Path(folder)/'paper.sqlite3')]), 0)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            account_main(['--demo', '--provider', 'webull', '--refresh-quotes'])


if __name__ == '__main__':
    unittest.main()
