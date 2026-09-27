"""Run with python -m prediction_paper.cli demo."""
import argparse
import json
import math
import tempfile
import time
from pathlib import Path

from .account import Account
from .model import iso, rules_hash, timestamp
from .providers import DataError, PublicData
from .strategy import process, validate_config


def emit(value):
    print(json.dumps(value, sort_keys=True, allow_nan=False), flush=True)


def record(path, event):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True, allow_nan=False) + "\n")


def cycle(provider, account, cfg, tape, stop):
    # Observe final outcomes first. Failures abort new entries for this cycle.
    for p in account.open_positions():
        market = provider.market(p["ticker"])
        now = time.time()
        if market.get("status") == "finalized":
            event = {"kind": "settlement", "at": now, "market": market}
            record(tape, event)
            account.settle(market, now)
    if Path(stop).exists():
        account.log(time.time(), "skip", {"reason": "kill_switch"})
        return {"kill_switch": 1}
    markets = provider.markets(cfg["series"])
    candles = provider.candles()
    decisions = {}
    for listed in markets:
        if Path(stop).exists():
            break
        # Refresh each eligible market rather than executing against list-page quotes.
        market = provider.market(listed["ticker"]) if listed["ticker"] in cfg["approved_markets"] else listed
        now = time.time()
        snapshot = {"market": market, "candles": candles, "received_at": now,
                    "source": "public-rest-receipt-time"}
        record(tape, {"kind": "snapshot", "at": now, "snapshot": snapshot})
        result = process(account, snapshot, cfg, now, Path(stop).exists())
        decisions[result] = decisions.get(result, 0) + 1
    return decisions


def replay(path, cfg, since):
    """Replay receipt-ordered events with the same entry/risk/settlement code."""
    account = Account(":memory:", cfg["initial_cents"])
    previous = float("-inf")
    seen = 0
    try:
        with Path(path).open(encoding="utf-8") as f:
            for line in f:
                event = json.loads(line)
                now = float(event["at"])
                if not math.isfinite(now) or now < previous:
                    raise ValueError("replay must be chronologically ordered")
                previous = now
                if event["kind"] not in ("snapshot", "settlement"):
                    raise ValueError("unknown replay event")
                if now < since:
                    continue
                seen += 1
                if event["kind"] == "snapshot":
                    process(account, event["snapshot"], cfg, now)
                else:
                    account.settle(event["market"], now)
        return {**account.report(), "events_replayed": seen, "evaluation_since": iso(since),
                "validation": "Chronological replay only; freeze settings before collecting holdout data."}
    finally:
        account.close()


def demo_events():
    now = 1800000000.0
    # Synthetic history and deliberately mispriced contracts exercise both sides and losses.
    candles = [[now - 60 * (80 - i), 0, 0, 0, 100000 * math.exp(0.0008 * math.sin(i)), 1]
               for i in range(80)]
    cfg = validate_config({"series": "DEMO"})
    events = []
    for i, (bid, ask, outcome) in enumerate(((0.18, 0.20, "yes"), (0.80, 0.82, "yes"))):
        market = {"ticker": f"DEMO-{i}", "event_ticker": f"DEMO-EVENT-{i}",
                  "market_type": "binary", "status": "active", "strike_type": "greater",
                  "floor_strike": 100000, "close_time": iso(now + 3600),
                  "notional_value_dollars": "1.0000", "can_close_early": False,
                  "rules_primary": "FICTIONAL BTC terminal price above threshold.",
                  "rules_secondary": "Offline synthetic test, not an exchange listing.",
                  "yes_bid_dollars": str(bid), "yes_ask_dollars": str(ask),
                  "yes_bid_size_fp": "10.00", "yes_ask_size_fp": "10.00"}
        cfg["approved_markets"][market["ticker"]] = {
            "rules_sha256": rules_hash(market), "observation_time": market["close_time"],
            "fee_multiplier": 1, "accept_btc_proxy": True}
        events.append({"kind": "snapshot", "at": now,
                       "snapshot": {"market": market, "candles": candles, "received_at": now,
                                    "source": "SYNTHETIC_DEMO"}})
        events.append({"kind": "settlement", "at": now + 3601,
                       "market": {"ticker": market["ticker"], "status": "finalized", "result": outcome}})
    return cfg, sorted(events, key=lambda e: e["at"])


