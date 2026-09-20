import uuid
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from bot.engine import Config, Engine
from bot.market import Candle, fetch, validate
from bot.__main__ import paper


def candle(i, price=100, low=None):
    return Candle(i * 3600, price if low is None else low, price, price, price, 10)


class BotTests(unittest.TestCase):
    def engine(self):
        return Engine(Config(fast=1, slow=2))

    def test_no_lookahead(self):
        a, b = self.engine(), self.engine()
        for e in (a, b):
            e.step(candle(0, 100))
            e.step(candle(1, 110))
        x = a.step(Candle(7200, 110, 200, 110, 200, 10))
        y = b.step(candle(2, 110))
        self.assertEqual(x[0], y[0])

    def test_costs_exposure_and_stop(self):
        e = self.engine()
        e.step(candle(0, 100))
        e.step(candle(1, 110))
        trades = e.step(candle(2, 110, 90))
        self.assertEqual([t['side'] for t in trades], ['buy', 'sell'])
        self.assertLessEqual(trades[0]['qty'] * trades[0]['price'] + trades[0]['fee'], 2000)
        self.assertAlmostEqual(e.s.cash, 10000 + trades[1]['pnl'])
        self.assertLessEqual(-trades[1]['pnl'], 50.000001)

    def test_gap_stop_fills_at_open(self):
        e = self.engine()
        for i, p in enumerate([100, 110, 110]):
            e.step(candle(i, p))
        trades = e.step(candle(3, 80))
        self.assertEqual(trades[0]['price'], 80 * .999)

    def test_duplicate_is_noop(self):
        e = self.engine()
        e.step(candle(0))
        before = asdict(e.s)
        self.assertEqual(e.step(candle(0)), [])
        self.assertEqual(asdict(e.s), before)

    def test_bad_data(self):
        for rows in ([candle(0), candle(2)], [candle(0), candle(0)], [candle(0, float('nan'))], [candle(0, 100, 101)]):
            with self.assertRaises(ValueError):
                validate(rows)

    def test_kill_prevents_entry(self):
        e = self.engine()
        e.step(candle(0, 100))
        e.step(candle(1, 110))
        self.assertEqual(e.step(candle(2, 120), kill=True), [])
        self.assertTrue(e.s.halted)

    def test_restart_and_config_guard(self):
        path = str(Path.cwd() / ('test-' + uuid.uuid4().hex + '.sqlite3'))
        try:
            with patch('bot.__main__.time.time', return_value=10 * 3600), patch('bot.__main__.fetch', return_value=[candle(8, 100), candle(9, 110)]):
                paper(path, Config(fast=1, slow=2))
            with patch('bot.__main__.time.time', return_value=11 * 3600), patch('bot.__main__.fetch', return_value=[candle(10, 110)]):
                first = paper(path, Config(fast=1, slow=2))
                second = paper(path, Config(fast=1, slow=2))
                self.assertEqual(first, second)
                self.assertGreater(first['open_btc'], 0)
                with self.assertRaises(ValueError):
                    paper(path, Config())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_daily_and_drawdown_halts(self):
        for field, value in [('day_equity', 11000), ('peak', 12000)]:
            e = self.engine()
            e.step(candle(0, 100))
            e.step(candle(1, 110))
            setattr(e.s, field, value)
            self.assertEqual(e.step(candle(2, 120)), [])
            self.assertTrue(e.s.daily_halted or e.s.halted)

    def test_consecutive_losses_halt(self):
        e = Engine(Config(fast=1, slow=2, max_losses=1))
        e.step(candle(0, 100))
        e.step(candle(1, 110))
        e.step(candle(2, 110, 80))
        self.assertTrue(e.s.halted)
        self.assertEqual(e.step(candle(3, 120)), [])

    def test_pagination_filters_and_sorts(self):
        def response(url):
            from urllib.parse import parse_qs, urlparse
            from datetime import datetime
            q = parse_qs(urlparse(url).query)
            start = int(datetime.fromisoformat(q['start'][0]).timestamp())
            end = int(datetime.fromisoformat(q['end'][0]).timestamp())
            return [[t, 100, 100, 100, 100, 10] for t in range(end, start - 3601, -3600)]
        with patch('bot.market.get_json', side_effect=response), patch('bot.market.time.sleep'):
            rows = fetch(0, 600 * 3600)
            self.assertEqual(len(rows), 600)
            self.assertEqual(rows[-1].time, 599 * 3600)


if __name__ == '__main__':
    unittest.main()
