import copy
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from prediction_paper.account import Account
from prediction_paper.cli import cycle, demo_events, main, record, replay
from prediction_paper.model import fee_cents, probability, rules_hash
from prediction_paper.providers import DataError, NoRedirect, PublicData
from prediction_paper.strategy import candidate, process, validate_config


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.cfg, self.events = demo_events()
        self.snap = copy.deepcopy(self.events[0]["snapshot"])
        self.now = self.events[0]["at"]
        self.account = Account(":memory:")
        self.addCleanup(self.account.close)

    def decide(self, **changes):
        return process(self.account, self.snap, {**self.cfg, **changes}, self.now)

    def test_yes_and_no_choices(self):
        yes, _ = candidate(self.snap, self.cfg, self.now)
        no, _ = candidate(self.events[1]["snapshot"], self.cfg, self.now)
        self.assertEqual((yes["side"], no["side"]), ("yes", "no"))
        self.assertEqual(yes["cost"], 23)
        self.assertGreater(yes["edge_after_buffer"], self.cfg["min_edge"])

    def test_rules_must_be_reviewed_and_unchanged(self):
        self.assertEqual(self.decide(approved_markets={}), "unreviewed_rules")
        self.snap["market"]["rules_secondary"] = "changed payout basis"
        self.assertEqual(self.decide(), "changed_rules")
        self.assertEqual(self.account.report()["trades"], 0)

    def test_quote_guards(self):
        for bid, ask in ((0.1, 0.8), (0.5, 0.4), (0, 0.1), (0.9, 1)):
            with self.subTest(bid=bid, ask=ask):
                self.snap["market"].update(yes_bid_dollars=str(bid), yes_ask_dollars=str(ask))
                self.assertEqual(self.decide(), "invalid_or_wide_quote")

    def test_missing_liquidity_and_no_edge(self):
        self.snap["market"].update(yes_ask_size_fp="0", yes_bid_size_fp="0")
        self.assertEqual(self.decide(), "no_edge_or_depth")
        self.snap["market"].update(yes_ask_size_fp="10", yes_bid_size_fp="10")
        self.assertEqual(self.decide(min_edge=0.9), "no_edge_or_depth")

    def test_stale_future_quote_and_nan(self):
        for received in (self.now - 16, self.now + 1):
            self.snap["received_at"] = received
            self.assertEqual(self.decide(), "stale_snapshot")
        self.snap["received_at"] = self.now
        self.snap["market"]["yes_bid_dollars"] = "NaN"
        self.assertTrue(self.decide().startswith("invalid_data"))

    def test_incomplete_candle_does_not_leak_future(self):
        rows = self.snap["candles"]
        original = probability(rows, 100000, 3600, self.now)
        altered = rows + [[self.now, 0, 0, 0, 10**12, 1]]
        self.assertEqual(original, probability(altered, 100000, 3600, self.now))

    def test_bad_candles_fail_closed(self):
        original = self.snap["candles"]
        variants = [original[:30], original[:-4], original[:20] + original[21:],
                    original + [original[-1]], [[r[0], 0, 0, 0, 1] for r in original]]
        for rows in variants:
            with self.subTest(length=len(rows)):
                self.snap["candles"] = rows
                self.assertTrue(self.decide().startswith("invalid_data"))

    def test_contract_types_expiry_and_kill(self):
        for key, value in (("market_type", "scalar"), ("can_close_early", True),
                           ("strike_type", "between"), ("notional_value_dollars", "2")):
            snap = copy.deepcopy(self.snap)
            snap["market"][key] = value
            cfg = copy.deepcopy(self.cfg)
            cfg["approved_markets"][snap["market"]["ticker"]]["rules_sha256"] = rules_hash(snap["market"])
            self.assertNotEqual(process(self.account, snap, cfg, self.now), "paper_buy")
        self.assertEqual(process(self.account, self.snap, self.cfg, self.now, True), "kill_switch")
        self.assertEqual(process(self.account, self.snap, self.cfg, self.now + 3600), "unsupported_time_window")

    def test_fee_rounding_and_multiplier(self):
        self.assertEqual(fee_cents("0.5", 1, 1), 2)
        self.assertEqual(fee_cents("0.5", 100, 1), 175)
        self.assertEqual(fee_cents("0.5", 1, 2), 4)
        self.assertEqual(fee_cents("0.5", 1, 0), 0)

    def test_config_rejects_dangerous_or_ambiguous_values(self):
        for cfg in ({"quantity": -1}, {"quantity": True}, {"initial_cents": 0},
                    {"slippage": -1}, {"min_edge": float("nan")}, {"mode": "live"}):
            with self.subTest(cfg=cfg), self.assertRaises(ValueError):
                validate_config(cfg)

    def test_balance_and_risk_limits(self):
        for key, reason in (("max_trade_cents", "trade_limit"),
                            ("max_exposure_cents", "exposure_limit"),
                            ("max_event_cents", "event_limit"),
                            ("daily_loss_cents", "daily_loss_budget")):
            with self.subTest(key=key):
                self.assertEqual(self.decide(**{key: 1}), reason)
        self.assertEqual(self.account.report()["cash_cents"], 10000)

    def test_duplicate_and_idempotent_settlement(self):
        self.assertEqual(self.decide(), "paper_buy")
        self.assertEqual(self.decide(), "already_traded")
        self.assertEqual(self.account.report()["cash_cents"], 9977)
        settlement = self.events[2]
        self.assertEqual(self.account.settle(settlement["market"], settlement["at"]), "paper_settlement")
        self.assertEqual(self.account.settle(settlement["market"], settlement["at"]), "already_settled")
        self.assertEqual(self.account.report()["cash_cents"], 10077)
        self.assertEqual(self.decide(), "already_traded")

    def test_pending_early_and_conflicting_settlement(self):
        self.decide()
        m = copy.deepcopy(self.events[2]["market"])
        self.assertEqual(self.account.settle({**m, "status": "closed"}, self.now + 3601), "pending")
        with self.assertRaises(ValueError):
            self.account.settle(m, self.now)
        self.account.settle(m, self.now + 3601)
        with self.assertRaises(ValueError):
            self.account.settle({**m, "result": "no"}, self.now + 3602)
        self.assertEqual(self.account.report()["cash_cents"], 10077)

    def test_persistence_across_process_connections(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "account.sqlite"
            a = Account(p)
            process(a, self.snap, self.cfg, self.now)
            a.close()
            b = Account(p, initial_cents=999999)
            try:
                self.assertEqual(b.report()["cash_cents"], 9977)
                self.assertEqual(process(b, self.snap, self.cfg, self.now), "already_traded")
                self.assertEqual(b.report()["initial_cents"], 10000)
            finally:
                b.close()

    def test_provisional_or_fractional_payout_is_not_guessed(self):
        self.decide()
        m = copy.deepcopy(self.events[2]["market"])
        self.assertEqual(self.account.settle({**m, "is_provisional": True}, self.now + 3601), "pending")
        with self.assertRaises(ValueError):
            self.account.settle({**m, "settlement_value_dollars": "0.5"}, self.now + 3601)
        self.assertEqual(self.account.report()["cash_cents"], 9977)

    def test_daily_gross_loss_and_open_exposure(self):
        self.decide()
        trade, _ = candidate(self.events[1]["snapshot"], self.cfg, self.now)
        self.assertEqual(self.account.enter(trade, {**self.cfg, "daily_loss_cents": 45}, self.now), "daily_loss_budget")
        self.account.settle({**self.events[2]["market"], "result": "no"}, self.now + 3601)
        self.assertEqual(self.account.enter(trade, {**self.cfg, "daily_loss_cents": 45}, self.now + 3602), "daily_loss_budget")

    def test_transaction_rolls_back_on_write_failure(self):
        with patch.object(self.account, "log", side_effect=RuntimeError("disk failure")):
            with self.assertRaises(RuntimeError):
                self.decide()
        self.assertEqual(self.account.report()["cash_cents"], 10000)
        self.assertEqual(self.account.report()["trades"], 0)


class ReplayTests(unittest.TestCase):
    def test_full_cycle_and_holdout_cutoff(self):
        cfg, events = demo_events()
        with tempfile.TemporaryDirectory() as d:
            tape = Path(d) / "events.jsonl"
            for event in events:
                record(tape, event)
            result = replay(tape, cfg, events[0]["at"])
            self.assertEqual(result["settled_trades"], 2)
            self.assertEqual(result["wins"], 1)
            self.assertEqual(result["realized_pnl_cents"], 54)
            self.assertEqual(result["cash_cents"], 10054)
            self.assertEqual(result["realized_max_drawdown_cents"], 23)
            self.assertEqual(replay(tape, cfg, events[0]["at"] + 1)["trades"], 0)

    def test_out_of_order_rejected(self):
        cfg, events = demo_events()
        with tempfile.TemporaryDirectory() as d:
            tape = Path(d) / "events.jsonl"
            for event in reversed(events):
                record(tape, event)
            with self.assertRaises(ValueError):
                replay(tape, cfg, events[0]["at"])

    def test_cli_demo_runs_without_network(self):
        with patch("prediction_paper.cli.PublicData", side_effect=AssertionError("network")), patch("builtins.print"):
            self.assertEqual(main(["demo"]), 0)


class Response(BytesIO):
    status = 200
    headers = {}


class FakeOpener:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.requests = []

    def open(self, req, timeout):
        self.requests.append((req, timeout))
        payload = next(self.payloads)
        if isinstance(payload, Exception):
            raise payload
        return Response(json.dumps(payload).encode())


class ProviderTests(unittest.TestCase):
    def test_pagination_get_only_no_credentials(self):
        op = FakeOpener([{"markets": [{"ticker": "A"}], "cursor": "next"},
                         {"markets": [{"ticker": "B"}], "cursor": ""}])
        rows = PublicData(op).markets("KXBTCD")
        self.assertEqual(len(rows), 2)
        for req, timeout in op.requests:
            self.assertEqual(req.get_method(), "GET")
            self.assertIsNone(req.data)
            self.assertEqual(timeout, 10)
            self.assertFalse(any("key" in k.lower() or "authorization" in k.lower() for k in req.headers))

    def test_repeated_cursor_and_http_errors_fail_closed(self):
        cases = [[{"markets": [], "cursor": "x"}] * 2,
                 [HTTPError("https://example.com", 429, "slow", {}, None)],
                 [URLError("offline")], [{"error": "bad schema"}]]
        for payloads in cases:
            with self.subTest(payloads=str(payloads)), self.assertRaises(DataError):
                PublicData(FakeOpener(payloads)).markets("KXBTCD")

    def test_reject_redirect_and_ticker_injection(self):
        with self.assertRaises(DataError):
            NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.test")
        with self.assertRaises(DataError):
            PublicData(FakeOpener([])).market("../portfolio/orders")

    def test_malformed_and_oversized_response(self):
        for body in (b"not json", b"x" * 2_000_001):
            with patch.object(FakeOpener, "open", return_value=Response(body)):
                with self.assertRaises(DataError):
                    PublicData(FakeOpener([])).candles()

    def test_live_cycle_collects_and_restarts_without_duplicate(self):
        cfg, events = demo_events()
        snap = events[0]["snapshot"]
        class Provider:
            def markets(self, series): return [snap["market"]]
            def market(self, ticker): return snap["market"]
            def candles(self): return snap["candles"]
        with tempfile.TemporaryDirectory() as d:
            account = Account(Path(d) / "account.sqlite")
            try:
                with patch("prediction_paper.cli.time.time", return_value=events[0]["at"]):
                    first = cycle(Provider(), account, cfg, Path(d)/"events.jsonl", Path(d)/"STOP")
                    second = cycle(Provider(), account, cfg, Path(d)/"events.jsonl", Path(d)/"STOP")
                self.assertEqual(first, {"paper_buy": 1})
                self.assertEqual(second, {"already_traded": 1})
                Path(d, "STOP").touch()
                self.assertEqual(cycle(Provider(), account, cfg, Path(d)/"events.jsonl", Path(d)/"STOP"), {"kill_switch": 1})
            finally:
                account.close()


if __name__ == "__main__":
    unittest.main()
