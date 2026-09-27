"""Fail-closed eligibility and fee-aware paper entry selection."""
from decimal import Decimal

from .model import cents_up, fee_cents, number, probability, rules_hash, timestamp

DEFAULTS = {
    "initial_cents": 10000, "quantity": 1, "max_trade_cents": 200,
    "max_exposure_cents": 1000, "max_event_cents": 200, "daily_loss_cents": 500,
    "min_edge": 0.05, "uncertainty_buffer": 0.05, "slippage": 0.01,
    "max_spread": 0.08, "series": "KXBTCD", "approved_markets": {},
}


def validate_config(config):
    if set(config) - set(DEFAULTS):
        raise ValueError("unknown config setting")
    cfg = {**DEFAULTS, **config}
    for k in ("initial_cents", "quantity", "max_trade_cents", "max_exposure_cents",
              "max_event_cents", "daily_loss_cents"):
        if type(cfg[k]) is not int or cfg[k] <= 0:
            raise ValueError(f"{k} must be a positive integer")
    if cfg["quantity"] > 100:
        raise ValueError("quantity exceeds paper research cap")
    for k in ("min_edge", "uncertainty_buffer", "slippage", "max_spread"):
        if not 0 <= number(cfg[k]) < 1:
            raise ValueError(f"invalid {k}")
    if not isinstance(cfg["series"], str) or not cfg["series"].isalnum():
        raise ValueError("invalid series")
    if not isinstance(cfg["approved_markets"], dict):
        raise ValueError("approved_markets must be an object")
    for ticker, approval in cfg["approved_markets"].items():
        if not isinstance(ticker, str) or not isinstance(approval, dict):
            raise ValueError("invalid market approval")
        if set(approval) != {"rules_sha256", "observation_time", "fee_multiplier", "accept_btc_proxy"}:
            raise ValueError("approval needs rules hash, observation time, fee multiplier and proxy acceptance")
        if approval["accept_btc_proxy"] is not True:
            raise ValueError("BTC proxy limitation must be acknowledged")
        if not isinstance(approval["rules_sha256"], str) or len(approval["rules_sha256"]) != 64:
            raise ValueError("invalid rules hash")
        timestamp(approval["observation_time"])
        if not 0 <= number(approval["fee_multiplier"]) <= 100:
            raise ValueError("invalid fee multiplier")
    return cfg


def candidate(snapshot, cfg, now):
    market = snapshot["market"]
    ticker = market["ticker"]
    if not ticker.startswith(cfg["series"] + "-"):
        return None, "wrong_series"
    approval = cfg["approved_markets"].get(ticker)
    if not approval:
        return None, "unreviewed_rules"
    if approval["rules_sha256"] != rules_hash(market):
        return None, "changed_rules"
    if market.get("status") != "active" or market.get("market_type") != "binary":
        return None, "not_active_binary"
    if (market.get("strike_type") not in ("greater", "greater_or_equal")
            or market.get("can_close_early") is not False
            or number(market.get("notional_value_dollars", 0)) != 1
            or market.get("mve_collection_ticker")
            or market.get("is_provisional") is True):
        return None, "unsupported_contract"
    closes = timestamp(market["close_time"])
    observes = timestamp(approval["observation_time"])
    # This first model handles a single terminal threshold only, not path/range contracts.
    if observes != closes or not 300 <= closes - now <= 86400:
        return None, "unsupported_time_window"
    if not 0 <= now - number(snapshot["received_at"]) <= 15:
        return None, "stale_snapshot"
    p = probability(snapshot["candles"], market["floor_strike"], observes - now, now)
    bid = number(market["yes_bid_dollars"])
    ask = number(market["yes_ask_dollars"])
    if not 0 < bid <= ask < 1 or ask - bid > cfg["max_spread"]:
        return None, "invalid_or_wide_quote"
    q = cfg["quantity"]
    choices = []
    for side, chance, price, size in (
        ("yes", p, ask, market.get("yes_ask_size_fp", 0)),
        ("no", 1 - p, Decimal("1") - Decimal(str(bid)), market.get("yes_bid_size_fp", 0)),
    ):
        if number(size) < q:
            continue
        fill = Decimal(str(price)) + Decimal(str(cfg["slippage"]))
        if fill >= 1:
            continue
        fees = fee_cents(fill, q, approval["fee_multiplier"])
        cost = cents_up(fill * q) + fees
        edge = chance - cost / (100 * q) - cfg["uncertainty_buffer"]
        if edge >= cfg["min_edge"]:
            choices.append({"ticker": ticker, "event": market["event_ticker"], "side": side,
                            "quantity": q, "cost": cost, "fee_cents": fees,
                            "fill_price": str(fill), "edge_after_buffer": edge,
                            "probability": p, "baseline": (bid + ask) / 2,
                            "closes": closes, "snapshot": snapshot,
                            "assumptions": cfg, "model": "btc-lognormal-v1"})
    if not choices:
        return None, "no_edge_or_depth"
    return max(choices, key=lambda x: x["edge_after_buffer"]), None


def process(account, snapshot, cfg, now, stopped=False):
    if stopped:
        account.log(now, "skip", {"reason": "kill_switch"})
        return "kill_switch"
    try:
        trade, reason = candidate(snapshot, cfg, now)
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        reason, trade = "invalid_data:" + type(exc).__name__, None
    if trade is None:
        account.log(now, "skip", {"ticker": snapshot.get("market", {}).get("ticker"), "reason": reason})
        return reason
    return account.enter(trade, cfg, now)
