"""Transactional, restart-safe simulated ledger. No broker-order interface."""
import json
import sqlite3
from datetime import datetime, timezone

from .model import number


class Account:
    def __init__(self, path, initial_cents=10000):
        if type(initial_cents) is not int or initial_cents <= 0:
            raise ValueError("initial balance must be positive integer cents")
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS balance(
                id INTEGER PRIMARY KEY CHECK(id=1), initial INTEGER, cash INTEGER);
            CREATE TABLE IF NOT EXISTS positions(
                ticker TEXT PRIMARY KEY, event TEXT NOT NULL, side TEXT NOT NULL,
                quantity INTEGER NOT NULL, cost INTEGER NOT NULL,
                entered REAL NOT NULL, closes REAL NOT NULL, probability REAL NOT NULL,
                baseline REAL NOT NULL, snapshot TEXT NOT NULL,
                settled REAL, payout INTEGER, result TEXT);
            CREATE TABLE IF NOT EXISTS audit(
                id INTEGER PRIMARY KEY, at REAL NOT NULL, kind TEXT NOT NULL,
                payload TEXT NOT NULL);
        """)
        self.db.execute("INSERT OR IGNORE INTO balance VALUES(1,?,?)",
                        (initial_cents, initial_cents))

    def close(self):
        self.db.close()

    def log(self, now, kind, payload):
        self.db.execute("INSERT INTO audit(at,kind,payload) VALUES(?,?,?)",
                        (now, kind, json.dumps(payload, sort_keys=True, allow_nan=False)))

    def open_positions(self):
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM positions WHERE settled IS NULL ORDER BY ticker")]

    def enter(self, trade, config, now):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            reason = self._risk(trade, config, now)
            if reason:
                self.log(now, "skip", {"ticker": trade["ticker"], "reason": reason})
                self.db.execute("COMMIT")
                return reason
            self.db.execute("""INSERT INTO positions
                (ticker,event,side,quantity,cost,entered,closes,probability,baseline,snapshot)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (trade["ticker"], trade["event"], trade["side"], trade["quantity"],
                 trade["cost"], now, trade["closes"], trade["probability"],
                 trade["baseline"], json.dumps(trade, sort_keys=True, allow_nan=False)))
            self.db.execute("UPDATE balance SET cash=cash-? WHERE id=1", (trade["cost"],))
            self.log(now, "paper_buy", trade)
            self.db.execute("COMMIT")
            return "paper_buy"
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def _risk(self, trade, cfg, now):
        if self.db.execute("SELECT 1 FROM positions WHERE ticker=?", (trade["ticker"],)).fetchone():
            return "already_traded"
        cash = self.db.execute("SELECT cash FROM balance").fetchone()[0]
        exposure = sum(p["cost"] for p in self.open_positions())
        event_exposure = sum(p["cost"] for p in self.open_positions() if p["event"] == trade["event"])
        day = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        # Sum gross losses, so a win cannot replenish today's risk budget.
        losses = self.db.execute("""SELECT COALESCE(SUM(MAX(cost-payout,0)),0)
            FROM positions WHERE settled>=? AND settled<=?""", (day, now)).fetchone()[0]
        cost = trade["cost"]
        if type(cost) is not int or cost <= 0 or trade["side"] not in ("yes", "no"):
            raise ValueError("invalid trade")
        if cost > cash:
            return "insufficient_cash"
        if cost > cfg["max_trade_cents"]:
            return "trade_limit"
        if exposure + cost > cfg["max_exposure_cents"]:
            return "exposure_limit"
        if event_exposure + cost > cfg["max_event_cents"]:
            return "event_limit"
        if losses + exposure + cost > cfg["daily_loss_cents"]:
            return "daily_loss_budget"
        return None

    def settle(self, market, now):
        """Only an explicitly finalized yes/no result; never infer from BTC spot."""
        if market.get("status") != "finalized" or market.get("result") not in ("yes", "no"):
            return "pending"
        if market.get("is_provisional") is True:
            return "pending"
        if market.get("settlement_value_dollars") is not None:
            expected = 1 if market["result"] == "yes" else 0
            if number(market["settlement_value_dollars"]) != expected:
                raise ValueError("non-binary or inconsistent settlement requires reconciliation")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            p = self.db.execute("SELECT * FROM positions WHERE ticker=?", (market["ticker"],)).fetchone()
            if p is None:
                result = "unknown_position"
            elif p["settled"] is not None:
                if p["result"] != market["result"]:
                    raise ValueError("conflicting settlement requires investigation")
                result = "already_settled"
            elif now < p["closes"]:
                raise ValueError("settlement before configured contract close")
            else:
                payout = p["quantity"] * 100 if p["side"] == market["result"] else 0
                self.db.execute("UPDATE balance SET cash=cash+? WHERE id=1", (payout,))
                self.db.execute("UPDATE positions SET settled=?,payout=?,result=? WHERE ticker=?",
                                (now, payout, market["result"], market["ticker"]))
                self.log(now, "paper_settlement", {"ticker": market["ticker"], "payout_cents": payout,
                                                  "source_market": market})
                result = "paper_settlement"
            self.db.execute("COMMIT")
            return result
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def report(self):
        b = self.db.execute("SELECT * FROM balance").fetchone()
        positions = [dict(p) for p in self.db.execute("SELECT * FROM positions")]
        settled = [p for p in positions if p["settled"] is not None]
        exposure = sum(p["cost"] for p in positions if p["settled"] is None)
        pnl = sum(p["payout"] - p["cost"] for p in settled)
        score = lambda field: (sum((p[field] - (p["result"] == "yes")) ** 2 for p in settled)
                               / len(settled) if settled else None)
        total = peak = drawdown = 0
        for p in sorted(settled, key=lambda p: (p["settled"], p["ticker"])):
            total += p["payout"] - p["cost"]
            peak = max(peak, total)
            drawdown = max(drawdown, peak - total)
        return {"mode": "PAPER_ONLY", "initial_cents": b["initial"], "cash_cents": b["cash"],
                "open_cost_cents": exposure, "equity_at_cost_cents": b["cash"] + exposure,
                "worst_case_equity_cents": b["cash"], "realized_pnl_cents": pnl,
                "trades": len(positions), "settled_trades": len(settled),
                "wins": sum(p["payout"] > p["cost"] for p in settled),
                "realized_max_drawdown_cents": drawdown, "brier_traded_model": score("probability"),
                "brier_traded_market_midpoint": score("baseline"),
                "note": "Cost equity is not mark-to-market. Scores cover traded contracts only; no proven edge."}