def main(argv=None):
    parser = argparse.ArgumentParser(description="BTC prediction research bot — PAPER ONLY")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("demo", help="offline synthetic buy/settle/replay, no credentials")
    scan = subs.add_parser("scan", help="show public markets and rule-review hashes")
    scan.add_argument("--series", default="KXBTCD")
    run = subs.add_parser("run", help="collect live data and simulate approved contracts")
    run.add_argument("--config", default="prediction-config.json")
    run.add_argument("--db", default="data/paper.sqlite")
    run.add_argument("--tape", default="data/events.jsonl")
    run.add_argument("--stop-file", default="STOP_PREDICTION_BOT")
    run.add_argument("--cycles", type=int, default=1, help="0 runs until stopped")
    run.add_argument("--interval", type=int, default=60)
    report = subs.add_parser("report", help="read the simulated account report")
    report.add_argument("--db", default="data/paper.sqlite")
    rep = subs.add_parser("replay", help="evaluate a recorded chronological holdout")
    rep.add_argument("tape")
    rep.add_argument("--config", default="prediction-config.json")
    rep.add_argument("--since", required=True, help="ISO timestamp with timezone; held-out start")
    args = parser.parse_args(argv)
    account = None
    try:
        if args.command == "demo":
            cfg, events = demo_events()
            with tempfile.TemporaryDirectory() as d:
                tape = Path(d) / "demo.jsonl"
                for event in events:
                    record(tape, event)
                emit({**replay(tape, cfg, events[0]["at"]), "data": "SYNTHETIC — NOT HISTORICAL RETURNS"})
        elif args.command == "scan":
            markets = PublicData().markets(args.series)
            emit({"mode": "READ_ONLY", "series": args.series, "markets": [
                {"market": m, "rules_sha256": rules_hash(m)} for m in markets]})
        elif args.command == "report":
            if not Path(args.db).is_file():
                raise ValueError("account does not exist; run the bot first")
            account = Account(args.db)
            emit(account.report())
        else:
            cfg = validate_config(json.loads(Path(args.config).read_text(encoding="utf-8")))
            if args.command == "replay":
                emit(replay(args.tape, cfg, timestamp(args.since)))
            else:
                if args.cycles < 0 or args.interval < 60:
                    raise ValueError("cycles must be >=0 and interval >=60 seconds")
                Path(args.db).parent.mkdir(parents=True, exist_ok=True)
                account = Account(args.db, cfg["initial_cents"])
                provider, count, failures = PublicData(), 0, 0
                while args.cycles == 0 or count < args.cycles:
                    count += 1
                    try:
                        decisions = cycle(provider, account, cfg, args.tape, args.stop_file)
                        failures = 0
                        emit({"cycle": count, "decisions": decisions, "account": account.report()})
                    except (DataError, ValueError, KeyError, TypeError, IndexError) as exc:
                        failures += 1
                        account.log(time.time(), "cycle_error", {"type": type(exc).__name__})
                        emit({"cycle": count, "error": str(exc), "consecutive_failures": failures})
                        if failures >= 3 or args.cycles == 1:
                            return 1
                    if args.cycles == 0 or count < args.cycles:
                        time.sleep(min(args.interval * 2 ** failures, 600))
                if failures:
                    return 1
        return 0
    except (DataError, ValueError, KeyError, TypeError, OSError) as exc:
        emit({"error": str(exc), "mode": "PAPER_ONLY"})
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        if account is not None:
            account.close()


if __name__ == "__main__":
    raise SystemExit(main())
