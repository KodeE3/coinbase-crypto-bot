import json
import sqlite3
import unittest
import uuid
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
from bot.engine import Config, Engine, State, make_config
from bot.market import Candle
from bot.__main__ import paper


def bar(i, close, low=None, high=None, opening=None):
    return Candle(i*3600, close if low is None else low, close if high is None else high,
                  close if opening is None else opening, close, 10)


class StrategyTests(unittest.TestCase):
    def config(self, **kwargs):
        return Config(strategy='breakout', fast=1, slow=3, breakout_window=2, exit_window=2, **kwargs)

    def ready(self, **kwargs):
        e=Engine(self.config(**kwargs))
        for i,p in enumerate([100,101,102]):
            e.step(bar(i,p))
        return e

    def test_breakout_uses_previous_close(self):
        a,b=self.ready(),self.ready()
        x=a.step(bar(3,200,low=102,high=200,opening=102))
        y=b.step(bar(3,102))
        self.assertEqual(x[0],y[0])
        self.assertEqual(x[0]['side'],'buy')

    def test_no_breakout_when_latest_equals_prior_max(self):
        e=Engine(self.config())
        for i,p in enumerate([100,102,102]):e.step(bar(i,p))
        self.assertEqual(e.step(bar(3,103)),[])

    def test_trailing_stop_waits_for_completed_close(self):
        e=self.ready(trailing=True, stop_pct=.1)
        e.step(bar(3,110,low=102,high=120,opening=102))
        initial=e.s.stop
        # Prior close=110 implies stop=99, not 108 from prior intrabar high=120.
        trades=e.step(bar(4,108,low=100,high=150,opening=110))
        self.assertEqual(trades,[])
        self.assertAlmostEqual(e.s.stop,99)
        self.assertGreater(e.s.stop,initial)
        e.step(bar(5,109,low=100,high=109,opening=108))
        self.assertAlmostEqual(e.s.stop,99)  # Never lower it.

    def test_channel_exit_at_next_open(self):
        e=self.ready(stop_pct=.2)
        e.step(bar(3,99,low=99,high=102,opening=102))
        trades=e.step(bar(4,98))
        self.assertEqual(trades[0]['side'],'sell')
        self.assertAlmostEqual(trades[0]['price'],98*.999)

    def test_serialized_state_replays_identically(self):
        a=self.ready(trailing=True)
        a.step(bar(3,105,low=102,high=105,opening=102))
        b=Engine(a.cfg,State(**json.loads(json.dumps(asdict(a.s)))))
        c=bar(4,100,low=98,high=105,opening=105)
        self.assertEqual(a.step(c),b.step(c))
        self.assertEqual(asdict(a.s),asdict(b.s))

    def test_paper_uses_full_breakout_warmup(self):
        path=Path.cwd()/('test-'+uuid.uuid4().hex+'.sqlite3')
        cfg=Config(strategy='breakout',fast=1,slow=2,breakout_window=4,exit_window=2)
        try:
            with patch('bot.__main__.time.time',return_value=10*3600), patch('bot.__main__.fetch',return_value=[bar(i,100+i) for i in range(5,10)]) as fetch:
                paper(str(path),cfg)
                fetch.assert_called_once_with(5*3600,10*3600)
            with sqlite3.connect(path) as db:
                saved=json.loads(db.execute('SELECT data FROM state').fetchone()[0])
            db.close()
            self.assertEqual(len(saved['closes']),5)
        finally:
            path.unlink(missing_ok=True)

    def test_presets_preserve_account_risk_limits(self):
        for name in ['slow_trend','weekly_breakout','weekly_breakout_trailing']:
            cfg=make_config(name)
            for field in ['risk','max_exposure','daily_loss','max_drawdown','max_losses']:
                self.assertEqual(getattr(cfg,field),getattr(Config(),field))

    def test_reject_fractional_lookback(self):
        with self.assertRaises(ValueError):Config(slow=50.5)

    def test_rising_filter_blocks_falling_and_flat_average(self):
        for prices in ([110,110,90,100,105], [100,100,90,95,105]):
            cfg=self.config(rising_trend_hours=2)
            e=Engine(cfg,State(cash=10000,peak=10000,closes=list(prices),last=4*3600))
            self.assertEqual(e.step(bar(5,106)),[])

    def test_rising_filter_uses_only_previous_closes(self):
        cfg=self.config(rising_trend_hours=2)
        a=Engine(cfg,State(cash=10000,peak=10000,closes=[80,85,90,100,105],last=4*3600))
        b=Engine(cfg,State(**asdict(a.s)))
        x=a.step(bar(5,120,low=106,high=120,opening=106))
        y=b.step(bar(5,106))
        self.assertEqual(x[0],y[0])
        self.assertEqual(x[0]['side'],'buy')

    def test_rising_filter_does_not_change_exit_rules(self):
        cfg=self.config(rising_trend_hours=2)
        e=Engine(cfg,State(cash=9000,qty=10,cost=1000,stop=80,peak=10000,
                           closes=[110,110,90,100,105],last=4*3600))
        self.assertEqual(e.step(bar(5,106)),[])
        self.assertEqual(e.s.qty,10)

    def test_rising_filter_warmup_and_validation(self):
        cfg=Config(strategy='breakout',slow=200,rising_trend_hours=24)
        self.assertEqual(cfg.history_size,224)
        for lag in [-1,1.5]:
            with self.assertRaises(ValueError):Config(strategy='breakout',rising_trend_hours=lag)
        with self.assertRaises(ValueError):Config(rising_trend_hours=24)


if __name__=='__main__':unittest.main()
