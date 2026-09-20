"""One frozen research hypothesis; does not inspect later validation outcomes."""
import argparse
import csv
import json
import sys
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.engine import Engine, make_config
from bot.market import Candle, validate

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--csv', required=True)
parser.add_argument('--out', default='filter-development.json')
args = parser.parse_args()

def timestamp(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp())

start, end = map(timestamp, ['2024-08-28', '2025-08-20'])
with Path(args.csv).open(encoding='utf-8', newline='') as f:
    bars = [Candle(int(r['time']), *(float(r[k]) for k in ('low','high','open','close','volume')))
            for r in csv.DictReader(f) if int(r['time']) < end]
results = {}
for name, lag in [('unfiltered', 0), ('rising_24h', 24)]:
    cfg = replace(make_config('weekly_breakout'), rising_trend_hours=lag)
    warmup = [c for c in bars if start-cfg.history_size*3600 <= c.time < start]
    sample = [c for c in bars if start <= c.time < end]
    validate(warmup+sample)
    if len(warmup) != cfg.history_size or sample[-1].time != end-3600:
        raise ValueError('Incomplete development data')
    engine = Engine(cfg)
    engine.s.closes = [c.close for c in warmup]
    engine.s.last = start-3600
    trades, halted_at = [], None
    for candle in sample:
        trades.extend(engine.step(candle))
        if engine.s.halted and halted_at is None:
            halted_at = candle.time
    results[name] = {'config': asdict(cfg), 'start': start, 'end_exclusive': end,
                     'summary': engine.report(trades), 'trades': trades, 'halted_at': halted_at}
    print(name, json.dumps(results[name]['summary']))
Path(args.out).write_text(json.dumps(results, indent=2), encoding='utf-8')
