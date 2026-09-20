import argparse
import json
import sqlite3
import time
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from .engine import Config, Engine, State
from .market import fetch, read_csv, write_csv


def paper(path, cfg, kill=False):
    # One transaction includes state and fills. Concurrent writers fail closed.
    with closing(sqlite3.connect(path, timeout=1)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), config TEXT, data TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, data TEXT)')
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT config, data FROM state WHERE id=1').fetchone()
        encoded = json.dumps(asdict(cfg), sort_keys=True)
        if row and row[0] != encoded:
            raise ValueError('Configuration differs from saved session; use a new database')
        engine = Engine(cfg, State(**json.loads(row[1])) if row else None)
        end = int(time.time()) // 3600 * 3600
        start = engine.s.last + 3600 if row else end - cfg.slow * 3600
        if row and end - start > 72 * 3600:
            raise ValueError('Session is over 72 hours behind; inspect it before starting a new session')
        if kill:
            engine.s.halted = True
        if start < end:
            candles = fetch(start, end)
            if not row:
                # Warm up indicators without inventing historic startup trades.
                engine.s.closes = [c.close for c in candles][-cfg.slow:]
                engine.s.last = candles[-1].time
            else:
                for candle in candles:
                    for event in engine.step(candle, kill):
                        db.execute('INSERT INTO events(data) VALUES (?)', (json.dumps(event),))
        db.execute('INSERT OR REPLACE INTO state VALUES (1, ?, ?)', (encoded, json.dumps(asdict(engine.s))))
        events = [json.loads(r[0]) for r in db.execute('SELECT data FROM events ORDER BY id')]
        return engine.report(events)


def main():
    parser = argparse.ArgumentParser(description='BTC-USD hourly research and paper simulation only')
    sub = parser.add_subparsers(dest='command', required=True)
    f = sub.add_parser('fetch', help='Save completed Coinbase hourly candles')
    f.add_argument('--days', type=int, default=30)
    f.add_argument('--out', default='candles.csv')
    b = sub.add_parser('backtest', help='Simulate a CSV history')
    b.add_argument('--csv', required=True)
    b.add_argument('--out', default='backtest.json')
    p = sub.add_parser('paper', help='Update a persistent paper session')
    p.add_argument('--db', default='paper.sqlite3')
    p.add_argument('--watch', action='store_true')
    p.add_argument('--kill-file', default='STOP')
    for command in (b, p):
        command.add_argument('--fee', type=float, default=0.006, help='Assumed fee per side, e.g. 0.006 = 0.6%%')
        command.add_argument('--slippage', type=float, default=0.001)
    args = parser.parse_args()
    try:
        if args.command == 'fetch':
            if not 1 <= args.days <= 3650:
                raise ValueError('days must be between 1 and 3650')
            end = int(time.time()) // 3600 * 3600
            candles = fetch(end - args.days * 86400, end)
            write_csv(args.out, candles)
            print(f'Saved {len(candles)} completed BTC-USD hourly candles to {args.out}')
        elif args.command == 'backtest':
            cfg = Config(fee=args.fee, slippage=args.slippage)
            candles = read_csv(args.csv)
            if len(candles) <= cfg.slow:
                raise ValueError('Need more than 50 hourly candles for this strategy')
            engine, events = Engine(cfg), []
            for candle in candles:
                events.extend(engine.step(candle))
            report = engine.report(events)
            Path(args.out).write_text(json.dumps({'config': asdict(cfg), 'summary': report, 'trades': events}, indent=2), encoding='utf-8')
            print(json.dumps(report, indent=2))
        else:
            cfg = Config(fee=args.fee, slippage=args.slippage)
            while True:
                print(json.dumps(paper(args.db, cfg, Path(args.kill_file).exists()), indent=2), flush=True)
                if not args.watch:
                    break
                # One update each UTC hour, after a publication grace period.
                time.sleep(3600 - time.time() % 3600 + 30)
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f'Bot stopped: {exc}\n')
    except KeyboardInterrupt:
        print('Paper monitor stopped. Session saved after its last successful update.')


if __name__ == '__main__':
    main()
