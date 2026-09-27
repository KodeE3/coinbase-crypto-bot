"""Experimental zero-drift log-return model; never an LLM price guess."""
import hashlib
import json
import math
import statistics
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING


def number(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("non-finite number")
    return value


def timestamp(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return dt.timestamp()


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def rules_hash(market):
    # Bind approval to terms that determine the payout, not changing quotes.
    fields = ("ticker", "market_type", "rules_primary", "rules_secondary",
              "strike_type", "floor_strike", "cap_strike", "close_time",
              "expected_expiration_time", "expiration_time", "can_close_early",
              "notional_value_dollars")
    payload = {k: market.get(k) for k in fields}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def probability(candles, strike, horizon_seconds, now):
    """Use only contiguous, completed one-minute Coinbase candles before now."""
    strike, horizon_seconds = number(strike), number(horizon_seconds)
    if strike <= 0 or not 300 <= horizon_seconds <= 86400:
        raise ValueError("unsupported strike or horizon (5 minutes to 24 hours)")
    rows = []
    for row in candles:
        start, close = number(row[0]), number(row[4])
        if close <= 0:
            raise ValueError("non-positive candle price")
        if start + 60 <= now:
            rows.append((start, close))
    rows.sort()
    rows = rows[-240:]
    if len(rows) < 60:
        raise ValueError("need at least 60 completed candles")
    if not 0 <= now - (rows[-1][0] + 60) <= 120:
        raise ValueError("stale candles")
    if any(b[0] - a[0] != 60 for a, b in zip(rows, rows[1:])):
        raise ValueError("missing or duplicate candle intervals")
    returns = [math.log(b[1] / a[1]) for a, b in zip(rows, rows[1:])]
    sigma = statistics.stdev(returns)
    if sigma <= 1e-8:
        raise ValueError("insufficient observed volatility")
    z = math.log(rows[-1][1] / strike) / (sigma * math.sqrt(horizon_seconds / 60))
    p = 0.5 * (1 + math.erf(z / math.sqrt(2)))
    # Deliberately shrink extreme estimates; this is not empirical calibration.
    return min(0.95, max(0.05, 0.5 + 0.8 * (p - 0.5)))


def cents_up(dollars):
    return int((Decimal(str(dollars)) * 100).to_integral_value(rounding=ROUND_CEILING))


def fee_cents(price, quantity, multiplier):
    """Conservative whole-cent rounding, not an exact broker fee replica."""
    p = Decimal(str(price))
    m = Decimal(str(multiplier))
    if not p.is_finite() or not m.is_finite() or not 0 < p < 1 or m < 0:
        raise ValueError("invalid fee inputs")
    if type(quantity) is not int or quantity <= 0:
        raise ValueError("invalid quantity")
    return cents_up(Decimal("0.07") * m * quantity * p * (1 - p))
